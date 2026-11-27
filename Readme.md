# StockSight

> **This is the lightweight `main` branch** for Render's free tier. It includes a NumPy-based **1–60 day price forecast**. The complete project with the TensorFlow LSTM and full deployment stack is kept on the [`full`](https://github.com/Ansari-Maaz/StockSight/tree/full) branch.

A lightweight stock price prediction dashboard built with **Django 5**, **yfinance** and **pandas**. Forecasts use a NumPy regression trained on each stock's own history, with a 1–60 trading-day horizon. It runs from a local market-data cache and works offline when the data provider is unavailable.

> The old version depended on hard-coded credentials, hard-coded date ranges, global in-memory DataFrames, and retrained a model on **every** request. This version removes all of that.

---

## Features

| Feature | Details |
|---|---|
| **Local-first data** | One CSV per ticker in `data/market/`. Pages work with zero network access. |
| **Always up to date** | Stale symbols are incrementally refreshed from yfinance as soon as a new trading session is expected, plus `refresh_data` for cron/Celery/Docker. |
| **Daily stock news** | Yahoo Finance RSS + Google News RSS + yfinance, deduplicated and cached per symbol; optional Finnhub/NewsAPI keys. Shown on the overview, details and compare pages. |
| **Forecasting** | NumPy regression trained **from your data**, with a 1–60 trading-day horizon. Models are cached by fingerprint and reused. Tensorflow/scikit-learn are not installed on this branch. |
| **Honest metrics** | RMSE, MAE, MAPE, directional accuracy and a naive-baseline comparison on a chronological holdout. |
| **No secret keys required** | All core features work without API keys; Finnhub/NewsAPI are optional upgrades. |
| **Modern UI** | Animated public landing page at `/`, plus a responsive dashboard at `/dashboard/` with **light/dark theme toggle** (persisted in `localStorage`), a **collapsible sidebar**, locally bundled Plus Jakarta Sans + JetBrains Mono fonts, indigo/violet palette, semantic colour coding, and Chart.js charts that re-theme with the active mode (vendored locally). No CDN dependency at runtime. |
| **Local workspace** | Browser-only watchlist and price/forecast alerts. No account or server-side user state. Includes a `Ctrl/⌘K` command palette, an installable PWA with an offline shell, SEO files, a 1200×630 social thumbnail (`static/stocksight-thumbnail.png`) for link previews, and branded error pages. |
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
4. Train a NumPy ridge regression on the scaled windows; evaluate on the holdout.
5. Produce a recursive forecast of up to **30 trading days** (weekend-aware dates) and a BUY / SELL / HOLD signal based on trend, current price, and directional accuracy.
6. Cache the model + scaler under `models/` keyed by a fingerprint of `(symbol, row count, last date, backend, window)`. New data automatically invalidates the cache.

### What the AI Forecast means

"AI Forecast" is a statistical projection, not a prediction with guaranteed outcomes. The model learns patterns from the stock's own historical daily closing prices and extrapolates the next 1–60 trading days. The **BUY / SELL / HOLD** signal compares the projected price path with the model's validated directional accuracy and the latest close. Metrics (RMSE, MAE, MAPE, directional accuracy, naive-baseline comparison) are computed on a chronological holdout so you can judge whether the model is actually useful. The forecast is automatically retrained whenever fresh market data changes the model fingerprint; otherwise the cached model is reused. **It is not investment advice.**

CLI:

```bash
python manage.py train_model AAPL                 # NumPy model, 7-day horizon
python manage.py train_model TSLA --backend numpy --days 14 --offline
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

The repo ships with WhiteNoise, so Django serves its own compressed static
files behind gunicorn. No separate nginx static volume is required.

### Option 1 — VPS + Docker Compose + automatic HTTPS (recommended)

You need an Ubuntu 22.04/24.04 VPS (1 GB RAM or more), a domain name, and
ports 80/443 open.

1. **Point DNS at the server.** Create an `A` record for `stocksight.example.com`
   (and optionally `www`) pointing to the VPS public IP. Wait for DNS to resolve:

   ```bash
   getent hosts stocksight.example.com
   ```

2. **Install Docker** on the VPS:

   ```bash
   curl -fsSL https://get.docker.com | sudo sh
   sudo usermod -aG docker "$USER"
   newgrp docker
   ```

3. **Open the firewall** (if `ufw` is enabled) and in your provider's
   security group / cloud firewall:

   ```bash
   sudo ufw allow OpenSSH
   sudo ufw allow 80/tcp
   sudo ufw allow 443/tcp
   sudo ufw enable
   ```

   If nginx or Apache is already using ports 80/443, stop it first
   (`sudo systemctl stop nginx` or `sudo systemctl stop apache2`).

4. **Clone the project and create the environment file:**

   ```bash
   git clone https://github.com/Ansari-Maaz/StockSight.git
   cd StockSight
   cp .env.example .env
   python3 -c "import secrets; print(secrets.token_urlsafe(50))"
   ```

   Edit `.env` and set at least:

   ```env
   DOMAIN=stocksight.example.com
   DJANGO_SECRET_KEY=<the generated key>
   DJANGO_DEBUG=False
   DJANGO_ALLOWED_HOSTS=stocksight.example.com,www.stocksight.example.com
   ```

   `DOMAIN` must be the bare hostname, without `https://` or a trailing slash.

5. **Build and start the stack:**

   ```bash
   docker compose -f docker-compose.prod.yml up -d --build
   ```

   The first build installs Python packages and can take a few minutes. Caddy
   obtains a Let's Encrypt certificate automatically once DNS is live.

   > Using Cloudflare? Set the DNS record to **DNS only** (grey cloud) until
   > Caddy has issued the certificate, then you can proxy it again.

6. **Verify:**

   ```bash
   docker compose -f docker-compose.prod.yml ps
   docker compose -f docker-compose.prod.yml logs -f caddy
   curl -I https://stocksight.example.com/
   ```

   The site should return `200 OK`, and `http://` should redirect to `https://`.

7. **Update a deployment:**

   ```bash
   git pull
   docker compose -f docker-compose.prod.yml up -d --build
   ```

   Price history, news cache and the SQLite database live in named Docker
   volumes (`market_data`, `model_data`), so rebuilding containers keeps them.

Useful commands:

```bash
docker compose -f docker-compose.prod.yml logs -f web
docker compose -f docker-compose.prod.yml restart web
docker compose -f docker-compose.prod.yml down          # stop, keep data
docker compose -f docker-compose.prod.yml down -v       # stop and delete data
```

If something fails:

- **`400 Bad Request`** — `DJANGO_ALLOWED_HOSTS` doesn't include the hostname you opened.
- **Certificate not issued** — confirm DNS points at the server and ports 80/443 are open; check `docker compose -f docker-compose.prod.yml logs caddy`.
- **`DisallowedHost` in logs** — add the exact hostname (without `https://`) to `DJANGO_ALLOWED_HOSTS`.
- **Old CSS/JS after an update** — rebuild with `--build`; the service worker also caches the shell, so hard-refresh once.

### Option 2 — PaaS (Render, Railway, Fly.io)

The included `Dockerfile` works on container-based hosts:

- **Start command:** `gunicorn StockPricePrediction.wsgi:application --bind 0.0.0.0:$PORT --workers 2 --timeout 300`
- **Environment:** `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=False`, `DJANGO_ALLOWED_HOSTS=<your-host>`, `SECURE_SSL_REDIRECT=False` (the platform terminates TLS).
- **Persistent disk:** mount one at `/app/data` so the cache, models and SQLite survive restarts. Keep a single instance or switch to Postgres.
- A 1 GB instance is enough for this lightweight build.

### Option 2b — Render free tier (this branch)

`main` is the lightweight build for Render's free 512 MB web service. It uses
`Dockerfile.render` and `render.yaml`. TensorFlow, Keras, scikit-learn and SciPy
are not installed; forecasts use the NumPy model with a 1–60 day horizon.

Deploy with the Render Blueprint:

1. Sign in to Render with GitHub (no card needed for the free plan).
2. **New → Blueprint → select `Ansari-Maaz/StockSight`**, branch `main`.
3. Deploy. The URL will be `https://stocksight.onrender.com` (or similar).

Limitations of the free tier:

- Forecasts use NumPy regression rather than the LSTM on the `full` branch.
- No persistent disk: caches reset on restart; the bundled market CSVs are the starting point.
- No background refresher container: market data refreshes when a page is opened.
- Free web services sleep after ~15 minutes idle; the first request after waking takes about a minute.
- Keep a single instance (`--workers 1`) to stay inside 512 MB.

For the full LSTM app, use the `full` branch.

### Option 3 — Manual gunicorn (existing server with nginx/Caddy)

```bash
cp .env.example .env            # set SECRET_KEY, ALLOWED_HOSTS, DEBUG=False
python manage.py migrate
python manage.py collectstatic --noinput
gunicorn StockPricePrediction.wsgi:application --bind 127.0.0.1:8000 --workers 2 --timeout 300
```

Put nginx/Caddy in front for TLS and proxy `/` to `127.0.0.1:8000`. WhiteNoise
serves `/static/` directly from Django. Keep `refresh_data` running from cron
(see `crontab.example`) or use the Compose `refresher` service.

Environment variables (all optional for local dev): `DOMAIN`, `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`, `SECURE_SSL_REDIRECT`, `CSRF_TRUSTED_ORIGINS`, `DB_*`, `MARKET_DATA_DIR`, `MODEL_DIR`, `MARKET_UNIVERSE_CSV`, `MARKET_REFRESH_TTL_HOURS`, `NEWS_DIR`, `NEWS_TTL_HOURS`, `FINNHUB_API_KEY`, `NEWS_API_KEY`, `LOG_LEVEL`.

## Security hardening

This is an intentionally **account-free** application: no passwords, JWTs,
email verification, sessions, user-owned records or admin users exist. The
authentication/authorization controls below are therefore not applicable; all
other controls are enforced in code.

### Controls implemented

| Control | Implementation |
|---|---|
| Input validation | `StockPricePredictionApp/validation.py` — strict allowlists for symbols, dates, integers, search strings, download IDs and symbol lists. Every view and API rejects invalid input with `400 Bad Request`. |
| Injection / ReDoS | `services/market.py` uses `str.contains(..., regex=False)` for both search paths. All filesystem paths are sanitised in `services/data.py`; lock files use the same sanitised stem. |
| Rate limiting | `StockPricePrediction/security.py` — per-IP quotas: 20/min for forecast and refresh, 120–180/min for APIs, 180–300/min for pages. Exceeded requests receive `429` + `Retry-After`. |
| CSRF | State-changing APIs require the Django CSRF token; JS sends `X-CSRFToken`. The alerts page uses `@ensure_csrf_cookie`. |
| Security headers | `SecurityHeadersMiddleware` emits nonce-based CSP, `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`, `COOP`, `CORP` and HSTS on secure requests. Caddy adds the same at the edge. |
| Secrets | `DJANGO_SECRET_KEY` must be ≥32 chars and cannot be the dev default when `DEBUG=False`. `DJANGO_ALLOWED_HOSTS` cannot be `*`. `.env` is gitignored. |
| Attack surface | Django admin route and `static()` media serving removed from the URLconf. No file-upload endpoints exist. |
| Logging | Structured JSON logs with a redaction filter for password/token/secret/api-key/cookie patterns; rate-limit denials are logged to `stocksight.security`. |

### Secret injection (exact configuration)

Generate a key:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(50))"
```

**Render:** Dashboard → Environment → add `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=False`, `DJANGO_ALLOWED_HOSTS=stocksight.onrender.com`, `CSRF_TRUSTED_ORIGINS=https://stocksight.onrender.com`, `SECURE_SSL_REDIRECT=True`. Never put these values in the Dockerfile.

**VPS / Docker Compose:** keep them in a root-only `.env` (`chmod 600 .env`) which is already gitignored, or use platform secrets:

```yaml
secrets:
  django_secret:
    file: ./secrets/django_secret.txt
services:
  web:
    secrets: [django_secret]
```

### Shared rate-limit cache (multi-worker)

The single-worker image uses Django's in-process `LocMemCache`. If you scale to
multiple workers, add `django-redis==5.4.0` and replace the `CACHES` block in
`settings.py`:

```python
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": env("REDIS_URL", "redis://127.0.0.1:6379/1"),
        "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
    }
}
```

### Database isolation

SQLite is a local file and is never network-exposed. For Postgres, keep the DB
on a private network/VPC, never assign it a public IP, and require TLS:

```env
DB_ENGINE=django.db.backends.postgresql
DB_NAME=stocksight
DB_USER=stocksight
DB_PASSWORD=<secret manager value>
DB_HOST=db.internal
DB_PORT=5432
```

### Secret scanning

Run before every release:

```bash
git grep -nE '(api[_-]?key|secret|token|password|BEGIN [A-Z ]*PRIVATE KEY|AKIA[0-9A-Z]{16})' -- ':!*.csv' ':!static/assets/*'
git log -p --all | grep -iE 'password|secret|api[_-]?key' || true
```

If a key is found in history, rotate it immediately and purge history with
`git filter-repo`. No first-party secret was found during this audit.

> **Disclaimer:** forecasts are a demonstration of the ML pipeline, not financial advice.
