-- R17: every fact_tracking[as_of_key] is a key of dim_date[date_key] (AC27: 100 % of the foreign keys in their dimension).
SELECT f.as_of_key, COUNT(*) AS rows FROM star_fact_tracking AS f LEFT JOIN star_dim_date AS d ON d.date_key = f.as_of_key
WHERE d.date_key IS NULL GROUP BY f.as_of_key;
