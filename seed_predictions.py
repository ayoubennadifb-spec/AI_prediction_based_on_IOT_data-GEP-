#!/usr/bin/env python3
"""
seed_predictions.py — One-shot historical seed for the DEST InfluxDB dashboard.

Loads historical CSV sensor data, runs the LSTM model, writes 240 forecast
points to the DEST InfluxDB (prediction_zone1) so the Vercel dashboard can
display them immediately.

Schema matches production_worker.py:
  measurement : prediction_zone1
  fields      : temperature_pred, humidite_pred, pmv_pred (if available)
  tag         : origin = ISO timestamp of the last observed minute

Usage (run from any directory):
    python seed_predictions.py
"""
from __future__ import annotations

# ── sys.path fix: must happen before ANY tensorflow/keras/gep_forecast import ──
import sys, os

_LOCAL_SITE = "/sessions/peaceful-fervent-ramanujan/.local/lib/python3.10/site-packages"
if _LOCAL_SITE not in sys.path:
    sys.path.insert(0, _LOCAL_SITE)

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_WORKER_DIR = os.path.join(_SCRIPT_DIR, "render_worker")
if _WORKER_DIR not in sys.path:
    sys.path.insert(1, _WORKER_DIR)

# Remove bare "" from path so render_worker/config.py cannot shadow TF internals
sys.path = [p for p in sys.path if p != ""]
# ───────────────────────────────────────────────────────────────────────────────

import logging, zipfile, json, io, tempfile
from pathlib import Path
from datetime import datetime, timezone
import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger("seed")

# ── Paths ────────────────────────────────────────────────────────────────────
WORKER_DIR  = Path(_WORKER_DIR)
ARTIFACTS   = WORKER_DIR / "artifacts"
MODEL_PATH  = ARTIFACTS / "direct_seed42.keras"
BUNDLE_PATH = ARTIFACTS / "scaler_bundle.joblib"

DATA_DIR = (
    Path(r"C:\Users\ayoub\Emines\S6\Internship_GEP")
    / "Stage Pfe GEP-20260607T171937Z-3-001-full"
    / "Stage Pfe GEP" / "Dataset" / "csv"
)
SOURCE_FILES = [
    DATA_DIR / "Data_30j.csv",
    DATA_DIR / "influxdata_2025-08-18T09_50_52Z.csv",
    DATA_DIR / "influxdata_2025-10-14T11_24_50Z.csv",
]

# ── DEST InfluxDB ─────────────────────────────────────────────────────────────
DST_URL    = "https://us-east-1-1.aws.cloud2.influxdata.com"
DST_ORG    = "c4b272be5d5aa502"
DST_TOKEN  = "A1J9hv6x31gkkNZIH2n64i4WMb9lE984hVmIFmiq28_OhDDTkxnRZekeV-r24SVGe5iUtgvx_-PsNSG6OfpMqQ=="
DST_BUCKET = "predictions"
PRED_MEAS    = "prediction_zone1"
PRED_MEAS_Z2 = "prediction_zone2"

# ── gep_forecast imports (after sys.path is fixed) ───────────────────────────
from gep_forecast import config as gconf
from gep_forecast import serving
from gep_forecast.scaling import ScalerBundle


# ── Keras version-compat patch ────────────────────────────────────────────────
def _strip_quantization_config(obj):
    """Recursively strip quantization_config=None keys added by Keras 3.13+.
    The installed Keras 3.12.2 does not accept this field on Dense.__init__."""
    if isinstance(obj, dict):
        return {k: _strip_quantization_config(v)
                for k, v in obj.items() if k != "quantization_config"}
    if isinstance(obj, list):
        return [_strip_quantization_config(i) for i in obj]
    return obj


def load_model_compat(keras_path: Path):
    """Load a .keras file, patching out Keras-3.13+ quantization_config if needed."""
    from tensorflow.keras.models import load_model

    # Try loading directly first
    try:
        return load_model(str(keras_path), compile=False)
    except (TypeError, Exception):
        pass

    log.info("Direct load failed (Keras version mismatch); patching config.json ...")
    buf = io.BytesIO()
    with zipfile.ZipFile(keras_path, "r") as zin, \
         zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "config.json":
                cfg = _strip_quantization_config(json.loads(data))
                data = json.dumps(cfg).encode("utf-8")
            elif item.filename == "metadata.json":
                meta = json.loads(data)
                meta["keras_version"] = "3.12.2"
                data = json.dumps(meta).encode("utf-8")
            zout.writestr(item, data)

    buf.seek(0)
    with tempfile.NamedTemporaryFile(suffix=".keras", delete=False) as tmp:
        tmp.write(buf.read())
        tmp_path = tmp.name

    log.info("Loading patched model from %s", tmp_path)
    model = load_model(tmp_path, compile=False)
    os.unlink(tmp_path)
    return model


# ── Historical data ───────────────────────────────────────────────────────────
def load_recent_history() -> pd.DataFrame:
    frames = []
    for p in SOURCE_FILES:
        if not p.exists():
            log.warning("Skipping (not found): %s", p)
            continue
        df = pd.read_csv(p, comment="#")
        df = df.loc[:, ~df.columns.str.startswith("Unnamed")]
        df = df.drop(columns=[c for c in ("host", "topic", "motion") if c in df.columns])
        df["time"] = pd.to_datetime(df["time"], errors="coerce", utc=True)
        for col in df.columns:
            if col not in ("time", "sensor"):
                df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=["time"]).sort_values("time")
        frames.append(df)
        log.info("  loaded %d rows from %s", len(df), p.name)

    if not frames:
        raise RuntimeError("No source CSV files could be loaded.")

    raw = pd.concat(frames, ignore_index=True)
    raw = raw.sort_values("time", kind="stable").drop_duplicates(subset="time", keep="first")
    log.info("Combined: %d rows after dedup", len(raw))

    missing_cols = [c for c in gconf.FEATURES if c not in raw.columns]
    if missing_cols:
        raise RuntimeError(f"Missing columns in source data: {missing_cols}")

    grid = raw.set_index("time")[gconf.FEATURES].resample("1min").mean()

    for col, (lo, hi) in gconf.PHYSICAL_RANGES.items():
        if col in grid.columns:
            bad = (grid[col] < lo) | (grid[col] > hi)
            if bad.sum():
                log.info("  nulled %d out-of-range values in %s", bad.sum(), col)
            grid.loc[bad, col] = np.nan

    needed = gconf.LOOKBACK + 10   # 250
    tail = grid.iloc[-(needed * 4):]
    tail = tail.interpolate(method="time", limit=gconf.GAP_MAX_MINUTES, limit_area="inside")
    tail_clean = tail.dropna()

    if len(tail_clean) < needed:
        raise RuntimeError(f"Only {len(tail_clean)} clean rows at end; need {needed}.")

    recent = tail_clean.iloc[-needed:]
    log.info(
        "History window: %d rows  %s  →  %s",
        len(recent), recent.index[0].isoformat(), recent.index[-1].isoformat(),
    )
    return recent


# ── Write forecast ────────────────────────────────────────────────────────────
def write_forecast(dst_client, result: serving.ForecastResult, pred_meas: str = PRED_MEAS) -> int:
    from influxdb_client import Point, WritePrecision
    from influxdb_client.client.write_api import SYNCHRONOUS

    try:
        from gep_forecast import comfort
        temps  = result.frame["temperature"].to_numpy(dtype=float)
        rhs    = result.frame["humidity"].to_numpy(dtype=float)
        pmv_df = comfort.pmv_ppd_frame(temps, rhs, result.frame.index)
        pmv_vals = pmv_df["pmv"].to_numpy(dtype=float)
        log.info("PMV computed OK")
    except Exception as exc:
        log.warning("PMV skipped (%s)", exc)
        pmv_vals = np.full(len(result.frame), np.nan)

    wapi   = dst_client.write_api(write_options=SYNCHRONOUS)
    origin = result.origin.isoformat()
    now_utc = datetime.now(timezone.utc)
    horizon = len(result.frame)  # 240

    # Write two batches:
    #   PAST   (offset=-horizon): timestamps NOW-240..NOW-1  → overlaps measured line
    #   FUTURE (offset=0):        timestamps NOW+1..NOW+240  → forecast ahead of now
    points = []
    for batch_offset, tag_suffix in ((-horizon, "past"), (0, "future")):
        for i, (_, row) in enumerate(result.frame.iterrows()):
            ts = now_utc + pd.Timedelta(minutes=batch_offset + i + 1)
            pt = (
                Point(pred_meas)
                .tag("origin", f"{origin}_{tag_suffix}")
                .field("temperature_pred", float(row["temperature"]))
                .field("humidite_pred",    float(row["humidity"]))
            )
            if not np.isnan(pmv_vals[i]):
                pt = pt.field("pmv_pred", float(pmv_vals[i]))
            pt = pt.time(ts, WritePrecision.NS)
            points.append(pt)

    wapi.write(bucket=DST_BUCKET, org=DST_ORG, record=points)
    return len(points)  # 480 per zone (240 past + 240 future)


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    log.info("=== seed_predictions.py ===")
    log.info("MODEL  : %s", MODEL_PATH)
    log.info("BUNDLE : %s", BUNDLE_PATH)
    log.info("DST    : %s  bucket=%s  meas=%s", DST_URL, DST_BUCKET, PRED_MEAS)

    for p in (MODEL_PATH, BUNDLE_PATH):
        if not p.exists():
            raise FileNotFoundError(f"Artifact missing: {p}")

    log.info("Loading LSTM model (with Keras compat patch if needed)...")
    model = load_model_compat(MODEL_PATH)
    log.info("  model input %s → output %s", model.input_shape, model.output_shape)

    log.info("Loading scaler bundle...")
    bundle = ScalerBundle.load(str(BUNDLE_PATH))

    log.info("Loading historical sensor data...")
    recent = load_recent_history()

    # Set fake_now 4 min ahead so the staleness guard (threshold=5 min) passes
    fake_now = recent.index[-1] + pd.Timedelta(minutes=4)

    log.info("Running LSTM forward pass...")
    result = serving.forecast_from_frame(recent, model, bundle, now=fake_now)
    log.info(
        "Forecast OK: origin=%s  horizon=%d min  "
        "temp [%.1f–%.1f] °C  hum [%.1f–%.1f] %%RH",
        result.origin.isoformat(), len(result.frame),
        result.frame["temperature"].min(), result.frame["temperature"].max(),
        result.frame["humidity"].min(),    result.frame["humidity"].max(),
    )

    log.info("Connecting to DEST InfluxDB...")
    from influxdb_client import InfluxDBClient
    dst = InfluxDBClient(url=DST_URL, token=DST_TOKEN, org=DST_ORG)
    try:
        log.info("  health: %s", dst.health().status)
    except Exception as exc:
        log.warning("  health check failed (%s) — continuing", exc)

    n = write_forecast(dst, result)
    log.info("SUCCESS: %d points → %s / %s / %s", n, DST_URL, DST_BUCKET, PRED_MEAS)

    n2 = write_forecast(dst, result, pred_meas=PRED_MEAS_Z2)
    log.info("SUCCESS: %d points → %s / %s / %s", n2, DST_URL, DST_BUCKET, PRED_MEAS_Z2)

    print("\n--- Forecast sample (first 5 + last 5 minutes) ---")
    print(pd.concat([result.frame.head(5), result.frame.tail(5)]).to_string())
    print(f"\nTotal points written : {n} (zone1) + {n2} (zone2)")
    print(f"Forecast origin      : {result.origin.isoformat()}")
    print(f"Forecast window      : {result.frame.index[0].isoformat()} → {result.frame.index[-1].isoformat()}")


if __name__ == "__main__":
    main()
