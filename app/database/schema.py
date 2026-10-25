CREATE_PRICES_TABLE = """
CREATE TABLE IF NOT EXISTS prices (
    symbol TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    adj_close REAL,
    volume INTEGER,
    dividends REAL DEFAULT 0.0,
    stock_splits REAL DEFAULT 0.0,
    PRIMARY KEY (symbol, timestamp)
);
"""

CREATE_PRICES_INDEX = """
CREATE INDEX IF NOT EXISTS idx_prices_symbol_timestamp ON prices (symbol, timestamp);
"""

CREATE_METADATA_TABLE = """
CREATE TABLE IF NOT EXISTS ticker_metadata (
    symbol TEXT PRIMARY KEY,
    company_name TEXT,
    currency TEXT,
    exchange TEXT,
    last_download TEXT,
    first_download TEXT,
    last_data_timestamp TEXT,
    status TEXT DEFAULT 'OK',
    error_message TEXT
);
"""

ADD_FIRST_DOWNLOAD_COLUMN = "ALTER TABLE ticker_metadata ADD COLUMN first_download TEXT;"

FILL_FIRST_DOWNLOAD = "UPDATE ticker_metadata SET first_download = last_download WHERE first_download IS NULL;"

CREATE_EARNINGS_TABLE = """
CREATE TABLE IF NOT EXISTS earnings (
    symbol TEXT NOT NULL,
    event_date TEXT NOT NULL,
    eps_estimate REAL,
    reported_eps REAL,
    surprise_pct REAL,
    is_estimated INTEGER NOT NULL DEFAULT 0,
    quarter TEXT,
    timing TEXT,
    PRIMARY KEY (symbol, event_date)
);
"""

CREATE_EARNINGS_META_TABLE = """
CREATE TABLE IF NOT EXISTS earnings_meta (
    symbol TEXT PRIMARY KEY,
    fetched_at TEXT
);
"""

CREATE_FORECASTS_TABLE = """
CREATE TABLE IF NOT EXISTS forecasts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    reference_date TEXT NOT NULL,
    reference_close REAL NOT NULL,
    target_date TEXT NOT NULL,
    horizon_months INTEGER NOT NULL,
    directional_bias TEXT NOT NULL,
    central_estimate REAL NOT NULL,
    lower_estimate REAL NOT NULL,
    upper_estimate REAL NOT NULL,
    expected_change_pct REAL NOT NULL,
    model_version TEXT NOT NULL,
    input_snapshot_json TEXT NOT NULL,
    signal_summary_json TEXT NOT NULL,
    evaluation_status TEXT NOT NULL DEFAULT 'pending',
    actual_price REAL,
    actual_date TEXT,
    actual_change_pct REAL,
    absolute_error REAL,
    percentage_error REAL,
    evaluated_at TEXT
);
"""

CREATE_FORECASTS_TICKER_INDEX = """
CREATE INDEX IF NOT EXISTS idx_forecasts_ticker ON forecasts (ticker);
"""

CREATE_FORECASTS_TARGET_INDEX = """
CREATE INDEX IF NOT EXISTS idx_forecasts_target_date ON forecasts (target_date);
"""

CREATE_FORECASTS_GENERATED_INDEX = """
CREATE INDEX IF NOT EXISTS idx_forecasts_generated_at ON forecasts (generated_at);
"""

CREATE_FORECASTS_STATUS_INDEX = """
CREATE INDEX IF NOT EXISTS idx_forecasts_evaluation_status ON forecasts (evaluation_status);
"""
