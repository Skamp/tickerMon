import gc
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from app.database.database import Database
from app.database.repositories import MarketDataRepository
from app.models.earnings import EarningsEvent, format_earnings_tooltip
from app.services.earnings_service import EarningsService, parse_earnings_dates


def make_df(rows, tz=None):
    index = pd.DatetimeIndex([pd.Timestamp(ts, tz=tz) for ts, _ in rows])
    data = [row for _, row in rows]
    return pd.DataFrame(data, index=index)


class TestParseEarningsDates(unittest.TestCase):
    def test_empty_dataframe(self):
        self.assertEqual(parse_earnings_dates(pd.DataFrame(), "TEST"), [])
        self.assertEqual(parse_earnings_dates(None, "TEST"), [])

    def test_confirmed_and_estimated_rows(self):
        df = make_df([
            ("2026-01-15", {
                "EPS Estimate": 1.50, "Reported EPS": 1.70, "Surprise(%)": 13.3,
            }),
            ("2026-04-15", {
                "EPS Estimate": 1.80, "Reported EPS": None, "Surprise(%)": None,
            }),
        ])
        events = parse_earnings_dates(df, "test")
        self.assertEqual(len(events), 2)
        self.assertFalse(events[0].is_estimated)
        self.assertAlmostEqual(events[0].reported_eps, 1.70)
        self.assertAlmostEqual(events[0].surprise_pct, 13.3)
        self.assertTrue(events[1].is_estimated)
        self.assertAlmostEqual(events[1].eps_estimate, 1.80)

    def test_symbol_uppercased(self):
        df = make_df([("2026-01-15", {"EPS Estimate": 1.0})])
        events = parse_earnings_dates(df, "sap.de")
        self.assertEqual(events[0].symbol, "SAP.DE")

    def test_tz_aware_index_keeps_exchange_wall_clock(self):
        df = make_df([("2026-01-15 00:00:00", {"EPS Estimate": 1.0})], tz="America/New_York")
        events = parse_earnings_dates(df, "TEST")
        self.assertEqual(events[0].event_date, "2026-01-15 00:00:00")

    def test_duplicate_date_prefers_reported_row(self):
        df = make_df([
            ("2026-01-15", {"EPS Estimate": 1.5, "Reported EPS": None}),
            ("2026-01-15", {"EPS Estimate": 1.5, "Reported EPS": 1.6}),
        ])
        events = parse_earnings_dates(df, "TEST")
        self.assertEqual(len(events), 1)
        self.assertFalse(events[0].is_estimated)
        self.assertAlmostEqual(events[0].reported_eps, 1.6)

    def test_events_sorted_by_date(self):
        df = make_df([
            ("2026-04-15", {"EPS Estimate": 1.0}),
            ("2026-01-15", {"EPS Estimate": 2.0}),
        ])
        events = parse_earnings_dates(df, "TEST")
        self.assertEqual([e.date_only for e in events], ["2026-01-15", "2026-04-15"])

    def test_nan_estimate_treated_as_missing(self):
        df = make_df([("2026-01-15", {"EPS Estimate": float("nan")})])
        events = parse_earnings_dates(df, "TEST")
        self.assertIsNone(events[0].eps_estimate)

    def test_quarter_and_timing_extracted(self):
        df = make_df([("2026-01-15", {"Quarter": "Q1 2026", "Timing": "AMC"})])
        events = parse_earnings_dates(df, "TEST")
        self.assertEqual(events[0].quarter, "Q1 2026")
        self.assertEqual(events[0].timing, "AMC")


class TestEarningsEvent(unittest.TestCase):
    def test_epoch_for_full_timestamp(self):
        event = EarningsEvent(symbol="TEST", event_date="2026-01-15 08:30:00")
        expected = datetime(2026, 1, 15, 8, 30).timestamp()
        self.assertAlmostEqual(event.epoch, expected)

    def test_epoch_for_date_only(self):
        event = EarningsEvent(symbol="TEST", event_date="2026-01-15")
        expected = datetime(2026, 1, 15).timestamp()
        self.assertAlmostEqual(event.epoch, expected)

    def test_epoch_nan_on_invalid_date(self):
        event = EarningsEvent(symbol="TEST", event_date="not-a-date")
        self.assertTrue(event.epoch != event.epoch)

    def test_date_only_property(self):
        event = EarningsEvent(symbol="TEST", event_date="2026-01-15 08:30:00")
        self.assertEqual(event.date_only, "2026-01-15")


class TestTooltipFormatting(unittest.TestCase):
    def test_confirmed_tooltip_full_fields(self):
        event = EarningsEvent(
            symbol="AAPL", event_date="2026-01-15 00:00:00",
            eps_estimate=1.5, reported_eps=1.7, surprise_pct=13.3,
            is_estimated=False, quarter="Q1 2026", timing="AMC",
        )
        text = format_earnings_tooltip(event, "Apple Inc.")
        self.assertIn("Apple Inc. — Earnings", text)
        self.assertIn("2026-01-15 (Confirmed)", text)
        self.assertIn("EPS Estimate: 1.50", text)
        self.assertIn("Reported EPS: 1.70", text)
        self.assertIn("EPS Surprise: +13.30%", text)
        self.assertIn("Period: Q1 2026", text)
        self.assertIn("Timing: AMC", text)

    def test_estimated_tooltip_omits_missing_fields(self):
        event = EarningsEvent(
            symbol="AAPL", event_date="2026-04-15 00:00:00",
            eps_estimate=1.8, is_estimated=True,
        )
        text = format_earnings_tooltip(event)
        self.assertIn("AAPL — Earnings", text)
        self.assertIn("(Estimated)", text)
        self.assertIn("EPS Estimate: 1.80", text)
        self.assertNotIn("Reported EPS", text)
        self.assertNotIn("Surprise", text)
        self.assertNotIn("Period", text)
        self.assertNotIn(": 0", text)

    def test_minimal_event_falls_back_to_symbol_and_date(self):
        event = EarningsEvent(symbol="MSFT", event_date="2026-07-01")
        text = format_earnings_tooltip(event)
        self.assertIn("MSFT — Earnings", text)
        self.assertIn("2026-07-01 (Confirmed)", text)


class TestEarningsRepository(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = Path(self.temp_dir.name) / "data" / "test_market_data.db"
        self.db = Database(self.db_path)
        self.repo = MarketDataRepository(self.db)

    def tearDown(self):
        gc.collect()
        self.temp_dir.cleanup()

    def test_replace_and_get_roundtrip(self):
        events = [
            EarningsEvent(symbol="TEST", event_date="2026-01-15 00:00:00",
                          eps_estimate=1.0, reported_eps=1.2, surprise_pct=20.0),
            EarningsEvent(symbol="TEST", event_date="2026-04-15 00:00:00",
                          eps_estimate=1.1, is_estimated=True),
        ]
        self.repo.replace_earnings("TEST", events)
        loaded = self.repo.get_earnings("TEST")
        self.assertEqual(len(loaded), 2)
        self.assertAlmostEqual(loaded[0].reported_eps, 1.2)
        self.assertTrue(loaded[1].is_estimated)

    def test_replace_is_idempotent(self):
        events = [EarningsEvent(symbol="TEST", event_date="2026-01-15 00:00:00")]
        self.repo.replace_earnings("TEST", events)
        self.repo.replace_earnings("TEST", events)
        self.assertEqual(len(self.repo.get_earnings("TEST")), 1)

    def test_fetch_timestamp_roundtrip(self):
        self.assertIsNone(self.repo.get_earnings_fetched_at("TEST"))
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.repo.set_earnings_fetched_at("TEST", now)
        self.assertEqual(self.repo.get_earnings_fetched_at("TEST"), now)


class StubYahooService:
    def __init__(self, df=None, error=None):
        self._df = df
        self._error = error
        self.calls = []

    def fetch_earnings_dates(self, symbol):
        self.calls.append(symbol)
        if self._error is not None:
            raise self._error
        return self._df


class TestEarningsService(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = Path(self.temp_dir.name) / "data" / "test_market_data.db"
        self.db = Database(self.db_path)
        self.repo = MarketDataRepository(self.db)

    def tearDown(self):
        gc.collect()
        self.temp_dir.cleanup()

    def test_is_stale_when_nothing_cached(self):
        service = EarningsService(StubYahooService(), self.repo)
        self.assertTrue(service.is_stale("TEST"))

    def test_is_not_stale_right_after_refresh(self):
        df = make_df([("2026-01-15", {"EPS Estimate": 1.0})])
        service = EarningsService(StubYahooService(df=df), self.repo)
        service.refresh("TEST")
        self.assertFalse(service.is_stale("TEST"))

    def test_is_stale_when_older_than_ttl(self):
        old = (datetime.now() - timedelta(hours=24 * 8)).strftime("%Y-%m-%d %H:%M:%S")
        self.repo.set_earnings_fetched_at("TEST", old)
        service = EarningsService(StubYahooService(), self.repo)
        self.assertTrue(service.is_stale("TEST"))

    def test_refresh_caches_events_and_symbol_is_normalized(self):
        df = make_df([("2026-01-15", {"EPS Estimate": 1.0, "Reported EPS": 1.1})])
        yahoo = StubYahooService(df=df)
        service = EarningsService(yahoo, self.repo)
        events = service.refresh("test")
        self.assertEqual(yahoo.calls, ["TEST"])
        self.assertEqual(len(events), 1)
        self.assertEqual(len(self.repo.get_earnings("TEST")), 1)
        self.assertIsNotNone(self.repo.get_earnings_fetched_at("TEST"))

    def test_refresh_failure_preserves_cache(self):
        first_df = make_df([("2026-01-15", {"EPS Estimate": 1.0})])
        EarningsService(StubYahooService(df=first_df), self.repo).refresh("TEST")

        failing = EarningsService(StubYahooService(error=RuntimeError("network")), self.repo)
        events = failing.refresh("TEST")
        self.assertEqual(len(events), 1)
        self.assertEqual(len(self.repo.get_earnings("TEST")), 1)

    def test_get_events_reads_cache_without_network(self):
        df = make_df([("2026-01-15", {"EPS Estimate": 1.0})])
        EarningsService(StubYahooService(df=df), self.repo).refresh("TEST")
        yahoo = StubYahooService(error=RuntimeError("must not be called"))
        service = EarningsService(yahoo, self.repo)
        events = service.get_events("TEST")
        self.assertEqual(len(events), 1)
        self.assertEqual(yahoo.calls, [])


if __name__ == "__main__":
    unittest.main()
