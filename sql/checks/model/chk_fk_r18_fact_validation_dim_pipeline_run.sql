-- R18: every fact_validation[run_key] is a key of dim_pipeline_run[run_key] (AC27: 100 % of the foreign keys in their dimension).
SELECT f.run_key, COUNT(*) AS rows FROM star_fact_validation AS f LEFT JOIN star_dim_pipeline_run AS d ON d.run_key = f.run_key
WHERE d.run_key IS NULL GROUP BY f.run_key;
