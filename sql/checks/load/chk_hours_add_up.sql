-- The hours with and without stock of a series-day add up to the analysis hours, and fully_out says whether none had stock.
SELECT series_key, date_key, instock_hours, stockout_hours, fully_out
FROM series_days
WHERE instock_hours + stockout_hours != :analysis_hours
   OR fully_out != (instock_hours = 0);
