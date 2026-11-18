-- The evaluation of the test week (plan, sections 5 and 16; RF18, D16, D17, D21): the criteria with their verdicts, the replication of every cell, the forecast
-- errors, the variants, the pairs of cells whose intervals overlap and the demonstration of the leak. ``seal_state`` says whether a row is the sealed result
-- (``sealed``: written once, with the configuration of the seal) or the analysis of another configuration (``post_seal``: it never replaces the sealed one and
-- is replaced by the next post-seal analysis). A sealed row cannot be updated, deleted or inserted twice, whoever writes (three triggers per table, as in
-- 002_effects.sql: the leak and the pairs have no post-seal state and are insert-only altogether).

CREATE TABLE IF NOT EXISTS eval_criteria (
    criterion_id TEXT NOT NULL CHECK (criterion_id IN ('C01', 'C02', 'C03', 'C04', 'C05', 'C06', 'C07', 'C08', 'C09', 'C10')),
    seal_state TEXT NOT NULL CHECK (seal_state IN ('sealed', 'post_seal')),
    name_es TEXT NOT NULL,
    value REAL,
    baseline_value REAL,
    ci_low REAL,
    ci_high REAL,
    threshold_es TEXT NOT NULL,
    passed INTEGER CHECK (passed IS NULL OR passed IN (0, 1)),      -- NULL: C10 is informative
    seen_by_research TEXT NOT NULL,
    seen_by_planner TEXT NOT NULL,
    verdict_es TEXT NOT NULL,
    run_key TEXT NOT NULL,
    PRIMARY KEY (criterion_id, seal_state)
);

CREATE TABLE IF NOT EXISTS eval_replication (
    cell_key TEXT NOT NULL,
    seal_state TEXT NOT NULL CHECK (seal_state IN ('sealed', 'post_seal')),
    series_launch INTEGER NOT NULL,
    series_test INTEGER NOT NULL,
    lift_launch REAL,
    ci_low_launch REAL,
    ci_high_launch REAL,
    lift_test REAL,
    ci_low_test REAL,
    ci_high_test REAL,
    diff_ci_low REAL,                    -- the interval of the difference test - sealed, only for a cell with at least min_series series in both
    diff_ci_high REAL,
    consistent INTEGER CHECK (consistent IS NULL OR consistent IN (0, 1)),
    run_key TEXT NOT NULL,
    PRIMARY KEY (cell_key, seal_state)
);

CREATE TABLE IF NOT EXISTS eval_forecast (
    method TEXT NOT NULL CHECK (method IN ('f0_no_lift', 'f1_naive', 'f2a_overall_lift', 'f2_cell_lift')),
    seal_state TEXT NOT NULL CHECK (seal_state IN ('sealed', 'post_seal')),
    fit_blocks TEXT NOT NULL CHECK (length(fit_blocks) > 0),
    wape REAL NOT NULL,
    bias REAL NOT NULL,
    series_days INTEGER NOT NULL,
    run_key TEXT NOT NULL,
    PRIMARY KEY (method, seal_state)
);

CREATE TABLE IF NOT EXISTS eval_variants (
    variant TEXT NOT NULL CHECK (variant IN ('control_any_flag0', 'series_only_intervals', 'mcar_mask', 'unflagged_band', 'first_category_cell', 'per_day_band')),
    unit_key TEXT NOT NULL,              -- what was measured, e.g. 'recovered:g1-b2' or 'r2@0.25:wape'
    seal_state TEXT NOT NULL CHECK (seal_state IN ('sealed', 'post_seal')),
    value REAL,
    ci_low REAL,
    ci_high REAL,
    series INTEGER,
    series_days INTEGER,
    run_key TEXT NOT NULL,
    PRIMARY KEY (variant, unit_key, seal_state)
);

CREATE TABLE IF NOT EXISTS eval_pairs (
    scope TEXT NOT NULL CHECK (scope IN ('launch', 'test')),
    ci_kind TEXT NOT NULL CHECK (ci_kind IN ('two_way', 'series_only')),
    cells INTEGER NOT NULL,              -- the cells that were ranked
    pairs INTEGER NOT NULL,
    overlapping INTEGER NOT NULL,
    median_width REAL,
    run_key TEXT NOT NULL,
    PRIMARY KEY (scope, ci_kind)
);

CREATE TABLE IF NOT EXISTS eval_leakage (
    "check" TEXT PRIMARY KEY,
    check_es TEXT NOT NULL,
    value REAL NOT NULL,                 -- the WAPE of the mass per series on the V2 mask of the launch
    note_es TEXT NOT NULL,
    run_key TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS eval_criteria_no_update BEFORE UPDATE ON eval_criteria WHEN OLD.seal_state = 'sealed'
BEGIN SELECT RAISE(ABORT, 'eval_criteria es de solo inserción: un criterio sellado no se cambia'); END;

CREATE TRIGGER IF NOT EXISTS eval_criteria_no_delete BEFORE DELETE ON eval_criteria WHEN OLD.seal_state = 'sealed'
BEGIN SELECT RAISE(ABORT, 'eval_criteria es de solo inserción: un criterio sellado no se borra'); END;

CREATE TRIGGER IF NOT EXISTS eval_criteria_no_second_insert BEFORE INSERT ON eval_criteria
WHEN NEW.seal_state = 'sealed' AND EXISTS (SELECT 1 FROM eval_criteria WHERE criterion_id = NEW.criterion_id AND seal_state = 'sealed')
BEGIN SELECT RAISE(ABORT, 'eval_criteria es de solo inserción: ese criterio ya se selló'); END;

CREATE TRIGGER IF NOT EXISTS eval_replication_no_update BEFORE UPDATE ON eval_replication WHEN OLD.seal_state = 'sealed'
BEGIN SELECT RAISE(ABORT, 'eval_replication es de solo inserción: una réplica sellada no se cambia'); END;

CREATE TRIGGER IF NOT EXISTS eval_replication_no_delete BEFORE DELETE ON eval_replication WHEN OLD.seal_state = 'sealed'
BEGIN SELECT RAISE(ABORT, 'eval_replication es de solo inserción: una réplica sellada no se borra'); END;

CREATE TRIGGER IF NOT EXISTS eval_replication_no_second_insert BEFORE INSERT ON eval_replication
WHEN NEW.seal_state = 'sealed' AND EXISTS (SELECT 1 FROM eval_replication WHERE cell_key = NEW.cell_key AND seal_state = 'sealed')
BEGIN SELECT RAISE(ABORT, 'eval_replication es de solo inserción: esa réplica ya se selló'); END;

CREATE TRIGGER IF NOT EXISTS eval_forecast_no_update BEFORE UPDATE ON eval_forecast WHEN OLD.seal_state = 'sealed'
BEGIN SELECT RAISE(ABORT, 'eval_forecast es de solo inserción: un error de pronóstico sellado no se cambia'); END;

CREATE TRIGGER IF NOT EXISTS eval_forecast_no_delete BEFORE DELETE ON eval_forecast WHEN OLD.seal_state = 'sealed'
BEGIN SELECT RAISE(ABORT, 'eval_forecast es de solo inserción: un error de pronóstico sellado no se borra'); END;

CREATE TRIGGER IF NOT EXISTS eval_forecast_no_second_insert BEFORE INSERT ON eval_forecast
WHEN NEW.seal_state = 'sealed' AND EXISTS (SELECT 1 FROM eval_forecast WHERE method = NEW.method AND seal_state = 'sealed')
BEGIN SELECT RAISE(ABORT, 'eval_forecast es de solo inserción: ese error de pronóstico ya se selló'); END;

CREATE TRIGGER IF NOT EXISTS eval_variants_no_update BEFORE UPDATE ON eval_variants WHEN OLD.seal_state = 'sealed'
BEGIN SELECT RAISE(ABORT, 'eval_variants es de solo inserción: una variante sellada no se cambia'); END;

CREATE TRIGGER IF NOT EXISTS eval_variants_no_delete BEFORE DELETE ON eval_variants WHEN OLD.seal_state = 'sealed'
BEGIN SELECT RAISE(ABORT, 'eval_variants es de solo inserción: una variante sellada no se borra'); END;

CREATE TRIGGER IF NOT EXISTS eval_variants_no_second_insert BEFORE INSERT ON eval_variants
WHEN NEW.seal_state = 'sealed' AND EXISTS (SELECT 1 FROM eval_variants WHERE variant = NEW.variant AND unit_key = NEW.unit_key AND seal_state = 'sealed')
BEGIN SELECT RAISE(ABORT, 'eval_variants es de solo inserción: esa variante ya se selló'); END;

CREATE TRIGGER IF NOT EXISTS eval_pairs_no_update BEFORE UPDATE ON eval_pairs
BEGIN SELECT RAISE(ABORT, 'eval_pairs es de solo inserción: el recuento de pares que se pisan no se cambia'); END;

CREATE TRIGGER IF NOT EXISTS eval_pairs_no_delete BEFORE DELETE ON eval_pairs
BEGIN SELECT RAISE(ABORT, 'eval_pairs es de solo inserción: el recuento de pares que se pisan no se borra'); END;

CREATE TRIGGER IF NOT EXISTS eval_pairs_no_second_insert BEFORE INSERT ON eval_pairs
WHEN EXISTS (SELECT 1 FROM eval_pairs WHERE scope = NEW.scope AND ci_kind = NEW.ci_kind)
BEGIN SELECT RAISE(ABORT, 'eval_pairs es de solo inserción: ese recuento ya se escribió'); END;

CREATE TRIGGER IF NOT EXISTS eval_leakage_no_update BEFORE UPDATE ON eval_leakage
BEGIN SELECT RAISE(ABORT, 'eval_leakage es de solo inserción: la demostración de la fuga no se cambia'); END;

CREATE TRIGGER IF NOT EXISTS eval_leakage_no_delete BEFORE DELETE ON eval_leakage
BEGIN SELECT RAISE(ABORT, 'eval_leakage es de solo inserción: la demostración de la fuga no se borra'); END;

CREATE TRIGGER IF NOT EXISTS eval_leakage_no_second_insert BEFORE INSERT ON eval_leakage
WHEN EXISTS (SELECT 1 FROM eval_leakage WHERE "check" = NEW."check")
BEGIN SELECT RAISE(ABORT, 'eval_leakage es de solo inserción: esa comprobación ya se escribió'); END;
