import gc
import math
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from app.config.config_manager import ConfigManager
from app.database.database import Database
from app.database.repositories import ForecastRepository, MarketDataRepository
from app.models.forecast import (
    EVALUATION_EVALUATED,
    EVALUATION_PENDING,
    EVALUATION_UNAVAILABLE,
    Forecast,
    ForecastHorizon,
    forecast_matches_filter,
    normalize_forecast_filter,
)
from app.services.forecast_engine import FORECAST_MODEL_VERSION, MIN_SESSIONS
from app.services.forecast_service import ForecastService
from app.services.market_data_service import MarketDataService
from app.services.ticker_service import TickerService


def make_forecast(ticker="AAPL", generated_at="2026-10-20 10:00:00",
                  reference_date="2026-10-19", target_date="2026-10-21",
                  central=110.0, reference_close=100.0):
    return Forecast(
        ticker=ticker,
        generated_at=generated_at,
        reference_date=reference_date,
        reference_close=reference_close,
        target_date=target_date,
        horizon_months=1,
        directional_bias="Bullish",
        central_estimate=central,
        lower_estimate=95.0,
        upper_estimate=125.0,
        expected_change_pct=(central - reference_close) / reference_close * 100.0,
        model_version=FORECAST_MODEL_VERSION,
        input_snapshot={
            "sigma_daily": 0.01,
            "mu_daily": 0.001,
            "band_z": 1.0,
            "n_sessions": 21,
            "median_gap": 86400.0,
            "reference_epoch": 1761129600.0,
        },
        signal_summary={"score": 0.3, "bias": "Bullish", "supporting": [], "assumptions": []},
        currency_code="USD",
    )


def insert_daily_prices(repo: MarketDataRepository, symbol: str, n: int, end_date: date,
                        start_price: float = 100.0, drift: float = 0.001):
    """Inserts n consecutive calendar-day rows ending on ``end_date``."""
    dates = pd.date_range(end=end_date, periods=n, freq="D")
    closes = [start_price * math.exp(drift * i) for i in range(n)]
    df = pd.DataFrame(
        {
            "Open": [c * 0.999 for c in closes],
            "High": [c * 1.01 for c in closes],
            "Low": [c * 0.99 for c in closes],
            "Close": closes,
            "Adj Close": closes,
            "Volume": [1000 + i for i in range(n)],
        },
        index=dates,
    )
    return repo.upsert_price_data(symbol, df)


class ForecastServiceTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self.temp_dir.name)
        self.db = Database(root / "data" / "test_market_data.db")
        self.price_repo = MarketDataRepository(self.db)
        self.forecast_repo = ForecastRepository(self.db)
        self.config_manager = ConfigManager(root / "config" / "tickers.json")
        self.ticker_service = TickerService(self.config_manager)
        self.market_data_service = MarketDataService(self.price_repo)
        self.service = ForecastService(
            self.market_data_service,
            self.ticker_service,
            self.forecast_repo,
            price_repo=self.price_repo,
        )

    def tearDown(self):
        gc.collect()
        self.temp_dir.cleanup()


class TestForecastGeneration(ForecastServiceTestCase):
    def test_generate_uses_local_history_only(self):
        insert_daily_prices(self.price_repo, "AAPL", 120, date(2026, 10, 20))
        forecast = self.service.generate("AAPL", ForecastHorizon.ONE_MONTH)
        self.assertEqual(forecast.ticker, "AAPL")
        self.assertEqual(forecast.horizon_months, 1)
        self.assertEqual(forecast.model_version, FORECAST_MODEL_VERSION)

    def test_generate_insufficient_history_raises(self):
        insert_daily_prices(self.price_repo, "AAPL", MIN_SESSIONS - 1, date(2026, 10, 20))
        with self.assertRaises(Exception):
            self.service.generate("AAPL", ForecastHorizon.ONE_MONTH)

    def test_generate_off_horizon_raises(self):
        insert_daily_prices(self.price_repo, "AAPL", 120, date(2026, 10, 20))
        with self.assertRaises(Exception):
            self.service.generate("AAPL", ForecastHorizon.OFF)


class TestForecastSave(ForecastServiceTestCase):
    def test_save_valid_forecast(self):
        ok, message, is_duplicate = self.service.save(make_forecast())
        self.assertTrue(ok)
        self.assertFalse(is_duplicate)
        self.assertIn("saved", message.lower())

    def test_duplicate_flagged(self):
        forecast = make_forecast()
        self.service.save(forecast)
        ok, _, is_duplicate = self.service.save(forecast)
        self.assertTrue(ok)
        self.assertTrue(is_duplicate)

    def test_invalid_forecast_rejected(self):
        bad = make_forecast()
        bad.central_estimate = 0.0
        ok, message, _ = self.service.save(bad)
        self.assertFalse(ok)
        self.assertIn("invalid", message.lower())


class TestForecastEvaluation(ForecastServiceTestCase):
    def test_pending_before_target_stays_pending(self):
        insert_daily_prices(self.price_repo, "AAPL", 60, date.today())
        self.service.save(make_forecast(target_date="2099-01-01"))
        evaluated, unavailable, pending = self.service.evaluate_pending()
        self.assertEqual((evaluated, unavailable), (0, 0))
        self.assertEqual(pending, 1)

    def test_due_forecast_evaluated_against_first_close_on_or_after_target(self):
        # Prices through Oct 22; target Oct 21 -> first close >= target is Oct 21.
        insert_daily_prices(self.price_repo, "AAPL", 60, date(2026, 10, 22),
                            start_price=100.0, drift=0.0)
        # flat closes at 100.0
        self.service.save(make_forecast(target_date="2026-10-21", central=100.0,
                                        reference_close=100.0))
        evaluated, unavailable, pending = self.service.evaluate_pending()
        self.assertEqual(evaluated, 1)
        self.assertEqual(pending, 0)
        record = self.service.load_saved()[0]
        self.assertEqual(record.evaluation_status, EVALUATION_EVALUATED)
        self.assertEqual(record.actual_date, "2026-10-21")
        self.assertAlmostEqual(record.actual_price, 100.0, places=6)
        self.assertAlmostEqual(record.absolute_error, 0.0, places=6)

    def test_evaluation_is_idempotent(self):
        insert_daily_prices(self.price_repo, "AAPL", 60, date(2026, 10, 22),
                            start_price=100.0, drift=0.0)
        self.service.save(make_forecast(target_date="2026-10-21"))
        first_evaluated, _, _ = self.service.evaluate_pending()
        second_evaluated, _, pending = self.service.evaluate_pending()
        self.assertEqual(first_evaluated, 1)
        self.assertEqual(second_evaluated, 0)
        self.assertEqual(pending, 0)
        records = self.service.load_saved()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].evaluation_status, EVALUATION_EVALUATED)

    def test_missing_ticker_marked_unavailable(self):
        self.service.save(make_forecast(ticker="NODATA", target_date="2020-01-02"))
        evaluated, unavailable, pending = self.service.evaluate_pending()
        self.assertEqual(unavailable, 1)
        record = self.service.load_saved(ticker="NODATA")[0]
        self.assertEqual(record.evaluation_status, EVALUATION_UNAVAILABLE)
        # Prediction fields remain intact.
        self.assertEqual(record.forecast.central_estimate, 110.0)

    def test_data_not_reaching_target_stays_pending(self):
        # Latest data Oct 2020, target Oct 2026: target passed but data never reached it.
        insert_daily_prices(self.price_repo, "AAPL", 60, date(2020, 10, 20))
        self.service.save(make_forecast(ticker="AAPL", target_date="2026-10-21"))
        evaluated, unavailable, pending = self.service.evaluate_pending()
        self.assertEqual(evaluated, 0)
        self.assertEqual(unavailable, 0)
        self.assertEqual(pending, 1)


class TestAccuracyStats(ForecastServiceTestCase):
    def test_stats_over_evaluated_records(self):
        insert_daily_prices(self.price_repo, "AAPL", 60, date(2026, 10, 22),
                            start_price=100.0, drift=0.0)
        # Bullish forecast that was correct (actual 100 vs ref 100: flat actual -> excluded from directional)
        self.service.save(make_forecast(
            generated_at="2026-10-01 10:00:00", target_date="2026-10-21",
            central=102.0, reference_close=100.0,
        ))
        self.service.save(make_forecast(
            generated_at="2026-10-02 10:00:00", target_date="2026-10-21",
            central=98.0, reference_close=100.0,
        ))
        self.service.save(make_forecast(
            generated_at="2026-10-03 10:00:00", target_date="2026-10-21",
            central=101.0, reference_close=100.0,
        ))
        self.service.evaluate_pending()
        stats = self.service.accuracy_stats()
        self.assertEqual(stats.overall.n_evaluated, 3)
        self.assertEqual(stats.overall.n_pending, 0)
        self.assertIsNotNone(stats.overall.mean_absolute_error)
        self.assertIsNotNone(stats.overall.mape)
        self.assertIn(1, stats.by_horizon)
        self.assertIn("AAPL", stats.by_ticker)
        self.assertIn(FORECAST_MODEL_VERSION, stats.by_model)

    def test_directional_accuracy_neutral_abstains(self):
        insert_daily_prices(self.price_repo, "AAPL", 60, date(2026, 10, 22),
                            start_price=100.0, drift=0.01)
        for i in range(3):
            forecast = make_forecast(
                generated_at=f"2026-10-0{i + 1} 10:00:00",
                target_date="2026-10-21",
                central=105.0,
                reference_close=100.0,
            )
            forecast.expected_change_pct = 0.0  # neutral prediction
            forecast.directional_bias = "Neutral"
            self.service.save(forecast)
        self.service.evaluate_pending()
        stats = self.service.accuracy_stats()
        self.assertEqual(stats.overall.n_evaluated, 3)
        # All predictions neutral -> directional accuracy abstains.
        self.assertIsNone(stats.overall.directional_accuracy)


class TestWalkForward(ForecastServiceTestCase):
    def test_walk_forward_runs_chronologically(self):
        insert_daily_prices(self.price_repo, "AAPL", 320, date(2026, 10, 20),
                            start_price=100.0, drift=0.001)
        result = self.service.walk_forward_validate("AAPL", ForecastHorizon.ONE_MONTH)
        self.assertGreater(result.n_origins, 0)
        self.assertIsNotNone(result.mean_absolute_error)
        self.assertIsNotNone(result.mape)

    def test_walk_forward_insufficient_history(self):
        insert_daily_prices(self.price_repo, "AAPL", 100, date(2026, 10, 20))
        result = self.service.walk_forward_validate("AAPL", ForecastHorizon.ONE_MONTH)
        self.assertEqual(result.n_origins, 0)
        self.assertTrue(result.errors)

    def test_walk_forward_look_ahead_free(self):
        """Forecast at each origin only uses the truncated series."""
        insert_daily_prices(self.price_repo, "AAPL", 300, date(2026, 10, 20),
                            start_price=100.0, drift=0.001)
        result = self.service.walk_forward_validate(
            "AAPL", ForecastHorizon.ONE_MONTH, min_history=252, step=42, max_origins=3
        )
        self.assertLessEqual(result.n_origins, 3)
        if result.n_origins >= 2:
            self.assertIsNotNone(result.directional_accuracy)


class TestForecastAnnotationConfig(ForecastServiceTestCase):
    def test_defaults_to_top_right(self):
        self.assertEqual(self.ticker_service.get_forecast_annotation_anchor(), "top_right")

    def test_roundtrip_and_normalization(self):
        for anchor in ("bottom_left", "hidden", "top_left"):
            self.assertTrue(self.ticker_service.set_forecast_annotation_anchor(anchor))
            self.assertEqual(self.ticker_service.get_forecast_annotation_anchor(), anchor)
        self.ticker_service.set_forecast_annotation_anchor("not_a_corner")
        self.assertEqual(self.ticker_service.get_forecast_annotation_anchor(), "top_right")


class TestDelete(ForecastServiceTestCase):
    def test_delete_and_older_than(self):
        self.service.save(make_forecast(generated_at="2020-01-01 10:00:00"))
        recent = self.service.save(make_forecast(generated_at="2026-10-20 10:00:00"))
        deleted = self.service.delete_older_than(365)
        self.assertEqual(deleted, 1)
        remaining = self.service.load_saved()
        self.assertEqual(len(remaining), 1)
        deleted_two = self.service.delete([remaining[0].id])
        self.assertEqual(deleted_two, 1)


class TestForecastFilterHelpers(unittest.TestCase):
    def test_normalize_defaults_and_valid_keys(self):
        self.assertEqual(normalize_forecast_filter(None), "off")
        self.assertEqual(normalize_forecast_filter(42), "off")
        self.assertEqual(normalize_forecast_filter("bogus"), "off")
        self.assertEqual(normalize_forecast_filter("Bullish"), "bullish")
        self.assertEqual(normalize_forecast_filter("  Any  "), "any")
        for key in ("off", "bullish", "bearish", "neutral", "any"):
            self.assertEqual(normalize_forecast_filter(key), key)

    def test_off_matches_everything(self):
        self.assertTrue(forecast_matches_filter(None, "off"))
        self.assertTrue(forecast_matches_filter(make_forecast(), "off"))

    def test_any_requires_a_forecast(self):
        self.assertFalse(forecast_matches_filter(None, "any"))
        self.assertTrue(forecast_matches_filter(make_forecast(), "any"))

    def test_direction_keys_match_bias(self):
        bullish = make_forecast()
        bullish.directional_bias = "Bullish"
        bearish = make_forecast()
        bearish.directional_bias = "Bearish"
        neutral = make_forecast()
        neutral.directional_bias = "Neutral"
        self.assertTrue(forecast_matches_filter(bullish, "bullish"))
        self.assertFalse(forecast_matches_filter(bearish, "bullish"))
        self.assertTrue(forecast_matches_filter(bearish, "bearish"))
        self.assertTrue(forecast_matches_filter(neutral, "neutral"))
        self.assertFalse(forecast_matches_filter(neutral, "bullish"))


class TestLatestForecastByTicker(ForecastServiceTestCase):
    def test_returns_newest_forecast_per_ticker(self):
        older = make_forecast(ticker="AAPL", generated_at="2026-10-19 10:00:00")
        older.directional_bias = "Bullish"
        newer = make_forecast(ticker="AAPL", generated_at="2026-10-20 10:00:00")
        newer.directional_bias = "Bearish"
        other = make_forecast(ticker="MSFT", generated_at="2026-10-20 11:00:00")
        for forecast in (older, newer, other):
            ok, message, _ = self.service.save(forecast)
            self.assertTrue(ok, message)
        latest = self.service.latest_forecast_by_ticker()
        self.assertEqual(set(latest), {"AAPL", "MSFT"})
        self.assertEqual(latest["AAPL"].directional_bias, "Bearish")
        self.assertEqual(latest["MSFT"].directional_bias, "Bullish")

    def test_empty_database_returns_empty_map(self):
        self.assertEqual(self.service.latest_forecast_by_ticker(), {})


class TestForecastFilterPersistence(ForecastServiceTestCase):
    def test_defaults_to_off(self):
        self.assertEqual(self.ticker_service.get_forecast_filter(), "off")

    def test_roundtrip_and_normalization(self):
        for key in ("bullish", "bearish", "neutral", "any"):
            self.assertTrue(self.ticker_service.set_forecast_filter(key))
            self.assertEqual(self.ticker_service.get_forecast_filter(), key)
        self.ticker_service.set_forecast_filter("not_a_filter")
        self.assertEqual(self.ticker_service.get_forecast_filter(), "off")


if __name__ == "__main__":
    unittest.main()
