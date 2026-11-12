-- The demonstration of the leak (plan, section 19; D25, D26). Built by export.build_powerbi_marts inside its transaction, after the reference tables (ref_*).

DROP TABLE IF EXISTS star_fact_leakage;

CREATE TABLE star_fact_leakage AS SELECT variable, variable_es, auc_valid_v2, note_es FROM eval_leakage ORDER BY variable;
