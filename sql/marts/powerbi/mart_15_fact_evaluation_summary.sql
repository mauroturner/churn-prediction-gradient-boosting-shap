-- The criteria C01-C10 (plan, section 19; D25, D26). Built by export.build_powerbi_marts inside its transaction, after the reference tables (ref_*).

DROP TABLE IF EXISTS star_fact_evaluation_summary;

CREATE TABLE star_fact_evaluation_summary AS
SELECT criterion_id, name_es, value, baseline_value, ci_low, ci_high, threshold_es, passed, seen_by_research, seen_by_planner, verdict_es, seal_state
FROM eval_criteria
ORDER BY criterion_id, seal_state;
