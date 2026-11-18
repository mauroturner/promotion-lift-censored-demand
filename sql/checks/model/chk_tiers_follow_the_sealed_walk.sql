-- The tiers are the ones the seal holds (D45), from the walk of D13 as the plan wrote it: walking the ranked cells from the largest lift, a cell is in the open group if its
-- interval overlaps that of a cell already in it, and opens the next group otherwise. That walk is not RF15's rule (the evaluation's B1): the indistinguishable group is
-- overlap_group, checked by chk_overlap_groups_are_components. A violation is a cell that is not first in its tier and overlaps none of the earlier cells of the tier ('does_not_overlap'), or that is
-- first in a later tier and overlaps a cell of the tier before it ('overlaps_the_previous_tier').
WITH ranked AS (
    SELECT scope, version_key, cell_key, rank, tier, ci_low, ci_high FROM star_fact_cell_effect WHERE ranked = 1
)
SELECT c.scope, c.version_key, c.cell_key, c.tier, 'does_not_overlap' AS problem
FROM ranked AS c
WHERE EXISTS (SELECT 1 FROM ranked AS e WHERE e.scope = c.scope AND e.version_key = c.version_key AND e.tier = c.tier AND e.rank < c.rank)
  AND NOT EXISTS (SELECT 1 FROM ranked AS e WHERE e.scope = c.scope AND e.version_key = c.version_key AND e.tier = c.tier AND e.rank < c.rank
                  AND NOT (e.ci_high < c.ci_low OR c.ci_high < e.ci_low))
UNION ALL
SELECT c.scope, c.version_key, c.cell_key, c.tier, 'overlaps_the_previous_tier'
FROM ranked AS c
WHERE c.tier > 1
  AND NOT EXISTS (SELECT 1 FROM ranked AS e WHERE e.scope = c.scope AND e.version_key = c.version_key AND e.tier = c.tier AND e.rank < c.rank)
  AND EXISTS (SELECT 1 FROM ranked AS e WHERE e.scope = c.scope AND e.version_key = c.version_key AND e.tier = c.tier - 1 AND NOT (e.ci_high < c.ci_low OR c.ci_high < e.ci_low));
