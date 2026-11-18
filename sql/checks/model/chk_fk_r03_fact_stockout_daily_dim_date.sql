-- R03: every fact_stockout_daily[date_key] is a dim_date[date_key] (AC24). A violation is the key that has no row in the dimension and how many fact rows have it.
SELECT f.date_key AS fact_key, COUNT(*) AS fact_rows
FROM star_fact_stockout_daily AS f
WHERE f.date_key IS NULL OR f.date_key NOT IN (SELECT date_key FROM star_dim_date)
GROUP BY f.date_key;
