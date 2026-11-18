-- The record of the staging (D46): the instant, the parameters and the rows stg_series_days was built with, written by promolift.warehouse after every rebuild or extension,
-- and the triggers that remove it when the tables it was built from change in any way the flow does not: a series-day or a series updated or deleted, a series-day added
-- before the recorded instant, or a recovered sum other than a NULL being filled. Without the record the next staging is a full rebuild. The flow only inserts the
-- series-days of later days and fills recovered sums (warehouse.load_delivery and set_recovered_sums), and those keep it.

CREATE TABLE IF NOT EXISTS stg_series_days_meta (
    as_of_key INTEGER NOT NULL,
    params TEXT NOT NULL,
    staged_rows INTEGER NOT NULL
);

CREATE TRIGGER IF NOT EXISTS stg_meta_series_day_before_the_instant AFTER INSERT ON series_days
WHEN NEW.date_key < (SELECT MAX(as_of_key) FROM stg_series_days_meta)
BEGIN
    DELETE FROM stg_series_days_meta;
END;

CREATE TRIGGER IF NOT EXISTS stg_meta_series_day_changed AFTER UPDATE OF series_key, date_key, delivery_id, day_state, band, activity_flag, discount, holiday_flag, raw_sum,
    instock_hours, stockout_hours, instock_sum, fully_out ON series_days
BEGIN
    DELETE FROM stg_series_days_meta;
END;

CREATE TRIGGER IF NOT EXISTS stg_meta_recovered_sum_rewritten AFTER UPDATE OF recovered_sum ON series_days
WHEN NOT (OLD.recovered_sum IS NULL AND NEW.recovered_sum IS NOT NULL)
BEGIN
    DELETE FROM stg_series_days_meta;
END;

CREATE TRIGGER IF NOT EXISTS stg_meta_series_day_deleted AFTER DELETE ON series_days
BEGIN
    DELETE FROM stg_series_days_meta;
END;

CREATE TRIGGER IF NOT EXISTS stg_meta_series_changed AFTER UPDATE ON series
BEGIN
    DELETE FROM stg_series_days_meta;
END;

CREATE TRIGGER IF NOT EXISTS stg_meta_series_deleted AFTER DELETE ON series
BEGIN
    DELETE FROM stg_series_days_meta;
END;
