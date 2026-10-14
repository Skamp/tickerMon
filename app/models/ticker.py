from dataclasses import dataclass
from typing import Optional


@dataclass
class TickerConfig:
    symbol: str
    name: str
    enabled: bool = True
    added_at: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol.upper().strip(),
            "name": self.name.strip(),
            "enabled": self.enabled,
            "added_at": self.added_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TickerConfig":
        return cls(
            symbol=data.get("symbol", "").upper().strip(),
            name=data.get("name", "").strip(),
            enabled=data.get("enabled", True),
            added_at=data.get("added_at"),
        )


@dataclass
class TickerSummary:
    symbol: str
    company_name: str
    current_price: Optional[float] = None
    price_change: Optional[float] = None
    pct_change: Optional[float] = None
    currency: Optional[str] = None
    exchange: Optional[str] = None
    last_updated: Optional[str] = None
    status: str = "OK"
    error_message: Optional[str] = None
    added_at: Optional[str] = None
