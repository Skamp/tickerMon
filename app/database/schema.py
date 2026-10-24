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
