-- The model and the baselines, B* marked (plan, section 19; D25, D26). Built by export.build_powerbi_marts inside its transaction, after the reference tables (ref_*).

DROP TABLE IF EXISTS star_dim_method;

CREATE TABLE star_dim_method AS SELECT method_key, method_es, is_b_star FROM ref_method ORDER BY sort_order;
