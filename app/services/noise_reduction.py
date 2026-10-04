import math
import logging
from enum import Enum
from typing import List, Tuple

logger = logging.getLogger(__name__)


class NoiseReductionAlgorithm(Enum):
    NONE = "None (Raw Data)"
    QUADTREE = "QuadTree Reduction"
    EMA = "Exponential Moving Average (EMA)"
    EMA50 = "Exponential MA (EMA 50)"
    EMA200 = "Exponential MA (EMA 200)"
    SAVITZKY_GOLAY = "Savitzky-Golay Filter"
    DOUGLAS_PEUCKER = "Ramer-Douglas-Peucker (RDP)"
    RPD1 = "Ramer-Douglas-Peucker (Loose)"
    RPD2 = "Ramer-Douglas-Peucker (Tight)"
    DEMA = "Double EMA (DEMA)"
    TEMA = "Triple EMA (TEMA)"
    HMA = "Hull Moving Average (HMA)"
    KALMAN = "Kalman Filter"
    PPD_FAST = "Price Deviation % (Fast)"
    PPD_SLOW = "Price Deviation % (Slow)"
    PASS_BAND = "Pass-Band Filter (Ehlers)"
    DECYCLER_OSC = "Ehlers Decycler Oscillator"
    UNIVERSAL_OSC = "Ehlers Universal Oscillator"
    REFLEX = "Ehlers Reflex"
    TRENDFLEX = "Ehlers Trendflex"
    FISHER = "Ehlers Fisher Transform"

    @classmethod
    def from_str(cls, val: str) -> "NoiseReductionAlgorithm":
        for item in cls:
            if item.value == val or item.name == val:
                return item
        return cls.NONE


# -----------------------------------------------------------------------------
# 1. QuadTree Spatial Curve Reduction
# -----------------------------------------------------------------------------
class QuadTreeNode:
    """1D/2D Spatial QuadTree node for adaptive trend segmentation."""

    def __init__(self, points: List[Tuple[float, float]], depth: int = 0, max_depth: int = 4, error_threshold: float = 0.035):
        self.points = points
        self.depth = depth
        self.max_depth = max_depth
        self.error_threshold = error_threshold

        self.min_x = min(p[0] for p in points) if points else 0.0
        self.max_x = max(p[0] for p in points) if points else 0.0
        self.min_y = min(p[1] for p in points) if points else 0.0
        self.max_y = max(p[1] for p in points) if points else 0.0

        self.children: List["QuadTreeNode"] = []
        self._subdivide()

    def _subdivide(self) -> None:
        if len(self.points) <= 4 or self.depth >= self.max_depth:
            return

        y_range = self.max_y - self.min_y
        avg_y = sum(p[1] for p in self.points) / len(self.points)
        relative_variation = y_range / (abs(avg_y) + 1e-9)

        # Stop subdividing if noise/variation inside quadrant is below error_threshold
        if relative_variation < self.error_threshold:
            return

        mid_x = (self.min_x + self.max_x) / 2.0
        mid_y = (self.min_y + self.max_y) / 2.0

        q1, q2, q3, q4 = [], [], [], []
        for x, y in self.points:
            if x <= mid_x and y >= mid_y:
                q1.append((x, y))
            elif x > mid_x and y >= mid_y:
                q2.append((x, y))
            elif x <= mid_x and y < mid_y:
                q3.append((x, y))
            else:
                q4.append((x, y))

        for q in [q1, q2, q3, q4]:
            if q:
                self.children.append(QuadTreeNode(q, self.depth + 1, self.max_depth, self.error_threshold))

    def get_leaf_segments(self) -> List[List[Tuple[float, float]]]:
        """Returns list of point lists contained in each leaf QuadTree quadrant."""
        if not self.children:
            return [self.points] if self.points else []

        result = []
        for child in self.children:
            result.extend(child.get_leaf_segments())
        return result


def apply_quadtree_reduction(timestamps: List[float], prices: List[float]) -> Tuple[List[float], List[float]]:
    """
    Applies adaptive QuadTree spatial decomposition to extract macro trend lines
    and reduce high-frequency market noise.
    """
    if len(prices) <= 4:
        return timestamps, prices

    pts = list(zip(timestamps, prices))
    tree = QuadTreeNode(pts, depth=0, max_depth=4, error_threshold=0.035)
    leaf_segments = tree.get_leaf_segments()

    # Sort leaf segments chronologically
    leaf_segments = sorted(leaf_segments, key=lambda seg: seg[0][0])

    node_x: List[float] = []
    node_y: List[float] = []

    for seg in leaf_segments:
        if not seg:
            continue
        start_pt = seg[0]
        end_pt = seg[-1]
        mid_x = (start_pt[0] + end_pt[0]) / 2.0
        avg_y = sum(p[1] for p in seg) / len(seg)

        node_x.extend([start_pt[0], mid_x, end_pt[0]])
        node_y.extend([start_pt[1], avg_y, end_pt[1]])

    # Deduplicate and sort key QuadTree centroids
    seen_x = set()
    clean_x = []
    clean_y = []
    for x, y in sorted(zip(node_x, node_y), key=lambda item: item[0]):
        if x not in seen_x:
            seen_x.add(x)
            clean_x.append(x)
            clean_y.append(y)

    if len(clean_x) < 2:
        return timestamps, prices

    # Interpolate QuadTree macro trend line over original timestamp domain
    import numpy as np
    interp_y = np.interp(timestamps, clean_x, clean_y).tolist()

    # Light 3-point smoothing pass over QuadTree trend line for clean rendering
    smoothed_y = []
    for i in range(len(interp_y)):
        if i == 0 or i == len(interp_y) - 1:
            smoothed_y.append(interp_y[i])
        else:
            smoothed_y.append(0.25 * interp_y[i - 1] + 0.5 * interp_y[i] + 0.25 * interp_y[i + 1])

    return timestamps, smoothed_y


# -----------------------------------------------------------------------------
# 2. Exponential Moving Average (EMA)
# -----------------------------------------------------------------------------
def apply_ema_reduction(timestamps: List[float], prices: List[float], span: int = 10) -> Tuple[List[float], List[float]]:
    if not prices:
        return timestamps, prices

    alpha = 2.0 / (span + 1.0)
    ema_prices: List[float] = []

    current_ema = prices[0]
    for p in prices:
        current_ema = alpha * p + (1.0 - alpha) * current_ema
        ema_prices.append(current_ema)

    return timestamps, ema_prices


# -----------------------------------------------------------------------------
# 3. Savitzky-Golay Low-Pass Filter
# -----------------------------------------------------------------------------
def apply_savitzky_golay_reduction(timestamps: List[float], prices: List[float], window_size: int = 7) -> Tuple[List[float], List[float]]:
    if len(prices) < window_size:
        return timestamps, prices

    smoothed: List[float] = []
    coeffs_5 = [-3 / 35.0, 12 / 35.0, 17 / 35.0, 12 / 35.0, -3 / 35.0]

    for i in range(len(prices)):
        if i < 2 or i >= len(prices) - 2:
            smoothed.append(prices[i])
        else:
            val = sum(coeffs_5[j + 2] * prices[i + j] for j in range(-2, 3))
            smoothed.append(val)

    return timestamps, smoothed


# -----------------------------------------------------------------------------
# 4. Ramer-Douglas-Peucker (RDP) Algorithm
# -----------------------------------------------------------------------------
def _perpendicular_distance(pt: Tuple[float, float], line_start: Tuple[float, float], line_end: Tuple[float, float]) -> float:
    dx = line_end[0] - line_start[0]
    dy = line_end[1] - line_start[1]
    if dx == 0 and dy == 0:
        return math.hypot(pt[0] - line_start[0], pt[1] - line_start[1])

    num = abs(dy * pt[0] - dx * pt[1] + line_end[0] * line_start[1] - line_end[1] * line_start[0])
    den = math.hypot(dx, dy)
    return num / den


def _rdp_recursive(points: List[Tuple[float, float]], epsilon: float) -> List[Tuple[float, float]]:
    if len(points) <= 2:
        return points

    dmax = 0.0
    index = 0
    end = len(points) - 1

    for i in range(1, end):
        d = _perpendicular_distance(points[i], points[0], points[end])
        if d > dmax:
            index = i
            dmax = d

    if dmax > epsilon:
        rec1 = _rdp_recursive(points[: index + 1], epsilon)
        rec2 = _rdp_recursive(points[index:], epsilon)
        return rec1[:-1] + rec2
    else:
        return [points[0], points[end]]


def apply_rdp_reduction(timestamps: List[float], prices: List[float], tolerance: float = 0.015) -> Tuple[List[float], List[float]]:
    if len(prices) <= 3:
        return timestamps, prices

    min_p, max_p = min(prices), max(prices)
    rng = (max_p - min_p) if max_p > min_p else 1.0

    pts = [(timestamps[i], (prices[i] - min_p) / rng * (timestamps[-1] - timestamps[0])) for i in range(len(prices))]
    simplified = _rdp_recursive(pts, epsilon=(timestamps[-1] - timestamps[0]) * tolerance)

    simplified_map = {p[0]: p[1] for p in simplified}
    out_x = []
    out_y = []
    for i in range(len(timestamps)):
        t = timestamps[i]
        if t in simplified_map:
            out_x.append(t)
            out_y.append(prices[i])

    return out_x, out_y


# -----------------------------------------------------------------------------
# 5. Double Exponential Moving Average (DEMA)
# -----------------------------------------------------------------------------
def apply_dema_reduction(timestamps: List[float], prices: List[float], span: int = 10) -> Tuple[List[float], List[float]]:
    if not prices:
        return timestamps, prices

    _, ema1 = apply_ema_reduction(timestamps, prices, span)
    _, ema2 = apply_ema_reduction(timestamps, ema1, span)
    dema_prices = [2.0 * e1 - e2 for e1, e2 in zip(ema1, ema2)]

    return timestamps, dema_prices


# -----------------------------------------------------------------------------
# 6. Triple Exponential Moving Average (TEMA)
# -----------------------------------------------------------------------------
def apply_tema_reduction(timestamps: List[float], prices: List[float], span: int = 10) -> Tuple[List[float], List[float]]:
    if not prices:
        return timestamps, prices

    _, ema1 = apply_ema_reduction(timestamps, prices, span)
    _, ema2 = apply_ema_reduction(timestamps, ema1, span)
    _, ema3 = apply_ema_reduction(timestamps, ema2, span)
    tema_prices = [3.0 * e1 - 3.0 * e2 + e3 for e1, e2, e3 in zip(ema1, ema2, ema3)]

    return timestamps, tema_prices


# -----------------------------------------------------------------------------
# 7. Hull Moving Average (HMA)
# -----------------------------------------------------------------------------
def _wma(values: List[float], window: int) -> List[float]:
    """Weighted moving average where the newest value carries the highest weight."""
    result: List[float] = []
    for i in range(len(values)):
        w = min(window, i + 1)
        chunk = values[i - w + 1: i + 1]
        denom = w * (w + 1) / 2.0
        result.append(sum((idx + 1) * v for idx, v in enumerate(chunk)) / denom)
    return result


def apply_hma_reduction(timestamps: List[float], prices: List[float], period: int = 16) -> Tuple[List[float], List[float]]:
    if not prices or period < 2:
        return timestamps, prices

    half_period = max(1, period // 2)
    root_period = max(1, int(round(math.sqrt(period))))

    half_wma = _wma(prices, half_period)
    full_wma = _wma(prices, period)
    raw = [2.0 * h - f for h, f in zip(half_wma, full_wma)]
    hma_prices = _wma(raw, root_period)

    return timestamps, hma_prices


# -----------------------------------------------------------------------------
# 8. Kalman Filter (constant-velocity model)
# -----------------------------------------------------------------------------
def apply_kalman_filter(
    timestamps: List[float],
    prices: List[float],
    process_noise: float = 1e-4,
    measurement_noise: float = 0.5,
) -> Tuple[List[float], List[float]]:
    if not prices:
        return timestamps, prices
    if len(prices) == 1:
        return timestamps, list(prices)

    diffs = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    mean_d = sum(diffs) / len(diffs)
    var_d = sum((d - mean_d) ** 2 for d in diffs) / len(diffs)
    scale = var_d if var_d > 0 else 1e-12

    q = process_noise * scale
    r = measurement_noise * scale

    x0 = float(prices[0])
    x1 = 0.0
    p00 = scale
    p01 = 0.0
    p10 = 0.0
    p11 = scale

    filtered: List[float] = []
    for z in prices:
        x0 = x0 + x1
        p00 = p00 + 2.0 * p01 + p11 + 0.25 * q
        p01 = p01 + p11 + 0.5 * q
        p10 = p10 + p11 + 0.5 * q
        p11 = p11 + q

        s = p00 + r
        k0 = p00 / s
        k1 = p10 / s
        innovation = z - x0
        x0 = x0 + k0 * innovation
        x1 = x1 + k1 * innovation

        n00 = p00 - k0 * p00
        n01 = p01 - k0 * p01
        n10 = p10 - k1 * p00
        n11 = p11 - k1 * p01
        p00, p01, p10, p11 = n00, n01, n10, n11

        filtered.append(x0)

    return timestamps, filtered


# -----------------------------------------------------------------------------
# 9. Ehlers Pass-Band Filter
# -----------------------------------------------------------------------------
def _map_oscillator_to_price(timestamps: List[float], prices: List[float], values: List[float]) -> Tuple[List[float], List[float]]:
    """Offsets a zero-centered oscillator onto a smoothed price baseline so it renders on the price pane."""
    if not prices or not values:
        return timestamps, values

    _, baseline = apply_ema_reduction(timestamps, prices, span=10)
    price_range = max(prices) - min(prices)
    peak = max(abs(v) for v in values)

    if price_range <= 0 or peak <= 0:
        return timestamps, baseline

    scale = 0.25 * price_range / peak
    return timestamps, [b + v * scale for b, v in zip(baseline, values)]


def apply_pass_band_filter(timestamps: List[float], prices: List[float], period: int = 20, bandwidth: float = 0.5) -> Tuple[List[float], List[float]]:
    if len(prices) < 2 or period < 2:
        return timestamps, prices

    l_term = math.cos(math.radians(360.0 / period))
    g_term = math.cos(math.radians(bandwidth * 360.0 / period))
    if abs(g_term) < 1e-9:
        return timestamps, prices

    s_term = 1.0 / g_term - math.sqrt(max(1.0 / (g_term * g_term) - 1.0, 0.0))

    band: List[float] = []
    bp1 = 0.0
    bp2 = 0.0
    for i, p in enumerate(prices):
        x2 = prices[i - 2] if i >= 2 else prices[0]
        val = 0.5 * (1.0 - s_term) * (p - x2) + l_term * (1.0 + s_term) * bp1 - s_term * bp2
        band.append(val)
        bp2 = bp1
        bp1 = val

    return _map_oscillator_to_price(timestamps, prices, band)


# -----------------------------------------------------------------------------
# 10. Ehlers Decycler Oscillator
# -----------------------------------------------------------------------------
def apply_decycler_oscillator(timestamps: List[float], prices: List[float], hp_period: int = 125, k: float = 1.0) -> Tuple[List[float], List[float]]:
    if len(prices) < 3 or hp_period < 2:
        return timestamps, prices

    cos1 = math.cos(math.radians(0.707 * 360.0 / hp_period))
    alpha1 = (cos1 + math.sin(math.radians(0.707 * 360.0 / hp_period)) - 1.0) / cos1

    half = 0.5 * hp_period
    cos2 = math.cos(math.radians(0.707 * 360.0 / half))
    alpha2 = (cos2 + math.sin(math.radians(0.707 * 360.0 / half)) - 1.0) / cos2

    hp = 0.0
    hp1 = 0.0
    hp2 = 0.0
    decycle1 = prices[0]
    decycle2 = prices[0]
    dec_osc = 0.0
    dec_osc1 = 0.0
    dec_osc2 = 0.0

    oscillator: List[float] = []
    for i, p in enumerate(prices):
        p1 = prices[i - 1] if i >= 1 else prices[0]
        p2 = prices[i - 2] if i >= 2 else prices[0]

        hp = (
            (1.0 - alpha1 / 2.0) * (1.0 - alpha1 / 2.0) * (p - 2.0 * p1 + p2)
            + 2.0 * (1.0 - alpha1) * hp1
            - (1.0 - alpha1) * (1.0 - alpha1) * hp2
        )
        decycle = p - hp

        dec_osc = (
            (1.0 - alpha2 / 2.0) * (1.0 - alpha2 / 2.0) * (decycle - 2.0 * decycle1 + decycle2)
            + 2.0 * (1.0 - alpha2) * dec_osc1
            - (1.0 - alpha2) * (1.0 - alpha2) * dec_osc2
        )

        oscillator.append(100.0 * k * dec_osc / p if p != 0 else 0.0)

        hp2, hp1 = hp1, hp
        decycle2, decycle1 = decycle1, decycle
        dec_osc2, dec_osc1 = dec_osc1, dec_osc

    return _map_oscillator_to_price(timestamps, prices, oscillator)


# -----------------------------------------------------------------------------
# 11. Ehlers Universal Oscillator
# -----------------------------------------------------------------------------
def _super_smoother(values: List[float], period: float) -> List[float]:
    """Two-pole Butterworth SuperSmoother filter with a steady-state warm-up."""
    if period <= 0:
        return list(values)

    a1 = math.exp(-1.414 * math.pi / period)
    b1 = 2.0 * a1 * math.cos(math.radians(1.414 * 180.0 / period))
    c2 = b1
    c3 = -a1 * a1
    c1 = 1.0 - c2 - c3

    smoothed: List[float] = []
    filt1 = values[0]
    filt2 = values[0]
    for i, v in enumerate(values):
        prev = values[i - 1] if i >= 1 else values[0]
        filt = c1 * (v + prev) / 2.0 + c2 * filt1 + c3 * filt2
        smoothed.append(filt)
        filt2, filt1 = filt1, filt
    return smoothed


def apply_universal_oscillator(timestamps: List[float], prices: List[float], band_edge: int = 20) -> Tuple[List[float], List[float]]:
    if len(prices) < 3 or band_edge < 2:
        return timestamps, prices

    a1 = math.exp(-1.414 * math.pi / band_edge)
    b1 = 2.0 * a1 * math.cos(math.radians(1.414 * 180.0 / band_edge))
    c2 = b1
    c3 = -a1 * a1
    c1 = 1.0 - c2 - c3

    oscillator: List[float] = []
    white1 = 0.0
    filt1 = 0.0
    filt2 = 0.0
    peak = 0.0

    for i, p in enumerate(prices):
        p2 = prices[i - 2] if i >= 2 else prices[0]
        white = (p - p2) / 2.0
        filt = c1 * (white + white1) / 2.0 + c2 * filt1 + c3 * filt2
        peak = max(abs(filt), 0.991 * peak)
        oscillator.append(filt / peak if peak != 0 else 0.0)

        white1 = white
        filt2, filt1 = filt1, filt

    return _map_oscillator_to_price(timestamps, prices, oscillator)


# -----------------------------------------------------------------------------
# 12. Ehlers Reflex
# -----------------------------------------------------------------------------
def apply_reflex(timestamps: List[float], prices: List[float], length: int = 20) -> Tuple[List[float], List[float]]:
    if not prices or length < 1:
        return timestamps, prices

    filt = _super_smoother(prices, 0.5 * length)

    oscillator: List[float] = []
    ms = 0.0
    for i in range(len(filt)):
        slope = ((filt[i - length] if i >= length else filt[0]) - filt[i]) / length

        total = 0.0
        for count in range(1, length + 1):
            lagged = filt[i - count] if i - count >= 0 else filt[0]
            total += (filt[i] + count * slope) - lagged
        total /= length

        ms = total * total if i == 0 else 0.04 * total * total + 0.96 * ms
        oscillator.append(total / math.sqrt(ms) if ms > 0 else 0.0)

    return _map_oscillator_to_price(timestamps, prices, oscillator)


# -----------------------------------------------------------------------------
# 13. Ehlers Trendflex
# -----------------------------------------------------------------------------
def apply_trendflex(timestamps: List[float], prices: List[float], length: int = 20) -> Tuple[List[float], List[float]]:
    if not prices or length < 1:
        return timestamps, prices

    filt = _super_smoother(prices, 0.5 * length)

    oscillator: List[float] = []
    ms = 0.0
    for i in range(len(filt)):
        total = 0.0
        for count in range(1, length + 1):
            lagged = filt[i - count] if i - count >= 0 else filt[0]
            total += filt[i] - lagged
        total /= length

        ms = total * total if i == 0 else 0.04 * total * total + 0.96 * ms
        oscillator.append(total / math.sqrt(ms) if ms > 0 else 0.0)

    return _map_oscillator_to_price(timestamps, prices, oscillator)


# -----------------------------------------------------------------------------
# 14. Ehlers Fisher Transform
# -----------------------------------------------------------------------------
def apply_fisher_transform(timestamps: List[float], prices: List[float], length: int = 10) -> Tuple[List[float], List[float]]:
    if not prices or length < 1:
        return timestamps, prices

    oscillator: List[float] = []
    value1_prev = 0.0
    fish_prev = 0.0

    for i, p in enumerate(prices):
        start = max(0, i - length + 1)
        window = prices[start: i + 1]
        max_h = max(window)
        min_l = min(window)
        rng = max_h - min_l

        normalized = 2.0 * ((p - min_l) / rng - 0.5) if rng > 0 else 0.0
        value1 = 0.33 * normalized + 0.67 * value1_prev
        value1 = max(-0.999, min(0.999, value1))
        fish = 0.5 * math.log((1.0 + value1) / (1.0 - value1)) + 0.5 * fish_prev

        oscillator.append(fish)
        value1_prev = value1
        fish_prev = fish

    return _map_oscillator_to_price(timestamps, prices, oscillator)


# -----------------------------------------------------------------------------
# 15. Percentage Price Deviation Oscillator
# -----------------------------------------------------------------------------
def apply_price_deviation_oscillator(timestamps: List[float], prices: List[float], span: int = 10) -> Tuple[List[float], List[float]]:
    if not prices:
        return timestamps, prices

    _, baseline = apply_ema_reduction(timestamps, prices, span)
    oscillator = [100.0 * (p - b) / b if b != 0 else 0.0 for p, b in zip(prices, baseline)]

    return _map_oscillator_to_price(timestamps, prices, oscillator)


# -----------------------------------------------------------------------------
# Main Noise Reduction Dispatcher Function
# -----------------------------------------------------------------------------
def reduce_noise(
    algorithm: NoiseReductionAlgorithm,
    timestamps: List[float],
    prices: List[float],
) -> Tuple[List[float], List[float]]:
    """Applies the specified noise reduction algorithm to time series price data."""
    if not timestamps or not prices or algorithm == NoiseReductionAlgorithm.NONE:
        return timestamps, prices

    try:
        if algorithm == NoiseReductionAlgorithm.QUADTREE:
            return apply_quadtree_reduction(timestamps, prices)
        elif algorithm == NoiseReductionAlgorithm.EMA:
            return apply_ema_reduction(timestamps, prices)
        elif algorithm == NoiseReductionAlgorithm.EMA50:
            return apply_ema_reduction(timestamps, prices, span=50)
        elif algorithm == NoiseReductionAlgorithm.EMA200:
            return apply_ema_reduction(timestamps, prices, span=200)
        elif algorithm == NoiseReductionAlgorithm.SAVITZKY_GOLAY:
            return apply_savitzky_golay_reduction(timestamps, prices)
        elif algorithm == NoiseReductionAlgorithm.DOUGLAS_PEUCKER:
            return apply_rdp_reduction(timestamps, prices)
        elif algorithm == NoiseReductionAlgorithm.RPD1:
            return apply_rdp_reduction(timestamps, prices, tolerance=0.03)
        elif algorithm == NoiseReductionAlgorithm.RPD2:
            return apply_rdp_reduction(timestamps, prices, tolerance=0.0075)
        elif algorithm == NoiseReductionAlgorithm.DEMA:
            return apply_dema_reduction(timestamps, prices)
        elif algorithm == NoiseReductionAlgorithm.TEMA:
            return apply_tema_reduction(timestamps, prices)
        elif algorithm == NoiseReductionAlgorithm.HMA:
            return apply_hma_reduction(timestamps, prices)
        elif algorithm == NoiseReductionAlgorithm.KALMAN:
            return apply_kalman_filter(timestamps, prices)
        elif algorithm == NoiseReductionAlgorithm.PPD_FAST:
            return apply_price_deviation_oscillator(timestamps, prices, span=10)
        elif algorithm == NoiseReductionAlgorithm.PPD_SLOW:
            return apply_price_deviation_oscillator(timestamps, prices, span=50)
        elif algorithm == NoiseReductionAlgorithm.PASS_BAND:
            return apply_pass_band_filter(timestamps, prices)
        elif algorithm == NoiseReductionAlgorithm.DECYCLER_OSC:
            return apply_decycler_oscillator(timestamps, prices)
        elif algorithm == NoiseReductionAlgorithm.UNIVERSAL_OSC:
            return apply_universal_oscillator(timestamps, prices)
        elif algorithm == NoiseReductionAlgorithm.REFLEX:
            return apply_reflex(timestamps, prices)
        elif algorithm == NoiseReductionAlgorithm.TRENDFLEX:
            return apply_trendflex(timestamps, prices)
        elif algorithm == NoiseReductionAlgorithm.FISHER:
            return apply_fisher_transform(timestamps, prices)
    except Exception as e:
        logger.error(f"Error applying noise reduction algorithm {algorithm}: {e}")

    return timestamps, prices
