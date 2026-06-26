"""Naive baselines (G1) -- the bar any model must beat.

With corr(temp(t), temp(t+60min)) ~ 0.98, persistence is already a strong
forecaster. Afaf's reported R2 = 0.751 was never compared against it; every
metric we report from now on is paired with these baselines.

Both baselines emit forecasts shaped (n_windows, horizon, n_targets) in
physical units, directly comparable to model output.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config

DAY_MINUTES = 1440


def persistence(
    data: pd.DataFrame,
    index: pd.DataFrame,
    targets: list[str] = None,
    horizon: int = config.HORIZON,
) -> np.ndarray:
    """y_hat(t0 + h) = y(t0): repeat the last observed value across the horizon."""
    targets = targets or config.TARGETS
    tmat = data[targets].to_numpy(dtype=np.float32)
    pos = index["pos"].to_numpy()
    last_obs = tmat[pos + config.LOOKBACK - 1]            # (n, n_targets)
    return np.repeat(last_obs[:, None, :], horizon, axis=1)


def seasonal_naive(
    data: pd.DataFrame,
    index: pd.DataFrame,
    targets: list[str] = None,
    horizon: int = config.HORIZON,
    period: int = DAY_MINUTES,
) -> np.ndarray:
    """y_hat(t0 + h) = y(t0 + h - 24h), within the same segment.

    Windows whose 24h-earlier values fall outside the segment get NaN
    (reported coverage tells how often the baseline applies)."""
    targets = targets or config.TARGETS
    tmat = data[targets].to_numpy(dtype=np.float32)
    seg_ids = data["segment_id"].to_numpy()
    n = len(index)
    out = np.full((n, horizon, len(targets)), np.nan, dtype=np.float32)
    for i, p in enumerate(index["pos"].to_numpy()):
        t_start = p + config.LOOKBACK          # first target row
        src_start = t_start - period
        if src_start < 0:
            continue
        # all source rows must exist and belong to the same segment
        if seg_ids[src_start] == seg_ids[t_start + horizon - 1] == seg_ids[t_start]:
            out[i] = tmat[src_start : src_start + horizon]
    return out
