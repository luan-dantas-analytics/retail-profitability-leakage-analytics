-- KPI logic lives here, once, so Power BI, the API and the dashboard all read the
-- same definitions. Each fact is aggregated to store x month BEFORE joining, which
-- avoids the row duplication that inflates numbers when facts of different grain
-- are joined directly.

DROP VIEW IF EXISTS vw_store_margin;
CREATE VIEW vw_store_margin AS
WITH rev AS (
    SELECT store_id, year_month, SUM(commission_received) AS revenue
    FROM fact_statement GROUP BY store_id, year_month),
cost AS (
    SELECT store_id, year_month, SUM(amount) AS operating_cost
    FROM fact_cost GROUP BY store_id, year_month),
m AS (
    SELECT c.store_id, c.year_month,
           COALESCE(r.revenue, 0)                          AS revenue,
           c.operating_cost,
           COALESCE(r.revenue, 0) - c.operating_cost       AS operating_profit
    FROM cost c LEFT JOIN rev r USING (store_id, year_month))
SELECT s.store_name, m.store_id, m.year_month,
       ROUND(m.revenue, 2)          AS revenue,
       ROUND(m.operating_cost, 2)   AS operating_cost,
       ROUND(m.operating_profit, 2) AS operating_profit,
       ROUND(100.0 * m.operating_profit / NULLIF(m.revenue, 0), 1) AS margin_pct,
       -- Bands are illustrative thresholds, agreed with the client in discovery.
       CASE WHEN m.operating_profit >= 0.15 * m.revenue THEN 'Healthy'
            WHEN m.operating_profit >= 0.05 * m.revenue THEN 'Attention'
            ELSE 'Critical' END AS band
FROM m JOIN dim_store s USING (store_id);

DROP VIEW IF EXISTS vw_leakage_by_store_month;
CREATE VIEW vw_leakage_by_store_month AS
SELECT store_id, year_month,
       ROUND(SUM(expected), 2) AS expected_commission,
       ROUND(SUM(received), 2) AS received_commission,
       ROUND(-SUM(CASE WHEN status = 'underpaid'            THEN variance ELSE 0 END), 2) AS underpaid_amount,
       ROUND(-SUM(CASE WHEN status = 'missing_in_statement' THEN variance ELSE 0 END), 2) AS missing_amount,
       ROUND( SUM(CASE WHEN status = 'overpaid'             THEN variance ELSE 0 END), 2) AS overpaid_amount,
       ROUND( SUM(CASE WHEN status = 'not_in_sales_base'    THEN variance ELSE 0 END), 2) AS unexplained_amount,
       COUNT(*) AS lines,
       SUM(CASE WHEN status = 'ok' THEN 1 ELSE 0 END) AS lines_ok
FROM recon_result
GROUP BY store_id, year_month;

DROP VIEW IF EXISTS vw_store_summary;
CREATE VIEW vw_store_summary AS
WITH f AS (
    SELECT store_id, SUM(revenue) AS revenue, SUM(operating_cost) AS operating_cost,
           SUM(operating_profit) AS operating_profit
    FROM vw_store_margin GROUP BY store_id),
l AS (
    SELECT store_id, SUM(underpaid_amount + missing_amount) AS leakage,
           SUM(overpaid_amount) AS overpaid, SUM(expected_commission) AS expected
    FROM vw_leakage_by_store_month GROUP BY store_id)
SELECT s.store_id, s.store_name,
       ROUND(f.revenue, 2) AS revenue, ROUND(f.operating_cost, 2) AS operating_cost,
       ROUND(f.operating_profit, 2) AS operating_profit,
       ROUND(100.0 * f.operating_profit / NULLIF(f.revenue, 0), 1) AS margin_pct,
       ROUND(l.leakage, 2) AS leakage, ROUND(l.overpaid, 2) AS overpaid,
       ROUND(100.0 * l.leakage / NULLIF(l.expected, 0), 2) AS leakage_pct
FROM dim_store s JOIN f USING (store_id) JOIN l USING (store_id);
