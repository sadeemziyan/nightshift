"""Rule-based problem detection from sensor readings only (never reads answer_key.json).

    events = detect(ds)            # everything up to the end of the data
    events = detect(ds, t=1791420600)   # as if "now" were t: only data with ts_unix <= t is used

Phase 1 has the pump-failure rule. Leak and degradation rules are added in Phase 2 and plug into
DETECTORS below. Every threshold is either learned from that pump's own history or comes from
network.json / ops.json (CLAUDE.md hard rules 1 and 4).

Pump failure rule, per pump:
  fault    : pump status == 2 (EOG's fault code).                         -> flagged at once
  stalled  : pump not delivering (status != 1 or flow below a small share of THIS pump's own
             learned running flow) while the tank is above the pump's start level, seen in 2
             readings in a row. Catches a dead pump even when the test data has no status 2.
Consecutive bad readings form one event. It ends at the first healthy reading after the run.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .loader import Dataset, iso

STALL_FLOW_SHARE = 0.10   # "not delivering" = flow under 10% of the pump's own learned running flow
STALL_CONFIRM = 2         # stalled readings in a row before we call it (fault is immediate)
FAULT_STATUS = 2          # SPEC: pump status 0 stopped, 1 running, 2 fault
RUNNING_STATUS = 1


def _event_id(asset_id: str, onset_unix: int) -> str:
    return f"{asset_id}@{int(onset_unix)}"


def learned_running_flow(flow: pd.Series, status: pd.Series) -> float | None:
    """This pump's normal delivered flow: median flow over readings where it was running."""
    running = flow[(status == RUNNING_STATUS).reindex(flow.index, fill_value=False)]
    running = running[running > 0]
    return float(running.median()) if len(running) else None


def _runs(mask: np.ndarray):
    """Yield (start_idx, end_idx_exclusive) of consecutive True stretches."""
    i, n = 0, len(mask)
    while i < n:
        if mask[i]:
            j = i
            while j < n and mask[j]:
                j += 1
            yield i, j
            i = j
        else:
            i += 1


def detect_pump_failures(ds: Dataset, t: int | None = None) -> list[dict]:
    t = ds.now_unix if t is None else int(t)
    events = []
    for fid, fac in ds.facilities.items():
        pump, tank = fac["pump"], fac["tank"]
        status = ds.series(pump["id"], "status", t)
        flow = ds.series(pump["id"], "flow_bpd", t)
        level = ds.series(tank["id"], "level_pct", t)
        if status.empty or level.empty:
            continue
        df = pd.concat({"status": status, "flow": flow, "level": level}, axis=1).dropna(subset=["status", "level"])
        if df.empty:
            continue
        ts = df.index.to_numpy()

        normal_flow = learned_running_flow(df["flow"].dropna(), df["status"])
        fault = (df["status"] == FAULT_STATUS).to_numpy()
        not_delivering = (df["status"] != RUNNING_STATUS).to_numpy()
        if normal_flow:
            not_delivering = not_delivering | (df["flow"].fillna(0) < STALL_FLOW_SHARE * normal_flow).to_numpy()
        above_start = (df["level"] > pump["start_level_pct"]).to_numpy()
        stalled = not_delivering & above_start

        prev_stalled = np.concatenate([[False], stalled[:-1]])
        confirmed = fault | (stalled & prev_stalled)
        bad = fault | stalled

        for a, b in _runs(bad):
            if not confirmed[a:b].any():
                continue  # a single stalled reading is not enough
            first_conf = a + int(np.argmax(confirmed[a:b]))
            onset_unix = int(ts[a])
            ended = b < len(ts)
            end_unix = int(ts[b]) if ended else None
            run_fault = bool(fault[a:b].any())

            level_start, level_now = float(df["level"].iloc[a]), float(df["level"].iloc[b - 1])
            flow_now = df["flow"].iloc[b - 1]
            if run_fault:
                evidence = [
                    f"Pump {pump['id']} reports fault (status {FAULT_STATUS})"
                    + (f" and delivers {flow_now:.0f} bpd" if pd.notna(flow_now) else "")
                    + f" while tank {tank['id']} is at {level_now:.1f}%"
                ]
                confidence = 0.95
            else:
                evidence = [
                    f"Pump {pump['id']} is not delivering flow"
                    + (f" (normal for this pump is about {normal_flow:.0f} bpd)" if normal_flow else "")
                    + f" while tank {tank['id']} is at {level_now:.1f}%, above the pump start level "
                    f"of {pump['start_level_pct']}%"
                ]
                confidence = 0.80
            if level_now > level_start + 0.5:
                evidence.append(
                    f"Tank {tank['id']} has risen from {level_start:.1f}% to {level_now:.1f}% since the pump stopped"
                )
                confidence = min(0.99, confidence + 0.02)

            events.append({
                "event_id": _event_id(pump["id"], onset_unix),
                "system_id": fac["system_id"],
                "facility_id": fid,
                "asset_id": pump["id"],
                "category": "pump_failure",
                "status": "resolved" if ended else "ongoing",
                "onset_ts": iso(onset_unix),
                "onset_unix": onset_unix,
                "end_ts": iso(end_unix),
                "end_unix": end_unix,
                "detected_unix": int(ts[first_conf]),
                "confidence": round(confidence, 2),
                "score": None,          # filled by the learned models in Phase 2/3
                "evidence": evidence,
                "source": "rules",
            })
    return events


# Phase 2 adds detect_pipeline_leaks and detect_pump_degradation here.
DETECTORS = [detect_pump_failures]


def detect(ds: Dataset, t: int | None = None) -> list[dict]:
    """All problems seen up to unix time t (None = end of data), oldest onset first."""
    t = ds.now_unix if t is None else int(t)
    events = []
    for fn in DETECTORS:
        try:
            events.extend(fn(ds, t))
        except Exception:  # a broken detector must never crash the app (hard rule 7)
            continue
    return sorted(events, key=lambda e: (e["onset_unix"], e["asset_id"]))
