-- stg_lines holds exactly one row for each line known on :as_of and nothing else.
SELECT r.line_id, 'missing' AS problem FROM raw_lines AS r LEFT JOIN stg_lines AS s ON s.line_id = r.line_id
WHERE r.invoice_date <= :as_of AND s.line_id IS NULL
UNION ALL
SELECT line_id, 'repeated' FROM stg_lines GROUP BY line_id HAVING COUNT(*) > 1
UNION ALL
SELECT s.line_id, 'unknown_or_later' FROM stg_lines AS s LEFT JOIN raw_lines AS r ON r.line_id = s.line_id
WHERE r.line_id IS NULL OR r.invoice_date > :as_of;
