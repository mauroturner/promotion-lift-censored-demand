-- Every cell of every day of the test week that ``daily_cell`` issued before :as_of_key is in the star model exactly once, and the star model has no daily cell that was not issued
-- (plan, section 7). A violation is a key with the number of rows on each side.
SELECT d.date_key, d.version AS version_key, d.cell_key, COUNT(s.cell_key) AS star_rows, 1 AS issued_rows
FROM daily_cell AS d
LEFT JOIN star_fact_daily_cell AS s ON s.date_key = d.date_key AND s.version_key = d.version AND s.cell_key = d.cell_key
WHERE d.cell_key LIKE 'g%' AND d.date_key < :as_of_key
GROUP BY d.date_key, d.version, d.cell_key
HAVING COUNT(s.cell_key) <> 1
UNION ALL
SELECT s.date_key, s.version_key, s.cell_key, 1, 0
FROM star_fact_daily_cell AS s
WHERE NOT EXISTS (SELECT 1 FROM daily_cell AS d WHERE d.date_key = s.date_key AND d.version = s.version_key AND d.cell_key = s.cell_key);
