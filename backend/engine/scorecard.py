"""OFFLINE scorecard: compare detect() against answer_key.json.

This is one of the only scripts allowed to read answer_key.json (CLAUDE.md hard rule 2).
The app, loader and API never import it for anything but offline checks.

    python -m backend.engine.scorecard data/full_week [--models]

An answer-key event counts as found if detect() returned an event on the same asset and category
whose time span overlaps the labelled window (it may start up to ONSET_SLACK_S early; the onset error is reported separately). Slow problems
(leaks, wear) ramp up gradually, so we do not demand the onset to the minute; instead we report
"minutes late" = detected_unix - true onset (how long the operator waited) and "onset error" =
our estimated onset - true onset. Extra detected events that match nothing are false alarms.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .detect import detect
from .loader import load

ONSET_SLACK_S = 3 * 3600  # a detection may start up to 3 h before the labelled onset and still be the same problem (onset error is reported separately)


def load_answer_key(folder) -> list[dict]:
    path = Path(folder) / "answer_key.json"
    return json.loads(path.read_text()) if path.exists() else []


def score(folder, t: int | None = None, ds=None, detector=None) -> dict:
    """detector: any function (ds, t) -> events. Default is the rule-based engine.detect."""
    ds = ds or load(folder)
    t = ds.now_unix if t is None else int(t)
    truth = [e for e in load_answer_key(folder) if e["onset_unix"] <= t]
    found_events = (detector or detect)(ds, t)

    matched_ids, rows = set(), []
    for e in truth:
        hit = None
        for d in found_events:
            d_end = d["end_unix"] if d["end_unix"] is not None else t
            if (d["asset_id"] == e["asset"] and d["category"] == e["category"]
                    and d["onset_unix"] <= min(e["end_unix"] if e.get("end_unix") is not None else t, t) and d_end >= e["onset_unix"] - ONSET_SLACK_S
                    and d["onset_unix"] >= e["onset_unix"] - ONSET_SLACK_S
                    and d["event_id"] not in matched_ids):
                hit = d
                break
        if hit:
            matched_ids.add(hit["event_id"])
        rows.append({
            "id": e["id"], "category": e["category"], "asset": e["asset"],
            "onset_unix": e["onset_unix"],
            "found": hit is not None,
            "minutes_late": None if not hit else round((hit["detected_unix"] - e["onset_unix"]) / 60.0, 1),
            "onset_error_min": None if not hit else round((hit["onset_unix"] - e["onset_unix"]) / 60.0, 1),
        })

    false_alarms = [d for d in found_events if d["event_id"] not in matched_ids]
    by_cat = {}
    for cat in sorted({r["category"] for r in rows} | {d["category"] for d in found_events}):
        cat_rows = [r for r in rows if r["category"] == cat]
        late = [r["minutes_late"] for r in cat_rows if r["found"]]
        by_cat[cat] = {
            "labelled": len(cat_rows),
            "found": sum(r["found"] for r in cat_rows),
            "recall": round(sum(r["found"] for r in cat_rows) / len(cat_rows), 3) if cat_rows else None,
            "mean_minutes_late": round(sum(late) / len(late), 1) if late else None,
            "false_alarms": sum(1 for d in false_alarms if d["category"] == cat),
        }
    return {"dataset": Path(folder).name, "t": t, "by_category": by_cat, "events": rows,
            "false_alarm_ids": [d["event_id"] for d in false_alarms]}


def print_result(result: dict):
    for cat, s in result["by_category"].items():
        print(f"  {cat:18s} found {s['found']}/{s['labelled']}  recall={s['recall']}  "
              f"mean minutes late={s['mean_minutes_late']}  false alarms={s['false_alarms']}")
    for cat in result["by_category"]:
        errs = [abs(r["onset_error_min"]) for r in result["events"] if r["category"] == cat and r["found"]]
        if errs:
            print(f"  {cat:18s} median |onset error| = {sorted(errs)[len(errs) // 2]:.0f} min")
    missed = [r for r in result["events"] if not r["found"]]
    if missed:
        print("  not found:", ", ".join(f"{r['id']} ({r['category']})" for r in missed))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    use_models = "--models" in sys.argv
    folder = args[0] if args else "data/full_week"
    detector = None
    if use_models:
        from backend.ml.detect.enrich import detect_with_models  # offline comparison only
        detector = detect_with_models
    if "--all" in sys.argv:   # every dataset folder that has an answer key (full_week and each snapshot)
        root = Path(folder).parent if args else Path("data")
        for f in sorted(p for p in root.iterdir() if (p / "answer_key.json").exists()):
            r = score(f, detector=detector)
            print(f"{f.name} (t={r['t']}) using {'rules + models' if use_models else 'rules only'}")
            print_result(r)
        return
    result = score(folder, detector=detector)
    result = score(folder, detector=detector)
    print(f"Scorecard for {result['dataset']} (t={result['t']}) using {'rules + models' if use_models else 'rules only'}")
    print_result(result)


if __name__ == "__main__":
    main()
