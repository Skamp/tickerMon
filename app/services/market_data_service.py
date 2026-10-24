import logging
import math
from datetime import datetime, timedelta
from typing import List, Optional, Tuple, Dict, Any, Set

from app.database.repositories import MarketDataRepository
from app.models.price_data import PricePoint
from app.models.ticker import TickerConfig, TickerSummary
from app.models.time_range import TimeRange
from app.models.trend import TrendBucket
from app.services.swing_detection import (
    SwingAlgorithm,
    detect_swings,
    has_significant_swing,
    restrict_swing_pivots,
)

logger = logging.getLogger(__name__)

TREND_CHANGE_THRESHOLD_PCT = 2.0
SWING_RANGE_THRESHOLD = 0.10

# Fixed lookback windows (label, days) used by the performance strip above the chart.
PERFORMANCE_RANGES: Tuple[Tuple[str, int], ...] = (
    ("1D", 1),
    ("1W", 7),
    ("1M", 30),
    ("3M", 90),
    ("6M", 180),
    ("1Y", 365),
    ("5Y", 1825),
)
# Tolerance used when local history starts just inside a lookback window.
PERFORMANCE_BASE_SLACK_RATIO = 0.05
PERFORMANCE_BASE_MIN_SLACK_DAYS = 2.0


def classify_price_series(prices: List[float]) -> TrendBucket:
    valid = [p for p in prices if p and p > 0]
    if len(valid) < 2:
        return TrendBucket.UNSURE

    change_pct = (valid[-1] - valid[0]) / valid[0] * 100.0
    if change_pct >= TREND_CHANGE_THRESHOLD_PCT:
        return TrendBucket.RISE
    if change_pct <= -TREND_CHANGE_THRESHOLD_PCT:
        return TrendBucket.DOWN
    return TrendBucket.LATERAL


def is_swing_series(
    prices: List[float],
    algorithm: SwingAlgorithm = SwingAlgorithm.RANGE,
    ohlc: Optional[Tuple[List[float], List[float], List[float]]] = None,
    params: Optional[Dict[str, Any]] = None,
) -> bool:
    return has_significant_swing(
        algorithm, prices, ohlc, threshold_pct=SWING_RANGE_THRESHOLD * 100.0, params=params
    )


def count_trend_buckets(trends: Dict[str, TrendBucket]) -> Dict[TrendBucket, int]:
    counts = {bucket: 0 for bucket in TrendBucket}
    for bucket in trends.values():
        counts[bucket] += 1
    return counts


class MarketDataService:
    WARMUP_CACHE_MAX_ENTRIES = 32

    def __init__(self, repo: MarketDataRepository):
        self.repo = repo
        self._warmup_cache: Dict[Tuple[str, TimeRange, int], Tuple[List[float], List[float], List[float], List[float]]] = {}

    def get_ticker_summary(self, config: TickerConfig) -> TickerSummary:
        """
        Builds a summary of the latest price and daily % change for a ticker using local SQLite data.
        Does NOT execute network requests.
        """
        sym = config.symbol
        meta = self.repo.get_ticker_metadata(sym) or {}
        company_name = config.name or meta.get("company_name") or sym
        currency = meta.get("currency", "USD")
        exchange = meta.get("exchange", "")
        last_updated = meta.get("last_download")
        status = meta.get("status", "OK")
        error_msg = meta.get("error_message")
        effective_added_at = config.added_at or meta.get("first_download")

        latest_point = self.repo.get_latest_price_point(sym)
        if not latest_point:
            return TickerSummary(
                symbol=sym,
                company_name=company_name,
                current_price=None,
                price_change=None,
                pct_change=None,
                currency=currency,
                exchange=exchange,
                last_updated=last_updated,
                status=status if status != "OK" else "NO_DATA",
                error_message=error_msg,
                added_at=effective_added_at,
            )

        current_price = latest_point.adj_close or latest_point.close

        # Get all prices to find previous trading session close
        prices = self.repo.get_prices(sym)
        price_change = None
        pct_change = None

        if len(prices) >= 2:
            prev_point = prices[-2]
            prev_price = prev_point.adj_close or prev_point.close
            if prev_price and prev_price > 0:
                price_change = current_price - prev_price
                pct_change = (price_change / prev_price) * 100.0

        return TickerSummary(
            symbol=sym,
            company_name=company_name,
            current_price=current_price,
            price_change=price_change,
            pct_change=pct_change,
            currency=currency,
            exchange=exchange,
            last_updated=last_updated,
            status=status,
            error_message=error_msg,
            added_at=effective_added_at,
        )

    def get_all_summaries(self, configs: List[TickerConfig]) -> List[TickerSummary]:
        return [self.get_ticker_summary(cfg) for cfg in configs]

    def get_tickers_without_data(self, configs: List[TickerConfig]) -> List[TickerConfig]:
        """Returns enabled tickers that have no price rows stored locally yet."""
        return [cfg for cfg in configs if not self.repo.has_price_data(cfg.symbol)]

    def get_performance(self, symbol: str) -> Dict[str, Optional[float]]:
        """
        Computes the percentage gain/loss for each entry in PERFORMANCE_RANGES
        using local SQLite prices only (no network requests).

        Returns a mapping of range label -> percent change, where a range that
        cannot be computed (missing or too-short local history) maps to None.
        """
        result: Dict[str, Optional[float]] = {key: None for key, _ in PERFORMANCE_RANGES}

        series: List[Tuple[datetime, float]] = []
        for p, dt, val in self._iter_priced_points(self.repo.get_prices(symbol)):
            if val and val > 0:
                series.append((dt, val))
        if len(series) < 2:
            return result

        latest_dt, latest_val = series[-1]
        for key, days in PERFORMANCE_RANGES:
            cutoff = latest_dt - timedelta(days=days)
            base_val: Optional[float] = None
            for dt, val in series:
                if dt <= cutoff:
                    base_val = val
                else:
                    break

            if base_val is None:
                # Local history may start marginally inside the window (e.g. a
                # fresh 5Y download or slightly stale data). Fall back to the
                # oldest point only when the gap is small relative to the window.
                oldest_dt, oldest_val = series[0]
                slack_days = max(
                    PERFORMANCE_BASE_MIN_SLACK_DAYS,
                    days * PERFORMANCE_BASE_SLACK_RATIO,
                )
                if oldest_dt - cutoff <= timedelta(days=slack_days):
                    base_val = oldest_val

            if base_val and base_val > 0:
                result[key] = (latest_val - base_val) / base_val * 100.0
        return result

    def get_trend_bucket(self, symbol: str, time_range: TimeRange) -> TrendBucket:
        _, prices, _ = self.get_chart_data(symbol, time_range)
        return classify_price_series(prices)

    def get_trend_buckets(self, configs: List[TickerConfig], time_range: TimeRange) -> Dict[str, TrendBucket]:
        return {cfg.symbol: self.get_trend_bucket(cfg.symbol, time_range) for cfg in configs}

    def get_swing_symbols(
        self,
        configs: List[TickerConfig],
        time_range: TimeRange,
        algorithm: SwingAlgorithm = SwingAlgorithm.RANGE,
        params: Optional[Dict[str, Any]] = None,
        range_settings: Optional[Dict[str, Any]] = None,
    ) -> Set[str]:
        symbols: Set[str] = set()
        for cfg in configs:
            timestamps, prices, _ = self.get_chart_data(cfg.symbol, time_range)
            if not prices:
                continue
            ohlc = None
            if algorithm != SwingAlgorithm.RANGE:
                ohlc = self.get_chart_ohlcv(cfg.symbol, time_range)
            if not is_swing_series(prices, algorithm, ohlc, params=params):
                continue
            _, legs = self.detect_swing_overlay(
                cfg.symbol, time_range, prices, timestamps, algorithm, params, range_settings
            )
            if legs:
                symbols.add(cfg.symbol)
        return symbols

    def detect_swing_pivots(
        self,
        symbol: str,
        time_range: TimeRange,
        prices: List[float],
        algorithm: SwingAlgorithm = SwingAlgorithm.RANGE,
        params: Optional[Dict[str, Any]] = None,
    ) -> List[int]:
        """Returns pivot indices of the swing overlay for the given prices.

        For the RANGE algorithm the global low and high of the series are
        included so the min-max range can be visualized as well.
        """
        if not prices:
            return []
        ohlc = None
        if algorithm != SwingAlgorithm.RANGE:
            ohlc = self.get_chart_ohlcv(symbol, time_range)
        pivots = detect_swings(algorithm, prices, ohlc, params=params)
        if algorithm == SwingAlgorithm.RANGE and len(prices) >= 2:
            low_index = min(range(len(prices)), key=prices.__getitem__)
            high_index = max(range(len(prices)), key=prices.__getitem__)
            pivots = sorted(set(pivots) | {low_index, high_index})
        return pivots

    def detect_swing_overlay(
        self,
        symbol: str,
        time_range: TimeRange,
        prices: List[float],
        timestamps: List[float],
        algorithm: SwingAlgorithm = SwingAlgorithm.RANGE,
        params: Optional[Dict[str, Any]] = None,
        range_settings: Optional[Dict[str, Any]] = None,
    ) -> Tuple[List[int], List[Tuple[int, int]]]:
        """Returns ``(pivots, legs)`` for the chart overlay after applying the swing range filter."""
        pivots = self.detect_swing_pivots(symbol, time_range, prices, algorithm, params)
        return restrict_swing_pivots(pivots, timestamps, range_settings)

    def _load_price_points(self, symbol: str, time_range: TimeRange) -> List[PricePoint]:
        start_str = time_range.get_start_date().strftime("%Y-%m-%d 00:00:00")
        return self.repo.get_prices(symbol, start_date=start_str)

    def _iter_priced_points(self, points: List[PricePoint]):
        for p in points:
            try:
                if " " in p.timestamp:
                    dt = datetime.strptime(p.timestamp, "%Y-%m-%d %H:%M:%S")
                else:
                    dt = datetime.strptime(p.timestamp[:10], "%Y-%m-%d")
            except Exception as e:
                logger.warning(f"Could not parse timestamp '{p.timestamp}': {e}")
                continue
            val = p.adj_close if p.adj_close is not None and p.adj_close > 0 else p.close
            yield p, dt, val

    def get_chart_data(self, symbol: str, time_range: TimeRange) -> Tuple[List[float], List[float], List[str]]:
        """
        Fetches local historical prices filtered by time_range.
        Returns:
            - timestamps: List of UNIX epoch floats (seconds) for PyQtGraph x-axis.
            - prices: List of float values (Adjusted Close or Close) for PyQtGraph y-axis.
            - date_labels: List of human-readable ISO date strings for mouse tooltips.
        """
        points = self._load_price_points(symbol, time_range)

        timestamps: List[float] = []
        prices: List[float] = []
        date_labels: List[str] = []

        for p, dt, val in self._iter_priced_points(points):
            timestamps.append(dt.timestamp())
            prices.append(val)
            date_labels.append(p.timestamp)

        return timestamps, prices, date_labels

    def get_chart_ohlcv(self, symbol: str, time_range: TimeRange) -> Tuple[List[float], List[float], List[float]]:
        """
        Fetches open/high/low arrays aligned bar-by-bar with get_chart_data for the same range.
        OHLC values are scaled by the close/adjusted-close ratio so they match the chart price series.
        """
        points = self._load_price_points(symbol, time_range)

        opens: List[float] = []
        highs: List[float] = []
        lows: List[float] = []

        for p, _, _ in self._iter_priced_points(points):
            ratio = (p.adj_close / p.close) if (p.adj_close and p.close and p.close > 0) else 1.0
            opens.append((p.open or 0.0) * ratio)
            highs.append((p.high or 0.0) * ratio)
            lows.append((p.low or 0.0) * ratio)

        return opens, highs, lows

    def get_chart_volume(
        self, symbol: str, time_range: TimeRange
    ) -> Tuple[List[float], List[float], List[float]]:
        """
        Fetches volume plus open/close arrays aligned bar-by-bar with get_chart_data.

        Yahoo Finance's Volume field is the *total* traded volume for the period;
        it does not provide a true buy-volume vs sell-volume breakdown. The
        buying/selling classification derived from these open/close values is
        only an approximation of pressure based on candle direction.
        Open values are scaled by the close/adjusted-close ratio so they match
        the chart price series; scaling by a positive factor keeps the candle
        direction (Close vs Open) unchanged.

        Returns:
            - volumes: traded volume per bar (0.0 when missing/invalid).
            - opens: open price per bar (0.0 when missing).
            - closes: close price per bar, identical to get_chart_data prices.
        """
        points = self._load_price_points(symbol, time_range)

        volumes: List[float] = []
        opens: List[float] = []
        closes: List[float] = []

        for p, _, val in self._iter_priced_points(points):
            ratio = (p.adj_close / p.close) if (p.adj_close and p.close and p.close > 0) else 1.0

            try:
                volume = float(p.volume)
            except (TypeError, ValueError):
                volume = 0.0
            if not math.isfinite(volume) or volume < 0:
                volume = 0.0
            volumes.append(volume)

            try:
                open_value = float(p.open)
            except (TypeError, ValueError):
                open_value = 0.0
            if not math.isfinite(open_value) or open_value <= 0:
                open_value = 0.0
            opens.append(open_value * ratio)

            try:
                close_value = float(val)
            except (TypeError, ValueError):
                close_value = 0.0
            if not math.isfinite(close_value) or close_value <= 0:
                close_value = 0.0
            closes.append(close_value)

        return volumes, opens, closes

    def get_warmup_ohlcv(
        self,
        symbol: str,
        time_range: TimeRange,
        warmup_bars: int = 260,
    ) -> Tuple[List[float], List[float], List[float], List[float]]:
        """Returns (opens, highs, lows, closes) with extra history before the range.

        The extra ``warmup_bars`` of history (approximated by two calendar days
        per bar) lets EMA/ATR indicators seed well before the visible chart
        range so their values at the left edge are accurate. Values are scaled
        exactly like ``get_chart_ohlcv`` so they match the chart price series.
        Results are cached in memory per (symbol, range, warmup); callers slice
        the tail to align with ``get_chart_data`` output.
        """
        cache_key = (symbol.upper().strip(), time_range, int(warmup_bars))
        cached = self._warmup_cache.get(cache_key)
        if cached is not None:
            return cached

        visible_start = time_range.get_start_date()
        warmup_start = visible_start - timedelta(days=max(int(warmup_bars), 0) * 2)
        points = self.repo.get_prices(symbol, start_date=warmup_start.strftime("%Y-%m-%d 00:00:00"))

        opens: List[float] = []
        highs: List[float] = []
        lows: List[float] = []
        closes: List[float] = []

        for p, _, val in self._iter_priced_points(points):
            ratio = (p.adj_close / p.close) if (p.adj_close and p.close and p.close > 0) else 1.0
            opens.append((p.open or 0.0) * ratio)
            highs.append((p.high or 0.0) * ratio)
            lows.append((p.low or 0.0) * ratio)
            closes.append(float(val) if val is not None else 0.0)

        result = (opens, highs, lows, closes)
        if len(self._warmup_cache) >= self.WARMUP_CACHE_MAX_ENTRIES:
            self._warmup_cache.clear()
        self._warmup_cache[cache_key] = result
        return result
