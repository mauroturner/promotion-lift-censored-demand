-- A cell is ranked only with at least :min_series series (D13), and only a ranked cell has a rank and a tier. A violation is a cell that breaks either.
SELECT scope, version_key, cell_key, series, ranked, rank, tier
FROM star_fact_cell_effect
WHERE (ranked = 1 AND (series < :min_series OR rank IS NULL OR tier IS NULL OR lift IS NULL OR ci_low IS NULL OR ci_high IS NULL))
   OR (ranked = 0 AND (rank IS NOT NULL OR tier IS NOT NULL));
