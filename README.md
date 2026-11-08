# Nightshift

**Catch the failure before the tank fills. Pick the cheapest fix. Text the crew.**

Nightshift is a web console for night-shift operators of a produced-water network. It reads sensor data, spots problems on its own, counts down to the moment a tank forces its wells to shut in, compares every response plan by cost, and texts the crew once the operator approves.

Built at **HackUTD 2026** for EOG's **Beat the Shutdown** challenge (with the Photon track for dispatch texts).

---

## The problem

Oil wells make oil, gas and a lot of salty water. The water goes into a tank, and a pump sends it through a pipeline to a disposal site. When something fails, usually at night, an operator has to notice and act fast:

| Problem | What happens | What the operator needs |
|---|---|---|
| **Pump failure** | The pump stops and the tank fills. At 92% full the wells shut in automatically and the company stops earning. | A countdown and the cheapest response |
| **Pump wearing out** | The pump moves a little less water every hour. | An alert and an inspection |
| **Pipeline leak** | Water escapes on the way to the disposal site. | An urgent alert and an inspector |

The response to a pump failure is a cost trade-off: send trucks to haul water ($905 per trip, 150 bbl), shut in some wells early (lost oil and gas sales), do both, or do nothing. Trucks are shared by every facility in a system, so the best plan for one tank may starve another.

## What Nightshift does

- **Detects** all three problems from sensor readings only. Nothing is read from an answer key.
- **Explains** every alert in plain English with a confidence score and its source (rules, learned models, or both).
- **Counts down** to tank shutdown, with a range (p10 to p90), and notes when the repair will finish first.
- **Plans the whole system together.** Simultaneous failures share one truck fleet. On the practice week (2026-10-08, three S2 pumps down at once): do nothing costs **$12,274**, planning each tank separately costs **$5,194**, and the joint plan costs **$3,108**.
- **Prices safety.** A slider asks for a chance of avoiding shutdown from "cheapest" up to 99.9%, and shows the extra cost of that safety.
- **Dispatches.** Approving a plan texts the truck driver, field operator or inspector through Photon. With no keys configured the texts are marked *simulated* and nothing is sent.
- **Replays the week** at 1x to 300x so alerts, countdowns and plans update live, including when a second pump fails.
- **Proves itself on stage.** "Inject a failure" adds a fault in memory only. It is badged **SIMULATED** everywhere and one click returns to the real data.
- **Shows its work.** The Model Lab tab shows each pump's learned normal band, anomaly score, the reasons behind each flag, and how the models scored on systems they never saw.
- **Gives the crew a phone page** (`#/jobs`): one big card per truck trip, well shut-in or inspection, with a Done button.

## How it works

```
telemetry.csv + network.json + ops.json      (any dataset folder under data/)
        |
        v
  Rule detector  ->  M1 learned normal  ->  M2 drift detector  ->  M3 classifier (second opinion)
        |                                                              |
        +------------------------ blended alerts <--------------------+
        |
        v
  Countdown (M4 forecast with range)  ->  Cost optimizer (exact, system-wide, risk-aware M5)
        |
        v
  FastAPI  <->  React console  ->  /approve  ->  Photon text to the crew
```

| Piece | What it does |
|---|---|
| **Rules** (`backend/engine`) | Sensor-only detection of pump failure, wear and leaks. It is built first and is the fallback for everything else. |
| **M1 learned normal** (`backend/ml/detect/baseline.py`) | Learns each pump's and pipeline's normal readings from its own history, in units of its own healthy spread, so the same threshold means the same thing for every pump. |
| **M2 drift** (`drift.py`) | CUSUM evidence that a reading has been below normal for hours. Catches slow wear early. |
| **M3 classifier** (`classifier.py`) | Gradient-boosted trees that call normal, leak, wear or failure with a calibrated probability and the top factors behind the call. It reads features in "healthy spreads", never raw bpd or psi, so it can read a pump it has never seen. |
| **M4 forecast** (`backend/ml/forecast`) | Quantile gradient-boosted model of tank inflow that turns the countdown into a range. |
| **M5 risk-aware plans** (`backend/optimizer/risk.py`) | Scores each plan against inflow scenarios to give a shutdown risk, and finds the cheapest plan that meets a requested safety level. |
| **Optimizer** (`backend/optimizer`) | Exact search over trucks, trips and early well shut-ins for one tank, then jointly for a whole system sharing a fleet. |
| **API** (`backend/api`) | FastAPI app that serves all of the above (contract in `docs/api.md`). |
| **Console** (`frontend/`) | React, Vite, Tailwind, React Flow (network map) and Recharts. |
| **Notifier** (`notifier/`) | Sends dispatch texts through Photon's Spectrum SDK. |

Every model call has a rules-only fallback. If a model errors or a file is missing, the app returns the rule-based result marked `"source": "rules"` and keeps running.

## Works on any network

Nothing is hardcoded: no facility names, prices, capacities, thresholds or timestamps. Everything comes from a dataset folder's three files, and the models refit to a folder's own history whenever it is loaded (the "Learning this network..." step shows how many pumps were calibrated).

A dataset is a folder under `data/` containing:

| File | Contents |
|---|---|
| `network.json` | systems, facilities, wells, tanks, pumps, pipelines, disposal sites |
| `ops.json` | prices, repair time, truck fleet and travel times |
| `telemetry.csv` | `timestamp, ts_unix, asset_id, metric, value`, one reading per series every 300 s |

To run a new network, drop its folder into `data/` (for example `data/test/`) and pick it in the Dataset menu. The console opens `test` first if it exists, then `mock_test_*`, then `full_week`.

## Run it locally

You need Python 3.11+, Node 20+ and Git.

**1. Backend**

```bash
python -m venv .venv
# Windows PowerShell:  .venv\Scripts\Activate.ps1      macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt
uvicorn backend.api.main:app --reload
```

The API is at http://localhost:8000 (interactive docs at `/docs`). `scikit-learn` is pinned because `models/m3.joblib` was saved with that version.

**2. Frontend** (second terminal)

```bash
cd frontend
npm install
npm run dev
```

Open the address Vite prints (usually http://localhost:5173). To point at a different backend, set `VITE_API_URL`. If the backend is not reachable, the console shows a banner and falls back to sample data.

**3. Dispatch texts (optional)**

```bash
cd notifier
npm install
# copy .env.example to .env and fill in your Photon project id, secret and phone number
cd ..
python -m backend.api.notify truck_driver "Nightshift test"
```

Without keys, `/approve` still works and marks every text *simulated*.

### Using the console

1. Press **Play** (or **Next problem**) to replay the week.
2. Click an alert to open its facility: countdown, tank chart and pump chart.
3. Compare plans, move the safety slider, then **Approve** to text the crew.
4. Open **Model Lab** for the models' evidence and test results, and **My Jobs** for the crew's phone view.
5. Use **Inject a failure** to create a SIMULATED fault; **Back to real data** removes it.

## API

The full contract is in [`docs/api.md`](docs/api.md).

| Endpoint | Purpose |
|---|---|
| `GET /datasets`, `POST /load` | list and load dataset folders (also refits the models) |
| `GET /network`, `GET /state`, `GET /timeseries` | layout, status of every asset at time `t`, sensor history |
| `GET /alerts` | detected problems with reasons, score, source and an optional M3 opinion |
| `GET /forecast` | countdown to shutdown with a range |
| `GET /plan` (`&risk=0.95`) | ranked plans per system, optionally for a safety level |
| `POST /approve` | approve a plan and text the crew |
| `GET /model/status`, `/model/baseline`, `/model/eval` | Model Lab data |
| `POST /simulate/inject` | add a SIMULATED fault (memory only) |

## Tests and checks

```bash
python -m backend.engine.tests.test_phase1
python -m backend.engine.tests.test_phase2
python -m backend.ml.detect.tests.test_models
python -m backend.ml.detect.tests.test_m3
python -m backend.optimizer.test_single
python -m backend.optimizer.test_system
python -m backend.optimizer.test_risk
python -m backend.ml.forecast.test_forecast
python -m backend.api.test_simulate
```

- **Dry run** every dataset through the API: `python -m backend.api.dry_run`
- **Detection scorecard** (offline): `python -m backend.engine.scorecard data/full_week --models`
- **Model evaluation** (offline, writes `docs/model_eval.json`): `python -m backend.ml.detect.evaluate`
- **Stress test** (offline): `python -m backend.ml.detect.stress data/full_week` rebuilds the practice week as a different network (renamed, rescaled, noisier, shorter history, missing readings) and scores the shipped models on it.
- **Frontend**: `cd frontend && npx eslint src && npm run build`

## Results on the practice data

| Check | Result | Source |
|---|---|---|
| Labelled events found, practice week | 23 of 23, 0 false alarms | `docs/scorecard_summary.json` |
| Leave-one-system-out test of M3 (each system hidden in turn) | all 23 events found; about 52 min after onset on average vs about 91 min for rules alone; 0.7% false alarms on normal windows | `docs/model_eval.json` |
| Joint vs separate planning, 2026-10-08 | $3,108 vs $5,194 (do nothing: $12,274) | `/plan` on `snapshot_2026-10-08T1200` |
| M4 range coverage on held-out data | 82% against an 80% target | `python -m backend.ml.forecast.check_m4 data/full_week` |

Every accuracy number comes from an offline script's output, never typed by hand.

## Honest limitations

- All practice data comes from one network family. The stress test shows the models do not depend on names, sizes or pressure levels, but only a truly different network can show how they cope with different physics.
- Heavy sensor noise or very short history makes alerts later and raises false alarms (see `stress.py`).
- M3 is a second opinion. The rule detector stays the fallback and always has the last word if a model fails.
- Photon texts need the keys and a phone added in the Photon dashboard; otherwise they are simulated.

## Project layout

```
backend/
  api/        FastAPI app, dry-run tool, notifier bridge
  engine/     loader, rule detection, forecast, scorecard
  ml/detect/  M1 baseline, M2 drift, M3 classifier, simulator, evaluation, stress test
  ml/forecast/  M4 shutdown forecaster
  optimizer/  single-tank, system-wide and risk-aware plans
data/         dataset folders (network.json, ops.json, telemetry.csv)
docs/         API contract, sensor list, EOG's SPEC, evaluation outputs
frontend/     React console (Console, Model Lab, My Jobs)
models/       saved M3 classifier
notifier/     Photon Spectrum text sender
```

## Rules we follow

1. Nothing hardcoded; everything comes from the dataset folder.
2. The app never reads `answer_key.json`. Only the offline scoring and evaluation scripts do.
3. Every model call has a rules-only fallback.
4. Models are validated by leaving one whole system out, not by splitting in time.

## Team

- **Sadeem** - API, cost optimizer, M4 forecast, risk-aware plans
- **Hamza** - detection engine, learned baseline, drift, classifier, simulator, evaluation
- **Huzaifa** - React console

Built for HackUTD 2026.
