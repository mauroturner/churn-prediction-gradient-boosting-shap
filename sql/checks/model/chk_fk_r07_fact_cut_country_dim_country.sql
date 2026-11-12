-- R07: every fact_cut_country[country_key] is a key of dim_country[country_key] (AC27: 100 % of the foreign keys in their dimension).
SELECT f.country_key, COUNT(*) AS rows FROM star_fact_cut_country AS f LEFT JOIN star_dim_country AS d ON d.country_key = f.country_key
WHERE d.country_key IS NULL GROUP BY f.country_key;
