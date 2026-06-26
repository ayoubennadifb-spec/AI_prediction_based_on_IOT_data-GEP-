"""Window indexing and leakage-safe chronological splits.

A *window* is (input span = LOOKBACK minutes, target span = HORIZON minutes),
both fully inside one contiguous segment -- by construction a window can never
span a data gap (fixes Afaf's windows built across interpolated 57 h holes).

Split rule (A2): chronological per regime, assigned by the window's FULL span
[start, end_of_target]. A window straddling a split boundary belongs to no
split (the purge) -- so train/val/test share zero timestamps.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config


# ---------------------------------------------------------------------------
# Window index
# ---------------------------------------------------------------------------

def window_index(
    data: pd.DataFrame,
    lookback: int = config.LOOKBACK,
    horizon: int = config.HORIZON,
    stride: int = 1,
) -> pd.DataFrame:
    """Enumerate every valid window. Returns a DataFrame with one row per
    window: segment_id, regime, row position (within data) of the input start,
    and the timestamps of input start / forecast origin / target end."""
    rows = []
    total = lookback + horizon
    # positions of each segment's rows inside the *global* frame
    pos = pd.Series(np.arange(len(data)), index=data.index)
    for sid, seg in data.groupby("segment_id", sort=True):
        n = len(seg)
        if n < total:
            continue
        starts = np.arange(0, n - total + 1, stride)
        seg_pos0 = int(pos.loc[seg.index[0]])
        for s in starts:
            rows.append(
                (
                    sid,
                    seg["regime"].iloc[0],
                    seg_pos0 + s,                       # global row position
                    seg.index[s],                       # input start time
                    seg.index[s + lookback - 1],        # forecast origin (t0)
                    seg.index[s + total - 1],           # last target time
                )
            )
    idx = pd.DataFrame(
        rows,
        columns=["segment_id", "regime", "pos", "t_in_start", "t_origin", "t_end"],
    )
    return idx


# ---------------------------------------------------------------------------
# Boundary-purged chronological split (A2)
# ---------------------------------------------------------------------------

def chronological_split(
    index: pd.DataFrame,
    fractions: tuple[float, float, float] = config.SPLIT_FRACTIONS,
) -> pd.DataFrame:
    """Assign each window to train/val/test per regime, purging straddlers.

    Cut times are quantiles of forecast-origin times within the regime.
    A window is in a split only if its FULL span lies inside that split's
    time range; windows crossing a cut are dropped (split = NaN -> 'purged').
    """
    f_train, f_val, f_test = fractions
    assert abs(f_train + f_val + f_test - 1.0) < 1e-9

    index = index.copy()
    index["split"] = "purged"
    for regime, grp in index.groupby("regime"):
        cut1 = grp["t_origin"].quantile(f_train)
        cut2 = grp["t_origin"].quantile(f_train + f_val)
        in_train = grp["t_end"] < cut1
        in_val = (grp["t_in_start"] >= cut1) & (grp["t_end"] < cut2)
        in_test = grp["t_in_start"] >= cut2
        index.loc[grp.index[in_train], "split"] = "train"
        index.loc[grp.index[in_val], "split"] = "val"
        index.loc[grp.index[in_test], "split"] = "test"
    return index


# ---------------------------------------------------------------------------
# Array construction
# ---------------------------------------------------------------------------

def build_arrays(
    data: pd.DataFrame,
    index: pd.DataFrame,
    features: list[str] = None,
    targets: list[str] = None,
    lookback: int = config.LOOKBACK,
    horizon: int = config.HORIZON,
) -> tuple[np.ndarray, np.ndarray]:
    """Materialise (X, Y) for the windows in ``index``.

    X: (n_windows, lookback, n_features)
    Y: (n_windows, horizon, n_targets)
    Values are raw physical units; scaling is the caller's job (train-only).
    """
    features = features or config.FEATURES
    targets = targets or config.TARGETS
    fmat = data[features].to_numpy(dtype=np.float32)
    tmat = data[targets].to_numpy(dtype=np.float32)
    n = len(index)
    X = np.empty((n, lookback, len(features)), dtype=np.float32)
    Y = np.empty((n, horizon, len(targets)), dtype=np.float32)
    for i, p in enumerate(index["pos"].to_numpy()):
        X[i] = fmat[p : p + lookback]
        Y[i] = tmat[p + lookback : p + lookback + horizon]
    return X, Y
