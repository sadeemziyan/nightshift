"""Load one dataset folder (network.json, ops.json, telemetry.csv).

    ds = load("data/full_week")

Rules this file follows (see CLAUDE.md):
  * it takes a folder path, never a fixed dataset name;
  * it never opens answer_key.json (only offline scripts may);
  * assets are mapped to facilities through network.json, never by parsing asset_id text;
  * "now" for a folder is its last ts_unix; nothing about time ranges is hardcoded.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

TELEMETRY_COLUMNS = ["ts_unix", "asset_id", "metric", "value"]


def iso(ts_unix) -> str | None:
    """Unix seconds -> '2026-10-08T00:20:00Z' (None stays None)."""
    if ts_unix is None:
        return None
    return datetime.fromtimestamp(int(ts_unix), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _as_lookup(container) -> dict:
    """ops.json may key systems/facilities by id (dict) or list them as {"id": ...}."""
    if isinstance(container, dict):
        return container
    return {item["id"]: item for item in (container or [])}


@dataclass
class Dataset:
    folder: Path
    network: dict
    ops: dict
    telemetry: pd.DataFrame            # columns: timestamp, ts_unix, asset_id, metric, value
    now_unix: int
    interval_s: int                    # sampling interval, inferred from the data
    facilities: dict                   # facility_id -> info dict (see _index_network)
    asset_to_facility: dict            # any asset id (well/tank/pump/pipeline) -> facility_id
    _series: dict = field(default_factory=dict, repr=False)

    # ---- time series access -------------------------------------------------
    def series(self, asset_id: str, metric: str, t: int | None = None) -> pd.Series:
        """Values of one sensor, indexed by ts_unix, sorted. Only rows with ts_unix <= t."""
        s = self._series.get((asset_id, metric))
        if s is None:
            return pd.Series(dtype=float)
        if t is not None:
            s = s[s.index <= t]
        return s

    def latest(self, asset_id: str, metric: str, t: int | None = None):
        s = self.series(asset_id, metric, t)
        return None if s.empty else float(s.iloc[-1])

    # ---- convenience lookups ------------------------------------------------
    def facility(self, facility_id: str) -> dict:
        return self.facilities[facility_id]

    def facility_of(self, asset_id: str) -> str | None:
        return self.asset_to_facility.get(asset_id)

    def system_ops(self, system_id: str) -> dict:
        return _as_lookup(self.ops.get("systems")).get(system_id, {})

    def facility_ops(self, facility_id: str) -> dict:
        fac = self.facilities[facility_id]
        return _as_lookup(self.system_ops(fac["system_id"]).get("facilities")).get(facility_id, {})

    def repair_hours(self, category: str = "pump_failure") -> float:
        return float(self.ops.get("expected_repair_hours", {}).get(category, 0))

    def summary(self) -> dict:
        return {
            "dataset": self.folder.name,
            "now_unix": self.now_unix,
            "now_ts": iso(self.now_unix),
            "systems": len(self.network["systems"]),
            "facilities": len(self.facilities),
        }


def _index_network(network: dict) -> tuple[dict, dict]:
    default_limits = network.get("defaults", {}).get("tank_limits_pct", {})
    facilities, asset_to_fac = {}, {}
    for system in network["systems"]:
        disposal = system.get("disposal_site", {})
        for fac in system["facilities"]:
            tank, pump, pipe = fac["tank"], fac["pump"], fac["pipeline"]
            limits = tank.get("tank_limits_pct") or fac.get("tank_limits_pct") or default_limits
            info = {
                "id": fac["id"],
                "system_id": system["id"],
                "wells": [w["id"] for w in fac["wells"]],
                "well_cfg": {w["id"]: w for w in fac["wells"]},
                "tank": tank,
                "pump": pump,
                "pipeline": pipe,
                "limits": {"warning": limits.get("warning"), "shutdown": limits.get("shutdown")},
                "disposal_psi": disposal.get("pressure_psi"),
            }
            facilities[fac["id"]] = info
            for asset in [*info["wells"], tank["id"], pump["id"], pipe["id"]]:
                asset_to_fac[asset] = fac["id"]
    return facilities, asset_to_fac


def load(folder: str) -> Dataset:
    folder = Path(folder)
    network = json.loads((folder / "network.json").read_text())
    ops = json.loads((folder / "ops.json").read_text())

    tel = pd.read_csv(
        folder / "telemetry.csv",
        dtype={"asset_id": "category", "metric": "category"},
    )
    tel = tel.sort_values("ts_unix", kind="stable").reset_index(drop=True)
    tel["timestamp"] = pd.to_datetime(tel["timestamp"], utc=True)

    facilities, asset_to_fac = _index_network(network)

    ts_all = np.sort(tel["ts_unix"].unique())
    interval = int(np.median(np.diff(ts_all))) if len(ts_all) > 1 else 300

    series = {}
    for (asset, metric), g in tel.groupby(["asset_id", "metric"], observed=True, sort=False):
        s = g.set_index("ts_unix")["value"].astype(float)
        series[(str(asset), str(metric))] = s[~s.index.duplicated(keep="last")].sort_index()

    return Dataset(
        folder=folder,
        network=network,
        ops=ops,
        telemetry=tel,
        now_unix=int(ts_all[-1]),
        interval_s=interval,
        facilities=facilities,
        asset_to_facility=asset_to_fac,
        _series=series,
    )
