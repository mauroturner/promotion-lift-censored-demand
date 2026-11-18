-- R05: every fact_cell_effect[cell_key] is a dim_cell[cell_key] (AC24). A violation is the key that has no row in the dimension and how many fact rows have it.
SELECT f.cell_key AS fact_key, COUNT(*) AS fact_rows
FROM star_fact_cell_effect AS f
WHERE f.cell_key IS NULL OR f.cell_key NOT IN (SELECT cell_key FROM star_dim_cell)
GROUP BY f.cell_key;
