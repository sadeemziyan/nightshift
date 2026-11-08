"""Plot one tank's level (the "sawtooth") and its pump's flow over one day.

Usage (from anywhere):
    python backend/engine/explore_sawtooth.py [dataset_folder] [facility_id]

Defaults: data/full_week and the first facility listed in network.json.
Nothing about the network is hardcoded: tank, pump, capacity, pump setpoints and
tank limits all come from network.json. Never reads answer_key.json.
Output: backend/engine/plots/sawtooth.png
"""
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # draw to a file, no window needed
import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "plots" / "sawtooth.png"


def pick_facility(network, facility_id=None):
    for system in network["systems"]:
        for fac in system["facilities"]:
            if facility_id is None or fac["id"] == facility_id:
                return system, fac
    raise SystemExit(f"Facility {facility_id!r} not found in network.json")


def series(tel, asset_id, metric):
    rows = tel[(tel["asset_id"] == asset_id) & (tel["metric"] == metric)]
    s = rows.set_index("ts_unix")["value"].sort_index()
    s.index = pd.to_datetime(s.index, unit="s", utc=True)
    return s


def main():
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "full_week"
    facility_id = sys.argv[2] if len(sys.argv) > 2 else None

    network = json.loads((folder / "network.json").read_text())
    system, fac = pick_facility(network, facility_id)
    limits = network["defaults"]["tank_limits_pct"]
    tank, pump = fac["tank"], fac["pump"]

    tel = pd.read_csv(folder / "telemetry.csv", usecols=["ts_unix", "asset_id", "metric", "value"])
    level = series(tel, tank["id"], "level_pct")
    flow = series(tel, pump["id"], "flow_bpd")

    start = level.index.min()
    end = start + pd.Timedelta(hours=24)
    level, flow = level[start:end], flow[start:end]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 6.5), sharex=True,
                                   gridspec_kw={"height_ratios": [3, 1.4]})
    ax1.plot(level.index, level.values, color="#1f77b4", lw=1.6, label="tank level")
    ax1.axhline(limits["shutdown"], color="#d62728", ls="--", label=f"shutdown ({limits['shutdown']}%)")
    ax1.axhline(limits["warning"], color="#ff7f0e", ls="--", label=f"warning ({limits['warning']}%)")
    ax1.axhline(pump["start_level_pct"], color="#2ca02c", ls=":", label=f"pump starts ({pump['start_level_pct']}%)")
    ax1.axhline(pump["stop_level_pct"], color="#7f7f7f", ls=":", label=f"pump stops ({pump['stop_level_pct']}%)")
    ax1.set_ylabel("tank level (%)")
    ax1.set_ylim(0, 100)
    ax1.set_title(f"{tank['id']} sawtooth ({tank['capacity_bbl']} bbl, system {system['id']}), first 24 h of {folder.name}")
    ax1.legend(loc="upper right", fontsize=8, ncol=2)
    ax1.grid(alpha=0.25)

    ax2.plot(flow.index, flow.values, color="#9467bd", lw=1.4)
    ax2.set_ylabel(f"{pump['id']}\nflow (bpd)")
    ax2.set_xlabel("time (UTC)")
    ax2.grid(alpha=0.25)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(OUT, dpi=150)

    starts = int(((flow > 0) & (flow.shift(1, fill_value=0) == 0)).sum())
    print(f"Saved {OUT}")
    print(f"{tank['id']}: level {level.min():.1f}% to {level.max():.1f}%, pump started {starts} time(s) in 24 h")


if __name__ == "__main__":
    main()
