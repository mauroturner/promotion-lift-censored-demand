-- R10: every fact_hour_profile[group_key] is a dim_group[group_key] (AC24). A violation is the key that has no row in the dimension and how many fact rows have it.
SELECT f.group_key AS fact_key, COUNT(*) AS fact_rows
FROM star_fact_hour_profile AS f
WHERE f.group_key IS NULL OR f.group_key NOT IN (SELECT group_key FROM star_dim_group)
GROUP BY f.group_key;
