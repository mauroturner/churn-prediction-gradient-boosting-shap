-- Every labelled customer is in the population of its cut. One row per cut, counted.
SELECT l.cut_date, COUNT(*) AS customers FROM cut_labels AS l
LEFT JOIN cut_features AS f ON f.cut_date = l.cut_date AND f.customer_id = l.customer_id
WHERE f.customer_id IS NULL
GROUP BY l.cut_date;
