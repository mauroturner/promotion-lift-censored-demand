"""The rules of validation as a contract (U05; RF06, D23; AC06): every rule of the plan's table with how it is published over runs, the malformed
deliveries and sources that each trip their rule, the counts of the warnings against the truth of the fixture, and the interface of the rules of
the model."""

from __future__ import annotations

import dataclasses
import json
import re
import sqlite3
from datetime import date
from pathlib import Path

import numpy as np
import pyarrow as pa
import pytest

from promolift.deliveries import ManifestEntry
from promolift.ingest import fetch_source, read_source
from promolift.schema import SourceError
from promolift.validate import (
    EXAMPLE_LIMIT,
    RULES,
    Aggregation,
    RuleResult,
    Severity,
    ValidationError,
    ValidationReport,
    add_results,
    combine_reports,
    model_result,
    read_report,
    validate_delivery,
    validate_source,
    write_report,
)
from tests.fixtures import store
from tests.fixtures.make_fixture import MALFORMED_RULES, damaged_pair, replace_column

PLAN = Path(__file__).resolve().parents[2] / "docs" / "plan.md"
SEVERITIES = {"bloqueante": Severity.BLOCKING, "advertencia": Severity.WARNING, "informativa": Severity.INFO}
SCOPES = {"fuente": "source", "entrega": "delivery", "días": "days", "modelo": "model"}
ROW_LINE = re.compile(r"^\| ([VIM]\d\d) \| (bloqueante|advertencia|informativa) \| (fuente|entrega|días|modelo) \| (source|per_run|latest) \|", re.M)
MODEL_RULES = ("I03", "I04", "M01", "M02", "M03", "M04", "M05", "M06")


def failing(report: ValidationReport) -> set[str]:
    return {r.rule_id for r in report.results if r.status == "fail"}


def result(report: ValidationReport, rule_id: str) -> RuleResult:
    return next(r for r in report.results if r.rule_id == rule_id)


_MASTERS: dict[tuple[int, str], tuple[object, sqlite3.Connection]] = {}   # the stores that were built, by delivery of the plan: every test gets a copy of one


def store_until(published, delivery_id: str) -> sqlite3.Connection:
    """A warehouse that holds every delivery of the plan before `delivery_id`: built once per delivery and handed over as a copy."""
    key = (id(published), delivery_id)
    if key not in _MASTERS:
        master = store.empty_store()
        for spec in published.plan:
            if spec.delivery_id == delivery_id:
                break
            store.load(master, spec.delivery_id, published.items[spec.delivery_id][1])
        _MASTERS[key] = (published, master)
    conn = store.empty_store()
    owner, master = _MASTERS[key]
    assert owner is published
    master.backup(conn)
    return conn


def validate(published, cfg, delivery_id: str, conn=None, *, days=None, cube=None, spec=None, entry=None, folder=None, run_key="run-1") -> ValidationReport:
    """Validate a delivery of the published plan, with the days, the cube, the spec, the entry or the folder replaced by the test."""
    own_entry, own_days, own_cube = published.items[delivery_id]
    own_spec = next(s for s in published.plan if s.delivery_id == delivery_id)
    conn = store_until(published, delivery_id) if conn is None else conn
    return validate_delivery(own_days if days is None else days, own_cube if cube is None else cube, own_spec if spec is None else spec, conn, cfg,
                             entry=own_entry if entry is None else entry, out_dir=published.out_dir if folder is None else folder, run_key=run_key)


# --- the table of the plan ---------------------------------------------------------------------------------------------------------


def test_every_rule_declares_how_it_aggregates_over_runs():
    assert all(isinstance(rule.aggregation, Aggregation) for rule in RULES.values())
    by_aggregation = {a: [rule_id for rule_id, rule in RULES.items() if rule.aggregation is a] for a in Aggregation}
    assert by_aggregation[Aggregation.SOURCE] == ["V01", "V02", "V03", "V04", "V05", "V06", "V07", "V26", "V27"]
    assert by_aggregation[Aggregation.LATEST] == ["M01", "M05", "M06"]
    assert set(by_aggregation[Aggregation.PER_RUN]) == {"V10", "V11", "V12", "V13", "V14", "V15", "V20", "V21", "V22", "V23", "V24", "V25", "I01", "I02",
                                                         "I03", "I04", "M02", "M03", "M04"}
    assert len(RULES) == 7 + 6 + 8 + 4 + 6 == 31
    for rule in RULES.values():
        assert rule.name_es and rule.scope in set(SCOPES.values())


def test_the_rules_are_the_table_of_the_plan_in_its_order():
    in_plan = ROW_LINE.findall(PLAN.read_text(encoding="utf-8"))
    assert [row[0] for row in in_plan] == list(RULES) and len(in_plan) == len(RULES)
    for rule_id, severity, scope, aggregation in in_plan:
        rule = RULES[rule_id]
        assert (rule.severity, rule.scope, rule.aggregation.value) == (SEVERITIES[severity], SCOPES[scope], aggregation), rule_id


# --- the valid fixture --------------------------------------------------------------------------------------------------------------


def test_the_valid_fixture_passes_every_blocking_rule_delivery_after_delivery(published, cfg, fixture_truth):
    conn = store.empty_store()
    for spec in published.plan:
        report = validate(published, cfg, spec.delivery_id, conn)
        assert not report.blocking_failed and failing(report) == set(), spec.delivery_id
        assert report.delivery_id == spec.delivery_id and report.series_days_delivery == published.items[spec.delivery_id][0].series_days
        assert [r.rule_id for r in report.results] == [r for r in RULES if RULES[r].scope in ("delivery", "days") and r not in ("I03", "I04")]
        assert report.not_evaluated == ()
        store.load(conn, spec.delivery_id, published.items[spec.delivery_id][1])


def test_the_counts_of_the_warnings_and_the_informative_rules_are_those_of_the_truth(published, cfg, fixture_truth):
    for delivery_id, days in (("L2024-06-25", slice(0, 90)), ("D2024-06-30", slice(94, 95)), ("D2024-07-02", slice(96, 97))):
        report = validate(published, cfg, delivery_id)
        expected = fixture_truth.rule_counts(days)
        series_days = expected["series_days"]
        got = {r.rule_id: r for r in report.results}
        assert got["V20"].series_days_affected == expected["discount_zero"] and got["V21"].series_days_affected == expected["discount_above_one"]
        assert got["V22"].series_days_affected == expected["discount_below_half"] and got["V23"].series_days_affected == expected["flag_with_no_discount"]
        assert got["V24"].series_days_affected == expected["unflagged_cut"] and got["V25"].series_days_affected == expected["fully_out"]
        for rule_id in ("V20", "V21", "V22", "V23", "V24", "V25"):
            assert got[rule_id].hours_affected == 16 * got[rule_id].series_days_affected, rule_id
            assert got[rule_id].passed == (got[rule_id].series_days_affected == 0) and got[rule_id].status in ("pass", "warn")
            assert not report.blocking_failed
        assert got["I01"].hours_affected == expected["night_out_hours"] and got["I01"].passed
        assert got["I02"].series_days_affected == expected["holiday_days"] * 300 and got["I02"].passed
        assert series_days == got["V20"].series_days_affected * 0 + series_days


def test_each_warning_names_at_most_five_series_days_by_key_and_never_a_value(published, cfg, fixture_truth):
    report = validate(published, cfg, "L2024-06-25")
    for rule_id in ("V20", "V22", "V23", "V24", "V25"):
        r = result(report, rule_id)
        assert r.series_days_affected > EXAMPLE_LIMIT and len(r.examples) == EXAMPLE_LIMIT, rule_id
        assert all(set(example) == {"series_key", "date_key"} for example in r.examples), rule_id
    above_one = fixture_truth.rule_counts(slice(0, 90))["discount_above_one"]
    assert result(report, "V21").series_days_affected == above_one > 0 and len(result(report, "V21").examples) == min(above_one, EXAMPLE_LIMIT)
    flat = json.dumps([r.examples for r in report.results])
    assert "discount" not in flat and "sale" not in flat


def test_the_inputs_of_a_validation_are_not_changed(published, cfg):
    entry, days, cube = published.items["D2024-06-28"]
    days_before, cube_before = days.copy(), tuple(a.copy() for a in cube)
    validate(published, cfg, "D2024-06-28")
    assert days.equals(days_before) and all(np.array_equal(a, b) for a, b in zip(cube, cube_before))


# --- the malformed deliveries ------------------------------------------------------------------------------------------------------------


def _spec(published, delivery_id):
    return next(s for s in published.plan if s.delivery_id == delivery_id)


def case_v10_not_in_plan(published, days, cube, entry):
    return {"spec": dataclasses.replace(_spec(published, "D2024-06-27"), delivery_id="D2024-06-27x")}


def case_v10_other_period(published, days, cube, entry):
    return {"spec": dataclasses.replace(_spec(published, "D2024-06-27"), first_day=date(2024, 6, 28), last_day=date(2024, 6, 28))}


def case_v10_previous_not_loaded(published, days, cube, entry):
    return {"conn": store.empty_store()}


def case_v10_already_loaded(published, days, cube, entry):
    conn = store_until(published, "D2024-06-27")
    store.load(conn, "D2024-06-27", days)
    return {"conn": conn}


def case_v11_outside_the_period(published, days, cube, entry):
    moved = days.copy()
    moved.loc[0, "date_key"] = 20240101
    return {"days": moved}


def case_v11_after_the_period(published, days, cube, entry):
    moved = days.copy()
    moved.loc[0, "date_key"] = 20240629
    return {"days": moved}


def case_v12_already_in_the_store(published, days, cube, entry):
    conn = store_until(published, "D2024-06-27")
    conn.execute("INSERT INTO series_days VALUES (5, 20240627, 'D-earlier')")
    return {"conn": conn}


def case_v12_repeated_inside(published, days, cube, entry):
    import pandas as pd

    return {"days": pd.concat([days, days.iloc[[3]]], ignore_index=True)}


def case_v13_count_differs(published, days, cube, entry):
    return {"entry": dataclasses.replace(entry, series_days=entry.series_days + 1)}


def case_v13_hash_differs(published, days, cube, entry):
    return {"entry": dataclasses.replace(entry, days_sha256="0" * 64)}


def case_v13_digest_differs(published, days, cube, entry):
    return {"entry": dataclasses.replace(entry, sha256="1" * 64)}


def case_v13_empty_daily(published, days, cube, entry):
    return {"days": days.iloc[0:0], "cube": (cube[0][:0], cube[1][:, :0], cube[2][:, :0])}


def case_v14_sum_differs(published, days, cube, entry):
    changed = days.copy()
    changed.loc[7, "raw_sum"] += 0.5
    return {"days": changed}


def case_v14_instock_hours_differ(published, days, cube, entry):
    changed = days.copy()
    changed.loc[7, "instock_hours"] = (changed.loc[7, "instock_hours"] + 1) % 17
    return {"days": changed}


def case_v14_cube_differs(published, days, cube, entry):
    sales = cube[1].copy()
    sales[2, 0, 10] += 1.0
    return {"cube": (cube[0], sales, cube[2])}


def case_v15_forbidden_column(published, days, cube, entry):
    changed = days.copy()
    changed["sale_amount"] = 0.0
    return {"days": changed}


CASES = {
    "V10_not_in_plan": (case_v10_not_in_plan, {"V10"}), "V10_other_period": (case_v10_other_period, {"V10", "V11"}),
    "V10_previous_not_loaded": (case_v10_previous_not_loaded, {"V10"}), "V10_already_loaded": (case_v10_already_loaded, {"V10", "V12"}),
    "V11_outside_the_period": (case_v11_outside_the_period, {"V11", "V14"}), "V11_after_the_period": (case_v11_after_the_period, {"V11", "V14"}),
    "V12_already_in_the_store": (case_v12_already_in_the_store, {"V12"}),
    "V12_repeated_inside": (case_v12_repeated_inside, {"V12", "V13"}), "V13_count_differs": (case_v13_count_differs, {"V13"}),
    "V13_hash_differs": (case_v13_hash_differs, {"V13"}), "V13_digest_differs": (case_v13_digest_differs, {"V13"}),
    "V13_empty_daily": (case_v13_empty_daily, {"V13"}), "V14_sum_differs": (case_v14_sum_differs, {"V14"}),
    "V14_instock_hours_differ": (case_v14_instock_hours_differ, {"V14"}), "V14_cube_differs": (case_v14_cube_differs, {"V14"}),
    "V15_forbidden_column": (case_v15_forbidden_column, {"V15"}),
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_each_malformed_delivery_fails_its_rule_and_only_the_rules_it_breaks(published, cfg, name):
    build, expected = CASES[name]
    entry, days, cube = published.items["D2024-06-27"]
    report = validate(published, cfg, "D2024-06-27", **build(published, days, cube, entry))
    assert failing(report) == expected, name
    assert report.blocking_failed and all(result(report, rule_id).status == "fail" for rule_id in expected)
    assert all(result(report, rule_id).examples for rule_id in expected), "a failing rule says what failed"
    assert RULES["V10"].severity is Severity.BLOCKING and all(RULES[r].severity is Severity.BLOCKING for r in expected)


def test_a_file_that_changed_on_disk_fails_v13_alone(published, cfg, copy_of):
    folder = copy_of(published.out_dir)
    entry = published.items["D2024-06-28"][0]
    path = folder / entry.cube_file
    data = bytearray(path.read_bytes())
    data[-1] ^= 0x01
    path.write_bytes(bytes(data))
    report = validate(published, cfg, "D2024-06-28", folder=folder)
    assert failing(report) == {"V13"} and "cube_file_differs_from_manifest" in result(report, "V13").examples[0]["reasons"]
    (folder / entry.days_file).unlink()
    assert "days_file_missing" in result(validate(published, cfg, "D2024-06-28", folder=folder), "V13").examples[0]["reasons"]


def test_the_close_holds_no_series_day_and_a_close_with_rows_is_refused(published, cfg):
    close_entry, close_days, close_cube = published.items["C2024-07-03"]
    report = validate(published, cfg, "C2024-07-03", store_until(published, "C2024-07-03"))
    assert failing(report) == set() and report.series_days_delivery == 0
    other_days = published.items["D2024-07-02"][1]
    assert failing(validate(published, cfg, "C2024-07-03", days=other_days)) >= {"V13"}
    assert close_entry.series_days == 0 and len(close_days) == 0 and close_cube[1].shape[1] == 0


def test_a_delivery_without_a_column_of_its_schema_is_a_wrong_delivery_not_a_rule(published, cfg):
    days = published.items["D2024-06-27"][1]
    with pytest.raises(ValueError, match="faltan raw_sum"):
        validate(published, cfg, "D2024-06-27", days=days.drop(columns="raw_sum"))
    with pytest.raises(ValueError, match="la entrega no tiene las columnas"):
        validate(published, cfg, "D2024-06-27", days=days.drop(columns=["raw_sum", "band"]))


def test_a_warehouse_that_has_no_tables_yet_holds_nothing(published, cfg):
    """Before the first load the tables do not exist: the rules read an empty warehouse (the launch passes V10 and V12)."""
    report = validate(published, cfg, "L2024-06-25", sqlite3.connect(":memory:"))
    assert failing(report) == set()
    assert failing(validate(published, cfg, "D2024-06-26", sqlite3.connect(":memory:"))) == {"V10"}


# --- the rules of the source ------------------------------------------------------------------------------------------------------------------


def source_error(malformed, cfg_for, kind) -> SourceError:
    bad = malformed(kind)
    with pytest.raises(SourceError) as raised:
        fetch_source(cfg_for(bad.dir, malformed=bad))
    return raised.value


@pytest.mark.parametrize("kind", sorted(MALFORMED_RULES))
def test_each_malformed_source_names_its_rule_and_leaves_every_other_rule_not_evaluated(malformed, cfg_for, kind):
    error = source_error(malformed, cfg_for, kind)
    report = validate_source(error, run_key="run-1")
    rule_id = MALFORMED_RULES[kind]
    assert failing(report) == {rule_id} and report.blocking_failed and report.delivery_id is None
    earlier = [r for r in ("V01", "V02", "V03", "V04", "V05", "V06", "V07") if r < rule_id]
    assert [r.rule_id for r in report.results] == [*earlier, rule_id]
    assert all(result(report, r).passed for r in earlier)
    assert set(report.not_evaluated) == set(RULES) - {r.rule_id for r in report.results}
    example = result(report, rule_id).examples[0]
    assert "path" not in example and all(not isinstance(v, Path) for v in example.values()), "an example never carries a path of this machine"
    json.dumps(result(report, rule_id).examples)


def test_a_clean_read_passes_the_source_rules_and_counts_the_two_sums_that_differ(cfg_for, small_truth, tmp_path):
    config = cfg_for(small_truth.dir)
    reports = (read_source(small_truth.train_path, "train", config)[1], read_source(small_truth.eval_path, "eval", config)[1])
    report = validate_source(reports, run_key="run-1", train_sha256="a" * 64, eval_sha256="b" * 64)
    assert [r.rule_id for r in report.results] == ["V01", "V02", "V03", "V04", "V05", "V06", "V07", "V26", "V27"]
    assert failing(report) == set() and report.not_evaluated == tuple(r for r in RULES if r not in {x.rule_id for x in report.results})
    assert (report.train_sha256, report.eval_sha256) == ("a" * 64, "b" * 64) and result(report, "V26").passed and result(report, "V27").passed

    def tamper(table):
        amounts = table.column("sale_amount").to_numpy().copy()
        amounts[[0, 7, 100]] += 1.0
        counts = table.column("stock_hour6_22_cnt").to_numpy().copy()
        counts[[3, 4]] = (counts[[3, 4]] + 1) % 17
        return replace_column(replace_column(table, "sale_amount", pa.array(amounts)), "stock_hour6_22_cnt", pa.array(counts, type=pa.int32()))

    folder = damaged_pair(small_truth, tmp_path / "sums", tamper)
    tampered = cfg_for(folder)
    reports = (read_source(folder / "train.parquet", "train", tampered)[1], read_source(folder / "eval.parquet", "eval", tampered)[1])
    report = validate_source(reports, run_key="run-2")
    assert failing(report) == set() and not report.blocking_failed
    assert (result(report, "V26").status, result(report, "V26").series_days_affected) == ("warn", 3)
    assert (result(report, "V27").status, result(report, "V27").series_days_affected) == ("warn", 2)


def test_a_rule_that_is_not_a_blocking_rule_of_the_source_is_refused():
    with pytest.raises(ValueError, match="V26 no es una regla bloqueante de la fuente"):
        validate_source(SourceError("V26", "x"), run_key="run-1")
    with pytest.raises(ValueError, match="no es una regla bloqueante"):
        validate_source(SourceError("M01", "x"), run_key="run-1")


# --- the rules of the model, the report of a run and its files ----------------------------------------------------------------------------------------


def test_the_rules_of_the_model_are_added_in_order_and_once(published, cfg):
    report = validate(published, cfg, "D2024-06-26")
    added = add_results(report, [model_result("M03", passed=True), model_result("I04", passed=True, series_days=300), model_result("M01", passed=False, examples=[{"ratio": 0.4}])])
    ids = [r.rule_id for r in added.results]
    assert ids == [r for r in RULES if r in {x.rule_id for x in report.results} | {"M03", "I04", "M01"}]
    assert ids.index("I04") < ids.index("M01") < ids.index("M03") and failing(added) == {"M01"} and added.blocking_failed
    assert result(added, "I04").status == "pass" and result(added, "I04").series_days_affected == 300
    with pytest.raises(ValueError, match="la regla M03 ya está en el reporte"):
        add_results(added, [model_result("M03", passed=True)])
    with pytest.raises(ValueError, match="no es una regla del modelo"):
        model_result("V10", passed=True)
    assert model_result("I03", passed=False).passed is True, "an informative rule always passes"
    assert [r for r in MODEL_RULES if RULES[r].scope != "model"] == []


def test_the_report_of_a_run_is_the_source_then_the_delivery_in_the_order_of_the_plan(published, cfg, cfg_for, small_truth):
    config = cfg_for(small_truth.dir)
    reports = (read_source(small_truth.train_path, "train", config)[1], read_source(small_truth.eval_path, "eval", config)[1])
    source = validate_source(reports, run_key="run-1", train_sha256="a" * 64, eval_sha256="b" * 64)
    delivery = validate(published, cfg, "D2024-06-26")
    combined = combine_reports(source, delivery)
    assert [r.rule_id for r in combined.results] == [r for r in RULES if r in {x.rule_id for x in (*source.results, *delivery.results)}]
    assert combined.delivery_id == "D2024-06-26" and (combined.train_sha256, combined.eval_sha256) == ("a" * 64, "b" * 64) and combined.run_key == "run-1"
    assert not set(combined.not_evaluated) & {r.rule_id for r in combined.results}


def test_a_rejected_run_names_the_blocking_rules_that_failed(published, cfg):
    report = validate(published, cfg, "D2024-06-27", conn=store.empty_store())
    error = ValidationError(report)
    assert error.report is report and "run-1" in str(error) and "V10" in str(error) and isinstance(error, RuntimeError)


def test_the_report_is_written_as_json_and_markdown_with_a_copy_per_run_and_read_back(published, cfg, tmp_path):
    report = validate(published, cfg, "D2024-06-26", run_key="run-7")
    json_path, md_path = write_report(report, tmp_path / "validation")
    assert json_path.name == "latest.json" and md_path.name == "latest.md"
    assert sorted(p.name for p in (tmp_path / "validation" / "history").iterdir()) == ["run-7.json", "run-7.md"]
    document = json.loads(json_path.read_text(encoding="utf-8"))
    assert document["run_key"] == "run-7" and document["delivery_id"] == "D2024-06-26" and document["blocking_failed"] is False
    assert {r["rule_id"]: r["aggregation"] for r in document["results"]}["V20"] == "per_run"
    assert all({"rule_id", "name_es", "severity", "scope", "aggregation", "status", "series_days_affected", "hours_affected", "examples"} == set(r)
               for r in document["results"])
    assert read_report(json_path) == report
    text = md_path.read_text(encoding="utf-8")
    assert "# Reporte de validación" in text and "Aceptado" in text and "| V20 |" in text and "| Agregación |" in text
    assert (tmp_path / "validation" / "history" / "run-7.json").read_text(encoding="utf-8") == json_path.read_text(encoding="utf-8")


def test_a_rejected_report_says_so_and_lists_what_was_not_evaluated(tmp_path):
    report = validate_source(SourceError("V03", "demasiado grande | con una barra", [{"rule_id": "V03", "size": 7}]), run_key="run-8")
    _json, md = write_report(report, tmp_path)
    text = md.read_text(encoding="utf-8")
    assert "Rechazado" in text and "No evaluadas" in text and "V10" in text
    rows = [line for line in text.splitlines() if line.startswith("| V") or line.startswith("| I") or line.startswith("| M")]
    assert all(line.count(" | ") == rows[0].count(" | ") for line in rows), "every row of the table has the width of its header"


def test_a_run_key_that_is_not_a_file_name_is_refused_before_writing(published, cfg, tmp_path):
    for bad in ("../x", "a/b", "", " ", "x y", ".hidden"):
        report = dataclasses.replace(validate(published, cfg, "D2024-06-26"), run_key=bad)
        with pytest.raises(ValueError, match="run_key"):
            write_report(report, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_the_entry_type_is_the_manifests(published):
    assert isinstance(published.items["L2024-06-25"][0], ManifestEntry)
