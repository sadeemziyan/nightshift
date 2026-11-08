"""M1: a learned baseline for every pump and pipeline ("what should this equipment be reading now?").

    models = fit(ds, t)                                   # one FacilityBaseline per facility, data up to t
    frame  = residuals(ds, facility_id, t, models)        # actual / expected / band / z for every reading
    pts    = chart_points(ds, asset_id, metric, t, models, hours=24)   # for GET /model/baseline

What it learns, from that facility's OWN history only (never fixed numbers, never answer_key.json):
  * for each sensor, its normal level and healthy spread in each pump state (running / not running).
    The fit ignores the most extreme points (engine.detect.robust_normal, two passes), so a fault that is
    already inside the history does not poison "normal".
  * receive flow as a function of pump flow: a robust (Huber) line. Healthy pipes deliver what the pump
    sends, so a leak shows up as receive flow far below this line.
  * the pump's expected state from the tank level and the pump's start/stop levels (the sawtooth):
    above the start level the pump should be running. A pump that is not, is stalled.
The residual score z is "how many healthy spreads away from expected", in units of that equipment's own
spread, so the same threshold means the same thing for every pump.

If anything here raises, callers fall back to the rule-based results (CLAUDE.md hard rule 7).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from backend.engine import detect as rules
from backend.engine.loader import Dataset

SENSORS = ("pflow", "pdis", "rflow", "rpsi")
# chart metric name -> (column key, asset kind)
METRIC_TO_SENSOR = {
    "flow_bpd": ("pflow", "pump"),
    "discharge_psi": ("pdis", "pump"),
    "receive_flow_bpd": ("rflow", "pipeline"),
    "pressure_psi": ("rpsi", "pipeline"),
}
UNITS = {"flow_bpd": "bpd", "discharge_psi": "psi", "receive_flow_bpd": "bpd", "pressure_psi": "psi"}
BAND_Z = 3.0  # the shaded "normal" band is +/- this many healthy spreads


@dataclass
class FacilityBaseline:
    facility_id: str
    fitted_unix: int
    running_rows: int
    normal_on: dict = field(default_factory=dict)     # sensor -> (centre, spread) while pump runs
    normal_off: dict = field(default_factory=dict)    # sensor -> (centre, spread) while pump is stopped
    rflow_slope: float = 1.0                          # receive flow = slope * pump flow (+ intercept)
    rflow_intercept: float = 0.0
    rflow_spread: float = 1.0
    ready: bool = False


def _raw_frame(ds: Dataset, facility_id: str, t: int) -> pd.DataFrame:
    fac = ds.facility(facility_id)
    pump, pipe, tank = fac["pump"], fac["pipeline"], fac["tank"]
    return pd.concat({
        "status": ds.series(pump["id"], "status", t),
        "pflow": ds.series(pump["id"], "flow_bpd", t),
        "pdis": ds.series(pump["id"], "discharge_psi", t),
        "rflow": ds.series(pipe["id"], "receive_flow_bpd", t),
        "rpsi": ds.series(pipe["id"], "pressure_psi", t),
        "level": ds.series(tank["id"], "level_pct", t),
    }, axis=1).dropna()


def expected_running(level: np.ndarray, start_pct: float, stop_pct: float, initial: bool = False,
                     status: np.ndarray | None = None) -> np.ndarray:
    """The pump's state if it followed its setpoints: at or above start_pct it should run, at or below stop_pct it should not.

    Between the two levels it keeps its state. Without `status` that state is tracked from the level alone, which gets stuck
    whenever a noisy level reading skips the exact start or stop level (a pump that starts at a reading of 69.8 against a
    start level of 70 then looked "wrong" for a whole cycle). With `status`, a pump that is observed running (1) or stopped (0)
    between the two levels is taken as being in its expected state, and a fault (2) keeps the previous expectation, so a
    pump that stalls above its start level is still reported as one that should be running."""
    out = np.empty(len(level), dtype=bool)
    state = initial
    st = None if status is None else np.asarray(status)
    for i, lv in enumerate(level):
        if lv >= start_pct:
            state = True
        elif lv <= stop_pct:
            state = False
        elif st is not None and st[i] in (0, 1):
            state = bool(st[i] == 1)
        out[i] = state
    return out


def fit(ds: Dataset, t: int | None = None) -> dict[str, FacilityBaseline]:
    from sklearn.linear_model import HuberRegressor

    t = ds.now_unix if t is None else int(t)
    models: dict[str, FacilityBaseline] = {}
    for fid in ds.facilities:
        run = rules.running_frame(ds, fid, t)
        fb = FacilityBaseline(facility_id=fid, fitted_unix=t, running_rows=len(run))
        zz = rules.z_scores(run)
        if zz is not None:
            z, normals = zz
            fb.normal_on = {k: normals[k] for k in SENSORS}
            # healthy rows: no sensor far from normal (this also drops any fault already in the history)
            clean = (z[["pflow", "pdis", "rpsi"]].abs() < 3.0).all(axis=1) & (z["loss"].abs() < 3.0)
            c = run[clean.to_numpy()]
            if len(c) >= 24:
                # Start from "the pipe delivers what the pump sends". Only learn a different line when the
                # pump's flow varies enough to tell a slope apart from noise (a pump held at one flow
                # gives a meaningless, nearly flat fit).
                res1 = c["rflow"].to_numpy() - c["pflow"].to_numpy()
                noise1 = 1.4826 * np.median(np.abs(res1 - np.median(res1)))
                if c["pflow"].std() > 5.0 * max(noise1, 1e-9):
                    try:
                        hr = HuberRegressor().fit(c[["pflow"]].to_numpy(), c["rflow"].to_numpy())
                        fb.rflow_slope, fb.rflow_intercept = float(hr.coef_[0]), float(hr.intercept_)
                    except Exception:
                        fb.rflow_slope, fb.rflow_intercept = 1.0, 0.0
            res = c["rflow"].to_numpy() - (fb.rflow_slope * c["pflow"].to_numpy() + fb.rflow_intercept)
            fb.rflow_spread = float(max(1.4826 * np.median(np.abs(res - np.median(res))), 1e-9)) if len(res) else 1.0
            fb.ready = True
        raw = _raw_frame(ds, fid, t)
        off = raw[raw["status"] == 0]
        for k in SENSORS:
            nm = rules.robust_normal(off[k]) if len(off) >= 8 else None
            if nm is not None:
                fb.normal_off[k] = nm
        models[fid] = fb
    return models


def residuals(ds: Dataset, facility_id: str, t: int | None = None, models: dict | None = None) -> pd.DataFrame:
    """One row per reading (all pump states). Columns per sensor s in SENSORS:
    s, s_exp, s_lo, s_hi, s_z; plus status, level, expected_on."""
    t = ds.now_unix if t is None else int(t)
    models = models or fit(ds, t)
    fb = models[facility_id]
    fac = ds.facility(facility_id)
    pump = fac["pump"]
    raw = _raw_frame(ds, facility_id, t)
    if raw.empty:
        return raw
    exp_on = expected_running(raw["level"].to_numpy(), pump["start_level_pct"], pump["stop_level_pct"],
                              initial=bool(raw["status"].iloc[0] == 1), status=raw["status"].to_numpy())
    out = raw.copy()
    out["expected_on"] = exp_on
    for k in SENSORS:
        on_c, on_s = fb.normal_on.get(k, (np.nan, np.nan))
        off_c, off_s = fb.normal_off.get(k, (0.0 if k in ("pflow", "rflow") else np.nan, on_s))
        # A stopped pump reads (almost) exactly zero flow, so its own spread is meaningless as a unit.
        # The healthy running spread is the unit for every state.
        off_s = max(off_s, on_s) if np.isfinite(on_s) else off_s
        centre = np.where(exp_on, on_c, off_c)
        spread = np.where(exp_on, on_s, off_s)
        if k == "rflow" and fb.ready:
            centre = np.where(exp_on, fb.rflow_slope * raw["pflow"].to_numpy() + fb.rflow_intercept, centre)
            spread = np.where(exp_on, fb.rflow_spread, spread)
        spread = np.maximum(spread, 1e-9)
        out[f"{k}_exp"] = centre
        out[f"{k}_lo"] = centre - BAND_Z * spread
        out[f"{k}_hi"] = centre + BAND_Z * spread
        out[f"{k}_z"] = (raw[k].to_numpy() - centre) / spread
    return out


def chart_points(ds: Dataset, asset_id: str, metric: str, t: int | None = None, models: dict | None = None,
                 hours: float = 24.0) -> dict:
    """Payload for GET /model/baseline (see docs/api.md)."""
    t = ds.now_unix if t is None else int(t)
    sensor, kind = METRIC_TO_SENSOR[metric]
    fid = ds.facility_of(asset_id)
    frame = residuals(ds, fid, t, models)
    frame = frame[frame.index >= t - int(hours * 3600)]
    pts = [{
        "ts_unix": int(ts),
        "actual": round(float(r[sensor]), 2),
        "expected": round(float(r[f"{sensor}_exp"]), 2),
        "lower": round(float(r[f"{sensor}_lo"]), 2),
        "upper": round(float(r[f"{sensor}_hi"]), 2),
        "score": round(float(abs(r[f"{sensor}_z"])), 2),
    } for ts, r in frame.iterrows()]
    return {"asset_id": asset_id, "metric": metric, "unit": UNITS[metric], "points": pts}
