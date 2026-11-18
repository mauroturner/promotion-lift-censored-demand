-- The core tables of the warehouse (plan, section 5; RF08, D22): series, deliveries, series-days, the hour profile, the runs and the validation
-- results. Every statement is idempotent (CREATE TABLE IF NOT EXISTS) and the file is run by promolift.warehouse statement by statement, never with
-- executescript. The hours of every series-day live in the cube (data/interim/cube); here are the series-days and their sums of 06 to 21.

CREATE TABLE IF NOT EXISTS series (
    series_key INTEGER PRIMARY KEY,
    store_id INTEGER NOT NULL,
    city_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    management_group_id INTEGER NOT NULL,
    first_category_id INTEGER NOT NULL,
    second_category_id INTEGER NOT NULL,
    third_category_id INTEGER NOT NULL,
    UNIQUE (store_id, product_id)
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_key TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL CHECK (status IN ('running', 'ok', 'failed', 'rejected', 'no_delivery')),
    delivery_id TEXT,
    as_of TEXT,
    train_sha256 TEXT,
    eval_sha256 TEXT,
    series_days_delivery INTEGER,
    rows_issued INTEGER,
    peak_working_set_mb REAL,
    peak_commit_mb REAL,
    memory_counter TEXT,
    message TEXT
);

CREATE TABLE IF NOT EXISTS deliveries (
    delivery_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('launch', 'daily', 'close')),
    first_day TEXT,
    last_day TEXT,
    as_of TEXT NOT NULL,
    series_days INTEGER NOT NULL CHECK (series_days >= 0),
    sha256 TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('published', 'loaded', 'rejected')),
    run_key TEXT
);

CREATE TABLE IF NOT EXISTS series_days (
    series_key INTEGER NOT NULL REFERENCES series (series_key),
    date_key INTEGER NOT NULL,
    delivery_id TEXT NOT NULL REFERENCES deliveries (delivery_id),
    day_state TEXT NOT NULL CHECK (day_state IN ('promo', 'regular', 'unflagged_cut', 'anomalous')),
    band INTEGER CHECK (band IS NULL OR band >= 0),
    activity_flag INTEGER NOT NULL CHECK (activity_flag IN (0, 1)),
    discount REAL NOT NULL,
    holiday_flag INTEGER NOT NULL CHECK (holiday_flag IN (0, 1)),
    raw_sum REAL NOT NULL CHECK (raw_sum >= 0),
    instock_hours INTEGER NOT NULL CHECK (instock_hours >= 0),
    stockout_hours INTEGER NOT NULL CHECK (stockout_hours >= 0),
    instock_sum REAL NOT NULL CHECK (instock_sum >= 0),
    recovered_sum REAL,
    fully_out INTEGER NOT NULL CHECK (fully_out IN (0, 1)),
    PRIMARY KEY (series_key, date_key)
);

CREATE INDEX IF NOT EXISTS ix_series_days_date ON series_days (date_key);
CREATE INDEX IF NOT EXISTS ix_series_days_delivery ON series_days (delivery_id);

CREATE TABLE IF NOT EXISTS hour_profile (
    date_key INTEGER NOT NULL,
    management_group_id INTEGER NOT NULL,
    hour INTEGER NOT NULL CHECK (hour BETWEEN 0 AND 23),
    day_state TEXT NOT NULL CHECK (day_state IN ('promo', 'regular', 'unflagged_cut', 'anomalous')),
    series_days INTEGER NOT NULL CHECK (series_days > 0),
    sales_sum REAL NOT NULL CHECK (sales_sum >= 0),
    stockout_count INTEGER NOT NULL CHECK (stockout_count >= 0),
    delivery_id TEXT NOT NULL REFERENCES deliveries (delivery_id),
    PRIMARY KEY (date_key, management_group_id, hour, day_state)
);

CREATE TABLE IF NOT EXISTS validation_results (
    run_key TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    name_es TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('blocking', 'warning', 'info')),
    scope TEXT NOT NULL,
    aggregation TEXT NOT NULL CHECK (aggregation IN ('source', 'per_run', 'latest')),
    passed INTEGER NOT NULL CHECK (passed IN (0, 1)),
    series_days_affected INTEGER NOT NULL,
    hours_affected INTEGER NOT NULL,
    examples_json TEXT NOT NULL,
    PRIMARY KEY (run_key, rule_id)
);
