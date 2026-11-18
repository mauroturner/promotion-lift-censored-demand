-- What each day of the test week issued, by cell (the rows of the whole day and of each band are not cells: the facts hold only the cells, so that a sum over them counts once).
DROP TABLE IF EXISTS star_fact_daily_cell;

CREATE TABLE star_fact_daily_cell AS
SELECT date_key, version AS version_key, cell_key, observed, counterfactual, lift, series_days, stockout_hours
FROM daily_cell
WHERE cell_key LIKE 'g%' AND date_key < :as_of_key;
