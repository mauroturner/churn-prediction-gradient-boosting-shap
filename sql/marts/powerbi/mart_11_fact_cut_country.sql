-- Customers by cut and country, with the same suppression (plan, section 19; D25, D26). Built by export.build_powerbi_marts inside its transaction, after the reference tables (ref_*).

DROP TABLE IF EXISTS star_fact_cut_country;

CREATE TABLE star_fact_cut_country AS
WITH cells AS (
    SELECT s.cut_date, COALESCE((SELECT c.country_key FROM ref_country AS c WHERE c.country_group = f.country_group), (SELECT c.country_key FROM ref_country AS c WHERE c.country_group = 'Otros')) AS country_key, COUNT(*) AS customers, SUM(s.is_contact) AS contacted,
           SUM(l.churned) AS churned
    FROM model_scores AS s
    JOIN cut_features AS f ON f.cut_date = s.cut_date AND f.customer_id = s.customer_id
    LEFT JOIN cut_labels AS l ON l.cut_date = s.cut_date AND l.customer_id = s.customer_id
    GROUP BY s.cut_date, country_key
),
flagged AS (
    SELECT *, customers < :min_cell_customers AS small FROM cells
),
-- Secondary suppression (project 03, D77): dim_cut publishes each cut's total, so a cut with exactly one hidden cell would give it back by
-- subtraction; then the smallest shown cell of that cut (fewest customers, then the lowest key) is hidden too. With two or more hidden cells
-- no single one can be recovered, and with none there is nothing to protect.
ranked AS (
    SELECT *, SUM(small) OVER (PARTITION BY cut_date) AS hidden,
           ROW_NUMBER() OVER (PARTITION BY cut_date, small ORDER BY customers, country_key) AS order_in_kind
    FROM flagged
),
decided AS (
    SELECT *, (small = 1 OR (hidden = 1 AND small = 0 AND order_in_kind = 1)) AS suppressed FROM ranked
)
SELECT CAST(strftime('%Y%m%d', cut_date) AS INTEGER) AS cut_key, country_key,
       CASE WHEN suppressed THEN NULL ELSE customers END AS customers, CASE WHEN suppressed THEN NULL ELSE contacted END AS contacted,
       CASE WHEN suppressed THEN NULL ELSE churned END AS churned, suppressed
FROM decided
ORDER BY cut_key, country_key;
