"""M5: risk-aware planning. Not trained: it scores plans against M4's inflow range.

M4 (backend/ml/forecast) says the average inflow over the repair window will be `ratio` times the inflow
now, with a p10 / p50 / p90 range. M4 supplies the SPREAD. The centre stays at the inflow measured now
(ratio 1), the same steady-inflow assumption as EOG's math, so risk mode never claims a plan that beats
the exact cost-optimal one: it only prices the margin needed to be safe. We turn the spread into a
lognormal and draw N_SCENARIOS evenly spaced scenarios from it. A plan's shutdown risk is the share of scenarios in which its tank still reaches the
shutdown level before the repair ends:

    risk = (scenarios where the tank hits the limit) / N_SCENARIOS

Each tank is scored on its own; for a whole system the tanks are treated as independent (different wells):

    system risk = 1 - (1 - risk_A) * (1 - risk_B) * ...

The cost of a plan never changes with risk (trips x $905 + wells off x their revenue). What changes is
which plans are allowed: with a risk level r, only plans whose system risk is at most 1 - r are kept, and
the cheapest of those wins. To find them we also plan against pessimistic inflow (high quantiles of the
scenario range), because a plan that is only just safe at the expected inflow is a coin flip in practice.
"""
from __future__ import annotations

import math
from dataclasses import replace
from statistics import NormalDist

from .single import _make_plan, _walk, arrivals_for, optimize

N_SCENARIOS = 101
PESSIMISTIC_Z = (1.2816, 1.96, 2.576)      # inflow at about the 90th, 97.5th and 99.5th percentile
_Z90 = 1.2815515655
_ND = NormalDist()


def lognormal(rng: dict) -> tuple:
    """(mu, sigma) of the inflow ratio: centred on 1 (inflow now), spread from M4's ratio_p10 / p90."""
    sigma = (math.log(rng["ratio_p90"]) - math.log(rng["ratio_p10"])) / (2.0 * _Z90)
    return 0.0, max(sigma, 1e-6)


def multipliers(rng: dict, n: int = N_SCENARIOS) -> list:
    mu, sigma = lognormal(rng)
    return [math.exp(mu + sigma * _ND.inv_cdf((k + 0.5) / n)) for k in range(n)]


def scaled(p, m: float):
    """The same tank problem with every well's water multiplied by m."""
    return replace(p, wells=tuple(replace(w, water_bpd=w.water_bpd * m) for w in p.wells))


def _actions(p, plan: dict) -> tuple:
    trucks, k = plan["trucks"], plan["trips_per_truck"]
    arrivals = arrivals_for(p, trucks, k) if trucks else []
    starts = {s["well"]: s["start_min"] for s in plan["shut_in"]}
    return arrivals or [], starts


def plan_risk(p, plan: dict, mults: list) -> float:
    """Share of inflow scenarios in which this plan's tank still reaches the shutdown level."""
    arrivals, starts = _actions(p, plan)
    bad = sum(0 if _walk(scaled(p, m), arrivals, starts)[0] else 1 for m in mults)
    return bad / len(mults)


def _key(plan: dict) -> tuple:
    return (plan["trucks"], plan["trips_per_truck"],
            tuple(sorted((s["well"], round(s["start_min"], 3)) for s in plan["shut_in"])))


def robust_candidates(p, rng: dict, step_min: int = 1, keep: int = 8) -> list:
    """Plans found by planning against pessimistic inflow, rebuilt and priced on the expected inflow."""
    mu, sigma = lognormal(rng)
    found = []
    for z in PESSIMISTIC_Z:
        res = optimize(scaled(p, math.exp(mu + sigma * z)), step_min=step_min)
        for pl in res["plans"]:
            if pl["kind"] == "do_nothing":
                continue
            arrivals = arrivals_for(p, pl["trucks"], pl["trips_per_truck"]) if pl["trucks"] else []
            starts = {s["well"]: s["start_min"] for s in pl["shut_in"]}
            found.append(_make_plan(p, pl["trucks"], pl["trips_per_truck"], arrivals or [], starts))
            if len(found) % keep == 0:
                break
    return found


def pareto(plans: list) -> list:
    """Drop plans that another plan beats (or ties) on cost, risk and trucks used."""
    keep = []
    for a in plans:
        dominated = any(
            b is not a
            and b["cost"] <= a["cost"] + 1e-9 and b["shutdown_risk"] <= a["shutdown_risk"] + 1e-9
            and b["trucks"] <= a["trucks"]
            and (b["cost"] < a["cost"] - 1e-9 or b["shutdown_risk"] < a["shutdown_risk"] - 1e-9
                 or b["trucks"] < a["trucks"] or id(b) < id(a))
            for b in plans)
        if not dominated:
            keep.append(a)
    return keep
