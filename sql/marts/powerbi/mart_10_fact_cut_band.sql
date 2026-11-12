-- Customers by cut and band of risk, with the small cells hidden and a second one where a cut would hide only one (plan, section 19; D25, D26). Built by export.build_powerbi_marts inside its transaction, after the reference tables (ref_*).

DROP TABLE IF EXISTS star_fact_cut_band;

CREATE TABLE star_fact_cut_band AS
WITH cells AS (
    SELECT s.cut_date, (SELECT b.band_key FROM ref_band AS b WHERE s.risk >= b.p_low AND (s.risk < b.p_high OR b.band_key = 10)) AS band_key, COUNT(*) AS customers, SUM(s.is_contact) AS contacted,
           SUM(COALESCE(r.returned, 0)) AS returned, SUM(l.churned) AS churned, SUM(s.risk) AS expected_churners
    FROM model_scores AS s
    LEFT JOIN ref_customer_return AS r ON r.cut_date = s.cut_date AND r.customer_id = s.customer_id
    LEFT JOIN cut_labels AS l ON l.cut_date = s.cut_date AND l.customer_id = s.customer_id
    GROUP BY s.cut_date, band_key
),
flagged AS (
    SELECT *, customers < :min_cell_customers AS small FROM cells
),
ranked AS (
    SELECT *, SUM(small) OVER (PARTITION BY cut_date) AS hidden,
           ROW_NUMBER() OVER (PARTITION BY cut_date, small ORDER BY customers, band_key) AS order_in_kind
    FROM flagged
),
decided AS (
    SELECT *, (small = 1 OR (hidden = 1 AND small = 0 AND order_in_kind = 1)) AS suppressed FROM ranked
)
SELECT CAST(strftime('%Y%m%d', cut_date) AS INTEGER) AS cut_key, band_key,
       CASE WHEN suppressed THEN NULL ELSE customers END AS customers, CASE WHEN suppressed THEN NULL ELSE contacted END AS contacted,
       CASE WHEN suppressed THEN NULL ELSE returned END AS returned, CASE WHEN suppressed THEN NULL ELSE churned END AS churned,
       CASE WHEN suppressed THEN NULL ELSE expected_churners END AS expected_churners, suppressed
FROM decided
ORDER BY cut_key, band_key;
