-- A forecast is issued only for a series-day with a promotion (D15). A violation is a forecast whose series-day is not a promo day, or is not in the warehouse.
SELECT f.series_key, f.date_key, f.method, d.day_state
FROM forecasts AS f
LEFT JOIN series_days AS d ON d.series_key = f.series_key AND d.date_key = f.date_key
WHERE d.day_state IS NULL OR d.day_state <> 'promo';
