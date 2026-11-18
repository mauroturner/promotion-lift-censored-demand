-- The bands of the discount, with the edges of [days] bands and the depth each one says in words.
DROP TABLE IF EXISTS star_dim_band;

CREATE TABLE star_dim_band AS SELECT band_key, discount_low, discount_high, depth_label_es FROM ref_band;
