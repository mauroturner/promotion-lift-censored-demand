"""The runner of the warehouse (U06; plan, section 5; D22): the connection and its pragmas, the split of a SQL file into statements, named
parameters, the idempotent schema that refuses a table with other columns, the controls' contract and the constraints of the core tables."""

from __future__ import annotations

import ast
import re
import sqlite3
from pathlib import Path

import numpy as np
import pytest

from promolift import warehouse
from promolift.warehouse import SchemaDriftError, apply_schema, connect, run_checks, run_sql_file, split_statements, sql_params

PROJECT = Path(__file__).resolve().parents[2]
CORE_TABLES = ["deliveries", "hour_profile", "pipeline_runs", "series", "series_days", "validation_results"]
# 002_effects.sql (U09, U10): what the model said, issued once
EFFECT_TABLES = ["daily_cell", "effect_estimates", "forecasts", "mask_checks", "model_registry", "recovery_checks"]
# 003_eval.sql (U11): the evaluation of the test week
EVAL_TABLES = ["eval_criteria", "eval_forecast", "eval_leakage", "eval_pairs", "eval_replication", "eval_variants"]
SCHEMA_TABLES = sorted([*CORE_TABLES, *EFFECT_TABLES, *EVAL_TABLES])


def tables(conn) -> list[str]:
    return [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]


# --- the connection ---------------------------------------------------------------------------------------------------------------------


def test_connect_creates_the_folder_and_sets_the_pragmas_of_the_project(tmp_path):
    conn = connect(tmp_path / "deep" / "er" / "w.sqlite")
    try:
        assert (tmp_path / "deep" / "er" / "w.sqlite").exists() and conn.isolation_level is None
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete" and conn.execute("PRAGMA synchronous").fetchone()[0] == 2
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1 and conn.execute("PRAGMA busy_timeout").fetchone()[0] == warehouse.BUSY_TIMEOUT_MS == 30_000
        assert conn.execute("PRAGMA cache_size").fetchone()[0] == -65_536
    finally:
        conn.close()


def test_the_runner_never_uses_executescript():
    """It commits the open transaction first (a load would no longer be all or nothing); the statements are split and run one by one."""
    for path in (PROJECT / "src" / "promolift").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        calls = [n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
        assert "executescript" not in calls, path.name


# --- splitting and running SQL files -------------------------------------------------------------------------------------------------------


def test_a_sql_file_is_split_into_statements_keeping_semicolons_in_strings_comments_and_triggers():
    text = """-- a comment; with a semicolon
CREATE TABLE t (a TEXT DEFAULT ';', b INTEGER); /* another; one */
INSERT INTO t VALUES ('x;y', 1);
CREATE TRIGGER tr BEFORE INSERT ON t BEGIN SELECT RAISE(ABORT, 'no; way'); SELECT 1; END;
-- only a comment
;;
SELECT 1"""
    statements = split_statements(text)
    assert len(statements) == 4, statements
    assert "CREATE TABLE t" in statements[0] and statements[0].endswith("b INTEGER);")
    assert "INSERT INTO t VALUES ('x;y', 1);" in statements[1] and "-- only a comment" not in statements[1]
    assert statements[2].startswith("CREATE TRIGGER tr") and statements[2].endswith("END;") and "SELECT 1; END" in statements[2]
    assert statements[3] == "SELECT 1"
    assert split_statements("") == [] and split_statements("-- nothing\n/* at all */;") == []
    returned = split_statements("SELECT 1;")
    returned.append("changed")
    assert split_statements("SELECT 1;") == ["SELECT 1;"], "the cached split is never shared with the caller"


def test_run_sql_file_binds_named_parameters_statement_by_statement(tmp_path):
    path = tmp_path / "q.sql"
    path.write_text("CREATE TABLE t (a INTEGER);\nINSERT INTO t VALUES (:one);\nINSERT INTO t VALUES (:two);\n", encoding="utf-8")
    conn = sqlite3.connect(":memory:", isolation_level=None)
    run_sql_file(conn, path, {"one": 1, "two": 2, "unused": 3})
    assert conn.execute("SELECT a FROM t ORDER BY a").fetchall() == [(1,), (2,)]
    with pytest.raises(sqlite3.ProgrammingError):
        run_sql_file(sqlite3.connect(":memory:", isolation_level=None), path, {"one": 1})


def test_sql_params_carry_the_day_the_blocks_the_thresholds_and_the_hours(cfg):
    from datetime import datetime

    params = sql_params(datetime(2024, 6, 26), cfg)
    assert params["as_of_key"] == 20240626
    assert (params["train_first_key"], params["train_last_key"], params["purge_first_key"], params["purge_last_key"]) == (20240328, 20240531, 20240601, 20240607)
    assert (params["valid_v1_first_key"], params["valid_v1_last_key"], params["valid_v2_first_key"], params["valid_v2_last_key"]) == (
        20240608, 20240616, 20240617, 20240625)
    assert (params["test_first_key"], params["test_last_key"]) == (20240626, 20240702)
    assert (params["regular_min_discount"], params["anomalous_max_discount"], params["anomalous_min_discount"]) == (0.999, 0.0, 1.0)
    assert params["band_edges"] == "[0.5, 0.6, 0.7, 0.8, 0.9, 0.95]" and params["edge_tolerance"] == 1e-6
    assert (params["first_hour"], params["last_hour"], params["analysis_hours"]) == (6, 21, 16)
    assert sql_params(datetime(2024, 7, 1, 13, 30), cfg)["as_of_key"] == 20240701


# --- the schema ------------------------------------------------------------------------------------------------------------------------------


def test_apply_schema_creates_the_core_tables_and_is_idempotent(tmp_path):
    conn = connect(tmp_path / "w.sqlite")
    try:
        apply_schema(conn)
        assert tables(conn) == SCHEMA_TABLES
        conn.execute("INSERT INTO series VALUES (1, 3, 1, 500, 0, 40, 20, 100)")
        apply_schema(conn)
        apply_schema(conn)
        assert tables(conn) == SCHEMA_TABLES and conn.execute("SELECT COUNT(*) FROM series").fetchone()[0] == 1, "the data is kept"
        assert not conn.in_transaction
    finally:
        conn.close()


def test_apply_schema_joins_the_transaction_of_the_caller_and_a_rollback_takes_it_back(tmp_path):
    conn = connect(tmp_path / "w.sqlite")
    try:
        conn.execute("BEGIN IMMEDIATE")
        apply_schema(conn)
        assert conn.in_transaction
        conn.execute("ROLLBACK")
        assert tables(conn) == []
    finally:
        conn.close()


def test_a_table_with_other_columns_than_its_file_declares_is_named_and_not_migrated(tmp_path):
    conn = connect(tmp_path / "w.sqlite")
    try:
        conn.execute("CREATE TABLE series (series_key INTEGER PRIMARY KEY, store_id INTEGER, legacy TEXT)")
        with pytest.raises(SchemaDriftError, match=r"La tabla series no coincide con su definición en sql/schema/001_core.sql.*R11") as raised:
            apply_schema(conn)
        assert raised.value.table == "series" and "legacy" in raised.value.unexpected and "city_id" in raised.value.missing
        assert tables(conn) == ["series"] and not conn.in_transaction
        conn.execute("DROP TABLE series")
        conn.execute("CREATE TABLE series (series_key INTEGER PRIMARY KEY, store_id TEXT, city_id INTEGER, product_id INTEGER, management_group_id INTEGER, "
                     "first_category_id INTEGER, second_category_id INTEGER, third_category_id INTEGER)")
        with pytest.raises(SchemaDriftError) as raised:
            apply_schema(conn)
        assert raised.value.retyped == ("store_id",)
    finally:
        conn.close()


# --- the constraints of the core tables ---------------------------------------------------------------------------------------------------------


@pytest.fixture
def conn(tmp_path):
    connection = connect(tmp_path / "w.sqlite")
    apply_schema(connection)
    connection.execute("INSERT INTO series VALUES (1, 3, 1, 500, 0, 40, 20, 100)")
    connection.execute("INSERT INTO deliveries VALUES ('L', 'launch', '2024-03-28', '2024-06-25', '2024-06-26 00:00:00', 0, 'x', 'loaded', 'r')")
    yield connection
    connection.close()


def day(**changes) -> tuple:
    row = {"series_key": 1, "date_key": 20240328, "delivery_id": "L", "day_state": "promo", "band": 2, "activity_flag": 1, "discount": 0.65,
           "holiday_flag": 0, "raw_sum": 1.0, "instock_hours": 16, "stockout_hours": 0, "instock_sum": 1.0, "recovered_sum": None, "fully_out": 0}
    row.update(changes)
    return tuple(row.values())


@pytest.mark.parametrize("changes", [
    {"day_state": "weekly"}, {"band": -1}, {"activity_flag": 2}, {"holiday_flag": 2}, {"raw_sum": -0.1}, {"instock_hours": -1}, {"stockout_hours": -1},
    {"fully_out": 2}, {"series_key": 99}, {"delivery_id": "ghost"}, {"discount": None},
])
def test_the_core_tables_refuse_what_their_constraints_name(conn, changes):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO series_days VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", day(**changes))


def test_a_series_day_cannot_be_inserted_twice_and_a_series_has_one_store_product_pair(conn):
    conn.execute("INSERT INTO series_days VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", day())
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO series_days VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", day())
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO series VALUES (2, 3, 1, 500, 0, 40, 20, 100)")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO deliveries VALUES ('X', 'weekly', NULL, NULL, 'x', 0, 'x', 'loaded', NULL)")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO pipeline_runs (run_key, started_at, status) VALUES ('r', 'now', 'sleeping')")
    conn.execute("INSERT INTO pipeline_runs (run_key, started_at, status) VALUES ('r', 'now', 'running')")


# --- the controls ---------------------------------------------------------------------------------------------------------------------------------


def test_the_controls_of_the_load_are_one_select_per_file_in_name_order(cfg):
    paths = sorted((PROJECT / "sql" / "checks" / "load").glob("chk_*.sql"))
    assert [p.stem for p in paths] == ["chk_day_state_rules", "chk_delivery_period", "chk_hours_add_up", "chk_profile_matches_days", "chk_series_day_unique"]
    for path in paths:
        statements = split_statements(path.read_text(encoding="utf-8"))
        code = re.sub(r"(?m)^--.*$", "", statements[0]).lstrip().upper()
        assert len(statements) == 1 and code.startswith(("SELECT", "WITH")), path.name


def test_a_group_that_does_not_exist_is_refused_and_an_empty_warehouse_passes_every_control(conn, cfg):
    from datetime import datetime

    with pytest.raises(ValueError, match="grupo de controles desconocido"):
        run_checks(conn, "weekly")  # type: ignore[arg-type]
    results = run_checks(conn, "load", sql_params(datetime(2024, 6, 26), cfg))
    assert [r.check_id for r in results] == ["chk_day_state_rules", "chk_delivery_period", "chk_hours_add_up", "chk_profile_matches_days", "chk_series_day_unique"]
    assert all(r.violations == 0 and r.sample == [] for r in results)
    assert run_checks(conn, "model") == []
    only = run_checks(conn, "load", sql_params(datetime(2024, 6, 26), cfg), only=["chk_hours_add_up"])
    assert [r.check_id for r in only] == ["chk_hours_add_up"]
    with pytest.raises(ValueError, match="chk_nope"):
        run_checks(conn, "load", sql_params(datetime(2024, 6, 26), cfg), only=["chk_nope"])


def test_a_control_counts_every_violation_and_samples_five(conn, cfg):
    from datetime import datetime

    conn.executemany("INSERT INTO series_days VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     [day(date_key=20240328 + i, instock_hours=10, stockout_hours=5, fully_out=0) for i in range(8)])
    (result,) = run_checks(conn, "load", sql_params(datetime(2024, 6, 26), cfg), only=["chk_hours_add_up"])
    assert result.violations == 8 and len(result.sample) == warehouse.SAMPLE_LIMIT == 5


def test_the_recovered_sums_are_set_once_and_never_rewritten(tmp_path):
    from promolift.warehouse import set_recovered_sums

    conn = connect(tmp_path / "w.sqlite")
    try:
        apply_schema(conn)
        conn.execute("INSERT INTO series VALUES (0, 3, 1, 500, 0, 40, 20, 100)")
        conn.execute("INSERT INTO series VALUES (1, 4, 1, 501, 0, 40, 20, 101)")
        conn.execute("INSERT INTO deliveries VALUES ('L', 'launch', '2024-06-01', '2024-06-02', '2024-06-03 00:00:00', 4, ?, 'loaded', 'r')", ("a" * 64,))
        conn.executemany("INSERT INTO series_days VALUES (?, ?, 'L', 'regular', NULL, 0, 1.0, 0, 1.0, 16, 0, 1.0, NULL, 0)", [(s, d) for s in (0, 1) for d in (20240601, 20240602)])
        assert set_recovered_sums(conn, np.array([20240601, 20240602]), np.array([[1.5, 2.5], [3.5, 4.5]])) == 4
        rows = conn.execute("SELECT series_key, date_key, recovered_sum FROM series_days ORDER BY series_key, date_key").fetchall()
        assert rows == [(0, 20240601, 1.5), (0, 20240602, 2.5), (1, 20240601, 3.5), (1, 20240602, 4.5)]
        assert set_recovered_sums(conn, np.array([20240601, 20240602]), np.array([[9.0, 9.0], [9.0, 9.0]])) == 0
        assert conn.execute("SELECT series_key, date_key, recovered_sum FROM series_days ORDER BY series_key, date_key").fetchall() == rows
    finally:
        conn.close()
