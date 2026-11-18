-- The indistinguishable groups are the connected components of the overlap graph of the ranked cells of a scope and version (RF15, D45). A violation is a ranked cell
-- without a group or an unranked one with a group ('group_without_rank'), two overlapping cells in different groups ('overlapping_cells_apart'), a cell of a group that
-- no cell before it in the order of the low limits reaches ('group_not_connected'), or a group numbered against the order of the lifts ('groups_out_of_order').
WITH ranked AS (
    SELECT scope, version_key, cell_key, rank, overlap_group, ci_low, ci_high FROM star_fact_cell_effect WHERE ranked = 1
)
SELECT scope, version_key, cell_key, overlap_group, 'group_without_rank' AS problem
FROM star_fact_cell_effect
WHERE (ranked = 1 AND overlap_group IS NULL) OR (ranked = 0 AND overlap_group IS NOT NULL)
UNION ALL
SELECT c.scope, c.version_key, c.cell_key, c.overlap_group, 'overlapping_cells_apart'
FROM ranked AS c
JOIN ranked AS e ON e.scope = c.scope AND e.version_key = c.version_key AND e.cell_key < c.cell_key
WHERE NOT (e.ci_high < c.ci_low OR c.ci_high < e.ci_low) AND e.overlap_group IS NOT c.overlap_group
UNION ALL
SELECT c.scope, c.version_key, c.cell_key, c.overlap_group, 'group_not_connected'
FROM ranked AS c
WHERE EXISTS (SELECT 1 FROM ranked AS e WHERE e.scope = c.scope AND e.version_key = c.version_key AND e.overlap_group = c.overlap_group
              AND (e.ci_low < c.ci_low OR (e.ci_low = c.ci_low AND e.cell_key < c.cell_key)))
  AND NOT EXISTS (SELECT 1 FROM ranked AS e WHERE e.scope = c.scope AND e.version_key = c.version_key AND e.overlap_group = c.overlap_group
                  AND (e.ci_low < c.ci_low OR (e.ci_low = c.ci_low AND e.cell_key < c.cell_key)) AND e.ci_high >= c.ci_low)
UNION ALL
SELECT c.scope, c.version_key, c.cell_key, c.overlap_group, 'groups_out_of_order'
FROM ranked AS c
WHERE (c.rank = 1 AND c.overlap_group <> 1)
   OR EXISTS (SELECT 1 FROM ranked AS e WHERE e.scope = c.scope AND e.version_key = c.version_key AND e.rank < c.rank AND e.overlap_group > c.overlap_group)
   OR (c.overlap_group > 1 AND NOT EXISTS (SELECT 1 FROM ranked AS f WHERE f.scope = c.scope AND f.version_key = c.version_key AND f.overlap_group = c.overlap_group - 1));
