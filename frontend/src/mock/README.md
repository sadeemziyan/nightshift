# Mock API responses

Build screens against these before the backend is connected. Field names match `docs/api.md`.

Every file is a **real response** from our API at `MOCK_T = 1791453900` (2026-10-08T10:05:00Z, dataset
`full_week`), the busiest moment of the week: three pumps in S2 are down at once and share two
trucks, one pipeline is leaking and two pumps are wearing out.

| File | Endpoint | Notes |
| --- | --- | --- |
| `datasets.json` | `GET /datasets` | |
| `load.json` | `POST /load?dataset=full_week` | `models.status` is `rules-only` |
| `network.json` | `GET /network` | exactly `network.json` from the data folder |
| `state.json` | `GET /state?t=MOCK_T` | tank level and state, pump status, wells |
| `alerts.json` | `GET /alerts?t=MOCK_T` | 3 pump failures, 2 pump wear, 1 leak, with `evidence` and `urgency`. `score` is `null` until the models are wired into `/alerts` |
| `forecast.json` | `GET /forecast?t=MOCK_T` | hours to shutdown for the 3 failing tanks |
| `plan.json` | `GET /plan?t=MOCK_T` | ranked plans for the 3 failures sharing 2 trucks, plus `planned_separately` |
| `timeseries.json` | `GET /timeseries?id=S2_TANK_B&metric=level_pct` | last 6 h of one tank |
| `approve.json` | `POST /approve` | `dispatches[].status` is `sent`, `simulated` or `failed` |
| `model_status.json` | `GET /model/status` | real response (rules only) |
| `model_baseline.json` | `GET /model/baseline?id=S2_PUMP_B&metric=flow_bpd` | learned-normal band (`expected`, `lower`, `upper`, `score`) |
| `simulate_inject.json` | `POST /simulate/inject` | shape from `docs/api.md` |

**Placeholders (not real results), so the Model Lab can be laid out early:**

- `model_eval.json`: invented numbers, with a `mock_notice` field. The real numbers come from
  `/model/eval`. Never put these on a slide.
- `model_status_fitting.json` and `model_status_ready.json`: the two states of the
  "Learning this network... N pumps calibrated" step.

Use them all through `index.js`:

```js
import { mock, MOCK_T } from './mock'
const failing = mock.alerts.alerts.filter((a) => a.category === 'pump_failure')
```

To refresh a file, start the backend, `POST /load?dataset=full_week`, then save the endpoint's
response with `t=1791453900`.
