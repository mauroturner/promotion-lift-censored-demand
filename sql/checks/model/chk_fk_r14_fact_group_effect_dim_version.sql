-- R14: every fact_group_effect[version_key] is a dim_version[version_key] (AC24). A violation is the key that has no row in the dimension and how many fact rows have it.
SELECT f.version_key AS fact_key, COUNT(*) AS fact_rows
FROM star_fact_group_effect AS f
WHERE f.version_key IS NULL OR f.version_key NOT IN (SELECT version_key FROM star_dim_version)
GROUP BY f.version_key;
