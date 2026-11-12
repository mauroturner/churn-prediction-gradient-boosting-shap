-- Ten fixed bands of risk (plan, section 19; D25, D26). Built by export.build_powerbi_marts inside its transaction, after the reference tables (ref_*).

DROP TABLE IF EXISTS star_dim_risk_band;

CREATE TABLE star_dim_risk_band AS SELECT band_key, band_es, p_low, p_high FROM ref_band ORDER BY band_key;
