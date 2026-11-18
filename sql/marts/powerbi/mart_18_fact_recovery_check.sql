-- The check of the recovery on hours that are hidden on purpose: the methods fitted on the training block in V1 and V2, and on the 90 days in the test week, on the tail
-- mask and (the test week) on three hours at random. A row says with which blocks its method was fitted.
DROP TABLE IF EXISTS star_fact_recovery_check;

CREATE TABLE star_fact_recovery_check AS
SELECT r.scope, r.mask, r.method AS method_key, r.fit_blocks, r.wape_series, r.bias, r.bias_promo, r.bias_regular, r.lift_bias, r.ci_low_vs_r1, r.ci_high_vs_r1,
       CASE WHEN r.method = json_extract((SELECT recovery_json FROM model_registry LIMIT 1), '$.name') THEN 1 ELSE 0 END AS chosen,
       CASE WHEN r.scope = 'test' THEN 'sealed' ELSE (SELECT launch_state FROM ref_seal) END AS seal_state
FROM recovery_checks AS r
WHERE r.scope <> 'test' OR :test_closed = 1
UNION ALL
SELECT 'test', 'mcar', substr(w.unit_key, 1, instr(w.unit_key, ':') - 1), (SELECT fit_blocks FROM recovery_checks WHERE scope = 'test' LIMIT 1), w.value, b.value, NULL, NULL, NULL, NULL, NULL,
       CASE WHEN substr(w.unit_key, 1, instr(w.unit_key, ':') - 1) = json_extract((SELECT recovery_json FROM model_registry LIMIT 1), '$.name') THEN 1 ELSE 0 END, w.seal_state
FROM eval_variants AS w
LEFT JOIN eval_variants AS b ON b.variant = 'mcar_mask' AND b.seal_state = w.seal_state AND b.unit_key = substr(w.unit_key, 1, instr(w.unit_key, ':')) || 'bias'
WHERE w.variant = 'mcar_mask' AND w.unit_key LIKE '%:wape' AND :test_closed = 1;
