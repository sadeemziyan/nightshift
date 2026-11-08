# Sensors and config: what every asset reports

Source: EOG's `SPEC.md` (copied to `docs/SPEC.md`), checked against
`data/full_week/telemetry.csv` (393,120 rows). Written in Phase 0 so we know what
the learned baseline (M1) can learn from.

## Telemetry format

- Columns: `timestamp, ts_unix, asset_id, metric, value`. Long format: one row per asset, per metric, per time.
- One reading every 300 s (5 min). Every series reports at every timestamp. No missing values in full_week.
- full_week runs `2026-10-05T00:00:00Z` (`ts_unix` 1791158400) to `2026-10-11T23:55:00Z` (1791762900).
- **"Now" for any dataset folder = its last `ts_unix`.** Never hardcode a time range.
- Map assets to facilities through `network.json`, **not** by parsing the text of `asset_id`.

## Sensors (full_week: 5 systems, 15 facilities)

| Asset type | Count | Metric | Unit | One-line meaning |
|---|---|---|---|---|
| Well | 45 | `water_bpd` | bbl/day | Live water rate coming from the well |
| Well | 45 | `status` | 1 / 0 | 1 producing, 0 shut in |
| Facility | 15 | `inflow_bpd` | bbl/day | Sum of its wells' water = the tank's inflow |
| Tank | 15 | `level_pct` | % full | Volume in bbl = `level_pct / 100 * capacity_bbl` |
| Pump | 15 | `status` | 0 / 1 / 2 | 0 stopped, 1 running, 2 fault |
| Pump | 15 | `flow_bpd` | bbl/day | Flow out of the tank into the pipeline |
| Pump | 15 | `discharge_psi` | psi | Pressure at the pump outlet |
| Pipeline | 15 | `receive_flow_bpd` | bbl/day | Flow arriving at the disposal site |
| Pipeline | 15 | `pressure_psi` | psi | Pressure at the disposal-site end of the pipe |

Disposal sites have no sensors and never go down. Readings carry small random noise.

## Static config (not in telemetry)

| Where | Fields |
|---|---|
| `network.json` `defaults.tank_limits_pct` | `warning` (85), `shutdown` (92), same for every tank |
| `network.json` system | `id`, `center`, `truck_yard`, `disposal_site{id, lat, lon, pressure_psi}`, `facilities` |
| `network.json` facility | `id`, `lat`, `lon`, `wells`, `tank`, `pump`, `pipeline` |
| well | `id`, `baseline_water_bpd`, `oil_bpd`, `gas_mcfd` |
| tank | `id`, `capacity_bbl` |
| pump | `id`, `max_flow_bpd`, `start_level_pct`, `stop_level_pct` |
| pipeline | `id`, `max_bpd`, `max_pressure_psi` |
| `ops.json` | `prices{oil_per_bbl, gas_per_mcf}`, `expected_repair_hours{pump_failure}`, `emergency_trucking{truck_capacity_bbl, cost_per_trip}` |
| `ops.json` per system | `emergency_fleet_size` |
| `ops.json` per facility | `response_min` (first trip from the truck yard), `cycle_min` (one round trip) |

## Relationships stated in SPEC.md (safe to build on)

- Tank level change per hour = `(inflow - pump flow) / 24 / capacity * 100`.
- Pump starts at `start_level_pct`, stops at `stop_level_pct`, keeps its state in between (the sawtooth).
- Healthy pressures: pump running means pipeline `pressure_psi` is about disposal pressure + 50 and pump `discharge_psi` is about disposal pressure + 150. Pump off or failed means both read the disposal pressure. (SPEC calls the offsets placeholders, so learn them per pump.)
- When a tank reaches `shutdown`, the facility's wells go to `status` 0 and `water_bpd` 0 and the level holds until the repair ends (6 h from onset, from `ops.json`).

## Seen in full_week (checked on the data)

- Pump `status` = 2 appears **936 times, all inside the 13 pump_failure windows** (13 events x 72 readings = 6 h). Inside them `flow_bpd` is 0 and `discharge_psi` falls to the disposal pressure (EVENT_9: 1049.5 psi vs 1050 disposal).
- So the rule "pump status is 2" finds every pump failure in full_week, with no delay. The test network may not be this clean, so Phase 1 also uses "pump off while the tank is above its start level".
- The answer key calls wear events `pump_degradation`. Our code uses the same three names: `pump_failure`, `pump_degradation`, `pipeline_leak`.

## Hypotheses to confirm in Phase 1/2 (not in SPEC, found by comparing labelled events to normal)

- `pump_degradation`: while running, `flow_bpd` drifts below the pump's normal and keeps sliding (maybe `discharge_psi` too).
- `pipeline_leak`: `receive_flow_bpd` falls below the pump's `flow_bpd`, or pipeline `pressure_psi` drops below its running level.
