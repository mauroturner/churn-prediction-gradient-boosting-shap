-- The calibration by bin of each probabilistic method, with the small bins empty and a second one where a breakdown would hide only one (plan, section 19; D25, D26, D86). Built by export.build_powerbi_marts inside its transaction, after the reference tables (ref_*).

DROP TABLE IF EXISTS star_fact_calibration;

CREATE TABLE star_fact_calibration AS
WITH flagged AS (
    SELECT scope, method, bin, p_mean, observed, rows, seal_state, rows < :min_cell_customers AS small FROM eval_calibration
),
-- A bin of fewer rows than the minimum, an empty one included, is hidden, as the site's protect hides it (D86). Each breakdown (scope, method
-- and seal state) publishes its total rows and its churn rate (fact_method_metrics), so a breakdown with exactly one hidden bin would give it
-- back by subtraction; then its smallest shown bin (fewest rows, then the lowest bin) is hidden too (project 03, D77; the rule of
-- mart_10_fact_cut_band.sql).
ranked AS (
    SELECT *, SUM(small) OVER (PARTITION BY scope, method, seal_state) AS hidden,
           ROW_NUMBER() OVER (PARTITION BY scope, method, seal_state, small ORDER BY rows, bin) AS order_in_kind
    FROM flagged
),
decided AS (
    SELECT *, (small = 1 OR (hidden = 1 AND small = 0 AND order_in_kind = 1)) AS suppressed FROM ranked
)
SELECT scope, method AS method_key, bin AS point, CASE WHEN suppressed THEN NULL ELSE p_mean END AS p_mean,
       CASE WHEN suppressed THEN NULL ELSE observed END AS observed, CASE WHEN suppressed THEN NULL ELSE rows END AS rows, seal_state
FROM decided
ORDER BY scope, method, bin, seal_state;
