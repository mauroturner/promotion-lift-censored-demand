-- The recovery methods that were measured and the four forecasts.
DROP TABLE IF EXISTS star_dim_method;

CREATE TABLE star_dim_method AS SELECT method_key, kind_es, label_es FROM ref_method;
