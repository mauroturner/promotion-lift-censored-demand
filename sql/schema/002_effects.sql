-- What the model said and when (plan, section 5; D17, D18, D20, D21): the registry of the frozen model, the validation of the recovery, the effects, the daily
-- cells, the forecasts and the synthetic masks of the test days, each issued once.
-- Every table here is insert-only: three triggers refuse, in the database itself and whoever writes, an update, a delete and a second insert of a key that is
-- already there (INSERT OR REPLACE and an upsert included: the trigger of the insert fires before the conflict is resolved), so a model that was frozen or a figure that
-- was issued cannot be rebuilt (item 1 of the risks of the plan). Instants are text 'YYYY-MM-DD HH:MM:SS'. ``fit_blocks`` says with which blocks of the split
-- the method behind a figure was fitted (D21): a figure of a block is never fitted with that block and shown as out of sample.

CREATE TABLE IF NOT EXISTS model_registry (
    model_version TEXT PRIMARY KEY,
    trained_as_of TEXT NOT NULL,
    artifact_name TEXT NOT NULL,         -- the file name inside [paths] models_dir, never a path of this machine
    artifact_sha256 TEXT NOT NULL CHECK (length(artifact_sha256) = 64),
    r3_name TEXT,
    r3_sha256 TEXT CHECK (r3_sha256 IS NULL OR length(r3_sha256) = 64),
    config_sha256 TEXT NOT NULL CHECK (length(config_sha256) = 64),
    recovery_json TEXT NOT NULL,         -- the method and kappa chosen, the error of every candidate in V1 and V2, the seal state
    validation_digest TEXT NOT NULL CHECK (length(validation_digest) = 64)
);

CREATE TABLE IF NOT EXISTS recovery_checks (
    scope TEXT NOT NULL CHECK (scope IN ('valid_v1', 'valid_v2', 'test')),
    mask TEXT NOT NULL CHECK (mask IN ('tail', 'mcar')),
    method TEXT NOT NULL,                -- r0, r1, r2@<kappa>, r3
    fit_blocks TEXT NOT NULL CHECK (length(fit_blocks) > 0),
    series INTEGER NOT NULL,
    masked_days INTEGER NOT NULL,
    hidden_hours INTEGER NOT NULL,
    hidden_mass REAL NOT NULL,
    wape_series REAL NOT NULL,
    bias REAL NOT NULL,
    bias_promo REAL,
    bias_regular REAL,
    lift_bias REAL,
    ci_low_vs_r1 REAL,
    ci_high_vs_r1 REAL,
    PRIMARY KEY (scope, mask, method)
);

CREATE TABLE IF NOT EXISTS effect_estimates (
    scope TEXT NOT NULL CHECK (scope IN ('launch', 'valid_replication', 'test')),
    version TEXT NOT NULL CHECK (version IN ('raw', 'recovered')),
    unit TEXT NOT NULL CHECK (unit IN ('overall', 'cell', 'band', 'group', 'first_category_cell', 'unflagged_band', 'naive_pooled')),
    unit_key TEXT NOT NULL,
    control TEXT NOT NULL CHECK (control IN ('regular', 'any_flag0')),
    fit_blocks TEXT NOT NULL CHECK (length(fit_blocks) > 0),
    observed REAL,
    counterfactual REAL,
    lift REAL,
    ci_low REAL,
    ci_high REAL,
    ci_kind TEXT CHECK (ci_kind IS NULL OR ci_kind IN ('two_way', 'series_only')),
    series INTEGER NOT NULL,
    series_days INTEGER NOT NULL,
    ranked INTEGER NOT NULL CHECK (ranked IN (0, 1)),
    tier INTEGER,
    PRIMARY KEY (scope, version, unit, unit_key, control)
);

CREATE TABLE IF NOT EXISTS daily_cell (
    date_key INTEGER NOT NULL,
    version TEXT NOT NULL CHECK (version IN ('raw', 'recovered')),
    cell_key TEXT NOT NULL,              -- 'all', 'b<band>' or 'g<group>-b<band>'
    observed REAL NOT NULL,
    counterfactual REAL NOT NULL,
    lift REAL,
    series_days INTEGER NOT NULL,
    stockout_hours INTEGER NOT NULL,
    run_key TEXT NOT NULL,
    PRIMARY KEY (date_key, version, cell_key)
);

CREATE TABLE IF NOT EXISTS forecasts (
    series_key INTEGER NOT NULL REFERENCES series (series_key),
    date_key INTEGER NOT NULL,
    method TEXT NOT NULL CHECK (method IN ('f0_no_lift', 'f1_naive', 'f2a_overall_lift', 'f2_cell_lift')),
    forecast REAL NOT NULL,
    observed_instock REAL NOT NULL,
    scope TEXT NOT NULL CHECK (scope IN ('valid', 'test')),
    run_key TEXT NOT NULL,
    PRIMARY KEY (series_key, date_key, method)
);

CREATE TABLE IF NOT EXISTS mask_checks (
    series_key INTEGER NOT NULL REFERENCES series (series_key),
    date_key INTEGER NOT NULL,
    method TEXT NOT NULL,                -- r0, r1, r2@<kappa>, r3
    cut_hour INTEGER NOT NULL,
    hidden_mass REAL NOT NULL,
    estimate REAL NOT NULL,
    day_state TEXT NOT NULL CHECK (day_state IN ('promo', 'regular')),
    run_key TEXT NOT NULL,
    PRIMARY KEY (series_key, date_key, method)
);

CREATE TRIGGER IF NOT EXISTS model_registry_no_update BEFORE UPDATE ON model_registry
BEGIN SELECT RAISE(ABORT, 'model_registry es de solo inserción: una versión del modelo registrada no se cambia'); END;

CREATE TRIGGER IF NOT EXISTS model_registry_no_delete BEFORE DELETE ON model_registry
BEGIN SELECT RAISE(ABORT, 'model_registry es de solo inserción: una versión del modelo registrada no se borra'); END;

CREATE TRIGGER IF NOT EXISTS model_registry_no_second_insert BEFORE INSERT ON model_registry
WHEN EXISTS (SELECT 1 FROM model_registry WHERE model_version = NEW.model_version)
BEGIN SELECT RAISE(ABORT, 'model_registry es de solo inserción: esa versión del modelo ya está registrada'); END;

CREATE TRIGGER IF NOT EXISTS recovery_checks_no_update BEFORE UPDATE ON recovery_checks
BEGIN SELECT RAISE(ABORT, 'recovery_checks es de solo inserción: una cifra de validación emitida no se cambia'); END;

CREATE TRIGGER IF NOT EXISTS recovery_checks_no_delete BEFORE DELETE ON recovery_checks
BEGIN SELECT RAISE(ABORT, 'recovery_checks es de solo inserción: una cifra de validación emitida no se borra'); END;

CREATE TRIGGER IF NOT EXISTS recovery_checks_no_second_insert BEFORE INSERT ON recovery_checks
WHEN EXISTS (SELECT 1 FROM recovery_checks WHERE scope = NEW.scope AND mask = NEW.mask AND method = NEW.method)
BEGIN SELECT RAISE(ABORT, 'recovery_checks es de solo inserción: esa cifra ya se emitió'); END;

CREATE TRIGGER IF NOT EXISTS effect_estimates_no_update BEFORE UPDATE ON effect_estimates
BEGIN SELECT RAISE(ABORT, 'effect_estimates es de solo inserción: un efecto emitido no se cambia'); END;

CREATE TRIGGER IF NOT EXISTS effect_estimates_no_delete BEFORE DELETE ON effect_estimates
BEGIN SELECT RAISE(ABORT, 'effect_estimates es de solo inserción: un efecto emitido no se borra'); END;

CREATE TRIGGER IF NOT EXISTS effect_estimates_no_second_insert BEFORE INSERT ON effect_estimates
WHEN EXISTS (SELECT 1 FROM effect_estimates WHERE scope = NEW.scope AND version = NEW.version AND unit = NEW.unit AND unit_key = NEW.unit_key AND control = NEW.control)
BEGIN SELECT RAISE(ABORT, 'effect_estimates es de solo inserción: ese efecto ya se emitió'); END;

CREATE TRIGGER IF NOT EXISTS daily_cell_no_update BEFORE UPDATE ON daily_cell
BEGIN SELECT RAISE(ABORT, 'daily_cell es de solo inserción: el efecto de un día emitido no se cambia'); END;

CREATE TRIGGER IF NOT EXISTS daily_cell_no_delete BEFORE DELETE ON daily_cell
BEGIN SELECT RAISE(ABORT, 'daily_cell es de solo inserción: el efecto de un día emitido no se borra'); END;

CREATE TRIGGER IF NOT EXISTS daily_cell_no_second_insert BEFORE INSERT ON daily_cell
WHEN EXISTS (SELECT 1 FROM daily_cell WHERE date_key = NEW.date_key AND version = NEW.version AND cell_key = NEW.cell_key)
BEGIN SELECT RAISE(ABORT, 'daily_cell es de solo inserción: ese efecto del día ya se emitió'); END;

CREATE TRIGGER IF NOT EXISTS forecasts_no_update BEFORE UPDATE ON forecasts
BEGIN SELECT RAISE(ABORT, 'forecasts es de solo inserción: un pronóstico emitido no se cambia'); END;

CREATE TRIGGER IF NOT EXISTS forecasts_no_delete BEFORE DELETE ON forecasts
BEGIN SELECT RAISE(ABORT, 'forecasts es de solo inserción: un pronóstico emitido no se borra'); END;

CREATE TRIGGER IF NOT EXISTS forecasts_no_second_insert BEFORE INSERT ON forecasts
WHEN EXISTS (SELECT 1 FROM forecasts WHERE series_key = NEW.series_key AND date_key = NEW.date_key AND method = NEW.method)
BEGIN SELECT RAISE(ABORT, 'forecasts es de solo inserción: ese pronóstico ya se emitió'); END;

CREATE TRIGGER IF NOT EXISTS mask_checks_no_update BEFORE UPDATE ON mask_checks
BEGIN SELECT RAISE(ABORT, 'mask_checks es de solo inserción: lo que estimó un método sobre una máscara no se cambia'); END;

CREATE TRIGGER IF NOT EXISTS mask_checks_no_delete BEFORE DELETE ON mask_checks
BEGIN SELECT RAISE(ABORT, 'mask_checks es de solo inserción: lo que estimó un método sobre una máscara no se borra'); END;

CREATE TRIGGER IF NOT EXISTS mask_checks_no_second_insert BEFORE INSERT ON mask_checks
WHEN EXISTS (SELECT 1 FROM mask_checks WHERE series_key = NEW.series_key AND date_key = NEW.date_key AND method = NEW.method)
BEGIN SELECT RAISE(ABORT, 'mask_checks es de solo inserción: esa estimación de la máscara ya se guardó'); END;
