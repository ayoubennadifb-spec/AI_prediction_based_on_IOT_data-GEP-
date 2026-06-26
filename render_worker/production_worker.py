#!/usr/bin/env python3
"""
Production inference worker  --  ZONE 1 + ZONE 2  (architecture "2 bases").

Reads the LIVE sensor data from the SOURCE InfluxDB (Ayman's) and writes the
forecasts to YOUR DESTINATION InfluxDB. Ayman's collection is never touched
(read-only on his side); you never write into his base.

    SOURCE (Ayman, READ)            DESTINATION (yours, WRITE)
    capteurs_zone1  ┐                 ┌  prediction_zone1
    capteurs_zone2  ┘ --> forecast -> ┘  prediction_zone2   --> your dashboard

It REUSES your validated pipeline (`gep_forecast.serving.forecast_from_frame`):
identical time-features, the persisted ScalerBundle, a single direct multi-step
forward pass (no recursive rollout), residual reconstruction. So online output
== your validated offline output.

ZONE 2 has no co2 sensor; it is served with the SAME 3-feature model by feeding
co2 = its training mean (neutral). Set SERVE_ZONE2_PROXY=false to disable.

>>> All you need to fill: the two tokens (SRC_INFLUX_TOKEN, DST_INFLUX_TOKEN)
    and the two URLs/orgs. Everything else has sensible defaults. <<<

Deploy on Render as a `type: worker`.
"""
from __future__ import annotations

import logging
import os
import time

import pandas as pd
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

# --- your validated pipeline (vendored next to this file) ------------------
from gep_forecast import config as gconf
from gep_forecast import serving
from gep_forecast.scaling import ScalerBundle
from tensorflow.keras.models import load_model

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger("worker")

# ===========================================================================
# SOURCE = Ayman's InfluxDB  (READ the live sensors)
# ===========================================================================
SRC_URL = os.environ.get("SRC_INFLUX_URL", "https://us-east-1-1.aws.cloud2.influxdata.com")
SRC_ORG = os.environ.get("SRC_INFLUX_ORG", "")        # <<< Ayman's org
SRC_TOKEN = os.environ.get("SRC_INFLUX_TOKEN", "")    # <<< Ayman's READ token
SRC_BUCKET_ZONE1 = os.environ.get("SRC_BUCKET_ZONE1", "Data")
SRC_BUCKET_ZONE2 = os.environ.get("SRC_BUCKET_ZONE2", "Zone2")
# Ayman has ONE token PER bucket (the existing ESP32 tokens in a(1)/a2(1)).
# Set a per-zone token to use them as-is; otherwise they fall back to a single
# SRC_INFLUX_TOKEN (e.g. one all-access read token).
SRC_TOKEN_ZONE1 = os.environ.get("SRC_INFLUX_TOKEN_ZONE1") or SRC_TOKEN
SRC_TOKEN_ZONE2 = os.environ.get("SRC_INFLUX_TOKEN_ZONE2") or SRC_TOKEN

# ===========================================================================
# DESTINATION = YOUR InfluxDB  (WRITE the predictions)
# ===========================================================================
DST_URL = os.environ.get("DST_INFLUX_URL", "")        # <<< your InfluxDB url
DST_ORG = os.environ.get("DST_INFLUX_ORG", "")        # <<< your org
DST_TOKEN = os.environ.get("DST_INFLUX_TOKEN", "")    # <<< your READ+WRITE token
DST_BUCKET = os.environ.get("DST_BUCKET", "predictions")

PREDICT_EVERY_SEC = int(os.environ.get("PREDICT_EVERY_SEC", "600"))  # 10-min cadence
MODEL_PATH = os.environ.get("MODEL_PATH", "artifacts/direct_seed42.keras")
BUNDLE_PATH = os.environ.get("BUNDLE_PATH", "artifacts/scaler_bundle.joblib")
SERVE_ZONE2_PROXY = os.environ.get("SERVE_ZONE2_PROXY", "true").lower() == "true"
# RUN_ONCE=1 -> run a single forecast cycle then exit (for cron / GitHub Actions,
# where the SCHEDULER handles the cadence instead of the internal loop).
RUN_ONCE = os.environ.get("RUN_ONCE", "").lower() in ("1", "true", "yes")

# --- schema bridge: Ayman's ingestion uses French field names --------------
FIELD_MAP_ZONE1 = {"temperature": "temperature", "humidite": "humidity", "gaz": "co2"}
FIELD_MAP_ZONE2 = {"temperature": "temperature", "humidite": "humidity"}
MEAS_ZONE1, PRED_MEAS_ZONE1 = "capteurs_zone1", "prediction_zone1"
MEAS_ZONE2, PRED_MEAS_ZONE2 = "capteurs_zone2", "prediction_zone2"


def _query_pivot(src_client, bucket, measurement, influx_fields) -> pd.DataFrame:
    """Last LOOKBACK+10 min of the given fields from the SOURCE base, pivoted to
    one row per minute. No fill(usePrevious): gaps stay visible for the guard."""
    lb = gconf.LOOKBACK + 10
    flux = f'''
    from(bucket: "{bucket}")
      |> range(start: -{lb}m)
      |> filter(fn: (r) => r._measurement == "{measurement}")
      |> filter(fn: (r) => contains(value: r._field, set: {influx_fields!r}))
      |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
    '''
    tables = src_client.query_api().query_data_frame(flux)
    df = pd.concat(tables) if isinstance(tables, list) else tables
    if df is None or len(df) == 0:
        raise serving.ServingDataError(f"no data from source {bucket}/{measurement}")
    return df


def fetch_zone1(src_client) -> pd.DataFrame:
    df = _query_pivot(src_client, SRC_BUCKET_ZONE1, MEAS_ZONE1, list(FIELD_MAP_ZONE1))
    df = df.rename(columns={"_time": "time", **FIELD_MAP_ZONE1})
    missing = [c for c in gconf.FEATURES if c not in df.columns]
    if missing:
        raise serving.ServingDataError(f"zone1 missing features after map: {missing}")
    df = df[["time", *gconf.FEATURES]].copy()
    df["time"] = pd.to_datetime(df["time"], utc=True)
    return df


def fetch_zone2(src_client, co2_proxy: float) -> pd.DataFrame:
    df = _query_pivot(src_client, SRC_BUCKET_ZONE2, MEAS_ZONE2, list(FIELD_MAP_ZONE2))
    df = df.rename(columns={"_time": "time", **FIELD_MAP_ZONE2})
    for c in ("temperature", "humidity"):
        if c not in df.columns:
            raise serving.ServingDataError(f"zone2 missing field: {c}")
    df["co2"] = co2_proxy                                   # neutral proxy
    df = df[["time", *gconf.FEATURES]].copy()
    df["time"] = pd.to_datetime(df["time"], utc=True)
    return df


def write_forecast(dst_client, result, measurement: str) -> int:
    """Write the 4 h forecast to YOUR base (DST_BUCKET), dashboard schema:
    fields `temperature_pred`, `humidite_pred`, one point per future minute."""
    wapi = dst_client.write_api(write_options=SYNCHRONOUS)
    points = []
    for ts, row in result.frame.iterrows():
        points.append(
            Point(measurement)
            .tag("origin", result.origin.isoformat())
            .field("temperature_pred", float(row["temperature"]))
            .field("humidite_pred", float(row["humidity"]))
            .time(ts.to_pydatetime(), WritePrecision.NS)
        )
    wapi.write(bucket=DST_BUCKET, org=DST_ORG, record=points)
    return len(points)


def run_zone(dst_client, model, bundle, recent, pred_meas, label) -> None:
    try:
        result = serving.forecast_from_frame(recent, model, bundle)
        n = write_forecast(dst_client, result, pred_meas)
        log.info("%s OK: origin=%s -> wrote %d forecast points", label, result.origin, n)
    except serving.ServingDataError as e:
        log.warning("%s SKIP (bad input): %s", label, e)
    except Exception as e:  # noqa: BLE001 - keep the worker alive
        log.exception("%s ERROR: %s", label, e)


def main() -> None:
    missing = [k for k, v in {
        "SRC_INFLUX_URL": SRC_URL, "SRC_INFLUX_ORG": SRC_ORG,
        "SRC token (zone1)": SRC_TOKEN_ZONE1, "SRC token (zone2)": SRC_TOKEN_ZONE2,
        "DST_INFLUX_URL": DST_URL, "DST_INFLUX_ORG": DST_ORG, "DST_INFLUX_TOKEN": DST_TOKEN,
    }.items() if not v]
    if missing:
        raise SystemExit("Missing env vars: " + ", ".join(missing))

    log.info("Loading model %s + scaler bundle %s ...", MODEL_PATH, BUNDLE_PATH)
    model = load_model(MODEL_PATH, compile=False)
    bundle = ScalerBundle.load(BUNDLE_PATH)
    co2_proxy = float(bundle.scalers["co2"].mean_[0])
    log.info(
        "Ready. model %s->%s | SRC=%s DST=%s/%s | zone2_proxy=%s (co2~%.1f)",
        model.input_shape, model.output_shape, SRC_URL, DST_URL, DST_BUCKET,
        SERVE_ZONE2_PROXY, co2_proxy,
    )

    # READ Ayman -- one client per zone (each bucket may have its own token)
    src_zone1 = InfluxDBClient(url=SRC_URL, token=SRC_TOKEN_ZONE1, org=SRC_ORG)
    src_zone2 = InfluxDBClient(url=SRC_URL, token=SRC_TOKEN_ZONE2, org=SRC_ORG)
    dst_client = InfluxDBClient(url=DST_URL, token=DST_TOKEN, org=DST_ORG)   # WRITE yours

    while True:
        t0 = time.time()
        try:
            run_zone(dst_client, model, bundle, fetch_zone1(src_zone1),
                     PRED_MEAS_ZONE1, "zone1")
        except serving.ServingDataError as e:
            log.warning("zone1 SKIP (no source data): %s", e)

        if SERVE_ZONE2_PROXY:
            try:
                run_zone(dst_client, model, bundle, fetch_zone2(src_zone2, co2_proxy),
                         PRED_MEAS_ZONE2, "zone2")
            except serving.ServingDataError as e:
                log.warning("zone2 SKIP (no source data): %s", e)

        if RUN_ONCE:
            log.info("RUN_ONCE -> one cycle done, exiting (cron mode).")
            break
        time.sleep(max(1.0, PREDICT_EVERY_SEC - (time.time() - t0)))


if __name__ == "__main__":
    main()
