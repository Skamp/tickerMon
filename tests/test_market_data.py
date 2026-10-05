import gc
import math
import tempfile
import unittest
from unittest.mock import MagicMock
from pathlib import Path
import pandas as pd

from app.database.database import Database
from app.database.repositories import MarketDataRepository
from app.services.market_data_service import (
    MarketDataService,
    classify_price_series,
    count_trend_buckets,
    is_swing_series,
)
from app.services.swing_detection import SwingAlgorithm
from app.services.sync_service import SyncService
from app.services.yahoo_service import YahooService
from app.models.ticker import TickerConfig
from app.models.time_range import TimeRange
from app.models.trend import TrendBucket


class TestMarketData(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = Path(self.temp_dir.name) / "data" / "test_market_data.db"
        self.db = Database(self.db_path)
        self.repo = MarketDataRepository(self.db)
        self.market_data_service = MarketDataService(self.repo)

    def tearDown(self):
        gc.collect()
        self.temp_dir.cleanup()

    def test_empty_chart_data(self):
        ts, prices, labels = self.market_data_service.get_chart_data("AAPL", TimeRange.ONE_YEAR)
        self.assertEqual(ts, [])
        self.assertEqual(prices, [])
        self.assertEqual(labels, [])

    def test_summary_calculation(self):
        dates = pd.date_range("2026-01-01", periods=2, freq="D")
        df = pd.DataFrame({
            "Open": [100.0, 105.0],
            "High": [105.0, 110.0],
            "Low": [99.0, 104.0],
            "Close": [100.0, 110.0],
            "Adj Close": [100.0, 110.0],
            "Volume": [1000, 1500],
        }, index=dates)

        self.repo.upsert_price_data("NVDA", df)
        cfg = TickerConfig("NVDA", "NVIDIA Corporation", True)

        summary = self.market_data_service.get_ticker_summary(cfg)
        self.assertEqual(summary.current_price, 110.0)
        self.assertEqual(summary.price_change, 10.0)
        self.assertEqual(summary.pct_change, 10.0)

    def test_mocked_sync_service(self):
        mock_yahoo = MagicMock(spec=YahooService)
        dates = pd.date_range("2026-01-01", periods=3, freq="D")
        df_fake = pd.DataFrame({
            "Open": [200.0, 202.0, 204.0],
            "High": [205.0, 206.0, 208.0],
            "Low": [199.0, 201.0, 203.0],
            "Close": [202.0, 205.0, 207.0],
            "Adj Close": [202.0, 205.0, 207.0],
            "Volume": [5000, 5500, 6000],
        }, index=dates)

        mock_yahoo.fetch_ticker_data.return_value = (df_fake, {
            "symbol": "GOOGL",
            "company_name": "Alphabet Inc.",
            "currency": "USD",
            "exchange": "NASDAQ",
        })

        sync = SyncService(mock_yahoo, self.repo)
        ok, msg, count = sync.sync_ticker("GOOGL")

        self.assertTrue(ok)
        self.assertEqual(count, 3)

        points = self.repo.get_prices("GOOGL")
        self.assertEqual(len(points), 3)

    def test_classify_price_series(self):
        self.assertEqual(classify_price_series([]), TrendBucket.UNSURE)
        self.assertEqual(classify_price_series([100.0]), TrendBucket.UNSURE)
        self.assertEqual(classify_price_series([100.0, 105.0]), TrendBucket.RISE)
        self.assertEqual(classify_price_series([100.0, 102.0]), TrendBucket.RISE)
        self.assertEqual(classify_price_series([100.0, 98.0]), TrendBucket.DOWN)
        self.assertEqual(classify_price_series([100.0, 98.1]), TrendBucket.LATERAL)
        self.assertEqual(classify_price_series([100.0, 101.9]), TrendBucket.LATERAL)

    def test_count_trend_buckets(self):
        trends = {
            "AAA": TrendBucket.RISE,
            "BBB": TrendBucket.RISE,
            "CCC": TrendBucket.DOWN,
            "DDD": TrendBucket.UNSURE,
        }
        counts = count_trend_buckets(trends)
        self.assertEqual(counts[TrendBucket.RISE], 2)
        self.assertEqual(counts[TrendBucket.DOWN], 1)
        self.assertEqual(counts[TrendBucket.LATERAL], 0)
        self.assertEqual(counts[TrendBucket.UNSURE], 1)

    def test_is_swing_series(self):
        self.assertFalse(is_swing_series([]))
        self.assertFalse(is_swing_series([100.0]))
        self.assertTrue(is_swing_series([100.0, 110.0]))
        self.assertFalse(is_swing_series([100.0, 109.9]))
        self.assertTrue(is_swing_series([110.0, 100.0]))
        self.assertFalse(is_swing_series([100.0, 105.0, 100.0]))
        self.assertTrue(is_swing_series([110.0, 99.0, 110.0]))

    def _seed_series(self, symbol: str, start_price: float, end_price: float, end_days_ago: int = 0, periods: int = 30) -> None:
        end_date = pd.Timestamp.now().normalize() - pd.Timedelta(days=end_days_ago)
        dates = pd.date_range(end=end_date, periods=periods, freq="D")
        closes = [start_price + (end_price - start_price) * i / (periods - 1) for i in range(periods)]
        df = pd.DataFrame({
            "Open": closes,
            "High": closes,
            "Low": closes,
            "Close": closes,
            "Adj Close": closes,
            "Volume": [1000] * periods,
        }, index=dates)
        self.repo.upsert_price_data(symbol, df)

    def _seed_closes(self, symbol: str, closes) -> None:
        end_date = pd.Timestamp.now().normalize()
        dates = pd.date_range(end=end_date, periods=len(closes), freq="D")
        df = pd.DataFrame({
            "Open": closes,
            "High": closes,
            "Low": closes,
            "Close": closes,
            "Adj Close": closes,
            "Volume": [1000] * len(closes),
        }, index=dates)
        self.repo.upsert_price_data(symbol, df)

    def test_get_trend_buckets(self):
        self._seed_series("AAA", 100.0, 130.0)
        self._seed_series("BBB", 100.0, 60.0)
        self._seed_series("CCC", 100.0, 100.0)
        self._seed_series("EEE", 100.0, 130.0, end_days_ago=70)

        configs = [
            TickerConfig("AAA", "Rising", True),
            TickerConfig("BBB", "Falling", True),
            TickerConfig("CCC", "Flat", True),
            TickerConfig("DDD", "No Data", True),
            TickerConfig("EEE", "Old Data", True),
        ]

        buckets = self.market_data_service.get_trend_buckets(configs, TimeRange.ONE_YEAR)
        self.assertEqual(buckets["AAA"], TrendBucket.RISE)
        self.assertEqual(buckets["BBB"], TrendBucket.DOWN)
        self.assertEqual(buckets["CCC"], TrendBucket.LATERAL)
        self.assertEqual(buckets["DDD"], TrendBucket.UNSURE)
        self.assertEqual(buckets["EEE"], TrendBucket.RISE)

        month_buckets = self.market_data_service.get_trend_buckets(configs, TimeRange.ONE_MONTH)
        self.assertEqual(month_buckets["EEE"], TrendBucket.UNSURE)
        self.assertEqual(month_buckets["AAA"], TrendBucket.RISE)

    def test_get_swing_symbols(self):
        self._seed_series("SWG", 100.0, 140.0)
        self._seed_series("FLAT", 100.0, 100.0)
        self._seed_series("MILD", 100.0, 105.0)

        configs = [
            TickerConfig("SWG", "Wide", True),
            TickerConfig("FLAT", "Flat", True),
            TickerConfig("MILD", "Mild", True),
            TickerConfig("NONE", "No Data", True),
        ]

        swings = self.market_data_service.get_swing_symbols(configs, TimeRange.ONE_YEAR)
        self.assertEqual(swings, {"SWG"})

        buckets = self.market_data_service.get_trend_buckets(configs, TimeRange.ONE_YEAR)
        self.assertEqual(buckets["SWG"], TrendBucket.RISE, "swing overlaps with trend buckets")

    def test_get_swing_symbols_with_algorithm(self):
        zigzag_series = [100.0, 106.0, 100.5, 109.0, 103.5, 113.0]
        self._seed_closes("ZZ", zigzag_series)

        configs = [TickerConfig("ZZ", "ZigZag Case", True)]

        legacy = self.market_data_service.get_swing_symbols(configs, TimeRange.ONE_YEAR)
        zigzag = self.market_data_service.get_swing_symbols(configs, TimeRange.ONE_YEAR, SwingAlgorithm.ZIGZAG)

        self.assertEqual(legacy, {"ZZ"})
        self.assertEqual(zigzag, set())

    def test_detect_swing_pivots_range_includes_low_and_high(self):
        closes = [100.0, 104.0, 112.0, 108.0, 95.0, 101.0, 118.0, 110.0]
        self._seed_closes("PVT", closes)
        _, prices, _ = self.market_data_service.get_chart_data("PVT", TimeRange.ONE_YEAR)

        pivots = self.market_data_service.detect_swing_pivots(
            "PVT", TimeRange.ONE_YEAR, prices, SwingAlgorithm.RANGE
        )

        self.assertEqual(pivots, sorted(set(pivots)))
        self.assertIn(prices.index(min(prices)), pivots)
        self.assertIn(prices.index(max(prices)), pivots)
        self.assertIn(0, pivots)
        self.assertIn(len(prices) - 1, pivots)

    def test_detect_swing_pivots_with_algorithm_and_params(self):
        zigzag_series = [100.0, 106.0, 100.5, 109.0, 103.5, 113.0, 105.0, 118.0]
        self._seed_closes("PVT2", zigzag_series)
        _, prices, _ = self.market_data_service.get_chart_data("PVT2", TimeRange.ONE_YEAR)

        loose = self.market_data_service.detect_swing_pivots(
            "PVT2", TimeRange.ONE_YEAR, prices, SwingAlgorithm.ZIGZAG,
            params={"threshold_pct": 40.0},
        )
        strict = self.market_data_service.detect_swing_pivots(
            "PVT2", TimeRange.ONE_YEAR, prices, SwingAlgorithm.ZIGZAG,
            params={"threshold_pct": 2.0},
        )

        for pivots in (loose, strict):
            self.assertEqual(pivots, sorted(set(pivots)))
            self.assertTrue(all(0 <= i < len(prices) for i in pivots))
        self.assertLessEqual(len(loose), len(strict))

    def test_detect_swing_pivots_empty_prices(self):
        pivots = self.market_data_service.detect_swing_pivots(
            "MISSING", TimeRange.ONE_YEAR, [], SwingAlgorithm.RSI
        )
        self.assertEqual(pivots, [])

    def _seed_swingy_series(self, symbol: str, periods: int = 120) -> None:
        closes = [100.0 + 30.0 * math.sin(i / 3.0) for i in range(periods)]
        self._seed_closes(symbol, closes)

    def test_get_swing_symbols_with_range_settings(self):
        self._seed_swingy_series("RSW")
        configs = [TickerConfig("RSW", "Range Case", True)]
        params = {"threshold_pct": 2.0}

        unfiltered = self.market_data_service.get_swing_symbols(
            configs, TimeRange.ONE_YEAR, SwingAlgorithm.ZIGZAG, params=params
        )
        self.assertEqual(unfiltered, {"RSW"})

        min_8_weeks = self.market_data_service.get_swing_symbols(
            configs,
            TimeRange.ONE_YEAR,
            SwingAlgorithm.ZIGZAG,
            params=params,
            range_settings={"mode": "Minimum duration", "value": 8, "value_max": 0, "unit": "weeks"},
        )
        self.assertEqual(min_8_weeks, set())

        min_1_week = self.market_data_service.get_swing_symbols(
            configs,
            TimeRange.ONE_YEAR,
            SwingAlgorithm.ZIGZAG,
            params=params,
            range_settings={"mode": "Minimum duration", "value": 1, "value_max": 0, "unit": "weeks"},
        )
        self.assertEqual(min_1_week, {"RSW"})

    def test_get_swing_symbols_with_lookback_range(self):
        self._seed_swingy_series("LBW")
        configs = [TickerConfig("LBW", "Lookback Case", True)]
        params = {"threshold_pct": 2.0}

        recent = self.market_data_service.get_swing_symbols(
            configs,
            TimeRange.ONE_YEAR,
            SwingAlgorithm.ZIGZAG,
            params=params,
            range_settings={"mode": "Lookback window", "value": 1, "value_max": 0, "unit": "months"},
        )
        self.assertEqual(recent, {"LBW"})

        timestamps, prices, _ = self.market_data_service.get_chart_data("LBW", TimeRange.ONE_YEAR)
        _, legs_week = self.market_data_service.detect_swing_overlay(
            "LBW",
            TimeRange.ONE_YEAR,
            prices,
            timestamps,
            SwingAlgorithm.ZIGZAG,
            params,
            {"mode": "Lookback window", "value": 1, "value_max": 0, "unit": "weeks"},
        )
        _, legs_month = self.market_data_service.detect_swing_overlay(
            "LBW",
            TimeRange.ONE_YEAR,
            prices,
            timestamps,
            SwingAlgorithm.ZIGZAG,
            params,
            {"mode": "Lookback window", "value": 1, "value_max": 0, "unit": "months"},
        )
        self.assertLessEqual(len(legs_week), len(legs_month))
        for start, end in legs_week:
            self.assertLessEqual(timestamps[end] - timestamps[start], 7 * 86400 + 1)

    def test_detect_swing_overlay_returns_legs(self):
        self._seed_swingy_series("OVL")
        timestamps, prices, _ = self.market_data_service.get_chart_data("OVL", TimeRange.ONE_YEAR)
        params = {"threshold_pct": 2.0}

        pivots, legs = self.market_data_service.detect_swing_overlay(
            "OVL",
            TimeRange.ONE_YEAR,
            prices,
            timestamps,
            SwingAlgorithm.ZIGZAG,
            params,
            None,
        )
        self.assertGreater(len(legs), 1)
        self.assertEqual(sorted({i for leg in legs for i in leg}), pivots)
        for start, end in legs:
            self.assertLess(start, end)

        filtered_pivots, filtered_legs = self.market_data_service.detect_swing_overlay(
            "OVL",
            TimeRange.ONE_YEAR,
            prices,
            timestamps,
            SwingAlgorithm.ZIGZAG,
            params,
            {"mode": "Minimum duration", "value": 8, "value_max": 0, "unit": "weeks"},
        )
        self.assertEqual(filtered_legs, [])
        self.assertEqual(filtered_pivots, [])

    def test_chart_ohlcv_alignment(self):
        self._seed_series("ALGN", 100.0, 140.0)

        _, prices, _ = self.market_data_service.get_chart_data("ALGN", TimeRange.ONE_YEAR)
        opens, highs, lows = self.market_data_service.get_chart_ohlcv("ALGN", TimeRange.ONE_YEAR)

        self.assertEqual(len(opens), len(prices))
        self.assertEqual(len(highs), len(prices))
        self.assertEqual(len(lows), len(prices))
        for open_, high, low, price in zip(opens, highs, lows, prices):
            self.assertGreaterEqual(high, max(open_, price))
            self.assertLessEqual(low, min(open_, price))

    def test_chart_ohlcv_scales_to_adjusted_close(self):
        dates = pd.date_range(end=pd.Timestamp.now().normalize(), periods=3, freq="D")
        df = pd.DataFrame({
            "Open": [100.0, 101.0, 102.0],
            "High": [105.0, 106.0, 107.0],
            "Low": [95.0, 96.0, 97.0],
            "Close": [100.0, 101.0, 102.0],
            "Adj Close": [50.0, 50.5, 51.0],
            "Volume": [1000, 1000, 1000],
        }, index=dates)
        self.repo.upsert_price_data("ADJ", df)

        _, prices, _ = self.market_data_service.get_chart_data("ADJ", TimeRange.ONE_YEAR)
        opens, highs, lows = self.market_data_service.get_chart_ohlcv("ADJ", TimeRange.ONE_YEAR)

        self.assertEqual(prices, [50.0, 50.5, 51.0])
        self.assertAlmostEqual(opens[0], 50.0)
        self.assertAlmostEqual(highs[0], 52.5)
        self.assertAlmostEqual(lows[0], 47.5)


if __name__ == "__main__":
    unittest.main()
