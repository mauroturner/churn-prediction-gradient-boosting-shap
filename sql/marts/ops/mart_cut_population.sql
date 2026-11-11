-- The population of every cut with its features and its block (plan, section 7): what scoring and the features read. It never joins the
-- window of a cut: a static test fails if this file names a table of the window (AC12). Rebuilt by build_cuts inside its transaction.

DROP TABLE IF EXISTS mart_cut_population;

CREATE TABLE mart_cut_population AS
SELECT
    f.cut_date, f.customer_id, b.block, b.is_censored,
    f.country_group, f.rec_days, f.tenure_days, f.freq_total, f.freq_90, f.freq_365, f.mon_total, f.mon_90, f.mon_365, f.aov_day,
    f.units_90, f.gap_mean, f.gap_max, f.n_products_365, f.med_units_365, f.canc_365, f.canc_value_365,
    f.computed_as_of, f.run_key
FROM cut_features AS f
JOIN cut_blocks AS b ON b.cut_date = f.cut_date
ORDER BY f.cut_date, f.customer_id;
