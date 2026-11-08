# Nightshift API contract

Field names come from EOG's `SPEC.md` and `network.json` / `ops.json` / `telemetry.csv`.
Alerts use the same shape as SPEC's `events.json`, so exporting is free, plus a few extra fields (marked **ours**).
Example values are rounded from EVENT_9 (S1_FACILITY_C, pump fails 2026-10-08T00:20:00Z) and are illustrative, not an answer key.

**Owners.** Hamza: this contract and the engine functions behind it. Sadeem: the FastAPI app and optimizer. Huzaifa: builds screens against mock copies of these responses.
**Changing a field name means telling the group chat first.**

## Conventions

- JSON in and out. Base URL `http://localhost:8000`.
- `t` is **unix seconds (UTC)**, as in `ts_unix`. If omitted, `t` = the loaded dataset's "now" (its last `ts_unix`). The app acts as if `t` is now and uses only data up to `t`.
- A dataset id is its folder name under `data/`: `full_week`, `snapshot_2026-10-08T1200`, `mock_test_2026-10-10T1530`, `test`.
- Ids (`S1`, `S1_FACILITY_C`, `S1_PUMP_C`, ...) always come from `network.json`. Never invent or hardcode them.
- The API never reads `answer_key.json`.
- Errors: HTTP 4xx/5xx with `{"error": "message"}`.
- Event `category` is one of `pump_failure`, `pump_degradation`, `pipeline_leak`.

## GET /datasets

```json
{"datasets": [{"id": "full_week", "now_unix": 1791762900, "now_ts": "2026-10-11T23:55:00Z", "loaded": true},
              {"id": "snapshot_2026-10-08T1200", "now_unix": 1791460800, "now_ts": "2026-10-08T12:00:00Z", "loaded": false}]}
```

## POST /load?dataset=full_week

Loads that folder. Everything below uses it. **ours:** `models` reports model fitting.

```json
{"dataset": "full_week", "now_unix": 1791762900, "now_ts": "2026-10-11T23:55:00Z",
 "systems": 5, "facilities": 15,
 "models": {"status": "rules-only", "seconds": 0.0, "pumps_calibrated": 0}}
```

`models.status`: `rules-only`, `fitting`, or `ready`.

## GET /network

Exactly the shape of `network.json` (`meta`, `defaults`, `systems[].facilities[]` with `wells`, `tank`, `pump`, `pipeline`), unchanged.

## GET /state?t=1791418800

```json
{"t": 1791418800,
 "facilities": [{"id": "S1_FACILITY_C", "system_id": "S1", "inflow_bpd": 1810.0, "shut_in": false}],
 "tanks":      [{"id": "S1_TANK_C", "facility_id": "S1_FACILITY_C", "level_pct": 49.93, "volume_bbl": 399.4,
                 "capacity_bbl": 800, "state": "normal"}],
 "pumps":      [{"id": "S1_PUMP_C", "facility_id": "S1_FACILITY_C", "status": 2, "flow_bpd": 0.0, "discharge_psi": 1049.5}],
 "pipelines":  [{"id": "S1_PIPELINE_C", "facility_id": "S1_FACILITY_C", "receive_flow_bpd": 0.0, "pressure_psi": 1049.7}],
 "wells":      [{"id": "S1_WELL_C1", "facility_id": "S1_FACILITY_C", "status": 1, "water_bpd": 456.7}]}
```

`tanks[].state`: `normal`, `warning` (at or above `defaults.tank_limits_pct.warning`) or `shutdown` (at or above `.shutdown`).
`pumps[].status`: 0 stopped, 1 running, 2 fault.

## GET /alerts?t=1791420600

Every problem still in progress at `t`, in SPEC's alerts-view order (the `order` field): pump failures first, soonest `hours_to_limit` first (ties: higher lost revenue per hour), then leaks and worn pumps. `?include_resolved=true` also returns ended events. Detection is **rules first**; model fields are filled when a model ran.

```json
{"t": 1791420600,
 "alerts": [{
   "event_id": "S1_PUMP_C@1791418800",
   "system_id": "S1", "facility_id": "S1_FACILITY_C", "asset_id": "S1_PUMP_C",
   "category": "pump_failure", "status": "ongoing",
   "onset_ts": "2026-10-08T00:20:00Z", "onset_unix": 1791418800,
   "end_ts": null, "end_unix": null,
   "detected_unix": 1791418800,
   "confidence": 0.95, "score": 0.97,
   "evidence": ["Pump S1_PUMP_C is in fault (status 2) and flow is 0 while tank S1_TANK_C keeps rising"],
   "level_pct": 54.6,
   "hours_to_limit": {"p50": 4.5, "p10": null, "p90": null},
   "recommended_actions": [{"type": "dispatch_truck", "facility_id": "S1_FACILITY_C", "trucks": 1, "trips_per_truck": 1}],
   "source": "rules", "order": 1}]}
```

- `onset_*`, `end_*`, `confidence`, `evidence`, `level_pct`, `hours_to_limit`, `recommended_actions` follow SPEC's `events.json`. `event_id` is `<asset_id>@<onset_unix>`, so it is stable across reloads.
- **ours:** `detected_unix` (when we first saw it, to measure minutes late), `score` (model anomaly score, null if no model), `source` (`rules`, `model`, `model+rules`), `order`.
- `hours_to_limit` is null for leaks and degradation. `p10`/`p90` stay null until the forecaster (M4) exists.
- Action `type`: `dispatch_truck` (`facility_id`, `trucks`, `trips_per_truck`), `shut_in_wells` (`wells`, `start_after_min`), `field_inspection` (`asset_id`), `none`.
- Leak example: `category: "pipeline_leak"`, `asset_id: "S3_PIPELINE_B"`, `hours_to_limit: null`, `recommended_actions: [{"type": "field_inspection", "asset_id": "S3_PIPELINE_B"}]`.

## GET /forecast?t=1791418800

One row per pump failure in progress at `t`.

```json
{"t": 1791418800,
 "forecasts": [{"event_id": "S1_PUMP_C@1791418800", "facility_id": "S1_FACILITY_C", "asset_id": "S1_PUMP_C",
                "level_pct": 49.93, "inflow_bpd": 1810.0,
                "hours_to_limit": {"p50": 4.5, "p10": null, "p90": null},
                "trips_at_unix": 1791434940, "repair_ends_unix": 1791440400, "repair_hours_remaining": 6.0}]}
```

`repair_ends_unix` = onset + `expected_repair_hours.pump_failure`. If the tank would not reach `shutdown` before the repair ends, `trips_at_unix` is null.

## GET /plan?t=1791418800  (optional `&risk=0.95`)

Plans per system. All of a system's failures in progress are planned **together**, because they share its trucks. Ranked cheapest first. `shutdown_risk` is null until M5 exists.

```json
{"t": 1791418800,
 "systems": [{"system_id": "S1", "fleet_size": 2, "event_ids": ["S1_PUMP_C@1791418800"],
   "do_nothing_cost_usd": 5016.0,
   "plans": [
     {"rank": 1, "summary": "1 truck, 1 trip", "cost_usd": 905.0,
      "cost_breakdown": {"trucks": 905.0, "shut_in": 0.0},
      "actions": [{"type": "dispatch_truck", "facility_id": "S1_FACILITY_C", "trucks": 1, "trips_per_truck": 1}],
      "keeps_tank_under_shutdown": true, "shutdown_risk": null},
     {"rank": 2, "summary": "Shut in S1_WELL_C2 at +125 min", "cost_usd": 1958.0,
      "cost_breakdown": {"trucks": 0.0, "shut_in": 1958.0},
      "actions": [{"type": "shut_in_wells", "wells": ["S1_WELL_C2"], "start_after_min": 125}],
      "keeps_tank_under_shutdown": true, "shutdown_risk": null}]}]}
```

## GET /timeseries?id=S1_TANK_C&metric=level_pct&from=1791418500&to=1791420600

`from`/`to` unix seconds; `to` defaults to `t`/now, `from` defaults to 24 h before `to`.

```json
{"asset_id": "S1_TANK_C", "metric": "level_pct", "unit": "%",
 "points": [[1791418500, 50.34], [1791418800, 49.93], [1791419100, 50.76]]}
```

## POST /approve

Approves a plan and notifies the crew (Photon). The phone number lives in the server's `.env`, never in the request.

```json
// request
{"event_id": "S1_PUMP_C@1791418800", "plan_rank": 1}
// response
{"approved": true,
 "dispatches": [{"to": "truck_driver", "message": "Truck 1 -> S1_FACILITY_C, 150 bbl, arrive 01:35Z", "status": "sent"}]}
```

`dispatches[].status`: `sent`, `simulated` (no Photon key set), or `failed`.

## GET /model/status

```json
{"dataset": "full_week", "status": "rules-only",
 "models": {"M1": {"ready": false, "fit_seconds": null}, "M2": {"ready": false, "fit_seconds": null},
            "M3": {"ready": false, "fit_seconds": null}, "M4": {"ready": false, "fit_seconds": null}},
 "pumps_calibrated": 0, "pumps_total": 15}
```

## GET /model/baseline?id=S1_PUMP_C&metric=flow_bpd&t=1791418800&hours=24

The learned normal behind the real sensor line, for the Model Lab chart. `score` is distance from normal in units of that pump's own healthy spread.

```json
{"asset_id": "S1_PUMP_C", "metric": "flow_bpd", "unit": "bpd",
 "points": [{"ts_unix": 1791418500, "actual": 2321.3, "expected": 2310.0, "lower": 2200.0, "upper": 2420.0, "score": 0.4}]}
```

## GET /model/eval

Reads `docs/model_eval.json`, written by the evaluation script. **Every number comes from that script; none are typed by hand.** Fields are null until the script has run.

```json
{"generated_unix": null, "method": "leave-one-system-out",
 "folds": [{"held_out_system": "S1", "precision": null, "recall": null, "mean_minutes_late": null}],
 "comparison": {"rules": {"recall": null, "mean_minutes_late": null},
                "models": {"recall": null, "mean_minutes_late": null},
                "ensemble": {"recall": null, "mean_minutes_late": null}},
 "calibration_bins": [{"p_mean": null, "observed": null, "n": null}]}
```

## POST /simulate/inject

Adds a simulated problem **in memory only** (never written to the loaded files). Every result carries `simulated: true` and the UI shows a SIMULATED badge.

```json
// request
{"asset_id": "S1_PUMP_C", "category": "pump_failure", "onset_unix": 1791418800, "severity": 1.0}
// response
{"simulated": true, "event_id": "SIM:S1_PUMP_C@1791418800", "category": "pump_failure"}
```

`severity` is 0 to 1 (1 = full failure, smaller = a milder leak or wear). Alerts created this way also carry `"simulated": true`.
