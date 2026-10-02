# tickerMon - Stock Market Monitoring Desktop Application

A clean, fast, modular Python 3.12+ desktop application for monitoring configurable stock market tickers and visualizing historical price performance. Inspired by dark-themed financial market terminals.

Built with **PySide6**, **PyQtGraph**, **yfinance**, **SQLite**, and **pandas**.

---

## 🌟 Key Features

- **Offline-First / Zero Lag**: Switching between tickers and time ranges queries a local SQLite database cache without network delays or web calls.
- **Asynchronous Sync**: Historical market data downloads execute on a non-blocking background `QThread` with live per-ticker progress reporting.
- **Interactive Financial Charts**: Dark-themed PyQtGraph time-series chart with crosshair cursor, hover tooltips (Date & Price), auto-scaling, and zoom controls.
- **Flexible Time Ranges**: View price performance across **1D**, **1W**, **1M**, **6M**, and **1Y** intervals.
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
|    (MarketDataService / TickerService / SyncService)        |
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
   ```cmd
   pip install -r requirements.txt
   ```

---

## ⚙️ Configuration

Ticker configurations are stored in `config/tickers.json`. You can edit this file manually or via the **Manage Tickers** (`Ctrl+T`) UI dialog.

Sample `config/tickers.json`:
```json
{
    "selected_ticker": "AAPL",
    "selected_range": "1Y",
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

Launch the application using:

```cmd
python main.py
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

Run the unit test suite using Python's `unittest` module:

```cmd
python -m unittest discover -s tests -p "test_*.py"
```

---

## 📝 Logging

Diagnostic logs are saved automatically to `logs/app.log`.
