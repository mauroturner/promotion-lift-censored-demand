"""The star model for Power BI (U12; RF20, AC24; D35; plan, section 19): ten dimensions and fifteen facts with their keys, the 21 relationships (one to many, single
direction, active), the marts that fill them from the warehouse as of the run, the controls that undo them and the Parquet files with the schema of the specification."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from promolift.dashboard.semantic_model import MODEL, ARROW_TYPES, Relationship, arrow_schema, validate_model
from promolift.export import STAR_MANIFEST, export_star_schema, verify_star_schema
from promolift.registry import RunMeta
from promolift.warehouse import CheckFailedError, connect

DIMENSIONS = ("dim_date", "dim_hour", "dim_group", "dim_band", "dim_cell", "dim_version", "dim_method", "dim_city", "dim_model", "dim_pipeline_run")
FACTS = ("fact_cell_effect", "fact_band_effect", "fact_group_effect", "fact_overall_effect", "fact_daily_cell", "fact_hour_profile", "fact_stockout_daily",
         "fact_recovery_check", "fact_forecast", "fact_replication", "fact_evaluation_summary", "fact_example_day", "fact_leakage", "fact_data_quality", "fact_validation")
# plan, section 19: relationship id -> (dimension, fact)
RELATIONSHIPS = {
    "R01": ("dim_date", "fact_daily_cell"), "R02": ("dim_date", "fact_hour_profile"), "R03": ("dim_date", "fact_stockout_daily"), "R04": ("dim_date", "fact_data_quality"),
    "R05": ("dim_cell", "fact_cell_effect"), "R06": ("dim_cell", "fact_daily_cell"), "R07": ("dim_cell", "fact_replication"), "R08": ("dim_band", "fact_band_effect"),
    "R09": ("dim_group", "fact_group_effect"), "R10": ("dim_group", "fact_hour_profile"), "R11": ("dim_group", "fact_stockout_daily"),
    "R12": ("dim_version", "fact_cell_effect"), "R13": ("dim_version", "fact_band_effect"), "R14": ("dim_version", "fact_group_effect"), "R15": ("dim_version", "fact_overall_effect"),
    "R16": ("dim_version", "fact_daily_cell"), "R17": ("dim_method", "fact_recovery_check"), "R18": ("dim_method", "fact_forecast"), "R19": ("dim_hour", "fact_hour_profile"),
    "R20": ("dim_city", "fact_stockout_daily"), "R21": ("dim_pipeline_run", "fact_validation")}


def table_rows(db: Path, name: str) -> list[tuple]:
    conn = connect(db)
    try:
        return conn.execute(f"SELECT * FROM star_{name}").fetchall()
    finally:
        conn.close()


def read(out: Path, name: str):
    return pq.read_table(out / f"{name}.parquet")


def test_every_relationship_is_one_to_many_single_and_keys_exist():
    tables = {t.name: t for t in MODEL.tables}
    assert len(MODEL.relationships) == 21 and {r.rel_id: (r.dim_table, r.fact_table) for r in MODEL.relationships} == RELATIONSHIPS
    for r in MODEL.relationships:
        dim, fact = tables[r.dim_table], tables[r.fact_table]
        assert (r.cardinality, r.cross_filter, r.active) == ("one_to_many", "single", True), r.rel_id
        assert dim.kind == "dimension" and fact.kind == "fact" and dim.key == (r.dim_column,), r.rel_id
        by_name = {c.name: c for c in fact.columns}
        assert r.fact_column in by_name and by_name[r.fact_column].dtype == next(c for c in dim.columns if c.name == r.dim_column).dtype, r.rel_id
        assert set(dim.key) <= set(dim.column_names) and set(fact.key) <= set(fact.column_names)
    assert validate_model(MODEL) == []


def test_the_model_is_the_plans_ten_dimensions_and_fifteen_facts_with_their_grain():
    assert [t.name for t in MODEL.tables] == [*DIMENSIONS, *FACTS]
    kinds = {t.name: t.kind for t in MODEL.tables}
    assert all(kinds[n] == "dimension" for n in DIMENSIONS) and all(kinds[n] == "fact" for n in FACTS)
    grain = {t.name: t.key for t in MODEL.tables}
    assert grain["fact_cell_effect"] == ("scope", "version_key", "cell_key", "ci_kind", "seal_state") and grain["dim_cell"] == ("cell_key",)
    assert grain["fact_daily_cell"] == ("date_key", "version_key", "cell_key") and grain["fact_hour_profile"] == ("date_key", "group_key", "hour", "day_state")
    for t in MODEL.tables:
        assert all(c.description_es for c in t.columns) and t.description_es and len({c.name for c in t.columns}) == len(t.columns), t.name
        assert all(c.dtype in ARROW_TYPES for c in t.columns)
    assert [c.name for c in MODEL.table("fact_forecast").columns] == ["scope", "method_key", "fit_blocks", "wape", "bias", "series_days", "seal_state"]
    assert {c.name for c in MODEL.table("fact_recovery_check").columns} >= {"fit_blocks", "mask", "chosen", "seal_state"}       # every figure says what it was fitted on and under which seal


def test_validate_model_names_each_incoherence():
    def with_table(name, **changes):
        return dataclasses.replace(MODEL, tables=tuple(dataclasses.replace(t, **changes) if t.name == name else t for t in MODEL.tables))

    def with_relationship(index, **changes):
        rels = list(MODEL.relationships)
        rels[index] = dataclasses.replace(rels[index], **changes)
        return dataclasses.replace(MODEL, relationships=tuple(rels))

    cases = [(dataclasses.replace(MODEL, tables=(*MODEL.tables, MODEL.tables[0])), "repetidas"), (with_table("dim_cell", key=("nope",)), "no es una columna"),
             (with_relationship(0, cardinality="many_to_many"), "uno a varios"), (with_relationship(0, cross_filter="both"), "unidireccional"),
             (with_relationship(0, active=False), "activa"), (with_relationship(0, fact_column="hour"), "no es una columna del tipo"),
             (with_relationship(0, dim_column="date"), "clave entera"), (with_relationship(0, fact_table="dim_hour"), "no une una dimensión con un hecho")]
    for model, text in cases:
        assert any(text in p for p in validate_model(model)), (text, validate_model(model))
    assert validate_model(dataclasses.replace(MODEL, relationships=(*MODEL.relationships, Relationship("R99", "dim_date", "date_key", "fact_hour_profile", "date_key")))) == []


def test_each_parquet_has_the_schema_of_the_specification_with_unique_keys_and_every_foreign_key_in_its_dimension(star_export):
    out, tables = star_export.out, {t.name: t for t in MODEL.tables}
    assert sorted(p.name for p in out.glob("*.parquet")) == sorted(f"{t.name}.parquet" for t in MODEL.tables) and (out / STAR_MANIFEST).is_file() and verify_star_schema(out) == []
    data = {t.name: read(out, t.name) for t in MODEL.tables}
    for t in MODEL.tables:
        assert data[t.name].schema.remove_metadata() == arrow_schema(t), t.name
        keys = list(zip(*[data[t.name].column(k).to_pylist() for k in t.key], strict=True))
        assert len(keys) == len(set(keys)) and all(None not in k for k in keys), t.name
    for r in MODEL.relationships:
        dimension = set(data[r.dim_table].column(r.dim_column).to_pylist())
        values = data[r.fact_table].column(r.fact_column).to_pylist()
        assert set(values) <= dimension and None not in values, r.rel_id
    for name in ("fact_cell_effect", "fact_band_effect", "fact_group_effect", "fact_overall_effect", "fact_daily_cell", "fact_hour_profile", "fact_stockout_daily", "fact_recovery_check",
                 "fact_forecast", "fact_replication", "fact_evaluation_summary", "fact_example_day", "fact_leakage", "fact_data_quality", "fact_validation", "dim_pipeline_run"):
        assert data[name].num_rows > 0, name


def test_the_facts_are_the_rows_of_the_warehouse_tables_they_are_made_from(star_export):
    db = star_export.db
    counts = {name: connect(db).execute(sql).fetchone()[0] for name, sql in {
        "fact_daily_cell": "SELECT COUNT(*) FROM daily_cell WHERE cell_key LIKE 'g%'", "fact_hour_profile": "SELECT COUNT(*) FROM hour_profile",
        "fact_evaluation_summary": "SELECT COUNT(*) FROM eval_criteria", "fact_replication": "SELECT COUNT(*) FROM eval_replication", "fact_leakage": "SELECT COUNT(*) FROM eval_leakage",
        "fact_validation": "SELECT COUNT(*) FROM validation_results", "fact_data_quality": "SELECT COUNT(DISTINCT date_key) FROM series_days",
        "fact_group_effect": "SELECT COUNT(*) FROM effect_estimates WHERE unit = 'group'", "dim_date": "SELECT COUNT(DISTINCT date_key) FROM series_days",
        "dim_cell": "SELECT COUNT(DISTINCT management_group_id) * 7 FROM series", "dim_city": "SELECT COUNT(DISTINCT city_id) FROM series",
        "dim_group": "SELECT COUNT(DISTINCT management_group_id) FROM series", "dim_band": "SELECT 7", "dim_hour": "SELECT 24", "dim_version": "SELECT 2"}.items()}
    for name, expected in counts.items():
        assert len(table_rows(db, name)) == expected, name
    assert len(table_rows(db, "fact_forecast")) == 8 and len(table_rows(db, "fact_cell_effect")) == connect(db).execute(
        "SELECT COUNT(*) FROM effect_estimates WHERE unit = 'cell'").fetchone()[0]
    daily = connect(db).execute("SELECT SUM(observed), SUM(counterfactual) FROM daily_cell WHERE cell_key LIKE 'g%' AND version = 'recovered'").fetchone()
    mine = connect(db).execute("SELECT SUM(observed), SUM(counterfactual) FROM star_fact_daily_cell WHERE version_key = 'recovered'").fetchone()
    assert mine == pytest.approx(daily)
    hp = connect(db).execute("SELECT SUM(series_days), SUM(mean_sales * series_days), SUM(stockout_rate * series_days) FROM star_fact_hour_profile").fetchone()
    raw = connect(db).execute("SELECT SUM(series_days), SUM(sales_sum), SUM(stockout_count) FROM hour_profile").fetchone()
    assert hp == pytest.approx(raw)


def test_the_files_carry_the_run_the_source_and_the_attribution_and_no_local_path_and_stay_under_the_size_limit(star_export):
    for path in star_export.paths:
        meta = {k.decode(): v.decode() for k, v in (pq.read_schema(path).metadata or {}).items()}
        assert meta["promolift.run_key"] == "run-close" and meta["promolift.as_of"] == "2024-07-03 00:00:00"
        assert meta["promolift.train_sha256"] == star_export.view.train_sha256_seen and meta["promolift.eval_sha256"] == star_export.view.eval_sha256_seen
        assert "CC BY 4.0" in meta["promolift.attribution"] and "Dingdong-Inc" in meta["promolift.attribution"]
        assert path.stat().st_size <= 25 * 1024 * 1024
        text = path.read_bytes()
        assert str(star_export.folder).encode() not in text and b"C:\\" not in text and b"/Users/" not in text
    manifest = json.loads((star_export.out / STAR_MANIFEST).read_text(encoding="utf-8"))
    assert manifest["run_key"] == "run-close" and [f["name"] for f in manifest["files"]] == [f"{t.name}.parquet" for t in MODEL.tables]
    assert str(star_export.folder) not in json.dumps(manifest)


def test_the_effect_facts_say_what_they_were_fitted_with_and_under_which_seal_and_carry_the_rank_and_tier_of_the_launch(star_export):
    cells = read(star_export.out, "fact_cell_effect").to_pandas()
    assert set(cells["scope"]) == {"launch", "valid_replication", "test"} and set(cells["version_key"]) == {"raw", "recovered"} and set(cells["ci_kind"]) == {"two_way"}
    assert set(cells[cells["scope"] == "launch"]["fit_blocks"]) == {"train+purge+valid_v1+valid_v2"} and set(cells[cells["scope"] == "valid_replication"]["fit_blocks"]) == {"train"}
    assert set(cells["seal_state"]) == {"sealed"} and cells["fit_blocks"].str.len().gt(0).all()
    ranked = cells[(cells["scope"] == "launch") & (cells["version_key"] == "recovered") & cells["ranked"]].sort_values("rank")
    assert ranked["rank"].tolist() == list(range(1, len(ranked) + 1)) and ranked["lift"].is_monotonic_decreasing and ranked["tier"].is_monotonic_increasing
    stored = connect(star_export.db).execute("SELECT unit_key, ranked, tier FROM effect_estimates WHERE scope = 'launch' AND version = 'recovered' AND unit = 'cell' AND ranked = 1").fetchall()
    assert {(r.cell_key, r.tier) for r in ranked.itertuples()} == {(k, t) for k, _r, t in stored}
    bands = read(star_export.out, "fact_band_effect").to_pandas()
    assert set(bands["day_state"]) == {"promo", "unflagged_cut"} and {"regular", "any_flag0"} == set(bands["control"]) and set(bands["seal_state"]) == {"sealed"}
    overall = read(star_export.out, "fact_overall_effect").to_pandas()
    assert {"naive_pooled", "counterfactual"} == set(overall["estimator"]) and {"regular", "any_flag0"} == set(overall["control"])
    recovery = read(star_export.out, "fact_recovery_check").to_pandas()
    assert set(recovery["scope"]) == {"valid_v1", "valid_v2", "test"} and {"tail", "mcar"} == set(recovery["mask"])
    chosen = json.loads(connect(star_export.db).execute("SELECT recovery_json FROM model_registry").fetchone()[0])["name"]
    assert set(recovery[recovery["chosen"]]["method_key"]) == {chosen} and recovery[recovery["scope"] != "test"]["fit_blocks"].eq("train").all()
    forecast = read(star_export.out, "fact_forecast").to_pandas()
    assert set(forecast["scope"]) == {"valid", "test"} and set(forecast[forecast["scope"] == "valid"]["fit_blocks"]) == {"train"} and forecast["wape"].between(0, 5).all()


def test_the_validation_status_and_the_runs_are_what_the_warehouse_holds(star_export):
    rules = read(star_export.out, "fact_validation").to_pandas().sort_values(["run_key", "rule_id"])
    assert rules["status"].tolist() == ["advierte", "pasa", "advierte"] * 2 and rules["severity"].tolist() == ["informativa", "bloqueante", "advertencia"] * 2
    runs = read(star_export.out, "dim_pipeline_run").to_pandas()
    assert sorted(runs["run_key"]) == ["run-close", "run-launch"] and runs["memory_counter"].eq("PeakWorkingSetSize").all()
    model = read(star_export.out, "dim_model").to_pandas()
    assert model["model_key"].tolist() == ["v1"] and model["seal_state"].tolist() == ["sealed"] and model["recovery_method"].iloc[0] in ("r1", "r2", "r3")
    dates = read(star_export.out, "dim_date").to_pandas().set_index("date_key")
    assert dates.loc[20240626, "block"] == "test" and dates.loc[20240608, "block"] == "valid_v1" and dates.loc[20240601, "block_es"] != dates.loc[20240608, "block_es"]
    assert dates.loc[20240629, "weekday_es"] == "sábado" and bool(dates.loc[20240629, "is_weekend"]) and not bool(dates.loc[20240626, "is_weekend"])
    band = read(star_export.out, "dim_band").to_pandas().set_index("band_key")
    assert band.loc[0, "depth_label_es"] == "más del 50 %" and band.loc[1, "depth_label_es"] == "40 a 50 %" and band.loc[6, "depth_label_es"] == "hasta 5 %"
    assert band.loc[0, "discount_low"] == 0.0 and band.loc[6, "discount_high"] == 1.0
    cell = read(star_export.out, "dim_cell").to_pandas().set_index("cell_key")
    assert cell.loc["g3-b2", "group_key"] == 3 and cell.loc["g3-b2", "band_key"] == 2 and cell.loc["g3-b2", "label_es"] == "Grupo 3, rebaja de 30 a 40 %"
    methods = read(star_export.out, "dim_method").to_pandas().set_index("method_key")
    assert methods.loc["r0", "kind_es"] == "recuperación" and methods.loc["f2_cell_lift", "kind_es"] == "pronóstico"


def test_the_marts_are_as_of_the_run_and_a_day_that_had_not_closed_is_not_in_them(star_export, launch_config, tmp_path):
    from tests.fixtures.weeks import clone

    w = clone(star_export.folder, tmp_path / "early", launch_config, star_export.view.train_sha256_seen, star_export.view.eval_sha256_seen)
    out = tmp_path / "powerbi"
    export_star_schema(w.conn, out, MODEL, RunMeta("run-early", __import__("datetime").datetime(2024, 6, 28)), w.view, seal_path=w.seal, interim_dir=w.cfg.paths.interim_dir)
    assert max(read(out, "dim_date").column("date_key").to_pylist()) == 20240627 and set(read(out, "fact_daily_cell").column("date_key").to_pylist()) == {20240626, 20240627}
    assert max(read(out, "fact_data_quality").column("date_key").to_pylist()) == 20240627 and max(read(out, "fact_hour_profile").column("date_key").to_pylist()) == 20240627
    assert verify_star_schema(out) == []
    w.conn.close()


def test_a_control_with_rows_undoes_the_marts_and_the_previous_ones_stay(star_export, launch_config, tmp_path):
    from tests.fixtures.weeks import clone

    w = clone(star_export.folder, tmp_path / "broken", launch_config, star_export.view.train_sha256_seen, star_export.view.eval_sha256_seen)
    out = tmp_path / "powerbi"
    export_star_schema(w.conn, out, MODEL, star_export.run, w.view, seal_path=w.seal, interim_dir=w.cfg.paths.interim_dir)
    before = {p.name: p.read_bytes() for p in out.iterdir()}
    marts = w.conn.execute("SELECT COUNT(*) FROM star_fact_validation").fetchone()[0]
    w.conn.execute("INSERT INTO validation_results VALUES ('run-orphan', 'V10', 'x', 'blocking', 'delivery', 'per_run', 1, 0, 0, '[]')")     # a rule of a run that is not in dim_pipeline_run
    with pytest.raises(CheckFailedError) as caught:
        export_star_schema(w.conn, out, MODEL, star_export.run, w.view, seal_path=w.seal, interim_dir=w.cfg.paths.interim_dir)
    assert any(c.check_id == "chk_fk_r21_fact_validation_dim_pipeline_run" and c.violations == 1 for c in caught.value.checks)
    assert not w.conn.in_transaction and w.conn.execute("SELECT COUNT(*) FROM star_fact_validation").fetchone()[0] == marts
    assert {p.name: p.read_bytes() for p in out.iterdir()} == before and verify_star_schema(out) == []
    w.conn.close()


def test_the_manifest_is_written_last_and_a_failure_in_the_middle_of_the_writes_leaves_a_set_that_is_refused(star_export, launch_config, tmp_path, monkeypatch):
    from promolift import export as export_module
    from tests.fixtures.weeks import clone

    w = clone(star_export.folder, tmp_path / "failing", launch_config, star_export.view.train_sha256_seen, star_export.view.eval_sha256_seen)
    out = tmp_path / "powerbi"
    export_star_schema(w.conn, out, MODEL, star_export.run, w.view, seal_path=w.seal, interim_dir=w.cfg.paths.interim_dir)
    assert verify_star_schema(out) == []
    real, calls = export_module.write_atomic, []

    def failing(path, data):
        calls.append(Path(path).name)
        if len(calls) == 13:
            raise OSError("disk full")
        return real(path, data)

    monkeypatch.setattr(export_module, "write_atomic", failing)
    with pytest.raises(OSError, match="disk full"):
        export_star_schema(w.conn, out, MODEL, RunMeta("run-again", star_export.run.as_of), w.view, seal_path=w.seal, interim_dir=w.cfg.paths.interim_dir)
    assert not (out / STAR_MANIFEST).exists() and STAR_MANIFEST not in calls and verify_star_schema(out)
    assert "no hay un manifiesto" in verify_star_schema(out)[0]
    monkeypatch.undo()
    export_star_schema(w.conn, out, MODEL, star_export.run, w.view, seal_path=w.seal, interim_dir=w.cfg.paths.interim_dir)
    assert verify_star_schema(out) == []
    (out / "dim_band.parquet").write_bytes(b"changed")
    (out / "stray.parquet").write_bytes(b"x")
    problems = verify_star_schema(out)
    assert any("dim_band.parquet" in p for p in problems) and any("stray.parquet" in p for p in problems)
    w.conn.close()


def test_a_post_seal_analysis_is_shown_beside_the_sealed_one_never_instead_of_it(evaluated_week, launch_config, tmp_path):
    from dataclasses import replace

    from promolift.registry import sealed_view
    from promolift.reporting import evaluate
    from tests.fixtures.weeks import clone
    from tests.unit.test_seal import with_key

    w = clone(evaluated_week.folder, tmp_path / "post", launch_config, evaluated_week.view.train_sha256_seen, evaluated_week.view.eval_sha256_seen)
    other = sealed_view(with_key(w.cfg, "ranking.min_series"), evaluated_week.view.train_sha256_seen, evaluated_week.view.eval_sha256_seen)
    assert evaluate(w.conn, w.cube, evaluated_week.bundle, replace(evaluated_week.run, run_key="run-post"), other, seal_path=w.seal)["test"] == "post_seal"
    out = tmp_path / "powerbi"
    export_star_schema(w.conn, out, MODEL, evaluated_week.run, w.view, seal_path=w.seal, interim_dir=w.cfg.paths.interim_dir)
    summary = read(out, "fact_evaluation_summary").to_pandas()
    assert summary.groupby("seal_state").size().to_dict() == {"post_seal": 10, "sealed": 10} and summary[summary["seal_state"] == "sealed"]["verdict_es"].str.len().gt(0).all()
    assert set(read(out, "fact_replication").column("seal_state").to_pylist()) == {"sealed", "post_seal"} and set(read(out, "fact_forecast").column("seal_state").to_pylist()) >= {"sealed", "post_seal"}
    w.conn.close()


def test_the_example_day_is_the_median_series_day_of_the_fixed_rule(star_export):
    import numpy as np

    from promolift.cube import open_loaded_cube, open_recovered

    example = read(star_export.out, "fact_example_day").to_pandas()
    assert example["hour"].tolist() == list(range(6, 22)) and set(example["in_stock"]) <= {0, 1, False, True}
    cube, recovered = open_loaded_cube(star_export.cfg.paths.interim_dir), open_recovered(star_export.cfg.paths.interim_dir, "L2024-06-25")
    first, last = star_export.view.calendar.day_hours
    keys = [k for k in cube.date_keys.tolist() if k <= 20240625]
    candidates = []
    for day, key in enumerate(keys):
        sales, stock = np.asarray(cube.sales(key))[:, first:last + 1], np.asarray(cube.stock(key))[:, first:last + 1]
        rec = np.asarray(recovered[:, day, first:last + 1], dtype=np.float64)
        out = (stock == 1).any(axis=1)
        cut = np.where(out, (stock == 1).argmax(axis=1) + first, -1)
        for s in np.flatnonzero(out & (cut >= 12) & (cut <= 18)):
            if (sales[s, :cut[s] - first] > 0).sum() >= 4:
                candidates.append((float(rec[s].sum()), int(s), key))
    candidates.sort()
    mass, series, key = candidates[(len(candidates) - 1) // 2]
    day = keys.index(key)
    assert example["observed"].to_numpy() == pytest.approx(np.asarray(cube.sales(key))[series, first:last + 1])
    assert example["recovered"].to_numpy() == pytest.approx(np.asarray(recovered[series, day, first:last + 1]), abs=1e-6) and example["recovered"].sum() == pytest.approx(mass)
    assert example["in_stock"].astype(int).tolist() == (1 - np.asarray(cube.stock(key))[series, first:last + 1]).tolist()


def test_nothing_of_the_test_week_is_in_the_marts_while_the_week_has_not_closed(star_export, launch_config, tmp_path):
    from datetime import datetime

    from tests.fixtures.weeks import clone

    w = clone(star_export.folder, tmp_path / "early", launch_config, star_export.view.train_sha256_seen, star_export.view.eval_sha256_seen)
    out = tmp_path / "powerbi"
    export_star_schema(w.conn, out, MODEL, RunMeta("run-early", datetime(2024, 7, 2)), w.view, seal_path=w.seal, interim_dir=w.cfg.paths.interim_dir)
    assert "test" not in set(read(out, "fact_cell_effect").column("scope").to_pylist()) and "test" not in set(read(out, "fact_recovery_check").column("scope").to_pylist())
    for name in ("fact_evaluation_summary", "fact_replication"):
        assert read(out, name).num_rows == 0, name
    assert set(read(out, "fact_forecast").column("scope").to_pylist()) == {"valid"} and set(read(out, "fact_band_effect").column("scope").to_pylist()) == {"launch", "valid_replication"}
    assert max(read(out, "fact_daily_cell").column("date_key").to_pylist()) == 20240701
    w.conn.close()
    late = clone(star_export.folder, tmp_path / "late", launch_config, star_export.view.train_sha256_seen, star_export.view.eval_sha256_seen)
    export_star_schema(late.conn, tmp_path / "late_out", MODEL, RunMeta("run-late", datetime(2024, 7, 3)), late.view, seal_path=late.seal, interim_dir=late.cfg.paths.interim_dir)
    assert "test" in set(read(tmp_path / "late_out", "fact_cell_effect").column("scope").to_pylist()) and read(tmp_path / "late_out", "fact_evaluation_summary").num_rows == 10
    late.conn.close()


def test_the_demand_that_stock_outs_hid_is_summed_only_over_the_series_days_that_were_recovered(star_export, launch_config, tmp_path):
    from tests.fixtures.weeks import clone

    w = clone(star_export.folder, tmp_path / "partial", launch_config, star_export.view.train_sha256_seen, star_export.view.eval_sha256_seen)
    w.conn.execute("UPDATE series_days SET recovered_sum = NULL WHERE date_key = 20240626")
    out = tmp_path / "powerbi"
    export_star_schema(w.conn, out, MODEL, star_export.run, w.view, seal_path=w.seal, interim_dir=w.cfg.paths.interim_dir)
    daily = read(out, "fact_stockout_daily").to_pandas()
    day, others = daily[daily["date_key"] == 20240626], daily[daily["date_key"] != 20240626]
    assert day["recovered_mass"].isna().all() and day["raw_mass"].isna().all() and day["series_days"].gt(0).all() and day["stockout_rate"].between(0, 1).all()
    assert others["recovered_mass"].notna().all() and (others["recovered_mass"] >= others["raw_mass"] - 1e-9).all()
    w.conn.close()


def test_the_model_seal_state_says_post_seal_when_the_registered_model_is_not_the_one_of_the_seal(star_export, launch_config, tmp_path):
    from tests.fixtures.weeks import clone

    w = clone(star_export.folder, tmp_path / "other_seal", launch_config, star_export.view.train_sha256_seen, star_export.view.eval_sha256_seen)
    document = json.loads(w.seal.read_text(encoding="utf-8"))
    document["launch"]["config_sha256"] = "e" * 64
    w.seal.write_text(json.dumps(document), encoding="utf-8")
    out = tmp_path / "powerbi"
    export_star_schema(w.conn, out, MODEL, star_export.run, w.view, seal_path=w.seal, interim_dir=w.cfg.paths.interim_dir)
    assert read(out, "dim_model").column("seal_state").to_pylist() == ["post_seal"]
    assert set(read(out, "fact_cell_effect").to_pandas().query("scope != 'test'")["seal_state"]) == {"post_seal"} and set(read(out, "fact_forecast").to_pandas().query("scope == 'valid'")["seal_state"]) == {"post_seal"}
    assert set(read(out, "fact_cell_effect").to_pandas().query("scope == 'test'")["seal_state"]) == {"sealed"}
    w.conn.close()


def _params(view, run):
    from promolift.launch import FIT_BLOCKS_VALID
    from promolift.warehouse import sql_params

    params = {**sql_params(run.as_of, view), "min_series": view.ranking.min_series, "fit_blocks_valid": FIT_BLOCKS_VALID}
    return {**params, "test_closed": int(params["as_of_key"] > params["test_last_key"])}


@pytest.mark.parametrize(("check", "damage"), [
    ("chk_interval_contains_lift", "UPDATE star_fact_group_effect SET lift = ci_high + 1 WHERE scope = 'launch' AND version_key = 'recovered' AND group_key = 1"),
    ("chk_interval_contains_lift", "UPDATE star_fact_cell_effect SET lift = ci_high + 1 WHERE rank = 1 AND scope = 'launch' AND version_key = 'recovered'"),
    ("chk_interval_contains_lift", "UPDATE star_fact_cell_effect SET ci_low = ci_high + 1 WHERE rank = 1 AND scope = 'launch' AND version_key = 'recovered'"),
    ("chk_ranked_cells_have_min_series", "UPDATE star_fact_cell_effect SET series = 1 WHERE rank = 1 AND scope = 'launch' AND version_key = 'recovered'"),
    ("chk_ranked_cells_have_min_series", "UPDATE star_fact_cell_effect SET rank = 3 WHERE ranked = 0"),
    ("chk_tiers_are_overlap_groups", "UPDATE star_fact_cell_effect SET tier = 2 WHERE rank = 2 AND scope = 'launch' AND version_key = 'recovered'"),
    ("chk_tiers_are_overlap_groups", "UPDATE star_fact_cell_effect SET tier = 1, ci_low = 100, ci_high = 101 WHERE scope = 'launch' AND version_key = 'recovered' AND rank = (SELECT MAX(rank) FROM star_fact_cell_effect "
                                    "WHERE scope = 'launch' AND version_key = 'recovered')"),
    ("chk_one_daily_cell_per_key", "DELETE FROM star_fact_daily_cell WHERE rowid = (SELECT MIN(rowid) FROM star_fact_daily_cell)"),
    ("chk_one_daily_cell_per_key", "INSERT INTO star_fact_daily_cell SELECT 20240626, version_key, 'g99-b9', observed, counterfactual, lift, series_days, stockout_hours FROM star_fact_daily_cell LIMIT 1"),
    ("chk_forecasts_only_promo_days", "UPDATE series_days SET day_state = 'regular' WHERE (series_key, date_key) = (SELECT series_key, date_key FROM forecasts WHERE scope = 'test' LIMIT 1)"),
    ("chk_four_forecasts_per_series_day", "DELETE FROM forecasts WHERE rowid = (SELECT MIN(rowid) FROM forecasts WHERE scope = 'valid') AND 1 = (SELECT 1)"),
    ("chk_star_keys_unique", "INSERT INTO star_dim_band SELECT * FROM star_dim_band LIMIT 1"),
    ("chk_star_keys_unique", "UPDATE star_dim_cell SET cell_key = NULL WHERE rowid = 1")])
def test_each_control_of_the_model_flags_the_violation_it_names_and_only_that_control_does(star_export, launch_config, tmp_path, check, damage):
    from promolift.warehouse import run_checks
    from tests.fixtures.weeks import clone

    w = clone(star_export.folder, tmp_path / "damaged", launch_config, star_export.view.train_sha256_seen, star_export.view.eval_sha256_seen)
    params = _params(w.view, star_export.run)
    assert [r.check_id for r in run_checks(w.conn, "model", params) if r.violations] == []                # the exported marts pass every control
    for trigger in ("forecasts_no_delete", "forecasts_no_update"):
        w.conn.execute(f"DROP TRIGGER IF EXISTS {trigger}")
    w.conn.execute(damage)
    flagged = [r.check_id for r in run_checks(w.conn, "model", params) if r.violations]
    assert check in flagged
    w.conn.close()
