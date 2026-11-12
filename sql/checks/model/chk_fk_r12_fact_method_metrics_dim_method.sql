-- R12: every fact_method_metrics[method_key] is a key of dim_method[method_key] (AC27: 100 % of the foreign keys in their dimension).
SELECT f.method_key, COUNT(*) AS rows FROM star_fact_method_metrics AS f LEFT JOIN star_dim_method AS d ON d.method_key = f.method_key
WHERE d.method_key IS NULL GROUP BY f.method_key;
