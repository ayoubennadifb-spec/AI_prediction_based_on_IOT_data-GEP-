"""Deterministic solar-geometry features for Benguerir -- no external data.

Sun elevation and theoretical clear-sky irradiance are exact functions of
(latitude, longitude, time). Unlike ERA5 reanalysis (which degraded July),
these carry ZERO measurement/model error; in Benguerir's mostly cloudless
summer, clear-sky irradiance is close to the real solar load -- exactly the
driver the indoor-only model was missing at long horizons.

Formulas: standard solar-position approximations (declination, equation of
time, hour angle) + the Haurwitz clear-sky model. Accuracy is well within
what a learned feature needs.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

LATITUDE = 32.236       # Benguerir / GSBP
LONGITUDE = -7.954

SOLAR_FEATURES = ["sun_elev", "csky_ghi"]


def sun_features(index: pd.DatetimeIndex) -> pd.DataFrame:
    """sin(solar elevation) and Haurwitz clear-sky GHI (W/m2) for each
    timestamp of a tz-aware UTC index."""
    t = index.tz_convert("UTC")
    n = t.dayofyear.to_numpy()                      # day of year
    frac_hour = (t.hour + t.minute / 60.0).to_numpy()

    # solar declination (degrees -> radians)
    decl = np.deg2rad(23.45 * np.sin(2 * np.pi * (284 + n) / 365.0))

    # equation of time (minutes)
    b = 2 * np.pi * (n - 81) / 364.0
    eot = 9.87 * np.sin(2 * b) - 7.53 * np.cos(b) - 1.5 * np.sin(b)

    # local solar time and hour angle
    solar_time = frac_hour + LONGITUDE / 15.0 + eot / 60.0
    hour_angle = np.deg2rad(15.0 * (solar_time - 12.0))

    lat = np.deg2rad(LATITUDE)
    sin_elev = (
        np.sin(lat) * np.sin(decl)
        + np.cos(lat) * np.cos(decl) * np.cos(hour_angle)
    )

    # Haurwitz clear-sky global horizontal irradiance
    cos_z = np.clip(sin_elev, 0.0, 1.0)             # cos(zenith) = sin(elev)
    with np.errstate(divide="ignore", invalid="ignore"):
        ghi = 1098.0 * cos_z * np.exp(-0.059 / np.where(cos_z > 0, cos_z, np.nan))
    ghi = np.nan_to_num(ghi, nan=0.0)

    return pd.DataFrame(
        {"sun_elev": sin_elev.astype(np.float32),
         "csky_ghi": ghi.astype(np.float32)},
        index=index,
    )


def merge_solar(dataset: pd.DataFrame) -> pd.DataFrame:
    """Join the two deterministic solar channels onto the dataset."""
    return dataset.join(sun_features(dataset.index))
