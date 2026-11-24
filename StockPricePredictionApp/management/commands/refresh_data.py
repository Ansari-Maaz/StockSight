"""Bring every cached symbol up to date. Schedule this with cron/Celery.

Example (cron, weekdays 18:30):
    30 18 * * 1-5 cd /path/to/StockSight && .venv/bin/python manage.py refresh_data
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from StockPricePredictionApp.services import data as data_service
from StockPricePredictionApp.services import market as market_service
from StockPricePredictionApp.services import news as news_service


class Command(BaseCommand):
    help = "Incrementally refresh all cached market data and stock news."

    def add_arguments(self, parser):
        parser.add_argument("symbols", nargs="*", help="Only refresh these symbols")
        parser.add_argument("--force", action="store_true",
                            help="Ignore the per-symbol refresh rate limit")
        parser.add_argument("--universe", action="store_true",
                            help="Refresh all symbols in the bundled universe (slow)")
        parser.add_argument("--no-news", action="store_true",
                            help="Skip the stock-news refresh")

    def handle(self, *args, **options):
        if options["universe"]:
            symbols = market_service.get_universe()["Symbol"].tolist()
        elif options["symbols"]:
            symbols = [s.upper() for s in options["symbols"]]
        else:
            symbols = [row["symbol"] for row in data_service.status()["symbols"]]

        if not symbols:
            self.stdout.write(self.style.WARNING("No cached symbols yet. Run seed_data first."))
            return

        self.stdout.write(f"Refreshing {len(symbols)} symbols …")
        results = data_service.refresh_symbols(symbols, force=options["force"])
        ok = sum(1 for r in results if r.get("ok"))
        for row in results:
            label = self.style.SUCCESS if row.get("ok") else self.style.WARNING
            self.stdout.write(label(f"{row['symbol']:<12} {row.get('last_date') or row.get('error', '')}"))
        self.stdout.write(self.style.SUCCESS(f"\nUpdated {ok}/{len(results)} symbols."))

        if options["no_news"]:
            return
        if options["universe"]:
            self.stdout.write(self.style.WARNING("Skipping news for --universe (too many symbols)."))
            return

        self.stdout.write("\nRefreshing stock news …")
        news_results = news_service.refresh_news(symbols, force=options["force"])
        news_ok = sum(1 for row in news_results if row.get("ok"))
        for row in news_results:
            label = self.style.SUCCESS if row.get("ok") else self.style.WARNING
            detail = f"{row.get('count', 0)} articles" if row.get("ok") else (row.get("error") or "no articles")
            self.stdout.write(label(f"{row['symbol']:<12} {detail}"))
        self.stdout.write(self.style.SUCCESS(f"News updated for {news_ok}/{len(news_results)} symbols."))
