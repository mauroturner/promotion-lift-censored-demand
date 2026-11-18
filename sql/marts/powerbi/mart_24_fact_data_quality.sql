-- The state of the series-days by day, and how many had no stock at all from the first to the last analysis hour.
DROP TABLE IF EXISTS star_fact_data_quality;

CREATE TABLE star_fact_data_quality AS
SELECT date_key, COUNT(*) AS series_days, SUM(day_state = 'promo') AS promo, SUM(day_state = 'regular') AS regular, SUM(day_state = 'unflagged_cut') AS unflagged_cut,
       SUM(day_state = 'anomalous') AS anomalous, SUM(fully_out) AS fully_out, CAST(SUM(stockout_hours) AS REAL) / (COUNT(*) * :analysis_hours) AS stockout_rate
FROM stg_series_days
GROUP BY date_key;
