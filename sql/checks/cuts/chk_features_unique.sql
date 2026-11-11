-- One row of the population per cut and customer. One row per cut, counted.
SELECT cut_date, COUNT(*) AS customers FROM (SELECT cut_date, customer_id FROM cut_features GROUP BY cut_date, customer_id HAVING COUNT(*) > 1)
GROUP BY cut_date;
