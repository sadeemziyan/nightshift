"""OFFLINE check of M1 against the answer key (one of the few scripts allowed to read answer_key.json).

    python -m backend.ml.detect.check_m1 [dataset_folder] [event_id]

Prints, per labelled problem type, how far M1's scores are from zero inside the labelled windows versus
in normal periods, and saves a plot of one failing pump (default: the first pump_failure) to
backend/ml/detect/plots/m1_<event>.png for the Model Lab. Numbers come from this run, never typed by hand.
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from backend.engine.loader import load
from backend.engine.scorecard import load_answer_key
from backend.ml.detect import baseline

ROOT = Path(__file__).resolve().parents[3]
PLOTS = Path(__file__).resolve().parent / "plots"
# the channel that carries each problem type, and which direction is "bad"
CHANNEL = {"pump_failure": ("pflow", -1), "pump_degradation": ("pflow", -1), "pipeline_leak": ("rpsi", -1)}


def window_stats(ds, models, key):
    rows = []
    for cat, (sensor, sign) in CHANNEL.items():
        inside, outside = [], []
        for fid in ds.facilities:
            fr = baseline.residuals(ds, fid, ds.now_unix, models)
            zc = sign * fr[f"{sensor}_z"]
            mask = np.zeros(len(fr), dtype=bool)
            for e in key:
                if e["category"] == cat and ds.facility_of(e["asset"]) == fid:
                    mask |= (fr.index >= e["onset_unix"]) & (fr.index < e["end_unix"])
            # "normal" = not inside ANY labelled problem at this facility
            anymask = np.zeros(len(fr), dtype=bool)
            for e in key:
                if ds.facility_of(e["asset"]) == fid:
                    anymask |= (fr.index >= e["onset_unix"]) & (fr.index < e["end_unix"])
            if mask.any():
                inside.append(zc[mask])
            outside.append(zc[~anymask])
        ins, outs = pd.concat(inside), pd.concat(outside)
        rows.append({
            "problem": cat, "scored channel": f"{sensor} (bad = {'down' if sign < 0 else 'up'})",
            "median score inside windows": round(float(ins.median()), 1),
            "share of readings beyond 3 spreads (inside)": round(float((ins > 3).mean()), 3),
            "median score in normal periods": round(float(outs.median()), 2),
            "share beyond 3 spreads (normal)": round(float((outs > 3).mean()), 4),
        })
    return pd.DataFrame(rows)


def plot_failure(ds, models, event, out):
    fid = ds.facility_of(event["asset"])
    fac = ds.facility(fid)
    fr = baseline.residuals(ds, fid, ds.now_unix, models)
    lo, hi = event["onset_unix"] - 12 * 3600, event["end_unix"] + 6 * 3600
    fr = fr[(fr.index >= lo) & (fr.index <= hi)]
    x = pd.to_datetime(fr.index, unit="s", utc=True)
    fig, ax = plt.subplots(3, 1, figsize=(11, 8), sharex=True, gridspec_kw={"height_ratios": [2, 2, 1.4]})
    ax[0].plot(x, fr["level"], color="#1f77b4")
    lim = fac["limits"]
    ax[0].axhline(lim["shutdown"], color="#d62728", ls="--", label="shutdown")
    ax[0].axhline(lim["warning"], color="#ff7f0e", ls="--", label="warning")
    ax[0].set_ylabel("tank level (%)")
    ax[0].legend(loc="upper left", fontsize=8)
    ax[1].fill_between(x, fr["pflow_lo"], fr["pflow_hi"], color="#2ca02c", alpha=0.25, label="learned normal (M1)")
    ax[1].plot(x, fr["pflow"], color="#9467bd", label="actual pump flow")
    ax[1].set_ylabel("pump flow (bpd)")
    ax[1].legend(loc="upper left", fontsize=8)
    ax[2].plot(x, (-fr["pflow_z"]).clip(lower=0), color="#d62728")
    ax[2].axhline(3, color="#7f7f7f", ls=":")
    ax[2].set_yscale("symlog", linthresh=1)
    ax[2].set_ylim(0, None)
    ax[2].set_ylabel("M1 score\n(healthy spreads)")
    for a in ax:
        a.axvspan(pd.to_datetime(event["onset_unix"], unit="s", utc=True),
                  pd.to_datetime(event["end_unix"], unit="s", utc=True), color="#d62728", alpha=0.06)
        a.grid(alpha=0.25)
    ax[0].set_title(f"{event['asset']} ({event['id']}, {event['category']}): learned normal vs reality")
    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=150)


def main():
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "full_week"
    ds = load(str(folder))
    key = load_answer_key(folder)
    models = baseline.fit(ds)
    print(f"M1 fitted for {sum(m.ready for m in models.values())}/{len(models)} facilities on {folder.name}")
    print(window_stats(ds, models, key).to_string(index=False))
    want = sys.argv[2] if len(sys.argv) > 2 else None
    ev = next((e for e in key if (e["id"] == want if want else e["category"] == "pump_failure")), None)
    if ev:
        out = PLOTS / f"m1_{ev['id']}.png"
        plot_failure(ds, models, ev, out)
        print("saved", out)


if __name__ == "__main__":
    main()
