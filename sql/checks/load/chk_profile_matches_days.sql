-- The hour profile adds up to the series-days it was built from: for every (day, group, state) the same number of series-days at every hour, the sale
-- of the analysis hours equal to the sum of raw_sum (to 1e-6) and the same number of hours without stock; and no profile row without series-days.
WITH days AS (
    SELECT d.date_key, s.management_group_id, d.day_state, COUNT(*) AS n, SUM(d.raw_sum) AS raw_sum, SUM(d.stockout_hours) AS stockout_hours
    FROM series_days AS d
    JOIN series AS s ON s.series_key = d.series_key
    GROUP BY d.date_key, s.management_group_id, d.day_state
),
profile AS (
    SELECT date_key, management_group_id, day_state, MIN(series_days) AS min_n, MAX(series_days) AS max_n, SUM(sales_sum) AS sales_sum,
           SUM(stockout_count) AS stockout_count
    FROM hour_profile
    WHERE hour BETWEEN :first_hour AND :last_hour
    GROUP BY date_key, management_group_id, day_state
)
SELECT d.date_key, d.management_group_id, d.day_state, 'profile_differs' AS problem
FROM days AS d
LEFT JOIN profile AS p ON p.date_key = d.date_key AND p.management_group_id = d.management_group_id AND p.day_state = d.day_state
WHERE p.date_key IS NULL OR p.min_n != d.n OR p.max_n != d.n OR ABS(p.sales_sum - d.raw_sum) > 0.000001 OR p.stockout_count != d.stockout_hours
UNION ALL
SELECT p.date_key, p.management_group_id, p.day_state, 'profile_without_days' AS problem
FROM profile AS p
LEFT JOIN days AS d ON d.date_key = p.date_key AND d.management_group_id = p.management_group_id AND d.day_state = p.day_state
WHERE d.date_key IS NULL;
