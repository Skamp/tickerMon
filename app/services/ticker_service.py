import re
import logging
from typing import Any, Dict, List, Tuple, Optional
from app.config.config_manager import ConfigManager
from app.models.ticker import TickerConfig
from app.services.noise_reduction import NoiseReductionAlgorithm
from app.services.swing_detection import (
    SwingAlgorithm,
    SwingRangeMode,
    default_swing_params,
    normalize_swing_params,
)

logger = logging.getLogger(__name__)


class TickerService:
    def __init__(self, config_manager: ConfigManager):
        self.config_manager = config_manager
        self.tickers, self.selected_ticker, self.selected_range = self.config_manager.load_config()

    def get_all_tickers(self) -> List[TickerConfig]:
        return self.tickers

    def get_enabled_tickers(self) -> List[TickerConfig]:
        return [t for t in self.tickers if t.enabled]

    def add_ticker(self, symbol: str, name: Optional[str] = None) -> Tuple[bool, str]:
        clean_symbol = symbol.upper().strip()
        if not clean_symbol:
            return False, "Symbol cannot be empty."

        if not self.validate_ticker_symbol(clean_symbol):
            return False, f"Invalid symbol format: {clean_symbol}"

        for t in self.tickers:
            if t.symbol == clean_symbol:
                return False, f"Ticker {clean_symbol} already exists."

        display_name = name.strip() if name and name.strip() else clean_symbol
        new_config = TickerConfig(symbol=clean_symbol, name=display_name, enabled=True)
        self.tickers.append(new_config)
        self._save()
        return True, f"Added ticker {clean_symbol}"

    def update_ticker(self, symbol: str, name: str, enabled: bool) -> bool:
        clean_symbol = symbol.upper().strip()
        for t in self.tickers:
            if t.symbol == clean_symbol:
                t.name = name.strip() or clean_symbol
                t.enabled = enabled
                self._save()
                return True
        return False

    def delete_ticker(self, symbol: str) -> bool:
        clean_symbol = symbol.upper().strip()
        initial_count = len(self.tickers)
        self.tickers = [t for t in self.tickers if t.symbol != clean_symbol]
        if len(self.tickers) < initial_count:
            self._save()
            return True
        return False

    def reorder_tickers(self, ordered_symbols: List[str]) -> bool:
        symbol_map = {t.symbol: t for t in self.tickers}
        reordered = []
        for sym in ordered_symbols:
            sym_clean = sym.upper().strip()
            if sym_clean in symbol_map:
                reordered.append(symbol_map[sym_clean])

        # Append any missing tickers
        for t in self.tickers:
            if t not in reordered:
                reordered.append(t)

        self.tickers = reordered
        self._save()
        return True

    def validate_ticker_symbol(self, symbol: str) -> bool:
        """Validates symbol pattern (allows standard tickers like AAPL, SAP.DE, AIR.PA, ^GSPC, EURUSD=X)."""
        pattern = r"^[A-Z0-9\.\=\^\-\_]{1,15}$"
        return bool(re.match(pattern, symbol.upper().strip()))

    def set_preferences(self, selected_ticker: str, selected_range: str) -> None:
        self.selected_ticker = selected_ticker
        self.selected_range = selected_range
        self._save()

    def get_enabled_filters(self) -> List[str]:
        stored = self.config_manager.load_enabled_filters()
        if stored is None or not isinstance(stored, list):
            return [algorithm.value for algorithm in NoiseReductionAlgorithm if algorithm != NoiseReductionAlgorithm.NONE]
        known = {algorithm.value for algorithm in NoiseReductionAlgorithm}
        return [value for value in stored if value in known and value != NoiseReductionAlgorithm.NONE.value]

    def set_enabled_filters(self, enabled_filters: List[str]) -> bool:
        return self.config_manager.save_enabled_filters(enabled_filters)

    def get_enabled_swing_algorithms(self) -> List[str]:
        stored = self.config_manager.load_enabled_swing_algorithms()
        if stored is None or not isinstance(stored, list):
            return [algorithm.value for algorithm in SwingAlgorithm]
        known = {algorithm.value for algorithm in SwingAlgorithm}
        enabled = [value for value in stored if value in known]
        if not enabled:
            return [SwingAlgorithm.RANGE.value]
        return enabled

    def set_enabled_swing_algorithms(self, enabled_algorithms: List[str]) -> bool:
        cleaned = list(dict.fromkeys(enabled_algorithms))
        if not cleaned:
            cleaned = [SwingAlgorithm.RANGE.value]
        return self.config_manager.save_enabled_swing_algorithms(cleaned)

    def get_swing_params(self, algorithm: SwingAlgorithm) -> Dict[str, float]:
        stored = self.config_manager.load_swing_params()
        raw: Optional[Dict[str, Any]] = None
        if isinstance(stored, dict):
            candidate = stored.get(algorithm.value)
            if isinstance(candidate, dict):
                raw = candidate
        return normalize_swing_params(algorithm, raw)

    def get_all_swing_params(self) -> Dict[str, Dict[str, float]]:
        return {
            algorithm.value: self.get_swing_params(algorithm)
            for algorithm in SwingAlgorithm
        }

    def set_swing_params(self, params: Dict[str, Dict[str, float]]) -> bool:
        normalized: Dict[str, Dict[str, float]] = {}
        for algorithm in SwingAlgorithm:
            candidate = params.get(algorithm.value)
            source = candidate if isinstance(candidate, dict) else default_swing_params(algorithm)
            normalized[algorithm.value] = normalize_swing_params(algorithm, source)
        return self.config_manager.save_swing_params(normalized)

    def get_swing_range_settings(self) -> Dict[str, Any]:
        stored = self.config_manager.load_swing_range_settings()
        return self._normalize_swing_range_settings(stored if isinstance(stored, dict) else {})

    def set_swing_range_settings(self, settings: Dict[str, Any]) -> bool:
        return self.config_manager.save_swing_range_settings(
            self._normalize_swing_range_settings(settings)
        )

    @staticmethod
    def _normalize_swing_range_settings(settings: Dict[str, Any]) -> Dict[str, Any]:
        mode = SwingRangeMode.from_str(str(settings.get("mode", "")))
        value = TickerService._clamp_swing_range_value(settings.get("value", 0))
        value_max = TickerService._clamp_swing_range_value(settings.get("value_max", 0))
        unit = "weeks"
        if mode == SwingRangeMode.DURATION_WINDOW and 0 < value_max < value:
            value, value_max = value_max, value
        return {"mode": mode.value, "value": value, "value_max": value_max, "unit": unit}

    @staticmethod
    def _clamp_swing_range_value(raw: Any) -> int:
        try:
            value = int(round(float(raw)))
        except (TypeError, ValueError):
            return 0
        return max(0, min(value, 520))

    def _save(self) -> None:
        self.config_manager.save_config(self.tickers, self.selected_ticker, self.selected_range)
