-- A label is written only once its window has closed: known_as_of >= label_end = c + N - 1 (RF12, D06). One row per cut, counted.
SELECT cut_date, COUNT(*) AS customers FROM cut_labels
WHERE known_as_of < label_end OR label_end <> date(cut_date, '+' || (:horizon_days - 1) || ' days')
GROUP BY cut_date;
