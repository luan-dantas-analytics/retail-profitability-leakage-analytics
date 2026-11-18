"""Commission reconciliation engine.

Compares what the operator PAID (statement) with what the plan rules say it SHOULD
have paid (sales x commission rules), line by line, and labels every line.
"""
import numpy as np
import pandas as pd

TOLERANCE = 0.01  # currency units
STATUSES = ["ok", "underpaid", "overpaid", "missing_in_statement", "not_in_sales_base"]


def expected_commission(sales: pd.DataFrame, rules: pd.DataFrame) -> pd.DataFrame:
    """Expected commission per sale = net value x rate for its product and plan."""
    exp = sales.merge(rules, on=["product_code", "plan_type"], how="left")
    exp["expected_commission"] = (exp["net_value"] * exp["commission_rate"]).round(2)
    return exp[["sale_id", "store_id", "year_month", "expected_commission"]]


def reconcile(statement: pd.DataFrame, sales: pd.DataFrame, rules: pd.DataFrame,
              tolerance: float = TOLERANCE) -> pd.DataFrame:
    """Return one row per sale or statement line with expected, received, variance, status.

    Assumes sale_id is unique in both inputs (the ETL step guarantees it).
    """
    expected = expected_commission(sales, rules)
    df = statement[["sale_id", "store_id", "year_month", "commission_received"]].merge(
        expected, on="sale_id", how="outer", suffixes=("_stmt", "_sales"), indicator=True)
    df["store_id"] = df["store_id_sales"].combine_first(df["store_id_stmt"])
    df["year_month"] = df["year_month_sales"].combine_first(df["year_month_stmt"])
    df["received"] = df["commission_received"].fillna(0.0)
    df["expected"] = df["expected_commission"].fillna(0.0)
    df["variance"] = (df["received"] - df["expected"]).round(2)

    df["status"] = np.select(
        [
            df["_merge"] == "right_only",       # sold, but absent from the statement
            df["_merge"] == "left_only",        # paid, but absent from the sales base
            df["variance"].abs() <= tolerance,  # matched and correct
            df["variance"] < 0,                 # matched, paid less than expected
        ],
        ["missing_in_statement", "not_in_sales_base", "ok", "underpaid"],
        default="overpaid",
    )
    cols = ["sale_id", "store_id", "year_month", "expected", "received", "variance", "status"]
    return df[cols].sort_values("variance", key=lambda s: s.abs(), ascending=False).reset_index(drop=True)


def summarize(result: pd.DataFrame) -> dict:
    """Headline numbers for the executive view."""
    by = result.groupby("status")["variance"].agg(["count", "sum"])
    matched = (~result["status"].isin(["missing_in_statement", "not_in_sales_base"])).mean()
    leakage = -(by.loc[[s for s in ("underpaid", "missing_in_statement") if s in by.index], "sum"].sum())
    return {
        "lines": int(len(result)),
        "match_coverage_pct": round(float(matched) * 100, 2),
        "leakage": round(float(leakage), 2),
        "overpaid": round(float(by["sum"].get("overpaid", 0.0)), 2),
        "unexplained_payments": round(float(by["sum"].get("not_in_sales_base", 0.0)), 2),
        "by_status": {k: {"lines": int(v["count"]), "amount": round(float(v["sum"]), 2)} for k, v in by.iterrows()},
    }
