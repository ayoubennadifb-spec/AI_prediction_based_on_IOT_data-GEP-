"""LSTM forecasters (LSTM family only, per project constraint).

Two architectures, both DIRECT multi-step (one forward pass emits the whole
horizon -- recursive rollout is forbidden, it caused the 3.42 degC live MAE):

  * direct  : stacked LSTM encoder -> Dense(H * n_targets)   (Afaf-style head,
              but multivariate + residual target)
  * seq2seq : LSTM encoder -> RepeatVector(H) -> LSTM decoder
              -> TimeDistributed(Dense)                      (D1 + D2)

Training recipe (E1-E3): Adam + ReduceLROnPlateau + EarlyStopping, Huber loss
(robust to residual sensor spikes), inter-layer Dropout. recurrent_dropout is
deliberately NOT used -- it disables Keras' fused LSTM kernel and makes CPU
training ~10x slower for a low-impact regularizer.

Default tanh/sigmoid gate activations are kept (they were correct in Afaf's
code; the report's 'RELU' claim did not match the implementation).
"""
from __future__ import annotations

import random

import numpy as np

from . import config


def set_seed(seed: int) -> None:
    """Best-effort full determinism for reproducible runs (E4)."""
    import tensorflow as tf

    random.seed(seed)
    np.random.seed(seed)
    tf.random.set_seed(seed)


def horizon_weighted_huber(
    horizon: int,
    w_min: float = 0.5,
    w_max: float = 2.0,
    delta: float = 1.0,
):
    """Huber loss with a linear weight ramp across the forecast horizon.

    Late lead times get up to w_max/w_min more weight, pushing optimization
    effort toward the long horizons where persistence collapses and skill
    actually matters. Weights are normalized to mean 1 so the loss scale
    stays comparable to plain Huber."""
    import tensorflow as tf

    w = tf.linspace(float(w_min), float(w_max), horizon)
    w = w / tf.reduce_mean(w)
    w = tf.reshape(w, (1, horizon, 1))

    def loss(y_true, y_pred):
        err = y_true - y_pred
        abs_err = tf.abs(err)
        quad = tf.minimum(abs_err, delta)
        lin = abs_err - quad
        per_elem = 0.5 * tf.square(quad) + delta * lin     # (B, H, T)
        return tf.reduce_mean(per_elem * w)

    loss.__name__ = "horizon_weighted_huber"
    return loss


# ---------------------------------------------------------------------------
# Architectures
# ---------------------------------------------------------------------------

def build_direct_lstm(
    n_features: int,
    lookback: int = config.LOOKBACK,
    horizon: int = config.HORIZON,
    n_targets: int = len(config.TARGETS),
    units: tuple[int, ...] = (96, 64),
    dropout: float = 0.25,
    learning_rate: float = 1e-3,
    horizon_weighted: bool = False,
):
    """Stacked LSTM -> Dense(H * n_targets), reshaped to (H, n_targets)."""
    from tensorflow.keras import Model, Input, layers, optimizers, losses

    inp = Input(shape=(lookback, n_features))
    x = inp
    for i, u in enumerate(units):
        last = i == len(units) - 1
        x = layers.LSTM(u, return_sequences=not last)(x)
        x = layers.Dropout(dropout)(x)
    x = layers.Dense(horizon * n_targets)(x)
    out = layers.Reshape((horizon, n_targets))(x)
    model = Model(inp, out, name="direct_lstm")
    loss = (
        horizon_weighted_huber(horizon)
        if horizon_weighted
        else losses.Huber(delta=1.0)
    )
    model.compile(
        optimizer=optimizers.Adam(learning_rate=learning_rate),
        loss=loss,
        metrics=["mae"],
    )
    return model


def build_seq2seq_lstm(
    n_features: int,
    lookback: int = config.LOOKBACK,
    horizon: int = config.HORIZON,
    n_targets: int = len(config.TARGETS),
    enc_units: tuple[int, ...] = (96, 64),
    dec_units: int = 64,
    dropout: float = 0.25,
    learning_rate: float = 1e-3,
):
    """Encoder-decoder: encoder summary state is repeated across the horizon
    and decoded step-by-step (still ONE forward pass -- not recursive)."""
    from tensorflow.keras import Model, Input, layers, optimizers, losses

    inp = Input(shape=(lookback, n_features))
    x = inp
    for u in enc_units[:-1]:
        x = layers.LSTM(u, return_sequences=True)(x)
        x = layers.Dropout(dropout)(x)
    x = layers.LSTM(enc_units[-1])(x)
    x = layers.Dropout(dropout)(x)

    x = layers.RepeatVector(horizon)(x)
    x = layers.LSTM(dec_units, return_sequences=True)(x)
    x = layers.TimeDistributed(layers.Dense(32, activation="relu"))(x)
    out = layers.TimeDistributed(layers.Dense(n_targets))(x)

    model = Model(inp, out, name="seq2seq_lstm")
    model.compile(
        optimizer=optimizers.Adam(learning_rate=learning_rate),
        loss=losses.Huber(delta=1.0),
        metrics=["mae"],
    )
    return model


BUILDERS = {"direct": build_direct_lstm, "seq2seq": build_seq2seq_lstm}


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

def train(
    model,
    X_train, y_train,
    X_val, y_val,
    epochs: int = 100,
    batch_size: int = 128,
    patience: int = 8,
    verbose: int = 2,
):
    """Fit with EarlyStopping (restore best) + ReduceLROnPlateau (E1)."""
    from tensorflow.keras import callbacks as cb

    history = model.fit(
        X_train, y_train,
        validation_data=(X_val, y_val),
        epochs=epochs,
        batch_size=batch_size,
        callbacks=[
            cb.EarlyStopping(
                monitor="val_loss", patience=patience, restore_best_weights=True
            ),
            cb.ReduceLROnPlateau(
                monitor="val_loss", factor=0.5, patience=3, min_lr=1e-5
            ),
        ],
        verbose=verbose,
    )
    return history
