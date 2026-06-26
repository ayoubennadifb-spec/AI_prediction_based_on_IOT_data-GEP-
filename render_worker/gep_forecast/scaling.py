"""Train-only, persisted scaler bundle (A3 / B5).

One bundle = per-channel scalers + the window contract + fit provenance,
saved as a single artifact. Serving loads the SAME bundle -- it can never
desync from training (Afaf persisted a bare scaler.pkl with no contract).

Scaler choice: MinMax for temperature/humidity (bounded, well-behaved),
StandardScaler for co2 (heavy-tailed, uncalibrated sensor).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.preprocessing import MinMaxScaler, StandardScaler

from . import config

_SCALER_FACTORY = {
    "temperature": MinMaxScaler,
    "humidity": MinMaxScaler,
    "co2": StandardScaler,
}


@dataclass
class ScalerBundle:
    features: list[str]
    lookback: int = config.LOOKBACK
    horizon: int = config.HORIZON
    scalers: dict = field(default_factory=dict)
    fit_meta: dict = field(default_factory=dict)

    # -- fitting ------------------------------------------------------------
    @classmethod
    def fit(cls, data: pd.DataFrame, train_mask: pd.Series, features=None,
            meta: dict | None = None) -> "ScalerBundle":
        """Fit per-channel scalers on TRAIN rows only.

        ``train_mask`` is a boolean Series aligned with ``data`` selecting the
        rows that belong to training windows (never val/test)."""
        features = features or config.FEATURES
        bundle = cls(features=list(features))
        train_rows = data.loc[train_mask, features]
        if train_rows.empty:
            raise ValueError("train_mask selects no rows")
        for col in features:
            scaler = _SCALER_FACTORY.get(col, MinMaxScaler)()
            scaler.fit(train_rows[[col]].to_numpy())
            bundle.scalers[col] = scaler
        bundle.fit_meta = {
            "n_train_rows": int(train_mask.sum()),
            "train_start": str(data.index[train_mask].min()),
            "train_end": str(data.index[train_mask].max()),
            **(meta or {}),
        }
        return bundle

    # -- transforms ---------------------------------------------------------
    def transform_frame(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        for col in self.features:
            out[col] = self.scalers[col].transform(df[[col]].to_numpy()).ravel()
        return out

    def transform_array(self, X: np.ndarray, channels: list[str]) -> np.ndarray:
        """Scale a (n, time, channels) array channel-by-channel."""
        out = X.copy()
        for j, col in enumerate(channels):
            s = self.scalers[col]
            flat = X[..., j].reshape(-1, 1)
            out[..., j] = s.transform(flat).reshape(X[..., j].shape)
        return out

    def inverse_transform_array(self, X: np.ndarray, channels: list[str]) -> np.ndarray:
        out = X.copy()
        for j, col in enumerate(channels):
            s = self.scalers[col]
            flat = X[..., j].reshape(-1, 1)
            out[..., j] = s.inverse_transform(flat).reshape(X[..., j].shape)
        return out

    # -- persistence ----------------------------------------------------------
    def save(self, path: Path | str) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, path)
        return path

    @staticmethod
    def load(path: Path | str) -> "ScalerBundle":
        bundle = joblib.load(path)
        # Contract check: a bundle from a different window contract is refused.
        if bundle.lookback != config.LOOKBACK or bundle.horizon != config.HORIZON:
            raise ValueError(
                f"Scaler bundle contract (lookback={bundle.lookback}, "
                f"horizon={bundle.horizon}) does not match config "
                f"({config.LOOKBACK}, {config.HORIZON}). Refusing to serve."
            )
        return bundle


def train_row_mask(data: pd.DataFrame, index: pd.DataFrame) -> pd.Series:
    """Boolean mask over ``data`` rows covered by TRAIN windows (input+target
    spans). Used so scalers see exactly the training data and nothing else."""
    mask = np.zeros(len(data), dtype=bool)
    total = config.LOOKBACK + config.HORIZON
    for p in index.loc[index["split"] == "train", "pos"].to_numpy():
        mask[p : p + total] = True
    return pd.Series(mask, index=data.index)
