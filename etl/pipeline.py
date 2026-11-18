"""ETL pipeline: raw files -> validated tables -> SQL warehouse -> KPI exports.

Run:  python -m etl.pipeline
Stages: ingest -> clean and validate -> load -> reconcile -> KPI views -> export.
Every rejected row goes to a quarantine table with its reason.
"""
import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from reconciliation.reconcile import reconcile, summarize

ROOT = Path(__file__).resolve().parents[1]
RAW, DB, SQL, EXPORTS = ROOT / "data" / "raw", ROOT / "data" / "warehouse.db", ROOT / "sql", ROOT / "exports"


def _quarantine(frame, source, reason):
    if frame.empty:
        return pd.DataFrame(columns=["source", "reason", "row_json"])
    return pd.DataFrame({"source": source, "reason": reason,
                         "row_json": frame.to_json(orient="records", lines=True).splitlines()})


def clean_sales(raw, stores, rules):
    """Standardize and validate the sales export. Returns (clean, quarantine)."""
    d = raw.copy()
    d["store_id"] = d["store_id"].str.strip().str.upper()
    d["product_code"] = d["product_code"].str.strip().str.upper()
    d["plan_type"] = d["plan_type"].str.strip().str.title()
    iso = pd.to_datetime(d["sale_date"], format="%Y-%m-%d", errors="coerce")
    d["sale_date"] = iso.fillna(pd.to_datetime(d["sale_date"], format="%d/%m/%Y", errors="coerce"))

    valid_pairs = set(zip(rules["product_code"], rules["plan_type"]))
    pair_ok = pd.Series([(p, t) in valid_pairs for p, t in zip(d["product_code"], d["plan_type"])], index=d.index)
    checks = [  # (rejected-mask, reason) evaluated in this order; first match wins
        (d.duplicated("sale_id", keep="first"), "duplicate_sale_id"),
        (d["sale_date"].isna(), "invalid_date"),
        (d["plan_type"].isna(), "missing_plan_type"),
        (~d["store_id"].isin(stores["store_id"]), "invalid_store"),
        (d["net_value"] <= 0, "non_positive_value"),
        (~pair_ok, "unknown_product_or_plan"),
    ]
    reject, reasons = pd.Series(False, index=d.index), pd.Series("", index=d.index)
    for mask, reason in checks:
        new = mask & ~reject
        reasons[new] = reason
        reject |= mask
    d["year_month"] = d["sale_date"].dt.strftime("%Y-%m")
    d["sale_date"] = d["sale_date"].dt.strftime("%Y-%m-%d")
    q = pd.concat([_quarantine(raw[reject & (reasons == r)], "sales", r) for r in reasons[reject].unique()]) \
        if reject.any() else pd.DataFrame(columns=["source", "reason", "row_json"])
    return d[~reject].copy(), q


def clean_statement(raw, stores):
    d = raw.copy()
    d["sale_id"] = d["sale_id"].str.strip()
    d["store_id"] = d["store_id"].str.strip().str.upper()
    bad = d.duplicated("statement_id") | ~d["store_id"].isin(stores["store_id"]) | d["commission_received"].isna()
    return d[~bad].copy(), _quarantine(raw[bad], "statement", "invalid_statement_line")


def main():
    t0 = time.perf_counter()
    stores = pd.read_csv(RAW / "stores.csv")
    rules = pd.read_csv(RAW / "commission_rules.csv")
    sales_raw = pd.read_csv(RAW / "sales.csv")
    stmt_raw = pd.read_csv(RAW / "commission_statement.csv")
    costs = pd.read_csv(RAW / "costs.csv")

    sales, q_sales = clean_sales(sales_raw, stores, rules)
    stmt, q_stmt = clean_statement(stmt_raw, stores)
    quarantine = pd.concat([q_sales, q_stmt], ignore_index=True)

    result = reconcile(stmt, sales, rules)
    summary = summarize(result)

    DB.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB) as con:
        con.executescript((SQL / "schema.sql").read_text())
        stores.to_sql("dim_store", con, if_exists="append", index=False)
        rules.to_sql("commission_rule", con, if_exists="append", index=False)
        sales[["sale_id", "sale_date", "year_month", "store_id", "employee_id", "product_code",
               "plan_type", "net_value"]].to_sql("fact_sales", con, if_exists="append", index=False)
        stmt.to_sql("fact_statement", con, if_exists="append", index=False)
        costs.to_sql("fact_cost", con, if_exists="append", index=False)
        result.to_sql("recon_result", con, if_exists="append", index=False)
        quarantine.to_sql("quarantine", con, if_exists="append", index=False)
        con.executescript((SQL / "views.sql").read_text())

        rows_in = len(sales_raw) + len(stmt_raw)
        loaded = len(sales) + len(stmt)
        quality = round(100.0 * loaded / rows_in, 2)
        seconds = round(time.perf_counter() - t0, 2)
        con.execute("INSERT INTO pipeline_log VALUES (?,?,?,?,?,?)",
                    (datetime.now(timezone.utc).isoformat(timespec="seconds"), seconds, rows_in, loaded,
                     len(quarantine), quality))

        EXPORTS.mkdir(exist_ok=True)
        tables = {
            "store_month_margin": "SELECT * FROM vw_store_margin ORDER BY year_month, store_id",
            "store_summary": "SELECT * FROM vw_store_summary ORDER BY margin_pct DESC",
            "leakage_by_store_month": "SELECT * FROM vw_leakage_by_store_month ORDER BY year_month, store_id",
            "top_discrepancies": ("SELECT r.*, s.store_name FROM recon_result r JOIN dim_store s USING (store_id) "
                                  "WHERE status <> 'ok' ORDER BY ABS(variance) DESC LIMIT 25"),
            "quarantine_summary": "SELECT source, reason, COUNT(*) AS rows FROM quarantine GROUP BY source, reason ORDER BY rows DESC",
        }
        frames = {name: pd.read_sql(q, con) for name, q in tables.items()}
    for name, f in frames.items():
        f.to_csv(EXPORTS / f"{name}.csv", index=False)
    result.to_csv(EXPORTS / "reconciliation_lines.csv", index=False)

    payload = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "data_quality_score": quality, "pipeline_seconds": seconds,
               "rows_in": rows_in, "rows_quarantined": int(len(quarantine)),
               "reconciliation": summary,
               **{k: json.loads(v.to_json(orient="records")) for k, v in frames.items()}}
    (EXPORTS / "kpis.json").write_text(json.dumps(payload, indent=2))
    print(f"loaded {loaded:,} of {rows_in:,} rows ({quality}% pass) in {seconds}s | "
          f"leakage={summary['leakage']:,.2f} overpaid={summary['overpaid']:,.2f} "
          f"coverage={summary['match_coverage_pct']}%")


if __name__ == "__main__":
    main()
