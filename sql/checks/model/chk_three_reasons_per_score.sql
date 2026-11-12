-- Every score has its reasons ranked 1 to :reasons_per_score (three, or every feature of a smaller set; D64), and no other.
SELECT s.cut_date, COUNT(*) AS customers
FROM model_scores AS s
LEFT JOIN (SELECT cut_date, customer_id, COUNT(*) AS reasons, MIN(rank) AS first, MAX(rank) AS last FROM score_reasons GROUP BY cut_date, customer_id) AS r
    ON r.cut_date = s.cut_date AND r.customer_id = s.customer_id
WHERE r.reasons IS NULL OR r.reasons != :reasons_per_score OR r.first != 1 OR r.last != :reasons_per_score
GROUP BY s.cut_date;
