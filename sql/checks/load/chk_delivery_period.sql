-- Every line was loaded with the delivery whose period holds its invoice date (V11's second line).
SELECT r.line_id, r.delivery_id, r.invoice_date FROM raw_lines AS r JOIN deliveries AS d ON d.delivery_id = r.delivery_id
WHERE r.invoice_date < d.lines_from OR r.invoice_date > d.lines_to;
