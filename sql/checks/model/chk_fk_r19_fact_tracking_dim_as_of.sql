-- R19: every fact_tracking[as_of_key] is a key of dim_as_of[as_of_key] (AC27: 100 % of the foreign keys in their dimension; D90).
SELECT f.as_of_key, COUNT(*) AS rows FROM star_fact_tracking AS f LEFT JOIN star_dim_as_of AS d ON d.as_of_key = f.as_of_key
WHERE d.as_of_key IS NULL GROUP BY f.as_of_key;
