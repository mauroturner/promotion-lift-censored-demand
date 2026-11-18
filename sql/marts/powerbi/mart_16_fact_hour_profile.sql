-- The sale and the stock-outs by hour, day, group and state of the day, from the days that had closed at :as_of.
DROP TABLE IF EXISTS star_fact_hour_profile;

CREATE TABLE star_fact_hour_profile AS
SELECT date_key, management_group_id AS group_key, hour, day_state, series_days, sales_sum / series_days AS mean_sales, CAST(stockout_count AS REAL) / series_days AS stockout_rate
FROM hour_profile
WHERE date_key < :as_of_key;
