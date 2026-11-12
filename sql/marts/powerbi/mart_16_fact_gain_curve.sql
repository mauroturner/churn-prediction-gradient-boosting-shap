-- The gain curve of each method (plan, section 19; D25, D26). Built by export.build_powerbi_marts inside its transaction, after the reference tables (ref_*).

DROP TABLE IF EXISTS star_fact_gain_curve;

CREATE TABLE star_fact_gain_curve AS
SELECT scope, method AS method_key, point, share_contacted, share_captured, lift, seal_state FROM eval_gain ORDER BY scope, method, point, seal_state;
