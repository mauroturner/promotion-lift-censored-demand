-- The lift of every cell by scope and version, with its interval and its place in the ranking (plan, section 19). The rows of the test week exist only once the week
-- closed at :as_of; the rank is the position by lift among the ranked cells of the scope and version. The tier is the indistinguishable group the launch stored.
DROP TABLE IF EXISTS star_fact_cell_effect;

CREATE TABLE star_fact_cell_effect AS
SELECT e.scope, e.version AS version_key, e.unit_key AS cell_key, e.observed, e.counterfactual, e.lift, e.ci_low, e.ci_high, COALESCE(e.ci_kind, 'two_way') AS ci_kind, e.series,
       e.series_days, e.ranked,
       CASE WHEN e.ranked = 1 THEN ROW_NUMBER() OVER (PARTITION BY e.scope, e.version, e.ranked ORDER BY e.lift DESC, e.unit_key) END AS rank,
       e.tier, e.fit_blocks, CASE WHEN e.scope = 'test' THEN 'sealed' ELSE (SELECT launch_state FROM ref_seal) END AS seal_state
FROM effect_estimates AS e
WHERE e.unit = 'cell' AND e.control = 'regular' AND (e.scope <> 'test' OR :test_closed = 1);
