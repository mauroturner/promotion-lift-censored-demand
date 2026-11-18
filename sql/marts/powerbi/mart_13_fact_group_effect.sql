-- The lift of every management group by scope and version.
DROP TABLE IF EXISTS star_fact_group_effect;

CREATE TABLE star_fact_group_effect AS
SELECT e.scope, e.version AS version_key, CAST(substr(e.unit_key, 2) AS INTEGER) AS group_key, e.lift, e.ci_low, e.ci_high, e.series,
       CASE WHEN e.scope = 'test' THEN 'sealed' ELSE (SELECT launch_state FROM ref_seal) END AS seal_state
FROM effect_estimates AS e
WHERE e.unit = 'group' AND e.control = 'regular' AND (e.scope <> 'test' OR :test_closed = 1);
