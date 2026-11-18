-- R08: every fact_band_effect[band_key] is a dim_band[band_key] (AC24). A violation is the key that has no row in the dimension and how many fact rows have it.
SELECT f.band_key AS fact_key, COUNT(*) AS fact_rows
FROM star_fact_band_effect AS f
WHERE f.band_key IS NULL OR f.band_key NOT IN (SELECT band_key FROM star_dim_band)
GROUP BY f.band_key;
