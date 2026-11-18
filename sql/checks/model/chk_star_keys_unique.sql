-- The key (the grain) of every table of the star model is unique and has no empty part (AC24). A violation is a table and a key that is repeated or has a null.
SELECT 'dim_date' AS table_name, COALESCE(CAST("date_key" AS TEXT), '<null>') AS grain_key, COUNT(*) AS copies FROM star_dim_date GROUP BY "date_key" HAVING COUNT(*) > 1 OR MAX("date_key" IS NULL) = 1
UNION ALL
SELECT 'dim_hour' AS table_name, COALESCE(CAST("hour" AS TEXT), '<null>') AS grain_key, COUNT(*) AS copies FROM star_dim_hour GROUP BY "hour" HAVING COUNT(*) > 1 OR MAX("hour" IS NULL) = 1
UNION ALL
SELECT 'dim_group' AS table_name, COALESCE(CAST("group_key" AS TEXT), '<null>') AS grain_key, COUNT(*) AS copies FROM star_dim_group GROUP BY "group_key" HAVING COUNT(*) > 1 OR MAX("group_key" IS NULL) = 1
UNION ALL
SELECT 'dim_band' AS table_name, COALESCE(CAST("band_key" AS TEXT), '<null>') AS grain_key, COUNT(*) AS copies FROM star_dim_band GROUP BY "band_key" HAVING COUNT(*) > 1 OR MAX("band_key" IS NULL) = 1
UNION ALL
SELECT 'dim_cell' AS table_name, COALESCE(CAST("cell_key" AS TEXT), '<null>') AS grain_key, COUNT(*) AS copies FROM star_dim_cell GROUP BY "cell_key" HAVING COUNT(*) > 1 OR MAX("cell_key" IS NULL) = 1
UNION ALL
SELECT 'dim_version' AS table_name, COALESCE(CAST("version_key" AS TEXT), '<null>') AS grain_key, COUNT(*) AS copies FROM star_dim_version GROUP BY "version_key" HAVING COUNT(*) > 1 OR MAX("version_key" IS NULL) = 1
UNION ALL
SELECT 'dim_method' AS table_name, COALESCE(CAST("method_key" AS TEXT), '<null>') AS grain_key, COUNT(*) AS copies FROM star_dim_method GROUP BY "method_key" HAVING COUNT(*) > 1 OR MAX("method_key" IS NULL) = 1
UNION ALL
SELECT 'dim_city' AS table_name, COALESCE(CAST("city_key" AS TEXT), '<null>') AS grain_key, COUNT(*) AS copies FROM star_dim_city GROUP BY "city_key" HAVING COUNT(*) > 1 OR MAX("city_key" IS NULL) = 1
UNION ALL
SELECT 'dim_model' AS table_name, COALESCE(CAST("model_key" AS TEXT), '<null>') AS grain_key, COUNT(*) AS copies FROM star_dim_model GROUP BY "model_key" HAVING COUNT(*) > 1 OR MAX("model_key" IS NULL) = 1
UNION ALL
SELECT 'dim_pipeline_run' AS table_name, COALESCE(CAST("run_key" AS TEXT), '<null>') AS grain_key, COUNT(*) AS copies FROM star_dim_pipeline_run GROUP BY "run_key" HAVING COUNT(*) > 1 OR MAX("run_key" IS NULL) = 1
UNION ALL
SELECT 'fact_cell_effect' AS table_name, COALESCE(CAST("scope" AS TEXT), '<null>') || '|' || COALESCE(CAST("version_key" AS TEXT), '<null>') || '|' || COALESCE(CAST("cell_key" AS TEXT), '<null>') || '|' || COALESCE(CAST("ci_kind" AS TEXT), '<null>') || '|' || COALESCE(CAST("seal_state" AS TEXT), '<null>') AS grain_key, COUNT(*) AS copies FROM star_fact_cell_effect GROUP BY "scope", "version_key", "cell_key", "ci_kind", "seal_state" HAVING COUNT(*) > 1 OR MAX("scope" IS NULL OR "version_key" IS NULL OR "cell_key" IS NULL OR "ci_kind" IS NULL OR "seal_state" IS NULL) = 1
UNION ALL
SELECT 'fact_band_effect' AS table_name, COALESCE(CAST("scope" AS TEXT), '<null>') || '|' || COALESCE(CAST("version_key" AS TEXT), '<null>') || '|' || COALESCE(CAST("band_key" AS TEXT), '<null>') || '|' || COALESCE(CAST("control" AS TEXT), '<null>') || '|' || COALESCE(CAST("day_state" AS TEXT), '<null>') || '|' || COALESCE(CAST("seal_state" AS TEXT), '<null>') AS grain_key, COUNT(*) AS copies FROM star_fact_band_effect GROUP BY "scope", "version_key", "band_key", "control", "day_state", "seal_state" HAVING COUNT(*) > 1 OR MAX("scope" IS NULL OR "version_key" IS NULL OR "band_key" IS NULL OR "control" IS NULL OR "day_state" IS NULL OR "seal_state" IS NULL) = 1
UNION ALL
SELECT 'fact_group_effect' AS table_name, COALESCE(CAST("scope" AS TEXT), '<null>') || '|' || COALESCE(CAST("version_key" AS TEXT), '<null>') || '|' || COALESCE(CAST("group_key" AS TEXT), '<null>') || '|' || COALESCE(CAST("seal_state" AS TEXT), '<null>') AS grain_key, COUNT(*) AS copies FROM star_fact_group_effect GROUP BY "scope", "version_key", "group_key", "seal_state" HAVING COUNT(*) > 1 OR MAX("scope" IS NULL OR "version_key" IS NULL OR "group_key" IS NULL OR "seal_state" IS NULL) = 1
UNION ALL
SELECT 'fact_overall_effect' AS table_name, COALESCE(CAST("scope" AS TEXT), '<null>') || '|' || COALESCE(CAST("version_key" AS TEXT), '<null>') || '|' || COALESCE(CAST("estimator" AS TEXT), '<null>') || '|' || COALESCE(CAST("control" AS TEXT), '<null>') || '|' || COALESCE(CAST("seal_state" AS TEXT), '<null>') AS grain_key, COUNT(*) AS copies FROM star_fact_overall_effect GROUP BY "scope", "version_key", "estimator", "control", "seal_state" HAVING COUNT(*) > 1 OR MAX("scope" IS NULL OR "version_key" IS NULL OR "estimator" IS NULL OR "control" IS NULL OR "seal_state" IS NULL) = 1
UNION ALL
SELECT 'fact_daily_cell' AS table_name, COALESCE(CAST("date_key" AS TEXT), '<null>') || '|' || COALESCE(CAST("version_key" AS TEXT), '<null>') || '|' || COALESCE(CAST("cell_key" AS TEXT), '<null>') AS grain_key, COUNT(*) AS copies FROM star_fact_daily_cell GROUP BY "date_key", "version_key", "cell_key" HAVING COUNT(*) > 1 OR MAX("date_key" IS NULL OR "version_key" IS NULL OR "cell_key" IS NULL) = 1
UNION ALL
SELECT 'fact_hour_profile' AS table_name, COALESCE(CAST("date_key" AS TEXT), '<null>') || '|' || COALESCE(CAST("group_key" AS TEXT), '<null>') || '|' || COALESCE(CAST("hour" AS TEXT), '<null>') || '|' || COALESCE(CAST("day_state" AS TEXT), '<null>') AS grain_key, COUNT(*) AS copies FROM star_fact_hour_profile GROUP BY "date_key", "group_key", "hour", "day_state" HAVING COUNT(*) > 1 OR MAX("date_key" IS NULL OR "group_key" IS NULL OR "hour" IS NULL OR "day_state" IS NULL) = 1
UNION ALL
SELECT 'fact_stockout_daily' AS table_name, COALESCE(CAST("date_key" AS TEXT), '<null>') || '|' || COALESCE(CAST("city_key" AS TEXT), '<null>') || '|' || COALESCE(CAST("group_key" AS TEXT), '<null>') AS grain_key, COUNT(*) AS copies FROM star_fact_stockout_daily GROUP BY "date_key", "city_key", "group_key" HAVING COUNT(*) > 1 OR MAX("date_key" IS NULL OR "city_key" IS NULL OR "group_key" IS NULL) = 1
UNION ALL
SELECT 'fact_recovery_check' AS table_name, COALESCE(CAST("scope" AS TEXT), '<null>') || '|' || COALESCE(CAST("mask" AS TEXT), '<null>') || '|' || COALESCE(CAST("method_key" AS TEXT), '<null>') || '|' || COALESCE(CAST("seal_state" AS TEXT), '<null>') AS grain_key, COUNT(*) AS copies FROM star_fact_recovery_check GROUP BY "scope", "mask", "method_key", "seal_state" HAVING COUNT(*) > 1 OR MAX("scope" IS NULL OR "mask" IS NULL OR "method_key" IS NULL OR "seal_state" IS NULL) = 1
UNION ALL
SELECT 'fact_forecast' AS table_name, COALESCE(CAST("scope" AS TEXT), '<null>') || '|' || COALESCE(CAST("method_key" AS TEXT), '<null>') || '|' || COALESCE(CAST("seal_state" AS TEXT), '<null>') AS grain_key, COUNT(*) AS copies FROM star_fact_forecast GROUP BY "scope", "method_key", "seal_state" HAVING COUNT(*) > 1 OR MAX("scope" IS NULL OR "method_key" IS NULL OR "seal_state" IS NULL) = 1
UNION ALL
SELECT 'fact_replication' AS table_name, COALESCE(CAST("cell_key" AS TEXT), '<null>') || '|' || COALESCE(CAST("seal_state" AS TEXT), '<null>') AS grain_key, COUNT(*) AS copies FROM star_fact_replication GROUP BY "cell_key", "seal_state" HAVING COUNT(*) > 1 OR MAX("cell_key" IS NULL OR "seal_state" IS NULL) = 1
UNION ALL
SELECT 'fact_evaluation_summary' AS table_name, COALESCE(CAST("criterion_id" AS TEXT), '<null>') || '|' || COALESCE(CAST("seal_state" AS TEXT), '<null>') AS grain_key, COUNT(*) AS copies FROM star_fact_evaluation_summary GROUP BY "criterion_id", "seal_state" HAVING COUNT(*) > 1 OR MAX("criterion_id" IS NULL OR "seal_state" IS NULL) = 1
UNION ALL
SELECT 'fact_example_day' AS table_name, COALESCE(CAST("hour" AS TEXT), '<null>') AS grain_key, COUNT(*) AS copies FROM star_fact_example_day GROUP BY "hour" HAVING COUNT(*) > 1 OR MAX("hour" IS NULL) = 1
UNION ALL
SELECT 'fact_leakage' AS table_name, COALESCE(CAST("check" AS TEXT), '<null>') AS grain_key, COUNT(*) AS copies FROM star_fact_leakage GROUP BY "check" HAVING COUNT(*) > 1 OR MAX("check" IS NULL) = 1
UNION ALL
SELECT 'fact_data_quality' AS table_name, COALESCE(CAST("date_key" AS TEXT), '<null>') AS grain_key, COUNT(*) AS copies FROM star_fact_data_quality GROUP BY "date_key" HAVING COUNT(*) > 1 OR MAX("date_key" IS NULL) = 1
UNION ALL
SELECT 'fact_validation' AS table_name, COALESCE(CAST("run_key" AS TEXT), '<null>') || '|' || COALESCE(CAST("rule_id" AS TEXT), '<null>') AS grain_key, COUNT(*) AS copies FROM star_fact_validation GROUP BY "run_key", "rule_id" HAVING COUNT(*) > 1 OR MAX("run_key" IS NULL OR "rule_id" IS NULL) = 1;
