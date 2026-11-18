"""The summary after the seal (U11; RF19, D21; AC19): a warehouse without the sealed rows takes C01 to C09 from the seal, each one rebuilt and compared with its entry to
6 decimals, and a seal entry that does not rebuild is not taken."""

from __future__ import annotations

import copy
import json
import shutil
from dataclasses import replace

import pytest

from promolift.evaluation import criteria_from_seal
from promolift.registry import SealError, read_seal
from promolift.reporting import build_summary, summary_markdown, write_summary
from promolift.warehouse import connect


def test_a_warehouse_without_sealed_rows_takes_the_sealed_result_from_the_seal(evaluated_week, week_copy, tmp_path):
    with_rows = connect(evaluated_week.db)
    try:
        sealed = build_summary(with_rows, evaluated_week.view, run=replace(evaluated_week.run, run_key="run-later"), seal_path=evaluated_week.seal)
    finally:
        with_rows.close()
    assert sealed["evaluation_status"] == "sealed" and "sealed_from" not in sealed and [c["criterion_id"] for c in sealed["criteria"]] == [f"C{k:02d}" for k in range(1, 11)]
    w = week_copy()                                       # a rebuild: the warehouse has the days but not the sealed rows, the seal has its test part
    shutil.copyfile(evaluated_week.seal, w.seal)
    from_seal = build_summary(w.conn, w.view, run=replace(w.run, run_key="run-rebuilt"), seal_path=w.seal)
    assert from_seal["evaluation_status"] == "sealed" and from_seal["sealed_from"] == "seal" and from_seal["seal"]["test_run_key"] == "run-close"
    for mine, theirs in zip(from_seal["criteria"], sealed["criteria"], strict=True):
        assert mine["criterion_id"] == theirs["criterion_id"] and mine["passed"] == theirs["passed"] and mine["verdict_es"] == theirs["verdict_es"]
        for key in ("value", "baseline_value", "ci_low", "ci_high"):
            assert mine[key] == pytest.approx(theirs[key], abs=1e-6) if theirs[key] is not None else mine[key] is None
    markdown = summary_markdown(from_seal)
    assert "(tomados del sello)" in markdown and "Estado: sealed" in markdown
    paths = write_summary(from_seal, tmp_path / "reports")
    assert json.loads(paths[0].read_text(encoding="utf-8"))["sealed_from"] == "seal" and paths[1].read_text(encoding="utf-8") == markdown


def test_a_seal_entry_that_does_not_rebuild_is_refused(evaluated_week, week_copy):
    document = read_seal(evaluated_week.seal)
    assert [c.criterion_id for c in criteria_from_seal(document)] == [f"C{k:02d}" for k in range(1, 11)]
    for change in (lambda d: d["test"]["criteria"][0].update(passed=not d["test"]["criteria"][0]["passed"]),
                   lambda d: d["test"]["criteria"][3].update(verdict_es="La prueba dice otra cosa."),
                   lambda d: d["test"]["criteria"][4].update(value=d["test"]["criteria"][4]["value"] + 0.001)):
        tampered = copy.deepcopy(document)
        change(tampered)
        with pytest.raises(SealError, match="C0"):
            criteria_from_seal(tampered)
    w = week_copy()
    broken = copy.deepcopy(document)
    broken["test"]["criteria"][5]["value"] = 0.123456
    w.seal.write_text(json.dumps(broken, sort_keys=True, indent=1), encoding="utf-8")
    with pytest.raises(SealError, match="C06"):
        build_summary(w.conn, w.view, run=replace(w.run, run_key="run-rebuilt"), seal_path=w.seal)
    with pytest.raises(SealError, match="no tiene la parte de la prueba"):
        criteria_from_seal({"launch": document["launch"]})


def test_before_the_close_the_summary_is_pending_says_when_the_test_is_evaluated_and_shows_the_validation_with_its_blocks(week_copy):
    w = week_copy()
    summary = build_summary(w.conn, w.view, run=replace(w.run, run_key="run-before"), seal_path=w.seal)
    assert summary["evaluation_status"] == "pending" and summary["pending_reason_es"].startswith("La prueba se evalúa con el cierre del 2024-07-03")
    assert all(c["passed"] is None and c["verdict_es"].startswith("Pendiente") for c in summary["criteria"]) and len(summary["criteria"]) == 10
    v2 = summary["validation"]["recovery_v2"]
    assert v2["fit_blocks"] == "train" and {"r1"} <= set(v2["methods"]) and all(m["wape_series"] > 0 for m in v2["methods"].values())
    assert "La prueba se evalúa con el cierre del 2024-07-03" in summary_markdown(summary)
