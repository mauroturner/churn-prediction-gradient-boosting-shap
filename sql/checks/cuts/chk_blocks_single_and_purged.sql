-- Every cut with a population has its one block, and the boundaries between blocks of different use are purged by N days (D08).
SELECT DISTINCT f.cut_date, 'without_block' AS problem FROM cut_features AS f LEFT JOIN cut_blocks AS b ON b.cut_date = f.cut_date
WHERE b.cut_date IS NULL
UNION ALL
SELECT edges.boundary, 'without_purge' FROM (
    SELECT 'train → valid_v1' AS boundary, (SELECT MAX(cut_date) FROM cut_blocks WHERE block = 'train') AS last,
           (SELECT MIN(cut_date) FROM cut_blocks WHERE block = 'valid_v1') AS first
    UNION ALL
    SELECT 'valid_v2 → test', (SELECT MAX(cut_date) FROM cut_blocks WHERE block = 'valid_v2'), (SELECT MIN(cut_date) FROM cut_blocks WHERE block = 'test')
) AS edges
WHERE edges.last IS NOT NULL AND edges.first IS NOT NULL AND date(edges.last, '+' || :horizon_days || ' days') > edges.first;
