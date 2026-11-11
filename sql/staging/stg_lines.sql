-- The lines known on the calculation date :as_of, with their role (RF05, D03): the same order of the rules as validate.classify_lines,
-- which a test compares line by line. :large_quantity_units is validate.LARGE_QUANTITY_UNITS (V29). The first character of the invoice is
-- compared with substr, which is case sensitive like Python's startswith (LIKE is not).

DROP TABLE IF EXISTS stg_lines;

CREATE TABLE stg_lines AS
WITH known AS (
    SELECT *, substr(invoice, 1, 1) AS invoice_prefix
    FROM raw_lines
    WHERE invoice_date <= :as_of
),
reasons AS (
    SELECT *,
        CASE
            WHEN customer_id IS NULL THEN 'no_customer'
            WHEN (invoice_prefix = 'C' AND quantity >= 0) OR (invoice_prefix <> 'C' AND quantity <= 0) THEN 'non_positive_quantity'
            WHEN price <= 0 THEN 'non_positive_price'
            WHEN code_kind = 'service' THEN 'service_code'
            WHEN code_kind = 'gift_voucher' THEN 'gift_voucher'
            WHEN invoice_prefix = 'A' THEN 'adjustment_invoice'
        END AS exclusion_reason
    FROM known
)
SELECT
    line_id, delivery_id, sheet, source_row, invoice, stock_code, description, quantity, invoice_ts, invoice_date, price, customer_id, country,
    code_kind, is_repeated_line,
    CASE WHEN exclusion_reason IS NOT NULL THEN 'excluded' WHEN invoice_prefix = 'C' THEN 'cancellation' ELSE 'purchase' END AS role,
    exclusion_reason,
    NULLIF(rtrim(
        CASE WHEN is_repeated_line = 1 THEN 'repeated_line,' ELSE '' END
        || CASE WHEN quantity >= :large_quantity_units THEN 'large_quantity,' ELSE '' END
        || CASE WHEN country = 'Unspecified' THEN 'unspecified_country,' ELSE '' END, ','), '') AS quality_flags
FROM reasons
ORDER BY line_id;
