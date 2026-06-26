"""InfluxDB Cloud I/O layer (Flux read + line-protocol write).

Read path : `read_window` pulls the last LOOKBACK_MIN minutes of the model's
            features for one zone, resampled to a clean 1-min grid, as an
            ordered pandas DataFrame indexed by tz-aware UTC time.
Write path: `write_forecast` writes a forecast DataFrame back to the zone's
            prediction measurement, one field per target, each point stamped at
            its FUTURE time.

IMPORTANT: the read deliberately does NOT use fill(usePrevious). Gaps must stay
visible (as NaN) so the staleness/coverage guard in inference_worker can refuse
to predict on hole-ridden or stale input.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List

import pandas as pd
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

import config

logger = logging.getLogger("influx_io")

# Single shared client for the whole process (cheap to keep open).
_client: InfluxDBClient | None = None


def get_client() -> InfluxDBClient:
    """Lazily create (and cache) the InfluxDB client from env-backed config."""
    global _client
    if _client is None:
        if not config.influx_settings_ok():
            raise RuntimeError(
                "Configuration InfluxDB incomplete : verifiez les variables "
                "d'environnement INFLUX_URL / INFLUX_ORG / INFLUX_TOKEN."
            )
        _client = InfluxDBClient(
            url=config.INFLUX_URL,
            token=config.INFLUX_TOKEN,
            org=config.INFLUX_ORG,
            timeout=30_000,
        )
    return _client


def close_client() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None


# ---------------------------------------------------------------------------
# READ
# ---------------------------------------------------------------------------
def _flux_field_filter(influx_fields: List[str]) -> str:
    """Build a Flux `contains(...)` set literal for the requested fields."""
    quoted = ", ".join(f'"{f}"' for f in influx_fields)
    return f"[{quoted}]"


def read_window(
    zone: str,
    features: List[str],
    lookback_min: int,
) -> pd.DataFrame:
    """Return the last ``lookback_min`` minutes of ``features`` for ``zone``.

    The frame is:
      * indexed by tz-aware UTC timestamps (name 'time'),
      * on a regular 1-min grid (aggregateWindow every 1m, mean),
      * column order == ``features`` (training order),
      * with REAL gaps left as NaN (no forward-fill).

    ``features`` are *training* names; they are translated to InfluxDB field
    names via config.FIELD_MAP for the query, then renamed back.
    """
    zinfo = config.ZONES[zone]
    bucket = zinfo["bucket"]
    measurement = zinfo["measurement"]

    # training name -> influx field name
    influx_fields = [config.FIELD_MAP.get(f, f) for f in features]
    # reverse lookup to rename query result columns back to training names
    influx_to_train = {config.FIELD_MAP.get(f, f): f for f in features}

    # Pull a little extra (+RESOLUTION margin) so the last aggregate window is full.
    range_min = lookback_min + config.RESOLUTION_MIN

    sensor_filter = ""
    if config.SENSOR_TAG_KEY and config.SENSOR_TAG_VALUE:
        sensor_filter = (
            f'  |> filter(fn: (r) => r["{config.SENSOR_TAG_KEY}"] '
            f'== "{config.SENSOR_TAG_VALUE}")\n'
        )

    flux = f'''
from(bucket: "{bucket}")
  |> range(start: -{range_min}m)
  |> filter(fn: (r) => r._measurement == "{measurement}")
{sensor_filter}  |> filter(fn: (r) => contains(value: r._field, set: {_flux_field_filter(influx_fields)}))
  |> aggregateWindow(every: {config.RESOLUTION_MIN}m, fn: mean, createEmpty: true)
  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
  |> sort(columns: ["_time"])
'''.strip()

    client = get_client()
    tables = client.query_api().query_data_frame(flux)
    df = pd.concat(tables, ignore_index=True) if isinstance(tables, list) else tables

    # Empty / missing-field handling: return an empty frame with the right columns
    # so the caller's guard reports "not enough points" rather than crashing.
    if df is None or len(df) == 0 or "_time" not in df.columns:
        return pd.DataFrame(columns=list(features)).rename_axis("time")

    df = df.rename(columns={"_time": "time", **influx_to_train})

    # Some requested fields may simply not exist in this zone (Zone-2 caveat).
    for f in features:
        if f not in df.columns:
            df[f] = pd.NA

    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df[["time"] + list(features)].set_index("time").sort_index()

    # Keep exactly the lookback tail on the 1-min grid, preserving feature order.
    df = df[list(features)].astype("float64")
    df = df.iloc[-lookback_min:]
    return df


# ---------------------------------------------------------------------------
# WRITE
# ---------------------------------------------------------------------------
def write_forecast(zone: str, forecast_df: pd.DataFrame) -> int:
    """Write a forecast trajectory back to InfluxDB.

    ``forecast_df`` index = tz-aware UTC future timestamps, columns = TARGETS in
    PHYSICAL units. Each target ``t`` is written as field ``t + "_pred"`` in the
    zone's prediction measurement (e.g. temperature_pred, humidite_pred).
    Returns the number of points written.
    """
    if forecast_df.empty:
        return 0

    zinfo = config.ZONES[zone]
    pred_measurement = zinfo["pred_measurement"]
    bucket = zinfo["bucket"]

    write_api = get_client().write_api(write_options=SYNCHRONOUS)
    now_iso = datetime.now(timezone.utc).isoformat()

    points = []
    for ts, row in forecast_df.iterrows():
        # tz-aware UTC enforced: convert any naive index to UTC defensively.
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        p = (
            Point(pred_measurement)
            .tag("zone", zone)
            .tag("forecast_run", now_iso)   # groups one horizon together
            .time(ts.to_pydatetime(), WritePrecision.NS)
        )
        for target in config.TARGETS:
            if target in row and pd.notna(row[target]):
                p = p.field(f"{target}_pred", float(row[target]))
        points.append(p)

    write_api.write(bucket=bucket, org=config.INFLUX_ORG, record=points)
    logger.info("Zone %s : %d points de prevision ecrits dans '%s'.",
                zone, len(points), pred_measurement)
    return len(points)
