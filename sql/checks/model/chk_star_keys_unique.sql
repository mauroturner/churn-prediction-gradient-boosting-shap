-- Every key of the star model is unique and never empty (AC27): one row per table and key that breaks it.
SELECT 'dim_date' AS star_table, COUNT(*) AS copies FROM star_dim_date GROUP BY date_key HAVING COUNT(*) > 1 OR SUM(date_key IS NULL) > 0
UNION ALL
SELECT 'dim_cut' AS star_table, COUNT(*) AS copies FROM star_dim_cut GROUP BY cut_key HAVING COUNT(*) > 1 OR SUM(cut_key IS NULL) > 0
UNION ALL
SELECT 'dim_country' AS star_table, COUNT(*) AS copies FROM star_dim_country GROUP BY country_key HAVING COUNT(*) > 1 OR SUM(country_key IS NULL) > 0
UNION ALL
SELECT 'dim_risk_band' AS star_table, COUNT(*) AS copies FROM star_dim_risk_band GROUP BY band_key HAVING COUNT(*) > 1 OR SUM(band_key IS NULL) > 0
UNION ALL
SELECT 'dim_reason' AS star_table, COUNT(*) AS copies FROM star_dim_reason GROUP BY reason_key HAVING COUNT(*) > 1 OR SUM(reason_key IS NULL) > 0
UNION ALL
SELECT 'dim_method' AS star_table, COUNT(*) AS copies FROM star_dim_method GROUP BY method_key HAVING COUNT(*) > 1 OR SUM(method_key IS NULL) > 0
UNION ALL
SELECT 'dim_model' AS star_table, COUNT(*) AS copies FROM star_dim_model GROUP BY model_version HAVING COUNT(*) > 1 OR SUM(model_version IS NULL) > 0
UNION ALL
SELECT 'dim_pipeline_run' AS star_table, COUNT(*) AS copies FROM star_dim_pipeline_run GROUP BY run_key HAVING COUNT(*) > 1 OR SUM(run_key IS NULL) > 0
UNION ALL
SELECT 'dim_as_of' AS star_table, COUNT(*) AS copies FROM star_dim_as_of GROUP BY as_of_key HAVING COUNT(*) > 1 OR SUM(as_of_key IS NULL) > 0
UNION ALL
SELECT 'fact_cut_band' AS star_table, COUNT(*) AS copies FROM star_fact_cut_band GROUP BY cut_key, band_key HAVING COUNT(*) > 1 OR SUM(cut_key IS NULL OR band_key IS NULL) > 0
UNION ALL
SELECT 'fact_cut_country' AS star_table, COUNT(*) AS copies FROM star_fact_cut_country GROUP BY cut_key, country_key HAVING COUNT(*) > 1 OR SUM(cut_key IS NULL OR country_key IS NULL) > 0
UNION ALL
SELECT 'fact_reason_summary' AS star_table, COUNT(*) AS copies FROM star_fact_reason_summary GROUP BY cut_key, reason_key HAVING COUNT(*) > 1 OR SUM(cut_key IS NULL OR reason_key IS NULL) > 0
UNION ALL
SELECT 'fact_tracking' AS star_table, COUNT(*) AS copies FROM star_fact_tracking GROUP BY as_of_key, cut_key HAVING COUNT(*) > 1 OR SUM(as_of_key IS NULL OR cut_key IS NULL) > 0
UNION ALL
SELECT 'fact_method_metrics' AS star_table, COUNT(*) AS copies FROM star_fact_method_metrics GROUP BY scope, method_key, seal_state HAVING COUNT(*) > 1 OR SUM(scope IS NULL OR method_key IS NULL OR seal_state IS NULL) > 0
UNION ALL
SELECT 'fact_evaluation_summary' AS star_table, COUNT(*) AS copies FROM star_fact_evaluation_summary GROUP BY criterion_id, seal_state HAVING COUNT(*) > 1 OR SUM(criterion_id IS NULL OR seal_state IS NULL) > 0
UNION ALL
SELECT 'fact_gain_curve' AS star_table, COUNT(*) AS copies FROM star_fact_gain_curve GROUP BY scope, method_key, point, seal_state HAVING COUNT(*) > 1 OR SUM(scope IS NULL OR method_key IS NULL OR point IS NULL OR seal_state IS NULL) > 0
UNION ALL
SELECT 'fact_roc' AS star_table, COUNT(*) AS copies FROM star_fact_roc GROUP BY scope, method_key, point, seal_state HAVING COUNT(*) > 1 OR SUM(scope IS NULL OR method_key IS NULL OR point IS NULL OR seal_state IS NULL) > 0
UNION ALL
SELECT 'fact_calibration' AS star_table, COUNT(*) AS copies FROM star_fact_calibration GROUP BY scope, method_key, point, seal_state HAVING COUNT(*) > 1 OR SUM(scope IS NULL OR method_key IS NULL OR point IS NULL OR seal_state IS NULL) > 0
UNION ALL
SELECT 'fact_cost_sensitivity' AS star_table, COUNT(*) AS copies FROM star_fact_cost_sensitivity GROUP BY scope, break_even, method_key, seal_state HAVING COUNT(*) > 1 OR SUM(scope IS NULL OR break_even IS NULL OR method_key IS NULL OR seal_state IS NULL) > 0
UNION ALL
SELECT 'fact_sensitivity' AS star_table, COUNT(*) AS copies FROM star_fact_sensitivity GROUP BY variant, method_key, seal_state HAVING COUNT(*) > 1 OR SUM(variant IS NULL OR method_key IS NULL OR seal_state IS NULL) > 0
UNION ALL
SELECT 'fact_label_definition' AS star_table, COUNT(*) AS copies FROM star_fact_label_definition GROUP BY n, m HAVING COUNT(*) > 1 OR SUM(n IS NULL OR m IS NULL) > 0
UNION ALL
SELECT 'fact_silence_return' AS star_table, COUNT(*) AS copies FROM star_fact_silence_return GROUP BY n HAVING COUNT(*) > 1 OR SUM(n IS NULL) > 0
UNION ALL
SELECT 'fact_importance' AS star_table, COUNT(*) AS copies FROM star_fact_importance GROUP BY scope, reason_key, seal_state HAVING COUNT(*) > 1 OR SUM(scope IS NULL OR reason_key IS NULL OR seal_state IS NULL) > 0
UNION ALL
SELECT 'fact_selection' AS star_table, COUNT(*) AS copies FROM star_fact_selection GROUP BY feature_set, learning_rate, max_leaf_nodes, min_samples_leaf HAVING COUNT(*) > 1 OR SUM(feature_set IS NULL OR learning_rate IS NULL OR max_leaf_nodes IS NULL OR min_samples_leaf IS NULL) > 0
UNION ALL
SELECT 'fact_leakage' AS star_table, COUNT(*) AS copies FROM star_fact_leakage GROUP BY variable HAVING COUNT(*) > 1 OR SUM(variable IS NULL) > 0
UNION ALL
SELECT 'fact_validation' AS star_table, COUNT(*) AS copies FROM star_fact_validation GROUP BY run_key, rule_id HAVING COUNT(*) > 1 OR SUM(run_key IS NULL OR rule_id IS NULL) > 0
UNION ALL
SELECT 'fact_customer_cut' AS star_table, COUNT(*) AS copies FROM star_fact_customer_cut GROUP BY customer_id, cut_key HAVING COUNT(*) > 1 OR SUM(customer_id IS NULL OR cut_key IS NULL) > 0;
