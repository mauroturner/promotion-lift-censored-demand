-- The two versions of the sale.
DROP TABLE IF EXISTS star_dim_version;

CREATE TABLE star_dim_version AS SELECT version_key, label_es FROM ref_version;
