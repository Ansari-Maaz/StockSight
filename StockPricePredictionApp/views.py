"""Thin views: all market / ML work is delegated to ``services``."""

from __future__ import annotations

import csv
import json
import logging
from datetime import date, timedelta

import pandas as pd
from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .services import data as data_service
from .services import indicators as indicator_service
from .services import market as market_service
from .services import news as news_service
from .services import predictor
from .services import sentiment as sentiment_service

logger = logging.getLogger(__name__)

DEFAULT_SYMBOL = "AAPL"
WATCHLIST = ["AAPL", "MSFT", "NVDA", "TSLA", "GOOGL", "AMZN", "META", "BTC-USD"]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _series(df: pd.DataFrame) -> dict:
    """Compact, JSON-friendly OHLCV series for the chart layer."""
    return {
        "labels": [d.strftime("%d %b %y") for d in df.index],
        "open": [round(float(v), 2) for v in df["Open"]],
        "high": [round(float(v), 2) for v in df["High"]],
        "low": [round(float(v), 2) for v in df["Low"]],
        "close": [round(float(v), 2) for v in df["Close"]],
        "volume": [int(v) for v in df["Volume"]],
    }


def _stats(df: pd.DataFrame, quote: dict) -> dict:
    if df.empty:
        return {}
    high = float(df["High"].max())
    low = float(df["Low"].min())
    first, last = float(df["Close"].iloc[0]), float(df["Close"].iloc[-1])
    return {
        "high": round(high, 2),
        "low": round(low, 2),
        "first": round(first, 2),
        "last": round(last, 2),
        "change": round(last - first, 2),
        "change_pct": round((last - first) / first * 100, 2) if first else 0,
        "avg_volume": int(df["Volume"].mean()),
        "sessions": len(df),
        "from_date": df.index[0].strftime("%d %b %Y"),
        "to_date": df.index[-1].strftime("%d %b %Y"),
        "day_change": quote.get("change", 0),
        "day_change_pct": quote.get("change_pct", 0),
    }


def _company_info(symbol: str) -> dict:
    try:
        import yfinance as yf
        info = yf.Ticker(symbol).info or {}
        keys = ["longName", "shortName", "sector", "industry", "country",
                "currency", "exchange", "marketCap", "website", "summary"]
        return {k: info.get(k) for k in keys if info.get(k) not in (None, "", "None")}
    except Exception as exc:
        logger.info("Company info unavailable for %s: %s", symbol, exc)
        return {}


def _json_body(request) -> dict:
    try:
        return json.loads(request.body or "{}")
    except (ValueError, UnicodeDecodeError):
        return {}


# --------------------------------------------------------------------------- #
# Pages
# --------------------------------------------------------------------------- #
def landing(request):
    """Public marketing page - no account, no network calls."""
    status = data_service.status()
    quotes = []
    for symbol in WATCHLIST:
        quote = data_service.get_quote(symbol, refresh="never")
        if quote.get("close") is not None and not quote.get("error"):
            quotes.append(quote)

    newest = max((s["last_date"] for s in status["symbols"] if s["last_date"]), default=None)
    if newest:
        try:
            newest = date.fromisoformat(newest).strftime("%d %b %Y")
        except ValueError:
            pass

    return render(request, "landing.html", {
        "app_name": getattr(settings, "APP_NAME", "StockSight"),
        "symbol_count": status["symbol_count"],
        "data_through": newest or "—",
        "ticker": quotes,
        "hero_quote": quotes[0] if quotes else {},
        "year": date.today().year,
    })


def home(request):
    raw_symbol = request.POST.get("company1") or request.GET.get("symbol") or ""
    symbol = data_service.normalize_symbol(raw_symbol) if str(raw_symbol).strip() else ""
    start = request.GET.get("start") or request.POST.get("start_date")
    end = request.GET.get("end") or request.POST.get("close_date")

    if symbol:
        history = data_service.get_history(symbol, start=start, end=end)
        df = history.df
        quote = data_service.get_quote(symbol, refresh="never") if not df.empty else {}
        if df.empty:
            quote = {"symbol": symbol, **history.as_dict()}
        series = _series(df.tail(252)) if not df.empty else _series(pd.DataFrame(
            columns=data_service.REQUIRED_COLUMNS, index=pd.DatetimeIndex([])
        ))
        indicators = indicator_service.compute(df.tail(252)) if not df.empty else {}
        news = news_service.get_news(symbol) if not df.empty else []
        suggestions = [{**s, "label": s["Symbol"]} for s in market_service.search_universe(symbol)]
        has_data = not df.empty
        error = history.error if not has_data else None
    else:
        history = data_service.HistoryResult("", pd.DataFrame(), source="empty")
        df = history.df
        quote, series, news, suggestions = {}, _series(pd.DataFrame(
            columns=data_service.REQUIRED_COLUMNS, index=pd.DatetimeIndex([]))), [], []
        indicators = {}
        has_data, error = False, None

    context = {
        "nav_active": "home",
        "symbol": symbol,
        "company": symbol,
        "series": series,
        "indicators": indicators,
        "stats": _stats(df, quote) if has_data else {},
        "quote": quote,
        "news": news,
        "news_pulse": sentiment_service.score(news),
        "market_news": news_service.get_market_news() if not symbol else [],
        "history": history.as_dict(),
        "has_data": has_data,
        "error": error,
        "suggestions": suggestions,
        "watchlist": WATCHLIST,
        "start": start or "",
        "end": end or "",
    }
    return render(request, "home.html", context)


def compare(request):
    raw1 = request.POST.get("company1") or request.GET.get("a") or ""
    raw2 = request.POST.get("company2") or request.GET.get("b") or ""
    symbol1 = data_service.normalize_symbol(raw1) if str(raw1).strip() else ""
    symbol2 = data_service.normalize_symbol(raw2) if str(raw2).strip() else ""
    has_selection = bool(symbol1 and symbol2)

    start = request.POST.get("start_date") or request.GET.get("start") or (
        date.today() - timedelta(days=365 * 2)
    ).strftime("%Y-%m-%d")
    end = request.POST.get("close_date") or request.GET.get("end") or date.today().strftime("%Y-%m-%d")

    if has_selection:
        h1 = data_service.get_history(symbol1, start=start, end=end)
        h2 = data_service.get_history(symbol2, start=start, end=end)
        df1, df2 = h1.df, h2.df
    else:
        h1 = h2 = None
        df1 = df2 = pd.DataFrame(columns=data_service.REQUIRED_COLUMNS)

    if not df1.empty and not df2.empty:
        common = df1.index.intersection(df2.index)
        a, b = df1.loc[common], df2.loc[common]
        series = {
            "labels": [d.strftime("%d %b %y") for d in common],
            "close1": [round(float(v), 2) for v in a["Close"]],
            "close2": [round(float(v), 2) for v in b["Close"]],
            "normalised1": [round(float(v / a["Close"].iloc[0] * 100), 2) for v in a["Close"]],
            "normalised2": [round(float(v / b["Close"].iloc[0] * 100), 2) for v in b["Close"]],
        }
    else:
        common = pd.DatetimeIndex([])
        a = df1 if not df1.empty else pd.DataFrame(columns=data_service.REQUIRED_COLUMNS)
        b = df2 if not df2.empty else pd.DataFrame(columns=data_service.REQUIRED_COLUMNS)
        series = {"labels": [], "close1": [], "close2": [], "normalised1": [], "normalised2": []}

    q1 = data_service.get_quote(symbol1, refresh="never") if not a.empty else {}
    q2 = data_service.get_quote(symbol2, refresh="never") if not b.empty else {}
    has_data = has_selection and not a.empty and not b.empty
    news1 = news_service.get_news(symbol1) if not a.empty else []
    news2 = news_service.get_news(symbol2) if not b.empty else []
    context = {
        "nav_active": "compare",
        "symbol1": symbol1, "symbol2": symbol2,
        "has_selection": has_selection,
        "start": start, "end": end,
        "series": series,
        "stats1": _stats(a, q1), "stats2": _stats(b, q2),
        "quote1": q1, "quote2": q2,
        "news1": news1, "news2": news2,
        "pulse1": sentiment_service.score(news1),
        "pulse2": sentiment_service.score(news2),
        "history": [h1.as_dict(), h2.as_dict()] if has_selection else [],
        "has_data": has_data,
        "error": (h1.error if df1.empty else h2.error) if has_selection and (df1.empty or df2.empty) else None,
    }
    return render(request, "compare.html", context)


def predict_view(request):
    """Forecast page. Training only happens on POST so GET stays instant."""
    symbol = ""
    days = 7
    result = None
    error = None
    if request.method == "POST":
        raw_symbol = request.POST.get("company1") or ""
        symbol = data_service.normalize_symbol(raw_symbol) if str(raw_symbol).strip() else ""
        try:
            days = int(request.POST.get("days") or 7)
        except (TypeError, ValueError):
            days = 7
        if not symbol:
            error = "Enter a stock symbol to run a forecast."
        else:
            try:
                result = predictor.predict(symbol, days=days).as_dict()
                projections = result.get("predictions") or []
                if projections:
                    closes = result.get("history_close") or []
                    base = closes[-1] if closes else projections[0]
                    if base:
                        result["projected_change_pct"] = round(
                            (projections[-1] / base - 1) * 100, 2)
                        result["projected_low"] = round(min(projections), 2)
                        result["projected_high"] = round(max(projections), 2)
                        result["projected_last"] = round(projections[-1], 2)
            except Exception as exc:
                logger.exception("Prediction failed for %s", symbol)
                error = str(exc)

    cached = []
    for path in predictor.MODEL_DIR.glob("*.meta.json") if predictor.MODEL_DIR.exists() else []:
        try:
            meta = json.loads(path.read_text())
            cached.append({
                "symbol": meta.get("symbol"),
                "backend": meta.get("backend"),
                "trained_at": (meta.get("trained_at") or "")[:16].replace("T", " "),
            })
        except Exception:
            pass

    return render(request, "predict.html", {
        "nav_active": "predict",
        "symbol": symbol,
        "days": days,
        "result": result,
        "has_result": result is not None,
        "error": error,
        "cached_models": sorted(cached, key=lambda r: r["symbol"] or ""),
        "max_days": 90,
    })


def all_stocks(request):
    search = request.GET.get("search") or request.POST.get("search") or ""
    try:
        page = int(request.GET.get("page") or 1)
    except ValueError:
        page = 1
    screener = market_service.screener(page=page, per_page=10, search=search)
    return render(request, "stocks.html", {
        "nav_active": "stocks",
        **screener,
    })


def _symbol_options() -> list[str]:
    """Cached symbols, used to populate browser-side datalists."""
    return [row["symbol"] for row in data_service.status()["symbols"]]


def portfolio(request):
    """Client-side portfolio and watchlist — nothing is sent to the server."""
    return render(request, "portfolio.html", {
        "nav_active": "portfolio",
        "watchlist": WATCHLIST,
        "symbol_options": _symbol_options(),
    })


def alerts(request):
    """Client-side price/forecast alerts with browser notifications."""
    return render(request, "alerts.html", {
        "nav_active": "alerts",
        "watchlist": WATCHLIST,
        "symbol_options": _symbol_options(),
    })


def details(request, id):
    symbol = data_service.normalize_symbol(id)
    history = data_service.get_history(symbol)
    df = history.df
    quote = data_service.get_quote(symbol, refresh="never") if not df.empty else {}
    info = _company_info(symbol) if not df.empty else {}
    news = news_service.get_news(symbol) if not df.empty else []
    chart_df = df.tail(500) if not df.empty else df
    return render(request, "details.html", {
        "nav_active": "stocks",
        "symbol": symbol,
        "company": info.get("longName") or info.get("shortName") or symbol,
        "info": info,
        "series": _series(chart_df) if not chart_df.empty else {"labels": [], "close": [], "volume": []},
        "indicators": indicator_service.compute(chart_df) if not chart_df.empty else {},
        "stats": _stats(df, quote) if not df.empty else {},
        "quote": quote,
        "news": news,
        "news_pulse": sentiment_service.score(news),
        "history": history.as_dict(),
        "has_data": not df.empty,
        "error": history.error if df.empty else None,
    })


def download(request, id):
    """CSV export: history (0/1/2), predictions (3), or screener (4)."""
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="stocksight_export.csv"'
    writer = csv.writer(response)
    symbol = data_service.normalize_symbol(request.GET.get("symbol") or DEFAULT_SYMBOL)

    if id in {"0", "1", "2", "history"}:
        history = data_service.get_history(symbol, refresh="never")
        writer.writerow(["Date", "Open", "High", "Low", "Close", "Volume"])
        for timestamp, row in history.df.iterrows():
            writer.writerow([timestamp.strftime("%Y-%m-%d")] +
                            [round(float(row[c]), 4) for c in data_service.REQUIRED_COLUMNS])
    elif id in {"3", "prediction"}:
        days = int(request.GET.get("days") or 7)
        try:
            result = predictor.predict(symbol, days=days, refresh_data=False)
        except Exception as exc:
            writer.writerow(["error", str(exc)])
        else:
            writer.writerow(["Date", "Prediction"])
            writer.writerows(zip(result.dates, [round(p, 2) for p in result.predictions]))
    else:
        screener = market_service.screener(page=1, per_page=500)
        writer.writerow(["Symbol", "Name", "Close", "Change", "% Change", "Country", "Industry", "Date"])
        for row in screener["rows"]:
            writer.writerow([row["symbol"], row["name"], row["close"], row["change"],
                             row["change_pct"], row["country"], row["industry"], row["date"]])
    return response


# --------------------------------------------------------------------------- #
# JSON API
# --------------------------------------------------------------------------- #
@require_GET
def api_history(request):
    refresh = request.GET.get("refresh")
    if refresh not in {"auto", "force", "never"}:
        refresh = "auto"
    symbol = data_service.normalize_symbol(request.GET.get("symbol") or DEFAULT_SYMBOL)
    history = data_service.get_history(
        symbol, start=request.GET.get("start"), end=request.GET.get("end"), refresh=refresh
    )
    return JsonResponse({
        **history.as_dict(),
        "series": _series(history.df) if not history.df.empty else None,
    })


@require_GET
def api_quote(request):
    refresh = request.GET.get("refresh")
    if refresh not in {"auto", "force", "never"}:
        refresh = "auto"
    symbol = data_service.normalize_symbol(request.GET.get("symbol") or DEFAULT_SYMBOL)
    return JsonResponse(data_service.get_quote(symbol, refresh=refresh))


@require_GET
def api_quotes(request):
    """Batch quotes for local-only portfolio/watchlist/alerts pages."""
    raw = request.GET.get("symbols") or ""
    symbols = [data_service.normalize_symbol(part) for part in raw.split(",") if part.strip()][:50]
    return JsonResponse({
        "quotes": [data_service.get_quote(symbol, refresh="never") for symbol in symbols if symbol]
    })


@csrf_exempt
@require_POST
def api_predict(request):
    body = _json_body(request)
    try:
        result = predictor.predict(
            body.get("symbol") or DEFAULT_SYMBOL,
            days=int(body.get("days") or 7),
            backend=body.get("backend") or "auto",
        ).as_dict()
        return JsonResponse({"ok": True, "result": result})
    except Exception as exc:
        logger.exception("API prediction failed")
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)


@require_GET
def api_search(request):
    return JsonResponse({"results": market_service.search_universe(request.GET.get("q", ""))})


@require_GET
def api_health(request):
    return JsonResponse(data_service.status())


@csrf_exempt
@require_POST
def api_refresh(request):
    body = _json_body(request)
    symbols = body.get("symbols") or [s["symbol"] for s in data_service.status()["symbols"]]
    return JsonResponse({"results": data_service.refresh_symbols(symbols, force=bool(body.get("force")))})


def api_docs(request):
    return render(request, "api.html", {"nav_active": "api"})
