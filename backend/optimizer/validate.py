"""Compare optimizer/single.py with EOG's reference plans in answer_key.json.

Offline check only. The app itself never reads answer_key.json.

    python -m backend.optimizer.validate data/full_week
"""
import csv, json, re, sys
from pathlib import Path
from datetime import datetime, timezone

from .single import build_problem, optimize, _find_facility, _by_id


def ts(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()


def well_water_at(folder, events, network):
    """Latest water_bpd per well at or before each event's onset."""
    want = {}
    for e in events:
        _, fac = _find_facility(network, e["facility"])
        want[e["id"]] = (e["onset_unix"], {w["id"] for w in fac["wells"]})
    latest = {eid: {} for eid in want}
    with open(Path(folder) / "telemetry.csv", newline="") as f:
        for r in csv.DictReader(f):
            if r["metric"] != "water_bpd":
                continue
            t = int(r["ts_unix"])
            for eid, (onset, wells) in want.items():
                if r["asset_id"] in wells and t <= onset:
                    latest[eid][r["asset_id"]] = float(r["value"])
    return latest


def main(folder):
    folder = Path(folder)
    network = json.load(open(folder / "network.json"))
    ops = json.load(open(folder / "ops.json"))
    events = sorted([e for e in json.load(open(folder / "answer_key.json"))
                     if e["category"] == "pump_failure"], key=lambda e: e["onset_unix"])
    water = well_water_at(folder, events, network)
    used = []  # (system, busy_until_unix, trucks)
    for e in events:
        sysid = e["system"]
        ops_sys = _by_id(ops["systems"], sysid)
        fleet = ops_sys["emergency_fleet_size"]
        busy = sum(n for s, until, n in used if s == sysid and until > e["onset_unix"])
        free = max(fleet - busy, 0)
        p = build_problem(network, ops, e["facility"], level_pct=e["level_pct"], water_bpd=water[e["id"]])
        from dataclasses import replace
        p = replace(p, fleet_size=free)
        res = optimize(p)
        best = res["best"]
        ref = e["reference_action"]
        m = re.search(r"~\$([\d,]+)", ref)
        ref_cost = float(m.group(1).replace(",", "")) if m else 0.0
        mt = re.search(r"(\d+) truck, (\d+) trip", ref)
        if best["trips"]:
            used.append((sysid, e["onset_unix"] + p.cycle_min * 60 * max(1, best["trips"] // max(free, 1)), min(best["trips"], free)))
        shut = "; ".join(f"{s['well']}@+{s['start_min']:.0f}" for s in best["shut_in"])
        ok = abs(best["cost"] - ref_cost) <= max(25, 0.01 * ref_cost)
        print(f"{e['id']:9} {e['facility']:14} free {free}/{fleet}  ref ${ref_cost:>7,.0f}  mine ${best['cost']:>8,.0f}  {'OK ' if ok else 'DIFF'}  trips {best['trips']} {shut}")
        if not ok:
            print("          ref :", ref)
            print("          mine:", best["name"], "|", best["cost_math"])

if __name__ == "__main__":
    main(sys.argv[1])
