"""Rule-based problem detection from sensor readings only (never reads answer_key.json).

    events = detect(ds)            # everything up to the end of the data
    events = detect(ds, t=1791420600)   # as if "now" were t: only data with ts_unix <= t is used

Three rules plug into DETECTORS below: pump failure, pipeline leak, pump degradation. Every
threshold is either learned from that equipment's own history ("normal" and its healthy spread,
see robust_normal) or comes from network.json / ops.json (CLAUDE.md hard rules 1 and 4). The few
constants in this file are unit-free statistics (z-scores, window lengths), not plant numbers.

Pump failure rule, per pump:
  fault    : pump status == 2 (EOG's fault code).                         -> flagged at once
  stalled  : pump not delivering (status != 1 or flow below a small share of THIS pump's own
             learned running flow) while the tank is above the pump's start level, seen in 2
             readings in a row. Catches a dead pump even when the test data has no status 2.
Consecutive bad readings form one event. It ends at the first healthy reading after the run.
"""
from __future__ import annotations

import logging
from statistics import NormalDist

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


# --------------------------------------------------------------------------------------
# Slow problems: pipeline leak and pump degradation
# --------------------------------------------------------------------------------------
# Signatures seen in the labelled week (docs/sensors.md):
#   pipeline_leak    pump flow stays normal, but the pipeline receives less than the pump sends
#                    and its pressure sags, growing for many hours.
#   pump_degradation the pump's own flow (and discharge pressure) drift below its normal while
#                    the pipeline just follows the pump (receive flow ~ pump flow, pressure normal).
# Everything is judged only while the pump is running, as a z-score against THAT equipment's
# own healthy readings.
SMOOTH_WINDOW = 12     # running readings in the rolling median (about an hour of running time)
Z_ALARM = 3.0          # smoothed z beyond this raises the alarm (healthy readings stay below about 1.1)
Z_CLEAR = 1.5          # smoothed z back inside this = the stretch has ended / began here
MIN_RUNNING = 48       # running readings needed before "normal" is trusted (about 4 h)
FIRST_LOOK_COVERAGE = 0.25   # pass 1 looks for the densest quarter of readings (see robust_normal)
END_CLEAN_READINGS = 4  # the median of this many readings back inside normal means the problem has ended


def robust_normal(values, coverage: float = 0.5) -> tuple[float, float] | None:
    """(centre, spread) of the healthy readings, ignoring extreme points.

    "Shorth" estimator: find the tightest window holding `coverage` of the readings and use its centre
    and width. Healthy readings are tight and dense while a fault is spread out, so the densest window
    sits on the healthy cluster even when a fault covers a third of the history. A small coverage
    (a quarter) is used for the first look when a fault may cover most of a short history.
    Spread is the equivalent standard deviation of that window.
    """
    x = np.sort(np.asarray(values, dtype=float))
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 8:
        return None
    h = max(3, int(np.ceil(coverage * n)))
    widths = x[h - 1:] - x[: n - h + 1]
    i = int(np.argmin(widths))
    centre = float(np.median(x[i: i + h]))
    half_normal_z = _ndtri((1.0 + coverage) / 2.0)   # window of `coverage` mass covers +/- this many sd
    spread = float(widths[i] / 2.0 / half_normal_z)
    return centre, max(spread, 1e-9 * max(1.0, abs(centre)))


def _ndtri(p: float) -> float:
    return NormalDist().inv_cdf(p)


def running_frame(ds: Dataset, facility_id: str, t: int) -> pd.DataFrame:
    """Readings (up to t) from the moments the facility's pump was running, one row per time."""
    fac = ds.facility(facility_id)
    pump, pipe = fac["pump"], fac["pipeline"]
    df = pd.concat({
        "status": ds.series(pump["id"], "status", t),
        "pflow": ds.series(pump["id"], "flow_bpd", t),
        "pdis": ds.series(pump["id"], "discharge_psi", t),
        "rflow": ds.series(pipe["id"], "receive_flow_bpd", t),
        "rpsi": ds.series(pipe["id"], "pressure_psi", t),
    }, axis=1).dropna()
    df = df[df["status"] == RUNNING_STATUS].copy()
    df["loss"] = (df["pflow"] - df["rflow"]) / df["pflow"].where(df["pflow"] > 0)
    return df.dropna()


SIGNALS = (("pflow", -1), ("pdis", -1), ("rpsi", -1), ("loss", +1))  # (signal, direction that means "worse")


def _z_against(df: pd.DataFrame, fit_rows: np.ndarray, coverage: float = 0.5):
    """z of every reading against the normal learned from only the rows in fit_rows."""
    normals, z = {}, {}
    for col in ("pflow", "pdis", "rflow", "rpsi", "loss"):
        nm = robust_normal(df[col].to_numpy()[fit_rows], coverage)
        if nm is None:
            return None
        if col == "loss":
            # Conservation of water: healthy equipment delivers what the pump sends, so the centre of
            # "share lost on the way" is zero by physics. Only its noise level is learned per pipeline.
            nm = (0.0, nm[1])
        normals[col] = nm
        z[col] = (df[col] - nm[0]) / nm[1]
    return pd.DataFrame(z, index=df.index), normals


def z_scores(df: pd.DataFrame) -> tuple[pd.DataFrame, dict] | None:
    """Per-signal z against this equipment's own normal. Returns (z frame, {signal: (centre, spread)}).

    Two passes so a fault in progress cannot pull "normal" towards itself: pass 1 learns normal from
    everything (robustly), finds the stretches that already look faulty, pass 2 relearns normal from
    the remaining readings only.
    """
    if len(df) < MIN_RUNNING:
        return None
    first = _z_against(df, np.ones(len(df), dtype=bool), coverage=FIRST_LOOK_COVERAGE)
    if first is None:
        return None
    z, normals = first
    hot = np.zeros(len(df), dtype=bool)
    for col, sign in SIGNALS:
        for lo, _, hi in stretches(sign * _smooth(z[col]).to_numpy(), raw=sign * z[col].to_numpy()):
            hot[max(0, lo - SMOOTH_WINDOW): hi] = True
    clean = ~hot
    if hot.any() and clean.sum() >= MIN_RUNNING:
        second = _z_against(df, clean)
        if second is not None:
            z, normals = second
    return z, normals


def _smooth(z: pd.Series) -> pd.Series:
    return z.rolling(SMOOTH_WINDOW, min_periods=SMOOTH_WINDOW).median()


def stretches(score: np.ndarray, alarm: float | None = None, clear: float | None = None, raw: np.ndarray | None = None):
    """Yield (onset_idx, alarm_idx, end_idx_exclusive) for each run where the smoothed `score`
    (bigger = worse) reaches `alarm`.

    The onset is where the smoothed score first rose above `clear`. The run ends at the first window of
    END_CLEAN_READINGS unsmoothed readings whose median is back below `clear` (repaired equipment
    recovers abruptly, so this is quick and, inside a real fault, practically never happens by chance).
    """
    alarm = Z_ALARM if alarm is None else alarm
    clear = Z_CLEAR if clear is None else clear
    s = np.nan_to_num(score, nan=-np.inf)
    r = s if raw is None else np.nan_to_num(raw, nan=-np.inf)
    hot = s >= alarm
    elevated = s >= clear
    # median of END_CLEAN_READINGS raw readings, so one noisy reading cannot keep a repaired problem open
    med = pd.Series(r).rolling(END_CLEAN_READINGS).median().to_numpy()
    n, i = len(s), 0
    while i < n:
        if not hot[i]:
            i += 1
            continue
        a = i
        lo = a
        while lo > 0 and elevated[lo - 1]:
            lo -= 1
        hi = n
        k = a
        while k + END_CLEAN_READINGS <= n:
            if med[k + END_CLEAN_READINGS - 1] < clear:
                hi = k
                break
            k += 1
        yield lo, a, hi
        i = max(hi, a + 1)
        while i < n and hot[i] and hi < n:   # the smoothed score lags the repair; do not re-open the same problem
            i += 1


def _slow_event(ds, fac, asset_id, category, df, onset_i, alarm_i, end_i, confidence, evidence):
    ts = df.index.to_numpy()
    ended = end_i < len(ts)
    onset_unix = int(ts[onset_i])
    end_unix = int(ts[end_i]) if ended else None
    return {
        "event_id": _event_id(asset_id, onset_unix),
        "system_id": fac["system_id"],
        "facility_id": fac["id"],
        "asset_id": asset_id,
        "category": category,
        "status": "resolved" if ended else "ongoing",
        "onset_ts": iso(onset_unix),
        "onset_unix": onset_unix,
        "end_ts": iso(end_unix),
        "end_unix": end_unix,
        "detected_unix": int(ts[alarm_i]),
        "confidence": round(float(confidence), 2),
        "score": None,
        "evidence": evidence,
        "source": "rules",
    }


def _confidence(peak_z: float, corroborated: bool) -> float:
    """0.5 at the alarm line, rising towards 0.99 as the evidence grows; +0.05 if a second signal agrees."""
    base = 0.5 + 0.49 * (1.0 - np.exp(-(max(peak_z, Z_ALARM) - Z_ALARM + 1.0) / 6.0))
    return min(0.99, base + (0.05 if corroborated else 0.0))


def _hours(df, a, b) -> float:
    ts = df.index.to_numpy()
    return float((ts[min(b, len(ts)) - 1] - ts[a]) / 3600.0)


def detect_pipeline_leaks(ds: Dataset, t: int | None = None) -> list[dict]:
    t = ds.now_unix if t is None else int(t)
    events = []
    for fid, fac in ds.facilities.items():
        df = running_frame(ds, fid, t)
        zz = z_scores(df)
        if zz is None:
            continue
        z, nm = zz
        zs_psi = _smooth(z["rpsi"]).to_numpy()       # pressure at the disposal end: leak pushes it DOWN
        zs_loss = _smooth(z["loss"]).to_numpy()      # share of pumped water that never arrives: leak pushes UP
        score = np.fmax(-zs_psi, zs_loss)            # worst of the two, bigger = worse
        pipe, pump = fac["pipeline"], fac["pump"]
        for lo, a, hi in stretches(score, raw=np.fmax(-z["rpsi"].to_numpy(), z["loss"].to_numpy())):
            peak_psi = float(np.nanmax(-zs_psi[lo:hi]))
            peak_loss = float(np.nanmax(zs_loss[lo:hi]))
            psi_drop = nm["rpsi"][0] - float(df["rpsi"].iloc[max(lo, hi - SMOOTH_WINDOW):hi].median())
            loss_pct = 100.0 * (float(df["loss"].iloc[max(lo, hi - SMOOTH_WINDOW):hi].median()) - nm["loss"][0])
            ev = [
                f"Pipeline {pipe['id']} pressure is {psi_drop:.0f} psi below its learned normal "
                f"({nm['rpsi'][0]:.0f} psi) for {_hours(df, lo, hi):.1f} h of pump running time",
                f"Only {100 - loss_pct:.1f}% of the water pump {pump['id']} sends is arriving at the disposal site",
            ]
            if peak_psi >= Z_ALARM and peak_loss >= Z_ALARM:
                ev.append("Pressure drop and flow loss agree, which points to a leak between pump and disposal site")
            conf = _confidence(max(peak_psi, peak_loss), corroborated=(peak_psi >= Z_ALARM and peak_loss >= Z_ALARM))
            events.append(_slow_event(ds, fac, pipe["id"], "pipeline_leak", df, lo, a, hi, conf, ev))
    return events


def detect_pump_degradation(ds: Dataset, t: int | None = None) -> list[dict]:
    t = ds.now_unix if t is None else int(t)
    events = []
    for fid, fac in ds.facilities.items():
        df = running_frame(ds, fid, t)
        zz = z_scores(df)
        if zz is None:
            continue
        z, nm = zz
        zs_flow = _smooth(z["pflow"]).to_numpy()     # pump output: wear pushes it DOWN
        zs_dis = _smooth(z["pdis"]).to_numpy()       # discharge pressure falls with it
        pump = fac["pump"]
        for lo, a, hi in stretches(-zs_flow, raw=-z["pflow"].to_numpy()):
            # A leak lowers pipeline pressure while the pump stays normal; wear is the pump itself.
            peak_flow = float(np.nanmax(-zs_flow[lo:hi]))
            peak_dis = float(np.nanmax(-zs_dis[lo:hi]))
            tail = slice(max(lo, hi - SMOOTH_WINDOW), hi)
            flow_now = float(df["pflow"].iloc[tail].median())
            drop_pct = 100.0 * (nm["pflow"][0] - flow_now) / nm["pflow"][0]
            ev = [
                f"Pump {pump['id']} moves {flow_now:.0f} bpd, {drop_pct:.1f}% below its learned normal "
                f"({nm['pflow'][0]:.0f} bpd), and the shortfall has grown over {_hours(df, lo, hi):.1f} h of running time"
            ]
            corroborated = peak_dis >= Z_ALARM
            if corroborated:
                ev.append(f"Discharge pressure is also falling ({nm['pdis'][0] - float(df['pdis'].iloc[tail].median()):.0f} psi below normal)")
            conf = _confidence(peak_flow, corroborated)
            events.append(_slow_event(ds, fac, pump["id"], "pump_degradation", df, lo, a, hi, conf, ev))
    return events


DETECTORS = [detect_pump_failures, detect_pipeline_leaks, detect_pump_degradation]


def detect(ds: Dataset, t: int | None = None) -> list[dict]:
    """All problems seen up to unix time t (None = end of data), oldest onset first."""
    t = ds.now_unix if t is None else int(t)
    events = []
    for fn in DETECTORS:
        try:
            events.extend(fn(ds, t))
        except Exception:  # a broken detector must never crash the app (hard rule 7)
            logging.getLogger(__name__).exception("detector %s failed; skipping it", fn.__name__)
            continue
    return sorted(events, key=lambda e: (e["onset_unix"], e["asset_id"]))
