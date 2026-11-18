-- The interval of an estimate contains the lift it surrounds (RF14): a violation is a row of the star model whose lift is outside its own interval, or whose limits are in the
-- wrong order. The naive account has no interval and is not checked.
SELECT 'fact_cell_effect' AS fact, scope || '|' || version_key || '|' || cell_key AS grain_key, lift, ci_low, ci_high
FROM star_fact_cell_effect
WHERE ci_low IS NOT NULL AND ci_high IS NOT NULL AND (ci_low > ci_high OR lift < ci_low OR lift > ci_high)
UNION ALL
SELECT 'fact_band_effect', scope || '|' || version_key || '|' || band_key || '|' || control || '|' || day_state, lift, ci_low, ci_high
FROM star_fact_band_effect
WHERE ci_low IS NOT NULL AND ci_high IS NOT NULL AND (ci_low > ci_high OR lift < ci_low OR lift > ci_high)
UNION ALL
SELECT 'fact_group_effect', scope || '|' || version_key || '|' || group_key, lift, ci_low, ci_high
FROM star_fact_group_effect
WHERE ci_low IS NOT NULL AND ci_high IS NOT NULL AND (ci_low > ci_high OR lift < ci_low OR lift > ci_high)
UNION ALL
SELECT 'fact_overall_effect', scope || '|' || version_key || '|' || estimator || '|' || control, lift, ci_low, ci_high
FROM star_fact_overall_effect
WHERE ci_low IS NOT NULL AND ci_high IS NOT NULL AND (ci_low > ci_high OR lift < ci_low OR lift > ci_high);
