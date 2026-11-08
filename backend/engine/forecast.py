"""Countdown to shutdown for every pump failure in progress at time t.

    rows = forecast(ds, t)

One dict per failing tank. The pump is dead, so the tank only fills:
    hours to shutdown = room left (bbl) / inflow (bbl per day) * 24
    room left         = (shutdown_pct - level_pct) / 100 * capacity_bbl
Everything (capacity, limits, repair hours) comes from network.json / ops.json; level and well
rates come from telemetry up to t. `well_water_bpd`, `level_pct` and `elapsed_min` are exactly what
the optimizer's build_problem() takes. p10/p90 stay null until the M4 forecaster exists.
"""
from __future__ import annotations


from .detect import detect
from .loader import Dataset, iso

RATE_WINDOW = 6  # readings averaged for each well's current rate (smooths sensor noise)


def current_well_rates(ds: Dataset, facility_id: str, t: int) -> dict:
    """{well_id: bpd now}. A well whose latest status is 0 (shut in) counts as 0."""
    rates = {}
    for wid in ds.facility(facility_id)["wells"]:
        status = ds.latest(wid, "status", t)
        water = ds.series(wid, "water_bpd", t).tail(RATE_WINDOW)
        if status is not None and status < 0.5:
            rates[wid] = 0.0
        elif len(water):
            rates[wid] = float(water.mean())
        else:
            rates[wid] = float(ds.facility(facility_id)["well_cfg"][wid].get("baseline_water_bpd", 0.0))
    return rates


def forecast(ds: Dataset, t: int | None = None, events: list[dict] | None = None) -> list[dict]:
    t = ds.now_unix if t is None else int(t)
    events = detect(ds, t) if events is None else events
    repair_h = ds.repair_hours("pump_failure")
    rows = []
    for ev in events:
        if ev["category"] != "pump_failure" or ev["status"] != "ongoing":
            continue
        fac = ds.facility(ev["facility_id"])
        tank = fac["tank"]
        level = ds.latest(tank["id"], "level_pct", t)
        if level is None:
            continue
        capacity = float(tank["capacity_bbl"])
        shutdown_pct = fac["limits"]["shutdown"]
        wells = current_well_rates(ds, fac["id"], t)
        inflow = float(sum(wells.values()))

        already_shut = level >= shutdown_pct
        room_bbl = max(0.0, (shutdown_pct - level) / 100.0 * capacity)
        if already_shut:
            hours = 0.0
        elif inflow > 0:
            hours = room_bbl / inflow * 24.0
        else:
            hours = None  # nothing flowing in, the tank is not filling

        repair_end = ev["onset_unix"] + int(repair_h * 3600)
        trips_at = None
        if hours is not None and t + hours * 3600 < repair_end:
            trips_at = int(round(t + hours * 3600))
        if already_shut:
            trips_at = t

        rows.append({
            "event_id": ev["event_id"],
            "system_id": ev["system_id"],
            "facility_id": fac["id"],
            "asset_id": ev["asset_id"],
            "level_pct": round(level, 2),
            "level_bbl": round(level / 100.0 * capacity, 1),
            "capacity_bbl": capacity,
            "shutdown_pct": shutdown_pct,
            "inflow_bpd": round(inflow, 1),
            "well_water_bpd": {k: round(v, 1) for k, v in wells.items()},
            "hours_to_limit": {"p50": None if hours is None else round(hours, 2), "p10": None, "p90": None},
            "already_shut_in": already_shut,
            "trips_at_unix": trips_at,
            "trips_at_ts": iso(trips_at),
            "repair_ends_unix": repair_end,
            "repair_hours_remaining": round(max(0.0, (repair_end - t) / 3600.0), 2),
            "elapsed_min": round((t - ev["onset_unix"]) / 60.0, 1),
        })
    rows.sort(key=lambda r: (r["hours_to_limit"]["p50"] is None, r["hours_to_limit"]["p50"] or 0))
    return rows
