-- The criteria C01 to C10 of the test week with their verdicts.
DROP TABLE IF EXISTS star_fact_evaluation_summary;

CREATE TABLE star_fact_evaluation_summary AS
SELECT criterion_id, name_es, value, baseline_value, ci_low, ci_high, threshold_es, passed, seen_by_research, seen_by_planner, verdict_es, seal_state
FROM eval_criteria
WHERE :test_closed = 1;
