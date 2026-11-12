-- The calibration by bin of each probabilistic method (plan, section 19; D25, D26). Built by export.build_powerbi_marts inside its transaction, after the reference tables (ref_*).

DROP TABLE IF EXISTS star_fact_calibration;

CREATE TABLE star_fact_calibration AS
SELECT scope, method AS method_key, bin AS point, p_mean, observed, rows, seal_state FROM eval_calibration ORDER BY scope, method, bin, seal_state;
