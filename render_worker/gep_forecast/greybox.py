"""Grey-box (physics-guided) linear corrector for long-horizon temperature.

WHY THIS EXISTS -- the justification chain:
  1. The LSTM's July long-horizon failure is a VARIANCE problem: +20% skill
     on validation weeks collapsing to -5% on test weeks = overfitting to
     weather episodes (too many parameters, too few distinct July episodes).
  2. A discretized 1R1C building-thermal model says the temperature change
     over a horizon is approximately LINEAR in a few physical drivers:
         dT(t->t+h) ~ a*(T_out - T_in)        (conduction)
                    + b*INT[clear-sky GHI]    (solar gain; deterministic
                                               astronomy -> the FUTURE part
                                               is known with zero leakage)
                    + c*(recent trend)        (thermal-mass momentum)
                    + d*(deviation from recent mean)   (mean reversion)
  3. A ridge regression per lead on these ~6 features has ~10^4 x fewer
     parameters than the LSTM -- it cannot memorize episodes, so its val
     performance is an honest predictor of test performance.
  4. The drivers carry measured linear-strength signal in July (corr with
     the 4 h residual: out_temp +0.38, solar +0.53).

Features are all computable at serving time from the lookback window,
current ERA5 sample, and astronomy.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config

GREYBOX_ALPHAS = [1.0, 10.0, 100.0, 1000.0]

# indices into config.FEATURES
_T = config.FEATURES.index("temperature")


def build_design(
    data: pd.DataFrame,          # segmented dataset + out_temp/solar + csky_ghi
    index: pd.DataFrame,         # window index rows to materialise
    lookback: int = config.LOOKBACK,
    horizon: int = config.HORIZON,
):
    """Physics-motivated design matrix per window.

    Returns:
        X_static  (n, 5)   features independent of lead
        csky_int  (n, H)   mean future clear-sky GHI over (t0, t0+h] per lead
        y_delta   (n, H)   physical temperature change targets
    """
    t_in = data["temperature"].to_numpy(np.float64)
    out_t = data["out_temp"].to_numpy(np.float64)
    solar = data["solar"].to_numpy(np.float64)
    csky = data["csky_ghi"].to_numpy(np.float64)
    csum = np.concatenate([[0.0], np.cumsum(csky)])

    pos = index["pos"].to_numpy()
    o = pos + lookback - 1                       # forecast-origin row
    n = len(pos)

    win = np.lib.stride_tricks.sliding_window_view(t_in, lookback)[pos]
    X_static = np.column_stack([
        t_in[o] - win.mean(axis=1),              # deviation from 4 h mean
        t_in[o] - t_in[o - 60],                  # 1 h trend
        t_in[o] - t_in[o - (lookback - 1)],      # 4 h trend
        out_t[o] - t_in[o],                      # indoor-outdoor drive (ERA5)
        solar[o],                                # current irradiance (clouds incl.)
    ])

    h = np.arange(1, horizon + 1)
    # mean clear-sky GHI over (t0, t0+h] -- deterministic future, no leakage
    csky_int = (csum[o[:, None] + h[None, :] + 1] - csum[o[:, None] + 1]) / h

    y_delta = t_in[o[:, None] + h[None, :]] - t_in[o][:, None]
    return X_static.astype(np.float32), csky_int.astype(np.float32), \
        y_delta.astype(np.float32)


class GreyboxCorrector:
    """One ridge regression per lead time (240 tiny models, ~7 params each)."""

    def __init__(self, alpha: float = 100.0, horizon: int = config.HORIZON):
        self.alpha = alpha
        self.horizon = horizon
        self.coef_ = None        # (H, n_features)
        self.intercept_ = None   # (H,)
        self.mu_ = None
        self.sd_ = None

    def _assemble(self, X_static, csky_int, h):
        return np.column_stack([X_static, csky_int[:, h]])

    def fit(self, X_static, csky_int, y_delta):
        n_feat = X_static.shape[1] + 1
        H = self.horizon
        self.coef_ = np.zeros((H, n_feat), np.float64)
        self.intercept_ = np.zeros(H, np.float64)
        # standardize per feature using lead-0 stats (csky col varies per lead
        # but shares scale); refit stats per lead is cheap enough -- do it.
        self.mu_ = np.zeros((H, n_feat)); self.sd_ = np.ones((H, n_feat))
        eye = np.eye(n_feat)
        for h in range(H):
            X = self._assemble(X_static, csky_int, h).astype(np.float64)
            mu, sd = X.mean(0), X.std(0) + 1e-9
            Xs = (X - mu) / sd
            y = y_delta[:, h].astype(np.float64)
            ym = y.mean()
            A = Xs.T @ Xs + self.alpha * eye
            b = Xs.T @ (y - ym)
            w = np.linalg.solve(A, b)
            self.coef_[h] = w
            self.intercept_[h] = ym
            self.mu_[h], self.sd_[h] = mu, sd
        return self

    def predict(self, X_static, csky_int):
        n = X_static.shape[0]
        out = np.zeros((n, self.horizon), np.float32)
        for h in range(self.horizon):
            X = self._assemble(X_static, csky_int, h).astype(np.float64)
            Xs = (X - self.mu_[h]) / self.sd_[h]
            out[:, h] = (Xs @ self.coef_[h] + self.intercept_[h]).astype(np.float32)
        return out
