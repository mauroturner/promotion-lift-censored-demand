-- The total lift: the account that goes wrong (the pooled mean of the promo series-days over the regular ones) next to the counterfactual of the same series and hour, and
-- the variant with any day without the flag as the control (the test week).
DROP TABLE IF EXISTS star_fact_overall_effect;

CREATE TABLE star_fact_overall_effect AS
SELECT e.scope, e.version AS version_key, CASE e.unit WHEN 'naive_pooled' THEN 'naive_pooled' ELSE 'counterfactual' END AS estimator, e.control, e.lift, e.ci_low, e.ci_high,
       e.series_days, CASE WHEN e.scope = 'test' THEN 'sealed' ELSE (SELECT launch_state FROM ref_seal) END AS seal_state
FROM effect_estimates AS e
WHERE e.unit IN ('overall', 'naive_pooled') AND (e.scope <> 'test' OR :test_closed = 1)
UNION ALL
SELECT 'test', substr(v.unit_key, 1, instr(v.unit_key, ':') - 1), 'counterfactual', 'any_flag0', v.value, v.ci_low, v.ci_high, v.series_days, v.seal_state
FROM eval_variants AS v
WHERE v.variant = 'control_any_flag0' AND v.unit_key LIKE '%:all' AND :test_closed = 1;
