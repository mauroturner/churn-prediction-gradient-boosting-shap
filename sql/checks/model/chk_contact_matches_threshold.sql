-- A customer is contacted if and only if its risk reaches the threshold of its score.
SELECT cut_date, COUNT(*) AS customers FROM model_scores WHERE is_contact != (risk >= threshold) GROUP BY cut_date;
