-- The reasons by cut: how many customers and contacts have each among their reasons, empty below the minimum (plan, section 19; D25, D26). Built by export.build_powerbi_marts inside its transaction, after the reference tables (ref_*).

DROP TABLE IF EXISTS star_fact_reason_summary;

CREATE TABLE star_fact_reason_summary AS
WITH cells AS (
    SELECT r.cut_date, r.feature AS reason_key, COUNT(*) AS customers_top3, SUM(s.is_contact) AS contacted_top3, AVG(r.shap_value) AS mean_shap
    FROM score_reasons AS r
    JOIN model_scores AS s ON s.cut_date = r.cut_date AND s.customer_id = r.customer_id
    GROUP BY r.cut_date, r.feature
)
SELECT CAST(strftime('%Y%m%d', cut_date) AS INTEGER) AS cut_key, reason_key,
       CASE WHEN customers_top3 < :min_cell_customers THEN NULL ELSE customers_top3 END AS customers_top3,
       CASE WHEN customers_top3 < :min_cell_customers THEN NULL ELSE contacted_top3 END AS contacted_top3,
       CASE WHEN customers_top3 < :min_cell_customers THEN NULL ELSE mean_shap END AS mean_shap
FROM cells
ORDER BY cut_key, reason_key;
