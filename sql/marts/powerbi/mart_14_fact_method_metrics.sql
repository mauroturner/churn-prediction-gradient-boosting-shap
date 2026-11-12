-- The metrics of each method on V2 and on the test (plan, section 19; D25, D26). Built by export.build_powerbi_marts inside its transaction, after the reference tables (ref_*).

DROP TABLE IF EXISTS star_fact_method_metrics;

CREATE TABLE star_fact_method_metrics AS
SELECT scope, method AS method_key,
       MAX(CASE metric WHEN 'auc' THEN value END) AS auc, MAX(CASE metric WHEN 'pr_auc' THEN value END) AS pr_auc,
       MAX(CASE metric WHEN 'brier' THEN value END) AS brier, MAX(CASE metric WHEN 'ece' THEN value END) AS ece,
       MAX(CASE metric WHEN 'threshold' THEN value END) AS threshold, MAX(CASE metric WHEN 'contact_share' THEN value END) AS contact_share,
       MAX(CASE metric WHEN 'precision' THEN value END) AS precision, MAX(CASE metric WHEN 'recall' THEN value END) AS recall,
       MAX(CASE metric WHEN 'capture_10' THEN value END) AS capture_10, MAX(CASE metric WHEN 'lift_10' THEN value END) AS lift_10,
       MAX(CASE metric WHEN 'capture_20' THEN value END) AS capture_20, MAX(CASE metric WHEN 'lift_20' THEN value END) AS lift_20,
       MAX(CASE metric WHEN 'nb_total' THEN value END) AS nb_total, MAX(CASE metric WHEN 'nb_per_1000' THEN value END) AS nb_per_1000, seal_state
FROM eval_metrics
WHERE method IN (SELECT method_key FROM ref_method)
GROUP BY scope, method, seal_state
ORDER BY scope, method, seal_state;
