
## Project Overview
tickerMon is a PySide6 desktop application for monitoring stock tickers with local SQLite caching, PyQtGraph charts, and Yahoo Finance (yfinance) as the data source.

Beyond raw price charts it provides:
- **Noise-reduction overlays** (20 filters) selected from a toolbar combo, with visibility toggled through the `Filters…` dialog.
- **Swing detection overlays** (22 algorithms) drawn on the chart as pivots + legs, configured through the `Swing…` dialog and a toolbar duration-range filter.
- **Trend/swing sidebar filtering**: tickers are bucketed into `Rise/Down/Lateral/Unsure` (±2% over the active range) or flagged as swinging, with live counts above `MARKET WATCH`.

## Tech Stack (from requirements.txt)
- **Python**: 3.12+
- **PySide6 >= 6.6.0** - Qt6 GUI framework
- **pyqtgraph >= 0.13.3** - Interactive financial charts and plotting
- **yfinance >= 0.2.36** - Yahoo Finance market data API
- **pandas >= 2.1.0** - Data manipulation and time-series processing
- **scipy >= 1.11.0** - Peak finding for the Pivot Window swing algorithm
- **ruptures >= 1.1.9** - Change-point detection (PELT) for the Change-Point swing algorithm
- **numpy** - Numeric arrays (pulled in transitively by pandas/scipy; used directly by `app/services/swing_detection.py`)
- **pytest >= 7.4.0** - Unit testing framework

## Key Modules
- `app/ui/main_window.py` - Toolbar (Filter / Swing / Duration rows), sidebar wiring, overlay refresh.
- `app/ui/chart_widget.py` - Price curve, filter overlay, swing overlay (zigzag, leg bands, annotation), fit-view zoom limits.
- `app/ui/ticker_list.py` / `app/ui/trend_filter_bar.py` - Sidebar list with trend/swing filtering and selection preservation.
- `app/ui/filter_settings_dialog.py` / `app/ui/swing_settings_dialog.py` - Visibility + parameter dialogs.
- `app/services/noise_reduction.py` - `NoiseReductionAlgorithm` enum and the `reduce_noise()` dispatcher.
- `app/services/swing_detection.py` - `SwingAlgorithm`, `SwingRangeMode`, parameter specs, detectors, `detect_swings()`, `restrict_swing_pivots()`.
- `app/services/market_data_service.py` - Chart/OHLCV data, `classify_price_series()`, trend buckets, swing symbols & overlay.
- `app/services/ticker_service.py` / `app/config/config_manager.py` - Persisted settings (`enabled_filters`, `enabled_swing_algorithms`, `swing_algorithm_params`, `swing_range_settings`).

## Configuration
All preferences live in `config/tickers.json` and are written through `ConfigManager`, which merges unknown keys on save. UI settings must be read/written via `TickerService` accessors (they normalize/clamp values), not by editing the JSON directly from UI code.

## Environment Setup
Create and activate a virtual environment, then install dependencies:

```bash
python -m venv .venv
source activate.sh  # or source .venv/bin/activate (Linux/WSL)
pip install -r requirements.txt
```
## Running the Application
With the virtual environment activated:

```bash
python main.py
```

##Testing
The project uses pytest (installed via requirements). Run tests with:

```bash
pytest -v
```

You can also run with unittest (as documented in README):

```bash
python -m unittest discover -s tests -p "test_*.py"
```

Test modules: `test_config.py`, `test_database.py`, `test_market_data.py`, `test_noise_reduction.py`, `test_swing_detection.py`, `test_time_ranges.py`.

## Project Conventions
- Follow PEP 8 style guidelines with 4-space indentation.
- Preserve the existing layered architecture: UI (app/ui/) → Services (app/services/) → Repositories/Database (app/database/) → External APIs.
- Mimic existing code style, naming conventions, and patterns when making changes.
- Add no comments unless explicitly requested by the user.
- Never introduce code that logs or exposes secrets/keys.
- Check existing utilities/libraries before adding new dependencies.
- Keep changes minimal and focused on the task at hand.
- New enums expose `from_str()` with a safe fallback; UI combos store enum members via `userData` and rebuild with signals blocked.
- Optional third-party imports (`scipy`, `ruptures`) must degrade gracefully to NumPy fallbacks.

## Development Guidelines
- Read relevant files first to understand context before editing.
- Prefer editing existing files over creating new ones unless necessary.
- After completing changes, run tests to verify correctness when possible.
- Do not commit changes unless explicitly requested by the user.

The file captures the dependencies, setup, run/test commands, and agent-friendly conventions based on the codebase.