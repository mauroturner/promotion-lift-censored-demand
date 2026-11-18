-- The demonstration of the leak: what a recovery that reads the daily total would give next to the honest ones.
DROP TABLE IF EXISTS star_fact_leakage;

CREATE TABLE star_fact_leakage AS SELECT "check", check_es, value, note_es FROM eval_leakage;
