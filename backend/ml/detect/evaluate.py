"""OFFLINE evaluation of M3 against EOG's answer key, leaving one whole system out. Writes docs/model_eval.json.

    python -m backend.ml.detect.evaluate [dataset_folder] [--quick]

One of the few scripts allowed to read answer_key.json (CLAUDE.md hard rule 2). Every accuracy number in the project
comes from this script's output, never typed by hand (hard rule 8).

How it is scored. For each practice system S in the folder (S1..S5): train on the OTHER four systems, test on S, whose
equipment the model has never seen, then pool the five test sets. Three ways to train are compared:
  sim       simulated faults only (simulate.py) - never touches the answer key. THIS IS THE HEADLINE "models" ROW.
  real      real labelled windows from the four training systems only
  sim+real  both
Rules (the engine's own detector) and an ensemble (either one flagging a problem is enough, see either_flags) are scored
on the same windows.
The test windows are decision times at onset + 0.5 h, 1 h, 1.5 h ... for every labelled event while it is in progress
(the correct answer is its category), plus normal times far from any event (the correct answer is "normal").
  recall            share of events whose category was called correctly at some decision time while it was in progress
  mean_minutes_late average of (first correct call - true onset), on the 30-minute decision grid
  precision         of all windows called a problem, the share where the called category was right
  false_alarm_rate  share of normal windows called a problem
"""
from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

from backend.engine import detect as rules
from backend.engine.loader import load

from . import baseline, simulate
from .classifier import CLASSES, fit_classifier, predict_proba, real_label_rows

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "docs" / "model_eval.json"
HOUR_BUCKETS = [(0, 1), (1, 2), (2, 4), (4, 8), (8, 13)]
HEADLINE = "sim"
N_CASES = 500


def _onehot(labels: list[str]) -> np.ndarray:
    p = np.zeros((len(labels), len(CLASSES)))
    for i, c in enumerate(labels):
        p[i, CLASSES.index(c)] = 1.0
    return p


def either_flags(p_rules: np.ndarray, p_model: np.ndarray) -> np.ndarray:
    """Ensemble: a problem class gets 1 - (1 - rules)(1 - model), "normal" needs both to say normal. So whenever the rules
    fire their call stands, and when only the model is confident it can raise the alarm earlier."""
    out = 1.0 - (1.0 - p_rules) * (1.0 - p_model)
    out[:, 0] = p_rules[:, 0] * p_model[:, 0]
    return out / out.sum(axis=1, keepdims=True)


def rules_labels(ds, rows: list[dict]) -> list[str]:
    """What the rule-based detector says at each window: the category of an ongoing event at that facility, else normal."""
    cache: dict = {}
    out = []
    for r in rows:
        ev = cache.get(r["t"])
        if ev is None:
            ev = cache[r["t"]] = rules.detect(ds, r["t"])
        mine = [e for e in ev if e["facility_id"] == r["facility"] and e["status"] == "ongoing"]
        out.append(max(mine, key=lambda e: e["onset_unix"])["category"] if mine else simulate.NORMAL)
    return out


def score(rows: list[dict], P: np.ndarray) -> dict:
    """Metrics for one method on one set of test windows (rows) given its probabilities P (n, 4)."""
    pred = [CLASSES[i] for i in P.argmax(axis=1)]
    y = [r["y"] for r in rows]
    called = [i for i, p in enumerate(pred) if p != simulate.NORMAL]
    normal = [i for i, t in enumerate(y) if t == simulate.NORMAL]
    by_event: dict = defaultdict(list)
    for i, r in enumerate(rows):
        if r["event"]:
            by_event[r["event"]].append(i)
    found, late, per_cat = 0, [], defaultdict(lambda: {"events": 0, "found": 0, "late": []})
    for ev, idx in by_event.items():
        idx = sorted(idx, key=lambda i: rows[i]["hours"])
        cat = rows[idx[0]]["y"]
        per_cat[cat]["events"] += 1
        hit = next((i for i in idx if pred[i] == cat), None)
        if hit is not None:
            found += 1
            per_cat[cat]["found"] += 1
            late.append(rows[hit]["hours"] * 60.0)
            per_cat[cat]["late"].append(rows[hit]["hours"] * 60.0)
    buckets = []
    for lo, hi in HOUR_BUCKETS:
        idx = [i for i, r in enumerate(rows) if r["hours"] is not None and lo <= r["hours"] < hi]
        buckets.append({"hours_since_onset": f"{lo}-{hi}", "n": len(idx),
                        "correct": round(float(np.mean([pred[i] == y[i] for i in idx])), 3) if idx else None})
    from sklearn.metrics import f1_score
    return {
        "events": len(by_event), "events_found": found,
        "recall": round(found / len(by_event), 3) if by_event else None,
        "mean_minutes_late": round(float(np.mean(late)), 1) if late else None,
        "precision": round(float(np.mean([pred[i] == y[i] for i in called])), 3) if called else None,
        "false_alarm_rate": round(float(np.mean([pred[i] != simulate.NORMAL for i in normal])), 4) if normal else None,
        "accuracy": round(float(np.mean([p == t for p, t in zip(pred, y)])), 3),
        "macro_f1": round(float(f1_score(y, pred, labels=CLASSES, average="macro", zero_division=0)), 3),
        "by_category": {c: {"events": v["events"], "recall": round(v["found"] / v["events"], 3),
                            "mean_minutes_late": round(float(np.mean(v["late"])), 1) if v["late"] else None}
                        for c, v in sorted(per_cat.items())},
        "correct_by_hours_since_onset": buckets,
    }


def calibration(rows: list[dict], P: np.ndarray, edges=(0.0, 0.5, 0.7, 0.85, 0.95, 1.0001)) -> list[dict]:
    conf, idx = P.max(axis=1), P.argmax(axis=1)
    correct = np.array([CLASSES[i] == r["y"] for i, r in zip(idx, rows)])
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (conf >= lo) & (conf < hi)
        if m.any():
            out.append({"p_mean": round(float(conf[m].mean()), 3), "observed": round(float(correct[m].mean()), 3), "n": int(m.sum())})
    return out


def run(folder: str, n_cases: int = N_CASES, seed: int = 0) -> dict:
    t0 = time.time()
    ds = load(folder)
    models = baseline.fit(ds)
    systems = [s["id"] for s in ds.network["systems"]]
    real = real_label_rows(folder, ds, models)
    print(f"{len(real)} real windows ({sum(r['y'] != simulate.NORMAL for r in real)} inside labelled events) "
          f"across {len(systems)} systems; computing the rule detector's call at each ({time.time() - t0:.0f}s so far)")
    rule_calls = rules_labels(ds, real)
    for r, c in zip(real, rule_calls):
        r["rules"] = c
    spans = simulate.healthy_spans(ds)
    rng = np.random.default_rng(seed)

    pooled = defaultdict(list)                       # method -> list of (rows, P) per fold
    folds = []
    for held in systems:
        train = [s for s in systems if s != held]
        sim_rows = simulate.training_rows(
            ds, models, simulate.sample_cases(ds, n_cases, rng, systems=train, spans=spans), rng, spans=spans, systems=train)
        real_train = [r for r in real if r["system"] in train]
        test = [r for r in real if r["system"] == held]
        if not test:
            continue
        bundles = {"sim": fit_classifier(sim_rows, seed=seed), "real": fit_classifier(real_train, seed=seed),
                   "sim+real": fit_classifier(sim_rows + real_train, seed=seed)}
        P = {k: predict_proba(b, test) for k, b in bundles.items()}
        P["rules"] = _onehot([r["rules"] for r in test])
        P["ensemble"] = either_flags(P["rules"], P[HEADLINE])
        for k, p in P.items():
            pooled[k].append((test, p))
        s = score(test, P[HEADLINE])
        folds.append({"held_out_system": held, "precision": s["precision"], "recall": s["recall"],
                      "mean_minutes_late": s["mean_minutes_late"], "events": s["events"],
                      "train_rows": {"simulated": len(sim_rows), "real": len(real_train)}})
        print(f"  held out {held}: events={s['events']} recall={s['recall']} precision={s['precision']} "
              f"late={s['mean_minutes_late']} min  ({time.time() - t0:.0f}s)")

    results = {}
    for k, parts in pooled.items():
        rows = [r for rr, _ in parts for r in rr]
        P = np.vstack([p for _, p in parts])
        results[k] = (rows, P, score(rows, P))
    head_rows, head_P, _ = results[HEADLINE]
    comparison = {
        "rules": {k: results["rules"][2][k] for k in ("recall", "mean_minutes_late")},
        "models": {k: results[HEADLINE][2][k] for k in ("recall", "mean_minutes_late")},
        "ensemble": {k: results["ensemble"][2][k] for k in ("recall", "mean_minutes_late")},
    }
    out = {
        "generated_unix": int(time.time()),
        "method": "leave-one-system-out",
        "folds": folds,
        "comparison": comparison,
        "calibration_bins": calibration(head_rows, head_P),
        # --- extra detail (not part of the frontend contract; safe to ignore) ---
        "headline_model": "gradient-boosted trees trained on simulated faults only (never sees the answer key)",
        "dataset": Path(folder).name,
        "windows": {"test_total": len(head_rows), "normal": sum(r["y"] == simulate.NORMAL for r in head_rows)},
        "detail": {k: results[k][2] for k in ("rules", "sim", "real", "sim+real", "ensemble")},
        "calibration_bins_by_recipe": {k: calibration(results[k][0], results[k][1]) for k in ("sim", "real", "sim+real")},
        "notes": [
            "Decision times are every 30 minutes after onset, so mean_minutes_late is on a 30-minute grid.",
            "Windows inside an event where the equipment has not yet visibly changed count as wrong for every method.",
            "All numbers pooled over five folds; each fold's model never saw the held-out system.",
        ],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2))
    print(f"wrote {OUT.relative_to(ROOT)} in {time.time() - t0:.0f}s")
    return out


def print_summary(out: dict):
    print("\nmethod       recall  late(min)  precision  false-alarm  macro-F1")
    for k in ("rules", "sim", "real", "sim+real", "ensemble"):
        d = out["detail"][k]
        print(f"{k:11s}  {d['recall']!s:6s}  {d['mean_minutes_late']!s:9s}  {d['precision']!s:9s}  {d['false_alarm_rate']!s:11s}  {d['macro_f1']}")
    print("\ncalibration (headline model):", out["calibration_bins"])


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    folder = args[0] if args else str(ROOT / "data" / "full_week")
    out = run(folder, n_cases=150 if "--quick" in sys.argv else N_CASES)
    print_summary(out)


if __name__ == "__main__":
    main()
