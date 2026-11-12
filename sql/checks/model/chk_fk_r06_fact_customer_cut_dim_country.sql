-- R06: every fact_customer_cut[country_key] is a key of dim_country[country_key] (AC27: 100 % of the foreign keys in their dimension).
SELECT f.country_key, COUNT(*) AS rows FROM star_fact_customer_cut AS f LEFT JOIN star_dim_country AS d ON d.country_key = f.country_key
WHERE d.country_key IS NULL GROUP BY f.country_key;
