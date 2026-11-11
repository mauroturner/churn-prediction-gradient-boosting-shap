-- The labelled rows of every cut whose window has closed (plan, section 7; D24): the features known before the cut, its block and the label
-- of its window. It is the only source of labels of the baselines and the model (split.labelled_rows); the features and the scoring never read
-- it (a static test). Rebuilt by build_cuts inside its transaction.

DROP TABLE IF EXISTS mart_labelled_rows;

CREATE TABLE mart_labelled_rows AS
SELECT
    f.cut_date, f.customer_id, b.block, l.churned, l.label_end, l.known_as_of,
    f.country_group, f.rec_days, f.tenure_days, f.freq_total, f.freq_90, f.freq_365, f.mon_total, f.mon_90, f.mon_365, f.aov_day,
    f.units_90, f.gap_mean, f.gap_max, f.n_products_365, f.med_units_365, f.canc_365, f.canc_value_365
FROM cut_features AS f
JOIN cut_blocks AS b ON b.cut_date = f.cut_date
JOIN cut_labels AS l ON l.cut_date = f.cut_date AND l.customer_id = f.customer_id
ORDER BY f.cut_date, f.customer_id;
