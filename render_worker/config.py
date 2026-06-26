"""Central configuration for the LSTM inference worker.

ALL tunables live here. Secrets are read from environment variables ONLY
(never hardcode an InfluxDB token in source control).

================================================================================
 >>> CONFIRM FROM YOUR TRAINING <<<
================================================================================
The defaults below are a GENERIC starting point. Several of them MUST match the
exact contract used when the model was trained, or the worker will produce
garbage online even though it scored well offline. The fields flagged
`# >>> CONFIRM FROM YOUR TRAINING <<<` are the ones you must verify.

Notes from the real GEP training pipeline (gep_forecast/) -- READ THESE:
  * The shipped models were trained with LOOKBACK = HORIZON = 240 (4h @ 1min),
    NOT the 120/240 placeholder defaults below. Set them to 240/240 if you
    deploy `direct_seed42.keras`.
  * Training FEATURES were ["temperature", "humidity", "co2"] PLUS two derived
    time channels (hour_sin, hour_cos), giving a 5-channel input
    (model.input_shape == (None, 240, 5)). If you deploy that model you must:
        - set FEATURES to the 3 sensor channels,
        - enable TIME_FEATURES below,
        - and map InfluxDB's French field names (humidite, gaz) to the
          English training names (humidity, co2) via FIELD_MAP.
  * The real model predicts a RESIDUAL (delta from the last observed value),
    not an absolute forecast. If your model does the same, set
    OUTPUT_IS_RESIDUAL = True so the worker adds the delta back before writing.
  * The real scaler is a per-channel `ScalerBundle` object, not a bare sklearn
    scaler. See preprocess.py / SCALER_KIND for how to handle both.
This generic worker defaults to the SIMPLE contract described in the spec
(2 features, absolute output, plain sklearn scaler) so it runs out of the box;
flip the flags above to match the production model.
================================================================================
"""
from __future__ import annotations

import os
from typing import Dict, List

# ---------------------------------------------------------------------------
# Window contract  -- MUST equal the training contract
# ---------------------------------------------------------------------------
# Number of input timesteps (minutes of history fed to the model).
# Asserted at startup against model.input_shape[1].
LOOKBACK_MIN: int = 120          # >>> CONFIRM FROM YOUR TRAINING <<< (real model: 240)

# Number of forecast timesteps emitted in ONE forward pass (direct multi-step).
# Asserted at startup against the model output length.
HORIZON_MIN: int = 240           # >>> CONFIRM FROM YOUR TRAINING <<< (real model: 240)

# Base sampling resolution. The 1-min grid (aggregateWindow every 1m) must match
# the grid the windows were built on.
RESOLUTION_MIN: int = 1          # >>> CONFIRM FROM YOUR TRAINING <<<

# ---------------------------------------------------------------------------
# Features / targets  -- order MUST match training, names MUST match the scaler
# ---------------------------------------------------------------------------
# Sensor channels fed to the model, in EXACT training order. These names are the
# *training* names (what the scaler was fit on); InfluxDB field names may differ
# (French) and are mapped via FIELD_MAP below.
FEATURES: List[str] = ["temperature", "humidite"]   # >>> CONFIRM FROM YOUR TRAINING <<<
#   Real model: ["temperature", "humidity", "co2"]

# Channels the model forecasts, in output order.
TARGETS: List[str] = ["temperature", "humidite"]    # >>> CONFIRM FROM YOUR TRAINING <<<
#   Real model: ["temperature", "humidity"]

# Map: training feature name -> InfluxDB field name. The worker queries Influx
# using the RIGHT side, then renames to the LEFT side so the scaler and model
# see the names they were trained on. Zone 1 uses French field names.
# (humidity<->humidite, co2<->gaz are the gotchas.)
FIELD_MAP: Dict[str, str] = {        # >>> CONFIRM FROM YOUR TRAINING <<<
    "temperature": "temperature",
    "humidite": "humidite",
    # "humidity": "humidite",
    # "co2": "gaz",
}

# Derived deterministic time channels appended after the sensor features
# (hour_sin, hour_cos). The real GEP model REQUIRES these (it is 5-channel).
# Leave False for the simple 2-feature contract.
USE_TIME_FEATURES: bool = False      # >>> CONFIRM FROM YOUR TRAINING <<<

# Does the model emit a RESIDUAL (delta vs. the last observed value) instead of
# an absolute forecast? The production GEP model does. If True, the worker adds
# the (inverse-scaled) last observation back per target.
OUTPUT_IS_RESIDUAL: bool = False     # >>> CONFIRM FROM YOUR TRAINING <<<

# ---------------------------------------------------------------------------
# Artifacts dropped into model/ by the user
# ---------------------------------------------------------------------------
MODEL_PATH: str = "model/lstm.keras"     # >>> CONFIRM FROM YOUR TRAINING <<<
SCALER_PATH: str = "model/scaler.pkl"    # >>> CONFIRM FROM YOUR TRAINING <<<

# How the scaler was persisted:
#   "sklearn"  -> a single fitted sklearn scaler covering all FEATURES columns
#                 (one .transform on the full feature matrix).
#   "perchannel" -> a dict {feature_name: fitted_scaler}, one scaler per column.
#   "bundle"   -> the gep_forecast ScalerBundle object (has .scalers dict +
#                 .transform_array / .inverse_transform_array). Requires the
#                 gep_forecast package importable, OR use "perchannel" after
#                 re-exporting the inner .scalers dict.
SCALER_KIND: str = "sklearn"             # >>> CONFIRM FROM YOUR TRAINING <<<

# ---------------------------------------------------------------------------
# Loop cadence & freshness guards
# ---------------------------------------------------------------------------
PREDICT_EVERY_SEC: int = 60          # run one forecast cycle this often
MAX_STALENESS_MIN: int = 10          # skip a zone if newest point is older than this
# Minimum number of REAL (non-NaN) 1-min points required inside the lookback
# window before we trust it. Below this we are mostly forward-filling / flat,
# which is exactly the data the model must NOT predict on.
MIN_FRESH_POINTS: int = max(1, int(0.5 * LOOKBACK_MIN))   # >>> CONFIRM <<< (default: 50% coverage)

# ---------------------------------------------------------------------------
# Forecast time step (minutes between successive horizon points)
# ---------------------------------------------------------------------------
# Future timestamp of horizon step i is  now + i * DELTA_MIN.
DELTA_MIN: int = RESOLUTION_MIN

# ---------------------------------------------------------------------------
# InfluxDB connection  -- secrets via ENV ONLY
# ---------------------------------------------------------------------------
INFLUX_URL: str = os.environ.get("INFLUX_URL", "https://us-east-1-1.aws.cloud2.influxdata.com")
INFLUX_ORG: str = os.environ.get("INFLUX_ORG", "")
INFLUX_TOKEN: str = os.environ.get("INFLUX_TOKEN", "")

# Per-zone buckets (overridable via env).
INFLUX_BUCKET_ZONE1: str = os.environ.get("INFLUX_BUCKET_ZONE1", "Data")
INFLUX_BUCKET_ZONE2: str = os.environ.get("INFLUX_BUCKET_ZONE2", "Zone2")

# ---------------------------------------------------------------------------
# Zones
# ---------------------------------------------------------------------------
# Each zone: which bucket/measurement to read sensor data from, and which
# measurement to write forecasts to. Zone 2 has FEWER sensors -- see README
# "Zone-2 caveat": only features common to the model are used (here: the model
# uses temperature+humidite which both exist in Zone 2).
ZONES: Dict[str, Dict[str, str]] = {
    "zone1": {
        "bucket": INFLUX_BUCKET_ZONE1,
        "measurement": "capteurs_zone1",
        "pred_measurement": "prediction_zone1",
    },
    "zone2": {
        "bucket": INFLUX_BUCKET_ZONE2,
        "measurement": "capteurs_zone2",
        "pred_measurement": "prediction_zone2",
    },
}

# Optional tag value the on-site scripts attach to a sensor node, used to filter
# the Flux query. Set to None to read all series of the measurement (then the
# pivot/mean collapses them). Leave None unless your data is multi-sensor.
SENSOR_TAG_KEY: str | None = None        # e.g. "sensor"
SENSOR_TAG_VALUE: str | None = None      # e.g. "sensor_1"


def influx_settings_ok() -> bool:
    """True if the mandatory InfluxDB secrets are present in the environment."""
    return bool(INFLUX_URL and INFLUX_ORG and INFLUX_TOKEN)
