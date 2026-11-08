"""Dry run: act like a judge. Load each dataset, scrub through time, hit every endpoint, report errors and speed.

    python -m backend.api.dry_run                 # every folder in data/
    python -m backend.api.dry_run test            # just one (use this when EOG adds data/test)

For each dataset it prints the load time (this includes fitting the models; the target is under 30 seconds),
then calls /state, /alerts, /forecast, /plan, /plan?risk=0.95 and /model/baseline at about 30 moments spread over
the data, and counts errors and any call slower than 5 seconds. Exit code 1 if anything failed.
Never reads answer_key.json. Needs httpx for the test client: pip install httpx
"""
from __future__ import annotations

import logging
import sys
import time

from fastapi.testclient import TestClient

from . import main as app_main

SLOW_S = 5.0


def run(name: str, client: TestClient) -> bool:
    t0 = time.time()
    info = client.post(f"/load?dataset={name}").json()
    load_s = time.time() - t0
    if "error" in info:
        print(f"{name}: LOAD FAILED: {info['error']}")
        return False
    ds = app_main._cache[name]
    first = int(ds.series(next(iter(ds.facilities)), "inflow_bpd").index[0])
    last = ds.now_unix
    step = max(3600, (last - first) // 28 // 3600 * 3600)
    times = list(range(first + 12 * 3600, last + 1, step)) + [last]
    pump = next(iter(ds.facilities.values()))["pump"]["id"]
    pipe = next(iter(ds.facilities.values()))["pipeline"]["id"]
    errors, slow, calls, worst = [], 0, 0, (" ", 0.0)
    for t in times:
        for url in (f"/state?t={t}", f"/alerts?t={t}", f"/forecast?t={t}", f"/plan?t={t}", f"/plan?t={t}&risk=0.95",
                    f"/model/baseline?id={pump}&metric=flow_bpd&t={t}&hours=6",
                    f"/model/baseline?id={pipe}&metric=pressure_psi&t={t}&hours=6"):
            t1 = time.time()
            resp = client.get(url)
            dt = time.time() - t1
            calls += 1
            body = resp.json()
            if resp.status_code != 200 or (isinstance(body, dict) and "error" in body):
                errors.append((url, resp.status_code, str(body)[:90]))
            slow += dt > SLOW_S
            if dt > worst[1]:
                worst = (url.split("?")[0], dt)
    models = info.get("models", {})
    ok = not errors and load_s < 30
    print(f"{'OK  ' if ok else 'FAIL'} {name:<28} load {load_s:4.1f}s (models {models.get('status')}, "
          f"{models.get('pumps_calibrated')} pumps)  {calls} calls, {len(errors)} errors, {slow} slow, "
          f"worst {worst[0]} {worst[1]:.1f}s")
    for e in errors[:5]:
        print("     ERROR", e)
    return ok


def main(argv=None) -> int:
    logging.disable(logging.CRITICAL)
    names = list(argv if argv is not None else sys.argv[1:]) or app_main.dataset_folders()
    client = TestClient(app_main.app)
    results = [run(n, client) for n in names]
    print("\nALL CLEAN" if all(results) else "\nSOMETHING FAILED")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
