-- The 24 hours of the day, with the 16 that the analysis covers (06 to 21) marked.
DROP TABLE IF EXISTS star_dim_hour;

CREATE TABLE star_dim_hour AS SELECT hour, in_analysis, label_es FROM ref_hour;
