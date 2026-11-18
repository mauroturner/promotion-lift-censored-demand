-- R18: every fact_forecast[method_key] is a dim_method[method_key] (AC24). A violation is the key that has no row in the dimension and how many fact rows have it.
SELECT f.method_key AS fact_key, COUNT(*) AS fact_rows
FROM star_fact_forecast AS f
WHERE f.method_key IS NULL OR f.method_key NOT IN (SELECT method_key FROM star_dim_method)
GROUP BY f.method_key;
