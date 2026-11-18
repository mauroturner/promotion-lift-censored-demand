-- The calendar of the days that had closed at :as_of (plan, section 19): one row per loaded day, with its block of the split, weekday and holiday mark.
DROP TABLE IF EXISTS star_dim_date;

CREATE TABLE star_dim_date AS
WITH days AS (
    SELECT date_key, MAX(holiday_flag) AS holiday_flag, MIN(block) AS block,
           date(substr(CAST(date_key AS TEXT), 1, 4) || '-' || substr(CAST(date_key AS TEXT), 5, 2) || '-' || substr(CAST(date_key AS TEXT), 7, 2)) AS iso
    FROM stg_series_days
    GROUP BY date_key
)
SELECT d.date_key, d.iso AS date, w.weekday_es, CASE WHEN w.weekday IN (0, 6) THEN 1 ELSE 0 END AS is_weekend, d.holiday_flag, d.block, b.block_es
FROM days AS d
JOIN ref_weekday AS w ON w.weekday = CAST(strftime('%w', d.iso) AS INTEGER)
JOIN ref_block AS b ON b.block = d.block;
