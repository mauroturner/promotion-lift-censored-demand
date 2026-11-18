-- The cities of the series (the dataset only numbers them).
DROP TABLE IF EXISTS star_dim_city;

CREATE TABLE star_dim_city AS SELECT DISTINCT city_id AS city_key, 'Ciudad ' || city_id AS label_es FROM series;
