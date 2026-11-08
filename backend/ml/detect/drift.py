"""M2: change-point detection (CUSUM) on the M1 scores.

    s, alarm_idx = cusum(z)                         # z: M1 scores where bigger = worse
    onset_unix   = estimate_onset(ts, z, alarm_idx) # when the drift most likely began
    score        = drift_score(s_now)               # 0..1, grows (log scale) as the evidence builds

CUSUM keeps a running total of "how much worse than normal, beyond a small allowance k", resets to zero
whenever the equipment looks healthy, and alarms when the total passes h. The last reset before the alarm
is the change point. For a slow ramp that point sits a little after the true start (the first few
readings are inside the noise), so estimate_onset also fits a straight line through the drifting stretch
and reports where it crosses zero. Both are returned so callers (and the offline check) can compare them.
All quantities are in healthy spreads, so nothing here depends on a plant number.
"""
from __future__ import annotations

import numpy as np

K_ALLOWANCE = 1.0   # CUSUM allowance, in healthy spreads (absorbs a slightly off-centre normal)
H_ALARM = 5.0       # CUSUM alarm level
RAMP_MIN_POINTS = 8
RAMP_LOOKBACK = 36  # a ramp estimate may sit up to this many readings (3 h) before the CUSUM change point


def cusum(z: np.ndarray, k: float = K_ALLOWANCE, h: float = H_ALARM):
    """One-sided CUSUM for "z drifting up". Returns (S, first_alarm_index or None)."""
    s = np.zeros(len(z))
    total = 0.0
    first = None
    for i, v in enumerate(np.nan_to_num(np.asarray(z, dtype=float), nan=0.0)):
        total = max(0.0, total + v - k)
        s[i] = total
        if first is None and total > h:
            first = i
    return s, first


def change_point(s: np.ndarray, alarm_idx: int) -> int:
    """Index where the CUSUM last sat at zero before the alarm (the drift starts just after it)."""
    i = alarm_idx
    while i > 0 and s[i - 1] > 0:
        i -= 1
    return i


def estimate_onset(ts: np.ndarray, z: np.ndarray, alarm_idx: int, end_idx: int | None = None) -> dict:
    """{"cusum": unix, "ramp": unix or None}: two estimates of when the drift began."""
    s, _ = cusum(z)
    cp = change_point(s, alarm_idx)
    out = {"cusum": int(ts[cp]), "ramp": None}
    end = len(z) if end_idx is None else min(end_idx, len(z))
    lo, hi = cp, end
    if hi - lo >= RAMP_MIN_POINTS:
        x = (ts[lo:hi] - ts[lo]).astype(float)
        y = np.asarray(z[lo:hi], dtype=float)
        ok = np.isfinite(y)
        if ok.sum() >= RAMP_MIN_POINTS and np.ptp(x[ok]) > 0:
            slope, intercept = np.polyfit(x[ok], y[ok], 1)
            if slope > 0:
                t0 = ts[lo] - intercept / slope          # where the fitted line crosses z = 0
                if ts[max(0, lo - RAMP_LOOKBACK)] <= t0 <= ts[alarm_idx]:
                    out["ramp"] = int(round(t0))
    return out


def drift_score(s_now: float, h: float = H_ALARM) -> float:
    """0..1, growing with the CUSUM total on a log scale: 0 at rest, about 0.15 at the alarm line,
    about 0.5 at ten times the alarm line, 1.0 at ninety-nine times it."""
    return float(min(1.0, np.log10(1.0 + max(0.0, s_now) / h) / 2.0))
