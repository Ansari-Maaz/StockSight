"""Fast, offline tests - no network calls are made."""

from __future__ import annotations

import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
from django.test import Client, TestCase

from StockPricePredictionApp.services import data as data_service
from StockPricePredictionApp.services import predictor


def synthetic_frame(days: int = 320, symbol: str = "TEST") -> pd.DataFrame:
    dates = pd.bdate_range(end=date.today(), periods=days)
    trend = np.linspace(100, 160, days)
    wave = np.sin(np.linspace(0, 20, days)) * 6
    close = trend + wave
    return pd.DataFrame({
        "Open": close - 0.5,
        "High": close + 1.5,
        "Low": close - 1.5,
        "Close": close,
        "Volume": np.full(days, 1_000_000, dtype=int),
    }, index=dates)


class TempDataMixin:
    """Redirect the data/model directories to a throw-away folder."""

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.data_dir = self.root / "market"
        self.data_dir.mkdir()
        self.model_dir = self.root / "models"
        self.model_dir.mkdir()
        predictor._MODEL_MEMORY.clear()
        self.patches = [
            patch.object(data_service, "DATA_DIR", self.data_dir),
            patch.object(data_service, "META_FILE", self.data_dir / "meta.json"),
            patch.object(predictor, "MODEL_DIR", self.model_dir),
        ]
        for p in self.patches:
            p.start()
        for symbol in ("TEST", "AAPL", "MSFT"):
            data_service.save_local(symbol, synthetic_frame(symbol=symbol))

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()
        super().tearDown()


class DataRepositoryTests(TempDataMixin, unittest.TestCase):
    def test_normalize_symbol(self):
        self.assertEqual(data_service.normalize_symbol(" apple "), "AAPL")
        self.assertEqual(data_service.normalize_symbol("btc"), "BTC-USD")

    def test_local_roundtrip(self):
        df = data_service.load_local("TEST")
        self.assertIsNotNone(df)
        self.assertEqual(len(df), 320)
        self.assertEqual(list(df.columns), data_service.REQUIRED_COLUMNS)

    def test_offline_history_is_flagged_cache(self):
        result = data_service.get_history("TEST", refresh="never")
        self.assertEqual(result.source, "cache")
        self.assertEqual(result.rows, 320)
        self.assertFalse(result.stale)

    def test_date_filter(self):
        start = date.today() - timedelta(days=30)
        result = data_service.get_history("TEST", start=start, refresh="never")
        self.assertLess(result.rows, 320)
        self.assertGreater(result.rows, 0)

    def test_missing_symbol_returns_empty(self):
        result = data_service.get_history("DOESNOTEXIST", refresh="never")
        self.assertTrue(result.df.empty)
        self.assertIsNotNone(result.error)


class PredictorTests(TempDataMixin, unittest.TestCase):
    def test_predict_from_synthetic_data_with_numpy_backend(self):
        result = predictor.predict("TEST", days=5, backend="numpy", seq_len=20,
                                   refresh_data=False)
        self.assertEqual(len(result.predictions), 5)
        self.assertEqual(len(result.dates), 5)
        self.assertIn(result.signal, {"BUY", "SELL", "HOLD"})
        self.assertGreater(result.metrics["samples"], 0)
        self.assertTrue(result.fresh)
        self.assertEqual(result.model_type, "Linear regression (NumPy)")

    def test_cached_model_is_reused(self):
        kwargs = dict(days=3, backend="numpy", seq_len=20, refresh_data=False)
        first = predictor.predict("TEST", **kwargs)
        second = predictor.predict("TEST", **kwargs)
        self.assertTrue(first.fresh)
        self.assertFalse(second.fresh)
        np.testing.assert_allclose(first.predictions, second.predictions)


class ViewSmokeTests(TempDataMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.client = Client()

    @patch("StockPricePredictionApp.views.news_service.get_news", return_value=[])
    @patch("StockPricePredictionApp.views._company_info", return_value={"sector": "Tech"})
    @patch("StockPricePredictionApp.views.market_service.screener")
    def test_pages_render(self, mock_screener, _mock_info, _mock_news):
        from django.core.paginator import Paginator
        page_obj = Paginator([{"symbol": "TEST"}], 10).get_page(1)
        mock_screener.return_value = {
            "rows": [{"symbol": "TEST", "name": "Test", "close": 100, "change": 1,
                      "change_pct": 1, "date": "today", "country": "", "industry": "",
                      "stale": False, "live": True}],
            "page_obj": page_obj, "total": 1, "search": "",
        }
        for url in ["/", "/compare/", "/predict/", "/stocks/", "/details/TEST/", "/health/", "/api-docs/"]:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200, url)

    def test_api_endpoints(self):
        self.assertEqual(self.client.get("/api/health/").status_code, 200)
        response = self.client.get("/api/history/?symbol=TEST")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["rows"], 320)
        response = self.client.get("/api/quote/?symbol=TEST")
        self.assertEqual(response.json()["symbol"], "TEST")

    def test_prediction_via_post(self):
        from unittest.mock import MagicMock
        fake = MagicMock()
        fake.as_dict.return_value = {
            "symbol": "TEST", "dates": ["d1", "d2"], "predictions": [1.0, 2.0],
            "history_dates": [], "history_close": [], "metrics": {"rmse": 1},
            "signal": "BUY", "confidence": 0.6, "model_type": "stub",
            "trained_at": "now", "data_through": "today", "data_source": "cache",
            "stale": False, "fresh": True, "note": "",
        }
        with patch("StockPricePredictionApp.views.predictor.predict", return_value=fake):
            response = self.client.post("/predict/", {"company1": "TEST", "days": "3"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["has_result"])

    def test_csv_download(self):
        response = self.client.get("/download/0/?symbol=TEST")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Date,Open,High,Low,Close,Volume", response.content)
