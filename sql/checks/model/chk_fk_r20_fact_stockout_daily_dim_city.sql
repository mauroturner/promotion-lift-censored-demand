-- R20: every fact_stockout_daily[city_key] is a dim_city[city_key] (AC24). A violation is the key that has no row in the dimension and how many fact rows have it.
SELECT f.city_key AS fact_key, COUNT(*) AS fact_rows
FROM star_fact_stockout_daily AS f
WHERE f.city_key IS NULL OR f.city_key NOT IN (SELECT city_key FROM star_dim_city)
GROUP BY f.city_key;
