"""Predictive thermal comfort (H1 + H3): PMV/PPD computed on FORECAST
trajectories, not just current readings (Afaf's PMV stage was reactive --
it defeated the 'predictive comfort' goal -- and crashed on undefined vars).

Assumptions (H3) -- explicit, seasonal, and documented instead of silently
hardcoded:
    air velocity vr = 0.1 m/s        (still indoor air; not measured)
    metabolic rate  = 1.2 met        (light sedentary activity; not measured)
    clothing clo    = 0.5 (Jun-Sep) / 0.7 (Oct-May)  (summer / mid-season)
    mean radiant temperature = air temperature        (no globe thermometer;
        underestimates radiant load on sun-exposed facades -- documented bias)

ISO 7730 applicability: tdb in [10, 30] degC, |PMV| <= 2. July indoor peaks
at 33.8 degC, outside the standard's envelope. We compute with limits OFF so
the dashboard stays continuous, but every row carries an ``iso_valid`` flag
and reports state the out-of-applicability fraction (H5).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

VR_MS = 0.1
MET = 1.2
CLO_SUMMER, CLO_MIDSEASON = 0.5, 0.7
SUMMER_MONTHS = (6, 7, 8, 9)

ISO_TDB_RANGE = (10.0, 30.0)
ISO_PMV_RANGE = (-2.0, 2.0)

# 7-point thermal sensation scale, for dashboard classification
_CLASSES = [
    (-np.inf, -2.5, "cold"), (-2.5, -1.5, "cool"), (-1.5, -0.5, "slightly cool"),
    (-0.5, 0.5, "neutral"), (0.5, 1.5, "slightly warm"), (1.5, 2.5, "warm"),
    (2.5, np.inf, "hot"),
]


def clo_for(ts: pd.Timestamp) -> float:
    return CLO_SUMMER if ts.month in SUMMER_MONTHS else CLO_MIDSEASON


def pmv_ppd_frame(temp: np.ndarray, rh: np.ndarray,
                  when: pd.DatetimeIndex) -> pd.DataFrame:
    """Vectorized PMV/PPD for a (temperature, humidity) trajectory.

    Returns a DataFrame indexed by ``when`` with columns:
    pmv, ppd, comfort_class, iso_valid.
    """
    from pythermalcomfort.models import pmv_ppd_iso

    temp = np.asarray(temp, dtype=float)
    rh = np.clip(np.asarray(rh, dtype=float), 0.0, 100.0)
    clo = np.array([clo_for(t) for t in when])

    res = pmv_ppd_iso(
        tdb=temp, tr=temp, vr=VR_MS, rh=rh, met=MET, clo=clo,
        limit_inputs=False,          # keep continuity; validity flagged below
    )
    pmv = np.asarray(res.pmv, dtype=float)
    ppd = np.asarray(res.ppd, dtype=float)

    iso_valid = (
        (temp >= ISO_TDB_RANGE[0]) & (temp <= ISO_TDB_RANGE[1])
        & (pmv >= ISO_PMV_RANGE[0]) & (pmv <= ISO_PMV_RANGE[1])
    )
    labels = np.empty(len(pmv), dtype=object)
    for lo, hi, name in _CLASSES:
        labels[(pmv > lo) & (pmv <= hi)] = name

    return pd.DataFrame(
        {"pmv": pmv, "ppd": ppd, "comfort_class": labels, "iso_valid": iso_valid},
        index=when,
    )


def comfort_class(pmv: np.ndarray) -> np.ndarray:
    """Vectorized 7-class label for an array of PMV values."""
    pmv = np.asarray(pmv, dtype=float)
    labels = np.empty(pmv.shape, dtype=object)
    for lo, hi, name in _CLASSES:
        labels[(pmv > lo) & (pmv <= hi)] = name
    return labels
