-- The example series-day of the fixed rule (plan, section 21), hour by hour, as the export chose it from the cube.
DROP TABLE IF EXISTS star_fact_example_day;

CREATE TABLE star_fact_example_day AS SELECT hour, observed, recovered, in_stock FROM ref_example_day;
