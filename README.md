# tickerMon - Stock Market Monitoring Desktop Application

A clean, fast, modular Python 3.12+ desktop application for monitoring configurable stock market tickers and visualizing historical price performance. Inspired by dark-themed financial market terminals.

Built with **PySide6**, **PyQtGraph**, **yfinance**, **SQLite**, **pandas**, **numpy**, **scipy**, and **ruptures**.

---

## 🌟 Key Features

- **Offline-First / Zero Lag**: Switching between tickers and time ranges queries a local SQLite database cache without network delays or web calls.
- **Asynchronous Sync**: Historical market data downloads execute on a non-blocking background `QThread` with live per-ticker progress reporting.
- **Interactive Financial Charts**: Dark-themed PyQtGraph time-series chart with crosshair cursor, hover tooltips (Date & Price), auto-scaling, and zoom controls clamped to the fit-view bounds (reset returns to it).
- **Flexible Time Ranges**: View price performance across **1D**, **1W**, **1M**, **6M**, and **1Y** intervals.
- **20 Noise-Reduction Filters**: Overlay the price curve with QuadTree, EMA / EMA 50 / EMA 200, DEMA, TEMA, HMA, Savitzky-Golay, RDP (default / loose / tight), Kalman, Ehlers pass-band, decycler & universal oscillators, Reflex, Trendflex, Fisher, and fast/slow price-deviation oscillators.
- **Swing Detection Overlay**: 22 swing algorithms drawn as a violet zigzag with pivot markers, translucent yellow leg bands, and a boxed readout of the active algorithm, its parameters, and the current range filter.
- **Trend & Swing Sidebar Filtering**: Every ticker is bucketed as **Rise / Down / Lateral / Unsure** (±2% over the active range) or flagged as a **Swing**, with live counts and multi-select toggles above `MARKET WATCH`.
- **Swing Duration Filtering**: Restrict detected swings by minimum duration, maximum duration, lookback window, or a two-sided duration window, expressed in weeks, directly from the toolbar.
- **Configurable Dropdowns**: `Filters…` and `Swing…` dialogs choose which entries appear in each combo box and edit per-algorithm parameters; everything persists to `config/tickers.json`.
- **Ticker Administration**: Add, edit, remove, enable/disable, and reorder ticker symbols easily from the UI.
- **Resilient & Reliable**: Robust error handling for rate limits, delisted tickers, missing data, and invalid symbols.
- **Keyboard Shortcuts**: Complete keyboard navigation for rapid ticker cycling (`Up`/`Down`, `Home`/`End`, `R` refresh, `Ctrl+U` update, `Ctrl+T` admin, `Ctrl+Q` quit).

---

## 🏗 Architecture & Design

The application enforces strict separation of concerns through a layered architecture:

```
+-------------------------------------------------------------+
|                      PySide6 GUI                            |
|        (MainWindow / TickerList / StockChartWidget)         |
+-------------------------------------------------------------+
                               |
                               v
+-------------------------------------------------------------+
|                    Application Services                     |
| (MarketDataService / TickerService / SyncService /          |
|  NoiseReduction / SwingDetection)                           |
+-------------------------------------------------------------+
               |                               |
               v                               v
+-----------------------------+  +----------------------------+
|     SQLite Repository       |  |   Yahoo Finance Service    |
|   (MarketDataRepository)    |  |       (YahooService)       |
+-----------------------------+  +----------------------------+
               |                               |
               v                               v
+-----------------------------+  +----------------------------+
|       SQLite Database       |  |       Yahoo Finance        |
|    (data/market_data.db)    |  |           (API)            |
+-----------------------------+  +----------------------------+
```

---

## 💻 System Requirements

- **Operating System**: Windows 10/11 (or Linux / macOS)
- **Python**: 3.12 or higher

---

## 🚀 Installation & Setup

1. **Clone or navigate to the project directory**:
   ```cmd
   cd e:\Workspaces\tickerMon
   ```

2. **Create a Python Virtual Environment**:
   ```cmd
   python -m venv .venv
   ```

3. **Activate the Virtual Environment**:
   - **WSL / Git Bash / Bash**:
     ```bash
     source activate.sh
     # or
     source .venv/bin/activate
     # or (Windows venv on Linux)
     source .venv/Scripts/activate
     ```
   - **Windows Command Prompt**:
     ```cmd
     .venv\Scripts\activate.bat
     ```
   - **Windows PowerShell**:
     ```powershell
     .venv\Scripts\Activate.ps1
     ```

4. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

---

## ⚙️ Configuration

Ticker configurations and UI preferences are stored in `config/tickers.json`. You can edit this file manually or via the **Manage Tickers** (`Ctrl+T`), **Filters…**, and **Swing…** UI dialogs.

| Key | Description |
| :--- | :--- |
| `selected_ticker` / `selected_range` | Last selected symbol and time range |
| `tickers` | Watchlist entries (`symbol`, `name`, `enabled`) |
| `enabled_filters` | Noise-reduction algorithms shown in the `Filter:` combo (missing = all enabled, `None (Raw Data)` is always present) |
| `enabled_swing_algorithms` | Swing algorithms shown in the `Swing:` combo (falls back to `Min-Max Range (10%)` when empty) |
| `swing_algorithm_params` | Per-algorithm parameters keyed by algorithm name; values are clamped/normalized on load |
| `swing_range_settings` | `mode`, `value`, `value_max`, `unit` for the toolbar duration filter |

Sample `config/tickers.json`:
```json
{
    "selected_ticker": "AAPL",
    "selected_range": "1Y",
    "enabled_filters": [
        "Exponential Moving Average (EMA)",
        "Kalman Filter"
    ],
    "enabled_swing_algorithms": [
        "Min-Max Range (10%)",
        "ZigZag"
    ],
    "swing_algorithm_params": {
        "ZigZag": { "threshold_pct": 5.0 }
    },
    "swing_range_settings": {
        "mode": "Duration window (both bounds)",
        "value": 2,
        "value_max": 4,
        "unit": "weeks"
    },
    "tickers": [
        {
            "symbol": "AAPL",
            "name": "Apple Inc.",
            "enabled": true
        },
        {
            "symbol": "MSFT",
            "name": "Microsoft Corporation",
            "enabled": true
        },
        {
            "symbol": "NVDA",
            "name": "NVIDIA Corporation",
            "enabled": true
        },
        {
            "symbol": "SAP.DE",
            "name": "SAP SE",
            "enabled": true
        }
    ]
}
```

---

## 🏃 Running the Application

Launch the application using (with venv activated):

```bash
python main.py
```

or

```bash
.venv/Scripts/python.exe main.py
```

Directories `config/`, `data/`, and `logs/` will be created automatically if they do not exist.

---

## 🗄 SQLite Local Cache & Database Structure

Historical market data is stored locally in SQLite at `data/market_data.db`.

### `prices` Table Schema
| Column | Type | Description |
| :--- | :--- | :--- |
| `symbol` | TEXT | Stock ticker symbol (e.g. `AAPL`) |
| `timestamp` | TEXT | ISO8601 formatted timestamp (`YYYY-MM-DD HH:MM:SS`) |
| `open` | REAL | Opening price |
| `high` | REAL | High price |
| `low` | REAL | Low price |
| `close` | REAL | Closing price |
| `adj_close` | REAL | Adjusted closing price |
| `volume` | INTEGER | Trading volume |
| `dividends` | REAL | Dividend payout |
| `stock_splits` | REAL | Stock split ratio |

- **Primary Key**: `(symbol, timestamp)`
- **Index**: `idx_prices_symbol_timestamp` on `(symbol, timestamp)`

### `ticker_metadata` Table Schema
Tracks synchronization timestamps and download status for each ticker symbol.

---

## 🌐 Yahoo Finance Integration & Sync Strategy

- Data fetching is handled by `yfinance`.
- Clicking **Update Data** (`Ctrl+U`) downloads missing price records incrementally based on the latest stored local timestamp.
- Errors (e.g., rate limits, invalid symbols, delisted securities) are logged to `logs/app.log` without crashing the GUI.

---

## 📈 Chart Overlays

Two independent overlays can be drawn on top of the raw price curve:

- **Filter overlay (amber)**: the currently selected noise-reduction algorithm from the `Filter:` combo. `None (Raw Data)` is always available; the remaining entries are toggled in the `Filters…` dialog.
- **Swing overlay (violet)**: pivots and legs produced by the selected algorithm from the `Swing:` combo, with a yellow band per leg and a top-left annotation listing the algorithm, its parameters, and the swing range filter.

Swing detection is parameterized per algorithm (`Swing…` dialog) and can be restricted by duration:

| Mode | Meaning |
| :--- | :--- |
| Minimum duration | Keep swings taking at least *X* weeks |
| Maximum duration | Keep swings completing within *X* weeks |
| Lookback window | Only detect swings in the last *X* weeks |
| Duration window | Keep swings between *X* and *Y* weeks (upper bound hidden in other modes) |

A value of `0` in the first box disables the range filter (`Off`).

Changing the swing algorithm, its parameters, or the duration filter re-buckets the sidebar and redraws the overlay immediately.

---

## 🧭 Trend & Swing Sidebar Filtering

`TrendFilterBar` sits above `MARKET WATCH` and shows live counts per bucket:

- **All** — master toggle; clears every other filter.
- **Swing** — tickers whose price series produced at least one leg under the active swing algorithm (the legacy `Min-Max Range (10%)` rule flags moves of ≥10% of the window).
- **Rise / Down / Lateral / Unsure** — classified from the first to the last price of the active time range using a ±2% threshold (`Unsure` when there are fewer than two valid points).

Filters combine with OR, preserve the current selection when possible (falling back to the first visible ticker), and are recomputed whenever the time range, swing algorithm, or settings change.

---

## ⌨️ Keyboard Shortcuts

| Shortcut | Action |
| :--- | :--- |
| `Up Arrow` | Select previous ticker in list |
| `Down Arrow` | Select next ticker in list |
| `Home` | Select first ticker in list |
| `End` | Select last ticker in list |
| `R` | Refresh current chart from local database |
| `Ctrl+U` | Trigger "Update Data" market sync |
| `Ctrl+T` | Open Ticker Administration dialog |
| `Ctrl+Q` | Quit application |

---

## 🧪 Running Unit Tests

The suite uses **pytest** (installed via `requirements.txt`):

```bash
pytest -v
```

Python's `unittest` runner works as well:

```bash
python -m unittest discover -s tests -p "test_*.py"
```

Test modules:

| Module | Coverage |
| :--- | :--- |
| `tests/test_config.py` | Config persistence, filter/swing settings, params & range normalization |
| `tests/test_database.py` | SQLite repository behaviour |
| `tests/test_market_data.py` | Chart data, OHLCV alignment, trend bucketing, swing symbols & overlay |
| `tests/test_noise_reduction.py` | Every noise-reduction algorithm |
| `tests/test_swing_detection.py` | All 22 swing detectors, parameter specs, duration range filtering |
| `tests/test_time_ranges.py` | Time range boundaries |

---

## 📝 Logging

Diagnostic logs are saved automatically to `logs/app.log`.
