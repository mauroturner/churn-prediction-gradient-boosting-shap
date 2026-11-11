-- The core of the warehouse (plan, section 5; D24): the deliveries, the lines they brought, the runs and the results of the validation.
-- Every table is created only if it does not exist: applying the schema again keeps the data. stg_lines is rebuilt by
-- sql/staging/stg_lines.sql for each calculation date.

CREATE TABLE IF NOT EXISTS deliveries (
    delivery_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('launch', 'monthly', 'close')),
    lines_from TEXT NOT NULL,
    lines_to TEXT NOT NULL,
    as_of_date TEXT NOT NULL,
    lines INTEGER NOT NULL CHECK (lines >= 0),
    sha256 TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('published', 'loaded', 'rejected')),
    run_key TEXT
);

CREATE TABLE IF NOT EXISTS raw_lines (
    line_id INTEGER PRIMARY KEY,
    delivery_id TEXT NOT NULL REFERENCES deliveries (delivery_id),
    sheet INTEGER NOT NULL,
    source_row INTEGER NOT NULL,
    invoice TEXT NOT NULL,
    stock_code TEXT NOT NULL,
    description TEXT,
    quantity INTEGER NOT NULL,
    invoice_ts TEXT NOT NULL,          -- local date and time of the file, 'YYYY-MM-DD HH:MM:SS'
    invoice_date TEXT NOT NULL,        -- the first date of the invoice, 'YYYY-MM-DD'
    price REAL NOT NULL,
    customer_id INTEGER,               -- null for a guest
    country TEXT NOT NULL,
    code_kind TEXT NOT NULL CHECK (code_kind IN ('product', 'service', 'gift_voucher')),
    is_repeated_line INTEGER NOT NULL CHECK (is_repeated_line IN (0, 1))
);

CREATE INDEX IF NOT EXISTS raw_lines_by_date ON raw_lines (invoice_date);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_key TEXT PRIMARY KEY,
    started_at TEXT,
    finished_at TEXT,
    status TEXT NOT NULL CHECK (status IN ('running', 'ok', 'failed', 'rejected', 'no_delivery')),
    delivery_id TEXT,
    as_of_date TEXT,
    cut_date TEXT,
    source_sha256 TEXT,
    lines_delivery INTEGER,
    customers_scored INTEGER,
    contacts INTEGER,
    peak_working_set_mb REAL,
    peak_commit_mb REAL,
    memory_counter TEXT,
    message TEXT
);

CREATE TABLE IF NOT EXISTS validation_results (
    run_key TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    name_es TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('blocking', 'warning', 'info')),
    scope TEXT NOT NULL CHECK (scope IN ('source', 'delivery', 'lines', 'model')),
    aggregation TEXT NOT NULL CHECK (aggregation IN ('source', 'per_run', 'latest')),
    passed INTEGER NOT NULL CHECK (passed IN (0, 1)),
    rows_affected INTEGER NOT NULL,
    customers_affected INTEGER NOT NULL,
    value_gbp REAL NOT NULL,
    examples_json TEXT NOT NULL,       -- line_id and columns that identify nobody: never a customer or an invoice number (D26)
    PRIMARY KEY (run_key, rule_id)
);
