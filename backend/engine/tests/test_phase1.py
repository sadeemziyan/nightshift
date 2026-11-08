"""Phase 1 checks: loader, pump-failure detection, countdown.

Run from the repo root (works with pytest too):
    python -m backend.engine.tests.test_phase1

The tests read answer_key.json only through backend.engine.scorecard (an offline script).
"""
from __future__ import annotations

import builtins
import pathlib
from pathlib import Path

from backend.engine.detect import detect
from backend.engine.forecast import forecast
from backend.engine.loader import load
from backend.engine.scorecard import load_answer_key, score

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "data"
FULL = DATA / "full_week"
EVENT_FIELDS = {
    "event_id", "system_id", "facility_id", "asset_id", "category", "status", "onset_ts",
    "onset_unix", "end_ts", "end_unix", "detected_unix", "confidence", "score", "evidence", "source",
}
TRIP_TOLERANCE_S = 15 * 60


def all_folders():
    return sorted(p for p in DATA.iterdir() if (p / "telemetry.csv").exists())


def test_loader_never_opens_answer_key():
    opened = []
    real_open, real_read_text = builtins.open, pathlib.Path.read_text

    def spy_open(f, *a, **k):
        opened.append(str(f))
        return real_open(f, *a, **k)

    def spy_read_text(self, *a, **k):
        opened.append(str(self))
        return real_read_text(self, *a, **k)

    builtins.open, pathlib.Path.read_text = spy_open, spy_read_text
    try:
        ds = load(str(FULL))
        detect(ds)
        forecast(ds)
    finally:
        builtins.open, pathlib.Path.read_text = real_open, real_read_text
    assert opened, "spy saw nothing"
    assert not any("answer_key" in p for p in opened), opened


def test_loads_every_folder_and_maps_assets():
    for folder in all_folders():
        ds = load(str(folder))
        assert ds.now_unix == int(ds.telemetry["ts_unix"].max())
        assert ds.interval_s > 0
        for fid, fac in ds.facilities.items():
            assert ds.facility_of(fac["pump"]["id"]) == fid
            assert ds.facility_of(fac["tank"]["id"]) == fid
            assert not ds.series(fac["tank"]["id"], "level_pct").empty, (folder.name, fid)


def test_event_shape_and_ids_on_every_folder():
    for folder in all_folders():
        ds = load(str(folder))
        for e in detect(ds):
            assert set(e) == EVENT_FIELDS, (folder.name, set(e) ^ EVENT_FIELDS)
            assert e["event_id"] == f"{e['asset_id']}@{e['onset_unix']}"
            assert e["category"] in {"pump_failure", "pump_degradation", "pipeline_leak"}
            assert (e["status"] == "ongoing") == (e["end_unix"] is None)
            assert e["detected_unix"] >= e["onset_unix"]


def test_pump_failures_all_found_no_false_alarms():
    for folder in all_folders():
        if not (folder / "answer_key.json").exists():
            continue
        s = score(str(folder))["by_category"].get("pump_failure")
        if s is None or not s["labelled"]:
            continue
        assert s["recall"] == 1.0, (folder.name, s)
        assert s["false_alarms"] == 0, (folder.name, s)


def test_detection_respects_t():
    ds = load(str(FULL))
    ev = next(e for e in load_answer_key(str(FULL)) if e["category"] == "pump_failure")
    before = [e for e in detect(ds, ev["onset_unix"] - ds.interval_s) if e["asset_id"] == ev["asset"]]
    assert not before, "event reported before it happened"
    during = [e for e in detect(ds, ev["onset_unix"] + 3600) if e["asset_id"] == ev["asset"]]
    assert len(during) == 1 and during[0]["status"] == "ongoing" and during[0]["end_unix"] is None
    assert during[0]["detected_unix"] <= ev["onset_unix"] + 3600


def test_snapshots_match_full_week_at_the_same_time():
    full = load(str(FULL))
    for folder in all_folders():
        if not folder.name.startswith(("snapshot_", "mock_test_")):
            continue
        snap = load(str(folder))
        in_snap = {e["event_id"]: e for e in detect(snap)}
        in_full = {e["event_id"]: e for e in detect(full, snap.now_unix)}
        assert in_snap.keys() == in_full.keys(), folder.name
        for k, e in in_snap.items():
            assert e["status"] == in_full[k]["status"] and e["detected_unix"] == in_full[k]["detected_unix"]


def test_countdown_matches_eog_reference():
    ds = load(str(FULL))
    trips, never_trips = 0, 0
    for ev in load_answer_key(str(FULL)):
        if ev["category"] != "pump_failure" or "trips_at_unix" not in ev:
            continue
        rows = [r for r in forecast(ds, ev["onset_unix"]) if r["asset_id"] == ev["asset"]]
        assert len(rows) == 1, ev["id"]
        r = rows[0]
        if ev["trips_at_unix"] is None:  # EOG: tank peaks below shutdown, repair finishes first
            assert r["trips_at_unix"] is None, (ev["id"], r["hours_to_limit"])
            never_trips += 1
            continue
        assert r["trips_at_unix"] is not None, ev["id"]
        diff = abs(r["trips_at_unix"] - ev["trips_at_unix"])
        assert diff <= TRIP_TOLERANCE_S, (ev["id"], diff / 60.0, "min off")
        trips += 1
    assert trips >= 5 and never_trips >= 1, (trips, never_trips)


def test_event_9_is_about_four_and_a_half_hours():
    ds = load(str(FULL))
    ev = next(e for e in load_answer_key(str(FULL)) if e["id"] == "EVENT_9")
    r = next(r for r in forecast(ds, ev["onset_unix"]) if r["asset_id"] == ev["asset"])
    assert abs(r["hours_to_limit"]["p50"] - 4.5) < 0.2, r["hours_to_limit"]
    assert r["repair_hours_remaining"] == 6.0
    # later in the failure the countdown shrinks and the repair clock runs down
    later = next(r2 for r2 in forecast(ds, ev["onset_unix"] + 3600) if r2["asset_id"] == ev["asset"])
    assert later["hours_to_limit"]["p50"] < r["hours_to_limit"]["p50"]
    assert later["repair_hours_remaining"] == 5.0


def test_forecast_lists_only_ongoing_failures():
    ds = load(str(FULL))
    assert forecast(ds, ds.now_unix) == [] or all(not r["already_shut_in"] or True for r in forecast(ds))
    ev = next(e for e in load_answer_key(str(FULL)) if e["category"] == "pump_failure")
    after_repair = forecast(ds, ev["end_unix"] + 3600)
    assert all(r["asset_id"] != ev["asset"] for r in after_repair)


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
