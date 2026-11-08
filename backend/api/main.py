"""Nightshift API. Contract: docs/api.md. Run from the repo root:

    uvicorn backend.api.main:app --reload

The API never reads answer_key.json. Everything is computed from the loaded dataset's
network.json, ops.json and telemetry.csv up to the time `t` (unix seconds).
"""
from __future__ import annotations

import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.api.notify import send_text
from backend.engine.detect import detect
from backend.engine.forecast import forecast
from backend.engine.loader import Dataset, iso, load
from backend.ml.detect import baseline as m1
from backend.ml.detect import enrich
from backend.ml.forecast import forecast as m4
from backend.optimizer.system import plan_all

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"

log = logging.getLogger(__name__)

app = FastAPI(title="Nightshift API")

# Lets the React app (Vite runs on port 5173) call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---- errors are always {"error": "message"} ---------------------------------
@app.exception_handler(StarletteHTTPException)
async def _http_error(_, exc):
    return JSONResponse({"error": str(exc.detail)}, status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def _bad_request(_, exc):
    first = exc.errors()[0] if exc.errors() else {}
    where = ".".join(str(x) for x in first.get("loc", []) if x != "query")
    return JSONResponse({"error": f"bad request: {where} {first.get('msg', '')}".strip()}, status_code=422)


@app.exception_handler(Exception)
async def _server_error(_, exc):
    return JSONResponse({"error": f"{type(exc).__name__}: {exc}"}, status_code=500)


# ---- loaded dataset ---------------------------------------------------------
_lock = threading.Lock()
_cache: dict[str, Dataset] = {}
_current: dict[str, str | None] = {"name": None}
_results: dict[tuple, object] = {}     # small memo so the UI can poll without recomputing
_model_info: dict[str, dict] = {}      # per dataset: how the model fit at /load went


def dataset_folders() -> list[str]:
    if not DATA_DIR.exists():
        return []
    return sorted(p.name for p in DATA_DIR.iterdir()
                  if p.is_dir() and (p / "network.json").exists() and (p / "telemetry.csv").exists())


def _last_ts_unix(folder: Path) -> int | None:
    """Last ts_unix in telemetry.csv without reading the whole file."""
    path = folder / "telemetry.csv"
    with open(path, "rb") as f:
        f.seek(0, 2)
        f.seek(max(0, f.tell() - 4096))
        lines = [ln for ln in f.read().decode("utf-8", "ignore").splitlines() if ln.strip()]
    for ln in reversed(lines):
        parts = ln.split(",")
        if len(parts) >= 2 and parts[1].isdigit():
            return int(parts[1])
    return None


def current() -> Dataset:
    name = _current["name"]
    if name is None or name not in _cache:
        raise HTTPException(400, "no dataset loaded: call POST /load?dataset=<id> first (see GET /datasets)")
    return _cache[name]


def _t(ds: Dataset, t: int | None) -> int:
    return ds.now_unix if t is None else int(t)


def _memo(kind: str, ds: Dataset, key: tuple, fn):
    k = (kind, ds.folder.name, *key)
    if k not in _results:
        if len(_results) > 400:
            _results.clear()
        _results[k] = fn()
    return _results[k]


# ---- datasets ---------------------------------------------------------------
@app.get("/")
def hello():
    return {"status": "ok", "app": "nightshift", "loaded": _current["name"]}


@app.get("/datasets")
def datasets():
    out = []
    for name in dataset_folders():
        now = _last_ts_unix(DATA_DIR / name)
        out.append({"id": name, "now_unix": now, "now_ts": iso(now),
                    "loaded": name == _current["name"]})
    return {"datasets": out}


@app.post("/load")
def load_dataset(dataset: str = Query(...)):
    if dataset not in dataset_folders():
        raise HTTPException(404, f"unknown dataset {dataset!r}; options: {', '.join(dataset_folders()) or 'none found in data/'}")
    with _lock:
        if dataset not in _cache:
            _cache[dataset] = load(str(DATA_DIR / dataset))
        _current["name"] = dataset
    ds = _cache[dataset]
    info = _fit_models(ds)
    return {**{k: v for k, v in ds.summary().items()},
            "models": {"status": info["status"], "seconds": info["seconds"],
                       "pumps_calibrated": info["pumps_calibrated"]}}


def _fit_models(ds: Dataset) -> dict:
    """Fit the learned baselines (M1) for the loaded dataset. Never raises: on any error the app
    keeps running on rules alone and says so (status "rules-only")."""
    t0 = time.time()
    info = {"status": "rules-only", "seconds": 0.0, "pumps_calibrated": 0,
            "pumps_total": len(ds.facilities), "error": None}
    info["m4_ready"] = 0
    try:
        models = enrich._models(ds, ds.now_unix)
        info["pumps_calibrated"] = sum(1 for fb in models.values() if fb.ready)
        info["status"] = "ready" if info["pumps_calibrated"] else "rules-only"
    except Exception as exc:                       # the rules still work without models
        log.exception("model fit failed; running on rules only")
        info["error"] = f"{type(exc).__name__}: {exc}"
    try:
        info["m4_ready"] = m4.fit_all(ds)["ready"]
    except Exception:
        log.exception("M4 fit failed; countdown ranges stay empty")
    info["seconds"] = round(time.time() - t0, 2)
    _model_info[ds.folder.name] = info
    return info


@app.get("/network")
def network():
    return current().network


# ---- state ------------------------------------------------------------------
def _num(x, nd=2):
    return None if x is None else round(float(x), nd)


@app.get("/state")
def state(t: int | None = None):
    ds = current()
    t = _t(ds, t)
    out = {"t": t, "facilities": [], "tanks": [], "pumps": [], "pipelines": [], "wells": []}
    for fid, fac in ds.facilities.items():
        tank, pump, pipe = fac["tank"], fac["pump"], fac["pipeline"]
        level = ds.latest(tank["id"], "level_pct", t)
        cap = float(tank["capacity_bbl"])
        lim = fac["limits"]
        if level is None:
            tank_state = None
        elif lim["shutdown"] is not None and level >= lim["shutdown"]:
            tank_state = "shutdown"
        elif lim["warning"] is not None and level >= lim["warning"]:
            tank_state = "warning"
        else:
            tank_state = "normal"
        well_status = [ds.latest(w, "status", t) for w in fac["wells"]]
        out["facilities"].append({
            "id": fid, "system_id": fac["system_id"],
            "inflow_bpd": _num(ds.latest(fid, "inflow_bpd", t), 1),
            "shut_in": bool(well_status) and all(s is not None and s < 0.5 for s in well_status),
        })
        out["tanks"].append({
            "id": tank["id"], "facility_id": fid, "level_pct": _num(level),
            "volume_bbl": None if level is None else round(level / 100 * cap, 1),
            "capacity_bbl": cap, "state": tank_state,
        })
        ps = ds.latest(pump["id"], "status", t)
        out["pumps"].append({
            "id": pump["id"], "facility_id": fid,
            "status": None if ps is None else int(round(ps)),
            "flow_bpd": _num(ds.latest(pump["id"], "flow_bpd", t), 1),
            "discharge_psi": _num(ds.latest(pump["id"], "discharge_psi", t), 1),
        })
        out["pipelines"].append({
            "id": pipe["id"], "facility_id": fid,
            "receive_flow_bpd": _num(ds.latest(pipe["id"], "receive_flow_bpd", t), 1),
            "pressure_psi": _num(ds.latest(pipe["id"], "pressure_psi", t), 1),
        })
        for w in fac["wells"]:
            st = ds.latest(w, "status", t)
            out["wells"].append({
                "id": w, "facility_id": fid,
                "status": None if st is None else int(round(st)),
                "water_bpd": _num(ds.latest(w, "water_bpd", t), 1),
            })
    return out


# ---- forecast and plans -----------------------------------------------------
def _events(ds: Dataset, t: int) -> list[dict]:
    def run():
        try:
            return enrich.detect_with_models(ds, t)    # adds score, a reason and source "model+rules"
        except Exception:
            log.exception("model detection failed; using rules only")
            return detect(ds, t)
    return _memo("events", ds, (t,), run)


def _forecast_rows(ds: Dataset, t: int) -> list[dict]:
    def run():
        rows = forecast(ds, t, _events(ds, t))
        try:
            return m4.add_ranges(ds, t, rows)         # M4: p10 / p90 around the countdown
        except Exception:
            log.exception("M4 failed; countdown has no range")
            return rows
    return _memo("forecast", ds, (t,), run)


def _plans(ds: Dataset, t: int, risk: float | None = None) -> dict:
    return _memo("plan", ds, (t, risk),
                 lambda: plan_all(ds.network, ds.ops, _forecast_rows(ds, t), t, risk=risk))


@app.get("/forecast")
def forecast_endpoint(t: int | None = None):
    ds = current()
    t = _t(ds, t)
    return {"t": t, "forecasts": _forecast_rows(ds, t)}


@app.get("/plan")
def plan_endpoint(t: int | None = None, risk: float | None = Query(None, ge=0, le=1)):
    """Ranked plans per system. Default: cheapest first. With `risk` (for example 0.95): the cheapest plans
    whose chance of avoiding shutdown is at least that, found against M4's inflow range (M5). Every plan
    carries its shutdown_risk when M4 is available."""
    ds = current()
    return _plans(ds, _t(ds, t), risk)


# ---- alerts -----------------------------------------------------------------
def _lost_revenue_per_hour(ds: Dataset, facility_id: str) -> float:
    prices = ds.ops["prices"]
    cfg = ds.facility(facility_id)["well_cfg"]
    per_day = sum(w["oil_bpd"] * prices["oil_per_bbl"] + w["gas_mcfd"] * prices["gas_per_mcf"] for w in cfg.values())
    return per_day / 24.0


def _urgency(category: str, hours_p50) -> str:
    """How fast someone must act: leaks are always urgent; a failing pump by time left to shutdown."""
    if category == "pipeline_leak":
        return "critical"
    if category == "pump_degradation":
        return "medium"
    if hours_p50 is None:
        return "medium"
    return "critical" if hours_p50 <= 2 else "high" if hours_p50 <= 4 else "medium"


@app.get("/alerts")
def alerts(t: int | None = None, include_resolved: bool = False):
    ds = current()
    t = _t(ds, t)
    forecasts = {r["event_id"]: r for r in _forecast_rows(ds, t)}
    actions_by_event: dict = {}
    for sysplan in _plans(ds, t)["systems"]:
        if sysplan["plans"]:
            for pf in sysplan["plans"][0]["per_facility"]:
                actions_by_event[pf["event_id"]] = pf["actions"]

    rows = []
    for ev in _events(ds, t):
        ongoing = ev["status"] == "ongoing"
        if not ongoing and not include_resolved:
            continue
        fac = ds.facility(ev["facility_id"])
        fc = forecasts.get(ev["event_id"])
        if ev["category"] == "pump_failure":
            actions = actions_by_event.get(ev["event_id"], []) if ongoing else []
            hours = fc["hours_to_limit"] if fc else {"p50": None, "p10": None, "p90": None}
        else:
            urgency_for_action = _urgency(ev["category"], None)
            actions = ([{"type": "field_inspection", "asset_id": ev["asset_id"], "urgency": urgency_for_action}]
                       if ongoing else [])
            hours = None
        row = {
            **ev,
            "reasons": list(ev.get("evidence") or []),
            "level_pct": _num(ds.latest(fac["tank"]["id"], "level_pct", t)),
            "hours_to_limit": hours,
            "urgency": _urgency(ev["category"], (hours or {}).get("p50")) if ongoing else None,
            "recommended_actions": actions,
        }
        rows.append(row)

    def sort_key(r):
        is_pf = r["category"] == "pump_failure" and r["status"] == "ongoing"
        h = (r["hours_to_limit"] or {}).get("p50") if is_pf else None
        return (0 if is_pf else 1 if r["status"] == "ongoing" else 2,
                float("inf") if h is None else h,
                -_lost_revenue_per_hour(ds, r["facility_id"]))

    rows.sort(key=sort_key)
    for i, r in enumerate(rows, 1):
        r["order"] = i
    return {"t": t, "alerts": rows}


# ---- time series ------------------------------------------------------------
UNITS = {"level_pct": "%", "flow_bpd": "bpd", "water_bpd": "bpd", "inflow_bpd": "bpd",
         "receive_flow_bpd": "bpd", "pressure_psi": "psi", "discharge_psi": "psi", "status": ""}


@app.get("/timeseries")
def timeseries(id: str, metric: str, t: int | None = None, from_: int | None = Query(None, alias="from"),
               to: int | None = None):
    ds = current()
    end = to if to is not None else _t(ds, t)
    start = from_ if from_ is not None else end - 24 * 3600
    s = ds.series(id, metric, end)
    if s.empty:
        raise HTTPException(404, f"no data for asset {id!r} metric {metric!r}")
    s = s[s.index >= start]
    return {"asset_id": id, "metric": metric, "unit": UNITS.get(metric, ""),
            "points": [[int(k), round(float(v), 3)] for k, v in s.items()]}


# ---- approve ----------------------------------------------------------------
class ApproveBody(BaseModel):
    event_id: str
    plan_rank: int = 1
    t: int | None = None     # ours: the console's current time; defaults to the dataset's "now"
    risk: float | None = None  # ours: the risk level the console is showing (same as GET /plan?risk=)


@app.post("/approve")
def approve(body: ApproveBody):
    ds = current()
    t = _t(ds, body.t)
    syst = next((s for s in _plans(ds, t, body.risk)["systems"] if body.event_id in s["event_ids"]), None)
    if syst is None:
        raise HTTPException(404, f"no pump failure in progress with event_id {body.event_id!r} at t={t}")
    if not 1 <= body.plan_rank <= len(syst["plans"]):
        raise HTTPException(404, f"plan_rank must be 1 to {len(syst['plans'])}")
    plan = syst["plans"][body.plan_rank - 1]

    cap = ds.ops["emergency_trucking"]["truck_capacity_bbl"]
    messages = []
    for pf in plan["per_facility"]:
        if pf["trucks"]:
            first = pf["trip_arrivals"][0]["arrives_ts"] if pf["trip_arrivals"] else "?"
            for n in range(1, pf["trucks"] + 1):
                messages.append(("truck_driver",
                                 f"Truck {n} -> {pf['facility_id']}, {cap:g} bbl x {pf['trips_per_truck']} trip(s), arrive {first}"))
        for s in pf["shut_in"]:
            messages.append(("field_operator",
                             f"Shut in {s['well']} at +{round(s['start_min'])} min and keep it off until the repair is done"))
    # texts go out in parallel so approving a plan with several messages isn't slow
    with ThreadPoolExecutor(max_workers=max(1, len(messages))) as pool:
        statuses = list(pool.map(lambda m: send_text(*m), messages))
    dispatches = [{"to": to, "message": msg, "status": st} for (to, msg), st in zip(messages, statuses)]
    return {"approved": True, "plan_rank": plan["rank"], "summary": plan["summary"],
            "cost_usd": plan["cost_usd"], "dispatches": dispatches}


# ---- models (Hamza's ML track fills these in; rules only for now) -----------
@app.get("/model/status")
def model_status():
    ds = current()
    info = _model_info.get(ds.folder.name) or _fit_models(ds)
    ready = info["status"] == "ready"
    secs = info["seconds"] if ready else None
    return {"dataset": ds.folder.name, "status": info["status"],
            "models": {"M1": {"ready": ready, "fit_seconds": secs},      # learned normal per pump
                       "M2": {"ready": ready, "fit_seconds": secs},      # drift detector (runs on M1)
                       "M3": {"ready": False, "fit_seconds": None},      # classifier: not built yet
                       "M4": {"ready": info.get("m4_ready", 0) > 0,      # forecaster: range around the countdown
                              "fit_seconds": info["seconds"] if info.get("m4_ready", 0) > 0 else None}},
            "pumps_calibrated": info["pumps_calibrated"], "pumps_total": info["pumps_total"],
            "error": info["error"]}


@app.get("/model/eval")
def model_eval():
    path = ROOT / "docs" / "model_eval.json"
    if path.exists():
        return json.loads(path.read_text())
    return {"generated_unix": None, "method": "leave-one-system-out",
            "folds": [], "comparison": {k: {"recall": None, "mean_minutes_late": None}
                                        for k in ("rules", "models", "ensemble")},
            "calibration_bins": []}


@app.get("/model/baseline")
def model_baseline(id: str, metric: str = "flow_bpd", t: int | None = None, hours: float = Query(24, gt=0, le=168)):
    """Actual vs learned-normal series with a band, for the pump and pipeline charts."""
    ds = current()
    t = _t(ds, t)
    if metric not in m1.METRIC_TO_SENSOR:
        raise HTTPException(400, f"metric must be one of: {', '.join(m1.METRIC_TO_SENSOR)}")
    fid = ds.facility_of(id)
    if fid is None:
        raise HTTPException(404, f"unknown asset {id!r}")
    kind = m1.METRIC_TO_SENSOR[metric][1]
    if ds.facility(fid)[kind]["id"] != id:
        raise HTTPException(400, f"{metric} is a {kind} metric, but {id!r} is not a {kind}")
    try:
        return m1.chart_points(ds, id, metric, t, enrich._models(ds, t), hours)
    except Exception as exc:
        log.exception("learned baseline failed")
        raise HTTPException(503, f"learned baseline unavailable ({type(exc).__name__}); rules-only mode")


@app.post("/simulate/inject")
def simulate_inject():
    raise HTTPException(501, "fault injection is not built yet")
