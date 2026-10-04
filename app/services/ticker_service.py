import re
import logging
from typing import List, Tuple, Optional
from app.config.config_manager import ConfigManager
from app.models.ticker import TickerConfig
from app.services.noise_reduction import NoiseReductionAlgorithm

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

    def _save(self) -> None:
        self.config_manager.save_config(self.tickers, self.selected_ticker, self.selected_range)
