"""Daily stock-news service.

Provider chain (keyless by default)
-----------------------------------
1. Yahoo Finance RSS headline feed for the ticker.
2. yfinance's news payload (new ``content`` shape + legacy shape).
3. Google News RSS, filtered to drop quote/history pages.
4. Finnhub company news when ``FINNHUB_API_KEY`` is configured.
5. NewsAPI when ``NEWS_API_KEY`` is configured.

Articles are cached per symbol on disk under ``data/news/`` (atomic writes) and
re-fetched after ``NEWS_TTL_HOURS`` (default 6h). A scheduled
``python manage.py refresh_news`` keeps the cache warm for every cached symbol,
so visitors always see recent, stock-specific headlines.
"""

from __future__ import annotations

import html
import json
import logging
import os
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from xml.etree import ElementTree as ET

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

NEWS_DIR = Path(getattr(settings, "NEWS_DIR", Path(settings.BASE_DIR) / "data" / "news"))
TTL_SECONDS = float(getattr(settings, "NEWS_TTL_HOURS", 6)) * 3600
EMPTY_TTL_SECONDS = 15 * 60
MAX_ARTICLES = 24
REQUEST_TIMEOUT = 8

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; StockSightNews/1.0)",
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}

_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()

# Google News frequently surfaces quote pages such as
# "Apple Inc. (AAPL) Stock Price, News, Quote & History".
_JUNK_MARKERS = (
    "stock price, news, quote",
    "stock price & news",
    "price, news, quote & history",
    "stock quote & history",
    "stock price today stock",
    "quote comparison",
    "stock prices |",
)

# Company names from the bundled universe are tokenised for relevance checks.
_GENERIC_NAME_WORDS = {
    "american", "and", "capital", "class", "co", "common", "companies", "company",
    "corporation", "corp", "depositary", "etf", "financial", "for", "fund", "global",
    "group", "holding", "holdings", "inc", "incorporated", "index", "industries",
    "industry", "international", "limited", "ltd", "market", "markets", "of",
    "ordinary", "plc", "preferred", "services", "shares", "solutions", "stock",
    "stocks", "systems", "the", "trust", "units", "warrant", "warrants",
}

# A few common tickers whose names are missing or abbreviated in the CSV snapshot.
_KNOWN_NAMES = {
    "AAPL": ("apple",),
    "MSFT": ("microsoft",),
    "NVDA": ("nvidia",),
    "TSLA": ("tesla",),
    "GOOGL": ("alphabet", "google"),
    "GOOG": ("alphabet", "google"),
    "AMZN": ("amazon",),
    "META": ("meta", "facebook"),
    "NFLX": ("netflix",),
    "AMD": ("amd", "advanced micro devices"),
    "INTC": ("intel",),
    "JPM": ("jpmorgan", "jp morgan"),
    "BAC": ("bank of america",),
    "V": ("visa",),
    "MA": ("mastercard",),
    "WMT": ("walmart",),
    "DIS": ("disney",),
    "BTC-USD": ("bitcoin", "btc"),
    "ETH-USD": ("ethereum", "eth"),
    "SOL-USD": ("solana",),
    "SPY": ("s&p 500", "sp500", "spy"),
    "QQQ": ("nasdaq 100", "qqq"),
    "DIA": ("dow jones", "dia"),
}

_NAME_CACHE: dict[str, tuple[str, ...]] = {}


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def _clean_key(value: str) -> str:
    return str(value or "").strip().upper()


def _cache_path(key: str) -> Path:
    safe = "".join(c for c in key if c.isalnum() or c in "-._^") or "MARKET"
    return NEWS_DIR / f"{safe}.json"


def _lock_for(key: str) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.Lock())


def _read_cache(key: str) -> dict:
    try:
        payload = json.loads(_cache_path(key).read_text())
        return payload if isinstance(payload, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_cache(key: str, payload: dict) -> None:
    NEWS_DIR.mkdir(parents=True, exist_ok=True)
    path = _cache_path(key)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str))
    os.replace(tmp, path)


def _parse_date(value) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(text)
        except (TypeError, ValueError, OverflowError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _clean_title(title: str, publisher: str = "") -> str:
    text = html.unescape(str(title or ""))
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if publisher:
        suffix = f" - {publisher}"
        if text.lower().endswith(suffix.lower()):
            text = text[: -len(suffix)].strip()
    return text


def _article(title, link, publisher, published) -> dict | None:
    title = _clean_title(title, publisher or "")
    if not title or len(title) < 12:
        return None
    lower = title.lower()
    if any(marker in lower for marker in _JUNK_MARKERS):
        return None
    when = _parse_date(published)
    return {
        "title": title,
        "link": str(link or "#"),
        "publisher": str(publisher or "News").strip(),
        "published": when.strftime("%d %b %Y") if when else "",
        "published_iso": when.isoformat() if when else "",
        "published_ts": when.timestamp() if when else 0,
    }


def _dedupe(articles: list[dict]) -> list[dict]:
    seen: set[str] = set()
    unique: list[dict] = []
    for item in sorted(articles, key=lambda a: a.get("published_ts") or 0, reverse=True):
        key = re.sub(r"[^a-z0-9]+", "", (item.get("title") or "").lower())[:140]
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _relevance_terms(symbol: str) -> tuple[str, ...]:
    """Ticker + distinctive company-name words used to keep headlines on-topic."""
    if symbol in _NAME_CACHE:
        return _NAME_CACHE[symbol]

    terms: set[str] = set(_KNOWN_NAMES.get(symbol, ()))

    name = ""
    try:
        from . import market as market_service

        frame = market_service.get_universe()
        row = frame.loc[frame["Symbol"] == symbol]
        if not row.empty and "Name" in row.columns:
            name = str(row.iloc[0]["Name"] or "")
    except Exception as exc:  # the universe file is optional
        logger.debug("Could not look up company name for %s: %s", symbol, exc)

    cleaned = re.sub(r"\b(common stock|class [a-z]|ordinary shares|american depositary shares|"
                     r"depositary shares|preferred stock)\b", " ", name, flags=re.I)
    for token in re.findall(r"[a-z0-9]+", cleaned.lower()):
        if len(token) >= 3 and token not in _GENERIC_NAME_WORDS:
            terms.add(token)

    base = symbol.lstrip("^")
    variants = {base.lower(), base.lower().replace("-", "."), base.lower().replace(".", "-")}
    short = base.split("-")[0]
    if len(short) >= 3:
        variants.add(short.lower())
    terms.update(v for v in variants if v)

    _NAME_CACHE[symbol] = tuple(sorted(terms))
    return _NAME_CACHE[symbol]


def _is_relevant(article: dict, terms: tuple[str, ...]) -> bool:
    title = (article.get("title") or "").lower()
    if not title:
        return False
    for term in terms:
        if len(term) <= 3:
            if re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", title):
                return True
        elif term in title:
            return True
    return False


def _age_seconds(payload: dict) -> float | None:
    stamp = payload.get("checked_at") or payload.get("fetched_at")
    when = _parse_date(stamp)
    if not when:
        return None
    return (datetime.now(timezone.utc) - when).total_seconds()


def _is_fresh(payload: dict) -> bool:
    if not payload:
        return False
    age = _age_seconds(payload)
    if age is None:
        return False
    ttl = TTL_SECONDS if payload.get("articles") else EMPTY_TTL_SECONDS
    return age < ttl


# --------------------------------------------------------------------------- #
# Providers
# --------------------------------------------------------------------------- #
def _parse_rss(content: bytes, default_publisher: str) -> list[dict]:
    root = ET.fromstring(content)
    articles: list[dict] = []
    for item in root.iter("item"):
        publisher = item.findtext("source") or default_publisher
        article = _article(
            item.findtext("title"),
            item.findtext("link"),
            publisher,
            item.findtext("pubDate"),
        )
        if article:
            articles.append(article)
    return articles


def _fetch_yahoo(symbol: str) -> list[dict]:
    response = requests.get(
        "https://feeds.finance.yahoo.com/rss/2.0/headline",
        params={"s": symbol, "region": "US", "lang": "en-US"},
        headers=HEADERS,
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return _parse_rss(response.content, "Yahoo Finance")


def _fetch_google(symbol: str, market: bool = False) -> list[dict]:
    query = '"stock market" when:2d' if market else f'"{symbol}" stock when:7d'
    response = requests.get(
        "https://news.google.com/rss/search",
        params={"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"},
        headers=HEADERS,
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return _parse_rss(response.content, "Google News")


def _normalise_yfinance_item(item: dict) -> dict | None:
    content = item.get("content") if isinstance(item.get("content"), dict) else {}
    title = content.get("title") or item.get("title")
    publisher = (
        content.get("provider", {}).get("displayName")
        if isinstance(content.get("provider"), dict) else None
    ) or item.get("publisher")
    if isinstance(publisher, dict):
        publisher = publisher.get("title") or publisher.get("name")
    link = (
        content.get("canonicalUrl", {}).get("url")
        if isinstance(content.get("canonicalUrl"), dict) else None
    ) or (
        content.get("clickThroughUrl", {}).get("url")
        if isinstance(content.get("clickThroughUrl"), dict) else None
    ) or item.get("link")
    published = (
        content.get("pubDate")
        or content.get("displayTime")
        or item.get("providerPublishTime")
        or item.get("publishedAt")
    )
    return _article(title, link, publisher or "Yahoo Finance", published)


def _fetch_yfinance(symbol: str) -> list[dict]:
    import yfinance as yf  # imported lazily so pages stay fast when cached

    raw = yf.Ticker(symbol).news or []
    articles = []
    for item in raw:
        if isinstance(item, dict):
            normalised = _normalise_yfinance_item(item)
            if normalised:
                articles.append(normalised)
    return articles


def _fetch_finnhub(symbol: str) -> list[dict]:
    api_key = os.environ.get("FINNHUB_API_KEY", "").strip()
    if not api_key or symbol.startswith("^"):
        return []
    end = date.today()
    start = end - timedelta(days=7)
    response = requests.get(
        "https://finnhub.io/api/v1/company-news",
        params={
            "symbol": symbol,
            "from": start.isoformat(),
            "to": end.isoformat(),
            "token": api_key,
        },
        headers=HEADERS,
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    articles = []
    for item in response.json() or []:
        article = _article(
            item.get("headline"),
            item.get("url"),
            item.get("source") or "Finnhub",
            item.get("datetime"),
        )
        if article:
            articles.append(article)
    return articles


def _fetch_newsapi(symbol: str) -> list[dict]:
    api_key = os.environ.get("NEWS_API_KEY", "").strip()
    if not api_key or symbol.startswith("^"):
        return []
    response = requests.get(
        "https://newsapi.org/v2/everything",
        params={
            "q": f'"{symbol}" stock',
            "language": "en",
            "pageSize": MAX_ARTICLES,
            "sortBy": "publishedAt",
            "apiKey": api_key,
        },
        headers=HEADERS,
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    articles = []
    for item in response.json().get("articles", []) or []:
        source = item.get("source") if isinstance(item.get("source"), dict) else {}
        article = _article(
            item.get("title"),
            item.get("url"),
            source.get("name") or "NewsAPI",
            item.get("publishedAt"),
        )
        if article:
            articles.append(article)
    return articles


def _collect(symbol: str, market: bool = False) -> tuple[list[dict], list[str]]:
    """Fetch every provider concurrently and merge the results."""
    providers = [
        ("yahoo", lambda: _fetch_yahoo(symbol)),
        ("yfinance", lambda: _fetch_yfinance(symbol)),
        ("google", lambda: _fetch_google(symbol, market=market)),
    ]
    if not market:
        providers.extend([
            ("finnhub", lambda: _fetch_finnhub(symbol)),
            ("newsapi", lambda: _fetch_newsapi(symbol)),
        ])

    collected: list[dict] = []
    topical: list[dict] = []
    relevance = () if market else _relevance_terms(symbol)
    sources: list[str] = []
    with ThreadPoolExecutor(max_workers=len(providers)) as pool:
        futures = {pool.submit(fn): name for name, fn in providers}
        try:
            for future in as_completed(futures, timeout=REQUEST_TIMEOUT + 5):
                name = futures[future]
                try:
                    rows = future.result() or []
                except Exception as exc:
                    logger.info("News provider %s failed for %s: %s", name, symbol, exc)
                    continue
                if not rows:
                    continue
                sources.append(name)
                collected.extend(rows)
                if relevance:
                    # Yahoo's ticker feed mixes in general market videos, so
                    # keep only headlines that actually mention this stock.
                    matches = [r for r in rows if _is_relevant(r, relevance)]
                    topical.extend(matches)
                else:
                    topical.extend(rows)
        except TimeoutError:
            logger.info("News fetch timed out for %s", symbol)

    articles = _dedupe(topical)
    if relevance and not articles:
        # For illiquid/obscure tickers, keep something useful rather than an
        # empty panel; the next refresh will pick up any new specific coverage.
        articles = _dedupe(collected)
    return articles[:MAX_ARTICLES], sorted(set(sources))


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def _get(key: str, symbol: str, limit: int, force: bool, market: bool) -> list[dict]:
    payload = _read_cache(key)
    if not force and _is_fresh(payload):
        return payload.get("articles", [])[:limit]

    with _lock_for(key):
        payload = _read_cache(key)
        if not force and _is_fresh(payload):
            return payload.get("articles", [])[:limit]

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            articles, sources = _collect(symbol, market=market)
        except Exception as exc:
            logger.warning("News collection failed for %s: %s", symbol, exc)
            articles, sources = [], []

        if articles:
            payload = {
                "key": key,
                "symbol": symbol,
                "fetched_at": now,
                "checked_at": now,
                "sources": sources,
                "articles": articles,
            }
        else:
            # Keep serving the previous batch (if any) and retry soon.
            payload = {**payload, "checked_at": now}
        try:
            _write_cache(key, payload)
        except OSError as exc:
            logger.warning("Could not cache news for %s: %s", key, exc)
        return payload.get("articles", [])[:limit]


def get_news(symbol: str, limit: int = 6, force: bool = False) -> list[dict]:
    """Return recent, stock-specific headlines for ``symbol``."""
    key = _clean_key(symbol)
    if not key:
        return []
    return _get(key, key, max(1, int(limit)), force=force, market=False)


def get_market_news(limit: int = 6, force: bool = False) -> list[dict]:
    """Return broad stock-market headlines for the empty overview page."""
    return _get("MARKET", "^GSPC", max(1, int(limit)), force=force, market=True)


def refresh_news(symbols, force: bool = False) -> list[dict]:
    """Warm the news cache for a list of tickers; one result row per symbol."""
    rows = []
    for symbol in symbols:
        key = _clean_key(symbol)
        if not key:
            continue
        try:
            articles = get_news(key, limit=MAX_ARTICLES, force=force)
            rows.append({
                "symbol": key,
                "ok": bool(articles),
                "count": len(articles),
                "latest": articles[0]["title"] if articles else None,
            })
        except Exception as exc:
            rows.append({"symbol": key, "ok": False, "count": 0, "error": str(exc)})
    return rows
