"""Checks for M1 (baseline), M2 (drift) and the enrichment layer.

Run from the repo root:   python -m backend.ml.detect.tests.test_models
answer_key.json is read only through backend.engine.scorecard / backend.ml.detect.check_m1 (offline scripts).
"""
from __future__ import annotations

import builtins
import pathlib
from pathlib import Path

import numpy as np

from backend.engine import detect as rules
from backend.engine.loader import load
from backend.engine.scorecard import load_answer_key, score
from backend.ml.detect import baseline, check_m1, drift, enrich
from backend.ml.detect.enrich import detect_with_models

ROOT = Path(__file__).resolve().parents[4]
DATA = ROOT / "data"
FULL = DATA / "full_week"
FIELDS = {"event_id", "system_id", "facility_id", "asset_id", "category", "status", "onset_ts", "onset_unix",
          "end_ts", "end_unix", "detected_unix", "confidence", "score", "evidence", "source"}
SLOW = ("pipeline_leak", "pump_degradation")


def keyed_folders():
    return sorted(p for p in DATA.iterdir() if (p / "answer_key.json").exists())


def test_cusum_finds_a_change_point_and_a_ramp_onset():
    rng = np.random.default_rng(1)
    z = rng.normal(0, 1, 300)
    z[150:] += np.arange(150) * 0.05            # ramp starts at index 150
    ts = np.arange(300) * 300
    s, alarm = drift.cusum(z)
    assert alarm is not None and alarm > 150
    est = drift.estimate_onset(ts, z, alarm)
    assert abs(est["cusum"] - 150 * 300) < 40 * 300
    assert est["ramp"] is not None and abs(est["ramp"] - 150 * 300) < 25 * 300
    quiet, none_alarm = drift.cusum(rng.normal(0, 1, 500))
    assert none_alarm is None


def test_drift_score_grows_with_evidence():
    vals = [drift.drift_score(x) for x in (0, 5, 50, 500)]
    assert vals == sorted(vals) and vals[0] == 0.0 and vals[-1] == 1.0


def test_m1_separates_failures_and_normal_periods():
    ds = load(str(FULL))
    models = baseline.fit(ds)
    assert all(m.ready for m in models.values())
    stats = check_m1.window_stats(ds, models, load_answer_key(FULL)).set_index("problem")
    f = stats.loc["pump_failure"]
    assert f["median score inside windows"] > 20 and f["share of readings beyond 3 spreads (inside)"] > 0.9
    assert abs(f["median score in normal periods"]) < 0.5 and f["share beyond 3 spreads (normal)"] < 0.05


def test_m1_chart_points_have_the_contract_fields():
    ds = load(str(FULL))
    asset = ds.facility(next(iter(ds.facilities)))["pump"]["id"]
    out = baseline.chart_points(ds, asset, "flow_bpd", hours=6)
    assert out["unit"] == "bpd" and out["points"]
    assert set(out["points"][0]) == {"ts_unix", "actual", "expected", "lower", "upper", "score"}
    assert all(p["lower"] <= p["expected"] <= p["upper"] for p in out["points"])


def test_every_problem_still_found_with_models_no_false_alarms():
    for folder in keyed_folders():
        r = score(str(folder), detector=detect_with_models)
        for cat, s in r["by_category"].items():
            assert s["recall"] == 1.0 and s["false_alarms"] == 0, (folder.name, cat, s)


def test_models_sharpen_the_onset_time():
    ds = load(str(FULL))
    with_models = score(str(FULL), ds=ds, detector=detect_with_models)
    only_rules = score(str(FULL), ds=ds)
    for cat, limit in (("pipeline_leak", 60), ("pump_degradation", 60)):
        m = sorted(abs(e["onset_error_min"]) for e in with_models["events"] if e["category"] == cat)
        r = sorted(abs(e["onset_error_min"]) for e in only_rules["events"] if e["category"] == cat)
        assert m[len(m) // 2] <= limit, (cat, m)
        assert m[len(m) // 2] <= r[len(r) // 2], (cat, m, r)


def test_enriched_events_keep_the_contract_and_explain_themselves():
    ds = load(str(FULL))
    for e in detect_with_models(ds):
        assert set(e) == FIELDS, set(e) ^ FIELDS
        assert e["source"] == "model+rules" and 0.0 <= e["score"] <= 1.0 and 0.0 <= e["confidence"] <= 1.0
        assert e["event_id"] == f"{e['asset_id']}@{e['onset_unix']}"
        assert e["evidence"][0] and "z=" in e["evidence"][0]


def test_score_grows_while_a_problem_develops():
    ds = load(str(FULL))
    for ev in load_answer_key(str(FULL)):
        if ev["id"] not in ("EVENT_16", "EVENT_5"):
            continue
        seen = []
        for h in (2, 6, 12, 24):
            m = [e for e in detect_with_models(ds, ev["onset_unix"] + h * 3600)
                 if e["asset_id"] == ev["asset"] and e["category"] == ev["category"]]
            if m:
                seen.append(m[0]["score"])
        assert len(seen) >= 2 and seen == sorted(seen) and seen[-1] > seen[0], (ev["id"], seen)


def test_model_failure_falls_back_to_rules_and_never_crashes():
    ds = load(str(FULL))
    expected = rules.detect(ds)
    real_fit = baseline.fit

    def boom(*a, **k):
        raise RuntimeError("simulated model failure")

    enrich._CACHE.clear()
    enrich.baseline.fit = boom
    try:
        got = detect_with_models(ds)
    finally:
        enrich.baseline.fit = real_fit
        enrich._CACHE.clear()
    assert got == expected and all(e["source"] == "rules" for e in got)


def test_one_bad_event_does_not_spoil_the_others():
    ds = load(str(FULL))
    real = enrich._reason
    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("bad event")
        return real(*a, **k)

    enrich._reason = flaky
    try:
        got = detect_with_models(ds)
    finally:
        enrich._reason = real
    sources = [e["source"] for e in got]
    assert sources.count("rules") == 1 and sources.count("model+rules") == len(got) - 1


def test_models_never_open_answer_key():
    opened = []
    real_open, real_read = builtins.open, pathlib.Path.read_text

    def spy_open(f, *a, **k):
        opened.append(str(f))
        return real_open(f, *a, **k)

    def spy_read(self, *a, **k):
        opened.append(str(self))
        return real_read(self, *a, **k)

    builtins.open, pathlib.Path.read_text = spy_open, spy_read
    try:
        ds = load(str(FULL))
        enrich._CACHE.clear()
        detect_with_models(ds)
        baseline.chart_points(ds, ds.facility(next(iter(ds.facilities)))["pump"]["id"], "flow_bpd", hours=2)
    finally:
        builtins.open, pathlib.Path.read_text = real_open, real_read
    assert opened and not any("answer_key" in p for p in opened), opened


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
