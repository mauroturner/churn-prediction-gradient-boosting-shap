-- No table of the star model but the private fact has a column of customer or of invoice (D26).
SELECT m.name AS star_table, p.name AS column_name
FROM sqlite_master AS m, pragma_table_info(m.name) AS p
WHERE m.type = 'table' AND m.name LIKE 'star\_%' ESCAPE '\' AND m.name != 'star_fact_customer_cut'
  AND (lower(p.name) LIKE '%customer\_id%' ESCAPE '\' OR lower(p.name) LIKE '%invoice%');
