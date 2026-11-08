"""
Tests for optimizer/single.py. Run from the repo root:

    python -m backend.optimizer.test_single

The EOG README example (800 bbl tank, 92% shutdown, 400 bbl now, 75 bbl/h in,
repair in 6 h, first truck in 75 min, 150 bbl trucks at $905) gives:
    one truck $905  <  shut in one well $1,958  <  do nothing $5,016.

The README does not list the three wells, so they are INVENTED here, chosen so
that all wells together lose $3,300/h (that is what makes do-nothing $5,016).
The truck and do-nothing numbers do not depend on the invented split.
"""

import itertools
import math

from .single import (
    TankProblem, Well, build_problem, do_nothing, min_cost_wells, optimize,
    shutdown_in_min, trip_arrivals,
)

OIL, GAS = 60.0, 3.0


def eog_example(**overrides) -> TankProblem:
    wells = (
        Well("C1", 600.0, 380.0, 400.0),     # $1,000/h
        Well("C2", 698.56, 190.0, 200.0),    # $500/h  (cheapest per barrel)
        Well("C3", 501.44, 700.0, 400.0),    # $1,800/h
    )
    kw = dict(
        facility_id="C", capacity_bbl=800.0, shutdown_pct=92.0, level_bbl=400.0,
        wells=wells, oil_price=OIL, gas_price=GAS, repair_remaining_min=360.0,
        response_min=75.0, cycle_min=230.0, fleet_size=2,
        truck_capacity_bbl=150.0, cost_per_trip=905.0,
    )
    kw.update(overrides)
    return TankProblem(**kw)


def test_eog_example():
    p = eog_example()
    res = optimize(p)
    by_kind = {}
    for plan in res["plans"]:
        by_kind.setdefault(plan["kind"], plan)

    assert round(res["do_nothing_cost"]) == 5016
    assert res["best"]["kind"] == "trucks"
    assert res["best"]["trips"] == 1
    assert round(res["best"]["cost"]) == 905
    assert round(by_kind["wells"]["cost"]) == 1958
    assert [round(x["cost"]) for x in res["plans"][:3]] == [905, 1958, 5016]
    assert res["best"]["keeps_under_shutdown"]


def test_every_plan_is_really_safe():
    res = optimize(eog_example())
    for plan in res["plans"]:
        if plan["kind"] != "do_nothing":
            assert plan["keeps_under_shutdown"], plan["name"]
            assert plan["peak_level_bbl"] <= 736.0 + 1e-6


def test_nothing_needed_when_repair_is_soon():
    p = eog_example(repair_remaining_min=100.0)   # 400 + 125 = 525 < 736
    res = optimize(p)
    assert res["best"]["cost"] == 0
    assert res["best"]["kind"] == "do_nothing"


def test_already_at_shutdown_everything_is_dark():
    p = eog_example(level_bbl=736.0)
    assert shutdown_in_min(p) == 0.0
    assert round(do_nothing(p)["cost"]) == round(3300 * 6)


def test_no_trucks_available():
    p = eog_example(fleet_size=0)
    res = optimize(p)
    assert res["best"]["kind"] == "wells"
    assert round(res["best"]["cost"]) == 1958


def test_expensive_trucks_lose_to_wells():
    p = eog_example(cost_per_trip=5000.0)
    assert optimize(p)["best"]["kind"] == "wells"


def test_truck_arrivals():
    p = eog_example(repair_remaining_min=600.0)
    # round 0 at 75, round 1 at 305, round 2 at 535; two trucks each round
    assert trip_arrivals(p) == [75, 75, 305, 305, 535, 535]


# -- brute force: try every truck count and every shut-in time on a grid -----

def brute_force(p: TankProblem, step: int) -> float:
    from .single import _walk, _wells_cost
    R = p.repair_remaining_min
    grid = [None] + list(range(0, int(R // step) * step + 1, step))
    grid = [g for g in grid if g is None or g < R]
    arrivals_all = trip_arrivals(p)
    best = do_nothing(p)["cost"]
    for n in range(len(arrivals_all) + 1):
        arrivals = arrivals_all[:n]
        for combo in itertools.product(grid, repeat=len(p.wells)):
            starts = {w.id: s for w, s in zip(p.wells, combo) if s is not None}
            if _walk(p, arrivals, starts)[0]:
                best = min(best, n * p.cost_per_trip + _wells_cost(p, starts))
    return best


def test_matches_brute_force_on_variants():
    cases = [
        eog_example(),
        eog_example(cost_per_trip=300.0),
        eog_example(cost_per_trip=1500.0),
        eog_example(level_bbl=600.0),
        eog_example(level_bbl=300.0, repair_remaining_min=480.0),
        eog_example(fleet_size=1, response_min=120.0, cycle_min=200.0),
        eog_example(truck_capacity_bbl=60.0, cost_per_trip=120.0),
    ]
    step = 15
    for p in cases:
        got = optimize(p, step_min=step)["best"]["cost"]
        want = brute_force(p, step)
        assert abs(got - want) < 0.01, (got, want)


def test_never_loses_to_exhaustive_search_on_random_cases():
    """1-minute optimizer vs exhaustive search on a coarse 20-minute grid."""
    import random
    rnd = random.Random(7)
    for _ in range(25):
        wells = tuple(
            Well(f"W{j}", rnd.uniform(200, 900), rnd.uniform(50, 500), rnd.uniform(50, 500))
            for j in range(rnd.choice([2, 3]))
        )
        cap = rnd.uniform(500, 1500)
        p = TankProblem(
            "F", cap, 92.0, cap * rnd.uniform(0.2, 0.8), wells, 60.0, 3.0,
            rnd.uniform(240, 480), rnd.uniform(30, 120), rnd.uniform(120, 300),
            rnd.choice([1, 2]), rnd.uniform(60, 250), rnd.uniform(100, 1500),
        )
        assert optimize(p, step_min=1)["best"]["cost"] <= brute_force(p, 20) + 0.01


def test_build_problem_reads_data_files():
    network = {
        "defaults": {"tank_limits_pct": {"warning": 85, "shutdown": 92}},
        "systems": [{
            "id": "S1",
            "facilities": [{
                "id": "S1_C",
                "tank": {"id": "T", "capacity_bbl": 800},
                "wells": [
                    {"id": "W1", "baseline_water_bpd": 900, "oil_bpd": 380, "gas_mcfd": 400},
                    {"id": "W2", "baseline_water_bpd": 900, "oil_bpd": 190, "gas_mcfd": 200},
                ],
            }],
        }],
    }
    ops = {
        "prices": {"oil_per_bbl": 60, "gas_per_mcf": 3.0},
        "expected_repair_hours": {"pump_failure": 6},
        "emergency_trucking": {"truck_capacity_bbl": 150, "cost_per_trip": 905},
        "systems": {"S1": {"emergency_fleet_size": 2,
                           "facilities": {"S1_C": {"response_min": 75, "cycle_min": 230}}}},
    }
    p = build_problem(network, ops, "S1_C", level_pct=50.0)
    assert p.level_bbl == 400 and p.limit_bbl == 736
    assert p.repair_remaining_min == 360 and p.fleet_size == 2
    assert round(optimize(p)["best"]["cost"]) == 905

    # a well that telemetry says is not flowing is left out
    p2 = build_problem(network, ops, "S1_C", level_pct=50.0, water_bpd={"W2": 0})
    assert [w.id for w in p2.wells] == ["W1"]


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("ok  ", t.__name__)
    print(f"\n{len(tests)} tests passed")
