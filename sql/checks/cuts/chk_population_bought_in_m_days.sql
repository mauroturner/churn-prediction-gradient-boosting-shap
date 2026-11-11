-- Every customer of a cut's population has a purchase line in [c - M, c - 1] (a net purchase day needs one; the netting is in Python).
-- One row per cut with such customers, counted, never named (D26).
SELECT f.cut_date, COUNT(*) AS customers FROM cut_features AS f
WHERE NOT EXISTS (
    SELECT 1 FROM raw_lines AS r
    WHERE r.customer_id = f.customer_id AND r.invoice_date >= date(f.cut_date, '-' || :active_days || ' days') AND r.invoice_date < f.cut_date
      AND substr(r.invoice, 1, 1) <> 'C' AND r.quantity > 0 AND r.price > 0
)
GROUP BY f.cut_date;
