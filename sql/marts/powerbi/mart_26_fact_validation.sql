-- The rules of each run, with their status in Spanish (plan, section 19; D25, D26). Built by export.build_powerbi_marts inside its transaction, after the reference tables (ref_*).

DROP TABLE IF EXISTS star_fact_validation;

CREATE TABLE star_fact_validation AS
SELECT run_key, rule_id, name_es,
       CASE severity WHEN 'blocking' THEN 'bloqueante' WHEN 'warning' THEN 'advertencia' ELSE 'informativa' END AS severity,
       scope, aggregation,
       CASE WHEN passed = 1 THEN 'pasa' WHEN severity = 'blocking' THEN 'falla' ELSE 'advierte' END AS status,
       rows_affected, customers_affected, value_gbp
FROM validation_results
ORDER BY run_key, rule_id;
