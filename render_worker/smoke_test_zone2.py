#!/usr/bin/env python3
"""Smoke test for the Zone-2 (co2-free) deployment artifacts.

Verifies, under the patched 2-feature contract:
  1. scaler_bundle_zone2.joblib loads (contract check passes).
  2. direct_zone2.keras loads with input (None,240,4) / output (None,240,2).
  3. serving.forecast_from_frame returns a 240-row frame on synthetic
     temperature+humidity history (no co2 anywhere).
"""
from __future__ import annotations

from pathlib import Path

# --- patch the 2-feature contract BEFORE importing features/serving ---------
from gep_forecast import config as gconf

gconf.FEATURES = ["temperature", "humidity"]
gconf.TARGETS = ["temperature", "humidity"]

import numpy as np
import pandas as pd

from gep_forecast import features as gfeatures, serving
from gep_forecast.scaling import ScalerBundle
from tensorflow.keras.models import load_model

HERE = Path(__file__).resolve().parent
MODEL_PATH = HERE / "artifacts_zone2" / "direct_zone2.keras"
BUNDLE_PATH = HERE / "artifacts_zone2" / "scaler_bundle_zone2.joblib"

assert gfeatures.MODEL_FEATURES == ["temperature", "humidity", "hour_sin", "hour_cos"], \
    gfeatures.MODEL_FEATURES

# 1. bundle loads under the patched contract
bundle = ScalerBundle.load(BUNDLE_PATH)
assert bundle.features == ["temperature", "humidity"], bundle.features
assert bundle.lookback == 240 and bundle.horizon == 240
print(f"OK  bundle loads: features={bundle.features} "
      f"lookback={bundle.lookback} horizon={bundle.horizon}")

# 2. model loads with the right shapes
model = load_model(MODEL_PATH, compile=False)
assert tuple(model.input_shape) == (None, 240, 4), model.input_shape
assert tuple(model.output_shape) == (None, 240, 2), model.output_shape
print(f"OK  model loads: input={model.input_shape} output={model.output_shape}")

# 3. forecast_from_frame on synthetic 2-channel history -> 240-row frame
n = gconf.LOOKBACK + 10
now = pd.Timestamp.now(tz="UTC").floor("1min")
idx = pd.date_range(now - pd.Timedelta(minutes=n - 1), periods=n, freq="1min",
                    tz="UTC", name="time")
rng = np.random.default_rng(7)
recent = pd.DataFrame(
    {
        "temperature": 24.0 + np.cumsum(rng.normal(0, 0.02, n)),
        "humidity": 50.0 + np.cumsum(rng.normal(0, 0.05, n)),
    },
    index=idx,
)
result = serving.forecast_from_frame(recent.reset_index(), model, bundle, now=now)
assert len(result.frame) == gconf.HORIZON, len(result.frame)
assert list(result.frame.columns) == ["temperature", "humidity"], list(result.frame.columns)
assert not result.frame.isna().any().any(), "NaN in forecast frame"
print(f"OK  forecast_from_frame: {len(result.frame)} rows, "
      f"cols={list(result.frame.columns)}, origin={result.origin}")
print(result.frame.head(3).to_string())
print(f"    forecast ranges: temp [{result.frame['temperature'].min():.2f}, "
      f"{result.frame['temperature'].max():.2f}] degC, "
      f"hum [{result.frame['humidity'].min():.2f}, "
      f"{result.frame['humidity'].max():.2f}] %RH")
print("\nALL SMOKE CHECKS PASSED")
