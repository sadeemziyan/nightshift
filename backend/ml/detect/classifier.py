"""M3: a gradient-boosted classifier that says normal / pipeline_leak / pump_degradation / pump_failure with a probability.

    python -m backend.ml.detect.classifier --train [folder] [--with-real]     # writes models/m3.joblib

Inputs are the M1/M2 features in features.py (healthy spreads and hours, never bpd or psi), so the same model reads a
pump it has never seen. Training data:
  * simulated faults (simulate.py): labelled by construction, no answer key needed. This is the headline recipe.
  * optionally real labelled windows from a practice folder's answer_key.json (--with-real). EOG confirmed offline
    training on those labels is allowed. THIS FILE IS ONE OF THE FEW THAT MAY READ answer_key.json (CLAUDE.md hard rule 2):
    training and evaluation only. The app never imports `real_label_rows`; it loads the saved model through blend.py.

The model is HistGradientBoostingClassifier (scikit-learn's gradient-boosted trees) plus a temperature fitted on groups the
trees did not train on, so a printed "90%" should mean about 90% of such calls are right (evaluate.py checks this).
Validate it with evaluate.py (leave one system out), never with a time split (CLAUDE.md hard rule 8).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from backend.engine.loader import Dataset, load

from . import baseline, simulate
from .features import FEATURES, as_matrix, window_features
from .m3_core import CLASSES, predict_proba, sharpen, to_class_order  # noqa: F401  (predict_proba is re-exported)

ROOT = Path(__file__).resolve().parents[3]
MODEL_PATH = ROOT / "models" / "m3.joblib"
REAL_HOURS = tuple(0.5 * k for k in range(1, 25))      # decision times after onset used for real labelled windows
SEED = 0


def _new_trees(seed: int = SEED):
    from sklearn.ensemble import HistGradientBoostingClassifier
    return HistGradientBoostingClassifier(max_depth=4, max_iter=120, learning_rate=0.08, l2_regularization=1.0,
                                          random_state=seed)


def _fit_temperature(p: np.ndarray, y_idx: np.ndarray) -> float:
    from scipy.optimize import minimize_scalar

    def nll(t):
        q = sharpen(p, t)
        return float(-np.log(np.clip(q[np.arange(len(y_idx)), y_idx], 1e-9, 1.0)).mean())

    return float(minimize_scalar(nll, bounds=(0.3, 10.0), method="bounded").x)


def _group_folds(groups: np.ndarray, k: int, seed: int):
    """Random k-fold split that keeps every group (all windows of one fault) in one fold. Groups are shuffled first:
    an unshuffled split can drop a whole fault type into a single fold, so the trees never see it in training."""
    order = np.random.default_rng(seed).permutation(np.unique(groups))
    fold_of = {g: i % k for i, g in enumerate(order)}
    f = np.array([fold_of[g] for g in groups])
    for i in range(k):
        yield np.where(f != i)[0], np.where(f == i)[0]


def fit_classifier(rows: list[dict], seed: int = SEED, calibrate: bool = True) -> dict:
    """rows: dicts with "x" (features), "y" (label) and "group" (windows from one fault share a group).
    Returns {"model", "classes", "features", "temperature", "n_rows", "calibrated"} (plain objects, saved with joblib).

    Calibration: trees are trained on 2/3 of the groups and asked about the other 1/3, three times over; one temperature
    is fitted so those out-of-group probabilities match how often the calls were right. The final trees then use all rows."""
    X = as_matrix([r["x"] for r in rows])
    y = np.array([r["y"] for r in rows])
    y_idx = np.array([CLASSES.index(v) for v in y])
    groups = np.array([r.get("group", i) for i, r in enumerate(rows)])
    temperature, calibrated = 1.0, False
    if calibrate and len(set(groups)) >= 6:
        try:
            oof = np.zeros((len(rows), len(CLASSES)))
            for tr, te in _group_folds(groups, 3, seed):
                m = _new_trees(seed).fit(X[tr], y[tr])
                oof[te] = to_class_order(m.predict_proba(X[te]), m.classes_)
            temperature, calibrated = _fit_temperature(oof, y_idx), True
        except Exception:                                   # calibration is a bonus; the trees alone still work
            temperature, calibrated = 1.0, False
    model = _new_trees(seed).fit(X, y)
    return {"model": model, "classes": [str(c) for c in model.classes_], "features": list(FEATURES),
            "temperature": temperature, "n_rows": int(len(rows)), "calibrated": calibrated}


# ---------------------------------------------------------------- real labelled windows (offline only)
def real_label_rows(folder, ds: Dataset, models: dict, systems: list[str] | None = None,
                    hours=REAL_HOURS, normal_every_h: float = 6.0, burn_in_h: float = 6.0, margin_h: float = 6.0) -> list[dict]:
    """Labelled windows from a practice folder's answer key: for each labelled event, decision times at onset + h while the
    event is in progress (label = its category), plus normal windows at least margin_h from any event at that facility.
    Each row also carries "t", "system", "event" and "hours" so evaluate.py can score by time since onset."""
    key = json.loads((Path(folder) / "answer_key.json").read_text())
    frames: dict = {}

    def frame(fid):
        if fid not in frames:
            frames[fid] = baseline.residuals(ds, fid, ds.now_unix, models)
        return frames[fid]

    rows: list[dict] = []
    busy: dict[str, list[tuple[int, int]]] = {}
    for e in key:
        fid = ds.facility_of(e["asset"])
        sysid = ds.facility(fid)["system_id"]
        end = e["end_unix"] if e.get("end_unix") is not None else ds.now_unix
        busy.setdefault(fid, []).append((e["onset_unix"], end))
        if systems is not None and sysid not in systems:
            continue
        for h in hours:
            t = e["onset_unix"] + int(h * 3600)
            if t > min(end, ds.now_unix):
                break
            x = window_features(frame(fid), t, ds.interval_s)
            if x:
                rows.append({"x": x, "y": e["category"], "group": e["id"], "hours": float(h), "t": t,
                             "system": sysid, "facility": fid, "event": e["id"]})
    start = int(min(s.index[0] for s in ds._series.values() if len(s))) + int(burn_in_h * 3600)
    step = int(normal_every_h * 3600)
    margin = int(margin_h * 3600)
    for fid, fac in ds.facilities.items():
        if systems is not None and fac["system_id"] not in systems:
            continue
        for t in range(start, ds.now_unix, step):
            if any(lo - margin <= t <= hi + margin for lo, hi in busy.get(fid, [])):
                continue
            x = window_features(frame(fid), t, ds.interval_s)
            if x:
                rows.append({"x": x, "y": simulate.NORMAL, "group": f"normal:{fid}:{t}", "hours": None, "t": t,
                             "system": fac["system_id"], "facility": fid, "event": None})
    return rows


# ---------------------------------------------------------------- training script
def train_final(folder: str, with_real: bool = False, n_cases: int = 600, seed: int = SEED) -> dict:
    import joblib

    ds = load(folder)
    models = baseline.fit(ds)
    rng = np.random.default_rng(seed)
    spans = simulate.healthy_spans(ds)
    rows = simulate.training_rows(ds, models, simulate.sample_cases(ds, n_cases, rng, spans=spans), rng, spans=spans)
    sources = {"simulated_rows": len(rows), "real_rows": 0}
    if with_real:
        real = real_label_rows(folder, ds, models)
        rows += real
        sources["real_rows"] = len(real)
    bundle = fit_classifier(rows, seed=seed)
    bundle["trained_on"] = {"folder": Path(folder).name, **sources, "with_real_labels": with_real,
                            "trained_unix": int(datetime.now(timezone.utc).timestamp())}
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, MODEL_PATH, compress=3)
    print(f"saved {MODEL_PATH.relative_to(ROOT)} ({MODEL_PATH.stat().st_size / 1024:.0f} KB), "
          f"{bundle['n_rows']} rows, calibrated={bundle['calibrated']}, trained_on={bundle['trained_on']}")
    return bundle


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--train" in sys.argv:
        train_final(args[0] if args else str(ROOT / "data" / "full_week"), with_real="--with-real" in sys.argv)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
