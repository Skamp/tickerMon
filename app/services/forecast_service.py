"""Forecast orchestration: generation, persistence, evaluation, accuracy.

``ForecastService`` wires the pure ``forecast_engine`` to the local SQLite
cache and the active filter/swing configuration. It performs no Yahoo Finance
requests — forecasts and evaluations only read data already stored locally.

Evaluation policy: a forecast stays *pending* until the calendar target date
has passed and a stored close on or after that date exists (the first such
close is the evaluation observation — the next valid trading session when the
target falls on a weekend/holiday). Current-day candles are never used: a
forecast is only evaluated against a close whose date is strictly before
today, or on a completed prior session. A ticker with no stored price rows at
all is marked *unavailable* (retryable by resetting the status); a ticker
whose data simply has not yet reached the target stays pending.

Percentage error is ``abs(central - actual) / abs(actual) * 100`` (MAPE-style
relative to the realized price); zero actuals yield None.
"""

import logging
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.database.repositories import ForecastRepository, MarketDataRepository
from app.models.forecast import (
    EVALUATION_EVALUATED,
    EVALUATION_PENDING,
    EVALUATION_UNAVAILABLE,
    Forecast,
    ForecastHorizon,
    SavedForecast,
    now_iso,
)
from app.services.forecast_engine import (
    FORECAST_MODEL_VERSION,
    MIN_SESSIONS,
    SESSIONS_PER_MONTH,
    ForecastError,
    generate_forecast,
)
from app.services.market_data_service import MarketDataService
from app.services.noise_reduction import NoiseReductionAlgorithm
from app.services.swing_detection import SwingAlgorithm
from app.services.ticker_service import TickerService

logger = logging.getLogger(__name__)

MIN_DIRECTIONAL_SAMPLE = 3
WALK_FORWARD_MIN_HISTORY = 252
WALK_FORWARD_STEP = 21
WALK_FORWARD_MAX_ORIGINS = 12


@dataclass
class AccuracyBucket:
    """Accuracy statistics for a subset of evaluated forecasts."""

    n_evaluated: int = 0
    n_pending: int = 0
    mean_absolute_error: Optional[float] = None
    mape: Optional[float] = None
    directional_accuracy: Optional[float] = None
    directional_sample: int = 0


@dataclass
class ForecastAccuracy:
    """Aggregate accuracy statistics over saved forecasts."""

    overall: AccuracyBucket = field(default_factory=AccuracyBucket)
    by_horizon: Dict[int, AccuracyBucket] = field(default_factory=dict)
    by_ticker: Dict[str, AccuracyBucket] = field(default_factory=dict)
    by_model: Dict[str, AccuracyBucket] = field(default_factory=dict)


@dataclass
class WalkForwardResult:
    """Outcome of a chronological walk-forward validation run."""

    ticker: str
    horizon_months: int
    n_origins: int = 0
    mean_absolute_error: Optional[float] = None
    mape: Optional[float] = None
    directional_accuracy: Optional[float] = None
    directional_sample: int = 0
    errors: List[str] = field(default_factory=list)


def _parse_date(value: str) -> Optional[date]:
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _compute_directional_accuracy(rows: Sequence[Tuple[Optional[float], Optional[float]]]) -> Tuple[Optional[float], int]:
    """Compares predicted vs actual change signs; neutral predictions are abstains."""
    matches = 0
    sample = 0
    for predicted, actual in rows:
        if predicted is None or actual is None:
            continue
        if predicted == 0 or actual == 0:
            continue
        sample += 1
        if (predicted > 0) == (actual > 0):
            matches += 1
    if sample < MIN_DIRECTIONAL_SAMPLE:
        return None, sample
    return matches / sample * 100.0, sample


def _build_bucket(records: Sequence[SavedForecast]) -> AccuracyBucket:
    evaluated = [r for r in records if r.evaluation_status == EVALUATION_EVALUATED]
    pending = sum(1 for r in records if r.evaluation_status == EVALUATION_PENDING)
    bucket = AccuracyBucket(n_evaluated=len(evaluated), n_pending=pending)
    if not evaluated:
        return bucket

    abs_errors = [r.absolute_error for r in evaluated if r.absolute_error is not None]
    if abs_errors:
        bucket.mean_absolute_error = sum(abs_errors) / len(abs_errors)

    pct_errors = [r.percentage_error for r in evaluated if r.percentage_error is not None]
    if pct_errors:
        bucket.mape = sum(pct_errors) / len(pct_errors)

    predicted_change = [r.forecast.expected_change_pct for r in evaluated]
    actual_change = [r.actual_change_pct for r in evaluated]
    bucket.directional_accuracy, bucket.directional_sample = _compute_directional_accuracy(
        list(zip(predicted_change, actual_change))
    )
    return bucket


class ForecastService:
    def __init__(
        self,
        market_data_service: MarketDataService,
        ticker_service: TickerService,
        forecast_repo: ForecastRepository,
        price_repo: Optional[MarketDataRepository] = None,
    ):
        self.market_data_service = market_data_service
        self.ticker_service = ticker_service
        self.forecast_repo = forecast_repo
        self.price_repo = price_repo
        # Active UI selections, synced by the main window whenever the user
        # changes the Filter or Swing combo boxes.
        self.active_filter_algorithm = NoiseReductionAlgorithm.NONE
        self.active_swing_algorithm = SwingAlgorithm.RANGE

    def generate(self, symbol: str, horizon: ForecastHorizon) -> Forecast:
        """Generates a forecast for ``symbol`` using the active UI configuration."""
        if horizon == ForecastHorizon.OFF:
            raise ForecastError("Forecast horizon is Off.")

        clean_symbol = symbol.upper().strip()
        timestamps, _, highs, lows, closes, _ = self.market_data_service.get_full_ohlcv(clean_symbol)
        if len(closes) < MIN_SESSIONS:
            raise ForecastError(
                f"Insufficient local history for {clean_symbol}: {len(closes)} sessions "
                f"(need at least {MIN_SESSIONS}). Update market data first."
            )

        filter_algorithm = self.active_filter_algorithm
        swing_algorithm = self.active_swing_algorithm
        swing_params = self.ticker_service.get_swing_params(swing_algorithm)
        swing_range_settings = self.ticker_service.get_swing_range_settings()

        currency = None
        meta = None
        if self.price_repo is not None:
            meta = self.price_repo.get_ticker_metadata(clean_symbol)
            currency = (meta or {}).get("currency")

        return generate_forecast(
            clean_symbol,
            timestamps,
            closes,
            highs=highs,
            lows=lows,
            horizon=horizon,
            filter_algorithm=filter_algorithm,
            swing_algorithm=swing_algorithm,
            swing_params=swing_params,
            swing_range_settings=swing_range_settings,
            currency_code=currency,
        )

    def save(self, forecast: Forecast) -> Tuple[bool, str, bool]:
        """Saves a forecast snapshot.

        Returns ``(ok, message, is_duplicate)``. The caller decides whether to
        proceed after a duplicate warning; nothing is overwritten either way.
        """
        if forecast.horizon_months not in (1, 2, 3):
            return False, "Invalid forecast horizon.", False
        if not forecast.ticker:
            return False, "Forecast ticker is missing.", False
        for value in (forecast.reference_close, forecast.central_estimate,
                      forecast.lower_estimate, forecast.upper_estimate):
            if value is None or not math.isfinite(value) or value <= 0:
                return False, "Forecast contains invalid price values.", False
        if not forecast.target_date or not forecast.reference_date:
            return False, "Forecast is missing reference or target dates.", False

        is_duplicate = self.forecast_repo.has_duplicate(forecast)
        try:
            forecast_id = self.forecast_repo.save_forecast(forecast)
        except Exception as e:
            logger.error(f"Could not persist forecast: {e}")
            return False, f"Failed to save forecast: {e}", is_duplicate
        return True, f"Forecast saved (id {forecast_id}).", is_duplicate

    def load_saved(
        self,
        ticker: Optional[str] = None,
        horizon_months: Optional[int] = None,
        evaluation_status: Optional[str] = None,
        order_by: str = "generated_desc",
    ) -> List[SavedForecast]:
        return self.forecast_repo.get_forecasts(
            ticker=ticker,
            horizon_months=horizon_months,
            evaluation_status=evaluation_status,
            order_by=order_by,
        )

    def latest_forecast_by_ticker(self) -> Dict[str, Forecast]:
        """Returns the most recently generated saved forecast per ticker.

        Records must arrive newest-first (``generated_desc``); the first
        occurrence of each ticker wins.
        """
        latest: Dict[str, Forecast] = {}
        for record in self.forecast_repo.get_forecasts(order_by="generated_desc"):
            latest.setdefault(record.forecast.ticker, record.forecast)
        return latest

    def delete(self, forecast_ids: List[int]) -> int:
        return self.forecast_repo.delete_forecasts(forecast_ids)

    def delete_older_than(self, days: int) -> int:
        cutoff = (datetime.now() - timedelta(days=max(int(days), 0))).date()
        return self.forecast_repo.delete_forecasts_before(cutoff.isoformat())

    def evaluate_pending(self) -> Tuple[int, int, int]:
        """Evaluates due pending forecasts against stored closes.

        Returns ``(evaluated_count, unavailable_count, remaining_pending)``.
        Idempotent: already-evaluated forecasts are never reprocessed, and the
        same observation always produces the same stored result.
        """
        pending = self.forecast_repo.get_pending_forecasts()
        evaluated = 0
        unavailable = 0
        today = date.today()

        for record in pending:
            forecast = record.forecast
            target = _parse_date(forecast.target_date)
            if target is None or today < target:
                continue

            points = None
            if self.price_repo is not None:
                try:
                    points = self.price_repo.get_prices(
                        forecast.ticker, start_date=f"{target.isoformat()} 00:00:00"
                    )
                except Exception as e:
                    logger.warning(f"Evaluation data lookup failed for {forecast.ticker}: {e}")
                    points = None

            if points is None:
                # No price repository wired (or lookup failed): retry later.
                continue

            if not points:
                has_any = self.price_repo.has_price_data(forecast.ticker)
                if not has_any:
                    try:
                        self.forecast_repo.mark_unavailable(record.id)
                        unavailable += 1
                    except Exception as e:
                        logger.warning(f"Could not mark forecast {record.id} unavailable: {e}")
                # Data exists but has not reached the target yet: stay pending.
                continue

            actual_point = points[0]
            actual_price = (
                actual_point.adj_close
                if actual_point.adj_close and actual_point.adj_close > 0
                else actual_point.close
            )
            if not actual_price or actual_price <= 0:
                try:
                    self.forecast_repo.mark_unavailable(record.id)
                    unavailable += 1
                except Exception as e:
                    logger.warning(f"Could not mark forecast {record.id} unavailable: {e}")
                continue

            actual_date = actual_point.timestamp[:10]
            reference_close = forecast.reference_close
            actual_change_pct = (actual_price - reference_close) / reference_close * 100.0
            absolute_error = abs(forecast.central_estimate - actual_price)
            percentage_error = (
                absolute_error / abs(actual_price) * 100.0 if actual_price != 0 else None
            )

            try:
                self.forecast_repo.update_evaluation(
                    record.id,
                    actual_price=actual_price,
                    actual_date=actual_date,
                    actual_change_pct=actual_change_pct,
                    absolute_error=absolute_error,
                    percentage_error=percentage_error,
                )
                evaluated += 1
            except Exception as e:
                logger.warning(f"Could not persist evaluation for forecast {record.id}: {e}")

        remaining = len(self.forecast_repo.get_pending_forecasts())
        return evaluated, unavailable, remaining

    def accuracy_stats(self, records: Optional[List[SavedForecast]] = None) -> ForecastAccuracy:
        """Computes accuracy statistics grouped by horizon, ticker and model."""
        if records is None:
            records = self.forecast_repo.get_forecasts()

        stats = ForecastAccuracy(overall=_build_bucket(records))

        by_horizon: Dict[int, List[SavedForecast]] = {}
        by_ticker: Dict[str, List[SavedForecast]] = {}
        by_model: Dict[str, List[SavedForecast]] = {}
        for record in records:
            by_horizon.setdefault(record.forecast.horizon_months, []).append(record)
            by_ticker.setdefault(record.forecast.ticker, []).append(record)
            by_model.setdefault(record.forecast.model_version, []).append(record)

        stats.by_horizon = {k: _build_bucket(v) for k, v in sorted(by_horizon.items())}
        stats.by_ticker = {k: _build_bucket(v) for k, v in sorted(by_ticker.items())}
        stats.by_model = {k: _build_bucket(v) for k, v in sorted(by_model.items())}
        return stats

    def walk_forward_validate(
        self,
        symbol: str,
        horizon: ForecastHorizon,
        *,
        min_history: int = WALK_FORWARD_MIN_HISTORY,
        step: int = WALK_FORWARD_STEP,
        max_origins: int = WALK_FORWARD_MAX_ORIGINS,
    ) -> WalkForwardResult:
        """Chronological walk-forward validation with strict truncation.

        At each origin the engine receives only the series up to and including
        the origin bar; the realized comparison price is the close
        ``horizon_sessions`` bars later. Origins advance forward in time, so no
        future observation ever influences an earlier forecast.
        """
        clean_symbol = symbol.upper().strip()
        months = horizon.months
        result = WalkForwardResult(ticker=clean_symbol, horizon_months=months)
        if months <= 0:
            result.errors.append("Horizon is Off.")
            return result

        timestamps, _, highs, lows, closes, _ = self.market_data_service.get_full_ohlcv(clean_symbol)
        n = len(closes)
        horizon_sessions = months * SESSIONS_PER_MONTH
        if n < min_history + horizon_sessions:
            result.errors.append(
                f"Insufficient history for walk-forward: {n} sessions "
                f"(need {min_history + horizon_sessions})."
            )
            return result

        filter_algorithm = self.active_filter_algorithm
        swing_algorithm = self.active_swing_algorithm
        swing_params = self.ticker_service.get_swing_params(swing_algorithm)
        swing_range_settings = self.ticker_service.get_swing_range_settings()

        abs_errors: List[float] = []
        pct_errors: List[float] = []
        direction_rows: List[Tuple[Optional[float], Optional[float]]] = []

        origins = list(range(min_history, n - horizon_sessions, step))[:max_origins]
        for origin in origins:
            ts_slice = timestamps[: origin + 1]
            close_slice = closes[: origin + 1]
            high_slice = highs[: origin + 1] if highs else None
            low_slice = lows[: origin + 1] if lows else None
            try:
                forecast = generate_forecast(
                    clean_symbol,
                    ts_slice,
                    close_slice,
                    highs=high_slice,
                    lows=low_slice,
                    horizon=horizon,
                    filter_algorithm=filter_algorithm,
                    swing_algorithm=swing_algorithm,
                    swing_params=swing_params,
                    swing_range_settings=swing_range_settings,
                    generated_at=datetime.fromtimestamp(ts_slice[-1]).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    ),
                )
            except ForecastError as e:
                result.errors.append(str(e))
                continue

            actual = closes[origin + horizon_sessions]
            if not actual or actual <= 0:
                continue
            result.n_origins += 1
            abs_errors.append(abs(forecast.central_estimate - actual))
            pct_errors.append(abs(forecast.central_estimate - actual) / abs(actual) * 100.0)
            direction_rows.append((forecast.expected_change_pct, (actual - forecast.reference_close) / forecast.reference_close * 100.0))

        if abs_errors:
            result.mean_absolute_error = sum(abs_errors) / len(abs_errors)
        if pct_errors:
            result.mape = sum(pct_errors) / len(pct_errors)
        result.directional_accuracy, result.directional_sample = _compute_directional_accuracy(
            direction_rows
        )
        return result

    def evaluate_on_startup(self) -> Tuple[int, int, int]:
        """Convenience hook used at application start (local data only)."""
        try:
            return self.evaluate_pending()
        except Exception as e:
            logger.warning(f"Startup forecast evaluation failed: {e}")
            return 0, 0, 0
