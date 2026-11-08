"""STRESS TEST: rebuild a practice week as a different network and see if the shipped models still work.

    python -m backend.ml.detect.stress [source_folder] [--out DIR]

OFFLINE ONLY (reads answer_key.json, like evaluate.py). For each variant it writes a new dataset folder (renamed
systems, every facility's volumes and every system's pressures rescaled, optional extra sensor noise, shorter history,
missing readings), carries the answer key across, then scores the SHIPPED models/m3.joblib (trained on simulated faults
only) plus the rule detector on it. M1/M2 are refitted on the new folder exactly as they are when a dataset is loaded.

What this does and does not show: it shows the models do not depend on names, sizes, pressure levels, noise level or
history length. It does not show they work on different physics; only EOG's real test/ folder does that.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import pandas as pd

from backend.engine.loader import load

from . import baseline
from .classifier import MODEL_PATH, real_label_rows
from .evaluate import _onehot, either_flags, rules_labels, score
from .m3_core import predict_proba

ROOT = Path(__file__).resolve().parents[3]
VOLUME = {"water_bpd", "inflow_bpd", "flow_bpd", "receive_flow_bpd"}
PRESSURE = {"discharge_psi", "pressure_psi"}
VARIANTS = {
    "identity":      dict(scale=False, offset=0),
    "new_network":   dict(scale=True, offset=5),
    "noisy_3pct":    dict(scale=True, offset=5, noise=0.03),
    "short_history": dict(scale=True, offset=5, drop_days=3),
    "missing_data":  dict(scale=True, offset=5, gaps=True),
}


def _rename(text: str, offset: int) -> str:
    return re.sub(r"(?<![A-Za-z0-9])S(\d+)(?![0-9])", lambda m: f"S{int(m.group(1)) + offset}", text)


def make_variant(src: Path, dst: Path, seed: int, scale=True, offset=5, noise=0.0, drop_days=0, gaps=False) -> Path:
    rng = np.random.default_rng(seed)
    net = json.loads((src / "network.json").read_text())
    kv, kp, owner = {}, {}, {}
    for s in net["systems"]:
        kp[s["id"]] = float(np.exp(rng.uniform(np.log(0.7), np.log(1.4)))) if scale else 1.0
        s["disposal_site"]["pressure_psi"] = round(s["disposal_site"]["pressure_psi"] * kp[s["id"]], 1)
        for f in s["facilities"]:
            k = kv[f["id"]] = float(np.exp(rng.uniform(np.log(0.5), np.log(2.0)))) if scale else 1.0
            for w in f["wells"]:
                for fld in ("baseline_water_bpd", "oil_bpd", "gas_mcfd"):
                    w[fld] = round(w[fld] * k, 1)
                owner[w["id"]] = (f["id"], s["id"])
            f["tank"]["capacity_bbl"] = round(f["tank"]["capacity_bbl"] * k, 1)
            f["pump"]["max_flow_bpd"] = round(f["pump"]["max_flow_bpd"] * k, 1)
            f["pipeline"]["max_bpd"] = round(f["pipeline"]["max_bpd"] * k, 1)
            f["pipeline"]["max_pressure_psi"] = round(f["pipeline"]["max_pressure_psi"] * kp[s["id"]], 1)
            for a in (f["id"], f["tank"]["id"], f["pump"]["id"], f["pipeline"]["id"]):
                owner[a] = (f["id"], s["id"])

    df = pd.read_csv(src / "telemetry.csv")
    fid = df["asset_id"].map(lambda a: owner[a][0])
    sid = df["asset_id"].map(lambda a: owner[a][1])
    v = df["value"].astype(float).to_numpy().copy()
    vol, pres = df["metric"].isin(VOLUME).to_numpy(), df["metric"].isin(PRESSURE).to_numpy()
    v[vol] *= fid[vol].map(kv).to_numpy()
    v[pres] *= sid[pres].map(kp).to_numpy()
    if noise:
        m = vol | pres
        v[m] *= 1.0 + rng.normal(0.0, noise, m.sum())
    df["value"] = v
    keep = np.ones(len(df), dtype=bool)
    start = int(df["ts_unix"].min())
    if drop_days:
        keep &= (df["ts_unix"] >= start + drop_days * 86400).to_numpy()
    if gaps:
        keep &= rng.random(len(df)) > 0.01                       # 1% of readings lost at random
        hit = (sid == sorted(kp)[0]).to_numpy()                  # plus a 3 h outage for one whole system
        t0 = start + 2 * 86400 + 3600
        keep &= ~(hit & (df["ts_unix"] >= t0).to_numpy() & (df["ts_unix"] < t0 + 3 * 3600).to_numpy())
    df = df[keep]
    cut = int(df["ts_unix"].min())

    dst.mkdir(parents=True, exist_ok=True)
    df["asset_id"] = df["asset_id"].map(lambda a: _rename(a, offset))
    df.to_csv(dst / "telemetry.csv", index=False)
    (dst / "network.json").write_text(_rename(json.dumps(net, indent=1), offset))
    shutil.copy(src / "ops.json", dst / "ops.json")
    (dst / "ops.json").write_text(_rename((src / "ops.json").read_text(), offset))
    key = json.loads((src / "answer_key.json").read_text())
    key = [e for e in key if e["onset_unix"] >= cut + 6 * 3600]  # events that start before there is any history are not fair
    (dst / "answer_key.json").write_text(_rename(json.dumps(key, indent=1), offset))
    return dst


def evaluate_folder(folder: Path) -> dict:
    import joblib
    t0 = time.time()
    ds = load(str(folder))
    models = baseline.fit(ds)
    rows = real_label_rows(str(folder), ds, models)
    for r, c in zip(rows, rules_labels(ds, rows)):
        r["rules"] = c
    bundle = joblib.load(MODEL_PATH)
    Pm, Pr = predict_proba(bundle, rows), _onehot([r["rules"] for r in rows])
    out = {k: score(rows, P) for k, P in {"rules": Pr, "models": Pm, "ensemble": either_flags(Pr, Pm)}.items()}
    out["seconds"] = round(time.time() - t0)
    return out


def main():
    argv = sys.argv[1:]
    out_dir = Path(tempfile.mkdtemp(prefix="stress_"))
    if "--out" in argv:
        i = argv.index("--out")
        out_dir = Path(argv[i + 1])
        del argv[i:i + 2]
    src = Path(argv[0]) if argv else ROOT / "data" / "full_week"
    only = argv[1:]                                             # optional: variant names to run
    results = {}
    for i, (name, kw) in enumerate(VARIANTS.items()):
        if only and name not in only:
            continue
        folder = make_variant(src, out_dir / name, seed=100 + i, **kw)
        try:
            results[name] = evaluate_folder(folder)
        except Exception as exc:                                  # a crash IS a result
            results[name] = {"error": f"{type(exc).__name__}: {exc}"}
        print(name, json.dumps({k: (v if k == "error" or k == "seconds" else {m: v[m] for m in ("events", "recall", "mean_minutes_late", "precision", "false_alarm_rate")})
                                for k, v in results[name].items()}), flush=True)
    (out_dir / "stress_results.json").write_text(json.dumps(results, indent=2))
    print("wrote", out_dir / "stress_results.json")


if __name__ == "__main__":
    main()
