-- The reasons by cut: how many customers and contacts have each among their reasons, empty below the minimum and a second one where a cut would hide only one (plan, section 19; D25, D26, D86). Built by export.build_powerbi_marts inside its transaction, after the reference tables (ref_*).

DROP TABLE IF EXISTS star_fact_reason_summary;

CREATE TABLE star_fact_reason_summary AS
WITH cells AS (
    SELECT r.cut_date, r.feature AS reason_key, COUNT(*) AS customers_top3, SUM(s.is_contact) AS contacted_top3, AVG(r.shap_value) AS mean_shap
    FROM score_reasons AS r
    JOIN model_scores AS s ON s.cut_date = r.cut_date AND s.customer_id = r.customer_id
    GROUP BY r.cut_date, r.feature
),
-- A reason held by fewer customers than the minimum, or by fewer contacted customers (the site's «motivos entre los contactados» hides those,
-- none or a few), is hidden whole (D86). Every customer has the same number of reasons, so the sums of a cut are published totals (its scored
-- and contacted customers): a cut with exactly one hidden reason would give it back by subtraction, so its smallest shown reason (by the
-- smaller of its two counts, then the lowest key) is hidden too (project 03, D77; the rule of mart_10_fact_cut_band.sql).
flagged AS (
    SELECT *, MIN(customers_top3, contacted_top3) AS cell_count, MIN(customers_top3, contacted_top3) < :min_cell_customers AS small FROM cells
),
ranked AS (
    SELECT *, SUM(small) OVER (PARTITION BY cut_date) AS hidden,
           ROW_NUMBER() OVER (PARTITION BY cut_date, small ORDER BY cell_count, reason_key) AS order_in_kind
    FROM flagged
),
decided AS (
    SELECT *, (small = 1 OR (hidden = 1 AND small = 0 AND order_in_kind = 1)) AS suppressed FROM ranked
)
SELECT CAST(strftime('%Y%m%d', cut_date) AS INTEGER) AS cut_key, reason_key,
       CASE WHEN suppressed THEN NULL ELSE customers_top3 END AS customers_top3,
       CASE WHEN suppressed THEN NULL ELSE contacted_top3 END AS contacted_top3,
       CASE WHEN suppressed THEN NULL ELSE mean_shap END AS mean_shap
FROM decided
ORDER BY cut_key, reason_key;
