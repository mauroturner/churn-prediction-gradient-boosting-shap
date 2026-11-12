-- The variants of N, M and the December cut (plan, section 19; D25, D26). Built by export.build_powerbi_marts inside its transaction, after the reference tables (ref_*).

DROP TABLE IF EXISTS star_fact_sensitivity;

CREATE TABLE star_fact_sensitivity AS
WITH methods (method_key) AS (VALUES ('model'), ('b2_rfm'), ('b_star'))
SELECT v.variant, rv.variant_es,
       CAST((SELECT value FROM eval_variants AS a WHERE a.variant = v.variant AND a.seal_state = v.seal_state AND a.method = 'all' AND a.metric = 'n') AS INTEGER) AS n,
       CAST((SELECT value FROM eval_variants AS a WHERE a.variant = v.variant AND a.seal_state = v.seal_state AND a.method = 'all' AND a.metric = 'm') AS INTEGER) AS m,
       x.method_key,
       (SELECT value FROM eval_variants AS a WHERE a.variant = v.variant AND a.seal_state = v.seal_state AND a.method = x.method_key AND a.metric = 'auc') AS auc,
       (SELECT value FROM eval_variants AS a WHERE a.variant = v.variant AND a.seal_state = v.seal_state AND a.method = 'all' AND a.metric = 'churn_rate') AS churn_rate,
       CAST((SELECT value FROM eval_variants AS a WHERE a.variant = v.variant AND a.seal_state = v.seal_state AND a.method = 'all' AND a.metric = 'rows') AS INTEGER) AS rows,
       (SELECT value FROM eval_variants AS a WHERE a.variant = v.variant AND a.seal_state = v.seal_state AND a.method = x.method_key AND a.metric = 'diff_ci_low') AS diff_ci_low,
       (SELECT value FROM eval_variants AS a WHERE a.variant = v.variant AND a.seal_state = v.seal_state AND a.method = x.method_key AND a.metric = 'diff_ci_high') AS diff_ci_high,
       v.seal_state
FROM (SELECT DISTINCT variant, seal_state FROM eval_variants) AS v
CROSS JOIN methods AS x
JOIN ref_variant AS rv ON rv.variant = v.variant
ORDER BY rv.sort_order, x.method_key, v.seal_state;
