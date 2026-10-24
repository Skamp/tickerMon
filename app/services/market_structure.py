"""Market structure classification of confirmed swing pivots.

Labels:
    HH — Higher High (swing high above the previous swing high)
    LH — Lower High  (swing high below the previous swing high)
    HL — Higher Low  (swing low above the previous swing low)
    LL — Lower Low   (swing low below the previous swing low)
    M  — Macro swing, combined with the structure label as "HH · M" etc.

Only swing highs are compared with previous swing highs and swing lows with
previous swing lows; a pivot with no previous comparable pivot (the first of
its kind) receives no structure label.

Equality policy: when the price difference to the previous comparable pivot is
within ``EQUITY_TOLERANCE_PCT`` percent (default 0.1%), the pivot is considered
equal and receives no HH/LH (HL/LL) label, rather than being arbitrarily
forced into one bucket.

Macro policy: a pivot qualifies as macro when the swing from the previous
opposite-kind pivot moved at least ``macro_threshold_pct`` percent, measured as
``(max - min) / min * 100`` over the two pivot prices — the same convention as
``has_significant_swing`` in ``swing_detection.py``. Callers should pass the
active swing algorithm's ``min_swing_pct`` parameter so macro classification
follows the user's existing swing-size configuration instead of an unrelated
arbitrary threshold.

Look-ahead: classification of each pivot only considers that pivot and earlier
pivots, so no future information leaks into a label.
"""

from dataclasses import dataclass
from statistics import median
from typing import List, Sequence, Tuple

STRUCTURE_HIGH = "high"
STRUCTURE_LOW = "low"

LABEL_HH = "HH"
LABEL_HL = "HL"
LABEL_LH = "LH"
LABEL_LL = "LL"

MACRO_LABEL = "M"

EQUITY_TOLERANCE_PCT = 0.1

STRUCTURE_COLORS = {
    LABEL_HH: "#26c6da",
    LABEL_HL: "#26c6da",
    LABEL_LH: "#ff7043",
    LABEL_LL: "#ff7043",
}

_BASE_OFFSET_RATIO = 0.035
_STACK_STEP_RATIO = 0.04
_HALF_HEIGHT_RATIO = 0.02
_MIN_X_GAP_FALLBACK_RATIO = 0.02
_MAX_COLLISION_BUMPS = 8


@dataclass(frozen=True)
class StructurePoint:
    """A confirmed swing pivot with its market-structure classification."""

    index: int
    kind: str  # STRUCTURE_HIGH | STRUCTURE_LOW
    label: str  # LABEL_HH | LABEL_LH | LABEL_HL | LABEL_LL
    is_macro: bool

    @property
    def text(self) -> str:
        return f"{self.label} · {MACRO_LABEL}" if self.is_macro else self.label

    @property
    def color(self) -> str:
        return STRUCTURE_COLORS.get(self.label, "#8b90a0")


def pivot_kinds(pivots: Sequence[int], prices: Sequence[float]) -> List[str]:
    """Returns the high/low kind of each pivot index.

    Mirrors the alternating direction logic used by ``_finalize_pivots`` in
    ``swing_detection.py``: a pivot is a high when its price is >= the next
    pivot's price; the final pivot takes the opposite kind of the previous one.
    """
    indices = [int(i) for i in pivots]
    n = len(prices)
    kinds: List[str] = []
    if not indices:
        return kinds

    directions: List[bool] = []
    for k in range(len(indices) - 1):
        a, b = indices[k], indices[k + 1]
        if not (0 <= a < n and 0 <= b < n):
            directions.append(True)
        else:
            directions.append(bool(float(prices[a]) >= float(prices[b])))
    directions.append(not directions[-1] if directions else True)

    for is_high in directions:
        kinds.append(STRUCTURE_HIGH if is_high else STRUCTURE_LOW)
    return kinds


def _swing_move_pct(price_a: float, price_b: float) -> float:
    low = min(abs(price_a), abs(price_b))
    high = max(abs(price_a), abs(price_b))
    if low <= 0:
        return 0.0 if high <= 0 else float("inf")
    return (high - low) / low * 100.0


def classify_structure(
    pivots: Sequence[int],
    prices: Sequence[float],
    macro_threshold_pct: float = 10.0,
    tolerance_pct: float = EQUITY_TOLERANCE_PCT,
) -> List[StructurePoint]:
    """Classifies confirmed pivots into HH/LH (highs) and HL/LL (lows).

    ``macro_threshold_pct`` should typically be the active swing algorithm's
    ``min_swing_pct`` parameter. Pivots equal within ``tolerance_pct`` receive
    no label (documented equality policy). The first pivot of each kind is
    unlabeled as there is no previous comparable pivot.
    """
    indices = [int(i) for i in pivots]
    kinds = pivot_kinds(indices, prices)
    points: List[StructurePoint] = []

    previous_by_kind = {STRUCTURE_HIGH: None, STRUCTURE_LOW: None}
    previous_opposite_price: dict = {}

    for idx, kind in zip(indices, kinds):
        if not (0 <= idx < len(prices)):
            continue
        price = float(prices[idx])

        label = None
        previous_index = previous_by_kind[kind]
        if previous_index is not None:
            previous_price = float(prices[previous_index])
            denominator = max(abs(previous_price), 1e-12)
            diff_pct = (price - previous_price) / denominator * 100.0
            if diff_pct > tolerance_pct:
                label = LABEL_HH if kind == STRUCTURE_HIGH else LABEL_HL
            elif diff_pct < -tolerance_pct:
                label = LABEL_LH if kind == STRUCTURE_HIGH else LABEL_LL

        is_macro = False
        opposite = STRUCTURE_LOW if kind == STRUCTURE_HIGH else STRUCTURE_HIGH
        opposite_price = previous_opposite_price.get(opposite)
        if opposite_price is not None:
            is_macro = _swing_move_pct(price, opposite_price) >= float(macro_threshold_pct)

        if label is not None:
            points.append(StructurePoint(index=idx, kind=kind, label=label, is_macro=is_macro))

        previous_by_kind[kind] = idx
        previous_opposite_price[kind] = price

    return points


def compute_label_positions(
    points: Sequence[StructurePoint],
    timestamps: Sequence[float],
    prices: Sequence[float],
) -> List[Tuple[float, float, str, str]]:
    """Returns (x, y, text, color) placements with simple collision avoidance.

    Labels are placed above swing highs and below swing lows, offset from the
    pivot price. When a placement would overlap one already on screen, it is
    stacked further away from the pivot. The underlying classification is not
    changed — only the rendered position.
    """
    count = min(len(timestamps), len(prices))
    valid = [p for p in points if 0 <= p.index < count]
    if not valid:
        return []

    price_values = [float(prices[i]) for i in range(count)]
    price_span = max(price_values) - min(price_values)
    if price_span <= 0:
        price_span = max(abs(price_values[0]) if price_values else 1.0, 1.0) * 0.01

    gaps = sorted(
        float(timestamps[b]) - float(timestamps[a])
        for a, b in zip(range(count - 1), range(1, count))
        if float(timestamps[b]) > float(timestamps[a])
    )
    if gaps:
        x_gap = median(gaps) * 2.5
    else:
        time_span = float(timestamps[-1]) - float(timestamps[0]) if count > 1 else 0.0
        x_gap = max(time_span * _MIN_X_GAP_FALLBACK_RATIO, 1.0)

    half_w = x_gap / 2.0
    half_h = price_span * _HALF_HEIGHT_RATIO
    base_offset = price_span * _BASE_OFFSET_RATIO
    stack_step = price_span * _STACK_STEP_RATIO

    placed: List[Tuple[float, float]] = []
    placements: List[Tuple[float, float, str, str]] = []

    for point in valid:
        x = float(timestamps[point.index])
        anchor_y = float(prices[point.index])
        direction = 1.0 if point.kind == STRUCTURE_HIGH else -1.0

        y = anchor_y + direction * base_offset
        bumps = 0
        while any(
            abs(x - px) < half_w * 2.0 and abs(y - py) < half_h * 2.0
            for px, py in placed
        ):
            bumps += 1
            if bumps > _MAX_COLLISION_BUMPS:
                break
            y = anchor_y + direction * (base_offset + bumps * stack_step)

        placed.append((x, y))
        placements.append((x, y, point.text, point.color))

    return placements
