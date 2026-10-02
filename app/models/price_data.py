from dataclasses import dataclass, field
from typing import List, Optional
import pandas as pd


@dataclass
class PricePoint:
    symbol: str
    timestamp: str  # ISO8601 string or YYYY-MM-DD / YYYY-MM-DD HH:MM:SS
    open: float
    high: float
    low: float
    close: float
    adj_close: float
    volume: int
    dividends: float = 0.0
    stock_splits: float = 0.0


@dataclass
class PriceSeries:
    symbol: str
    points: List[PricePoint] = field(default_factory=list)

    def to_dataframe(self) -> pd.DataFrame:
        if not self.points:
            return pd.DataFrame()
        data = [
            {
                "symbol": p.symbol,
                "timestamp": p.timestamp,
                "open": p.open,
                "high": p.high,
                "low": p.low,
                "close": p.close,
                "adj_close": p.adj_close,
                "volume": p.volume,
                "dividends": p.dividends,
                "stock_splits": p.stock_splits,
            }
            for p in self.points
        ]
        df = pd.DataFrame(data)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        return df
