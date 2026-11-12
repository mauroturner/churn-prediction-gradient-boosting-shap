-- The private fact: one customer in one scored cut, with the customer number; written only to outputs/private/ (plan, section 19; D25, D26). Built by export.build_powerbi_marts inside its transaction, after the reference tables (ref_*).

DROP TABLE IF EXISTS star_fact_customer_cut;

CREATE TABLE star_fact_customer_cut AS
SELECT
    s.customer_id, CAST(strftime('%Y%m%d', s.cut_date) AS INTEGER) AS cut_key, COALESCE((SELECT c.country_key FROM ref_country AS c WHERE c.country_group = f.country_group), (SELECT c.country_key FROM ref_country AS c WHERE c.country_group = 'Otros')) AS country_key, (SELECT b.band_key FROM ref_band AS b WHERE s.risk >= b.p_low AND (s.risk < b.p_high OR b.band_key = 10)) AS band_key,
    f.rec_days, f.freq_365, f.mon_365, f.gap_mean, s.risk, s.is_contact,
    (SELECT e.feature_es FROM score_reasons AS x JOIN ref_reason AS e ON e.reason_key = x.feature
     WHERE x.cut_date = s.cut_date AND x.customer_id = s.customer_id AND x.rank = 1) AS reason_1_es,
    (SELECT e.feature_es FROM score_reasons AS x JOIN ref_reason AS e ON e.reason_key = x.feature
     WHERE x.cut_date = s.cut_date AND x.customer_id = s.customer_id AND x.rank = 2) AS reason_2_es,
    (SELECT e.feature_es FROM score_reasons AS x JOIN ref_reason AS e ON e.reason_key = x.feature
     WHERE x.cut_date = s.cut_date AND x.customer_id = s.customer_id AND x.rank = 3) AS reason_3_es,
    COALESCE(r.returned, 0) AS returned, r.first_return_date, l.churned, s.as_of_date AS scored_as_of_date, s.model_version, s.run_key
FROM model_scores AS s
JOIN cut_features AS f ON f.cut_date = s.cut_date AND f.customer_id = s.customer_id
LEFT JOIN ref_customer_return AS r ON r.cut_date = s.cut_date AND r.customer_id = s.customer_id
LEFT JOIN cut_labels AS l ON l.cut_date = s.cut_date AND l.customer_id = s.customer_id
ORDER BY s.customer_id, s.cut_date;
