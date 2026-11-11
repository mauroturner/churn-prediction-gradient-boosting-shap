-- One customer per invoice; a guest line next to a customer line is two (V13's second line). The first line names the invoice: never its number (D26).
SELECT MIN(line_id) AS line_id, COUNT(DISTINCT COALESCE(customer_id, -1)) AS customers FROM raw_lines GROUP BY invoice
HAVING COUNT(DISTINCT COALESCE(customer_id, -1)) > 1;
