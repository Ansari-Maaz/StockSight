"""Stock universe and screener helpers.

The bundled ``all_stockss.csv`` snapshot is used as an offline fallback, while
live quotes are pulled through the local-first data repository (small thread
pool so a page load stays responsive).
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
from django.conf import settings
from django.core.paginator import Paginator

from . import data as data_service

logger = logging.getLogger(__name__)
_UNIVERSE: pd.DataFrame | None = None


def get_universe() -> pd.DataFrame:
    """Load the symbol universe (cached in memory for the process lifetime)."""
    global _UNIVERSE
    if _UNIVERSE is not None:
        return _UNIVERSE
    paths = [
        Path(getattr(settings, "MARKET_UNIVERSE_CSV", Path(settings.BASE_DIR) / "all_stockss.csv")),
        Path(settings.BASE_DIR) / "data" / "universe.csv",
    ]
    for path in paths:
        if path.exists():
            try:
                frame = pd.read_csv(path)
                frame.columns = [str(c).strip() for c in frame.columns]
                if "Symbol" in frame.columns:
                    frame["Symbol"] = frame["Symbol"].astype(str).str.strip().str.upper()
                    _UNIVERSE = frame.dropna(subset=["Symbol"]).reset_index(drop=True)
                    return _UNIVERSE
            except Exception as exc:
                logger.warning("Could not load universe %s: %s", path, exc)
    _UNIVERSE = pd.DataFrame(columns=["Symbol", "Name", "Country", "Industry"])
    return _UNIVERSE


def search_universe(query: str, limit: int = 8) -> list[dict]:
    frame = get_universe()
    q = str(query or "").strip().upper()
    if not q:
        return []
    mask = frame["Symbol"].str.contains(q, na=False) | frame.get(
        "Name", pd.Series("", index=frame.index)
    ).astype(str).str.upper().str.contains(q, na=False)
    return frame.loc[mask].head(limit)[["Symbol", "Name"]].to_dict("records")


def _snapshot_row(symbol: str) -> dict:
    frame = get_universe()
    row = frame.loc[frame["Symbol"] == symbol]
    if row.empty:
        return {"symbol": symbol, "name": symbol, "country": "", "industry": ""}
    r = row.iloc[0]

    def val(key: str, default=""):
        return r[key] if key in r and pd.notna(r[key]) else default

    def numeric(key: str):
        text = str(val(key, "")).replace("$", "").replace("%", "").replace(",", "").strip()
        return text

    return {
        "symbol": symbol,
        "name": val("Name", symbol),
        "country": val("Country", ""),
        "industry": val("Industry", val("Sector", "")),
        "snapshot_close": numeric("Last Sale"),
        "snapshot_change": numeric("Net Change"),
        "snapshot_change_pct": numeric("% Change"),
    }


def screener(page: int = 1, per_page: int = 10, search: str = "") -> dict:
    frame = get_universe()
    if search:
        q = search.strip().upper()
        mask = frame["Symbol"].str.contains(q, na=False) | frame.get(
            "Name", pd.Series("", index=frame.index)
        ).astype(str).str.upper().str.contains(q, na=False)
        frame = frame.loc[mask]

    paginator = Paginator(frame.reset_index(drop=True), per_page)
    page_obj = paginator.get_page(page)
    symbols = page_obj.object_list["Symbol"].tolist()

    quotes: dict[str, dict] = {}
    # Only symbols we already cache are auto-refreshed. Obscure universe entries
    # keep their bundled snapshot until someone explicitly opens their detail page.
    def quote_for(symbol: str) -> dict:
        cached = data_service.load_local(symbol) is not None
        return data_service.get_quote(symbol, refresh="auto" if cached else "never")

    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(quote_for, s): s for s in symbols}
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                quotes[symbol] = future.result()
            except Exception as exc:
                logger.warning("Quote failed for %s: %s", symbol, exc)

    rows = []
    for symbol in symbols:
        quote = quotes.get(symbol, {})
        snapshot = _snapshot_row(symbol)
        rows.append({
            **snapshot,
            "close": quote.get("close", snapshot.get("snapshot_close", "—")),
            "change": quote.get("change", snapshot.get("snapshot_change", "—")),
            "change_pct": quote.get("change_pct", snapshot.get("snapshot_change_pct", "—")),
            "date": quote.get("date", "snapshot"),
            "stale": quote.get("stale", True),
            "live": bool(quote.get("rows")),
        })

    return {
        "rows": rows,
        "page_obj": page_obj,
        "total": paginator.count,
        "search": search,
    }
