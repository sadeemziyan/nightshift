"""M4: shutdown forecaster. Adds a range to the countdown.

    model = fit_series(inflow_series, facility_id, t)         # one small model per facility
    rows  = add_ranges(ds, t, forecast_rows)                  # fills hours_to_limit p10/p90 + inflow_range

What it learns, from the facility's OWN inflow history up to t (never fixed numbers, never answer_key.json):
how the average inflow over the next h hours compares with the inflow right now. That ratio is learned with
quantile regression (gradient-boosted trees, quantiles 0.1 / 0.5 / 0.9) on the time of day, the horizon h and
how far "now" sits from the facility's usual level. Windows in which the wells were off (a tank that already
hit shutdown) are left out, so the model learns normal inflow uncertainty, not shutdown behavior.

From the ratio quantiles the cumulative inflow over time is
    barrels in by h  =  inflow now * ratio_q(h) * h / 24
and the time the tank reaches its limit is where that crosses the room left:
    shutdown_p10 = high-inflow case (q90), shutdown_p90 = low-inflow case (q10).
The median (p50) is still the straight-line number from engine.forecast, so with steady inflow all three
collapse to EOG's example (336 bbl of room at 75 bbl/h = 4.5 hours).

If anything here raises, the row keeps p10/p90 = null and the app runs on rules (CLAUDE.md hard rule 7).
"""
from __future__ import annotations

import logging
import time
from collections import OrderedDict
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

QUANTILES = (0.1, 0.5, 0.9)
HORIZONS_H = (0.5, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0)
RECENT = 6            # readings averaged for "inflow now" (same as engine.forecast.RATE_WINDOW)
STRIDE = 3            # every 3rd reading is a training anchor
MIN_ROWS = 120        # fewer training rows than this: no model, rules only
MAX_HORIZON_H = 12.0
GRID_STEP_H = 0.1
_CACHE: "OrderedDict[tuple, InflowModel]" = OrderedDict()


@dataclass
class InflowModel:
    facility_id: str
    fitted_unix: int
    interval_s: int
    rows: int = 0
    long_mean: float = 0.0
    models: dict = field(default_factory=dict)     # quantile -> fitted regressor
    ready: bool = False


def _features(h, ts_unix, recent, long_mean) -> np.ndarray:
    ts = np.asarray(ts_unix, float)
    h = np.broadcast_to(np.asarray(h, float), ts.shape)
    recent = np.broadcast_to(np.asarray(recent, float), ts.shape)
    hod = ((ts + h * 1800.0) / 3600.0) % 24.0           # hour of day at the middle of the window
    ang = 2.0 * np.pi * hod / 24.0
    return np.column_stack([h, np.sin(ang), np.cos(ang), recent / long_mean])


def training_set(values, index, interval_s: int, long_mean: float | None = None, horizons=HORIZONS_H):
    """(long_mean, X, y): one row per anchor reading and horizon. y = log(future mean / recent mean)."""
    v = np.asarray(values, float)
    idx = np.asarray(index)
    if len(v) < RECENT + 2:
        return None
    med = float(np.median(v))
    if med <= 0:
        return None
    valid = v > 0.5 * med                                # wells off (shutdown) readings are not "normal"
    if long_mean is None:
        long_mean = float(v[valid].mean())
    vv = np.where(valid, v, 0.0)
    cs = np.concatenate([[0.0], np.cumsum(vv)])
    cn = np.concatenate([[0.0], np.cumsum(valid.astype(float))])
    n = len(v)
    X, y = [], []
    for h in horizons:
        steps = max(1, int(round(h * 3600.0 / interval_s)))
        anchors = np.arange(RECENT - 1, n - steps, STRIDE)
        if not len(anchors):
            continue
        ok = ((cn[anchors + 1] - cn[anchors + 1 - RECENT]) == RECENT) & \
             ((cn[anchors + 1 + steps] - cn[anchors + 1]) == steps)
        a = anchors[ok]
        if not len(a):
            continue
        recent = (cs[a + 1] - cs[a + 1 - RECENT]) / RECENT
        future = (cs[a + 1 + steps] - cs[a + 1]) / steps
        X.append(_features(h, idx[a].astype(float), recent, long_mean))
        y.append(np.log(future / recent))
    if not X:
        return None
    return long_mean, np.vstack(X), np.concatenate(y)


def fit_series(series: pd.Series, facility_id: str, t: int, interval_s: int = 300) -> InflowModel:
    from sklearn.ensemble import GradientBoostingRegressor

    t = int(t)
    s = series[series.index <= t].dropna()
    model = InflowModel(facility_id=facility_id, fitted_unix=t, interval_s=interval_s)
    ts = training_set(s.to_numpy(), s.index.to_numpy(), interval_s)
    if ts is None or len(ts[2]) < MIN_ROWS:
        return model
    long_mean, X, y = ts
    for q in QUANTILES:
        gbr = GradientBoostingRegressor(loss="quantile", alpha=q, n_estimators=40, max_depth=2,
                                        learning_rate=0.1, subsample=0.8, min_samples_leaf=10,
                                        random_state=0)
        model.models[q] = gbr.fit(X, y)
    model.rows, model.long_mean, model.ready = len(y), long_mean, True
    return model


def ratio_quantiles(model: InflowModel, t: int, recent: float, hours) -> np.ndarray:
    """Rows of (q10, q50, q90): average inflow over the next `hours` divided by inflow now."""
    h = np.atleast_1d(np.asarray(hours, float))
    X = _features(h, np.full(len(h), float(t)), recent, model.long_mean)
    out = np.column_stack([np.exp(model.models[q].predict(X)) for q in QUANTILES])
    out.sort(axis=1)                                     # quantiles must not cross
    return out


def _cross(volume: np.ndarray, grid: np.ndarray, room: float):
    hit = volume >= room
    if not hit.any():
        return None
    i = int(np.argmax(hit))
    if i == 0:
        return float(grid[0] * room / volume[0])
    v0, v1, g0, g1 = volume[i - 1], volume[i], grid[i - 1], grid[i]
    return float(g0 + (g1 - g0) * (room - v0) / (v1 - v0))


def shutdown_range(model: InflowModel, t: int, recent: float, inflow_bpd: float, room_bbl: float,
                   p50_hours: float, repair_hours: float) -> dict:
    """{"p10": hours, "p90": hours or None}: early case (high inflow) and late case (low inflow)."""
    if room_bbl <= 0:
        return {"p10": 0.0, "p90": 0.0}
    top = min(MAX_HORIZON_H, max(repair_hours, p50_hours * 1.5) + 1.0)
    grid = np.arange(GRID_STEP_H, top + 1e-9, GRID_STEP_H)
    r = ratio_quantiles(model, t, recent, grid)
    early = _cross(inflow_bpd * r[:, 2] * grid / 24.0, grid, room_bbl)
    late = _cross(inflow_bpd * r[:, 0] * grid / 24.0, grid, room_bbl)
    return {"p10": p50_hours if early is None else min(early, p50_hours),
            "p90": None if late is None else max(late, p50_hours)}


def _model_for(ds, facility_id: str, t: int) -> InflowModel:
    t_fit = int(t) - int(t) % 21600       # refit at most every 6 h; uses only data before t
    key = (str(ds.folder), facility_id, t_fit)
    if key not in _CACHE:
        _CACHE[key] = fit_series(ds.series(facility_id, "inflow_bpd", t_fit), facility_id, t_fit, ds.interval_s)
        while len(_CACHE) > 80:
            _CACHE.popitem(last=False)
    return _CACHE[key]


def fit_all(ds, t: int | None = None) -> dict:
    """Fit M4 for every facility of the loaded dataset (called at /load). Never raises."""
    t = ds.now_unix if t is None else int(t)
    t0 = time.time()
    ready = 0
    for fid in ds.facilities:
        try:
            ready += int(_model_for(ds, fid, t).ready)
        except Exception:
            log.exception("M4 fit failed for %s; that facility stays on rules", fid)
    return {"seconds": round(time.time() - t0, 2), "ready": ready, "total": len(ds.facilities)}


def add_ranges(ds, t: int, rows: list) -> list:
    """Copies of the forecast rows with hours_to_limit p10/p90 and an inflow_range filled in."""
    out = []
    for row in rows:
        new = {**row, "hours_to_limit": dict(row["hours_to_limit"])}
        try:
            m = _model_for(ds, row["facility_id"], t)
            if m.ready:
                series = ds.series(row["facility_id"], "inflow_bpd", t).tail(RECENT)
                recent = float(series.mean())
                repair_h = float(row["repair_hours_remaining"])
                H = max(0.5, min(MAX_HORIZON_H, repair_h))
                q = ratio_quantiles(m, t, recent, [H])[0]
                new["inflow_range"] = {"horizon_h": round(H, 2), "ratio_p10": round(float(q[0]), 4),
                                       "ratio_p50": round(float(q[1]), 4), "ratio_p90": round(float(q[2]), 4)}
                p50 = row["hours_to_limit"]["p50"]
                if p50 is not None and not row["already_shut_in"]:
                    room = (row["shutdown_pct"] - row["level_pct"]) / 100.0 * row["capacity_bbl"]
                    rng = shutdown_range(m, t, recent, row["inflow_bpd"], room, p50, repair_h)
                    new["hours_to_limit"]["p10"] = round(rng["p10"], 2)
                    new["hours_to_limit"]["p90"] = None if rng["p90"] is None else round(rng["p90"], 2)
        except Exception:
            log.exception("M4 range failed for %s; keeping the rule-based countdown", row["facility_id"])
        out.append(new)
    return out
