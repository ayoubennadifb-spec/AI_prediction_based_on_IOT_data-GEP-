"""The PRODUCTION recipe, as one object.

``DeploymentRecipe.forecast(indoor_recent, outdoor_recent, now)`` runs the
exact pipeline that was evaluated offline:

    season switch (month) ->
      july-like  : mean( ens3 LSTM , grey-box physics corrector )
      sept.-oct. : ens3 ramped into the 8-channel weather LSTM
    -> skill-gated shrinkage (per season/channel/lead)
    -> conformal 80% intervals
    -> predictive PMV/PPD band

Inputs are plain DataFrames so the whole path is replayable offline on
historical data (script 17) -- the same guarantee style as serving.py.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from . import comfort, config, features, serving, solar, weather

OCTOBER_ARM_MONTHS = (9, 10)        # validated weather-arm months


@dataclass
class DeploymentForecast:
    origin: pd.Timestamp
    arm: str
    frame: pd.DataFrame      # index t0+1..t0+H; per target: value, lo, hi
    pmv: pd.DataFrame        # pmv, pmv_lo, pmv_hi, ppd, comfort_class, iso_valid


class DeploymentRecipe:
    def __init__(self, bundle_path: Path | str, models_dir: Path | str):
        from tensorflow.keras.models import load_model

        b = joblib.load(bundle_path)
        man = b["manifest"]
        if (man["lookback"], man["horizon"]) != (config.LOOKBACK, config.HORIZON):
            raise ValueError("bundle contract != config contract -- refusing")
        self.manifest = man
        self.b_in = b["scaler_indoor"]
        self.b_w = b["scaler_weather"]
        self.greybox = b["greybox"]
        self.shrinkage = b["shrinkage"]
        self.conformal = b["conformal"]
        self.t_scale = b["t_scale"]
        mdir = Path(models_dir)
        self.nets = [load_model(mdir / f) for f in man["model_files"][:-1]]
        self.net_w = load_model(mdir / man["model_files"][-1])
        h = np.arange(config.HORIZON, dtype=np.float32)
        self._ramp = (h / (config.HORIZON - 1))[None, :, None]
        self._wf = config.FEATURES + weather.WEATHER_FEATURES + features.TIME_FEATURES

    # ------------------------------------------------------------------
    @staticmethod
    def season_arm(when: pd.Timestamp) -> str:
        return "october" if when.month in OCTOBER_ARM_MONTHS else "july"

    def _greybox_delta(self, grid: pd.DataFrame, outdoor: pd.DataFrame,
                       origin: pd.Timestamp) -> np.ndarray:
        """Serve-side grey-box: physics features from the indoor window +
        outdoor sample at origin + deterministic future clear-sky integral."""
        t = grid["temperature"].to_numpy()
        out_now = outdoor.loc[:origin].iloc[-1]
        X_static = np.array([[
            t[-1] - t.mean(),
            t[-1] - t[-61],
            t[-1] - t[0],
            float(out_now["out_temp"]) - t[-1],
            float(out_now["solar"]),
        ]], dtype=np.float32)
        fut = pd.date_range(origin + pd.Timedelta(minutes=1),
                            periods=config.HORIZON, freq="1min", tz="UTC")
        csky = solar.sun_features(fut)["csky_ghi"].to_numpy()
        csum = np.cumsum(csky)
        hsteps = np.arange(1, config.HORIZON + 1)
        csky_int = (csum / hsteps)[None, :].astype(np.float32)
        return self.greybox.predict(X_static, csky_int)[0] * self.t_scale  # (H,)

    # ------------------------------------------------------------------
    def forecast(self, indoor_recent: pd.DataFrame, outdoor_recent: pd.DataFrame,
                 now: pd.Timestamp | None = None) -> DeploymentForecast:
        # 1) guarded indoor window (same rules as training/serving)
        grid = serving.prepare_input_window(indoor_recent, now=now)
        origin = grid.index[-1]
        arm = self.season_arm(origin)

        # 2) outdoor aligned to the indoor grid (1-min interpolation)
        out = outdoor_recent.copy()
        if "time" in out.columns:
            out = out.set_index("time")
        out = (out[weather.WEATHER_FEATURES].sort_index()
               .resample("1min").interpolate("time").reindex(grid.index)
               .interpolate("time").bfill().ffill())
        if out.isna().any().any():
            raise serving.ServingDataError("outdoor data does not cover lookback")

        # 3) ens3 delta (scaled space)
        gi = features.add_time_features(grid)
        scaled = self.b_in.transform_frame(gi)
        X = scaled[features.MODEL_FEATURES].to_numpy(np.float32)[None]
        d = np.mean([m.predict(X, verbose=0) for m in self.nets], axis=0)

        # 4) seasonal arm
        if arm == "october":
            gw = features.add_time_features(grid.join(out))
            sw = self.b_w.transform_frame(gw)
            Xw = sw[self._wf].to_numpy(np.float32)[None]
            d = (1 - self._ramp) * d + self._ramp * self.net_w.predict(Xw, verbose=0)
        else:
            gb = self._greybox_delta(grid, out, origin)
            d[0, :, 0] = 0.5 * d[0, :, 0] + 0.5 * gb

        # 5) calibration + back to physical units
        d = d * self.shrinkage[arm][None]
        last_scaled = X[0, -1, features.TARGET_IDX][None]
        y = features.reconstruct_physical(d, last_scaled, self.b_in)[0]   # (H, C)

        # 6) conformal interval + assemble output
        q_lo, q_hi = self.conformal[arm]["q_lo"], self.conformal[arm]["q_hi"]
        fut = pd.date_range(origin + pd.Timedelta(minutes=1),
                            periods=config.HORIZON, freq="1min", tz="UTC",
                            name="time")
        cols = {}
        for j, ch in enumerate(config.TARGETS):
            cols[ch] = y[:, j]
            cols[f"{ch}_lo"] = y[:, j] + q_lo[:, j]
            cols[f"{ch}_hi"] = y[:, j] + q_hi[:, j]
        frame = pd.DataFrame(cols, index=fut)

        # 7) predictive PMV + band (corner evaluation)
        pmv_mid = comfort.pmv_ppd_frame(y[:, 0], np.clip(y[:, 1], 0, 100), fut)
        corners = []
        for tt in (frame["temperature_lo"], frame["temperature_hi"]):
            for hh in (frame["humidity_lo"].clip(0, 100),
                       frame["humidity_hi"].clip(0, 100)):
                corners.append(
                    comfort.pmv_ppd_frame(tt.to_numpy(), hh.to_numpy(), fut)["pmv"]
                    .to_numpy()
                )
        pmv = pmv_mid.assign(pmv_lo=np.min(corners, axis=0),
                             pmv_hi=np.max(corners, axis=0))

        return DeploymentForecast(origin=origin, arm=arm, frame=frame, pmv=pmv)


# ---------------------------------------------------------------------------
# Live outdoor weather (Open-Meteo, no API key) -- for the real-time service
# ---------------------------------------------------------------------------

def fetch_recent_outdoor_openmeteo() -> pd.DataFrame:
    """Past ~24 h + next hours of Benguerir weather, mapped to our channels."""
    import requests

    r = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": solar.LATITUDE, "longitude": solar.LONGITUDE,
            "past_days": 1, "forecast_days": 1,
            "hourly": "temperature_2m,relative_humidity_2m,shortwave_radiation",
            "timezone": "UTC",
        }, timeout=30,
    )
    r.raise_for_status()
    j = r.json()["hourly"]
    df = pd.DataFrame({
        "time": pd.to_datetime(j["time"], utc=True),
        "out_temp": j["temperature_2m"],
        "out_humidity": j["relative_humidity_2m"],
        "solar": j["shortwave_radiation"],
    })
    return df
