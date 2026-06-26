"""Data loading, quality filtering and gap-aware segmentation.

Pipeline (replaces Afaf's `resample('1min').mean().interpolate('linear')`,
which drew a straight line through a 57.6 h hole and 252 other gaps):

    load_raw_sources -> merge_dedup -> to_minute_grid -> apply_quality_filters
        -> segment_and_interpolate -> per-segment, NaN-free 1-min frames

Guarantees on the output of ``load_dataset()``:
  * tz-aware UTC DatetimeIndex on an exact 1-minute grid
  * no NaN in any FEATURE column
  * within a segment, consecutive rows are exactly 1 minute apart
  * no value was interpolated across a hole longer than GAP_MAX_MINUTES
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from . import config


# ---------------------------------------------------------------------------
# Loading & merging (A6)
# ---------------------------------------------------------------------------

def _read_one(path: Path) -> pd.DataFrame:
    """Read either a plain CSV or an InfluxDB annotated CSV (#group/#datatype
    comment rows, leading unnamed column, extra host/topic columns)."""
    df = pd.read_csv(path, comment="#")
    df = df.loc[:, ~df.columns.str.startswith("Unnamed")]
    df = df.drop(columns=[c for c in ("host", "topic", "motion") if c in df.columns])
    df["time"] = pd.to_datetime(df["time"], errors="coerce", utc=True)
    for col in df.columns:
        if col not in ("time", "sensor"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["time"]).sort_values("time")
    df["source_file"] = path.name
    return df


def load_raw_sources(paths=None) -> pd.DataFrame:
    """Load every source file and concatenate (raw, irregular timestamps)."""
    paths = paths or config.SOURCE_FILES
    frames = [_read_one(Path(p)) for p in paths]
    return pd.concat(frames, ignore_index=True)


def merge_dedup(raw: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Sort by time and drop duplicate timestamps (keep first occurrence,
    in SOURCE_FILES order). Returns (merged, per-file contribution report)."""
    raw = raw.sort_values(["time"], kind="stable").reset_index(drop=True)
    before = raw.groupby("source_file").size().rename("rows_loaded")
    merged = raw.drop_duplicates(subset="time", keep="first")
    after = merged.groupby("source_file").size().rename("rows_kept_unique_time")
    report = pd.concat([before, after], axis=1).fillna(0).astype(int)
    report["rows_dropped_as_duplicates"] = (
        report["rows_loaded"] - report["rows_kept_unique_time"]
    )
    return merged.reset_index(drop=True), report


# ---------------------------------------------------------------------------
# 1-minute grid
# ---------------------------------------------------------------------------

def to_minute_grid(merged: pd.DataFrame) -> pd.DataFrame:
    """Resample to an exact 1-min grid (mean within each minute). Minutes with
    no data at all become NaN rows -- those encode the gaps."""
    numeric = config.FEATURES + [
        c for c in config.QA_ONLY_COLUMNS if c in merged.columns
    ]
    g = (
        merged.set_index("time")[numeric]
        .resample(f"{config.FREQ_MINUTES}min")
        .mean()
    )
    return g


# ---------------------------------------------------------------------------
# Quality filters (A5)
# ---------------------------------------------------------------------------

@dataclass
class QualityReport:
    range_violations: dict = field(default_factory=dict)
    flatline_minutes: int = 0
    flatline_runs: int = 0


def apply_quality_filters(grid: pd.DataFrame) -> tuple[pd.DataFrame, QualityReport]:
    """Null out physically impossible values and frozen-sensor flatlines.
    Runs BEFORE interpolation so artifacts cannot be smeared into neighbours."""
    grid = grid.copy()
    rep = QualityReport()

    for col, (lo, hi) in config.PHYSICAL_RANGES.items():
        if col in grid.columns:
            bad = (grid[col] < lo) | (grid[col] > hi)
            rep.range_violations[col] = int(bad.sum())
            grid.loc[bad, col] = np.nan

    # Flatline: temperature AND humidity both exactly constant for >= N min.
    # (Joint condition -- temperature alone can legitimately sit on one
    # quantized value for a while at night.)
    t, h = grid["temperature"], grid["humidity"]
    both_present = t.notna() & h.notna()
    changed = (t.ne(t.shift()) | h.ne(h.shift())) | ~both_present
    run_id = changed.cumsum()
    run_len = run_id.groupby(run_id).transform("size")
    frozen = both_present & (run_len >= config.FLATLINE_MINUTES)
    rep.flatline_minutes = int(frozen.sum())
    rep.flatline_runs = int(run_id[frozen].nunique())
    grid.loc[frozen, config.FEATURES] = np.nan

    return grid, rep


# ---------------------------------------------------------------------------
# Gap-aware segmentation (A1)
# ---------------------------------------------------------------------------

def segment_and_interpolate(grid: pd.DataFrame) -> pd.DataFrame:
    """Split on holes > GAP_MAX_MINUTES; time-interpolate holes <= that,
    strictly within segments. Output rows all carry a ``segment_id`` and a
    ``regime`` column; every FEATURE value is non-NaN."""
    missing = grid[config.FEATURES].isna().any(axis=1)

    # Runs of consecutive missing minutes.
    run_id = (missing.ne(missing.shift())).cumsum()
    run_len = missing.groupby(run_id).transform("size")
    long_hole = missing & (run_len > config.GAP_MAX_MINUTES)

    # Segment id increments after every long hole; long-hole rows are dropped.
    seg_id = long_hole.ne(long_hole.shift()).cumsum()  # alternates hole/data blocks
    keep = ~long_hole
    df = grid[keep].copy()
    df["segment_id"] = seg_id[keep]

    # Interpolate the remaining short holes within each segment (time-based,
    # interior only -- edges of a segment cannot be anchored on both sides).
    out = []
    for sid, seg in df.groupby("segment_id", sort=True):
        seg = seg.copy()
        seg[config.FEATURES] = seg[config.FEATURES].interpolate(
            method="time", limit=config.GAP_MAX_MINUTES, limit_area="inside"
        )
        # Trim un-fillable NaN rows at segment edges.
        valid = seg[config.FEATURES].notna().all(axis=1)
        if valid.any():
            seg = seg.loc[valid.idxmax(): valid[::-1].idxmax()]
        else:
            continue
        if len(seg) >= config.MIN_SEGMENT_MINUTES:
            out.append(seg)

    if not out:
        raise RuntimeError("No usable segments produced -- check inputs.")
    result = pd.concat(out)

    # Re-number segments 0..n-1 and tag the seasonal regime.
    result["segment_id"] = (
        result["segment_id"].ne(result["segment_id"].shift()).cumsum() - 1
    )
    boundary = pd.Timestamp(config.REGIME_BOUNDARY, tz="UTC")
    result["regime"] = np.where(result.index < boundary, "july", "october")

    # -- hard guarantees ----------------------------------------------------
    assert not result[config.FEATURES].isna().any().any(), "NaN survived pipeline"
    deltas = result.groupby("segment_id").apply(
        lambda s: s.index.to_series().diff().dropna().dt.total_seconds().max(),
        include_groups=False,
    )
    assert (deltas <= 60.0).all(), "non-contiguous rows inside a segment"
    return result


# ---------------------------------------------------------------------------
# One-call entry point
# ---------------------------------------------------------------------------

def load_dataset(paths=None, verbose: bool = False):
    """Full pipeline. Returns (data, info) where ``data`` is the segmented
    1-min DataFrame and ``info`` is a dict of QA artifacts."""
    raw = load_raw_sources(paths)
    merged, file_report = merge_dedup(raw)
    grid = to_minute_grid(merged)
    filtered, quality_report = apply_quality_filters(grid)
    data = segment_and_interpolate(filtered)

    seg_stats = (
        data.groupby("segment_id")
        .agg(
            start=("regime", lambda s: s.index.min()),
            end=("regime", lambda s: s.index.max()),
            minutes=("regime", "size"),
            regime=("regime", "first"),
        )
        .sort_values("start")
    )
    info = {
        "file_report": file_report,
        "quality_report": quality_report,
        "segments": seg_stats,
        "raw_rows": len(raw),
        "merged_rows": len(merged),
        "grid_minutes": len(grid),
        "kept_minutes": len(data),
    }
    if verbose:
        print(file_report)
        print(seg_stats)
    return data, info
