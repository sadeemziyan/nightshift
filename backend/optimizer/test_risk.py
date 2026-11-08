"""Tests for risk-aware planning (optimizer/risk.py + the risk setting of system.py).

    python -m backend.optimizer.test_risk

Uses the same invented world as test_system (EOG's 800 bbl tank, trucks $905, 6 h repair). Each failing tank
gets an M4-style inflow_range; a 1% spread is wide enough to make a knife-edge plan visibly risky.
"""
from .system import plan_system
from .test_system import world

SPREAD = {"horizon_h": 6.0, "ratio_p10": 0.99, "ratio_p50": 1.0, "ratio_p90": 1.01}


def plans(fleet, risk=None, rng=SPREAD, rows_slice=slice(None)):
    network, ops, rows = world(fleet)
    rows = [{**r, **({"inflow_range": rng} if rng else {})} for r in rows[rows_slice]]
    return plan_system(network, ops, "S1", rows, t=1_000_000, risk=risk)


def test_without_a_forecast_range_there_is_no_risk_number():
    res = plans(2, risk=0.95, rng=None)
    assert all(p["shutdown_risk"] is None for p in res["plans"])
    assert res["risk_level"] is None and res["risk_note"]
    assert round(res["plans"][0]["cost_usd"]) == 1810            # still the cost-optimal plan


def test_default_plans_are_unchanged_by_the_risk_code():
    with_range = plans(2)
    without = plans(2, rng=None)
    assert [p["cost_usd"] for p in with_range["plans"]] == [p["cost_usd"] for p in without["plans"]]
    assert round(plans(2, rows_slice=slice(0, 1))["plans"][0]["cost_usd"]) == 905   # EOG's example


def test_every_plan_reports_a_risk_between_0_and_1():
    for p in plans(2)["plans"]:
        assert 0.0 <= p["shutdown_risk"] <= 1.0


def test_do_nothing_is_certain_to_hit_shutdown_and_a_truck_with_room_is_safe():
    res = plans(2, rows_slice=slice(0, 1))
    do_nothing = res["plans"][-1]
    assert do_nothing["shutdown_risk"] == 1.0
    assert res["plans"][0]["shutdown_risk"] == 0.0                # one truck leaves plenty of room


def test_a_knife_edge_shut_in_plan_is_risky_when_inflow_is_uncertain():
    top = plans(0)["plans"][0]                                    # no trucks: late shut-ins only
    assert top["shutdown_risk"] > 0.2


def test_risk_mode_meets_the_level_and_costs_more_for_more_safety():
    base = plans(0)["plans"][0]["cost_usd"]
    previous = base
    for level in (0.9, 0.99):
        res = plans(0, risk=level)
        top = res["plans"][0]
        assert top["meets_risk"] is True and top["shutdown_risk"] <= 1 - level + 1e-9
        assert top["cost_usd"] >= base - 1e-6                     # never beats the exact optimum
        assert top["cost_usd"] >= previous - 1e-6                 # more safety never costs less
        assert abs(res["cost_of_safety_usd"] - (top["cost_usd"] - base)) < 0.02
        previous = top["cost_usd"]


def test_a_plan_that_already_has_room_costs_nothing_extra_for_safety():
    res = plans(2, risk=0.99, rows_slice=slice(0, 1))
    assert round(res["plans"][0]["cost_usd"]) == 905 and res["cost_of_safety_usd"] == 0.0


def test_risk_mode_never_uses_more_trucks_than_the_fleet():
    for fleet in (0, 1, 2):
        for p in plans(fleet, risk=0.95)["plans"]:
            assert p["trucks_used"] <= fleet


def test_system_risk_combines_the_tanks_as_independent():
    res = plans(0)
    top = res["plans"][0]
    parts = [pf["shutdown_risk"] for pf in top["per_facility"]]
    safe = 1.0
    for r in parts:
        safe *= 1 - r
    assert abs(top["shutdown_risk"] - round(1 - safe, 3)) < 0.002


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("ok  ", t.__name__)
    print(f"\n{len(tests)} tests passed")
