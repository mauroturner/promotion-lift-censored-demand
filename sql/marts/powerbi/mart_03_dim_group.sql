-- The management groups of the series the warehouse holds (the dataset does not name them).
DROP TABLE IF EXISTS star_dim_group;

CREATE TABLE star_dim_group AS SELECT DISTINCT management_group_id AS group_key, 'Grupo ' || management_group_id AS label_es FROM series;
