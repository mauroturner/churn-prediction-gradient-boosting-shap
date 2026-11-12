-- R08: every fact_customer_cut[band_key] is a key of dim_risk_band[band_key] (AC27: 100 % of the foreign keys in their dimension).
SELECT f.band_key, COUNT(*) AS rows FROM star_fact_customer_cut AS f LEFT JOIN star_dim_risk_band AS d ON d.band_key = f.band_key
WHERE d.band_key IS NULL GROUP BY f.band_key;
