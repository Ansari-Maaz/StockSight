"""Fast, offline tests - no network calls are made."""

from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
from django.test import Client, TestCase

from StockPricePredictionApp.services import data as data_service
from StockPricePredictionApp.services import indicators
from StockPricePredictionApp.services import news as news_service
from StockPricePredictionApp.services import predictor
from StockPricePredictionApp.services import sentiment


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
        self.news_dir = self.root / "news"
        self.news_dir.mkdir()
        predictor._MODEL_MEMORY.clear()
        self.patches = [
            patch.object(data_service, "DATA_DIR", self.data_dir),
            patch.object(data_service, "META_FILE", self.data_dir / "meta.json"),
            patch.object(predictor, "MODEL_DIR", self.model_dir),
            patch.object(news_service, "NEWS_DIR", self.news_dir),
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

    def test_stale_data_is_refreshed_even_after_recent_attempt(self):
        data_service.save_local("TEST", synthetic_frame(days=320))
        with patch.object(data_service, "_expected_session", return_value=date.today() + timedelta(days=2)):
            self.assertTrue(data_service._should_refresh("TEST", data_service.load_local("TEST"), False))
            meta = {"TEST": {"last_attempt": datetime.now(timezone.utc).isoformat()}}
            with patch.object(data_service, "_read_meta", return_value=meta):
                self.assertFalse(data_service._should_refresh("TEST", data_service.load_local("TEST"), False))

    def test_missing_symbol_returns_empty(self):
        result = data_service.get_history("DOESNOTEXIST", refresh="never")
        self.assertTrue(result.df.empty)
        self.assertIsNotNone(result.error)


class IndicatorTests(unittest.TestCase):
    def test_indicator_series_align_and_warmup(self):
        df = synthetic_frame(days=120)
        values = indicators.compute(df)
        self.assertEqual(len(values["labels"]), len(df))
        self.assertEqual(len(values["sma20"]), len(df))
        self.assertIsNone(values["sma20"][18])
        self.assertAlmostEqual(values["sma20"][19], round(df["Close"].iloc[:20].mean(), 2), places=2)
        self.assertIsNone(values["sma50"][48])
        self.assertIsNone(values["macd"][24])
        self.assertIsNotNone(values["bb_upper"][-1])
        self.assertGreaterEqual(values["bb_upper"][-1], values["bb_lower"][-1])
        rsi_values = [v for v in values["rsi"] if v is not None]
        self.assertTrue(rsi_values)
        self.assertTrue(all(0 <= v <= 100 for v in rsi_values))

    def test_empty_frame_returns_empty(self):
        self.assertEqual(indicators.compute(pd.DataFrame()), {})


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
        self.assertEqual(len(result.backtest_dates), result.metrics["samples"])
        self.assertEqual(len(result.backtest_actual), len(result.backtest_predicted))
        self.assertEqual(len(result.backtest_naive), len(result.backtest_actual))
        self.assertIn("backtest_actual", result.as_dict())

    def test_cached_model_is_reused(self):
        kwargs = dict(days=3, backend="numpy", seq_len=20, refresh_data=False)
        first = predictor.predict("TEST", **kwargs)
        second = predictor.predict("TEST", **kwargs)
        self.assertTrue(first.fresh)
        self.assertFalse(second.fresh)
        np.testing.assert_allclose(first.predictions, second.predictions)


class SentimentTests(unittest.TestCase):
    def test_headline_tone(self):
        rows = [
            {"title": "Apple beats estimates and raises guidance"},
            {"title": "Nvidia surges on strong growth"},
            {"title": "Tesla misses targets amid weakening demand"},
        ]
        result = sentiment.score(rows)
        self.assertEqual(result["label"], "Bullish")
        self.assertEqual(result["positive"], 2)
        self.assertEqual(result["negative"], 1)

        bearish = sentiment.score([
            {"title": "Company warns of losses and cuts outlook"},
            {"title": "Shares plunge after weak results"},
        ])
        self.assertEqual(bearish["label"], "Bearish")
        self.assertIsNone(sentiment.score([]))


class NewsServiceTests(TempDataMixin, unittest.TestCase):
    def test_article_filters_quote_pages_and_parses_dates(self):
        junk = news_service._article(
            "Apple Inc. (AAPL) Stock Price, News, Quote & History",
            "https://example.com", "Yahoo Finance", "Wed, 25 Nov 2026 12:00:00 GMT",
        )
        self.assertIsNone(junk)
        self.assertIsNone(news_service._article(
            "AA,NFLX,UAL,ZBH | Stock Prices | Quote Comparison - Yahoo Finance",
            "https://example.com", "Yahoo Finance", "2026-11-25",
        ))

        article = news_service._article(
            "Apple beats expectations on strong iPhone demand",
            "https://example.com/story", "Reuters", "Wed, 25 Nov 2026 12:00:00 GMT",
        )
        self.assertEqual(article["publisher"], "Reuters")
        self.assertEqual(article["published"], "25 Nov 2026")
        self.assertTrue(article["published_iso"].startswith("2026-11-25"))

    def test_dedupe_keeps_newest_first(self):
        rows = [
            news_service._article("Older Apple headline about services growth", "u1", "A", "2026-11-20T10:00:00Z"),
            news_service._article("Newer Apple headline about iPhone demand", "u2", "B", "2026-11-25T10:00:00Z"),
            news_service._article("Older Apple headline about services growth!", "u3", "C", "2026-11-21T10:00:00Z"),
        ]
        unique = news_service._dedupe(rows)
        self.assertEqual(len(unique), 2)
        self.assertEqual(unique[0]["publisher"], "B")

    def test_yfinance_payload_shapes(self):
        nested = news_service._normalise_yfinance_item({
            "content": {
                "title": "Nvidia unveils a new AI platform",
                "pubDate": "2026-11-25T13:00:00Z",
                "provider": {"displayName": "Yahoo Finance"},
                "canonicalUrl": {"url": "https://example.com/nvda"},
            }
        })
        self.assertEqual(nested["publisher"], "Yahoo Finance")
        self.assertEqual(nested["link"], "https://example.com/nvda")

        legacy = news_service._normalise_yfinance_item({
            "title": "Microsoft expands its cloud regions",
            "publisher": "Reuters",
            "link": "https://example.com/msft",
            "providerPublishTime": 1795600000,
        })
        self.assertEqual(legacy["publisher"], "Reuters")
        self.assertEqual(legacy["link"], "https://example.com/msft")

    def test_relevance_filters_out_general_market_headlines(self):
        terms = news_service._relevance_terms("AAPL")
        self.assertIn("aapl", terms)
        self.assertIn("apple", terms)
        self.assertTrue(news_service._is_relevant(
            {"title": "Apple Stock Has 3 Things Going for It in 2027"}, terms))
        self.assertTrue(news_service._is_relevant(
            {"title": "Apple Inc. (AAPL) Delivered Strong Results"}, terms))
        self.assertFalse(news_service._is_relevant(
            {"title": "Why the Jensen Huang rally faded so quickly"}, terms))
        self.assertFalse(news_service._is_relevant(
            {"title": "At 63, a Robo-Adviser Bought You 11 Funds You Can't Explain"}, terms))

    @patch.object(news_service, "_collect")
    def test_news_is_cached_on_disk(self, mock_collect):
        mock_collect.return_value = ([{
            "title": "Tesla reports quarterly deliveries",
            "link": "https://example.com/tsla",
            "publisher": "Reuters",
            "published": "25 Nov 2026",
            "published_iso": "2026-11-25T12:00:00+00:00",
            "published_ts": 1795600000,
        }], ["yahoo"])

        first = news_service.get_news("TSLA", limit=6)
        self.assertEqual(len(first), 1)
        self.assertTrue((self.news_dir / "TSLA.json").exists())

        second = news_service.get_news("TSLA", limit=6)
        self.assertEqual(second, first)
        self.assertEqual(mock_collect.call_count, 1)


class ViewSmokeTests(TempDataMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.client = Client()

    @patch("StockPricePredictionApp.views.news_service.get_market_news", return_value=[])
    @patch("StockPricePredictionApp.views.news_service.get_news", return_value=[])
    @patch("StockPricePredictionApp.views._company_info", return_value={"sector": "Tech"})
    @patch("StockPricePredictionApp.views.market_service.screener")
    def test_pages_render(self, mock_screener, _mock_info, _mock_news, _mock_market_news):
        from django.core.paginator import Paginator
        page_obj = Paginator([{"symbol": "TEST"}], 10).get_page(1)
        mock_screener.return_value = {
            "rows": [{"symbol": "TEST", "name": "Test", "close": 100, "change": 1,
                      "change_pct": 1, "date": "today", "country": "", "industry": "",
                      "stale": False, "live": True}],
            "page_obj": page_obj, "total": 1, "search": "",
        }
        for url in ["/", "/dashboard/", "/compare/", "/predict/", "/stocks/", "/portfolio/", "/alerts/", "/details/TEST/", "/api-docs/"]:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200, url)

    def test_landing_page(self):
        response = self.client.get("/")
        self.assertTemplateUsed(response, "landing.html")
        self.assertContains(response, "See the market")
        self.assertContains(response, "How AI Forecast works")
        self.assertContains(response, "No signup")
        self.assertContains(response, 'href="/dashboard/"')
        self.assertContains(response, 'id="landingThemeToggle"')
        self.assertContains(response, 'id="cmpChart"')
        self.assertContains(response, 'data-demo-symbol="AAPL"')
        self.assertEqual([q["symbol"] for q in response.context["ticker"]], ["AAPL", "MSFT"])
        self.assertGreater(len(response.context["hero_series"]["close"]), 1)

    def test_health_page_removed(self):
        self.assertEqual(self.client.get("/health/").status_code, 404)

    @patch("StockPricePredictionApp.views.news_service.get_market_news", return_value=[])
    def test_first_visit_has_empty_symbol_inputs(self, _mock_market_news):
        home = self.client.get("/dashboard/")
        self.assertEqual(home.context["symbol"], "")
        self.assertContains(home, "Search a symbol to get started")
        self.assertContains(home, 'name="company1" list="homeSymbols" value=""')

        compare = self.client.get("/compare/")
        self.assertEqual(compare.context["symbol1"], "")
        self.assertEqual(compare.context["symbol2"], "")
        self.assertContains(compare, "Choose two symbols to compare")

        predict = self.client.get("/predict/")
        self.assertEqual(predict.context["symbol"], "")
        self.assertContains(predict, "What is AI Forecast")
        self.assertContains(predict, "Sanity-check a hunch")

    def test_local_tool_pages(self):
        portfolio = self.client.get("/portfolio/")
        self.assertTemplateUsed(portfolio, "portfolio.html")
        self.assertContains(portfolio, "My Portfolio")
        self.assertContains(portfolio, "LOCAL ONLY")
        self.assertContains(portfolio, 'href="/alerts/"')

        alerts = self.client.get("/alerts/")
        self.assertTemplateUsed(alerts, "alerts.html")
        self.assertContains(alerts, "Price & Forecast Alerts")
        self.assertContains(alerts, "forecast_above")
        self.assertContains(alerts, 'href="/portfolio/"')

    def test_api_endpoints(self):
        self.assertEqual(self.client.get("/api/health/").status_code, 200)
        response = self.client.get("/api/history/?symbol=TEST")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["rows"], 320)
        response = self.client.get("/api/quote/?symbol=TEST")
        self.assertEqual(response.json()["symbol"], "TEST")
        response = self.client.get("/api/quotes/?symbols=TEST,AAPL")
        self.assertEqual([q["symbol"] for q in response.json()["quotes"]], ["TEST", "AAPL"])
        response = self.client.get("/api/history/?symbol=TEST&refresh=never")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["source"], "cache")

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
        self.assertEqual(response.context["result"]["projected_change_pct"], 100.0)
        self.assertEqual(response.context["result"]["projected_high"], 2.0)

    def test_csv_download(self):
        response = self.client.get("/download/0/?symbol=TEST")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Date,Open,High,Low,Close,Volume", response.content)
