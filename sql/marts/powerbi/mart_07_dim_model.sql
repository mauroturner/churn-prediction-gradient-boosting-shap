-- The frozen model of the launch (plan, section 19; D25, D26). Built by export.build_powerbi_marts inside its transaction, after the reference tables (ref_*).

DROP TABLE IF EXISTS star_dim_model;

CREATE TABLE star_dim_model AS
SELECT model_version, feature_set, params_es, calibration, threshold, offer_cost, rescue_rate, retained_value, break_even, b_star, trained_as_of,
       config_sha256, seal_state
FROM ref_model;
