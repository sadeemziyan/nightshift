"""Tests for optimizer/system.py. Run: python -m backend.optimizer.test_system"""

from .system import plan_all, plan_system


def _facility(fid):
    wells = [
        {"id": f"{fid}_W1", "baseline_water_bpd": 600.0, "oil_bpd": 380, "gas_mcfd": 400},   # $1,000/h
        {"id": f"{fid}_W2", "baseline_water_bpd": 698.56, "oil_bpd": 190, "gas_mcfd": 200},  # $500/h
        {"id": f"{fid}_W3", "baseline_water_bpd": 501.44, "oil_bpd": 700, "gas_mcfd": 400},  # $1,800/h
    ]
    return {"id": fid, "wells": wells, "tank": {"id": f"{fid}_T", "capacity_bbl": 800}}


def world(fleet):
    network = {
        "defaults": {"tank_limits_pct": {"warning": 85, "shutdown": 92}},
        "systems": [{"id": "S1", "facilities": [_facility("C"), _facility("D")]}],
    }
    ops = {
        "prices": {"oil_per_bbl": 60, "gas_per_mcf": 3.0},
        "expected_repair_hours": {"pump_failure": 6},
        "emergency_trucking": {"truck_capacity_bbl": 150, "cost_per_trip": 905},
        "systems": {"S1": {"emergency_fleet_size": fleet, "facilities": {
            "C": {"response_min": 75, "cycle_min": 230},
            "D": {"response_min": 75, "cycle_min": 230}}}},
    }
    rows = []
    for fid in ("C", "D"):
        rows.append({
            "event_id": f"{fid}_PUMP@1", "system_id": "S1", "facility_id": fid,
            "level_pct": 50.0, "elapsed_min": 0.0, "already_shut_in": False,
            "well_water_bpd": {f"{fid}_W1": 600.0, f"{fid}_W2": 698.56, f"{fid}_W3": 501.44},
        })
    return network, ops, rows


def best(fleet, rows_slice=slice(None)):
    network, ops, rows = world(fleet)
    return plan_system(network, ops, "S1", rows[rows_slice], t=1_000_000)


def test_one_failure_matches_eog_example():
    sysplan = best(2, slice(0, 1))
    assert round(sysplan["do_nothing_cost_usd"]) == 5016
    top = sysplan["plans"][0]
    assert round(top["cost_usd"]) == 905 and top["summary"] == "1 truck, 1 trip"
    assert top["actions"] == [{"type": "dispatch_truck", "facility_id": "C",
                               "trucks": 1, "trips_per_truck": 1}]
    assert top["keeps_tank_under_shutdown"] is True


def test_two_failures_with_two_trucks_get_one_each():
    top = best(2)["plans"][0]
    assert round(top["cost_usd"]) == 1810 and top["trucks_used"] == 2


def test_two_failures_with_one_truck_share_it():
    top = best(1)["plans"][0]
    assert top["trucks_used"] == 1
    assert round(top["cost_usd"], 2) == round(905 + 235 * 500 / 60, 2)   # truck + one late shut-in
    kinds = sorted(a["type"] for a in top["actions"])
    assert kinds == ["dispatch_truck", "shut_in_wells"]


def test_no_trucks_means_wells_only():
    top = best(0)["plans"][0]
    assert top["trucks_used"] == 0
    assert round(top["cost_usd"], 2) == round(2 * 235 * 500 / 60, 2)


def test_never_uses_more_trucks_than_the_fleet():
    for fleet in (0, 1, 2, 3):
        for plan in best(fleet)["plans"]:
            assert plan["trucks_used"] <= fleet


def test_plans_ranked_cheapest_first_and_do_nothing_listed():
    plans = best(2)["plans"]
    costs = [p["cost_usd"] for p in plans[:-1]]
    assert costs == sorted(costs)
    assert any(p["summary"].count("Do nothing") == 2 for p in plans)


def test_already_shut_in_tank_is_priced_not_planned():
    network, ops, rows = world(2)
    rows = rows[:1]
    rows[0].update(level_pct=92.0, already_shut_in=True, well_water_bpd={})
    out = plan_all(network, ops, rows, t=1_000_000)["systems"][0]
    assert out["plans"][0]["actions"] == [{"type": "none", "facility_id": "C"}]
    assert round(out["plans"][0]["cost_usd"]) == 3300 * 6


def test_separate_planning_is_never_cheaper_than_system_plan():
    for fleet in (0, 1, 2, 3):
        out = best(fleet)
        sep = out["planned_separately"]
        assert sep["trucks_used"] <= fleet
        assert sep["cost_usd"] >= out["plans"][0]["cost_usd"] - 0.01
        assert sep["extra_cost_vs_system_plan_usd"] >= -0.01


def test_one_tank_has_no_separate_comparison():
    assert best(2, slice(0, 1))["planned_separately"] is None


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("ok  ", t.__name__)
    print(f"\n{len(tests)} tests passed")
