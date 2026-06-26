"""Per-horizon evaluation in physical units (G2 / G3).

Replaces Afaf's n=1 'test' (one window, one day) with metrics computed over
MANY rolling-origin windows, reported per lead time and per channel, plus a
skill score against persistence:

    skill = 1 - MAE_model / MAE_persistence      (>0 means better than naive)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config


def evaluate(
    y_true: np.ndarray,          # (n, horizon, n_targets), physical units
    y_pred: np.ndarray,          # same shape; may contain NaN windows
    channels: list[str] = None,
    horizons: list[int] = None,
    model_name: str = "model",
) -> pd.DataFrame:
    """Per-(horizon, channel) MAE / RMSE / R2 across windows."""
    channels = channels or config.TARGETS
    horizons = horizons or config.EVAL_HORIZONS
    rows = []
    for h in horizons:
        k = h - 1                                   # lead h minutes -> index h-1
        for j, ch in enumerate(channels):
            t = y_true[:, k, j].astype(np.float64)
            p = y_pred[:, k, j].astype(np.float64)
            ok = ~np.isnan(p) & ~np.isnan(t)
            n = int(ok.sum())
            if n == 0:
                rows.append((model_name, ch, h, n, *([np.nan] * 3)))
                continue
            err = p[ok] - t[ok]
            mae = float(np.mean(np.abs(err)))
            rmse = float(np.sqrt(np.mean(err**2)))
            denom = float(np.sum((t[ok] - t[ok].mean()) ** 2))
            r2 = float(1.0 - np.sum(err**2) / denom) if denom > 0 else np.nan
            rows.append((model_name, ch, h, n, mae, rmse, r2))
    return pd.DataFrame(
        rows, columns=["model", "channel", "horizon_min", "n", "MAE", "RMSE", "R2"]
    )


def add_skill(metrics: pd.DataFrame, reference: str = "persistence") -> pd.DataFrame:
    """Append a `skill_vs_<reference>` column: 1 - MAE/MAE_ref per (channel, horizon)."""
    ref = (
        metrics[metrics["model"] == reference]
        .set_index(["channel", "horizon_min"])["MAE"]
        .rename("ref_mae")
    )
    out = metrics.join(ref, on=["channel", "horizon_min"])
    out[f"skill_vs_{reference}"] = 1.0 - out["MAE"] / out["ref_mae"]
    return out.drop(columns="ref_mae")


def summarize(metrics: pd.DataFrame, float_fmt: str = "{:.3f}") -> str:
    """ASCII table for reports (Windows console safe)."""
    df = metrics.copy()
    for c in ("MAE", "RMSE", "R2"):
        df[c] = df[c].map(lambda v: float_fmt.format(v) if pd.notna(v) else "-")
    skill_cols = [c for c in df.columns if c.startswith("skill_vs_")]
    for c in skill_cols:
        df[c] = df[c].map(lambda v: f"{v:+.1%}" if pd.notna(v) else "-")
    return df.to_string(index=False)
