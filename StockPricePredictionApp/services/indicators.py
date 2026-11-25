"""Technical indicators computed from cached daily OHLCV data.

Everything is plain pandas/numpy so it works offline and adds no dependency.
Series are aligned to the input index and contain ``None`` during their warm-up
window, which keeps Chart.js rendering straightforward.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _round_list(series: pd.Series, digits: int = 2) -> list:
    return [None if pd.isna(value) else round(float(value), digits) for value in series]


def sma(close: pd.Series, window: int) -> pd.Series:
    return close.rolling(window=window, min_periods=window).mean()


def ema(close: pd.Series, span: int) -> pd.Series:
    return close.ewm(span=span, adjust=False, min_periods=span).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    valid = avg_gain.notna() & avg_loss.notna()
    rs = avg_gain / avg_loss
    values = 100 - (100 / (1 + rs))
    values = values.mask(avg_loss == 0, 100.0)
    values = values.mask((avg_gain == 0) & (avg_loss == 0), 50.0)
    return values.where(valid)


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    line = ema(close, fast) - ema(close, slow)
    signal_line = line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return {
        "macd": line,
        "signal": signal_line,
        "histogram": line - signal_line,
    }


def bollinger(close: pd.Series, window: int = 20, num_std: float = 2.0) -> dict:
    middle = sma(close, window)
    deviation = close.rolling(window=window, min_periods=window).std()
    return {
        "middle": middle,
        "upper": middle + deviation * num_std,
        "lower": middle - deviation * num_std,
    }


def compute(df: pd.DataFrame) -> dict:
    """Return chart-ready indicator series for a price frame."""
    if df is None or df.empty or "Close" not in df:
        return {}

    close = df["Close"].astype(float)
    macd_values = macd(close)
    bands = bollinger(close)

    return {
        "labels": [d.strftime("%d %b %y") for d in df.index],
        "sma20": _round_list(sma(close, 20)),
        "sma50": _round_list(sma(close, 50)),
        "ema20": _round_list(ema(close, 20)),
        "bb_upper": _round_list(bands["upper"]),
        "bb_middle": _round_list(bands["middle"]),
        "bb_lower": _round_list(bands["lower"]),
        "rsi": _round_list(rsi(close), 2),
        "macd": _round_list(macd_values["macd"], 4),
        "macd_signal": _round_list(macd_values["signal"], 4),
        "macd_hist": _round_list(macd_values["histogram"], 4),
    }
