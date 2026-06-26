"""Shared configuration for the GEP indoor-climate forecasting pipeline.

This module is the SINGLE SOURCE OF TRUTH for the window contract
(lookback/horizon) and feature definitions. Both training and serving
must import from here -- never redefine these constants locally.
(Afaf's pipeline trained with window=480 but served with LOOKBACK=60,
which was the root cause of the offline/online accuracy collapse.)
"""
from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
# Root of the fixed dataset (previous student's PFE export). Data is frozen:
# these four CSVs are the only data sources for this project.
DATA_DIR = Path(
    r"C:\Users\ayoub\Emines\S6\Internship_GEP"
    r"\Stage Pfe GEP-20260607T171937Z-3-001-full\Stage Pfe GEP\Dataset\csv"
)

SOURCE_FILES = [
    DATA_DIR / "Data_30j.csv",                          # Jul 02 - Aug 11 (gappy)
    DATA_DIR / "Data_30j_influxdbcsv.csv",              # duplicate of the above (deduped at load)
    DATA_DIR / "influxdata_2025-08-18T09_50_52Z.csv",   # Jul 22-23, fills part of a July gap
    DATA_DIR / "influxdata_2025-10-14T11_24_50Z.csv",   # Sep 16 - Oct 14 (clean block)
]

# Where pipeline artifacts (reports, scalers, metrics) are written.
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "outputs"

# ---------------------------------------------------------------------------
# Window contract (C1)  --  shared by training AND serving
# ---------------------------------------------------------------------------
FREQ_MINUTES = 1          # base sampling grid

LOOKBACK = 240            # input length, minutes (4 h). Afaf used 480 (8 h); temp
                          # autocorrelation saturates well before that, and a
                          # shorter window doubles the usable training windows
                          # in the gap-riddled July data.
HORIZON = 240             # forecast length, minutes (4 h) -- product requirement.

# Lead times (minutes) at which metrics are reported (G3).
EVAL_HORIZONS = [15, 30, 60, 120, 240]

# ---------------------------------------------------------------------------
# Features / targets
# ---------------------------------------------------------------------------
# Channels with verified predictive signal. lux/sound/motion are deliberately
# excluded (no lagged signal / inconsistent ADC scaling / degenerate).
FEATURES = ["temperature", "humidity", "co2"]
TARGETS = ["temperature", "humidity"]

# Extra columns kept by the loader for data-quality reporting only.
QA_ONLY_COLUMNS = ["lux", "sound"]

# ---------------------------------------------------------------------------
# Data-quality rules (A1 / A5)
# ---------------------------------------------------------------------------
GAP_MAX_MINUTES = 5       # a hole longer than this starts a new segment;
                          # holes <= this are time-interpolated within a segment.

# Physically impossible readings are nulled (sensor glitches). Bounds are
# deliberately loose: the MQ-135 CO2 sensor is uncalibrated, so we only
# reject hard-impossible values, not implausible ones.
PHYSICAL_RANGES = {
    "temperature": (-10.0, 60.0),   # deg C, indoor Benguerir
    "humidity": (0.0, 100.0),       # % RH
    "co2": (0.0, 10000.0),          # ppm (uncalibrated sensor, loose bounds)
}

# A run where temperature AND humidity are both EXACTLY constant for at least
# this long is treated as a frozen sensor / forward-fill artifact -> missing.
FLATLINE_MINUTES = 60

# A segment shorter than LOOKBACK + HORIZON cannot yield a single window.
MIN_SEGMENT_MINUTES = LOOKBACK + HORIZON

# ---------------------------------------------------------------------------
# Regimes (A4): July-August vs September-October are different seasonal
# regimes (ventilation/co2 distribution shift). They are kept separate for
# splitting/scaling decisions and for the cross-season test (G4).
# ---------------------------------------------------------------------------
REGIME_BOUNDARY = "2025-09-01"      # < boundary -> "july", >= -> "october"

# ---------------------------------------------------------------------------
# Splits (A2)
# ---------------------------------------------------------------------------
SPLIT_FRACTIONS = (0.70, 0.15, 0.15)   # train / val / test, chronological per regime

# Evaluation stride (minutes) between rolling-origin starts in the backtest:
# matches the 10-min serving cadence.
EVAL_STRIDE = 10
