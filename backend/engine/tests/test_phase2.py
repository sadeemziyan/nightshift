"""Phase 2 checks: rule-based leak and pump-degradation detection.

Run from the repo root:   python -m backend.engine.tests.test_phase2
(answer_key.json is read only through backend.engine.scorecard, an offline script.)
"""
from __future__ import annotations

from pathlib import Path

from backend.engine.detect import detect
from backend.engine.loader import load
from backend.engine.scorecard import load_answer_key, score

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "data"
FULL = DATA / "full_week"
SLOW = ("pipeline_leak", "pump_degradation")


def keyed_folders():
    return sorted(p for p in DATA.iterdir() if (p / "answer_key.json").exists())


def pump_ran_since(ds, ev, t, readings=4):
    """True if the problem's pump has >= `readings` running readings after the labelled end (up to t)."""
    fid = ds.asset_to_facility[ev["asset"]]
    st = ds.series(ds.facility(fid)["pump"]["id"], "status", t)
    return int(((st.index > ev["end_unix"]) & (st == 1)).sum()) >= readings


def test_every_labelled_problem_found_no_false_alarms_on_every_folder():
    for folder in keyed_folders():
        r = score(str(folder))
        for cat, s in r["by_category"].items():
            assert s["recall"] == 1.0, (folder.name, cat, s)
            assert s["false_alarms"] == 0, (folder.name, cat, s)


def test_no_false_alarms_when_only_part_of_the_week_is_known():
    """Learning 'normal' from little history must not invent problems."""
    ds = load(str(FULL))
    start = int(ds.telemetry["ts_unix"].min())
    for hours in range(6, 169, 12):
        r = score(str(FULL), t=start + hours * 3600, ds=ds)
        assert all(s["false_alarms"] == 0 for s in r["by_category"].values()), (hours, r["false_alarm_ids"])


def test_slow_problems_are_caught_within_a_reasonable_time():
    r = score(str(FULL))
    for e in r["events"]:
        if e["category"] == "pipeline_leak":
            assert e["minutes_late"] <= 120, e
        if e["category"] == "pump_degradation":
            assert e["minutes_late"] <= 600, e


def test_reported_live_not_only_in_hindsight():
    """Replaying the week hour by hour, each problem must show up while it is still in progress."""
    ds = load(str(FULL))
    for ev in load_answer_key(str(FULL)):
        if ev["category"] not in SLOW:
            continue
        limit = 12 if ev["category"] == "pipeline_leak" else 12
        first = None
        for h in range(0, limit + 1):
            t = ev["onset_unix"] + h * 3600
            if any(e["asset_id"] == ev["asset"] and e["category"] == ev["category"] for e in detect(ds, t)):
                first = h
                break
        assert first is not None, (ev["id"], f"not reported within {limit} h of onset")


def test_nothing_reported_before_it_happens():
    ds = load(str(FULL))
    for ev in load_answer_key(str(FULL)):
        if ev["category"] not in SLOW:
            continue
        early = [e for e in detect(ds, ev["onset_unix"] - 3600) if e["asset_id"] == ev["asset"] and e["category"] == ev["category"]]
        assert not early, (ev["id"], early)


def test_ongoing_versus_resolved_is_reported_correctly():
    ds = load(str(FULL))
    truth = [e for e in load_answer_key(str(FULL)) if e["category"] in SLOW]
    for ev in truth:
        mid = ev["onset_unix"] + (ev["end_unix"] - ev["onset_unix"]) // 2
        during = [e for e in detect(ds, mid) if e["asset_id"] == ev["asset"] and e["category"] == ev["category"]]
        assert len(during) == 1 and during[0]["status"] == "ongoing" and during[0]["end_unix"] is None, ev["id"]
        after = [e for e in detect(ds, ev["end_unix"] + 14 * 3600) if e["asset_id"] == ev["asset"] and e["category"] == ev["category"]]
        assert len(after) == 1 and after[0]["status"] == "resolved", (ev["id"], after)


def test_snapshot_still_in_progress_matches_the_answer_key_status():
    for folder in keyed_folders():
        if not folder.name.startswith("snapshot_"):
            continue
        ds = load(str(folder))
        events = detect(ds)
        for ev in load_answer_key(str(folder)):
            if ev["category"] not in SLOW:
                continue
            match = [e for e in events if e["asset_id"] == ev["asset"] and e["category"] == ev["category"]]
            assert match, (folder.name, ev["id"])
            if ev.get("status") == "ongoing":
                assert match[-1]["status"] == "ongoing", (folder.name, ev["id"])
            elif pump_ran_since(ds, ev, ds.now_unix):
                assert match[-1]["status"] == "resolved", (folder.name, ev["id"])
            # else: repaired but the pump has not run since, so no reading can confirm it yet -> ongoing is honest


def test_slow_events_have_confidence_evidence_and_valid_ids():
    ds = load(str(FULL))
    slow = [e for e in detect(ds) if e["category"] in SLOW]
    assert len(slow) >= 10
    for e in slow:
        assert 0.5 <= e["confidence"] <= 0.99, e
        assert e["evidence"] and all(isinstance(x, str) and x for x in e["evidence"])
        assert e["event_id"] == f"{e['asset_id']}@{e['onset_unix']}"
        assert e["detected_unix"] >= e["onset_unix"]


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS {name}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {name}: {type(exc).__name__}: {exc}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    raise SystemExit(1 if failed else 0)

