-- The sealed lift of every cell of the launch next to the one of the test week, with the interval of their difference.
DROP TABLE IF EXISTS star_fact_replication;

CREATE TABLE star_fact_replication AS
SELECT cell_key, lift_launch, ci_low_launch, ci_high_launch, lift_test, ci_low_test, ci_high_test, diff_ci_low, diff_ci_high, consistent, seal_state
FROM eval_replication
WHERE :test_closed = 1;
