"""Latest confirmed swing high/low levels with distance and crossing status.

Confirmation policy: ``detect_swings`` always anchors the pivot list at the
final bar (index ``n - 1``). That trailing pivot cannot be confirmed yet —
its leg may still extend — so confirmed pivots are the detected pivots
excluding the trailing bar anchor. Everything else produced by the swing
detection pipeline is treated as confirmed (detection is retrospective over
the loaded series and exposes no separate provisional state).

Reference close: the most recent valid closing price of the currently loaded
dataset (``prices[-1]``). Distance and percentage distance are measured from
this reference; the hover price is never used.

Crossing rule: a level is considered crossed when any bar *after* the pivot
bar trades through it — for a swing high, any later bar whose High (or Close
when High is unavailable) exceeds the level; for a swing low, any later bar
whose Low (or Close when Low is unavailable) is below the level.

Colors indicate the level's position relative to the reference close (green
above, red below, neutral within ``NEUTRAL_TOLERANCE_PCT`` percent); the line
style (solid/dashed) independently indicates crossing status.
"""

from dataclasses import dataclass
from typing import List, Optional, Sequence

from app.services.market_structure import STRUCTURE_HIGH, STRUCTURE_LOW, pivot_kinds
from app.utils.currency import get_currency_symbol

NEUTRAL_TOLERANCE_PCT = 0.1


@dataclass(frozen=True)
class SwingLevel:
    """A confirmed swing level rendered as a horizontal price line."""

    kind: str  # STRUCTURE_HIGH | STRUCTURE_LOW
    index: int
    price: float
    distance: float
    distance_pct: float
    crossed: bool
    color: str
    annotation: str


def confirmed_pivot_indices(pivots: Sequence[int], n_bars: int) -> List[int]:
    """Returns the confirmed pivots: detected pivots excluding the trailing bar."""
    return [int(p) for p in pivots if 0 <= int(p) < n_bars - 1]


def _is_valid_price(value) -> bool:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return False
    return result == result and result > 0


def is_level_crossed(
    level_price: float,
    kind: str,
    pivot_index: int,
    highs: Optional[Sequence[float]] = None,
    lows: Optional[Sequence[float]] = None,
    closes: Optional[Sequence[float]] = None,
) -> bool:
    """Returns True when a bar after ``pivot_index`` traded through ``level_price``.

    Uses High/Low when available and valid (> 0); falls back to Close for bars
    with missing OHLC data.
    """
    count = len(closes) if closes is not None else 0
    if highs is not None:
        count = max(count, len(highs))
    if lows is not None:
        count = max(count, len(lows))

    for i in range(pivot_index + 1, count):
        if kind == STRUCTURE_HIGH:
            barrier = None
            if highs is not None and i < len(highs) and _is_valid_price(highs[i]):
                barrier = float(highs[i])
            elif closes is not None and i < len(closes) and _is_valid_price(closes[i]):
                barrier = float(closes[i])
            if barrier is not None and barrier > level_price:
                return True
        else:
            barrier = None
            if lows is not None and i < len(lows) and _is_valid_price(lows[i]):
                barrier = float(lows[i])
            elif closes is not None and i < len(closes) and _is_valid_price(closes[i]):
                barrier = float(closes[i])
            if barrier is not None and barrier < level_price:
                return True
    return False


def level_color(price: float, reference_close: float) -> str:
    """Green above the reference close, red below, neutral within tolerance."""
    if not _is_valid_price(reference_close):
        return "#8b90a0"
    diff_pct = abs(price - reference_close) / reference_close * 100.0
    if diff_pct <= NEUTRAL_TOLERANCE_PCT:
        return "#8b90a0"
    if price > reference_close:
        return "#00e676"
    return "#ff5252"


def format_level_annotation(
    kind: str,
    price: float,
    reference_close: float,
    currency_code: Optional[str] = None,
) -> str:
    """Builds the compact right-edge annotation for a swing level."""
    symbol = get_currency_symbol(currency_code)
    name = "Last Confirmed High" if kind == STRUCTURE_HIGH else "Last Confirmed Low"
    distance = price - reference_close
    pct = (distance / reference_close * 100.0) if _is_valid_price(reference_close) else 0.0
    return f"{name}: {symbol}{price:,.2f} | {symbol}{distance:+,.2f} ({pct:+.2f}%)"


def compute_swing_levels(
    pivots: Sequence[int],
    prices: Sequence[float],
    reference_close: float,
    highs: Optional[Sequence[float]] = None,
    lows: Optional[Sequence[float]] = None,
    closes: Optional[Sequence[float]] = None,
    currency_code: Optional[str] = None,
) -> tuple:
    """Returns (high_level, low_level) for the latest confirmed pivots of each kind.

    Either element is None when no confirmed pivot of that kind exists.
    Levels keep their original pivot price; only color/crossing/annotation are
    derived from the current reference close and OHLC data.
    """
    n_bars = len(prices)
    confirmed = confirmed_pivot_indices(pivots, n_bars)
    if not confirmed:
        return None, None

    kinds = pivot_kinds(pivots, prices)
    kind_by_index = {int(p): k for p, k in zip(pivots, kinds)}

    latest_high: Optional[int] = None
    latest_low: Optional[int] = None
    for idx in confirmed:
        kind = kind_by_index.get(idx)
        if kind == STRUCTURE_HIGH:
            latest_high = idx
        elif kind == STRUCTURE_LOW:
            latest_low = idx

    def build(index: Optional[int], kind: str) -> Optional[SwingLevel]:
        if index is None:
            return None
        price = float(prices[index])
        distance = price - reference_close
        distance_pct = (
            distance / reference_close * 100.0 if _is_valid_price(reference_close) else 0.0
        )
        crossed = is_level_crossed(price, kind, index, highs=highs, lows=lows, closes=closes)
        return SwingLevel(
            kind=kind,
            index=index,
            price=price,
            distance=distance,
            distance_pct=distance_pct,
            crossed=crossed,
            color=level_color(price, reference_close),
            annotation=format_level_annotation(kind, price, reference_close, currency_code),
        )

    high_level = build(latest_high, STRUCTURE_HIGH)
    low_level = build(latest_low, STRUCTURE_LOW)
    return high_level, low_level
