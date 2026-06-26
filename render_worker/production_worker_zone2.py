#!/usr/bin/env python3
"""
Production inference worker for the GEP indoor-climate LSTM  --  ZONE 2 (co2-free).

Zone 2's IoT sensors have NO co2/gas sensor, so Zone 2 is served by a DEDICATED
2-channel model (temperature + humidity only) trained with the same validated
`gep_forecast` pipeline -- NOT by the 3-channel Zone-1 model with a co2 proxy.

It REUSES the validated serving path that already lives in the vendored package
(`gep_forecast.serving.forecast_from_frame`): identical time-features, the same
persisted ScalerBundle, a single direct multi-step forward pass (NO recursive
rollout), and residual reconstruction back to physical units. So what runs
online is byte-for-byte the pipeline validated offline -- only the feature set
is 2 channels instead of 3.

Loop (every PREDICT_EVERY_SEC):
    InfluxDB capteurs_zone2  ->  forecast 4 h  ->  InfluxDB prediction_zone2
                                                   (fields temperature_pred,
                                                    humidite_pred  --> dashboard)

If you deploy this worker, set SERVE_ZONE2_PROXY=false in the Zone-1 worker
(`production_worker.py`) so the two workers do not both write prediction_zone2.

Deploy on Render as a `type: worker`. Secrets come from environment variables.
"""
from __future__ import annotations

import logging
import os
import time

# ===========================================================================
# CONTRACT PATCH -- MUST happen before importing features / serving.
# gep_forecast.features computes MODEL_FEATURES = config.FEATURES + TIME_FEATURES
# and TARGET_IDX at IMPORT time, and serving imports features. So patch the
# in-memory config FIRST; the 2-channel contract then propagates everywhere.
# (This mutates the imported config object in memory only -- it does NOT modify
#  the vendored gep_forecast source files.)
# ---------------------------------------------------------------------------
from gep_forecast import config as gconf

gconf.FEATURES = ["temperature", "humidity"]   # Zone 2 has no gas sensor
gconf.TARGETS = ["temperature", "humidity"]

# Only NOW import the modules that snapshot config at import time.
import pandas as pd
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

from gep_forecast import serving
from gep_forecast import features as gfeatures
from gep_forecast.scaling import ScalerBundle
from tensorflow.keras.models import load_model

# Hard contract check -- fail loud if the patch did not take effect.
assert gfeatures.MODEL_FEATURES == ["temperature", "humidity", "hour_sin", "hour_cos"], (
    f"Zone-2 contract patch failed: MODEL_FEATURES={gfeatures.MODEL_FEATURES}"
)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s"
)
log = logging.getLogger("worker_zone2")

# --- connection / cadence (env only) ---------------------------------------
INFLUX_URL = os.environ.get(
    "INFLUX_URL", "https://us-east-1-1.aws.cloud2.influxdata.com"
)
INFLUX_ORG = os.environ.get("INFLUX_ORG", "")
INFLUX_TOKEN = os.environ.get("INFLUX_TOKEN", "")
BUCKET_ZONE2 = os.environ.get("INFLUX_BUCKET_ZONE2", "Zone2")
PREDICT_EVERY_SEC = int(os.environ.get("PREDICT_EVERY_SEC", "600"))  # 10-min cadence

MODEL_PATH = os.environ.get("MODEL_PATH", "artifacts_zone2/direct_zone2.keras")
BUNDLE_PATH = os.environ.get("BUNDLE_PATH", "artifacts_zone2/scaler_bundle_zone2.joblib")

# --- schema bridge: Ayman's ingestion uses French field names --------------
# InfluxDB live field -> training feature name. Zone 2 has only temp + humidite.
FIELD_MAP_ZONE2 = {"temperature": "temperature", "humidite": "humidity"}

MEAS_ZONE2, PRED_MEAS_ZONE2 = "capteurs_zone2", "prediction_zone2"


def _query_pivot(client: InfluxDBClient, bucket: str, measurement: str,
                 influx_fields: list[str]) -> pd.DataFrame:
    """Pull the last LOOKBACK+10 min of the given fields, pivoted to one row per
    minute. No fill(usePrevious): gaps stay visible so the staleness/gap guard
    inside forecast_from_frame can reject bad windows."""
    lb = gconf.LOOKBACK + 10
    flux = f'''
    from(bucket: "{bucket}")
      |> range(start: -{lb}m)
      |> filter(fn: (r) => r._measurement == "{measurement}")
      |> filter(fn: (r) => contains(value: r._field, set: {influx_fields!r}))
      |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
    '''
    tables = client.query_api().query_data_frame(flux)
    df = pd.concat(tables) if isinstance(tables, list) else tables
    if df is None or len(df) == 0:
        raise serving.ServingDataError(
            f"no data from {bucket}/{measurement}"
        )
    return df


def fetch_zone2(client: InfluxDBClient) -> pd.DataFrame:
    """Zone 2: temperature + humidite (no gas sensor)  ->  temperature, humidity."""
    df = _query_pivot(client, BUCKET_ZONE2, MEAS_ZONE2, list(FIELD_MAP_ZONE2))
    df = df.rename(columns={"_time": "time", **FIELD_MAP_ZONE2})
    missing = [c for c in gconf.FEATURES if c not in df.columns]
    if missing:
        raise serving.ServingDataError(f"zone2 missing features after map: {missing}")
    df = df[["time", *gconf.FEATURES]].copy()
    df["time"] = pd.to_datetime(df["time"], utc=True)
    return df


def write_forecast(client: InfluxDBClient, result: "serving.ForecastResult",
                   measurement: str, bucket: str) -> int:
    """Write the 4 h forecast in the dashboard's schema: fields
    `temperature_pred` and `humidite_pred`, one point per future minute."""
    wapi = client.write_api(write_options=SYNCHRONOUS)
    points = []
    for ts, row in result.frame.iterrows():
        points.append(
            Point(measurement)
            .tag("origin", result.origin.isoformat())
            .field("temperature_pred", float(row["temperature"]))
            .field("humidite_pred", float(row["humidity"]))  # target 'humidity' -> field 'humidite_pred'
            .time(ts.to_pydatetime(), WritePrecision.NS)
        )
    wapi.write(bucket=bucket, org=INFLUX_ORG, record=points)
    return len(points)


def run_zone(client, model, bundle, recent, pred_meas, bucket, label) -> None:
    """One forecast cycle for a zone: forecast -> write, with clean skipping."""
    try:
        result = serving.forecast_from_frame(recent, model, bundle)
        n = write_forecast(client, result, pred_meas, bucket)
        log.info("%s OK: origin=%s -> wrote %d forecast points", label, result.origin, n)
    except serving.ServingDataError as e:
        log.warning("%s SKIP (bad input): %s", label, e)
    except Exception as e:  # noqa: BLE001 - keep the worker alive
        log.exception("%s ERROR: %s", label, e)


def main() -> None:
    if not (INFLUX_URL and INFLUX_ORG and INFLUX_TOKEN):
        raise SystemExit(
            "Missing InfluxDB secrets: set INFLUX_URL, INFLUX_ORG, INFLUX_TOKEN."
        )

    log.info("Loading Zone-2 model %s + scaler bundle %s ...", MODEL_PATH, BUNDLE_PATH)
    model = load_model(MODEL_PATH, compile=False)
    bundle = ScalerBundle.load(BUNDLE_PATH)  # refuses if its contract != config
    log.info(
        "Ready (Zone 2, co2-free). model input=%s output=%s | contract "
        "LOOKBACK=%d HORIZON=%d FEATURES=%s TARGETS=%s",
        model.input_shape, model.output_shape,
        gconf.LOOKBACK, gconf.HORIZON, gconf.FEATURES, gconf.TARGETS,
    )

    client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)

    while True:
        t0 = time.time()

        # --- Zone 2 (temperature + humidity, dedicated 2-channel model) ---
        try:
            run_zone(client, model, bundle, fetch_zone2(client),
                     PRED_MEAS_ZONE2, BUCKET_ZONE2, "zone2")
        except serving.ServingDataError as e:
            log.warning("zone2 SKIP (no data): %s", e)

        elapsed = time.time() - t0
        time.sleep(max(1.0, PREDICT_EVERY_SEC - elapsed))


if __name__ == "__main__":
    main()
