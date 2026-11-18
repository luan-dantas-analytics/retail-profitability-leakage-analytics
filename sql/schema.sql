-- Star schema for the Profitability & Revenue Leakage platform.
-- Written for SQLite so the demo runs anywhere; the same DDL ports to PostgreSQL
-- (swap REAL for NUMERIC(12,2) and add proper DATE types).

DROP TABLE IF EXISTS fact_sales;
DROP TABLE IF EXISTS fact_statement;
DROP TABLE IF EXISTS fact_cost;
DROP TABLE IF EXISTS recon_result;
DROP TABLE IF EXISTS commission_rule;
DROP TABLE IF EXISTS dim_store;
DROP TABLE IF EXISTS quarantine;
DROP TABLE IF EXISTS pipeline_log;

CREATE TABLE dim_store (
    store_id   TEXT PRIMARY KEY,
    store_name TEXT NOT NULL,
    city       TEXT
);

CREATE TABLE commission_rule (
    product_code    TEXT NOT NULL,
    plan_type       TEXT NOT NULL,
    commission_rate REAL NOT NULL CHECK (commission_rate >= 0),
    PRIMARY KEY (product_code, plan_type)
);

CREATE TABLE fact_sales (
    sale_id      TEXT PRIMARY KEY,
    sale_date    TEXT NOT NULL,
    year_month   TEXT NOT NULL,
    store_id     TEXT NOT NULL REFERENCES dim_store(store_id),
    employee_id  TEXT,
    product_code TEXT NOT NULL,
    plan_type    TEXT NOT NULL,
    net_value    REAL NOT NULL CHECK (net_value > 0)
);

-- What the operator actually paid (the partner's revenue).
CREATE TABLE fact_statement (
    statement_id        TEXT PRIMARY KEY,
    sale_id             TEXT NOT NULL,
    store_id            TEXT NOT NULL REFERENCES dim_store(store_id),
    year_month          TEXT NOT NULL,
    commission_received REAL NOT NULL
);

CREATE TABLE fact_cost (
    store_id   TEXT NOT NULL REFERENCES dim_store(store_id),
    year_month TEXT NOT NULL,
    cost_type  TEXT NOT NULL,
    amount     REAL NOT NULL,
    PRIMARY KEY (store_id, year_month, cost_type)
);

-- Output of the reconciliation engine: one row per sale or statement line.
CREATE TABLE recon_result (
    sale_id    TEXT,
    store_id   TEXT,
    year_month TEXT,
    expected   REAL,
    received   REAL,
    variance   REAL,
    status     TEXT
);
CREATE INDEX ix_recon_store_month ON recon_result (store_id, year_month);

-- Rows rejected by validation, with the reason, so nothing disappears silently.
CREATE TABLE quarantine (
    source TEXT,
    reason TEXT,
    row_json TEXT
);

CREATE TABLE pipeline_log (
    run_at          TEXT,
    seconds         REAL,
    rows_in         INTEGER,
    rows_loaded     INTEGER,
    rows_quarantined INTEGER,
    quality_score   REAL
);
