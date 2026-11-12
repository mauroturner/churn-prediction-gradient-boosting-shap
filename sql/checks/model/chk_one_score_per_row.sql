-- Every customer of the population of a scored cut has exactly one score, and every score is one of the population.
SELECT f.cut_date, COUNT(*) AS customers, 'without_score' AS problem
FROM cut_features AS f LEFT JOIN model_scores AS s ON s.cut_date = f.cut_date AND s.customer_id = f.customer_id
WHERE f.cut_date IN (SELECT DISTINCT cut_date FROM model_scores) AND s.customer_id IS NULL
GROUP BY f.cut_date
UNION ALL
SELECT s.cut_date, COUNT(*), 'outside_population'
FROM model_scores AS s LEFT JOIN cut_features AS f ON f.cut_date = s.cut_date AND f.customer_id = s.customer_id
WHERE f.customer_id IS NULL
GROUP BY s.cut_date;
