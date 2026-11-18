-- A loaded delivery whose series-days fall outside its period (the close has none), or that holds another number of series-days than it declares.
SELECT d.delivery_id, 'outside_period' AS problem, COUNT(*) AS series_days
FROM series_days AS s
JOIN deliveries AS d ON d.delivery_id = s.delivery_id
WHERE d.status = 'loaded'
  AND (d.first_day IS NULL
       OR s.date_key < CAST(strftime('%Y%m%d', d.first_day) AS INTEGER)
       OR s.date_key > CAST(strftime('%Y%m%d', d.last_day) AS INTEGER))
GROUP BY d.delivery_id
UNION ALL
SELECT d.delivery_id, 'count_differs' AS problem, ABS(d.series_days - COUNT(s.series_key)) AS series_days
FROM deliveries AS d
LEFT JOIN series_days AS s ON s.delivery_id = d.delivery_id
WHERE d.status = 'loaded'
GROUP BY d.delivery_id
HAVING d.series_days != COUNT(s.series_key);
