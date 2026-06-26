"""Real-time serving path (F1-F6) -- the corrected version of Afaf's
`Real time (4h).ipynb`, whose train/serve mismatch caused the 3.42 degC
live MAE (LOOKBACK=60 vs trained 480; 240x recursive rollout).

Design rules enforced here:
  F1  serving lookback == training lookback (imported from config; the
      ScalerBundle refuses to load under a mismatched contract)
  F2  ONE forward pass emits the whole horizon -- no recursive rollout
  F3  identical preprocessing: same scaler bundle, same feature order,
      same gap rules as training (this module reuses the training code)
  F4  staleness/gap guard: no forecast from stale or hole-ridden input
  F6  tz-aware UTC timestamps end to end

The core is ``forecast_from_frame``: a PURE function from a recent-history
DataFrame to a forecast DataFrame. The InfluxDB layer is a thin wrapper
around it, so the exact serving path can be replayed offline on historical
data (G5) -- which is how we prove online == offline.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import config, features
from .scaling import ScalerBundle


class ServingDataError(RuntimeError):
    """Input data unfit for forecasting (stale / gappy / short). The caller
    should skip this cycle and alert -- NOT forecast on bad input."""


@dataclass
class ForecastResult:
    origin: pd.Timestamp                 # forecast origin t0 (last observed minute)
    frame: pd.DataFrame                  # index: t0+1min .. t0+HORIZON, cols: TARGETS


# ---------------------------------------------------------------------------
# Input validation (F4)
# ---------------------------------------------------------------------------

def prepare_input_window(
    recent: pd.DataFrame,
    now: pd.Timestamp | None = None,
    max_staleness_min: int = 5,
) -> pd.DataFrame:
    """Validate + regularize the last LOOKBACK minutes of sensor history.

    ``recent``: raw sensor rows (any sampling), tz-aware index or 'time'
    column, containing at least config.FEATURES columns.
    Returns an exactly-LOOKBACK-row, 1-min, NaN-free frame or raises
    ServingDataError with the reason.
    """
    df = recent.copy()
    if "time" in df.columns:
        df = df.set_index("time")
    if df.index.tz is None:
        raise ServingDataError("timestamps must be tz-aware UTC (F6)")
    df = df.sort_index()

    missing_cols = [c for c in config.FEATURES if c not in df.columns]
    if missing_cols:
        raise ServingDataError(f"missing feature columns: {missing_cols}")

    # staleness: the freshest reading must be recent
    now = now or pd.Timestamp.now(tz="UTC")
    age_min = (now - df.index.max()).total_seconds() / 60.0
    if age_min > max_staleness_min:
        raise ServingDataError(
            f"data is stale: last reading {age_min:.1f} min old"
            f" (max {max_staleness_min})"
        )

    # 1-min grid over the lookback window ending at the last full minute
    grid = df[config.FEATURES].resample("1min").mean()
    grid = grid.iloc[-config.LOOKBACK :]
    if len(grid) < config.LOOKBACK:
        raise ServingDataError(
            f"only {len(grid)} minutes of history; need {config.LOOKBACK}"
        )

    # same quality filters as training (A5): impossible values become holes,
    # a frozen sensor (temp+hum exactly constant for >= FLATLINE_MINUTES)
    # blocks the forecast instead of feeding the model a flat line.
    for col, (lo, hi) in config.PHYSICAL_RANGES.items():
        if col in grid.columns:
            grid.loc[(grid[col] < lo) | (grid[col] > hi), col] = np.nan
    t, h = grid["temperature"], grid["humidity"]
    changed = t.ne(t.shift()) | h.ne(h.shift())
    run_len = (~changed).groupby(changed.cumsum()).transform("size")
    if bool((run_len >= config.FLATLINE_MINUTES).any()):
        raise ServingDataError(
            f"sensor appears frozen (constant temp+humidity"
            f" >= {config.FLATLINE_MINUTES} min)"
        )

    # same gap rule as training: interpolate holes <= GAP_MAX_MINUTES only
    missing = grid.isna().any(axis=1)
    if missing.any():
        run_id = missing.ne(missing.shift()).cumsum()
        run_len = missing.groupby(run_id).transform("size")
        if bool((missing & (run_len > config.GAP_MAX_MINUTES)).any()):
            raise ServingDataError(
                f"hole > {config.GAP_MAX_MINUTES} min inside the lookback window"
            )
        grid = grid.interpolate(method="time", limit=config.GAP_MAX_MINUTES,
                                limit_area="inside")
    if grid.isna().any().any():
        raise ServingDataError("unfillable NaN at window edge")
    return grid


# ---------------------------------------------------------------------------
# Forecast (F1 + F2 + F3)
# ---------------------------------------------------------------------------

def forecast_from_frame(
    recent: pd.DataFrame,
    model,
    bundle: ScalerBundle,
    now: pd.Timestamp | None = None,
) -> ForecastResult:
    """Recent sensor history -> HORIZON-minute forecast, one forward pass."""
    grid = prepare_input_window(recent, now=now)

    # identical feature assembly as training (F3)
    grid = features.add_time_features(grid)
    scaled = bundle.transform_frame(grid)
    X = scaled[features.MODEL_FEATURES].to_numpy(dtype=np.float32)[None, ...]

    # model input-shape contract check (F1): fail loud, never adapt silently
    expected = (config.LOOKBACK, len(features.MODEL_FEATURES))
    if tuple(model.input_shape[1:]) != expected:
        raise ServingDataError(
            f"model expects input {model.input_shape[1:]}, contract is {expected}"
        )

    delta = model.predict(X, verbose=0)                      # (1, H, n_targets)
    last_scaled = X[0, -1, features.TARGET_IDX][None, :]
    y_phys = features.reconstruct_physical(delta, last_scaled, bundle)[0]

    origin = grid.index[-1]
    future_index = pd.date_range(
        origin + pd.Timedelta(minutes=1), periods=config.HORIZON, freq="1min",
        tz="UTC", name="time",
    )
    frame = pd.DataFrame(y_phys, index=future_index, columns=config.TARGETS)
    return ForecastResult(origin=origin, frame=frame)


# ---------------------------------------------------------------------------
# InfluxDB wrapper (thin; everything testable lives above)
# ---------------------------------------------------------------------------

def fetch_recent_influx(client, bucket: str, measurement: str,
                        sensor: str = "sensor_1") -> pd.DataFrame:
    """Pull the last LOOKBACK+10 minutes of raw points. NOTE: no
    fill(usePrevious) -- gaps must stay visible so the guard can see them."""
    lookback = config.LOOKBACK + 10
    flux = f'''
    from(bucket: "{bucket}")
      |> range(start: -{lookback}m)
      |> filter(fn: (r) => r._measurement == "{measurement}")
      |> filter(fn: (r) => r["sensor"] == "{sensor}")
      |> filter(fn: (r) => contains(value: r._field,
                 set: {list(config.FEATURES)!r}))
      |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
    '''
    tables = client.query_api().query_data_frame(flux)
    df = pd.concat(tables) if isinstance(tables, list) else tables
    df = df.rename(columns={"_time": "time"})[["time"] + config.FEATURES]
    df["time"] = pd.to_datetime(df["time"], utc=True)
    return df


def write_forecast_influx(client, bucket: str, org: str,
                          result: ForecastResult, model_tag: str) -> int:
    """Write the forecast trajectory back to InfluxDB (tz-aware, F6)."""
    from influxdb_client import Point, WritePrecision
    from influxdb_client.client.write_api import SYNCHRONOUS

    write_api = client.write_api(write_options=SYNCHRONOUS)
    points = []
    for ts, row in result.frame.iterrows():
        p = (
            Point("climate_forecast")
            .tag("model", model_tag)
            .tag("origin", result.origin.isoformat())
            .time(ts.to_pydatetime(), WritePrecision.NS)
        )
        for ch in config.TARGETS:
            p = p.field(ch, float(row[ch]))
        points.append(p)
    write_api.write(bucket=bucket, org=org, record=points)
    return len(points)
