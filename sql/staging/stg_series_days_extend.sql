-- The staging extended to a later instant (D46): the series-days of the days from the instant the table was built for (:from_key) to the new one (:as_of_key), with the
-- columns and blocks of stg_series_days.sql, and then the recovered sums set since on the days it already held (recover only fills a NULL, never rewrites one).
-- promolift.warehouse uses it only when stg_series_days_meta says the table is the whole staging of :from_key under the same parameters and nothing was added before
-- :from_key since; tests/integration/test_load.py compares the result, row for row and in order, with a full rebuild.

INSERT INTO stg_series_days
SELECT
    d.series_key, d.date_key, d.delivery_id, s.store_id, s.city_id, s.product_id, s.management_group_id, s.first_category_id, s.second_category_id,
    s.third_category_id, d.day_state, d.band, d.activity_flag, d.discount, d.holiday_flag, d.raw_sum, d.instock_hours, d.stockout_hours,
    d.instock_sum, d.recovered_sum, d.fully_out,
    CASE
        WHEN d.date_key BETWEEN :train_first_key AND :train_last_key THEN 'train'
        WHEN d.date_key BETWEEN :purge_first_key AND :purge_last_key THEN 'purge'
        WHEN d.date_key BETWEEN :valid_v1_first_key AND :valid_v1_last_key THEN 'valid_v1'
        WHEN d.date_key BETWEEN :valid_v2_first_key AND :valid_v2_last_key THEN 'valid_v2'
        WHEN d.date_key BETWEEN :test_first_key AND :test_last_key THEN 'test'
        ELSE 'outside'
    END AS block
FROM series_days AS d
JOIN series AS s ON s.series_key = d.series_key
WHERE d.date_key >= :from_key AND d.date_key < :as_of_key;

UPDATE stg_series_days
SET recovered_sum = (SELECT d.recovered_sum FROM series_days AS d WHERE d.series_key = stg_series_days.series_key AND d.date_key = stg_series_days.date_key)
WHERE recovered_sum IS NULL AND date_key < :from_key;
