# GEP HVAC Digital-Twin Dashboard

A small **Next.js (App Router, TypeScript)** dashboard that visualizes, **per
zone**, the real-time IoT sensor data **and** the LSTM forecast. It reads
**MEASURED** data from a **SOURCE** InfluxDB (Ayman's base) and **PREDICTED** data
from a **DESTINATION** InfluxDB (your own base). Built to deploy on **Vercel**.

> Green Energy Park context: Zone 1 and Zone 2 each have temperature/humidity
> sensors streaming into Ayman's **SOURCE** InfluxDB; a separate Python worker
> reads those, computes the LSTM forecast, and writes it into your **DEST**
> InfluxDB. This dashboard overlays the two. CO₂ (`gaz`) is real-time only — there
> is no CO₂ forecast.

---

## What it shows

- **Zone selector** (tabs) for **Zone 1** and **Zone 2**.
- Two **time-series charts** per zone:
  - **Temperature**: measured (last ~6 h, solid) + forecast (next ~4 h, dashed amber).
  - **Humidity**: same overlay on a second chart.
  - A dashed **"now"** marker separates history from forecast.
- **KPI cards**: current temperature, current humidity, last-updated time, and
  whether a forecast is available (Yes/No).
- **Auto-refresh every 60 s** (client polls the API; no page reload).

---

## Architecture

```
Browser (app/page.tsx)
   │  fetch every 60s
   ▼
GET /api/series?zone=1|2&field=temperature|humidite   (Next.js route, server-only)
   │  tokens never sent to browser
   ├─ measured  ──▶ SOURCE InfluxDB (Ayman, SRC_*, read-only)
   │                  bucket "Data"  / measurement capteurs_zone1   (Zone 1)
   │                  bucket "Zone2" / measurement capteurs_zone2   (Zone 2)
   │                  fields temperature / humidite / gaz (CO₂, real-time only)
   └─ predicted ──▶ DEST InfluxDB (yours, DST_*)
                      bucket "predictions"
                      measurement prediction_zone1 / prediction_zone2
                      fields temperature_pred / humidite_pred  (future timestamps)
```

- **`lib/influx.ts`** — InfluxDB client + Flux builders (`measuredFlux`,
  `predictionFlux`) and `fetchSeries()`. Server-only; reads env vars.
- **`app/api/series/route.ts`** — serverless GET endpoint. Validates `zone`
  and `field`, queries Influx, returns
  `{ measured: [{time,value}], predicted: [{time,value}] }`. **The token stays
  server-side** — only points are returned to the browser.
- **`components/ZoneChart.tsx`** — Recharts line chart, measured solid +
  forecast dashed, merged on a numeric time axis.
- **`components/KpiCard.tsx`** — small KPI tile.

### Data contract (must match the worker)

| Zone | Source bucket (`SRC_*`)     | Measured measurement | Dest bucket (`DST_*`)   | Forecast measurement | Fields                                                       |
| ---- | --------------------------- | -------------------- | ----------------------- | -------------------- | ----------------------------------------------------------- |
| 1    | `SRC_BUCKET_ZONE1` (`Data`)  | `capteurs_zone1` | `DST_BUCKET` (`predictions`) | `prediction_zone1` | `temperature`, `humidite`, `gaz` / `temperature_pred`, `humidite_pred` |
| 2    | `SRC_BUCKET_ZONE2` (`Zone2`) | `capteurs_zone2` | `DST_BUCKET` (`predictions`) | `prediction_zone2` | `temperature`, `humidite` / `temperature_pred`, `humidite_pred` |

Note the **French field spelling** `humidite`. **MEASURED** fields are read from
the **SOURCE** base; **forecast** (`*_pred`) fields are read from the **DEST**
base. CO₂ (`gaz`) is measured-only — there is no forecast field for it.

---

## Environment variables (two bases)

Copy `.env.example` to `.env.local` for local dev and fill in. The dashboard
reads MEASURED data from the **SOURCE** base and PREDICTED data from the **DEST**
base, so it needs **both** sets of credentials (same names as the worker).

**SOURCE — Ayman's base (READ):**

| Variable           | Required | Default | Description                                              |
| ------------------ | -------- | ------- | -------------------------------------------------------- |
| `SRC_INFLUX_URL`   | yes      | —       | Ayman's InfluxDB Cloud URL                               |
| `SRC_INFLUX_ORG`   | yes      | —       | Ayman's organization name or ID                          |
| `SRC_INFLUX_TOKEN` | yes      | —       | Ayman's **read** token (kept server-side; never exposed) |
| `SRC_BUCKET_ZONE1` | no       | `Data`  | Source bucket for Zone 1                                  |
| `SRC_BUCKET_ZONE2` | no       | `Zone2` | Source bucket for Zone 2                                  |

**DESTINATION — your own base (READ):**

| Variable           | Required | Default       | Description                                              |
| ------------------ | -------- | ------------- | -------------------------------------------------------- |
| `DST_INFLUX_URL`   | yes      | —             | Your InfluxDB Cloud URL                                  |
| `DST_INFLUX_ORG`   | yes      | —             | Your organization name or ID                             |
| `DST_INFLUX_TOKEN` | yes      | —             | Your token (read is enough here; kept server-side)       |
| `DST_BUCKET`       | no       | `predictions` | Your bucket holding the forecasts                        |

These are read **only** inside the API route / `lib/influx.ts`. They are **not**
prefixed with `NEXT_PUBLIC_`, so Next.js never bundles them into client code.

> ### 📨 What to ask Ayman (SOURCE base)
> Just **one read token**. In his InfluxDB: **Load Data → API Tokens → Generate →
> Custom API Token** → check **Read** on buckets **`Data`** AND **`Zone2`** → copy.
> Send you that token plus his **`SRC_INFLUX_URL`** and **`SRC_INFLUX_ORG`**.
> *(No write access needed — his real-time collection is not touched.)*

> ### 🪣 Prepare your own InfluxDB (DESTINATION base)
> Create a free InfluxDB Cloud account → create a bucket named **`predictions`** →
> generate a token scoped to it (read is enough for the dashboard; the worker
> needs read+write). These become `DST_INFLUX_URL`, `DST_INFLUX_ORG`,
> `DST_INFLUX_TOKEN`, and `DST_BUCKET=predictions`.

---

## Run locally

```bash
npm install
cp .env.example .env.local   # then edit with your SRC_* and DST_* details
npm run dev                  # http://localhost:3000
```

Build:

```bash
npm run build
npm start
```

---

## Deploy to Vercel (3 steps)

1. **Import the repo** — push this folder to GitHub/GitLab, then in Vercel
   click **Add New → Project** and import the repository. Vercel auto-detects
   Next.js (no build settings needed). If this dashboard lives in a subfolder,
   set the project **Root Directory** to
   `My work/AI/deployment/vercel_dashboard`.
2. **Set environment variables** — in **Project → Settings → Environment
   Variables**, add the **`SRC_*`** group (`SRC_INFLUX_URL`, `SRC_INFLUX_ORG`,
   `SRC_INFLUX_TOKEN`, `SRC_BUCKET_ZONE1`, `SRC_BUCKET_ZONE2`) and the **`DST_*`**
   group (`DST_INFLUX_URL`, `DST_INFLUX_ORG`, `DST_INFLUX_TOKEN`, `DST_BUCKET`)
   for Production + Preview.
3. **Deploy** — click **Deploy**. Vercel runs `next build` and serves the app;
   the `/api/series` route runs as a serverless function with your env vars.

> **Note:** Measured lines render as soon as the **SOURCE** (`SRC_*`) base is
> reachable. The forecast (dashed amber) lines only appear once the **Render
> worker** is writing `prediction_zone1` / `prediction_zone2` into your **DEST**
> (`DST_*`) base. Until then the "Forecast Available" KPI shows **No** and only
> the measured lines render — this is expected.
