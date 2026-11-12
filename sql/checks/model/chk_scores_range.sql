-- Every risk is a number in [0, 1] (M04's second line).
SELECT cut_date, COUNT(*) AS customers FROM model_scores WHERE risk IS NULL OR NOT (risk >= 0 AND risk <= 1) GROUP BY cut_date;
