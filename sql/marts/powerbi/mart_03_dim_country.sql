-- The country groups of the launch, with their customers in the training rows (plan, section 19; D25, D26). Built by export.build_powerbi_marts inside its transaction, after the reference tables (ref_*).

DROP TABLE IF EXISTS star_dim_country;

CREATE TABLE star_dim_country AS
SELECT
    c.country_key, c.country_group, c.country_es,
    (SELECT COUNT(DISTINCT f.customer_id) FROM cut_features AS f JOIN cut_blocks AS b ON b.cut_date = f.cut_date
     WHERE b.block = 'train' AND COALESCE((SELECT c.country_key FROM ref_country AS c WHERE c.country_group = f.country_group), (SELECT c.country_key FROM ref_country AS c WHERE c.country_group = 'Otros')) = c.country_key) AS train_customers
FROM ref_country AS c
ORDER BY c.country_key;
