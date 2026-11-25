# StockSight

A production-ready stock analytics and forecasting dashboard built with **Django 5**, **yfinance**, **pandas**, and a **TensorFlow LSTM** (with automatic CPU fallbacks). It runs entirely from a local market-data cache, keeps that cache up to date automatically, and works offline when the data provider is unavailable.

> The old version depended on hard-coded credentials, hard-coded date ranges, global in-memory DataFrames, and retrained a model on **every** request. This version removes all of that.

---

## Features

| Feature | Details |
|---|---|
| **Local-first data** | One CSV per ticker in `data/market/`. Pages work with zero network access. |
| **Always up to date** | Stale symbols are incrementally refreshed from yfinance as soon as a new trading session is expected, plus `refresh_data` for cron/Celery/Docker. |
| **Daily stock news** | Yahoo Finance RSS + Google News RSS + yfinance, deduplicated and cached per symbol; optional Finnhub/NewsAPI keys. Shown on the overview, details and compare pages. |
| **Forecasting** | LSTM → scikit-learn Gradient Boosting → NumPy regression, automatic fallback chain. Models are trained **from your data**, cached by fingerprint, and reused. |
| **Honest metrics** | RMSE, MAE, MAPE, directional accuracy and a naive-baseline comparison on a chronological holdout. |
| **No secret keys required** | All core features work without API keys; Finnhub/NewsAPI are optional upgrades. |
| **Modern UI** | Animated public landing page at `/`, plus a responsive dashboard at `/dashboard/` with **light/dark theme toggle** (persisted in `localStorage`), a **collapsible sidebar**, locally bundled Plus Jakarta Sans + JetBrains Mono fonts, indigo/violet palette, semantic colour coding, and Chart.js charts that re-theme with the active mode (vendored locally). No CDN dependency at runtime. |
| **Local workspace** | Browser-only portfolio with P&L, a persistent watchlist and price/forecast alerts. No account or server-side user state. Includes a `Ctrl/⌘K` command palette, an installable PWA with an offline shell, SEO files and branded error pages. |
| **JSON API** | `/api/history/`, `/api/quote/`, `/api/quotes/`, `/api/predict/`, `/api/search/`, `/api/health/`, `/api/refresh/`. |
| **Production bits** | Env-driven settings, security headers, gunicorn, Dockerfile + compose, cron example, logging, tests. |

---

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate

# 1. Import market history into the local cache (one-time, ~10 years)
python manage.py seed_data

# 2. Train a model for a symbol (optional — predict page trains on first use)
python manage.py train_model AAPL

# 3. Run
python manage.py runserver
```

Open <http://127.0.0.1:8000/> for the landing page, or <http://127.0.0.1:8000/dashboard/> to go straight to the dashboard. No API keys, no external services, no manual CSV placement.

**Already have data?** Import it offline:

```bash
python manage.py seed_data --from-csv data.csv --symbol AAPL
python manage.py seed_data --symbol AAPL --offline   # show cache status without network
```

---

## How "always up to date" works

1. `services/data.py:get_history()` reads `data/market/<SYMBOL>.csv`.
2. If the last row is older than the most recent expected US trading session (weekends and pre-close hours handled automatically), it fetches only the missing tail from yfinance, merges, and atomically replaces the file.
3. Attempts are throttled via `data/market/meta.json` (`MARKET_REFRESH_TTL_HOURS`, default 1). Concurrent requests are serialized with a per-symbol file lock, so gunicorn workers are safe.
4. If the network fails, the cached file is still served and flagged `stale` in the UI/API — the app never hard-fails because a provider is down.
5. On every page view the cache is checked again, so a deployment used months later automatically pulls the current data instead of showing a frozen snapshot.

Keep a long-running deployment current with **any** of:

```bash
# Cron (see crontab.example)
30 18 * * 1-5 cd /app && .venv/bin/python manage.py refresh_data

# Docker Compose includes a "refresher" service that runs this hourly

# Or hit POST /api/refresh/ from the dashboard's "Refresh" button
```

To add more tickers, just request them in the UI or run `python manage.py seed_data NVDA AMD ...`. The bundled `all_stockss.csv` (~8,200 symbols) is used as an offline screener fallback; its values are a snapshot, and live quotes replace them as soon as data is cached.

---

## Daily news pipeline

`services/news.py` merges several providers so the news panels never depend on a single feed:

1. **Yahoo Finance RSS** headline feed for the ticker (keyless).
2. **yfinance** news payload (new `content` shape and legacy shape).
3. **Google News RSS** fallback, with quote/history pages filtered out.
4. **Finnhub** company news when `FINNHUB_API_KEY` is set.
5. **NewsAPI** when `NEWS_API_KEY` is set.

Articles are normalized, deduplicated by title, sorted by publication time and cached atomically in `data/news/<SYMBOL>.json`. The cache is refreshed after `NEWS_TTL_HOURS` (default 6), and `refresh_data` also refreshes news by default:

```bash
python manage.py refresh_news                       # every cached symbol
python manage.py refresh_news AAPL MSFT --force     # specific tickers
python manage.py refresh_news --market              # broad market headlines
```

The overview, details and compare pages all read from this cache, so every visitor sees the same recent stock-specific headlines.

---

## Forecasting pipeline

`services/predictor.py` is independent of Django views:

1. Load OHLCV for the symbol (auto-refreshing if needed).
2. Scale closing prices to `[0, 1]`, build 60-day sliding windows.
3. Chronological 90/10 train/validation split (no look-ahead leakage).
4. Train an LSTM (`LSTM 64 → Dropout → LSTM 32 → Dense 16 → Dense 1`) with early stopping; evaluate on the holdout.
5. Produce an N-day recursive forecast (weekend-aware dates) and a BUY / SELL / HOLD signal based on trend, current price, and directional accuracy.
6. Cache the model + scaler under `models/` keyed by a fingerprint of `(symbol, row count, last date, backend, window)`. New data automatically invalidates the cache.

If TensorFlow is missing or training fails, it falls back to `HistGradientBoostingRegressor`, then to a NumPy ridge solution. You can force a backend with `--backend sklearn` or `{"backend": "sklearn"}`.

### What the AI Forecast means

"AI Forecast" is a statistical projection, not a prediction with guaranteed outcomes. The model learns patterns from the stock's own historical daily closing prices and extrapolates the next 1–90 trading days. The **BUY / SELL / HOLD** signal compares the projected price path with the model's validated directional accuracy and the latest close. Metrics (RMSE, MAE, MAPE, directional accuracy, naive-baseline comparison) are computed on a chronological holdout so you can judge whether the model is actually useful. The forecast is automatically retrained whenever fresh market data changes the model fingerprint; otherwise the cached model is reused. **It is not investment advice.**

CLI:

```bash
python manage.py train_model AAPL                 # LSTM, 7-day horizon
python manage.py train_model TSLA --backend sklearn --days 14 --offline
```

---

## Pages & API

| Page | URL | Purpose |
|---|---|---|
| Overview | `/` | Quote, stats, price/volume charts, headlines, freshness badge |
| Compare | `/compare/` | Overlay two tickers (raw + indexed-to-100) |
| AI Forecast | `/predict/` | Train/load model, forecast, metrics, signal |
| Screener | `/stocks/` | Paginated ~8,200-symbol universe with live quotes |
| Details | `/details/AAPL/` | Company info, full chart, news |
| API Docs | `/api-docs/` | Endpoint reference |

```bash
curl http://localhost:8000/api/health/
curl "http://localhost:8000/api/history/?symbol=AAPL&start=2025-01-01"
curl "http://localhost:8000/api/quote/?symbol=AAPL"
curl -X POST http://localhost:8000/api/predict/ \
     -H 'Content-Type: application/json' \
     -d '{"symbol":"AAPL","days":7}'
curl -X POST http://localhost:8000/api/refresh/ -H 'Content-Type: application/json' -d '{}'
```

CSV export: `/download/0/?symbol=AAPL` (history), `/download/3/?symbol=AAPL&days=7` (forecast), `/download/4/` (screener).

---

## Tests

```bash
python manage.py test StockPricePredictionApp -v 2
```

Tests use synthetic data in a temporary directory and make **no network calls**.

---

## Production deployment

```bash
cp .env.example .env            # set a real SECRET_KEY, ALLOWED_HOSTS, DEBUG=False
python manage.py collectstatic --noinput
gunicorn StockPricePrediction.wsgi:application --bind 0.0.0.0:8000 --workers 2 --timeout 300
```

Or `docker compose up --build -d`. Serve `staticfiles/` with nginx in front of gunicorn. For Postgres, set `DB_ENGINE`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST` (install `psycopg2-binary` when using Postgres).

Environment variables (all optional for local dev): `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`, `DB_*`, `MARKET_DATA_DIR`, `MODEL_DIR`, `MARKET_UNIVERSE_CSV`, `MARKET_REFRESH_TTL_HOURS`, `NEWS_DIR`, `NEWS_TTL_HOURS`, `FINNHUB_API_KEY`, `NEWS_API_KEY`, `LOG_LEVEL`.

> **Disclaimer:** forecasts are a demonstration of the ML pipeline, not financial advice.
