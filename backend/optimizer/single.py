"""
Single-tank cost optimizer for Nightshift.

When a pump fails, its tank fills until it reaches the shutdown level and the
facility's wells shut in. This module lists every way to avoid that and returns
the options ranked by cost, cheapest first:

  * do nothing            tank hits shutdown, ALL wells lose money until repair
  * send emergency trucks each trip removes truck_capacity_bbl for a flat price
  * shut in wells early   each well loses its oil + gas revenue while it is off
  * any mix of trucks and wells

Nothing is hardcoded. Prices, truck size and cost, response and cycle times,
repair time, tank limits and well rates all come from ops.json / network.json
(or are passed in by the caller from telemetry).

Time is measured in minutes from "now", the moment the plan is acted on.

Modelling rules (see the README of the challenge for the first four):
  1. Tank level rises by the water of every flowing well; the pump is dead.
  2. A truck trip removes up to truck_capacity_bbl at the moment it arrives.
     The first truck arrives response_min after it is called; each truck can
     return every cycle_min. fleet_size trucks work in parallel.
  3. A shut-in well produces no water, oil or gas from its shut-in minute until
     the repair is done.
  4. A plan is valid only if the tank never exceeds the shutdown level before
     the repair. "Do nothing" is always listed as the baseline.
  5. Shut-in times are whole minutes (step_min), rounded toward earlier so the
     plan is always safe. "Do nothing" uses the exact shutdown time.
  6. Trucks are dispatched immediately (earliest possible arrivals).
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path

EPS = 1e-9
MIN_PER_DAY = 1440.0


# ---------------------------------------------------------------------------
# Problem description
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Well:
    id: str
    water_bpd: float
    oil_bpd: float
    gas_mcfd: float

    @property
    def water_per_min(self) -> float:
        return self.water_bpd / MIN_PER_DAY


@dataclass(frozen=True)
class TankProblem:
    facility_id: str
    capacity_bbl: float
    shutdown_pct: float
    level_bbl: float
    wells: tuple
    oil_price: float
    gas_price: float
    repair_remaining_min: float
    response_min: float
    cycle_min: float
    fleet_size: int
    truck_capacity_bbl: float
    cost_per_trip: float

    @property
    def limit_bbl(self) -> float:
        return self.capacity_bbl * self.shutdown_pct / 100.0

    @property
    def inflow_per_min(self) -> float:
        return sum(w.water_per_min for w in self.wells)

    def revenue_per_hour(self, well: Well) -> float:
        return (well.oil_bpd * self.oil_price + well.gas_mcfd * self.gas_price) / 24.0


def _by_id(container, wanted: str):
    """Look up an entry in a dict keyed by id, or a list of {"id": ...} items.

    Also accepts a short key such as "C" for "S1_FACILITY_C" (last segment).
    """
    short = wanted.split("_")[-1]
    if isinstance(container, dict):
        for key in (wanted, short):
            if key in container:
                return container[key]
    else:
        for key in (wanted, short):
            for item in container:
                if item.get("id") == key:
                    return item
    raise KeyError(f"{wanted!r} not found in ops.json")


def _find_facility(network: dict, facility_id: str):
    for system in network["systems"]:
        for facility in system["facilities"]:
            if facility["id"] == facility_id:
                return system["id"], facility
    raise KeyError(f"facility {facility_id!r} not found in network")


def build_problem(
    network: dict,
    ops: dict,
    facility_id: str,
    *,
    level_bbl: float | None = None,
    level_pct: float | None = None,
    elapsed_min: float = 0.0,
    water_bpd: dict | None = None,
    failure_type: str = "pump_failure",
) -> TankProblem:
    """Build a TankProblem from the parsed network.json and ops.json.

    level_bbl / level_pct: the tank level now (give exactly one). It comes from
        telemetry, so the caller (the engine) supplies it.
    elapsed_min: minutes since the failure started. The repair clock started
        then, so the time left to repair shrinks by this much.
    water_bpd: optional {well_id: current bpd} from telemetry. Wells missing
        from it use baseline_water_bpd; wells at 0 are treated as not flowing.
    """
    if (level_bbl is None) == (level_pct is None):
        raise ValueError("give exactly one of level_bbl or level_pct")

    system_id, facility = _find_facility(network, facility_id)
    tank = facility["tank"]
    capacity = float(tank["capacity_bbl"])
    level = float(level_bbl) if level_bbl is not None else capacity * level_pct / 100.0

    limits = (
        tank.get("tank_limits_pct")
        or facility.get("tank_limits_pct")
        or network["defaults"]["tank_limits_pct"]
    )

    overrides = water_bpd or {}
    wells = []
    for w in facility["wells"]:
        bpd = float(overrides.get(w["id"], w["baseline_water_bpd"]))
        if bpd <= 0:
            continue
        wells.append(Well(w["id"], bpd, float(w["oil_bpd"]), float(w["gas_mcfd"])))

    ops_system = _by_id(ops["systems"], system_id)
    ops_facility = _by_id(ops_system["facilities"], facility_id)
    trucking = ops["emergency_trucking"]

    return TankProblem(
        facility_id=facility_id,
        capacity_bbl=capacity,
        shutdown_pct=float(limits["shutdown"]),
        level_bbl=level,
        wells=tuple(wells),
        oil_price=float(ops["prices"]["oil_per_bbl"]),
        gas_price=float(ops["prices"]["gas_per_mcf"]),
        repair_remaining_min=ops["expected_repair_hours"][failure_type] * 60.0 - elapsed_min,
        response_min=float(ops_facility["response_min"]),
        cycle_min=float(ops_facility["cycle_min"]),
        fleet_size=int(ops_system["emergency_fleet_size"]),
        truck_capacity_bbl=float(trucking["truck_capacity_bbl"]),
        cost_per_trip=float(trucking["cost_per_trip"]),
    )


# ---------------------------------------------------------------------------
# Simulation helpers
# ---------------------------------------------------------------------------

def trip_arrivals(p: TankProblem) -> list:
    """Earliest arrival minute of every possible truck trip, soonest first."""
    arrivals = []
    if p.fleet_size <= 0 or p.truck_capacity_bbl <= 0:
        return arrivals
    round_no = 0
    while True:
        t = p.response_min + round_no * p.cycle_min
        if t >= p.repair_remaining_min - EPS:
            break
        arrivals.extend([t] * p.fleet_size)
        round_no += 1
        if p.cycle_min <= 0:
            break
    return arrivals


def _walk(p: TankProblem, arrivals: list, starts: dict, removed: list | None = None):
    """Walk the tank level through every event. Returns (ok, peak_bbl).

    The level only rises between events, so its peak is always at an event
    (just before a truck arrives) or at the repair time.
    """
    limit = p.limit_bbl
    level = p.level_bbl
    peak = level
    if level > limit + EPS:
        return False, peak

    rate = p.inflow_per_min
    events = []
    for w in p.wells:
        s = starts.get(w.id)
        if s is not None and s < p.repair_remaining_min:
            events.append((float(s), 0, w.water_per_min))
    for a in arrivals:
        events.append((float(a), 1, 0.0))
    events.sort()

    t_prev = 0.0
    for t, kind, delta in events:
        level += rate * (t - t_prev)
        peak = max(peak, level)
        if level > limit + EPS:
            return False, peak
        if kind == 1:
            take = min(p.truck_capacity_bbl, level)
            level -= take
            if removed is not None:
                removed.append((t, take))
        else:
            rate -= delta
        t_prev = t

    level += rate * (p.repair_remaining_min - t_prev)
    peak = max(peak, level)
    return level <= limit + EPS, peak


def shutdown_in_min(p: TankProblem) -> float:
    """Minutes until the tank reaches shutdown if nothing is done (inf if never)."""
    if p.level_bbl >= p.limit_bbl - EPS:
        return 0.0
    rate = p.inflow_per_min
    if rate <= EPS:
        return math.inf
    return (p.limit_bbl - p.level_bbl) / rate


def do_nothing(p: TankProblem) -> dict:
    """Let the automatic shut-in happen: every well loses money until repair."""
    ts = shutdown_in_min(p)
    R = p.repair_remaining_min
    if ts >= R - EPS:
        return {
            "name": "Do nothing",
            "kind": "do_nothing",
            "cost": 0.0,
            "cost_math": "tank stays under shutdown until the repair: no action needed",
            "trips": 0,
            "trip_arrivals": [],
            "shut_in": [],
            "shutdown_in_min": None,
            "dark_minutes": 0.0,
            "keeps_under_shutdown": True,
        }
    dark = R - ts
    per_hour = sum(p.revenue_per_hour(w) for w in p.wells)
    cost = per_hour * dark / 60.0
    return {
        "name": "Do nothing",
        "kind": "do_nothing",
        "cost": cost,
        "cost_math": f"all wells off {dark:.1f} min × {_money(per_hour)}/h",
        "trips": 0,
        "trip_arrivals": [],
        "shut_in": [],
        "shutdown_in_min": ts,
        "dark_minutes": dark,
        "keeps_under_shutdown": False,
    }


# ---------------------------------------------------------------------------
# Cheapest well shut-ins for a fixed set of truck arrivals
# ---------------------------------------------------------------------------

def _wells_cost(p: TankProblem, starts: dict) -> float:
    R = p.repair_remaining_min
    by_id = {w.id: w for w in p.wells}
    return sum(p.revenue_per_hour(by_id[i]) * (R - s) / 60.0 for i, s in starts.items())


def _latest_start(p, arrivals, starts, well_id, lo_idx, hi_idx, step):
    """Largest grid index in [lo_idx, hi_idx] that is still feasible.

    Feasibility only gets harder as a shut-in starts later, so binary search
    works. lo_idx must already be feasible.
    """
    trial = dict(starts)
    lo, hi = lo_idx, hi_idx
    while lo < hi:
        mid = (lo + hi + 1) // 2
        trial[well_id] = mid * step
        if _walk(p, arrivals, trial)[0]:
            lo = mid
        else:
            hi = mid - 1
    return lo


def min_cost_wells(p: TankProblem, arrivals: list, step: int = 1):
    """Cheapest well shut-ins that keep the tank under shutdown.

    Returns (cost, {well_id: start_minute}) or None if even shutting every
    well in right now is not enough.

    Wells are used in order of money lost per barrel of water stopped
    (cheapest first). Each well is shut in as LATE as possible, since shut-in
    cost is proportional to how long it is off.
    """
    if _walk(p, arrivals, {})[0]:
        return 0.0, {}

    R = p.repair_remaining_min
    last_idx = int(math.floor((R - EPS) / step))  # last whole-step start before repair
    usable = [w for w in p.wells if w.water_bpd > 0]
    order = sorted(usable, key=lambda w: p.revenue_per_hour(w) / w.water_per_min)

    starts: dict = {}
    for w in order:
        trial = dict(starts)
        trial[w.id] = 0
        if not _walk(p, arrivals, trial)[0]:
            starts = trial          # fully off is still not enough; add the next well
            continue
        idx = _latest_start(p, arrivals, starts, w.id, 0, last_idx, step)
        starts[w.id] = idx * step
        break
    else:
        return None

    # Polish: drop or delay any shut-in that the others have made unnecessary.
    improved = True
    while improved:
        improved = False
        for w in reversed(order):
            if w.id not in starts:
                continue
            without = {k: v for k, v in starts.items() if k != w.id}
            if _walk(p, arrivals, without)[0]:
                starts = without
                improved = True
                continue
            cur_idx = int(round(starts[w.id] / step))
            idx = _latest_start(p, arrivals, starts, w.id, cur_idx, last_idx, step)
            if idx > cur_idx:
                starts[w.id] = idx * step
                improved = True

    return _wells_cost(p, starts), starts


# ---------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------

def _money(x: float) -> str:
    return f"${x:,.2f}" if abs(x - round(x)) > 0.005 else f"${x:,.0f}"


def _make_plan(p: TankProblem, n_trips: int, arrivals: list, starts: dict) -> dict:
    R = p.repair_remaining_min
    removed: list = []
    ok, peak = _walk(p, arrivals, starts, removed)

    shut_in = []
    for w in p.wells:
        if w.id in starts:
            s = starts[w.id]
            minutes = R - s
            rate = p.revenue_per_hour(w)
            shut_in.append({
                "well": w.id,
                "start_min": s,
                "minutes": minutes,
                "rate_per_hour": rate,
                "cost": rate * minutes / 60.0,
            })
    shut_in.sort(key=lambda x: x["start_min"])

    truck_cost = n_trips * p.cost_per_trip
    total = truck_cost + sum(s["cost"] for s in shut_in)

    parts = []
    if n_trips:
        parts.append(f"{n_trips} trip{'s' if n_trips != 1 else ''} × {_money(p.cost_per_trip)}")
    for s in shut_in:
        parts.append(f"{s['well']} off {s['minutes']:.0f} min × {_money(s['rate_per_hour'])}/h")

    if n_trips and shut_in:
        name = f"Send {n_trips} truck trip{'s' if n_trips != 1 else ''} + shut in wells"
        kind = "trucks_and_wells"
    elif n_trips:
        name = f"Send {n_trips} truck trip{'s' if n_trips != 1 else ''}"
        kind = "trucks"
    else:
        name = "Shut in wells early"
        kind = "wells"

    return {
        "name": name,
        "kind": kind,
        "cost": total,
        "cost_math": " + ".join(parts),
        "trips": n_trips,
        "trip_arrivals": [
            {"arrives_in_min": t, "removes_bbl": take} for t, take in removed
        ],
        "shut_in": shut_in,
        "peak_level_bbl": peak,
        "peak_level_pct": peak / p.capacity_bbl * 100.0,
        "keeps_under_shutdown": ok,
    }


def optimize(p: TankProblem, step_min: int = 1) -> dict:
    """Return every option ranked cheapest first, with do-nothing as baseline."""
    baseline = do_nothing(p)
    plans = [baseline]

    arrivals_all = trip_arrivals(p)
    for n in range(0, len(arrivals_all) + 1):
        arrivals = arrivals_all[:n]
        found = min_cost_wells(p, arrivals, step_min)
        if found is None:
            continue
        _, starts = found
        if n == 0 and not starts:
            break  # nothing needed at all; baseline already says so
        plans.append(_make_plan(p, n, arrivals, starts))
        if not starts:
            break  # more trucks would only add cost

    plans.sort(key=lambda x: (x["cost"], x["trips"], len(x["shut_in"])))
    return {
        "facility": p.facility_id,
        "limit_bbl": p.limit_bbl,
        "level_bbl": p.level_bbl,
        "repair_remaining_min": p.repair_remaining_min,
        "do_nothing_cost": baseline["cost"],
        "best": plans[0],
        "plans": plans,
    }


# ---------------------------------------------------------------------------
# Command line, for quick checks on a dataset folder
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Rank plans for one failed pump.")
    ap.add_argument("folder", help="dataset folder with network.json and ops.json")
    ap.add_argument("facility", help="facility id, e.g. S1_FACILITY_C")
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--level-pct", type=float)
    group.add_argument("--level-bbl", type=float)
    ap.add_argument("--elapsed-min", type=float, default=0.0)
    args = ap.parse_args(argv)

    folder = Path(args.folder)
    network = _load_json(folder / "network.json")
    ops = _load_json(folder / "ops.json")
    p = build_problem(
        network, ops, args.facility,
        level_bbl=args.level_bbl, level_pct=args.level_pct,
        elapsed_min=args.elapsed_min,
    )
    result = optimize(p)
    ts = shutdown_in_min(p)
    print(f"{p.facility_id}: tank {p.level_bbl:.0f}/{p.capacity_bbl:.0f} bbl, "
          f"shutdown at {p.limit_bbl:.0f} bbl")
    print("shutdown in:", "never" if math.isinf(ts) else f"{ts/60:.2f} h",
          f"| repair in {p.repair_remaining_min/60:.2f} h")
    for i, plan in enumerate(result["plans"], 1):
        print(f"{i}. {plan['name']}: {_money(plan['cost'])}   ({plan['cost_math']})")


if __name__ == "__main__":
    main()
