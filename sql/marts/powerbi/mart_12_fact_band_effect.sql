-- The lift of every band of discount, and the lift of the days with a cut and no flag (their own effect, never the control). The variants of the test week add the
-- control with any day without the flag (plan, section 19).
DROP TABLE IF EXISTS star_fact_band_effect;

CREATE TABLE star_fact_band_effect AS
SELECT e.scope, e.version AS version_key, CAST(substr(e.unit_key, 2) AS INTEGER) AS band_key, e.control, e.lift, e.ci_low, e.ci_high, e.series, e.series_days,
       CASE e.unit WHEN 'band' THEN 'promo' ELSE 'unflagged_cut' END AS day_state, CASE WHEN e.scope = 'test' THEN 'sealed' ELSE (SELECT launch_state FROM ref_seal) END AS seal_state
FROM effect_estimates AS e
WHERE e.unit IN ('band', 'unflagged_band') AND e.control = 'regular' AND (e.scope <> 'test' OR :test_closed = 1)
UNION ALL
SELECT 'test', substr(v.unit_key, 1, instr(v.unit_key, ':') - 1), CAST(substr(v.unit_key, instr(v.unit_key, ':') + 2) AS INTEGER), 'any_flag0', v.value, v.ci_low, v.ci_high,
       v.series, v.series_days, 'promo', v.seal_state
FROM eval_variants AS v
WHERE v.variant = 'control_any_flag0' AND v.unit_key LIKE '%:b%' AND :test_closed = 1
UNION ALL
SELECT 'test', substr(v.unit_key, 1, instr(v.unit_key, ':') - 1), CAST(substr(v.unit_key, instr(v.unit_key, ':') + 2) AS INTEGER), 'regular', v.value, v.ci_low, v.ci_high,
       v.series, v.series_days, 'unflagged_cut', v.seal_state
FROM eval_variants AS v
WHERE v.variant = 'unflagged_band' AND v.unit_key LIKE '%:b%' AND :test_closed = 1;
