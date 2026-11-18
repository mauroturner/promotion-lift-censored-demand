-- The result of every rule in every run: a blocking rule that does not pass is «falla»; a warning or an informative one that does not pass only «advierte».
DROP TABLE IF EXISTS star_fact_validation;

CREATE TABLE star_fact_validation AS
SELECT run_key, rule_id, name_es,
       CASE severity WHEN 'blocking' THEN 'bloqueante' WHEN 'warning' THEN 'advertencia' ELSE 'informativa' END AS severity, scope, aggregation,
       CASE WHEN passed = 1 THEN 'pasa' WHEN severity = 'blocking' THEN 'falla' ELSE 'advierte' END AS status, series_days_affected, hours_affected
FROM validation_results;
