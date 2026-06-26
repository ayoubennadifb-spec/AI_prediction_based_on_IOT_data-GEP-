Drop your two trained artifacts in THIS folder:

  1. lstm.keras   -- the trained Keras model (Keras 3 .keras format).
                     This is a DIRECT multi-step model: ONE forward pass emits
                     the whole HORIZON_MIN-step forecast.
                     Its input_shape MUST be (None, LOOKBACK_MIN, n_features)
                     and output length MUST be HORIZON_MIN (asserted at startup).

  2. scaler.pkl   -- the SAME scaler object you fit at TRAINING time
                     (joblib.dump). It is loaded and reused, never refit.

Filenames must match MODEL_PATH / SCALER_PATH in ../config.py
(default: model/lstm.keras and model/scaler.pkl).

--------------------------------------------------------------------------------
Picking the right files from this project's training outputs
--------------------------------------------------------------------------------
The GEP training pipeline saved models under:
    My work/AI/final/outputs/models/
        direct_seed42.keras          input (None, 240, 5)  output (None, 240, 2)
        direct_weather_seed42.keras  input (None, 240, 8)  output (None, 240, 2)
and the scaler as a ScalerBundle:
    My work/AI/final/outputs/scaler_bundle.joblib

If you deploy direct_seed42.keras, set in config.py:
    LOOKBACK_MIN = 240
    HORIZON_MIN  = 240
    FEATURES     = ["temperature", "humidity", "co2"]
    TARGETS      = ["temperature", "humidity"]
    USE_TIME_FEATURES  = True          # the 4th/5th channels are hour_sin/hour_cos
    OUTPUT_IS_RESIDUAL = True          # the model predicts a delta, not absolute
    SCALER_KIND  = "bundle"            # ScalerBundle (per-channel scalers)
    FIELD_MAP    = {"temperature":"temperature", "humidity":"humidite", "co2":"gaz"}

and copy/rename:
    final/outputs/models/direct_seed42.keras   -> model/lstm.keras
    final/outputs/scaler_bundle.joblib         -> model/scaler.pkl

NOTE: SCALER_KIND="bundle" needs the gep_forecast package importable, OR
re-export just the inner per-channel scalers dict and use SCALER_KIND="perchannel":
    import joblib
    b = joblib.load("scaler_bundle.joblib")
    joblib.dump(dict(b.scalers), "scaler.pkl")   # {feature_name: sklearn scaler}

(These artifacts are NOT committed to git -- this folder ships empty except for
this README.)
