-- A series-day (series, day) held more than once. The primary key makes it impossible; the control says so in the language of the rule.
SELECT series_key, date_key, COUNT(*) AS copies
FROM series_days
GROUP BY series_key, date_key
HAVING COUNT(*) > 1;
