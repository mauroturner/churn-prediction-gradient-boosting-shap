-- The tracking counts what the scores and the labels hold.
SELECT t.as_of_date, t.cut_date
FROM tracking AS t
JOIN (SELECT cut_date, COUNT(*) AS scored, SUM(is_contact) AS contacted FROM model_scores GROUP BY cut_date) AS s ON s.cut_date = t.cut_date
WHERE t.scored != s.scored OR t.contacted != s.contacted OR t.contacted_returned > t.returned OR t.contacted_returned > t.contacted
   OR (t.window_closed = 1 AND t.churned != (SELECT SUM(l.churned) FROM cut_labels AS l WHERE l.cut_date = t.cut_date))
   OR (t.window_closed = 0 AND t.churned IS NOT NULL);
