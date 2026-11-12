-- R10: every fact_reason_summary[reason_key] is a key of dim_reason[reason_key] (AC27: 100 % of the foreign keys in their dimension).
SELECT f.reason_key, COUNT(*) AS rows FROM star_fact_reason_summary AS f LEFT JOIN star_dim_reason AS d ON d.reason_key = f.reason_key
WHERE d.reason_key IS NULL GROUP BY f.reason_key;
