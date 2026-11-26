"""Train / refresh the forecasting model for a symbol from local data.

    python manage.py train_model AAPL
    python manage.py train_model AAPL --backend sklearn --days 14
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from StockPricePredictionApp.services import predictor


class Command(BaseCommand):
    help = "Train a forecasting model entirely from the local dataset."

    def add_arguments(self, parser):
        parser.add_argument("symbol")
        parser.add_argument("--backend", default="auto",
                            choices=["auto", "lstm", "sklearn", "numpy"])
        parser.add_argument("--days", type=int, default=7)
        parser.add_argument("--seq-len", type=int, default=predictor.SEQ_LEN)
        parser.add_argument("--offline", action="store_true",
                            help="Do not refresh market data before training")

    def handle(self, *args, **options):
        try:
            result = predictor.predict(
                options["symbol"],
                days=options["days"],
                backend=options["backend"],
                seq_len=options["seq_len"],
                force_retrain=True,
                refresh_data=not options["offline"],
            )
        except Exception as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(
            f"{result.symbol}: {result.model_type} trained on data through {result.data_through}"
        ))
        self.stdout.write(f"  metrics : {result.metrics}")
        self.stdout.write(f"  signal  : {result.signal} (confidence {result.confidence:.0%})")
        self.stdout.write(f"  forecast: {result.predictions[:3]} …")
