-- The series-days that had closed at the instant of a calculation, joined to their series and to the block of the split (plan, sections 5 and 7).
-- Rebuilt inside the transaction of a load (DROP + CREATE TABLE AS), so a rollback undoes it too. :as_of_key is the day of the instant as YYYYMMDD
-- and a day is known whole at 00:00 of the next one (D05): only the days before it are in. The block of a day is the one of
-- promolift.split.block_of; tests/integration/test_load.py compares the two under two partitions.

DROP TABLE IF EXISTS stg_series_days;

CREATE TABLE stg_series_days AS
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
WHERE d.date_key < :as_of_key;

CREATE UNIQUE INDEX ix_stg_series_days_key ON stg_series_days (series_key, date_key);
CREATE INDEX ix_stg_series_days_block ON stg_series_days (block, management_group_id, day_state);
