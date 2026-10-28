# tickerMon - Stock Market Monitoring Desktop Application

A clean, fast, modular Python 3.12+ desktop application for monitoring configurable stock market tickers and visualizing historical price performance. Inspired by dark-themed financial market terminals.

Built with **PySide6**, **PyQtGraph**, **yfinance**, **SQLite**, **pandas**, **numpy**, **scipy**, and **ruptures**.

---

## 🌟 Key Features

- **Offline-First / Zero Lag**: Switching between tickers and time ranges queries a local SQLite database cache without network delays or web calls.
- **Asynchronous Sync**: Historical market data downloads execute on a non-blocking background `QThread` with live per-ticker progress reporting.
- **Interactive Financial Charts**: Dark-themed PyQtGraph time-series chart with crosshair cursor, hover tooltips (Date & Price), auto-scaling, and zoom controls clamped to the fit-view bounds (reset returns to it).
- **Three Chart Types**: Switch the price pane between **Line** (default), **Candle** (OHLC candlesticks), and **Baseline** (close relative to the first price of the range) from a compact toolbar dropdown.
- **Volume Panel**: A compact volume sub-chart sits below the price chart on the same shared time axis, with green/red/neutral bars approximating buying/selling pressure from candle direction.
- **Flexible Time Ranges**: View price performance across **1W**, **2W**, **3W**, **1M**, **6M**, **1Y**, and **5Y** intervals.
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

Ticker configurations and UI preferences are stored in `config/tickers.json`. You can edit this file manually or via the **Manage Tickers** (`Ctrl+T`), **Filters…**, and **Swing…** UI dialogs. A full template with every supported key is provided in `config/tickers.example.json` (the real `config/tickers.json` is git-ignored and auto-created on first run).

| Key | Description |
| :--- | :--- |
| `selected_ticker` / `selected_range` | Last selected symbol and time range |
| `tickers` | Watchlist entries (`symbol`, `name`, `enabled`) |
| `ui_scale` | Optional UI scale multiplier applied on top of OS display scaling (the `TICKERMON_SCALE` environment variable overrides it) |
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

### Display scaling & DPI diagnostics

The DPI policy (Qt scale-factor rounding policy, Windows DPI awareness) and the
application default font are pinned at startup in `app/ui/scaling.py`, so the
UI renders at the same relative size across Python/Qt versions and machines.

```bash
python main.py --debug-dpi
```

prints the Python/PySide6/Qt/pyqtgraph versions, the screen's device pixel
ratio and logical/physical DPI, the effective application font, the active
scaling environment variables and the Windows process DPI awareness state.

On Python 3.13 and newer, a default `"ui_scale": 1.5` is seeded into
`config/tickers.json` on the first launch where the key is missing, so the
UI matches the 150%-scaled reference machine. An existing value is never
overwritten — edit or delete the key to opt out, or use `TICKERMON_SCALE`
for a per-run override.

Scale/font overrides (highest precedence first):

| Override | Effect |
| :--- | :--- |
| `TICKERMON_SCALE` (env) | Global scale multiplier on top of OS display scaling (e.g. `TICKERMON_SCALE=1.25`); overrides `ui_scale` in `config/tickers.json` |
| `ui_scale` (config) | Same multiplier, persisted per machine in `config/tickers.json` |
| `TICKERMON_FONT_FAMILY` / `TICKERMON_FONT_POINT` (env) | Override the pinned application font family / point size |

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
- Clicking **Update all tickers** (`Ctrl+U`) downloads missing price records incrementally based on the latest stored local timestamp.
- Clicking **Update new tickers** only downloads data for enabled tickers that have no price rows in the local database yet (newly added symbols).
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

## 📈 Chart Types

A compact `Chart type:` dropdown stacked below the `Range:` buttons switches the price pane between three rendering modes; the selection is persisted in `config/tickers.json` and defaults to **Line**:

| Mode | Rendering |
| :--- | :--- |
| **Line** | The original close-price line with its soft fill, overlays, and tooltips. |
| **Candle** | Green/red/neutral OHLC candlesticks (body from Open to Close, wicks to High/Low) built from the same locally cached OHLC rows used for swing detection — no extra API request. Invalid or missing OHLC rows are skipped; when no valid candle exists the chart falls back to the line. The tooltip adds `O`/`H`/`L` values. |
| **Baseline** | The close line relative to the first valid close of the selected range: a dashed horizontal reference line with green fill above it and red fill below it, including interpolated crossing points so fills meet the baseline exactly. The baseline is recomputed on ticker/range change, not on zoom/pan. The tooltip shows the baseline value. |

All three modes keep the volume panel X-linked on the same time scale, and the filter and swing overlays continue to work unchanged. Changing the chart type redraws immediately from cached data.

---

## 📊 Volume Panel

Below the price chart a compact `VolumeChartWidget` renders one bar per price period, built from the same local OHLCV rows (Date, Open, Close, Volume — no additional API request):

- Bar **height** is the real traded volume; the right-hand Y-axis abbreviates values (`1.2K`, `3.5M`, `2.1B`).
- Bar **color** approximates pressure from candle direction — `Close > Open` green (Buying), `Close < Open` red (Selling), `Close == Open` dimmed (Neutral). Yahoo Finance reports only total traded volume, so this is an estimate, not actual buy/sell order flow.
- Hovering a bar shows date, volume, open, close, change %, and the estimated pressure; a legend sits next to the `VOLUME` title.
- The panel's time axis is X-linked to the price chart, so ticker, range, zoom, pan and duration changes keep both charts on the same time scale; its own bottom axis is hidden to avoid duplicated date labels. The panel gets ~25% of the chart area (price ~75%).

---

## 🧭 Trend & Swing Sidebar Filtering

`TrendFilterBar` sits above `MARKET WATCH` and shows live counts per bucket:

- **All** — master toggle; clears every other filter.
- **Swing** — tickers whose price series produced at least one leg under the active swing algorithm (the legacy `Min-Max Range (10%)` rule flags moves of ≥10% of the window).
- **Rise / Down / Lateral / Unsure** — classified from the first to the last price of the active time range using a ±2% threshold (`Unsure` when there are fewer than two valid points).

Filters combine with OR, preserve the current selection when possible (falling back to the first visible ticker), and are recomputed whenever the time range, swing algorithm, or settings change.

A **Sort** combo below the `MARKET WATCH` header orders the list by ticker, by date ascending, or by date descending. The date is the moment the ticker was added to the tool (stored as `added_at` in `config/tickers.json`); tickers added before this field existed have no date and are grouped first when sorting ascending, last when descending.

---

## ⌨️ Keyboard Shortcuts

| Shortcut | Action |
| :--- | :--- |
| `Up Arrow` | Select previous ticker in list |
| `Down Arrow` | Select next ticker in list |
| `Home` | Select first ticker in list |
| `End` | Select last ticker in list |
| `R` | Refresh current chart from local database |
| `Ctrl+U` | Trigger "Update all tickers" market sync |
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
| `tests/test_chart_type.py` | Chart type enum, candle classification/geometry, baseline series splitting |
| `tests/test_config.py` | Config persistence, filter/swing settings, params & range normalization |
| `tests/test_database.py` | SQLite repository behaviour |
| `tests/test_market_data.py` | Chart data, OHLCV alignment, trend bucketing, swing symbols & overlay |
| `tests/test_noise_reduction.py` | Every noise-reduction algorithm |
| `tests/test_swing_detection.py` | All 22 swing detectors, parameter specs, duration range filtering |
| `tests/test_ticker_list.py` | Sidebar sorting by ticker and by added date |
| `tests/test_time_ranges.py` | Time range boundaries |
| `tests/test_volume_chart.py` | Volume formatting, pressure classification & bar width |

---

## 📝 Logging

Diagnostic logs are saved automatically to `logs/app.log`.
