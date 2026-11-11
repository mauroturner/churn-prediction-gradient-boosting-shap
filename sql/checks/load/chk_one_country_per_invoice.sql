-- One country per invoice (V13's second line). The first line names the invoice: never its number (D26).
SELECT MIN(line_id) AS line_id, COUNT(DISTINCT country) AS countries FROM raw_lines GROUP BY invoice HAVING COUNT(DISTINCT country) > 1;
