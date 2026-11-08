"""Features for M3: a short list of numbers that describe "how does this pump look right now?".

    fr  = baseline.residuals(ds, facility_id, t, models)     # M1: every reading as a score against that pump's own normal
    row = window_features(fr, t)                              # one dict of numbers, JSON-friendly

Every number is in "healthy spreads" (M1) or hours (M2), never in bpd or psi, so a window from a pump the model
has never seen looks the same as one it has. Nothing here reads answer_key.json or names a facility.

The features, in plain words:
  * <sensor>_z12 / _z36   median M1 score of the last 1 h / 3 h of running readings, for pump flow, pump discharge
                          pressure, receive flow and pipeline pressure (negative = below normal)
  * pflow_slope / rpsi_slope   how fast those scores are moving, per hour (a ramp vs a step)
  * cusum_<sensor>        M2: log(1 + biggest CUSUM total) over the last 12 h of "below normal" evidence
  * drift_h_<sensor>      M2: hours the current below-normal run has lasted
  * stall_share, fault_share   share of the last hour where the pump should run but does not / reports status 2
  * pflow_zall6, pdis_zall6    score of the last 30 min over ALL readings (a stopped pump is far below normal)
"""
from __future__ import annotations

import numpy as np

from . import drift

SENSORS = ("pflow", "pdis", "rflow", "rpsi")
Z_CLIP = 60.0          # scores beyond this are "obviously broken"; clipping keeps one huge number from dominating
RUN_TAIL_12H = 144     # readings of the running frame used for the CUSUM features (12 h at 5 min)

FEATURES = (
    ["stall_share", "fault_share", "pflow_zall6", "pdis_zall6", "n_run"]
    + [f"{c}_z12" for c in SENSORS]
    + [f"{c}_z36" for c in SENSORS]
    + ["pflow_slope", "rpsi_slope"]
    + [f"cusum_{c}" for c in SENSORS]
    + [f"drift_h_{c}" for c in SENSORS]
)


def _med(x, minimum: int, default: float = 0.0) -> float:
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    return float(np.clip(np.median(x), -Z_CLIP, Z_CLIP)) if len(x) >= minimum else default


def _slope_per_hour(index, z) -> float:
    z = np.clip(np.asarray(z, dtype=float), -Z_CLIP, Z_CLIP)
    ok = np.isfinite(z)
    if ok.sum() < 8:
        return 0.0
    idx = np.asarray(index, dtype=float)[ok]
    x = (idx - idx[0]) / 3600.0
    if np.ptp(x) <= 0:
        return 0.0
    return float(np.polyfit(x, z[ok], 1)[0])


def window_features(fr, t: int, interval_s: int = 300) -> dict | None:
    """Features for the decision time t from the M1 residual frame fr (uses rows with index <= t only)."""
    w = fr[fr.index <= t]
    if len(w) < 12:
        return None
    run = w[w["status"] == 1]
    last12, last6 = w.tail(12), w.tail(6)
    r12, r36, r144 = run.tail(12), run.tail(36), run.tail(RUN_TAIL_12H)

    f: dict = {
        "stall_share": float(((last12["status"] != 1) & last12["expected_on"]).mean()),
        "fault_share": float((last12["status"] == 2).mean()),
        "pflow_zall6": _med(last6["pflow_z"], 1),
        "pdis_zall6": _med(last6["pdis_z"], 1),
        "n_run": float(len(r36)),
    }
    for c in SENSORS:
        f[f"{c}_z12"] = _med(r12[f"{c}_z"], 4)
        f[f"{c}_z36"] = _med(r36[f"{c}_z"], 8)
    idx36 = r36.index.to_numpy()
    f["pflow_slope"] = _slope_per_hour(idx36, r36["pflow_z"].to_numpy())
    f["rpsi_slope"] = _slope_per_hour(idx36, r36["rpsi_z"].to_numpy())
    for c in SENSORS:
        z = -np.clip(np.nan_to_num(r144[f"{c}_z"].to_numpy(dtype=float), nan=0.0), -Z_CLIP, Z_CLIP)
        if len(z) >= 8:
            s, _ = drift.cusum(z)
            run_len = 0
            for v in s[::-1]:
                if v > 0:
                    run_len += 1
                else:
                    break
            f[f"cusum_{c}"] = float(np.log1p(s.max()))
            f[f"drift_h_{c}"] = run_len * interval_s / 3600.0
        else:
            f[f"cusum_{c}"], f[f"drift_h_{c}"] = 0.0, 0.0
    return f


def as_matrix(rows: list[dict]) -> np.ndarray:
    return np.array([[r[k] for k in FEATURES] for r in rows], dtype=float)
