"""
System-wide plans for Nightshift.

A system's pump failures in progress at time t share ONE truck fleet (SPEC.md,
"Shared trucks"). So we plan them together:

  1. For each failing tank, single.optimize() lists its own options: do nothing,
     N trucks x K trips (+ late well shut-ins), or wells only.
  2. We try every mix of those options across the tanks, drop the mixes that
     use more trucks than the system owns, and rank the rest by total cost.

At "now" nothing has been dispatched yet, so the whole fleet is free.

Everything comes from network.json / ops.json / telemetry (through the rows
that engine.forecast() returns). Nothing is hardcoded and answer_key.json is
never read.
"""

from __future__ import annotations

import itertools
from dataclasses import replace
from datetime import datetime, timezone

from .single import _by_id, build_problem, optimize

MAX_CANDIDATES_PER_FACILITY = 8   # best options kept per tank before mixing
TOP_PLANS = 5                     # ranked system plans returned (plus do-nothing)


def _hhmm(unix: float) -> str:
    return datetime.fromtimestamp(int(unix), tz=timezone.utc).strftime("%H:%MZ")


def _plan_summary(plan: dict) -> str:
    parts = []
    if plan["trucks"]:
        t, k = plan["trucks"], plan["trips_per_truck"]
        parts.append(f"{t} truck{'s' if t != 1 else ''}, {k} trip{'s' if k != 1 else ''}")
    shut = plan["shut_in"]
    if shut:
        text = ", ".join(f"{s['well']} at +{round(s['start_min'])} min" for s in shut)
        parts.append(f"shut in {text}" if parts else f"Shut in {text}")
    if parts:
        return " + ".join(parts)
    if plan["kind"] == "do_nothing":
        return "No action needed" if plan["keeps_under_shutdown"] else "Do nothing"
    return plan["name"]


def _actions(facility_id: str, plan: dict) -> list:
    actions = []
    if plan["trucks"]:
        actions.append({"type": "dispatch_truck", "facility_id": facility_id,
                        "trucks": plan["trucks"], "trips_per_truck": plan["trips_per_truck"]})
    for s in plan["shut_in"]:
        actions.append({"type": "shut_in_wells", "wells": [s["well"]],
                        "start_after_min": int(round(s["start_min"]))})
    if not actions:
        actions.append({"type": "none", "facility_id": facility_id})
    return actions


def _candidates(problem, step_min: int) -> list:
    res = optimize(problem, step_min=step_min)
    plans = res["plans"]
    keep = plans[:MAX_CANDIDATES_PER_FACILITY]
    baseline = next(p for p in plans if p["kind"] == "do_nothing")
    if baseline not in keep:
        keep.append(baseline)
    return keep


def _one_at_a_time(facilities: list, fleet: int) -> dict:
    """What a console that plans each tank separately would do.

    Tanks are handled most urgent first (the order of `facilities`). Each takes its cheapest
    plan from the trucks still left, so an early tank can grab trucks a later tank needed.
    """
    left, total, trucks_used, parts = fleet, 0.0, 0, []
    wanted = 0
    for fac in facilities:
        wanted += min(fac["cands"], key=lambda c: (c["cost"], c["trips"]))["trucks"]
        options = [c for c in fac["cands"] if c["trucks"] <= left]
        pick = min(options, key=lambda c: (c["cost"], c["trips"]))
        left -= pick["trucks"]
        trucks_used += pick["trucks"]
        total += pick["cost"]
        parts.append(f"{fac['row']['facility_id']}: {_plan_summary(pick)}")
    return {"cost_usd": round(total, 2), "summary": "; ".join(parts),
            "trucks_used": trucks_used, "trucks_wanted_if_independent": wanted}


def plan_system(network: dict, ops: dict, system_id: str, rows: list, t: int,
                *, step_min: int = 1) -> dict:
    """Plans for every failing tank of one system, planned together.

    rows: forecast() rows for this system's pump failures in progress at t. Each
    needs facility_id, event_id, level_pct, well_water_bpd, elapsed_min and
    already_shut_in.
    """
    fleet = int(_by_id(ops["systems"], system_id)["emergency_fleet_size"])

    facilities = []
    for row in rows:
        already = bool(row.get("already_shut_in"))
        problem = build_problem(
            network, ops, row["facility_id"],
            level_pct=row["level_pct"],
            elapsed_min=row["elapsed_min"],
            # a tank already at shutdown has its wells off: price them at their normal rates
            water_bpd=None if already else row["well_water_bpd"],
        )
        problem = replace(problem, fleet_size=fleet)
        cands = _candidates(problem, step_min)
        facilities.append({"row": row, "problem": problem, "cands": cands,
                           "baseline": next(c for c in cands if c["kind"] == "do_nothing")})

    do_nothing_cost = sum(f["baseline"]["cost"] for f in facilities)

    mixes = []
    for combo in itertools.product(*[f["cands"] for f in facilities]):
        if sum(c["trucks"] for c in combo) > fleet:
            continue
        mixes.append((sum(c["cost"] for c in combo), sum(c["trips"] for c in combo), combo))
    mixes.sort(key=lambda m: (m[0], m[1]))

    chosen = mixes[:TOP_PLANS]
    all_idle = tuple(f["baseline"] for f in facilities)
    if not any(m[2] == all_idle for m in chosen):
        chosen.append((do_nothing_cost, 0, all_idle))

    plans = []
    for rank, (total, _, combo) in enumerate(chosen, 1):
        per_fac, actions = [], []
        truck_cost = shut_cost = auto_cost = 0.0
        keeps = True
        for fac, plan in zip(facilities, combo):
            fid = fac["row"]["facility_id"]
            cost_trucks = plan["trips"] * fac["problem"].cost_per_trip
            if plan["kind"] == "do_nothing":
                auto_cost += plan["cost"]
            else:
                truck_cost += cost_trucks
                shut_cost += plan["cost"] - cost_trucks
            keeps = keeps and plan["keeps_under_shutdown"]
            actions.extend(_actions(fid, plan))
            per_fac.append({
                "facility_id": fid,
                "event_id": fac["row"]["event_id"],
                "summary": _plan_summary(plan),
                "cost_usd": round(plan["cost"], 2),
                "cost_math": plan["cost_math"],
                "trucks": plan["trucks"],
                "trips_per_truck": plan["trips_per_truck"],
                "trip_arrivals": [
                    {"arrives_unix": int(t + a["arrives_in_min"] * 60),
                     "arrives_ts": _hhmm(t + a["arrives_in_min"] * 60),
                     "removes_bbl": round(a["removes_bbl"], 1)}
                    for a in plan["trip_arrivals"]
                ],
                "shut_in": plan["shut_in"],
                "peak_level_pct": plan.get("peak_level_pct"),
                "tank_trips_in_min": plan.get("shutdown_in_min"),
                "keeps_tank_under_shutdown": plan["keeps_under_shutdown"],
                "actions": _actions(fid, plan),
            })
        # trucks first, then shut-ins, so the screen reads in dispatch order
        actions.sort(key=lambda a: {"dispatch_truck": 0, "shut_in_wells": 1}.get(a["type"], 2))
        plans.append({
            "rank": rank,
            "summary": "; ".join(f"{pf['facility_id']}: {pf['summary']}" for pf in per_fac)
            if len(per_fac) > 1 else per_fac[0]["summary"],
            "cost_usd": round(total, 2),
            "cost_breakdown": {"trucks": round(truck_cost, 2), "shut_in": round(shut_cost, 2),
                               "automatic_shutdown": round(auto_cost, 2)},
            "cost_math": " | ".join(
                (f"{pf['facility_id']}: " if len(per_fac) > 1 else "") + pf["cost_math"] for pf in per_fac),
            "actions": actions,
            "trucks_used": sum(pf["trucks"] for pf in per_fac),
            "keeps_tank_under_shutdown": keeps,
            "shutdown_risk": None,
            "per_facility": per_fac,
        })

    separate = None
    if len(facilities) > 1 and plans:
        separate = _one_at_a_time(facilities, fleet)
        separate["extra_cost_vs_system_plan_usd"] = round(separate["cost_usd"] - plans[0]["cost_usd"], 2)

    return {
        "system_id": system_id,
        "fleet_size": fleet,
        "event_ids": [f["row"]["event_id"] for f in facilities],
        "do_nothing_cost_usd": round(do_nothing_cost, 2),
        "planned_separately": separate,
        "plans": plans,
    }


def plan_all(network: dict, ops: dict, rows: list, t: int, *, step_min: int = 1) -> dict:
    """Plans for every system that has a pump failure in progress.

    rows: engine.forecast(ds, t) output (pump failures in progress at t only).
    """
    by_system: dict = {}
    for row in rows:
        by_system.setdefault(row["system_id"], []).append(row)
    systems = [plan_system(network, ops, sid, rs, t, step_min=step_min)
               for sid, rs in by_system.items()]
    return {"t": int(t), "systems": systems}
