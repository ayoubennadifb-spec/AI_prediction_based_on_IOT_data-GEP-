# LSTM Inference Worker (Render + InfluxDB Cloud)

> ## ⭐ PRODUCTION — use `production_worker.py` (your real GEP model)
>
> **`production_worker.py` is the file to deploy.** It does NOT re-implement the
> preprocessing — it **reuses your own validated pipeline**
> (`gep_forecast.serving.forecast_from_frame`, vendored in `./gep_forecast/`):
> the exact time-features, the persisted `ScalerBundle`, a single **direct**
> multi-step forward pass (no recursive rollout), and residual reconstruction.
> So **online output == your validated offline output.**
>
> It is pre-wired to your artifacts: `artifacts/direct_seed42.keras` (input
> `(240,5)` → output `(240,2)`) and `artifacts/scaler_bundle.joblib`
> (contract 240/240, features `temperature, humidity, co2`). ✅ End-to-end tested.
>
> **Two-base topology:** the worker **READS** live sensors from a **SOURCE**
> InfluxDB (Ayman's base, read-only — his real-time collection is never touched)
> and **WRITES** forecasts to a **DESTINATION** InfluxDB (your own base). It serves
> **Zone 1** (real co2 = `gaz`) and **Zone 2** (co2 = training-mean proxy, gated by
> `SERVE_ZONE2_PROXY`).
>
> **Schema bridge (Zone 1):** Ayman's ingestion writes French field names, so the
> worker maps `humidite→humidity` and `gaz→co2` before forecasting, and writes the
> forecast to measurement **`prediction_zone1`** (and **`prediction_zone2`**) with
> fields **`temperature_pred`, `humidite_pred`** into bucket **`DST_BUCKET`**
> (default `predictions`) — exactly what the Vercel dashboard reads.
>
> **Deploy:** push this `render_worker/` folder to Git → Render → **New →
> Blueprint** on `render.yaml` (it runs `python production_worker.py` as an
> always-on `type: worker`). Set the **`SRC_*`** (Ayman, read) and **`DST_*`**
> (yours, read+write) env vars in the Render dashboard — see the Environment
> variables section below. That's it.
>
> *(The generic, fully-configurable `inference_worker.py` below is kept only as a
> fallback for a simple custom model. For your project, use `production_worker.py`.)*

---

A production-ready Python worker that connects an already-trained Keras LSTM to a
live IoT sensor stream in **InfluxDB Cloud** and writes **direct multi-step
forecasts** back to InfluxDB, so a dashboard can plot *measured vs predicted* per
zone.

## Architecture (two bases)

The worker reads from a **SOURCE** base (Ayman's, read-only) and writes to a
**DESTINATION** base (yours). Nobody writes into Ayman's base — his real-time
collection stays untouched.

```
 Ayman's ESP32 ingestion ──▶ SOURCE InfluxDB (Ayman)
                                    │  READ last LOOKBACK_MIN min (SRC_*)
                                    ▼
            ┌──────────────────────────────────────────┐
            │   THIS WORKER (Render background worker)  │
            │   every PREDICT_EVERY_SEC, per zone:      │
            │   read → guard → scale → predict → write  │
            └──────────────────────────────────────────┘
                                    │  WRITE forecast (DST_*)
                                    ▼
                          DEST InfluxDB (yours)
                                    │
                                    ▼
                  dashboard (measured from SOURCE vs predicted from DEST)
```

## What it does (loop, every `PREDICT_EVERY_SEC`, default 60s), per zone

1. **Read** the last `LOOKBACK_MIN` minutes of the model's `FEATURES` from the
   **SOURCE** InfluxDB (Ayman's, `SRC_*`), resampled to a 1-min grid
   (`aggregateWindow(every: 1m, mean)`), as a clean ordered DataFrame (gaps kept
   as `NaN`, no forward-fill).
2. **Staleness / gap guard**: skip the zone (warn, don't predict) if the newest
   real point is older than `MAX_STALENESS_MIN`, or fewer than
   `MIN_FRESH_POINTS` real points exist in the window.
3. **Preprocess** with the **same persisted training scaler** (loaded from
   `scaler.pkl`, applied via `.transform`, exact feature order) — never refit.
4. **`model.predict()`** → a **direct multi-step** forecast (one forward pass).
5. **Inverse-transform** and **write** the forecast to the **DEST** InfluxDB
   (yours, `DST_*`), bucket `DST_BUCKET`, measurement `prediction_zone1` /
   `prediction_zone2`, one field per target (`temperature_pred`,
   `humidite_pred`, …), each point stamped at its future time `now + i·Δt`
   (tz-aware UTC).

## The 4 correctness rules (where naive deployments fail)

- **R1 — Lookback match.** `LOOKBACK_MIN` MUST equal the training lookback. The
  worker asserts `model.input_shape[1] == LOOKBACK_MIN` at startup and refuses
  to run on a mismatch. (Afaf's pipeline trained at 480 but served at 60 — the
  root cause of the offline→online accuracy collapse.)
- **R2 — Direct multi-step only.** The model emits the whole horizon in one
  forward pass; the worker asserts the output length `== HORIZON_MIN`.
  **Never** do recursive step-by-step rollout (feeding a prediction back as the
  next input). That compounding is the #1 bug that turns a 0.15 °C offline error
  into a 3.4 °C online error.
- **R3 — Same scaler & feature order.** The training scaler is loaded from disk
  and reused; it is **never** refit on serving data, and features are assembled
  in the exact training order.
- **R4 — tz-aware UTC everywhere.** All timestamps use
  `datetime.now(timezone.utc)` / tz-aware pandas indices, in and out.

## Files

```
render_worker/
├── config.py            # ALL tunables; secrets via ENV; >>> CONFIRM FROM YOUR TRAINING <<<
├── influx_io.py         # read_window() (Flux) + write_forecast()
├── preprocess.py        # load scaler, build (1, LOOKBACK, n_feat) tensor, inverse-transform
├── inference_worker.py  # main loop: asserts, guard, predict, per-zone error handling
├── requirements.txt
├── render.yaml          # Render worker service (+ commented cron alternative)
├── .env.example
├── README.md
└── model/
    └── README.txt       # drop lstm.keras + scaler.pkl here
```

## Environment variables (two bases)

All configuration is via environment variables (see `.env.example` for the
canonical list). The worker talks to **two** InfluxDB instances:

**SOURCE — Ayman's base (READ only):**

| Var | Example | Notes |
|-----|---------|-------|
| `SRC_INFLUX_URL` | `https://us-east-1-1.aws.cloud2.influxdata.com` | Ayman's region URL |
| `SRC_INFLUX_ORG` | `e873aeb2e2a1406c` | Ayman's org |
| `SRC_INFLUX_TOKEN` | `…` | **read token** from Ayman (see box below) |
| `SRC_BUCKET_ZONE1` | `Data` | Zone 1 measured |
| `SRC_BUCKET_ZONE2` | `Zone2` | Zone 2 measured |

**DESTINATION — your own base (READ + WRITE):**

| Var | Example | Notes |
|-----|---------|-------|
| `DST_INFLUX_URL` | `https://eu-central-1-1.aws.cloud2.influxdata.com` | your region URL |
| `DST_INFLUX_ORG` | `…` | your org |
| `DST_INFLUX_TOKEN` | `…` | **read+write token** on `predictions` |
| `DST_BUCKET` | `predictions` | where forecasts are written |

**Worker-only:**

| Var | Example | Notes |
|-----|---------|-------|
| `PREDICT_EVERY_SEC` | `600` | seconds between prediction cycles |
| `SERVE_ZONE2_PROXY` | `true` | serve Zone 2 with a training-mean co2 proxy |

> ### 📨 What to ask Ayman (SOURCE base)
> Just **one read token**. In his InfluxDB: **Load Data → API Tokens → Generate →
> Custom API Token** → check **Read** on buckets **`Data`** AND **`Zone2`** → copy.
> Send you that token plus his **`SRC_INFLUX_URL`** and **`SRC_INFLUX_ORG`**.
> *(No write access needed — his real-time collection is not touched.)*

> ### 🪣 Prepare your own InfluxDB (DESTINATION base)
> Create a free InfluxDB Cloud account → create a bucket named **`predictions`** →
> generate a **Read + Write** token scoped to it. These become your `DST_INFLUX_URL`,
> `DST_INFLUX_ORG`, `DST_INFLUX_TOKEN`, and `DST_BUCKET=predictions`.

Local run:

```bash
cd render_worker
python -m venv .venv && . .venv/Scripts/activate   # Windows; or source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then edit .env with your SRC_* and DST_* values
python production_worker.py
```

## Deploy to Render (exact steps)

1. Push this `render_worker/` folder to a Git repo (GitHub/GitLab). The artifacts
   under `artifacts/` (`direct_seed42.keras`, `scaler_bundle.joblib`) are required
   at runtime — keep them committed.
2. In Render: **New → Blueprint**, point it at the repo containing
   `render.yaml`. It creates an always-on **Background Worker** that runs
   `python production_worker.py`.
   - If the worker is in a subfolder, set **Root Directory** to
     `My work/AI/deployment/render_worker` (or set `rootDir` in `render.yaml`).
3. Set the env vars in the Render dashboard (or an env group): the **`SRC_*`**
   group (`SRC_INFLUX_URL`, `SRC_INFLUX_ORG`, `SRC_INFLUX_TOKEN`,
   `SRC_BUCKET_ZONE1`, `SRC_BUCKET_ZONE2`) and the **`DST_*`** group
   (`DST_INFLUX_URL`, `DST_INFLUX_ORG`, `DST_INFLUX_TOKEN`, `DST_BUCKET`), plus
   `PREDICT_EVERY_SEC` and `SERVE_ZONE2_PROXY`. The token vars are `sync: false`
   in `render.yaml` so they are never read from git.
4. Deploy. Build runs `pip install -r requirements.txt`; start runs
   `python production_worker.py`. Watch the logs: startup must print the loaded
   `input_shape` / `output_shape` and pass the R1/R2 asserts.
5. Verify in your **DEST** InfluxDB that `prediction_zone1` / `prediction_zone2`
   receive `*_pred` points; point your dashboard at measured (SOURCE) vs
   predicted (DEST).

> **Cron alternative.** A commented `type: cron` block in `render.yaml` runs one
> pass on a schedule instead of an always-on worker (cheaper). For cron, add a
> `RUN_ONCE` guard so the process does one cycle and exits.

## ⚠️ Config values you MUST confirm from your training

Open `config.py` and verify every line flagged `# >>> CONFIRM FROM YOUR TRAINING <<<`.
The shipped GEP models do **not** match the generic defaults:

- `LOOKBACK_MIN` / `HORIZON_MIN` — real model trained at **240 / 240**, not the
  120/240 placeholders.
- `FEATURES` / `TARGETS` — real model: `["temperature","humidity","co2"]` →
  `["temperature","humidity"]`.
- `USE_TIME_FEATURES = True` — the real model is **5-channel** (sensor features +
  `hour_sin`, `hour_cos`).
- `OUTPUT_IS_RESIDUAL = True` — the real model predicts a **delta** from the last
  observation, not an absolute forecast.
- `SCALER_KIND` — real scaler is a per-channel `ScalerBundle` (`"bundle"`), not a
  plain sklearn scaler.
- `FIELD_MAP` — InfluxDB Zone 1 uses **French field names**; map training names
  to Influx fields (`humidity → humidite`, `co2 → gaz`).

See `model/README.txt` for the exact config block to deploy `direct_seed42.keras`.

## Zone-2 caveat (read this)

Zone 2 (`SRC_BUCKET_ZONE2` = `Zone2`) has **fewer sensors** — notably **no
`gaz`/CO₂** — yet the production model **requires** a `co2` channel. To still
forecast Zone 2, the worker fills that channel with a **training-mean proxy**
when `SERVE_ZONE2_PROXY=true`, then writes `prediction_zone2`. Set
`SERVE_ZONE2_PROXY=false` to skip Zone 2 entirely. Either way the dashboard
always shows Zone-2 real-time data; with the proxy off, only its forecast line is
absent. For a cleaner Zone 2, retrain a `co2`-free (temperature+humidity) model
and serve it from a second worker arm.
