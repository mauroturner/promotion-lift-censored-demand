-- The runs of the pipeline, as the warehouse recorded them.
DROP TABLE IF EXISTS star_dim_pipeline_run;

CREATE TABLE star_dim_pipeline_run AS
SELECT run_key, started_at, finished_at, status, delivery_id, as_of, train_sha256, eval_sha256, series_days_delivery, rows_issued, peak_working_set_mb, peak_commit_mb,
       memory_counter, message
FROM pipeline_runs;
