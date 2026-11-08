"""Tests for POST /simulate/inject. Run from the repo root:

    python -m backend.api.test_simulate

Calls the endpoint functions directly (no test client needed). Uses data/full_week.
"""
from fastapi import HTTPException

from . import main

ONSET = 1_791_600_000          # a quiet stretch of full_week
VIEW = ONSET + 3 * 3600


def fresh():
    main.load_dataset("full_week")
    return main._cache["full_week"]


def raises(status, **body):
    try:
        main.simulate_inject(main.InjectBody(**body))
    except HTTPException as e:
        assert e.status_code == status, (e.status_code, e.detail)
        return
    raise AssertionError("expected an HTTPException")


def test_injected_pump_failure_is_found_and_flagged_simulated():
    fresh()
    res = main.simulate_inject(main.InjectBody(asset_id="S1_PUMP_A", category="pump_failure", onset_unix=ONSET))
    assert res["simulated"] is True and res["event_id"] == f"SIM:S1_PUMP_A@{ONSET}"
    alerts = main.alerts(t=VIEW)
    assert alerts["simulated"] is True
    mine = [a for a in alerts["alerts"] if a["asset_id"] == "S1_PUMP_A"]
    assert mine and mine[0]["category"] == "pump_failure" and mine[0]["simulated"] is True
    assert main.forecast_endpoint(t=VIEW)["simulated"] is True
    assert main.plan_endpoint(t=VIEW, risk=None)["simulated"] is True


def test_real_alerts_are_not_flagged():
    fresh()
    alerts = main.alerts(t=1791453900)
    assert "simulated" not in alerts and all("simulated" not in a for a in alerts["alerts"])


def test_the_real_data_is_never_changed_and_load_goes_back_to_it():
    real = fresh()
    before = real.series("S1_PUMP_A", "flow_bpd").copy()
    main.simulate_inject(main.InjectBody(asset_id="S1_PUMP_A", category="pump_failure", onset_unix=ONSET))
    assert real.series("S1_PUMP_A", "flow_bpd").equals(before)
    assert main.current() is not real
    main.load_dataset("full_week")
    assert main.current() is real
    assert [a for a in main.alerts(t=VIEW)["alerts"] if a["asset_id"] == "S1_PUMP_A"] == []


def test_a_milder_leak_is_smaller_than_a_severe_one():
    ds = fresh()
    def peak_drop(sev):
        fresh()
        main.simulate_inject(main.InjectBody(asset_id="S2_PIPELINE_B", category="pipeline_leak",
                                             onset_unix=ONSET, severity=sev))
        sim = main.current()
        return float((ds.series("S2_PIPELINE_B", "pressure_psi") - sim.series("S2_PIPELINE_B", "pressure_psi")).max())
    assert 0 < peak_drop(0.1) < peak_drop(1.0)


def test_bad_requests_get_clean_errors():
    fresh()
    raises(404, asset_id="NOPE", category="pump_failure", onset_unix=ONSET)
    raises(400, asset_id="S1_PUMP_A", category="meltdown", onset_unix=ONSET)
    raises(400, asset_id="S1_PUMP_A", category="pipeline_leak", onset_unix=ONSET)      # a pump, not a pipeline
    raises(400, asset_id="S1_PUMP_A", category="pump_failure", onset_unix=5)           # before the data starts


def test_model_status_reports_the_classifier():
    fresh()
    assert main.model_status()["models"]["M3"]["ready"] is True


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("ok  ", t.__name__)
    print(f"\n{len(tests)} tests passed")
