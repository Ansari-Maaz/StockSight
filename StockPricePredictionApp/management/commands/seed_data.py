"""Import market history into the local cache (offline-friendly).

Examples:
    python manage.py seed_data                       # default watchlist
    python manage.py seed_data AAPL TSLA --years 5
    python manage.py seed_data --from-csv data.csv --symbol AAPL
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from StockPricePredictionApp.services import data as data_service

DEFAULT_SYMBOLS = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "TSLA", "META", "BTC-USD"]


class Command(BaseCommand):
    help = "Import / seed local OHLCV data from yfinance or a CSV file."

    def add_arguments(self, parser):
        parser.add_argument("symbols", nargs="*", help="Ticker symbols to import")
        parser.add_argument("--years", type=int, default=10, help="Years of history (default: 10)")
        parser.add_argument("--from-csv", help="Import from a local OHLCV CSV instead of the network")
        parser.add_argument("--symbol", help="Symbol to use with --from-csv")
        parser.add_argument("--offline", action="store_true", help="Never touch the network")

    def handle(self, *args, **options):
        if options["from_csv"]:
            symbol = options["symbol"]
            if not symbol:
                raise CommandError("--from-csv requires --symbol")
            rows = data_service.seed_from_csv(options["from_csv"], symbol)
            self.stdout.write(self.style.SUCCESS(f"Imported {rows} rows for {symbol.upper()}"))
            return

        symbols = options["symbols"] or DEFAULT_SYMBOLS
        if options["offline"]:
            for symbol in symbols:
                frame = data_service.load_local(symbol)
                status = f"{len(frame)} cached rows" if frame is not None else "NO LOCAL DATA"
                self.stdout.write(f"{symbol.upper():<10} {status}")
            return

        start = date.today() - timedelta(days=365 * options["years"])
        self.stdout.write(f"Fetching {len(symbols)} symbols from {start} …")
        summary = []
        for symbol in symbols:
            try:
                frame = data_service.fetch_remote(symbol, start=start)
                data_service.save_local(symbol, frame)
                summary.append((symbol.upper(), len(frame), str(frame.index[-1].date()), None))
            except Exception as exc:
                summary.append((symbol.upper(), 0, "-", str(exc)[:90]))
        for symbol, rows, last, error in summary:
            if error:
                self.stdout.write(self.style.WARNING(f"{symbol:<10} FAILED: {error}"))
            else:
                self.stdout.write(self.style.SUCCESS(f"{symbol:<10} {rows:>6} rows  through {last}"))
        self.stdout.write(f"Data directory: {data_service.DATA_DIR}")
