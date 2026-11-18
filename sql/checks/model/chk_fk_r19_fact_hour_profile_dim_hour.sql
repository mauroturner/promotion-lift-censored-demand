-- R19: every fact_hour_profile[hour] is a dim_hour[hour] (AC24). A violation is the key that has no row in the dimension and how many fact rows have it.
SELECT f.hour AS fact_key, COUNT(*) AS fact_rows
FROM star_fact_hour_profile AS f
WHERE f.hour IS NULL OR f.hour NOT IN (SELECT hour FROM star_dim_hour)
GROUP BY f.hour;
