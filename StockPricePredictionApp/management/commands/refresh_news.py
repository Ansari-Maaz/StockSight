"""Refresh the daily stock-news cache.

Examples:
    python manage.py refresh_news
    python manage.py refresh_news AAPL MSFT NVDA --force
    python manage.py refresh_news --market
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from StockPricePredictionApp.services import data as data_service
from StockPricePredictionApp.services import news as news_service


class Command(BaseCommand):
    help = "Refresh cached stock-specific news from Yahoo/Google/optional APIs."

    def add_arguments(self, parser):
        parser.add_argument("symbols", nargs="*", help="Only refresh news for these symbols")
        parser.add_argument("--force", action="store_true", help="Ignore the news cache TTL")
        parser.add_argument("--market", action="store_true", help="Also refresh broad market news")

    def handle(self, *args, **options):
        if options["market"]:
            articles = news_service.get_market_news(limit=news_service.MAX_ARTICLES, force=True)
            self.stdout.write(self.style.SUCCESS(f"MARKET       {len(articles)} articles"))

        symbols = [s.upper() for s in options["symbols"]]
        if not symbols:
            symbols = [row["symbol"] for row in data_service.status()["symbols"]]

        if not symbols:
            self.stdout.write(self.style.WARNING("No cached symbols yet. Run seed_data first."))
            return

        self.stdout.write(f"Refreshing news for {len(symbols)} symbols …")
        results = news_service.refresh_news(symbols, force=options["force"])
        ok = sum(1 for row in results if row.get("ok"))
        for row in results:
            label = self.style.SUCCESS if row.get("ok") else self.style.WARNING
            detail = f"{row.get('count', 0)} articles"
            if row.get("error"):
                detail = row["error"]
            self.stdout.write(label(f"{row['symbol']:<12} {detail}"))
        self.stdout.write(self.style.SUCCESS(f"\nNews updated for {ok}/{len(results)} symbols."))
