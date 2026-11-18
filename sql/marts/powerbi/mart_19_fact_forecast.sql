-- The forecast errors of the four methods: the validation (everything fitted on the training block) and the test week.
DROP TABLE IF EXISTS star_fact_forecast;

CREATE TABLE star_fact_forecast AS
SELECT 'valid' AS scope, method AS method_key, :fit_blocks_valid AS fit_blocks, SUM(ABS(forecast - observed_instock)) / SUM(observed_instock) AS wape,
       SUM(forecast - observed_instock) / SUM(observed_instock) AS bias, COUNT(*) AS series_days, (SELECT launch_state FROM ref_seal) AS seal_state
FROM forecasts
WHERE scope = 'valid'
GROUP BY method
UNION ALL
SELECT 'test', method, fit_blocks, wape, bias, series_days, seal_state
FROM eval_forecast
WHERE :test_closed = 1;
