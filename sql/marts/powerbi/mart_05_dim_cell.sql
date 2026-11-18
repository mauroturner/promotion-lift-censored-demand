-- The cells: every management group with every band (the dimension carries both as columns, so there is no snowflake).
DROP TABLE IF EXISTS star_dim_cell;

CREATE TABLE star_dim_cell AS
SELECT 'g' || g.group_key || '-b' || b.band_key AS cell_key, g.group_key, b.band_key, g.label_es || ', rebaja de ' || b.depth_label_es AS label_es
FROM star_dim_group AS g
CROSS JOIN star_dim_band AS b;
