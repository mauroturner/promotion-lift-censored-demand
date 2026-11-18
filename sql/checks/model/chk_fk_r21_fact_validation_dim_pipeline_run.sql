-- R21: every fact_validation[run_key] is a dim_pipeline_run[run_key] (AC24). A violation is the key that has no row in the dimension and how many fact rows have it.
SELECT f.run_key AS fact_key, COUNT(*) AS fact_rows
FROM star_fact_validation AS f
WHERE f.run_key IS NULL OR f.run_key NOT IN (SELECT run_key FROM star_dim_pipeline_run)
GROUP BY f.run_key;
