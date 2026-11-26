"""Self-contained forecasting engine.

The model is built entirely from the local OHLCV dataset - no pre-trained
weights are required. On first use it trains, evaluates on a chronological holdout
and caches the artifact under ``models/``. Later requests reuse the cached model
until new market data arrives (detected via a data fingerprint).

Backends, in order of preference:
    1. TensorFlow/Keras LSTM (deep learning, when TF is installed)
    2. scikit-learn HistGradientBoostingRegressor (fast CPU fallback)
    3. NumPy least-squares linear regression (last-resort, zero dependencies)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from django.conf import settings

from . import data as data_service

logger = logging.getLogger(__name__)


class _NumpyMinMaxScaler:
    """Tiny single-feature MinMaxScaler, so scikit-learn is not required at runtime."""

    def __init__(self, feature_range=(0, 1)):
        self.lower, self.upper = feature_range
        self.min_ = None
        self.scale_ = None

    def fit(self, values):
        values = np.asarray(values, dtype=float)
        self.min_ = values.min(axis=0)
        span = values.max(axis=0) - self.min_
        self.scale_ = np.where(span == 0, 1.0, (self.upper - self.lower) / span)
        return self

    def transform(self, values):
        return np.asarray(values, dtype=float) * self.scale_ + self.lower - self.min_ * self.scale_

    def fit_transform(self, values):
        return self.fit(values).transform(values)


# Always use the lightweight scaler. The full build can still use scikit-learn
# trainers below, but importing sklearn is no longer needed to render a page.
MinMaxScaler = _NumpyMinMaxScaler

# Render-free / low-memory build: skip TensorFlow and scikit-learn entirely.
LITE_MODE = os.environ.get("STOCKSIGHT_LITE", "").lower() in ("1", "true", "yes")

SEQ_LEN = 60
MAX_DAYS = 60   # lightweight build cap; does not affect memory usage
MODEL_VERSION = "v2-returns"   # bump when the training target/pipeline changes
RETURN_SCALE = 20.0            # daily returns are small; amplify for stable training
MODEL_DIR = Path(getattr(settings, "MODEL_DIR", Path(settings.BASE_DIR) / "models"))
_DATA_LOCK = threading.Lock()
_MODEL_MEMORY: dict[tuple, dict] = {}   # warm models avoid repeated Keras disk loads

# Keep TF from grabbing every CPU core on small VPS / container deployments.
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
os.environ.setdefault("TF_NUM_INTEROP_THREADS", "1")
os.environ.setdefault("TF_NUM_INTRAOP_THREADS", "2")


@dataclass
class PredictionResult:
    symbol: str
    dates: list[str]
    predictions: list[float]
    history_dates: list[str]
    history_close: list[float]
    metrics: dict
    backtest_dates: list[str]
    backtest_actual: list[float]
    backtest_predicted: list[float]
    backtest_naive: list[float]
    signal: str
    confidence: float
    model_type: str
    trained_at: str | None
    data_through: str
    data_source: str
    stale: bool
    fresh: bool          # True when the model was trained during this request
    note: str = ""

    def as_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "dates": self.dates,
            "predictions": [round(float(p), 2) for p in self.predictions],
            "history_dates": self.history_dates,
            "history_close": [round(float(p), 2) for p in self.history_close],
            "metrics": self.metrics,
            "backtest_dates": self.backtest_dates,
            "backtest_actual": [round(float(p), 2) for p in self.backtest_actual],
            "backtest_predicted": [round(float(p), 2) for p in self.backtest_predicted],
            "backtest_naive": [round(float(p), 2) for p in self.backtest_naive],
            "signal": self.signal,
            "confidence": round(float(self.confidence), 3),
            "model_type": self.model_type,
            "trained_at": self.trained_at,
            "data_through": self.data_through,
            "data_source": self.data_source,
            "stale": self.stale,
            "fresh": self.fresh,
            "note": self.note,
        }


# --------------------------------------------------------------------------- #
# Artifact bookkeeping
# --------------------------------------------------------------------------- #
def _fingerprint(symbol: str, df, backend: str, seq_len: int) -> str:
    payload = f"{MODEL_VERSION}|{symbol}|{len(df)}|{df.index[-1].date()}|{backend}|{seq_len}"
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _paths(symbol: str) -> tuple[Path, Path, Path]:
    safe = "".join(c for c in symbol if c.isalnum() or c in "-._^")
    model = MODEL_DIR / f"{safe}.model.keras"
    auxiliary = MODEL_DIR / f"{safe}.aux.joblib"
    meta = MODEL_DIR / f"{safe}.meta.json"
    return model, auxiliary, meta


def _load_cached(symbol: str, fingerprint: str):
    model_path, aux_path, meta_path = _paths(symbol)
    if not meta_path.exists() or not aux_path.exists():
        return None
    try:
        meta = json.loads(meta_path.read_text())
        if meta.get("fingerprint") != fingerprint:
            return None
        import joblib
        backend = meta["backend"]
        if backend == "lstm":
            import keras
            model = keras.models.load_model(model_path)
            scaler = joblib.load(aux_path)
        else:
            # sklearn / numpy backends store model + scaler in one bundle.
            bundle = joblib.load(aux_path)
            model, scaler = bundle["model"], bundle["scaler"]
        return {
            "backend": backend,
            "model": model,
            "scaler": scaler,
            "trained_at": meta.get("trained_at"),
            "seq_len": meta.get("seq_len", SEQ_LEN),
        }
    except Exception as exc:  # pragma: no cover - corrupted cache
        logger.warning("Ignoring unusable cached model for %s: %s", symbol, exc)
        return None


def _save_cached(symbol: str, fingerprint: str, backend: str, model, scaler,
                 seq_len: int, trained_at: str) -> None:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    model_path, aux_path, meta_path = _paths(symbol)
    import joblib
    if backend == "lstm":
        model.save(model_path)
        joblib.dump(scaler, aux_path)
    else:
        joblib.dump({"model": model, "scaler": scaler}, aux_path)
        if model_path.exists():
            model_path.unlink()
    meta_path.write_text(json.dumps({
        "symbol": symbol,
        "fingerprint": fingerprint,
        "backend": backend,
        "seq_len": seq_len,
        "trained_at": trained_at,
    }, indent=2))


# --------------------------------------------------------------------------- #
# Data preparation
# --------------------------------------------------------------------------- #
def _make_sequences(scaled: np.ndarray, targets: np.ndarray,
                    seq_len: int) -> tuple[np.ndarray, np.ndarray]:
    """Windows of scaled prices -> scaled one-day return that follows them.

    Predicting returns instead of absolute price keeps the target stationary,
    which makes all three backends markedly more robust across long histories.
    """
    xs, ys = [], []
    for i in range(seq_len, len(scaled)):
        xs.append(scaled[i - seq_len:i, 0])
        ys.append(targets[i - 1])
    return np.asarray(xs, dtype="float32"), np.asarray(ys, dtype="float32")


def _metrics(actual: np.ndarray, predicted: np.ndarray, naive: np.ndarray) -> dict:
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    if actual.size == 0:
        return {"rmse": None, "mae": None, "mape": None, "direction_accuracy": None,
                "naive_rmse": None, "rmse_vs_naive": None, "samples": 0}
    rmse = float(np.sqrt(np.mean((actual - predicted) ** 2)))
    mae = float(np.mean(np.abs(actual - predicted)))
    nonzero = np.abs(actual) > 1e-8
    mape = float(np.mean(np.abs((actual[nonzero] - predicted[nonzero]) / actual[nonzero])) * 100) if nonzero.any() else None
    direction = float(np.mean(
        (np.diff(actual) > 0) == (np.diff(predicted) > 0)
    )) if actual.size > 1 else 0.5
    naive_rmse = float(np.sqrt(np.mean((actual - naive) ** 2)))
    return {
        "rmse": round(rmse, 4),
        "mae": round(mae, 4),
        "mape": round(mape, 2) if mape is not None else None,
        "direction_accuracy": round(direction, 3),
        "naive_rmse": round(naive_rmse, 4),
        "rmse_vs_naive": round((1 - rmse / naive_rmse) * 100, 1) if naive_rmse else None,
        "samples": int(actual.size),
    }


# --------------------------------------------------------------------------- #
# Backend trainers
# --------------------------------------------------------------------------- #
def _train_lstm(x_train, y_train, x_val, y_val, seq_len):
    import keras
    keras.backend.clear_session()
    model = keras.Sequential([
        keras.Input(shape=(seq_len, 1)),
        keras.layers.LSTM(64, return_sequences=True),
        keras.layers.Dropout(0.2),
        keras.layers.LSTM(32),
        keras.layers.Dense(16, activation="relu"),
        keras.layers.Dense(1),
    ])
    model.compile(optimizer=keras.optimizers.Adam(1e-3), loss="mse", metrics=["mae"])
    callbacks = [
        keras.callbacks.EarlyStopping(monitor="val_loss" if len(x_val) else "loss",
                                      patience=4, restore_best_weights=True),
        keras.callbacks.ReduceLROnPlateau(monitor="loss", factor=0.5, patience=2, min_lr=1e-5),
    ]
    fit_kwargs = dict(epochs=30, batch_size=32, verbose=0, callbacks=callbacks, shuffle=False)
    if len(x_val):
        fit_kwargs["validation_data"] = (x_val, y_val)
    model.fit(x_train, y_train, **fit_kwargs)
    return model


def _train_sklearn(x_train, y_train, x_val, y_val):
    from sklearn.ensemble import HistGradientBoostingRegressor
    model = HistGradientBoostingRegressor(
        max_iter=250, learning_rate=0.05, max_leaf_nodes=15,
        l2_regularization=0.1, random_state=42,
    )
    model.fit(x_train, y_train)
    return model


def _train_numpy(x_train, y_train):
    # Analytic ridge solution: (XᵀX + λI)⁻¹ Xᵀy
    xtx = x_train.T @ x_train
    xtx.flat[:: xtx.shape[0] + 1] += 1e-3
    return np.linalg.solve(xtx, x_train.T @ y_train)


def _predict_backend(backend: str, model, features: np.ndarray) -> float:
    if backend == "lstm":
        value = model.predict(features.reshape(1, -1, 1), verbose=0)[0][0]
    elif backend == "sklearn":
        value = model.predict(features.reshape(1, -1))[0]
    else:  # numpy
        value = float(np.dot(np.asarray(features).reshape(-1), model))
    return float(np.clip(value, -1e6, 1e6))


# --------------------------------------------------------------------------- #
# Public entry points
# --------------------------------------------------------------------------- #
def predict(
    symbol: str,
    days: int = 7,
    seq_len: int = SEQ_LEN,
    backend: str = "auto",         # auto | lstm | sklearn | numpy
    force_retrain: bool = False,
    refresh_data: bool = True,
) -> PredictionResult:
    """Train-or-load a model from local data and produce an N-day forecast."""
    symbol = data_service.normalize_symbol(symbol)
    days = max(1, min(int(days), MAX_DAYS))
    seq_len = max(10, min(int(seq_len), 120))

    history = data_service.get_history(symbol, refresh="auto" if refresh_data else "never")
    df = history.df
    if len(df) < seq_len + 20:
        # Pull as much history as the provider has before giving up.
        if refresh_data:
            history = data_service.get_history(symbol, refresh="force")
            df = history.df
        if len(df) < seq_len + 20:
            raise ValueError(
                f"Need at least {seq_len + 20} trading days for {symbol}, found {len(df)}. "
                "Try refreshing market data first."
            )

    close_values = df["Close"].astype(float).to_numpy()
    closes = close_values.reshape(-1, 1)
    scaler = MinMaxScaler(feature_range=(0, 1))
    scaled = scaler.fit_transform(closes).astype("float32")  # shape (n, 1)

    # Stationary target: the daily return that follows each 60-day window.
    raw_returns = np.diff(close_values) / np.maximum(close_values[:-1], 1e-8)
    targets = np.clip(raw_returns * RETURN_SCALE, -5, 5).astype("float32")
    x_all, y_all = _make_sequences(scaled, targets, seq_len)
    split = max(1, int(len(x_all) * 0.9))
    x_train, y_train = x_all[:split], y_all[:split]
    x_val, y_val = x_all[split:], y_all[split:]

    preferred = [] if backend == "auto" else [backend]
    candidates = ["numpy"] if LITE_MODE else (preferred or ["lstm", "sklearn", "numpy"])
    use_backend, trained_model, fresh = None, None, False
    note = ""

    # Any cached backend is valid as long as the data fingerprint matches.
    for candidate in candidates:
        candidate_fp = _fingerprint(symbol, df, candidate, seq_len)
        memory_key = (symbol, candidate_fp)
        cached = _MODEL_MEMORY.get(memory_key)
        if cached is None:
            cached = _load_cached(symbol, candidate_fp)
            if cached:
                _MODEL_MEMORY[memory_key] = cached
        if cached and not force_retrain:
            use_backend, trained_model = cached["backend"], cached
            seq_len = cached["seq_len"]
            break
        try:
            with _DATA_LOCK:
                if candidate == "lstm":
                    model = _train_lstm(
                        x_train.reshape(-1, seq_len, 1), y_train,
                        x_val.reshape(-1, seq_len, 1), y_val, seq_len,
                    )
                    trained_model = {"backend": "lstm", "model": model, "scaler": scaler,
                                     "seq_len": seq_len}
                elif candidate == "sklearn":
                    model = _train_sklearn(x_train, y_train, x_val, y_val)
                    trained_model = {"backend": "sklearn", "model": model, "scaler": scaler,
                                     "seq_len": seq_len}
                else:
                    model = _train_numpy(x_train, y_train)
                    trained_model = {"backend": "numpy", "model": model, "scaler": scaler,
                                     "seq_len": seq_len}
            use_backend = candidate
            fresh = True
            trained_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            _save_cached(symbol, candidate_fp, use_backend, trained_model["model"],
                         scaler, seq_len, trained_at)
            trained_model["trained_at"] = trained_at
            _MODEL_MEMORY[memory_key] = trained_model
            break
        except Exception as exc:
            note = f"{candidate} backend unavailable: {str(exc)[:180]}"
            logger.warning("%s for %s, trying next backend", note, symbol)
            continue

    if not use_backend or not trained_model:
        raise RuntimeError(f"No forecasting backend could be initialised. {note}")

    model = trained_model["model"]
    scaler = trained_model["scaler"]
    seq_len = trained_model["seq_len"]

    # Evaluate on the chronological holdout.
    backtest_dates: list[str] = []
    backtest_actual: list[float] = []
    backtest_predicted: list[float] = []
    backtest_naive: list[float] = []
    if len(x_val):
        if use_backend == "lstm":
            val_preds = model.predict(x_val.reshape(-1, seq_len, 1), verbose=0).ravel()
        elif use_backend == "sklearn":
            val_preds = model.predict(x_val)
        else:
            val_preds = x_val @ model
        val_start = seq_len + split
        prev_prices = close_values[val_start - 1: val_start - 1 + len(y_val)]
        actual_prices = close_values[val_start: val_start + len(y_val)]
        pred_prices = prev_prices * (1 + val_preds / RETURN_SCALE)
        naive_prices = prev_prices  # "tomorrow = today" baseline
        metrics = _metrics(actual_prices, pred_prices, naive_prices)
        backtest_dates = [d.strftime("%d %b %y") for d in df.index[val_start: val_start + len(y_val)]][-120:]
        backtest_actual = [float(v) for v in actual_prices][-120:]
        backtest_predicted = [float(v) for v in pred_prices][-120:]
        backtest_naive = [float(v) for v in naive_prices][-120:]
    else:
        metrics = _metrics(np.array([]), np.array([]), np.array([]))

    # Recursive multi-step forecast in price space.
    window = scaled[-seq_len:, 0].copy()
    last_price = float(close_values[-1])
    predictions: list[float] = []
    for _ in range(days):
        ret_scaled = _predict_backend(use_backend, model, window)
        ret = float(np.clip(ret_scaled, -5, 5)) / RETURN_SCALE
        last_price *= (1 + ret)
        predictions.append(last_price)
        next_scaled = float(scaler.transform([[last_price]])[0, 0])
        window = np.append(window[1:], next_scaled)

    future_dates = []
    cursor = pd.Timestamp(df.index[-1])
    while len(future_dates) < days:
        cursor += timedelta(days=1)
        if cursor.weekday() < 5:
            future_dates.append(cursor.strftime("%d %b %Y"))

    trend_up = bool(predictions[-1] > predictions[0])
    above_now = bool(predictions[-1] > closes[-1][0])
    direction = metrics.get("direction_accuracy") or 0.5
    if trend_up and above_now and direction >= 0.48:
        signal = "BUY"
    elif not trend_up and not above_now and direction >= 0.48:
        signal = "SELL"
    else:
        signal = "HOLD"

    return PredictionResult(
        symbol=symbol,
        dates=future_dates,
        predictions=predictions,
        history_dates=[d.strftime("%d %b %y") for d in df.index[-90:]],
        history_close=[float(v) for v in closes[-90:].ravel()],
        metrics=metrics,
        backtest_dates=backtest_dates,
        backtest_actual=backtest_actual,
        backtest_predicted=backtest_predicted,
        backtest_naive=backtest_naive,
        signal=signal,
        confidence=direction,
        model_type={"lstm": "LSTM (TensorFlow)", "sklearn": "Gradient Boosting (scikit-learn)",
                    "numpy": "Linear regression (NumPy)"}[use_backend],
        trained_at=trained_model.get("trained_at"),
        data_through=df.index[-1].strftime("%d %b %Y"),
        data_source=history.source,
        stale=history.stale,
        fresh=fresh,
        note=note,
    )


def train(symbol: str, **kwargs) -> PredictionResult:
    """Train (or refresh) a model without caring about the forecast horizon."""
    return predict(symbol, days=1, force_retrain=True, **kwargs)
