-- The cuts, with their population and, once known, their churn rate (the test's only after the seal) (plan, section 19; D25, D26). Built by export.build_powerbi_marts inside its transaction, after the reference tables (ref_*).

DROP TABLE IF EXISTS star_dim_cut;

CREATE TABLE star_dim_cut AS
SELECT
    CAST(strftime('%Y%m%d', b.cut_date) AS INTEGER) AS cut_key, b.cut_date, b.label_end, b.block, e.block_es, b.is_censored,
    (SELECT COUNT(*) FROM cut_features AS f WHERE f.cut_date = b.cut_date) AS active_customers,
    CASE WHEN b.block = 'test' AND (SELECT test_sealed FROM ref_flags) = 0 THEN NULL
         ELSE (SELECT AVG(l.churned) FROM cut_labels AS l WHERE l.cut_date = b.cut_date) END AS churn_rate
FROM cut_blocks AS b
JOIN ref_block AS e ON e.block = b.block
ORDER BY b.cut_date;
