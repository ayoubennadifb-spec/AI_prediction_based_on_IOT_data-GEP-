"""Preprocessing: persisted-scaler loading, input-tensor build, inverse scale.

CORRECTNESS RULE #3 (see README): the SAME scaler persisted at training time is
loaded and REUSED here -- it is NEVER refit on serving data. Refitting online is
a classic silent failure (the online distribution differs from training, so a
refit scaler maps the model into a region it never saw).

This module supports three scaler persistence formats via config.SCALER_KIND:
  "sklearn"    : one fitted sklearn scaler for the whole feature matrix.
  "perchannel" : dict {feature_name -> fitted sklearn scaler} (one per column).
  "bundle"     : the gep_forecast ScalerBundle object (per-channel + contract).
"""
from __future__ import annotations

import logging
from typing import List

import joblib
import numpy as np
import pandas as pd

import config

logger = logging.getLogger("preprocess")


# ---------------------------------------------------------------------------
# Scaler loading
# ---------------------------------------------------------------------------
def load_scaler(path: str | None = None):
    """Load the persisted scaler object (whatever its kind)."""
    path = path or config.SCALER_PATH
    scaler = joblib.load(path)
    logger.info("Scaler charge depuis %s (type=%s, kind=%s).",
                path, type(scaler).__name__, config.SCALER_KIND)
    return scaler


# ---------------------------------------------------------------------------
# Time features (only if the model was trained with them)
# ---------------------------------------------------------------------------
def add_time_features(df: pd.DataFrame) -> pd.DataFrame:
    """Append hour_sin / hour_cos derived from the tz-aware UTC index.

    Must reproduce training EXACTLY (gep_forecast.features.add_time_features):
    angle = 2*pi*(hour + minute/60)/24.
    """
    out = df.copy()
    frac_hour = out.index.hour + out.index.minute / 60.0
    angle = 2.0 * np.pi * frac_hour / 24.0
    out["hour_sin"] = np.sin(angle).astype(np.float64)
    out["hour_cos"] = np.cos(angle).astype(np.float64)
    return out


# ---------------------------------------------------------------------------
# Scale a feature frame  (forward transform)
# ---------------------------------------------------------------------------
def _scale_features(scaler, df_feat: pd.DataFrame, feature_order: List[str]) -> np.ndarray:
    """Return the scaled (LOOKBACK, n_features) matrix for sensor features.

    Only the *sensor* FEATURES are scaled here; raw time channels (if any) are
    appended later un-scaled (they are already in [-1, 1]).
    """
    arr = df_feat[feature_order].to_numpy(dtype=np.float64)

    if config.SCALER_KIND == "sklearn":
        return scaler.transform(arr)

    if config.SCALER_KIND == "perchannel":
        out = np.empty_like(arr)
        for j, col in enumerate(feature_order):
            out[:, j] = scaler[col].transform(arr[:, [j]]).ravel()
        return out

    if config.SCALER_KIND == "bundle":
        # gep_forecast ScalerBundle: per-column .scalers dict.
        out = np.empty_like(arr)
        for j, col in enumerate(feature_order):
            out[:, j] = scaler.scalers[col].transform(arr[:, [j]]).ravel()
        return out

    raise ValueError(f"SCALER_KIND inconnu: {config.SCALER_KIND!r}")


def build_input_tensor(scaler, grid: pd.DataFrame) -> np.ndarray:
    """Build the (1, LOOKBACK, n_model_features) float32 model input.

    ``grid`` : exactly-LOOKBACK rows, 1-min, NaN-free, columns >= FEATURES,
               tz-aware UTC index.
    Feature order is config.FEATURES (sensor channels) optionally followed by
    [hour_sin, hour_cos] when config.USE_TIME_FEATURES is True.
    """
    scaled_sensor = _scale_features(scaler, grid, config.FEATURES)   # (L, n_feat)

    if config.USE_TIME_FEATURES:
        gt = add_time_features(grid)
        time_block = gt[["hour_sin", "hour_cos"]].to_numpy(dtype=np.float64)
        scaled = np.concatenate([scaled_sensor, time_block], axis=1)
    else:
        scaled = scaled_sensor

    X = scaled.astype(np.float32)[None, ...]    # (1, LOOKBACK, n_model_features)
    return X


# ---------------------------------------------------------------------------
# Inverse-transform the model output back to physical units
# ---------------------------------------------------------------------------
def _inverse_targets(scaler, y_scaled: np.ndarray) -> np.ndarray:
    """Inverse-scale a (HORIZON, n_targets) array from scaled -> physical.

    Uses the per-TARGET scalers. For a single global "sklearn" scaler fit on all
    FEATURES, we slice that scaler's per-column parameters for the target columns
    so we don't need the (unobserved) feature columns at inverse time.
    """
    targets = config.TARGETS

    if config.SCALER_KIND == "sklearn":
        # Build a full-width zero matrix, place targets in their feature columns,
        # inverse-transform, then read the target columns back. This works for
        # MinMax/Standard scalers (column-wise affine).
        feat_index = {f: i for i, f in enumerate(config.FEATURES)}
        n_feat = len(config.FEATURES)
        H = y_scaled.shape[0]
        full = np.zeros((H, n_feat), dtype=np.float64)
        for k, t in enumerate(targets):
            full[:, feat_index[t]] = y_scaled[:, k]
        inv_full = scaler.inverse_transform(full)
        out = np.empty((H, len(targets)), dtype=np.float64)
        for k, t in enumerate(targets):
            out[:, k] = inv_full[:, feat_index[t]]
        return out

    if config.SCALER_KIND in ("perchannel", "bundle"):
        scalers = scaler if config.SCALER_KIND == "perchannel" else scaler.scalers
        out = np.empty_like(y_scaled, dtype=np.float64)
        for k, t in enumerate(targets):
            out[:, k] = scalers[t].inverse_transform(y_scaled[:, [k]]).ravel()
        return out

    raise ValueError(f"SCALER_KIND inconnu: {config.SCALER_KIND!r}")


def postprocess_prediction(
    scaler,
    y_model: np.ndarray,
    X_input: np.ndarray,
) -> np.ndarray:
    """Turn the raw model output into a (HORIZON, n_targets) PHYSICAL array.

    ``y_model`` : model output, shape (HORIZON, n_targets) (already squeezed).
    ``X_input`` : the (1, LOOKBACK, n_model_features) tensor fed to the model,
                  needed only when OUTPUT_IS_RESIDUAL is True (to recover the
                  scaled last observation per target).

    If OUTPUT_IS_RESIDUAL: the model predicted a delta in SCALED space relative
    to the last observed (scaled) target value, so we add that back BEFORE
    inverse-transforming. Otherwise the model output is the scaled absolute
    forecast and we inverse-transform directly.
    """
    if config.OUTPUT_IS_RESIDUAL:
        # Index of each target inside the model's input channels.
        model_features = list(config.FEATURES)
        if config.USE_TIME_FEATURES:
            model_features = model_features + ["hour_sin", "hour_cos"]
        target_idx = [model_features.index(t) for t in config.TARGETS]
        last_scaled = X_input[0, -1, target_idx]          # (n_targets,)
        y_scaled = y_model + last_scaled[None, :]         # broadcast over horizon
    else:
        y_scaled = y_model

    return _inverse_targets(scaler, y_scaled)
