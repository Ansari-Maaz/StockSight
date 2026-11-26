# StockSight

> **This is the lightweight `main` branch**, built for Render's free tier. The complete original project — including the TensorFlow AI Forecast and full deployment stack — is kept on the [`full`](https://github.com/Ansari-Maaz/StockSight/tree/full) branch.

A lightweight stock analytics dashboard built with **Django 5**, **yfinance** and **pandas**. It runs from a local market-data cache, refreshes it on demand, and works offline when the data provider is unavailable.

> The old version depended on hard-coded credentials, hard-coded date ranges, global in-memory DataFrames, and retrained a model on **every** request. This version removes all of that.

---

## Features

| Feature | Details |
|---|---|
| **Local-first data** | One CSV per ticker in `data/market/`. Pages work with zero network access. |
| **Always up to date** | Stale symbols are incrementally refreshed from yfinance as soon as a new trading session is expected, plus `refresh_data` for cron/Celery/Docker. |
| **Daily stock news** | Yahoo Finance RSS + Google News RSS + yfinance, deduplicated and cached per symbol; optional Finnhub/NewsAPI keys. Shown on the overview, details and compare pages. |
| **No secret keys required** | All core features work without API keys; Finnhub/NewsAPI are optional upgrades. |
| **Modern UI** | Animated public landing page at `/`, plus a responsive dashboard at `/dashboard/` with **light/dark theme toggle** (persisted in `localStorage`), a **collapsible sidebar**, locally bundled Plus Jakarta Sans + JetBrains Mono fonts, indigo/violet palette, semantic colour coding, and Chart.js charts that re-theme with the active mode (vendored locally). No CDN dependency at runtime. |
| **Local workspace** | Browser-only watchlist and price alerts. No account or server-side user state. Includes a `Ctrl/⌘K` command palette, an installable PWA with an offline shell, SEO files and branded error pages. |
| **JSON API** | `/api/history/`, `/api/quote/`, `/api/quotes/`, `/api/search/`, `/api/health/`, `/api/refresh/`. |
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

# 2. Run
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

## Pages & API

| Page | URL | Purpose |
|---|---|---|
| Overview | `/` | Quote, stats, price/volume charts, headlines, freshness badge |
| Compare | `/compare/` | Overlay two tickers (raw + indexed-to-100) |
| Screener | `/stocks/` | Paginated ~8,200-symbol universe with live quotes |
| Details | `/details/AAPL/` | Company info, full chart, news |
| API Docs | `/api-docs/` | Endpoint reference |

```bash
curl http://localhost:8000/api/health/
curl "http://localhost:8000/api/history/?symbol=AAPL&start=2025-01-01"
curl "http://localhost:8000/api/quote/?symbol=AAPL"
curl -X POST http://localhost:8000/api/refresh/ -H 'Content-Type: application/json' -d '{}'
```

CSV export: `/download/0/?symbol=AAPL` (history), `/download/4/` (screener).

---

## Tests

```bash
python manage.py test StockPricePredictionApp -v 2
```

Tests use synthetic data in a temporary directory and make **no network calls**.

---

## Production deployment

This branch ships with WhiteNoise, so Django serves its own compressed static
files behind gunicorn. For the full production stack, use the `full` branch.

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
   volumes, so rebuilding containers keeps them.

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
- **Persistent disk:** mount one at `/app/data` so the price/news cache and SQLite survive restarts. Keep a single instance or switch to Postgres.
- A 1 GB instance is enough for this lightweight build.

### Option 2b — Render free tier (this branch)

`main` is the lightweight build for Render's free 512 MB web service. It uses
`Dockerfile.render` and `render.yaml`. TensorFlow, Keras, scikit-learn and SciPy
are not installed, and the AI Forecast feature is not present on this branch.

Deploy with the Render Blueprint:

1. Sign in to Render with GitHub (no card needed for the free plan).
2. **New → Blueprint → select `Ansari-Maaz/StockSight`**, branch `main`.
3. Deploy. The URL will be `https://stocksight.onrender.com` (or similar).

Limitations of the free tier:

- No persistent disk: caches reset on restart; the bundled market CSVs are the starting point.
- No background refresher container: market data refreshes when a page is opened.
- Free web services sleep after ~15 minutes idle; the first request after waking takes about a minute.
- Keep a single instance (`--workers 1`) to stay inside 512 MB.

For the full app with AI Forecast, use the `full` branch.

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

> **Disclaimer:** market data may be delayed. Nothing here is investment advice.
