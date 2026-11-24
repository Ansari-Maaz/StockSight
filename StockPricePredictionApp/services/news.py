"""Headline service with no hard-coded API keys and graceful offline fallback."""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_CACHE: dict[str, tuple[float, list[dict]]] = {}
_TTL_SECONDS = 15 * 60
_GUARD = threading.Lock()


def _normalise(item: dict) -> dict | None:
    title = item.get("title") or ""
    if not title:
        return None
    published = item.get("providerPublishTime") or item.get("publishedAt")
    when = ""
    if published:
        try:
            when = datetime.fromtimestamp(float(published), timezone.utc).strftime("%d %b %Y")
        except (ValueError, OSError, TypeError):
            when = str(published)[:10]
    return {
        "title": title,
        "link": item.get("link") or item.get("url") or "#",
        "publisher": (item.get("publisher") or {}).get("title", "") if isinstance(item.get("publisher"), dict)
                     else item.get("source", {}).get("name", "") if isinstance(item.get("source"), dict) else "",
        "published": when,
    }


def get_news(symbol: str, limit: int = 5) -> list[dict]:
    """Return recent headlines for a ticker (yfinance, optional NewsAPI)."""
    symbol = str(symbol or "").strip().upper()
    now = time.time()
    with _GUARD:
        cached = _CACHE.get(symbol)
        if cached and now - cached[0] < _TTL_SECONDS:
            return cached[1][:limit]

    articles: list[dict] = []
    try:
        import yfinance as yf
        raw = yf.Ticker(symbol).news or []
        for item in raw:
            normalised = _normalise(item)
            if normalised:
                articles.append(normalised)
    except Exception as exc:
        logger.info("yfinance news unavailable for %s: %s", symbol, exc)

    api_key = os.environ.get("NEWS_API_KEY", "").strip()
    if api_key and not articles:
        try:
            import requests
            response = requests.get(
                "https://newsapi.org/v2/everything",
                params={"q": symbol, "pageSize": limit, "sortBy": "publishedAt",
                        "apiKey": api_key},
                timeout=10,
            )
            response.raise_for_status()
            for item in response.json().get("articles", []):
                normalised = _normalise(item)
                if normalised:
                    articles.append(normalised)
        except Exception as exc:
            logger.info("NewsAPI unavailable for %s: %s", symbol, exc)

    with _GUARD:
        _CACHE[symbol] = (now, articles)
    return articles[:limit]
