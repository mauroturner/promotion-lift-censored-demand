-- The stock-outs and the demand they hid by day, city and group. The raw and the recovered mass are those of the series-days that already have their recovery, so their
-- ratio always compares the same series-days.
DROP TABLE IF EXISTS star_fact_stockout_daily;

CREATE TABLE star_fact_stockout_daily AS
SELECT date_key, city_id AS city_key, management_group_id AS group_key, COUNT(*) AS series_days,
       CAST(SUM(stockout_hours) AS REAL) / (COUNT(*) * :analysis_hours) AS stockout_rate,
       SUM(CASE WHEN recovered_sum IS NOT NULL THEN raw_sum END) AS raw_mass, SUM(recovered_sum) AS recovered_mass
FROM stg_series_days
GROUP BY date_key, city_id, management_group_id;
