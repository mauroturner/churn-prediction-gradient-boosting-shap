-- The calendar from the first to the last day of the data (plan, section 19; D25, D26). Built by export.build_powerbi_marts inside its transaction, after the reference tables (ref_*).

DROP TABLE IF EXISTS star_dim_date;

CREATE TABLE star_dim_date AS
WITH RECURSIVE days (day) AS (
    SELECT date(:first_date)
    UNION ALL
    SELECT date(day, '+1 day') FROM days WHERE day < date(:last_date)
)
SELECT
    CAST(strftime('%Y%m%d', day) AS INTEGER) AS date_key, day AS date, CAST(strftime('%Y', day) AS INTEGER) AS year, CAST(strftime('%m', day) AS INTEGER) AS month,
    CASE CAST(strftime('%m', day) AS INTEGER) WHEN 1 THEN 'enero' WHEN 2 THEN 'febrero' WHEN 3 THEN 'marzo' WHEN 4 THEN 'abril' WHEN 5 THEN 'mayo'
        WHEN 6 THEN 'junio' WHEN 7 THEN 'julio' WHEN 8 THEN 'agosto' WHEN 9 THEN 'septiembre' WHEN 10 THEN 'octubre' WHEN 11 THEN 'noviembre'
        ELSE 'diciembre' END AS month_name_es,
    (CAST(strftime('%w', day) AS INTEGER) + 6) % 7 + 1 AS weekday,
    CASE (CAST(strftime('%w', day) AS INTEGER) + 6) % 7 + 1 WHEN 1 THEN 'lunes' WHEN 2 THEN 'martes' WHEN 3 THEN 'miércoles' WHEN 4 THEN 'jueves'
        WHEN 5 THEN 'viernes' WHEN 6 THEN 'sábado' ELSE 'domingo' END AS weekday_es
FROM days;
