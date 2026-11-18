"""Generate a SYNTHETIC dataset for the Profitability & Revenue Leakage case.

Nothing here is real client data. The shapes (stores, plans, commission rules, payment
discrepancies, messy source files) are modeled on how indirect retail partner
networks work, so the pipeline has realistic problems to solve.

Business model of the simulated network
---------------------------------------
Five stores sell mobile, broadband, TV and devices on behalf of an operator.
The operator pays the network a commission per sale (its REVENUE) and publishes a
monthly commission statement. The network pays payroll, rent and other costs.
"""
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 42
RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"
MONTHS = [f"2025-{m:02d}" for m in range(1, 13)]
SEASON = dict(zip(MONTHS, [0.96, 0.95, 0.98, 0.99, 1.01, 0.99, 1.00, 1.00, 1.01, 1.03, 1.05, 1.08]))

# store_id, name, city, lines/month (base), employees, salary, rent, other, monthly trend, missing-line rate
STORES = [
    ("S01", "North Plaza", "North District", 720, 17, 2350, 8200, 3600, 0.004, 0.018),
    ("S02", "Harbor Mall", "Harbor", 760, 18, 2350, 9400, 4100, 0.000, 0.020),
    ("S03", "Central Square", "Downtown", 960, 18, 2400, 9800, 4300, -0.025, 0.040),
    ("S04", "Airport Kiosk", "Airport", 600, 14, 2500, 11800, 4600, -0.002, 0.045),
    ("S05", "Riverside", "Riverside", 760, 17, 2300, 7600, 3300, 0.006, 0.012),
]

# product -> (plan list, plan probabilities, contract values)
PRODUCTS = {
    "MOBILE": (["Basic", "Plus", "Premium"], [0.45, 0.35, 0.20], [360, 540, 780]),
    "BROADBAND": (["Basic", "Plus", "Premium"], [0.40, 0.40, 0.20], [600, 840, 1080]),
    "TV": (["Basic", "Plus"], [0.60, 0.40], [420, 600]),
    "DEVICE": (["Standard"], [1.0], [None]),
}
PRODUCT_MIX = {"MOBILE": 0.45, "BROADBAND": 0.25, "TV": 0.12, "DEVICE": 0.18}
RATES = {
    ("MOBILE", "Basic"): 0.14, ("MOBILE", "Plus"): 0.15, ("MOBILE", "Premium"): 0.16,
    ("BROADBAND", "Basic"): 0.16, ("BROADBAND", "Plus"): 0.17, ("BROADBAND", "Premium"): 0.18,
    ("TV", "Basic"): 0.12, ("TV", "Plus"): 0.13,
    ("DEVICE", "Standard"): 0.04,
}


def build_sales(rng):
    rows = []
    for sid, _n, _c, base, emp, *_rest in STORES:
        trend = next(s[8] for s in STORES if s[0] == sid)
        for i, ym in enumerate(MONTHS):
            n = int(base * SEASON[ym] * (1 + trend * i) * rng.normal(1.0, 0.03))
            prods = rng.choice(list(PRODUCT_MIX), size=n, p=list(PRODUCT_MIX.values()))
            for k, prod in enumerate(prods):
                plans, probs, values = PRODUCTS[prod]
                j = rng.choice(len(plans), p=probs)
                value = rng.uniform(400, 1800) if prod == "DEVICE" else values[j] * rng.uniform(0.97, 1.03)
                rows.append((f"{sid}-{ym}-{k:05d}", f"{ym}-{rng.integers(1, 29):02d}", sid,
                             f"{sid}-E{rng.integers(1, emp + 1):02d}", prod, plans[j], round(float(value), 2)))
    return pd.DataFrame(rows, columns=["sale_id", "sale_date", "store_id", "employee_id",
                                       "product_code", "plan_type", "net_value"])


def build_statement(sales, rng):
    """The operator's statement: mostly correct, with realistic payment errors."""
    rules = pd.DataFrame([(p, t, r) for (p, t), r in RATES.items()],
                         columns=["product_code", "plan_type", "commission_rate"])
    s = sales.merge(rules, on=["product_code", "plan_type"])
    s["commission_received"] = (s["net_value"] * s["commission_rate"]).round(2)
    s["year_month"] = s["sale_date"].str[:7]
    miss = {st[0]: st[9] for st in STORES}
    u = rng.random(len(s))
    missing = u < s["store_id"].map(miss)
    under = (u >= 0.5) & (u < 0.5 + 0.018)
    over = (u >= 0.7) & (u < 0.7 + 0.008)
    s.loc[under, "commission_received"] = (s.loc[under, "commission_received"] * rng.uniform(0.50, 0.85, under.sum())).round(2)
    s.loc[over, "commission_received"] = (s.loc[over, "commission_received"] * rng.uniform(1.15, 1.50, over.sum())).round(2)
    s = s[~missing][["sale_id", "store_id", "year_month", "commission_received"]].reset_index(drop=True)

    n_ghost = int(len(s) * 0.004)  # payments that match no sale
    ghosts = pd.DataFrame({
        "sale_id": [f"EXT-{i:05d}" for i in range(n_ghost)],
        "store_id": rng.choice([x[0] for x in STORES], n_ghost),
        "year_month": rng.choice(MONTHS, n_ghost),
        "commission_received": rng.uniform(20, 150, n_ghost).round(2),
    })
    out = pd.concat([s, ghosts], ignore_index=True).sample(frac=1, random_state=SEED).reset_index(drop=True)
    out.insert(0, "statement_id", [f"ST-{i:06d}" for i in range(len(out))])
    return out, rules


def build_costs(rng):
    rows = []
    for sid, _n, _c, _b, emp, sal, rent, other, *_ in STORES:
        for ym in MONTHS:
            rows += [(sid, ym, "PAYROLL", round(emp * sal * rng.normal(1.0, 0.015), 2)),
                     (sid, ym, "RENT", float(rent)),
                     (sid, ym, "OTHER", round(other * rng.normal(1.0, 0.06), 2))]
    return pd.DataFrame(rows, columns=["store_id", "year_month", "cost_type", "amount"])


def make_messy(sales, rng):
    """Degrade the sales export the way real exports arrive."""
    d = sales.copy()
    n = len(d)
    iso = rng.random(n) < 0.04  # some rows exported as dd/mm/yyyy
    d.loc[iso, "sale_date"] = pd.to_datetime(d.loc[iso, "sale_date"]).dt.strftime("%d/%m/%Y")
    messy = rng.random(n) < 0.03
    d.loc[messy, "store_id"] = d.loc[messy, "store_id"].str.lower() + " "
    d.loc[rng.random(n) < 0.002, "plan_type"] = None
    d.loc[rng.random(n) < 0.001, "net_value"] = -d["net_value"]
    d.loc[rng.random(n) < 0.0015, "product_code"] = "UNKNOWN"
    dup = d.sample(frac=0.003, random_state=SEED)  # duplicated lines
    return pd.concat([d, dup], ignore_index=True)


def main():
    rng = np.random.default_rng(SEED)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    sales = build_sales(rng)
    statement, rules = build_statement(sales, rng)
    costs = build_costs(rng)
    stores = pd.DataFrame([(s[0], s[1], s[2]) for s in STORES], columns=["store_id", "store_name", "city"])
    make_messy(sales, rng).to_csv(RAW_DIR / "sales.csv", index=False)
    statement.to_csv(RAW_DIR / "commission_statement.csv", index=False)
    costs.to_csv(RAW_DIR / "costs.csv", index=False)
    rules.to_csv(RAW_DIR / "commission_rules.csv", index=False)
    stores.to_csv(RAW_DIR / "stores.csv", index=False)
    print(f"sales={len(sales):,} statement={len(statement):,} costs={len(costs)} -> {RAW_DIR}")


if __name__ == "__main__":
    main()
