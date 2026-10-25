import gc
import json
import math
import tempfile
import unittest
from pathlib import Path

from app.database.database import Database
from app.database.repositories import ForecastRepository
from app.models.forecast import (
    EVALUATION_EVALUATED,
    EVALUATION_PENDING,
    EVALUATION_UNAVAILABLE,
    Forecast,
    SavedForecast,
    now_iso,
    rebuild_projection,
)


def make_forecast(
    ticker="AAPL",
    generated_at="2026-10-24 10:00:00",
    reference_date="2026-10-23",
    target_date="2026-11-23",
    horizon_months=1,
    central=260.0,
):
    n_sessions = 21
    mu_daily = math.log(central / 250.0) / n_sessions
    return Forecast(
        ticker=ticker,
        generated_at=generated_at,
        reference_date=reference_date,
        reference_close=250.0,
        target_date=target_date,
        horizon_months=horizon_months,
        directional_bias="Bullish",
        central_estimate=central,
        lower_estimate=242.0,
        upper_estimate=278.0,
        expected_change_pct=4.0,
        model_version="baseline_v1",
        input_snapshot={
            "sigma_daily": 0.015,
            "mu_daily": mu_daily,
            "band_z": 1.0,
            "n_sessions": n_sessions,
            "median_gap": 86400.0,
            "reference_epoch": 1761129600.0,
            "filter": "EMA 20",
        },
        signal_summary={
            "score": 0.4,
            "bias": "Bullish",
            "supporting": ["Close above EMA 20"],
            "assumptions": ["Estimated range, not support/resistance."],
        },
        currency_code="USD",
    )


class TestForecastRepository(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = Path(self.temp_dir.name) / "data" / "test_market_data.db"
        self.db = Database(self.db_path)
        self.repo = ForecastRepository(self.db)

    def tearDown(self):
        gc.collect()
        self.temp_dir.cleanup()

    def test_schema_has_forecasts_table(self):
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row[0] for row in cursor.fetchall()]
        conn.close()
        self.assertIn("forecasts", tables)

    def test_save_and_load_roundtrip(self):
        forecast = make_forecast()
        forecast_id = self.repo.save_forecast(forecast)
        self.assertGreater(forecast_id, 0)

        loaded = self.repo.get_forecast(forecast_id)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.id, forecast_id)
        self.assertEqual(loaded.forecast.ticker, "AAPL")
        self.assertEqual(loaded.forecast.central_estimate, 260.0)
        self.assertEqual(loaded.forecast.lower_estimate, 242.0)
        self.assertEqual(loaded.forecast.upper_estimate, 278.0)
        self.assertEqual(loaded.forecast.model_version, "baseline_v1")
        self.assertEqual(loaded.evaluation_status, EVALUATION_PENDING)
        self.assertIsNone(loaded.actual_price)
        self.assertEqual(loaded.forecast.input_snapshot["filter"], "EMA 20")
        self.assertEqual(loaded.forecast.signal_summary["score"], 0.4)

    def test_projection_rebuilt_from_snapshot(self):
        forecast_id = self.repo.save_forecast(make_forecast())
        loaded = self.repo.get_forecast(forecast_id)
        self.assertEqual(len(loaded.forecast.path_central), 22)
        self.assertAlmostEqual(loaded.forecast.path_central[-1], loaded.forecast.central_estimate, places=6)

    def test_evaluation_updates_only_outcome_fields(self):
        forecast = make_forecast()
        forecast_id = self.repo.save_forecast(forecast)
        original = self.repo.get_forecast(forecast_id)

        self.repo.update_evaluation(
            forecast_id,
            actual_price=255.0,
            actual_date="2026-11-24",
            actual_change_pct=2.0,
            absolute_error=5.0,
            percentage_error=5.0 / 255.0 * 100.0,
        )
        updated = self.repo.get_forecast(forecast_id)
        self.assertEqual(updated.evaluation_status, EVALUATION_EVALUATED)
        self.assertEqual(updated.actual_price, 255.0)
        self.assertEqual(updated.actual_date, "2026-11-24")
        # Prediction fields untouched.
        self.assertEqual(updated.forecast.central_estimate, original.forecast.central_estimate)
        self.assertEqual(updated.forecast.generated_at, original.forecast.generated_at)
        self.assertEqual(updated.forecast.target_date, original.forecast.target_date)
        self.assertEqual(updated.forecast.input_snapshot, original.forecast.input_snapshot)
        self.assertIsNotNone(updated.evaluated_at)

    def test_multiple_forecasts_same_ticker_kept_separate(self):
        self.repo.save_forecast(make_forecast(generated_at="2026-09-01 10:00:00", central=240.0))
        self.repo.save_forecast(make_forecast(generated_at="2026-10-01 10:00:00", central=250.0))
        records = self.repo.get_forecasts(ticker="AAPL")
        self.assertEqual(len(records), 2)
        centrals = sorted(r.forecast.central_estimate for r in records)
        self.assertEqual(centrals, [240.0, 250.0])

    def test_has_duplicate_detection(self):
        forecast = make_forecast()
        self.assertFalse(self.repo.has_duplicate(forecast))
        self.repo.save_forecast(forecast)
        self.assertTrue(self.repo.has_duplicate(forecast))

    def test_filters_and_ordering(self):
        self.repo.save_forecast(make_forecast(ticker="AAPL", generated_at="2026-10-01 10:00:00"))
        self.repo.save_forecast(make_forecast(ticker="MSFT", generated_at="2026-10-02 10:00:00"))
        self.repo.save_forecast(
            make_forecast(ticker="AAPL", generated_at="2026-10-03 10:00:00", horizon_months=3)
        )
        aapl = self.repo.get_forecasts(ticker="AAPL")
        self.assertEqual(len(aapl), 2)
        three_month = self.repo.get_forecasts(horizon_months=3)
        self.assertEqual(len(three_month), 1)
        newest_first = self.repo.get_forecasts(order_by="generated_desc")
        self.assertEqual(newest_first[0].forecast.ticker, "AAPL")
        oldest_first = self.repo.get_forecasts(order_by="generated_asc")
        self.assertEqual(oldest_first[0].forecast.generated_at, "2026-10-01 10:00:00")

    def test_pending_only_returns_pending(self):
        id_a = self.repo.save_forecast(make_forecast(ticker="AAPL"))
        id_b = self.repo.save_forecast(make_forecast(ticker="MSFT"))
        self.repo.update_evaluation(
            id_b, actual_price=255.0, actual_date="2026-11-24",
            actual_change_pct=2.0, absolute_error=5.0, percentage_error=2.0,
        )
        pending = self.repo.get_pending_forecasts()
        self.assertEqual([r.id for r in pending], [id_a])

    def test_delete_single_and_multiple(self):
        id_a = self.repo.save_forecast(make_forecast(generated_at="2026-10-01 10:00:00"))
        id_b = self.repo.save_forecast(make_forecast(generated_at="2026-10-02 10:00:00"))
        deleted = self.repo.delete_forecasts([id_a, id_b])
        self.assertEqual(deleted, 2)
        self.assertEqual(self.repo.get_forecasts(), [])

    def test_delete_before_cutoff(self):
        self.repo.save_forecast(make_forecast(generated_at="2026-01-01 10:00:00"))
        keep = self.repo.save_forecast(make_forecast(generated_at="2026-10-01 10:00:00"))
        deleted = self.repo.delete_forecasts_before("2026-06-01")
        self.assertEqual(deleted, 1)
        remaining = self.repo.get_forecasts()
        self.assertEqual([r.id for r in remaining], [keep])

    def test_mark_unavailable(self):
        forecast_id = self.repo.save_forecast(make_forecast())
        self.repo.mark_unavailable(forecast_id)
        record = self.repo.get_forecast(forecast_id)
        self.assertEqual(record.evaluation_status, EVALUATION_UNAVAILABLE)
        # Prediction intact after unavailability marking.
        self.assertEqual(record.forecast.central_estimate, 260.0)

    def test_count_by_status(self):
        self.repo.save_forecast(make_forecast(ticker="AAPL"))
        id_b = self.repo.save_forecast(make_forecast(ticker="MSFT"))
        self.repo.update_evaluation(
            id_b, actual_price=255.0, actual_date="2026-11-24",
            actual_change_pct=2.0, absolute_error=5.0, percentage_error=2.0,
        )
        counts = self.repo.count_by_status()
        self.assertEqual(counts[EVALUATION_PENDING], 1)
        self.assertEqual(counts[EVALUATION_EVALUATED], 1)

    def test_unserializable_snapshot_rejected(self):
        forecast = make_forecast()
        forecast.input_snapshot = {"bad": object()}
        with self.assertRaises((TypeError, ValueError)):
            self.repo.save_forecast(forecast)


if __name__ == "__main__":
    unittest.main()
