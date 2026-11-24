"""Local-first market data repository.

Design goals
------------
* **Runnable from data** - every symbol has a CSV in ``data/market/``. The app
  works from those files with no network access at all.
* **Always up to date** - when a local file is older than the last expected
  trading day, it is incrementally refreshed from yfinance on demand. Refresh
  attempts are rate limited (once per symbol per hour) and writes are atomic,
  so multiple web workers cannot corrupt a file.
* **Offline graceful** - if the network is down, the cached data is still
  served, flagged as ``stale`` in the UI/API.

This module has no Django model dependency and can be used standalone.
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd
from django.conf import settings

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
DATA_DIR = Path(getattr(settings, "MARKET_DATA_DIR", Path(settings.BASE_DIR) / "data" / "market"))
META_FILE = DATA_DIR / "meta.json"
UNIVERSE_CSV = Path(
    getattr(settings, "MARKET_UNIVERSE_CSV", Path(settings.BASE_DIR) / "all_stockss.csv")
)

REQUIRED_COLUMNS = ["Open", "High", "Low", "Close", "Volume"]
DEFAULT_START = date.today() - timedelta(days=365 * 10)
DEFAULT_END = date.today() + timedelta(days=1)
REFRESH_TTL_HOURS = float(getattr(settings, "MARKET_REFRESH_TTL_HOURS", 1))
STALE_AFTER_DAYS = 3  # Fri -> Mon / holidays need a small grace window
NETWORK_TIMEOUT = 20

_LOCAL_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()
_META_GUARD = threading.Lock()


# --------------------------------------------------------------------------- #
# Result container
# --------------------------------------------------------------------------- #
@dataclass
class HistoryResult:
    symbol: str
    df: pd.DataFrame
    source: str = "empty"          # live | cache | legacy | empty
    stale: bool = False
    last_updated: str | None = None
    error: str | None = None
    rows: int = 0

    def __post_init__(self) -> None:
        self.rows = len(self.df)

    def as_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "source": self.source,
            "stale": self.stale,
            "last_updated": self.last_updated,
            "error": self.error,
            "rows": self.rows,
        }


# --------------------------------------------------------------------------- #
# Paths, metadata, locking
# --------------------------------------------------------------------------- #
def normalize_symbol(symbol: str) -> str:
    """Uppercase and trim a ticker, with a few common aliases normalised."""
    clean = str(symbol or "").strip().upper()
    aliases = {
        "BITCOIN": "BTC-USD",
        "BTC": "BTC-USD",
        "APPLE": "AAPL",
        "TESLA": "TSLA",
        "GOOGLE": "GOOGL",
        "MICROSOFT": "MSFT",
    }
    return aliases.get(clean, clean)


def data_path(symbol: str) -> Path:
    # Tickers such as BTC-INR / BRK-B are safe as filenames, but sanitise
    # anything unexpected (e.g. "../") before touching the filesystem.
    safe = "".join(c for c in normalize_symbol(symbol) if c.isalnum() or c in "-._^")
    if not safe:
        raise ValueError("Empty or invalid ticker symbol")
    return DATA_DIR / f"{safe}.csv"


def _read_meta() -> dict:
    try:
        return json.loads(META_FILE.read_text())
    except (OSError, ValueError):
        return {}


def _write_meta(meta: dict) -> None:
    """Atomic metadata write, safe across threads and processes."""
    META_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = META_FILE.with_name(f"{META_FILE.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    with _META_GUARD:
        tmp.write_text(json.dumps(meta, indent=2, default=str))
        os.replace(tmp, META_FILE)


def _thread_lock(symbol: str) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCAL_LOCKS.setdefault(symbol, threading.Lock())


@contextmanager
def _file_lock(symbol: str):
    """Cross-process advisory lock so gunicorn workers don't race on refresh."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = DATA_DIR / f".{normalize_symbol(symbol)}.lock"
    with open(lock_path, "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


# --------------------------------------------------------------------------- #
# Local CSV I/O
# --------------------------------------------------------------------------- #
def _read_csv(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        if df.empty:
            return None
        # Normalise to tz-naive so comparisons with plain dates never fail.
        df.index = pd.to_datetime(df.index).tz_localize(None)
        df.index.name = "Date"
        for col in REQUIRED_COLUMNS:
            if col not in df.columns:
                return None
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df[REQUIRED_COLUMNS].dropna(subset=["Close"])
        return df.sort_index()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Could not read %s: %s", path, exc)
        return None


def load_local(symbol: str) -> pd.DataFrame | None:
    return _read_csv(data_path(symbol))


def save_local(symbol: str, df: pd.DataFrame) -> Path:
    """Atomically persist a clean OHLCV frame and update its metadata."""
    path = data_path(symbol)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    clean = df[REQUIRED_COLUMNS].sort_index()
    clean.index.name = "Date"
    tmp = path.with_suffix(".csv.tmp")
    clean.to_csv(tmp)
    os.replace(tmp, path)

    meta = _read_meta()
    meta[normalize_symbol(symbol)] = {
        "rows": len(clean),
        "last_date": str(clean.index[-1].date()),
        "first_date": str(clean.index[0].date()),
        "last_success": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    _write_meta(meta)
    return path


# --------------------------------------------------------------------------- #
# Remote fetch (yfinance) - only called when needed
# --------------------------------------------------------------------------- #
def fetch_remote(
    symbol: str,
    start: date | str | None = None,
    end: date | str | None = None,
    attempts: int = 2,
) -> pd.DataFrame:
    """Fetch daily OHLCV from yfinance. MultiIndex columns are flattened."""
    import yfinance as yf  # imported lazily to keep startup fast / tests offline

    symbol = normalize_symbol(symbol)
    start = str(start or DEFAULT_START)
    end = str(end or DEFAULT_END)

    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            raw = yf.Ticker(symbol).history(
                start=start,
                end=end,
                actions=False,
                auto_adjust=False,
                timeout=NETWORK_TIMEOUT,
            )
            if raw is None or raw.empty:
                raise ValueError(f"No remote rows returned for {symbol}")
            if isinstance(raw.columns, pd.MultiIndex):
                raw.columns = raw.columns.get_level_values(0)
            raw = raw.rename(columns=str.capitalize)
            missing = set(REQUIRED_COLUMNS) - set(raw.columns)
            if missing:
                raise ValueError(f"Remote data missing columns: {sorted(missing)}")
            raw.index = pd.to_datetime(raw.index).tz_localize(None)
            raw.index.name = "Date"
            return raw[REQUIRED_COLUMNS].dropna(subset=["Close"]).sort_index()
        except Exception as exc:
            last_error = exc
            logger.warning("Remote fetch %s failed (attempt %s): %s", symbol, attempt + 1, exc)
            if attempt + 1 < attempts:
                time.sleep(0.75 * (attempt + 1))
    raise ConnectionError(f"Could not fetch {symbol}: {last_error}") from last_error


def _merge_frames(local: pd.DataFrame | None, remote: pd.DataFrame) -> pd.DataFrame:
    if local is None or local.empty:
        return remote
    merged = pd.concat([local, remote])
    merged = merged[~merged.index.duplicated(keep="last")].sort_index()
    return merged


def _should_refresh(symbol: str, local: pd.DataFrame | None, force: bool) -> bool:
    if force or local is None or local.empty:
        return True
    meta = _read_meta().get(symbol, {})
    last_attempt = meta.get("last_attempt")
    if last_attempt:
        try:
            elapsed = datetime.now(timezone.utc) - datetime.fromisoformat(last_attempt)
            if elapsed.total_seconds() < REFRESH_TTL_HOURS * 3600:
                return False
        except ValueError:
            pass
    last_date = local.index[-1].date()
    expected = datetime.now(timezone.utc).date() - timedelta(days=STALE_AFTER_DAYS)
    return last_date < expected


def _mark_attempt(symbol: str) -> None:
    meta = _read_meta()
    entry = meta.setdefault(symbol, {})
    entry["last_attempt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _write_meta(meta)


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def get_history(
    symbol: str,
    start: date | str | None = None,
    end: date | str | None = None,
    refresh: str = "auto",       # auto | force | never
) -> HistoryResult:
    """Return OHLCV history, preferring local data and refreshing when stale.

    ``refresh='never'`` guarantees zero network calls - useful for tests and
    for serving a page while the data provider is down.
    """
    symbol = normalize_symbol(symbol)
    if not symbol:
        return HistoryResult(symbol, pd.DataFrame(), error="No symbol supplied")

    path = data_path(symbol)
    with _thread_lock(symbol), _file_lock(symbol):
        local = load_local(symbol)
        source = "cache" if local is not None else "empty"
        error: str | None = None
        last_updated = (_read_meta().get(symbol, {}).get("last_success") or
                        (datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
                         if path.exists() else None))

        if refresh != "never" and (refresh == "force" or _should_refresh(symbol, local, False)):
            _mark_attempt(symbol)
            try:
                fetch_start = local.index[-1].date() - timedelta(days=7) if local is not None else start
                remote = fetch_remote(symbol, start=fetch_start, end=end)
                local = _merge_frames(local, remote)
                save_local(symbol, local)
                source = "live"
                last_updated = _read_meta().get(symbol, {}).get("last_success")
            except Exception as exc:
                error = str(exc)
                logger.info("Serving cached data for %s (%s)", symbol, error)

        if local is None or local.empty:
            # Last resort: the legacy bundled sample (AAPL 2021) for offline demos.
            legacy = Path(getattr(settings, "BASE_DIR", ".")) / "data.csv"
            if symbol in {"AAPL", "BTC-INR"} and legacy.exists():
                try:
                    legacy_df = _read_csv(legacy)
                    if legacy_df is not None:
                        local = legacy_df
                        source = "legacy"
                        error = error or "Using bundled sample data (offline)"
                except Exception:
                    pass

        if local is None or local.empty:
            return HistoryResult(symbol, pd.DataFrame(), source="empty", error=error or "No data")

        if start:
            local = local[local.index >= pd.Timestamp(start)]
        if end:
            local = local[local.index <= pd.Timestamp(end)]

        stale = local.index[-1].date() < (
            datetime.now(timezone.utc).date() - timedelta(days=STALE_AFTER_DAYS)
        )
        return HistoryResult(symbol, local, source=source, stale=stale,
                             last_updated=last_updated, error=error)


def get_quote(symbol: str, refresh: str = "auto") -> dict:
    """Latest quote with day-over-day change, plus freshness metadata."""
    result = get_history(symbol, refresh=refresh)
    if result.df.empty:
        return {"symbol": normalize_symbol(symbol), "error": result.error or "No data", **result.as_dict()}
    df = result.df
    last = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else last
    change = float(last["Close"] - prev["Close"])
    change_pct = float(change / prev["Close"] * 100) if prev["Close"] else 0.0
    return {
        "symbol": normalize_symbol(symbol),
        "date": df.index[-1].strftime("%d %b %Y"),
        "open": round(float(last["Open"]), 2),
        "high": round(float(last["High"]), 2),
        "low": round(float(last["Low"]), 2),
        "close": round(float(last["Close"]), 2),
        "volume": int(last["Volume"]),
        "change": round(change, 2),
        "change_pct": round(change_pct, 2),
        **result.as_dict(),
    }


def refresh_symbols(symbols: Iterable[str], force: bool = False) -> list[dict]:
    """Refresh a list of tickers and return one summary row per symbol."""
    summary = []
    for symbol in symbols:
        symbol = normalize_symbol(symbol)
        try:
            result = get_history(symbol, refresh="force" if force else "auto")
            summary.append({
                "symbol": symbol,
                "ok": not result.df.empty,
                "rows": result.rows,
                "source": result.source,
                "last_date": result.df.index[-1].strftime("%Y-%m-%d") if result.rows else None,
                "error": result.error,
            })
        except Exception as exc:
            summary.append({"symbol": symbol, "ok": False, "error": str(exc)})
    return summary


def status() -> dict:
    """Freshness overview for the health page / API."""
    meta = _read_meta()
    files = sorted(DATA_DIR.glob("*.csv")) if DATA_DIR.exists() else []
    symbols = []
    for path in files:
        info = meta.get(path.stem, {})
        df = _read_csv(path)
        symbols.append({
            "symbol": path.stem,
            "rows": len(df) if df is not None else 0,
            "last_date": str(df.index[-1].date()) if df is not None else None,
            "last_success": info.get("last_success"),
            "stale": bool(df is not None and df.index[-1].date() <
                          datetime.now(timezone.utc).date() - timedelta(days=STALE_AFTER_DAYS)),
        })
    return {
        "data_dir": str(DATA_DIR),
        "symbol_count": len(symbols),
        "symbols": symbols,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def seed_from_csv(csv_path: str | Path, symbol: str) -> int:
    """Import a user supplied OHLCV CSV into the local cache (offline seeding)."""
    df = _read_csv(Path(csv_path))
    if df is None:
        raise ValueError(f"Could not parse {csv_path}")
    save_local(symbol, df)
    return len(df)
