"""Derived input channels and model-ready array assembly (B2 / B3).

Adds deterministic time-of-day encodings (sin/cos of fractional hour) so the
model gets the diurnal phase for free instead of inferring it from one window
-- the baseline backtest showed seasonal structure matters at long horizons
(seasonal-naive beats persistence at +240 min in October).

Channel layout fed to the model:
    [temperature, humidity, co2]  -> scaled via ScalerBundle (train-only fit)
    [hour_sin, hour_cos]          -> already in [-1, 1], passed through raw
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config, windows as win_mod
from .scaling import ScalerBundle

TIME_FEATURES = ["hour_sin", "hour_cos"]
MODEL_FEATURES = config.FEATURES + TIME_FEATURES   # input channel order
TARGET_IDX = [MODEL_FEATURES.index(t) for t in config.TARGETS]


def add_time_features(data: pd.DataFrame) -> pd.DataFrame:
    """Append hour_sin / hour_cos columns derived from the (UTC) index."""
    out = data.copy()
    frac_hour = out.index.hour + out.index.minute / 60.0
    angle = 2.0 * np.pi * frac_hour / 24.0
    out["hour_sin"] = np.sin(angle).astype(np.float32)
    out["hour_cos"] = np.cos(angle).astype(np.float32)
    return out


def assemble_model_arrays(
    data: pd.DataFrame,
    index: pd.DataFrame,
    bundle: ScalerBundle,
    model_features: list[str] | None = None,
):
    """Build scaled model inputs and residual-over-persistence targets (C4).

    ``model_features`` defaults to MODEL_FEATURES; pass an extended list
    (e.g. with weather channels already joined onto ``data``) to train
    augmented variants. Targets must appear in the list.

    Returns a dict with:
        X            (n, LOOKBACK, n_model_features)  scaled inputs
        y_delta      (n, HORIZON, n_targets)  scaled residual targets
        last_scaled  (n, n_targets)           scaled last observation (t0)
        y_true       (n, HORIZON, n_targets)  PHYSICAL-unit ground truth

    Residual formulation: the model predicts the *change* from the last
    observed value, so persistence (delta == 0) is the built-in starting
    point and any learning is pure skill on top of it.
    """
    model_features = model_features or MODEL_FEATURES
    target_idx = [model_features.index(t) for t in config.TARGETS]

    data = add_time_features(data)

    # Physical-unit ground truth for evaluation.
    _, y_true = win_mod.build_arrays(
        data, index, features=config.FEATURES, targets=config.TARGETS
    )

    # Scaled physical channels + raw time channels.
    scaled = bundle.transform_frame(data)
    X, y_scaled = win_mod.build_arrays(
        scaled, index, features=model_features, targets=config.TARGETS
    )

    last_scaled = X[:, -1, target_idx]                 # value at forecast origin
    y_delta = y_scaled - last_scaled[:, None, :]

    return {
        "X": X,
        "y_delta": y_delta,
        "last_scaled": last_scaled,
        "y_true": y_true,
    }


def reconstruct_physical(
    delta_pred: np.ndarray,        # (n, HORIZON, n_targets) predicted residuals
    last_scaled: np.ndarray,       # (n, n_targets)
    bundle: ScalerBundle,
) -> np.ndarray:
    """Residuals -> scaled forecasts -> physical units (degC, %RH)."""
    pred_scaled = delta_pred + last_scaled[:, None, :]
    return bundle.inverse_transform_array(pred_scaled, config.TARGETS)
