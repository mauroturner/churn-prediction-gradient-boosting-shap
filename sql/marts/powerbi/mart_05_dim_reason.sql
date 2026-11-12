-- The features that can be a reason (plan, section 19; D25, D26). Built by export.build_powerbi_marts inside its transaction, after the reference tables (ref_*).

DROP TABLE IF EXISTS star_dim_reason;

CREATE TABLE star_dim_reason AS SELECT reason_key, reason_key AS feature, feature_es, description_es FROM ref_reason ORDER BY sort_order;
