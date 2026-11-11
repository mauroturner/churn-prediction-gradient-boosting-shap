-- A cut is day 1 of a month, in every table of the cuts.
SELECT cut_date, 'cut_blocks' AS source FROM cut_blocks WHERE strftime('%d', cut_date) <> '01'
UNION ALL SELECT DISTINCT cut_date, 'cut_features' FROM cut_features WHERE strftime('%d', cut_date) <> '01'
UNION ALL SELECT DISTINCT cut_date, 'cut_labels' FROM cut_labels WHERE strftime('%d', cut_date) <> '01';
