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
    last_data_timestamp TEXT,
    status TEXT DEFAULT 'OK',
    error_message TEXT
);
"""
