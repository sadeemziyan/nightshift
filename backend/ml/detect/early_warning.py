"""Early-warning proof: how early does M3 see a slow problem, and how often does it cry wolf?

    python -m backend.ml.detect.early_warning [dataset_folder]     # writes docs/early_warning.json and a plot

For every leak and wear event the rule detector finds (sensor-only: this script never reads answer_key.json) it
  * draws the curve "how sure is M3, hour by hour after the problem starts" (frozen M1 normals, so it is fast), and
  * replays the night in real time at 30-minute steps with `blend.early_warnings` and records when M3 first flagged the
    problem, i.e. how many minutes BEFORE the rule alert it gave a warning.
It also replays the whole week every 2 hours and counts warnings raised where no problem was in progress.
Numbers come from this run, never typed by hand.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

from backend.engine import detect as rules
from backend.engine.loader import load

from . import baseline, blend, drift, enrich
from .features import window_features
from .m3_core import CLASSES, predict_proba

ROOT = Path(__file__).resolve().parents[3]
SLOW = ("pipeline_leak", "pump_degradation")
CHANNEL = {"pipeline_leak": "rpsi", "pump_degradation": "pflow"}
CURVE_HOURS = [0.5 * k for k in range(1, 17)]            # 0.5 h .. 8 h after the problem starts
STEP_S = 1800


def curves(ds, events, models, bundle) -> list[dict]:
    out = []
    for ev in events:
        fr = baseline.residuals(ds, ev["facility_id"], ds.now_unix, models)
        run = fr[fr["status"] == 1]
        z = (-run[f"{CHANNEL[ev['category']]}_z"]).to_numpy()
        s, _ = drift.cusum(z)
        s_by_t = dict(zip(run.index.to_numpy(), s))
        pts = []
        for h in CURVE_HOURS:
            t = ev["onset_unix"] + int(h * 3600)
            if ev["end_unix"] is not None and t > ev["end_unix"]:
                break
            x = window_features(fr, t, ds.interval_s)
            if not x:
                continue
            p = predict_proba(bundle, [x])[0][CLASSES.index(ev["category"])]
            seen = [v for tt, v in s_by_t.items() if tt <= t]
            pts.append({"hours": h, "m3_probability": round(float(p), 3),
                        "drift_score": round(drift.drift_score(max(seen) if seen else 0.0), 3)})
        out.append({"event_id": ev["event_id"], "category": ev["category"], "points": pts})
    return out


def lead_times(ds, events, threshold) -> list[dict]:
    out = []
    for ev in events:
        first = None
        t = ev["onset_unix"] - 3600
        while t < ev["detected_unix"]:
            if any(w["facility_id"] == ev["facility_id"] and w["category"] == ev["category"]
                   for w in blend.early_warnings(ds, t, threshold)):
                first = t
                break
            t += STEP_S
        out.append({"event_id": ev["event_id"], "category": ev["category"],
                    "rule_alert_after_onset_min": round((ev["detected_unix"] - ev["onset_unix"]) / 60.0, 1),
                    "m3_warning_after_onset_min": None if first is None else round((first - ev["onset_unix"]) / 60.0, 1),
                    "warned_first_by_min": None if first is None else round((ev["detected_unix"] - first) / 60.0, 1)})
    return out


def false_warnings(ds, all_events, threshold, every_h: float = 2.0) -> dict:
    start = int(min(s.index[0] for s in ds._series.values() if len(s))) + 12 * 3600
    total, false, checked = 0, [], 0
    for t in range(start, ds.now_unix, int(every_h * 3600)):
        checked += 1
        for w in blend.early_warnings(ds, t, threshold):
            total += 1
            near = any(e["facility_id"] == w["facility_id"] and e["onset_unix"] - 6 * 3600 <= t
                       <= (e["end_unix"] if e["end_unix"] is not None else ds.now_unix) + 6 * 3600 for e in all_events)
            if not near:
                false.append({"t": t, "facility_id": w["facility_id"], "category": w["category"], "probability": w["probability"]})
    return {"times_checked": checked, "warnings_raised": total, "false_warnings": len(false), "examples": false[:5], "all": false}


def plot(cv: list[dict], out: Path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    colors = {"pipeline_leak": "#1f77b4", "pump_degradation": "#d95f02"}
    names = {"pipeline_leak": "pipeline leak", "pump_degradation": "pump wearing out"}
    fig, ax = plt.subplots(figsize=(8, 4.5))
    for cat in SLOW:
        series = [c["points"] for c in cv if c["category"] == cat and c["points"]]
        for pts in series:
            ax.plot([p["hours"] for p in pts], [p["m3_probability"] for p in pts], color=colors[cat], alpha=0.18, lw=1)
        hours = sorted({p["hours"] for pts in series for p in pts})
        mean = [np.mean([p["m3_probability"] for pts in series for p in pts if p["hours"] == h]) for h in hours]
        ax.plot(hours, mean, color=colors[cat], lw=2.5, label=f"{names[cat]} (average of {len(series)})")
    ax.axhline(0.8, color="#7f7f7f", ls=":", lw=1)
    ax.text(0.2, 0.82, "early-warning level", color="#7f7f7f", fontsize=8)
    ax.set_xlabel("hours since the problem started")
    ax.set_ylabel("how sure the classifier is (probability)")
    ax.set_ylim(0, 1.02)
    ax.set_title("Confidence rises as the evidence builds")
    ax.grid(alpha=0.25)
    ax.legend(loc="lower right", fontsize=9)
    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=150)


def run(folder: str, threshold: float = 0.8) -> dict:
    t0 = time.time()
    ds = load(folder)
    bundle = blend._bundle()
    if bundle is None:
        raise SystemExit("models/m3.joblib is missing: python -m backend.ml.detect.classifier --train")
    models = baseline.fit(ds)
    all_events = rules.detect(ds)
    slow = [e for e in enrich.detect_with_models(ds) if e["category"] in SLOW]
    cv = curves(ds, slow, models, bundle)
    leads = lead_times(ds, slow, threshold)
    fw = false_warnings(ds, all_events, threshold)
    warned = [x["warned_first_by_min"] for x in leads if x["warned_first_by_min"] is not None]
    summary = {"events": len(leads), "warned_before_rule_alert": sum(1 for w in warned if w > 0),
               "mean_minutes_earlier": round(float(np.mean(warned)), 1) if warned else None}
    for cat in SLOW:
        w = [x["warned_first_by_min"] for x in leads if x["category"] == cat and x["warned_first_by_min"] is not None]
        summary[cat] = {"events": sum(1 for x in leads if x["category"] == cat),
                        "mean_minutes_earlier": round(float(np.mean(w)), 1) if w else None}
    out = {"generated_unix": int(time.time()), "dataset": Path(folder).name, "threshold": threshold,
           "reference": "problem start and alert time come from the sensor-only rule detector, not the answer key",
           "summary": summary, "lead_times": leads, "false_warnings": fw, "curves": cv}
    dest = ROOT / "docs" / "early_warning.json"
    dest.write_text(json.dumps(out, indent=2))
    plot(cv, Path(__file__).resolve().parent / "plots" / "early_warning.png")
    print(json.dumps({"summary": summary, "false_warnings": {k: v for k, v in fw.items() if k not in ("examples", "all")}}, indent=2))
    print(f"wrote {dest.relative_to(ROOT)} and plots/early_warning.png in {time.time() - t0:.0f}s")
    return out


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "data" / "full_week"))
