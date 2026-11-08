"""How well does M4's p10-p90 range cover what really happened? Run from the repo root:

    python -m backend.ml.forecast.check_m4 data/full_week

For every facility: fit on the first 75% of the history, then on the last 25% compare the average inflow
over the next 3 h and 6 h with the model's p10-p90 range. A good 80% range covers about 80% of cases.
These are the only M4 accuracy numbers we quote (rule: every number comes from a script).
"""
from __future__ import annotations

import sys

import numpy as np

from backend.engine.loader import load
from .forecast import QUANTILES, RECENT, fit_series, training_set


def main(argv=None) -> None:
    folder = (argv or sys.argv[1:] or ["data/full_week"])[0]
    ds = load(folder)
    print(f"M4 held-out check on {folder}: fit on first 75%, test on last 25%")
    print(f"{'facility':<16}{'cv':>7}{'cover 3h':>10}{'cover 6h':>10}{'median err':>12}{'naive err':>11}{'range 6h':>10}")
    covers = []
    for fid in ds.facilities:
        s = ds.series(fid, "inflow_bpd", ds.now_unix)
        cut = int(len(s) * 0.75)
        m = fit_series(s.iloc[:cut], fid, int(s.index[cut - 1]), ds.interval_s)
        if not m.ready:
            print(f"{fid:<16}  (not enough history: rules only)")
            continue
        row = [fid, f"{s.std() / s.mean():.3f}"]
        for h in (3.0, 6.0):
            ts = training_set(s.iloc[cut - RECENT:].to_numpy(), s.iloc[cut - RECENT:].index.to_numpy(),
                              ds.interval_s, long_mean=m.long_mean, horizons=(h,))
            if ts is None:
                row.append("-")
                continue
            _, X, y = ts
            q = np.sort(np.column_stack([m.models[k].predict(X) for k in QUANTILES]), axis=1)
            inside = float(((y >= q[:, 0]) & (y <= q[:, 2])).mean())
            row.append(f"{inside:.0%}")
            covers.append(inside)
            if h == 6.0:
                med_err = float(np.abs(np.exp(y) - np.exp(q[:, 1])).mean())
                naive_err = float(np.abs(np.exp(y) - 1.0).mean())
                width = float((np.exp(q[:, 2]) - np.exp(q[:, 0])).mean())
        print(f"{row[0]:<16}{row[1]:>7}{row[2]:>10}{row[3]:>10}{med_err:>12.4f}{naive_err:>11.4f}{width:>10.4f}")
    if covers:
        print(f"\nmean coverage of the p10-p90 range: {np.mean(covers):.0%} (target about 80%)")


if __name__ == "__main__":
    main()
