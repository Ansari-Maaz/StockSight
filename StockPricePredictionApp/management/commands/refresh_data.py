"""Bring every cached symbol up to date. Schedule this with cron/Celery.

Example (cron, weekdays 18:30):
    30 18 * * 1-5 cd /path/to/MarketMind && .venv/bin/python manage.py refresh_data
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from StockPricePredictionApp.services import data as data_service
from StockPricePredictionApp.services import market as market_service


class Command(BaseCommand):
    help = "Incrementally refresh all cached market data from the provider."

    def add_arguments(self, parser):
        parser.add_argument("symbols", nargs="*", help="Only refresh these symbols")
        parser.add_argument("--force", action="store_true",
                            help="Ignore the per-symbol refresh rate limit")
        parser.add_argument("--universe", action="store_true",
                            help="Refresh all symbols in the bundled universe (slow)")

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
