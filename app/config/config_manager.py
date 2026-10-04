import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional
from app.models.ticker import TickerConfig

logger = logging.getLogger(__name__)


class ConfigManager:
    def __init__(self, config_path: Path):
        self.config_path = config_path
        self._ensure_config_dir()

    def _ensure_config_dir(self) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

    def load_config(self) -> Tuple[List[TickerConfig], str, str]:
        """Loads configuration returning (list_of_ticker_configs, selected_ticker, selected_range)."""
        if not self.config_path.exists():
            logger.info("Config file not found. Creating default configuration.")
            return self._create_default_config()

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            tickers_data = data.get("tickers", [])
            tickers = [TickerConfig.from_dict(t) for t in tickers_data]
            selected_ticker = data.get("selected_ticker", "AAPL")
            selected_range = data.get("selected_range", "1Y")

            if not tickers:
                return self._create_default_config()

            return tickers, selected_ticker, selected_range
        except Exception as e:
            logger.error(f"Error reading config file: {e}. Falling back to default.")
            return self._create_default_config()

    def save_config(self, tickers: List[TickerConfig], selected_ticker: str = "AAPL", selected_range: str = "1Y") -> bool:
        """Saves current ticker list and selected preferences to JSON file."""
        try:
            self._ensure_config_dir()
            existing = self._read_raw_config()
            data = {
                **existing,
                "selected_ticker": selected_ticker,
                "selected_range": selected_range,
                "tickers": [t.to_dict() for t in tickers],
            }
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
            logger.info(f"Saved configuration to {self.config_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to save configuration: {e}")
            return False

    def load_enabled_filters(self) -> Optional[List[str]]:
        """Returns configured filter visibility list, or None when no setting exists yet."""
        if not self.config_path.exists():
            return None

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("enabled_filters")
        except Exception as e:
            logger.error(f"Error reading filter settings: {e}")
            return None

    def save_enabled_filters(self, enabled_filters: List[str]) -> bool:
        """Saves which noise reduction filters are visible in the UI combo box."""
        try:
            self._ensure_config_dir()
            existing = self._read_raw_config()
            existing["enabled_filters"] = list(enabled_filters)
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(existing, f, indent=4)
            logger.info(f"Saved filter settings to {self.config_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to save filter settings: {e}")
            return False

    def _read_raw_config(self) -> Dict[str, Any]:
        if not self.config_path.exists():
            return {}

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception as e:
            logger.error(f"Error reading config file: {e}")
            return {}

    def _create_default_config(self) -> Tuple[List[TickerConfig], str, str]:
        defaults = [
            TickerConfig("AAPL", "Apple Inc.", True),
            TickerConfig("MSFT", "Microsoft Corporation", True),
            TickerConfig("NVDA", "NVIDIA Corporation", True),
            TickerConfig("GOOGL", "Alphabet Inc.", True),
            TickerConfig("AMZN", "Amazon.com Inc.", True),
            TickerConfig("TSLA", "Tesla Inc.", True),
            TickerConfig("META", "Meta Platforms Inc.", True),
        ]
        self.save_config(defaults, "AAPL", "1Y")
        return defaults, "AAPL", "1Y"
