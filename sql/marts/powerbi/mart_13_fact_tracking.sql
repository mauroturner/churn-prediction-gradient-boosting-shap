-- The tracking of each scored cut at each calculation date (plan, section 19; D25, D26). Built by export.build_powerbi_marts inside its transaction, after the reference tables (ref_*).

DROP TABLE IF EXISTS star_fact_tracking;

CREATE TABLE star_fact_tracking AS
SELECT CAST(strftime('%Y%m%d', as_of_date) AS INTEGER) AS as_of_key, CAST(strftime('%Y%m%d', cut_date) AS INTEGER) AS cut_key, scored, contacted, returned, window_closed, churned,
       contacted_churned, contacted_returned, expected_churners, is_censored
FROM tracking
ORDER BY as_of_key, cut_key;
