-- Every series-day that has a forecast has the four of them (F0, F1, F2a and F2), once each (RF17). A violation is a series-day with another number of methods or a repeated one.
SELECT series_key, date_key, scope, COUNT(*) AS forecasts, COUNT(DISTINCT method) AS methods
FROM forecasts
GROUP BY series_key, date_key, scope
HAVING COUNT(*) <> 4 OR COUNT(DISTINCT method) <> 4;
