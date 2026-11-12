-- The churn rate of the training by N and M (plan, section 19; D25, D26). Built by export.build_powerbi_marts inside its transaction, after the reference tables (ref_*).

DROP TABLE IF EXISTS star_fact_label_definition;

CREATE TABLE star_fact_label_definition AS SELECT n, m, churn_rate, rows FROM eval_label_definition ORDER BY n, m;
