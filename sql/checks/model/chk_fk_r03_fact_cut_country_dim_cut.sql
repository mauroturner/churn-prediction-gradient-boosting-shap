-- R03: every fact_cut_country[cut_key] is a key of dim_cut[cut_key] (AC27: 100 % of the foreign keys in their dimension).
SELECT f.cut_key, COUNT(*) AS rows FROM star_fact_cut_country AS f LEFT JOIN star_dim_cut AS d ON d.cut_key = f.cut_key
WHERE d.cut_key IS NULL GROUP BY f.cut_key;
