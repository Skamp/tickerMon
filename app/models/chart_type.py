from enum import Enum


class ChartType(Enum):
    LINE = "Line"
    CANDLE = "Candle"
    BASELINE = "Baseline"

    @classmethod
    def from_str(cls, val: str) -> "ChartType":
        for item in cls:
            if item.value == val or item.name == val:
                return item
        return cls.LINE
