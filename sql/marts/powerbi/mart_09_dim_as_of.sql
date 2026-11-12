-- The calculation dates of the tracking, a parameter table without relationships (plan, section 19; D25, D26). Built by export.build_powerbi_marts inside its transaction, after the reference tables (ref_*).

DROP TABLE IF EXISTS star_dim_as_of;

CREATE TABLE star_dim_as_of AS
SELECT DISTINCT CAST(strftime('%Y%m%d', as_of_date) AS INTEGER) AS as_of_key, as_of_date, as_of_date AS as_of_label FROM tracking ORDER BY as_of_date;
