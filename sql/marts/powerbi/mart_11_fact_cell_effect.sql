-- The lift of every cell by scope and version, with its interval and its place in the ranking (plan, section 19). The rows of the test week exist only once the week
-- closed at :as_of; the rank is the position by lift among the ranked cells of the scope and version. The indistinguishable group is the connected component of the overlap
-- graph (ref_overlap_group, from export.overlap_group_rows: RF15, D45); the tier is the one the seal holds, from the walk that compared a cell only with the open group (B1).
DROP TABLE IF EXISTS star_fact_cell_effect;

CREATE TABLE star_fact_cell_effect AS
SELECT e.scope, e.version AS version_key, e.unit_key AS cell_key, e.observed, e.counterfactual, e.lift, e.ci_low, e.ci_high, COALESCE(e.ci_kind, 'two_way') AS ci_kind, e.series,
       e.series_days, e.ranked,
       CASE WHEN e.ranked = 1 THEN ROW_NUMBER() OVER (PARTITION BY e.scope, e.version, e.ranked ORDER BY e.lift DESC, e.unit_key) END AS rank,
       e.tier, g.overlap_group, e.fit_blocks, CASE WHEN e.scope = 'test' THEN 'sealed' ELSE (SELECT launch_state FROM ref_seal) END AS seal_state
FROM effect_estimates AS e
LEFT JOIN ref_overlap_group AS g ON g.scope = e.scope AND g.version = e.version AND g.cell_key = e.unit_key AND e.ranked = 1
WHERE e.unit = 'cell' AND e.control = 'regular' AND (e.scope <> 'test' OR :test_closed = 1);
