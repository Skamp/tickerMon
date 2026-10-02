import math
import logging
from enum import Enum
from typing import List, Tuple

logger = logging.getLogger(__name__)


class NoiseReductionAlgorithm(Enum):
    NONE = "None (Raw Data)"
    QUADTREE = "QuadTree Reduction"
    EMA = "Exponential Moving Average (EMA)"
    SAVITZKY_GOLAY = "Savitzky-Golay Filter"
    DOUGLAS_PEUCKER = "Ramer-Douglas-Peucker (RDP)"

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


def apply_rdp_reduction(timestamps: List[float], prices: List[float]) -> Tuple[List[float], List[float]]:
    if len(prices) <= 3:
        return timestamps, prices

    min_p, max_p = min(prices), max(prices)
    rng = (max_p - min_p) if max_p > min_p else 1.0

    pts = [(timestamps[i], (prices[i] - min_p) / rng * (timestamps[-1] - timestamps[0])) for i in range(len(prices))]
    simplified = _rdp_recursive(pts, epsilon=(timestamps[-1] - timestamps[0]) * 0.015)

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
        elif algorithm == NoiseReductionAlgorithm.SAVITZKY_GOLAY:
            return apply_savitzky_golay_reduction(timestamps, prices)
        elif algorithm == NoiseReductionAlgorithm.DOUGLAS_PEUCKER:
            return apply_rdp_reduction(timestamps, prices)
    except Exception as e:
        logger.error(f"Error applying noise reduction algorithm {algorithm}: {e}")

    return timestamps, prices
