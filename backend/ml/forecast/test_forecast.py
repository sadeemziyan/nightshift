"""Tests for M4 (forecast.py). Run from the repo root:

    python -m backend.ml.forecast.test_forecast

EOG's example: an 800 bbl tank, 400 bbl in it, shutdown at 92% (736 bbl), 75 bbl/h of water coming in.
Room left = 336 bbl, so the tank hits shutdown in 336 / 75 = 4.48 hours. With steady inflow the p10 and p90
must collapse onto that number.
"""
import numpy as np
import pandas as pd

from .forecast import fit_series, ratio_quantiles, shutdown_range

INTERVAL = 300
N = 7 * 288          # one week of 5-minute readings
T = 1_791_000_000
ROOM, INFLOW = 336.0, 1800.0     # 75 bbl/h
EXACT = ROOM / INFLOW * 24.0     # 4.48 h


def series(noise: float, seed: int = 1, outages=()) -> pd.Series:
    rng = np.random.default_rng(seed)
    v = INFLOW * (1 + noise * rng.standard_normal(N))
    for a, b in outages:
        v[a:b] = 0.0
    idx = T - INTERVAL * (N - 1) + INTERVAL * np.arange(N)
    return pd.Series(v, index=idx)


def test_steady_inflow_collapses_to_eog_example():
    s = series(0.001)
    m = fit_series(s, "F", int(s.index[-1]), INTERVAL)
    assert m.ready
    rng = shutdown_range(m, int(s.index[-1]), INFLOW, INFLOW, ROOM, EXACT, 6.0)
    assert abs(EXACT - 4.48) < 0.01
    assert abs(rng["p10"] - EXACT) / EXACT < 0.01
    assert abs(rng["p90"] - EXACT) / EXACT < 0.01
    assert rng["p10"] <= EXACT <= rng["p90"]


def test_noisier_inflow_gives_a_wider_range():
    def width(noise):
        s = series(noise)
        m = fit_series(s, "F", int(s.index[-1]), INTERVAL)
        r = shutdown_range(m, int(s.index[-1]), INFLOW, INFLOW, ROOM, EXACT, 6.0)
        return r["p90"] - r["p10"]
    assert width(0.15) > width(0.001)


def test_quantiles_are_ordered_and_near_one_when_steady():
    s = series(0.002)
    m = fit_series(s, "F", int(s.index[-1]), INTERVAL)
    q = ratio_quantiles(m, int(s.index[-1]), INFLOW, [1.0, 3.0, 6.0])
    assert (q[:, 0] <= q[:, 1]).all() and (q[:, 1] <= q[:, 2]).all()
    assert np.abs(q - 1.0).max() < 0.02


def test_shutdown_windows_are_not_learned_as_normal():
    # a day when the wells were off (tank hit shutdown) must not widen the range
    s = series(0.001, outages=[(600, 700)])
    m = fit_series(s, "F", int(s.index[-1]), INTERVAL)
    assert m.ready
    r = shutdown_range(m, int(s.index[-1]), INFLOW, INFLOW, ROOM, EXACT, 6.0)
    assert abs(r["p10"] - EXACT) / EXACT < 0.02 and abs(r["p90"] - EXACT) / EXACT < 0.02


def test_already_full_tank_has_zero_hours():
    s = series(0.001)
    m = fit_series(s, "F", int(s.index[-1]), INTERVAL)
    assert shutdown_range(m, int(s.index[-1]), INFLOW, INFLOW, 0.0, 0.0, 6.0) == {"p10": 0.0, "p90": 0.0}


def test_too_little_history_means_rules_only():
    s = series(0.001).iloc[:40]
    m = fit_series(s, "F", int(s.index[-1]), INTERVAL)
    assert not m.ready


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("ok  ", t.__name__)
    print(f"\n{len(tests)} tests passed")
