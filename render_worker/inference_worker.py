"""LSTM inference worker -- main loop (Render background worker entrypoint).

Architecture:
    sensors --> [on-site ingestion scripts] --> InfluxDB Cloud
                                                     |
                              (this worker, on Render) reads last LOOKBACK_MIN
                                                     |
                       LSTM direct multi-step forecast (one forward pass)
                                                     |
                              writes forecast back --> InfluxDB Cloud
                                                     |
                                              dashboard (measured vs predicted)

Every PREDICT_EVERY_SEC seconds, for EACH zone:
    1. read_window  -> last LOOKBACK_MIN min of FEATURES on a 1-min grid
    2. staleness/gap guard  -> skip if stale or too few real points
    3. preprocess with the persisted training scaler (same feature order)
    4. model.predict  -> direct multi-step horizon in ONE forward pass
    5. inverse-transform -> write forecast to prediction_<zone>

================================================================================
 THE FOUR CORRECTNESS RULES (this is where naive deployments fail)
================================================================================
 R1  LOOKBACK_MIN MUST equal the training lookback.
     -> asserted: model.input_shape[1] == LOOKBACK_MIN  (startup, fail loud).
 R2  DIRECT multi-step output ONLY. The model emits the whole horizon in one
     forward pass.  NEVER do recursive step-by-step rollout: feeding step t's
     prediction back as input for t+1 compounds error and is THE #1 bug that
     turns a 0.15 degC offline error into a 3.4 degC online error.
     -> asserted: model output length == HORIZON_MIN (startup, fail loud).
 R3  Same scaler + same feature order as training, loaded from disk, reused --
     NEVER refit on serving data.
 R4  tz-aware UTC timestamps everywhere (datetime.now(timezone.utc)).
================================================================================
"""
from __future__ import annotations

import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone
from typing import List

import numpy as np
import pandas as pd

# Load .env for local runs (no-op if python-dotenv missing or no .env present).
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:  # pragma: no cover - optional dependency
    pass

import config
import influx_io
import preprocess

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger("inference_worker")

# Graceful shutdown flag set by SIGTERM/SIGINT (Render sends SIGTERM on deploy).
_STOP = False


def _handle_stop(signum, _frame):
    global _STOP
    logger.info("Signal %s recu : arret en douceur apres le cycle courant.", signum)
    _STOP = True


# ---------------------------------------------------------------------------
# Model loading + startup contract checks (R1, R2)
# ---------------------------------------------------------------------------
def load_model_and_check():
    """Load the Keras model and assert the window contract (R1 + R2)."""
    # Quiet TF logs before import.
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
    import keras  # lazy import: keeps startup logs clean and import errors local

    model = keras.models.load_model(config.MODEL_PATH, compile=False)

    in_shape = model.input_shape       # (None, timesteps, n_features)
    out_shape = model.output_shape     # (None, horizon, n_targets) for direct ms

    logger.info("Modele charge : input_shape=%s, output_shape=%s.", in_shape, out_shape)

    # ---- R1: lookback (number of input timesteps) must match training --------
    n_timesteps = in_shape[1]
    if n_timesteps != config.LOOKBACK_MIN:
        raise RuntimeError(
            f"[R1] Contrat de fenetre viole : model.input_shape[1]={n_timesteps} "
            f"!= LOOKBACK_MIN={config.LOOKBACK_MIN}. Ajustez LOOKBACK_MIN dans "
            f"config.py pour qu'il EGALE le lookback d'entrainement."
        )

    # ---- R2: direct multi-step -> output horizon length must equal HORIZON ---
    # Direct multi-step models emit shape (None, HORIZON, n_targets). If the
    # output is 2-D (None, n_targets*HORIZON) you must reshape -- but you must
    # STILL produce the full horizon in one pass (never roll out recursively).
    horizon_len = _infer_horizon_length(out_shape)
    if horizon_len != config.HORIZON_MIN:
        raise RuntimeError(
            f"[R2] Sortie multi-step directe attendue de longueur "
            f"HORIZON_MIN={config.HORIZON_MIN}, mais le modele produit "
            f"{horizon_len} pas (output_shape={out_shape}). Ne JAMAIS compenser "
            f"par un rollout recursif pas-a-pas (bug #1)."
        )

    # Sanity: number of input feature channels matches our assembled features.
    n_model_features = len(config.FEATURES) + (2 if config.USE_TIME_FEATURES else 0)
    if in_shape[2] != n_model_features:
        raise RuntimeError(
            f"[R3] Le modele attend {in_shape[2]} canaux d'entree mais la config "
            f"en assemble {n_model_features} (FEATURES={config.FEATURES}, "
            f"USE_TIME_FEATURES={config.USE_TIME_FEATURES}). Verifiez FEATURES / "
            f"USE_TIME_FEATURES / FIELD_MAP."
        )

    return model


def _infer_horizon_length(out_shape) -> int:
    """Number of forecast timesteps from the model output shape.

    Handles the two common direct-multi-step layouts:
      (None, HORIZON, n_targets) -> HORIZON
      (None, HORIZON*n_targets)  -> HORIZON  (flattened head)
    """
    if len(out_shape) == 3:
        return out_shape[1]
    if len(out_shape) == 2:
        n_targets = len(config.TARGETS)
        flat = out_shape[1]
        if flat % n_targets != 0:
            raise RuntimeError(
                f"[R2] Sortie aplatie de taille {flat} non divisible par "
                f"n_targets={n_targets}; impossible de retrouver l'horizon."
            )
        return flat // n_targets
    raise RuntimeError(f"[R2] output_shape inattendu: {out_shape}")


def _reshape_model_output(y_raw: np.ndarray) -> np.ndarray:
    """Squeeze model output to (HORIZON, n_targets), no recursive rollout."""
    n_targets = len(config.TARGETS)
    y = np.asarray(y_raw)
    if y.ndim == 3:                       # (1, HORIZON, n_targets)
        y = y[0]
    elif y.ndim == 2 and y.shape[0] == 1:  # (1, HORIZON*n_targets)
        y = y[0].reshape(config.HORIZON_MIN, n_targets)
    else:
        y = y.reshape(config.HORIZON_MIN, n_targets)
    return y.astype(np.float64)


# ---------------------------------------------------------------------------
# Staleness / gap guard (R4 freshness)
# ---------------------------------------------------------------------------
def passes_freshness_guard(zone: str, df: pd.DataFrame, now: datetime) -> bool:
    """Return True if ``df`` is fresh and dense enough to forecast on.

    Refuses (logs a warning + returns False) when:
      * the window is shorter than LOOKBACK_MIN,
      * the newest REAL point is older than MAX_STALENESS_MIN,
      * fewer than MIN_FRESH_POINTS real (non-NaN) points across FEATURES.
    """
    if df.empty:
        logger.warning("Zone %s : aucune donnee retournee par InfluxDB. Cycle ignore.", zone)
        return False

    # Real points = rows where ALL features are present (a usable observation).
    real_mask = df.notna().all(axis=1)
    n_real = int(real_mask.sum())

    if n_real == 0:
        logger.warning("Zone %s : 0 point reel dans la fenetre. Cycle ignore.", zone)
        return False

    last_real_ts = df.index[real_mask][-1]
    age_min = (now - last_real_ts.to_pydatetime()).total_seconds() / 60.0
    if age_min > config.MAX_STALENESS_MIN:
        logger.warning(
            "Zone %s : donnees perimees (dernier point reel il y a %.1f min "
            "> MAX_STALENESS_MIN=%d). Cycle ignore (pas de prevision sur du "
            "forward-fill).",
            zone, age_min, config.MAX_STALENESS_MIN,
        )
        return False

    if n_real < config.MIN_FRESH_POINTS:
        logger.warning(
            "Zone %s : seulement %d points reels < MIN_FRESH_POINTS=%d. "
            "Fenetre trop creuse, cycle ignore.",
            zone, n_real, config.MIN_FRESH_POINTS,
        )
        return False

    if len(df) < config.LOOKBACK_MIN:
        logger.warning(
            "Zone %s : %d minutes d'historique < LOOKBACK_MIN=%d. Cycle ignore.",
            zone, len(df), config.LOOKBACK_MIN,
        )
        return False

    return True


def _fill_small_gaps(df: pd.DataFrame) -> pd.DataFrame:
    """Interpolate ONLY interior gaps (NaN holes) so the tensor has no NaN.

    The freshness guard already ensured the window is mostly real; here we just
    bridge the small holes left by aggregateWindow(createEmpty: true). This is
    NOT forward-filling stale data (that case was rejected upstream).
    """
    out = df.interpolate(method="time", limit_direction="both")
    return out


# ---------------------------------------------------------------------------
# One forecast cycle for one zone
# ---------------------------------------------------------------------------
def run_zone_cycle(zone: str, model, scaler) -> None:
    now = datetime.now(timezone.utc)          # R4: tz-aware UTC

    # 1. read the lookback window (1-min grid, training feature order, gaps=NaN)
    df = influx_io.read_window(zone, config.FEATURES, config.LOOKBACK_MIN)

    # 2. staleness / gap guard
    if not passes_freshness_guard(zone, df, now):
        return

    grid = _fill_small_gaps(df)
    if grid.isna().any().any():
        logger.warning("Zone %s : NaN residuels apres interpolation. Cycle ignore.", zone)
        return
    grid = grid.iloc[-config.LOOKBACK_MIN:]

    # 3. preprocess with the persisted training scaler (R3: reuse, never refit)
    X = preprocess.build_input_tensor(scaler, grid)   # (1, LOOKBACK, n_features)

    # 4. DIRECT multi-step forecast -- ONE forward pass (R2). NO rollout loop.
    y_raw = model.predict(X, verbose=0)
    y_model = _reshape_model_output(y_raw)            # (HORIZON, n_targets)

    # 5. inverse-transform (+ residual reconstruction if applicable) -> physical
    y_phys = preprocess.postprocess_prediction(scaler, y_model, X)

    # Future timestamps: now + i*DELTA_MIN, i = 1..HORIZON (tz-aware UTC, R4).
    origin = grid.index[-1]
    future_index = pd.date_range(
        start=origin + pd.Timedelta(minutes=config.DELTA_MIN),
        periods=config.HORIZON_MIN,
        freq=f"{config.DELTA_MIN}min",
        tz="UTC",
        name="time",
    )
    forecast_df = pd.DataFrame(y_phys, index=future_index, columns=config.TARGETS)

    # write back: one field per target (e.g. temperature_pred, humidite_pred)
    influx_io.write_forecast(zone, forecast_df)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
def main() -> int:
    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)

    logger.info("=== Demarrage du worker d'inference LSTM ===")
    logger.info("LOOKBACK_MIN=%d  HORIZON_MIN=%d  RESOLUTION_MIN=%d",
                config.LOOKBACK_MIN, config.HORIZON_MIN, config.RESOLUTION_MIN)
    logger.info("FEATURES=%s  TARGETS=%s  USE_TIME_FEATURES=%s  OUTPUT_IS_RESIDUAL=%s",
                config.FEATURES, config.TARGETS,
                config.USE_TIME_FEATURES, config.OUTPUT_IS_RESIDUAL)

    if not config.influx_settings_ok():
        logger.error("Variables InfluxDB manquantes (INFLUX_URL/ORG/TOKEN). Arret.")
        return 2

    try:
        model = load_model_and_check()             # R1 + R2 asserts here
        scaler = preprocess.load_scaler()          # R3: persisted scaler
    except Exception as exc:
        logger.exception("Echec de l'initialisation (modele/scaler): %s", exc)
        return 1

    logger.info("Initialisation OK. Boucle toutes les %d s sur les zones: %s.",
                config.PREDICT_EVERY_SEC, list(config.ZONES))

    while not _STOP:
        cycle_start = time.monotonic()
        for zone in config.ZONES:
            try:
                run_zone_cycle(zone, model, scaler)
            except Exception as exc:
                # graceful per-zone error: one bad zone never kills the loop.
                logger.exception("Zone %s : erreur pendant le cycle: %s", zone, exc)

        if _STOP:
            break

        # Sleep the remainder of the cadence (subtract work already done).
        elapsed = time.monotonic() - cycle_start
        sleep_s = max(0.0, config.PREDICT_EVERY_SEC - elapsed)
        # Interruptible sleep so SIGTERM is honored promptly.
        slept = 0.0
        while slept < sleep_s and not _STOP:
            step = min(1.0, sleep_s - slept)
            time.sleep(step)
            slept += step

    influx_io.close_client()
    logger.info("=== Worker arrete proprement ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
