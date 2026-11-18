import pandas as pd
import pytest

from reconciliation.reconcile import reconcile, summarize

RULES = pd.DataFrame({"product_code": ["MOBILE"], "plan_type": ["Basic"], "commission_rate": [0.10]})


def _sales(ids):
    return pd.DataFrame({"sale_id": ids, "store_id": "S01", "year_month": "2025-01",
                         "product_code": "MOBILE", "plan_type": "Basic", "net_value": 100.0})


def _stmt(rows):
    return pd.DataFrame(rows, columns=["sale_id", "commission_received"]).assign(store_id="S01", year_month="2025-01")


def test_each_status_is_detected():
    sales = _sales(["a", "b", "c", "d"])
    stmt = _stmt([("a", 10.0), ("b", 6.0), ("c", 14.0), ("ghost", 5.0)])  # d is missing
    res = reconcile(stmt, sales, RULES).set_index("sale_id")
    assert res.loc["a", "status"] == "ok"
    assert res.loc["b", "status"] == "underpaid" and res.loc["b", "variance"] == -4.0
    assert res.loc["c", "status"] == "overpaid" and res.loc["c", "variance"] == 4.0
    assert res.loc["d", "status"] == "missing_in_statement" and res.loc["d", "variance"] == -10.0
    assert res.loc["ghost", "status"] == "not_in_sales_base" and res.loc["ghost", "variance"] == 5.0


def test_tolerance_absorbs_rounding():
    res = reconcile(_stmt([("a", 10.005)]), _sales(["a"]), RULES, tolerance=0.01)
    assert res.loc[0, "status"] == "ok"


def test_sorted_by_absolute_variance():
    sales = _sales(["a", "b"])
    res = reconcile(_stmt([("a", 9.0), ("b", 1.0)]), sales, RULES)
    assert list(res["sale_id"]) == ["b", "a"]


def test_summary_leakage_counts_underpaid_and_missing():
    sales = _sales(["a", "b", "d"])
    res = reconcile(_stmt([("a", 10.0), ("b", 6.0)]), sales, RULES)
    s = summarize(res)
    assert s["leakage"] == pytest.approx(14.0)   # 4 underpaid + 10 missing
    assert s["match_coverage_pct"] == pytest.approx(66.67, abs=0.01)
