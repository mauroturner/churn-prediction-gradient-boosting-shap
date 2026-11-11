-- Every line is loaded once (V12's second line).
SELECT line_id, COUNT(*) AS copies FROM raw_lines GROUP BY line_id HAVING COUNT(*) > 1;
