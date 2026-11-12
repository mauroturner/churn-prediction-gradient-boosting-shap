-- The runs of the flow (plan, section 19; D25, D26). Built by export.build_powerbi_marts inside its transaction, after the reference tables (ref_*).

DROP TABLE IF EXISTS star_dim_pipeline_run;

CREATE TABLE star_dim_pipeline_run AS
SELECT run_key, started_at, finished_at, status, delivery_id, as_of_date, CAST(strftime('%Y%m%d', as_of_date) AS INTEGER) AS as_of_key, lines_delivery,
       customers_scored, contacts, message
FROM pipeline_runs
ORDER BY run_key;
