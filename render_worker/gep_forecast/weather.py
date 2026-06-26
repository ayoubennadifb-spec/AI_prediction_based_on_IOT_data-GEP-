"""Outdoor weather covariates for Benguerir (Open-Meteo ERA5 archive).

Indoor temperature over a 4 h horizon is driven by outdoor conditions; the
measured correlations with the 4 h indoor-temperature RESIDUAL (the exact
quantity the model predicts) are substantial:

    solar:        +0.53 (july)  +0.93 (october)
    out_temp:     +0.38         +0.60
    out_humidity: -0.38         -0.62
    wind:         ~0  -> excluded

Data is cached in data/weather_benguerir.csv (hourly, UTC, fetched from
https://archive-api.open-meteo.com). ``merge_weather`` upsamples it to the
1-min grid by time interpolation and joins it onto the segmented dataset.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

WEATHER_FEATURES = ["out_temp", "solar", "out_humidity"]

_CSV = Path(__file__).resolve().parent.parent / "data" / "weather_benguerir.csv"


def load_weather(path: Path | str = _CSV) -> pd.DataFrame:
    """Cached hourly weather, tz-aware UTC index."""
    w = pd.read_csv(path, parse_dates=["time"]).set_index("time")
    if w.index.tz is None:
        w.index = w.index.tz_localize("UTC")
    return w[WEATHER_FEATURES]


def merge_weather(dataset: pd.DataFrame, path: Path | str = _CSV) -> pd.DataFrame:
    """Join 1-min interpolated weather onto the segmented sensor dataset.

    Hourly -> 1-min by time interpolation (weather signals are smooth at this
    scale). Raises if any dataset minute ends up without weather coverage."""
    w = load_weather(path)
    w1 = w.resample("1min").interpolate("time").reindex(dataset.index)
    if w1.isna().any().any():
        missing = int(w1.isna().any(axis=1).sum())
        raise ValueError(f"{missing} dataset minutes lack weather coverage")
    out = dataset.join(w1)
    return out
