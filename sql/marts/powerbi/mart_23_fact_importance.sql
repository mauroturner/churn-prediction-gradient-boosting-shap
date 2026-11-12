-- The mean |SHAP| of each feature (plan, section 19; D25, D26). Built by export.build_powerbi_marts inside its transaction, after the reference tables (ref_*).

DROP TABLE IF EXISTS star_fact_importance;

CREATE TABLE star_fact_importance AS SELECT scope, feature AS reason_key, mean_abs_shap, seal_state FROM feature_importance ORDER BY scope, feature, seal_state;
