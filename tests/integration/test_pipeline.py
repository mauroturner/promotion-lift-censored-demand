"""The tasks of a run, their state, the ordered close and the refusals (U16; AC07, AC27, AC28, AC29, AC35; plan, sections 3 and 22; D25, D26; ported from project 05's tests): a closed
run refuses every task and keeps its records, a run that did not load its own delivery writes nothing, a load needs a passed validation of its own run, the failure handler never
hides the task's error, a rejected run changes no published file, the close writes in its order, the commands hold the single-writer lock, and the flow wraps what the functions
it calls do.

The flow runs over the 60-series fixture (``tests/fixtures/pipeline_state.py``): the launch, seven daily deliveries and the close. A test that writes works on a copy of the
state a session fixture built."""

from __future__ import annotations

import dataclasses
import json
import logging
import sqlite3
import tempfile
import threading
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from promolift import lock, pipeline
from promolift.deliveries import MANIFEST_NAME, mark_delivery, read_manifest
from promolift.export import verify_star_schema
from promolift.pipeline import TASK_IDS, RunLockedError, RunRefusedError, RunStateError, UsageError
from promolift.site_export import SiteExportError
from promolift.validate import ValidationError
from tests.fixtures.pipeline_state import (
    CLOSE_ID,
    DAILY_ID,
    LAUNCH_ID,
    content_of,
    copy_state,
    published_digest,
    query,
    runs_of,
    state_of,
    tamper_delivery,
    tree_digest,
    tree_state,
)


def advance(cfg, run_key: str, upto: str) -> None:
    """The tasks of a run from the first to `upto`, each as the DAG runs it."""
    for task_id in TASK_IDS[: TASK_IDS.index(upto) + 1]:
        pipeline.run_task(task_id, run_key, cfg)


def state_file(cfg, run_key: str) -> dict:
    return json.loads((Path(cfg.paths.interim_dir) / "runs" / f"{run_key}.json").read_text(encoding="utf-8"))


def from_another_thread(call):
    """The error `call` raises when another thread of this process holds the lock (the lock refuses a second thread of its own process), or None."""
    outcome: dict[str, BaseException] = {}

    def target() -> None:
        try:
            call()
        except BaseException as error:
            outcome["error"] = error

    thread = threading.Thread(target=target)
    thread.start()
    thread.join(timeout=120)
    return outcome.get("error")


def manifest_of(cfg) -> Path:
    return Path(cfg.paths.raw_dir) / "deliveries" / MANIFEST_NAME


# --- the RED of U16 ------------------------------------------------------------------------------------------------------------


def test_closed_run_refuses_every_task_and_keeps_its_records(pipeline_replayed, tmp_path, quick_cfg):
    """AC28: every task of a run that ended, ``ok`` or ``no_delivery``, is refused before anything is written (exit 2): the state files, the warehouse, the exported files and the
    reports are the same bytes afterwards, and so are the rows of ``pipeline_runs``."""
    state = copy_state(pipeline_replayed, tmp_path / "state", quick_cfg)
    cfg = state.cfg
    closed = [key for key, status in runs_of(cfg).items() if status in ("ok", "no_delivery")]
    assert sorted(runs_of(cfg).values()) == ["no_delivery"] + ["ok"] * 9 and len(closed) == 10
    before, rows = tree_digest(state.root), query(cfg, "SELECT * FROM pipeline_runs ORDER BY run_key")
    for run_key in (closed[0], closed[-1], "idle"):
        for task_id in TASK_IDS:
            with pytest.raises(RunRefusedError, match="está cerrada") as refused:
                pipeline.run_task(task_id, run_key, cfg)
            assert refused.value.exit_code == 2
        with pytest.raises(RunRefusedError, match="está cerrada"):
            pipeline.run_all(cfg, only=["report"], run_key=run_key)
    assert tree_digest(state.root) == before and query(cfg, "SELECT * FROM pipeline_runs ORDER BY run_key") == rows


def test_a_task_of_a_run_that_did_not_load_its_own_delivery_is_refused_and_writes_nothing(pipeline_staged, tmp_path, quick_cfg):
    """AC28: after ``load`` every task works on the delivery its own run loaded. A run that holds a delivery nobody loaded is refused, and so is one whose delivery another run
    loaded (it names the run that did); neither writes a byte."""
    state = copy_state(pipeline_staged("deliver"), tmp_path / "state", quick_cfg)
    cfg = state.cfg
    assert state_file(cfg, "a")["tasks"]["deliver"]["delivery_id"] == DAILY_ID
    before = tree_state(state.root)
    for task_id in TASK_IDS[TASK_IDS.index("recover"):]:
        with pytest.raises(RunRefusedError, match="no la cargó") as refused:
            pipeline.run_task(task_id, "a", cfg)
        assert refused.value.exit_code == 2
    assert tree_state(state.root) == before
    advance(cfg, "owner", "load")
    assert query(cfg, "SELECT run_key FROM deliveries WHERE delivery_id = ?", (DAILY_ID,)) == [("owner",)]
    before = tree_state(state.root)
    for task_id in TASK_IDS[TASK_IDS.index("load"):]:
        with pytest.raises(RunRefusedError, match="la cargó la corrida owner") as refused:
            pipeline.run_task(task_id, "a", cfg)
        assert refused.value.exit_code == 2
    assert tree_state(state.root) == before


def test_load_is_refused_without_a_passed_validation_of_this_run(pipeline_staged, tmp_path, quick_cfg):
    """AC28: ``load`` needs the validation report of its own run, and the last run's ``latest.json`` does not stand in for it; a report with a blocking rule that fails refuses it
    too. Nothing is written by the refusals: the delivery is not in the warehouse and the run has no row."""
    state = copy_state(pipeline_staged("deliver"), tmp_path / "state", quick_cfg)
    cfg = state.cfg
    assert (Path(cfg.paths.reports_dir) / "validation" / "latest.json").is_file()      # the launch run's, not this one's
    before = tree_state(state.root)
    with pytest.raises(RunRefusedError, match="no validó su entrega") as refused:
        pipeline.run_task("load", "a", cfg)
    assert refused.value.exit_code == 2 and tree_state(state.root) == before
    tamper_delivery(cfg, DAILY_ID)
    with pytest.raises(ValidationError, match="V13"):
        pipeline.run_task("validate", "a", cfg)
    before = tree_state(state.root)
    with pytest.raises(RunRefusedError, match="rechazó su entrega") as refused:
        pipeline.run_task("load", "a", cfg)
    assert refused.value.exit_code == 2 and tree_state(state.root) == before
    assert query(cfg, "SELECT COUNT(*) FROM series_days WHERE delivery_id = ?", (DAILY_ID,)) == [(0,)] and "a" not in runs_of(cfg)


def test_failure_handler_write_errors_do_not_mask_the_task_error(pipeline_staged, tmp_path, quick_cfg, monkeypatch, caplog):
    """AC27: when a task fails after ``load``, the handler tries each of its writes on its own (the state file, the run's row, the run table, the summary, the HTML), and when every
    one of them fails too the caller sees the task's error, and each failure is in the log."""
    state = copy_state(pipeline_staged("recover"), tmp_path / "state", quick_cfg)
    cfg = state.cfg
    attempts: list[str] = []

    def fails(step: str, error: Exception):
        def write(*args, **kwargs):
            attempts.append(step)
            raise error

        return write

    def estimating_blew_up(*args, **kwargs):
        raise RuntimeError("estimating blew up")

    monkeypatch.setattr(pipeline, "estimate_delivery", estimating_blew_up)
    monkeypatch.setattr(pipeline, "write_atomic", fails("state", PermissionError(13, "denied")))
    monkeypatch.setattr(pipeline, "record_run", fails("sqlite", sqlite3.OperationalError("database is locked")))
    monkeypatch.setattr(pipeline, "export_run_table", fails("run_table", OSError("disk full")))
    monkeypatch.setattr(pipeline, "export_summary", fails("summary", OSError("disk full")))
    monkeypatch.setattr(pipeline, "render_design", fails("html", OSError("disk full")))
    with caplog.at_level(logging.WARNING, logger="promolift.pipeline"):
        with pytest.raises(RuntimeError, match="^estimating blew up$"):
            pipeline.run_task("estimate", "a", cfg)
    assert attempts == ["state", "sqlite", "run_table", "summary", "html"]
    warned = [r for r in caplog.records if r.levelno == logging.WARNING]
    errors = [str(r.exc_info[1]) for r in warned if r.exc_info]
    assert len(warned) == 5 and all("run a" in r.getMessage() for r in warned)
    assert errors == ["[Errno 13] denied", "database is locked", "disk full", "disk full", "disk full"]


def test_a_task_from_load_on_of_a_run_that_holds_no_delivery_is_refused_before_its_state_file_is_written(pipeline_launched, tmp_path, quick_cfg):
    """AC28, B2 of project 05's evaluation: ``task load`` (or any later one) of a new run has no delivery of its own: it is refused with exit 2 before the state file of the run is
    created, so nothing is written and no run is left ``failed``; the tasks before ``load`` open a new run as before."""
    state = copy_state(pipeline_launched, tmp_path / "state", quick_cfg)
    cfg = state.cfg
    before = tree_state(state.root)
    for task_id in TASK_IDS[TASK_IDS.index("load"):]:
        with pytest.raises(RunRefusedError, match="no tiene una entrega") as refused:
            pipeline.run_task(task_id, "fresh", cfg)
        assert refused.value.exit_code == 2
    assert tree_state(state.root) == before and not (Path(cfg.paths.interim_dir) / "runs" / "fresh.json").exists() and runs_of(cfg) == {"launch": "ok"}
    assert pipeline.run_task("fetch_source", "fresh", cfg)["train_sha256"] and state_file(cfg, "fresh")["status"] == "running"


def test_closing_never_creates_a_run_row(pipeline_staged, tmp_path, quick_cfg):
    """AC28: the row of ``pipeline_runs`` is ``load``'s. A run whose row is not there is not closed by ``report``, which says so, and the failure it records creates no row either."""
    state = copy_state(pipeline_staged("load"), tmp_path / "state", quick_cfg)
    cfg = state.cfg
    conn = sqlite3.connect(cfg.paths.warehouse)
    try:
        conn.execute("DELETE FROM pipeline_runs WHERE run_key = 'a'")
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(RunStateError, match="no tiene su fila en pipeline_runs"):
        pipeline.run_task("report", "a", cfg)
    assert query(cfg, "SELECT COUNT(*) FROM pipeline_runs WHERE run_key = 'a'") == [(0,)]
    assert state_file(cfg, "a")["status"] == "failed"


def test_report_leaves_the_validation_report_of_its_own_run_as_the_latest(pipeline_staged, tmp_path, quick_cfg):
    """Plan section 3, step 11: ``reports/validation/latest.*`` is the report of the run that closes, whatever another run wrote there while this one was open. ``report`` writes it
    before it closes anything; here it stops at the summary, which belongs to another run's export."""
    state = copy_state(pipeline_staged("load"), tmp_path / "state", quick_cfg)
    cfg = state.cfg
    validation = Path(cfg.paths.reports_dir) / "validation"
    (validation / "latest.json").write_text((validation / "history" / "launch.json").read_text(encoding="utf-8"), encoding="utf-8")
    assert json.loads((validation / "latest.json").read_text(encoding="utf-8"))["run_key"] == "launch"
    with pytest.raises(SiteExportError, match="otra corrida"):
        pipeline.run_task("report", "a", cfg)
    assert (validation / "latest.json").read_bytes() == (validation / "history" / "a.json").read_bytes()
    assert (validation / "latest.md").read_bytes() == (validation / "history" / "a.md").read_bytes()


# --- AC07: a rejected run --------------------------------------------------------------------------------------------------


def test_a_rejected_run_leaves_every_published_file_and_the_warehouse_byte_identical(pipeline_staged, tmp_path, quick_cfg):
    """AC07: a delivery that fails a blocking rule is rejected (the manifest says so, the report names the rule), and the SQLite file, every Parquet of the star model, the HTML,
    every JSON of the site and the seal are the same bytes as before; so is a source that is not the pinned one."""
    state = copy_state(pipeline_staged("deliver"), tmp_path / "state", quick_cfg)
    cfg = state.cfg
    before = published_digest(cfg)
    assert len(before) > 25 and runs_of(cfg) == {"launch": "ok"}
    tamper_delivery(cfg, DAILY_ID)
    with pytest.raises(ValidationError, match="V13"):
        pipeline.run_task("validate", "a", cfg)
    assert published_digest(cfg) == before and runs_of(cfg) == {"launch": "ok"}
    assert state_file(cfg, "a")["status"] == "rejected" and state_file(cfg, "a")["tasks"]["validate"]["rules"]
    assert {e.delivery_id: e.status for e in read_manifest(manifest_of(cfg))}[DAILY_ID] == "rejected"
    report = json.loads((Path(cfg.paths.reports_dir) / "validation" / "history" / "a.json").read_text(encoding="utf-8"))
    assert report["blocking_failed"] is True


def test_a_v01_rejection_writes_only_the_validation_report_and_the_run_state(pipeline_launched, tmp_path, quick_cfg):
    """AC07, V01: a source that is not the pinned one changes neither the warehouse, nor the model, nor the seal, nor any file of ``outputs/`` or the dashboard; what it writes is
    the validation report (``latest`` and the run's copy in ``history/``), which records the rejection, and the state of the rejected run."""
    state = copy_state(pipeline_launched, tmp_path / "state", quick_cfg)
    cfg = state.cfg
    source = Path(cfg.source.train_path)
    source.write_bytes(source.read_bytes() + b"changed after the hash was pinned")
    before = tree_state(state.root)
    with pytest.raises(ValidationError, match="V01"):
        pipeline.run_task("fetch_source", "v01", cfg)
    after = tree_state(state.root)
    changed = sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))
    changed = [path for path in changed if path != "source/train.parquet"]
    assert changed == ["interim/runs/v01.json", "reports/validation/history/v01.json", "reports/validation/history/v01.md",
                       "reports/validation/latest.json", "reports/validation/latest.md"]
    latest = json.loads((Path(cfg.paths.reports_dir) / "validation" / "latest.json").read_text(encoding="utf-8"))
    assert latest["blocking_failed"] is True and latest["run_key"] == "v01"
    assert state_file(cfg, "v01")["status"] == "rejected" and runs_of(cfg) == {"launch": "ok"}


# --- the close ------------------------------------------------------------------------------------------------------------------


def test_a_run_closes_in_order_sqlite_the_run_table_the_summary_the_html_and_only_then_the_delivery(pipeline_staged, tmp_path, quick_cfg, monkeypatch):
    """AC27, plan section 3: ``report`` closes the run in SQLite, rewrites the run table alone, then ``summary.json`` with the manifest, then the HTML, and only then does the
    delivery become ``loaded`` in the manifest of deliveries: the state of the run, of its exported run table, of its summary and of its delivery as each step starts."""
    state = copy_state(pipeline_staged("render_dashboard"), tmp_path / "state", quick_cfg)
    cfg = state.cfg
    seen: list[tuple[str, str, str, str, str]] = []

    def snapshot(step: str) -> None:
        table = {r["run_key"]: r["status"] for r in pq.read_table(Path(cfg.paths.outputs_dir) / "dim_pipeline_run.parquet").to_pylist()}
        summary = json.loads((Path(cfg.paths.site_dir) / "summary.json").read_text(encoding="utf-8"))["status"]
        delivery = {e.delivery_id: e.status for e in read_manifest(manifest_of(cfg))}[DAILY_ID]
        seen.append((step, query(cfg, "SELECT status FROM pipeline_runs WHERE run_key = 'a'")[0][0], table["a"], summary, delivery))

    for step, closer in dict(pipeline._CLOSERS).items():
        monkeypatch.setitem(pipeline._CLOSERS, step, lambda ctx, step=step, closer=closer: (snapshot(step), closer(ctx))[1])
    result = pipeline.run_task("report", "a", cfg)
    assert [s[0] for s in seen] == list(pipeline.CLOSING_STEPS) == ["sqlite", "run_table", "summary", "html", "manifest"]
    assert seen == [("sqlite", "running", "running", "running", "published"), ("run_table", "ok", "running", "running", "published"),
                    ("summary", "ok", "ok", "running", "published"), ("html", "ok", "ok", "ok", "published"), ("manifest", "ok", "ok", "ok", "published")]
    assert {e.delivery_id: (e.status, e.run_key) for e in read_manifest(manifest_of(cfg))}[DAILY_ID] == ("loaded", "a")
    assert result["run_status"] == "ok" and state_file(cfg, "a")["status"] == "ok" and verify_star_schema(cfg.paths.outputs_dir) == []
    assert json.loads((Path(cfg.paths.reports_dir) / "validation" / "latest.json").read_text(encoding="utf-8"))["run_key"] == "a"


def test_a_failure_at_the_html_leaves_the_run_failed_and_its_delivery_published_until_the_task_is_repeated(pipeline_staged, tmp_path, quick_cfg, monkeypatch):
    """AC27: the delivery is marked ``loaded`` last, so a close that stopped at the HTML left the run ``failed`` (in the state file, in SQLite and in the run table, whose set still
    verified) and the delivery ``published``; repeating ``report`` with the same run key closed it."""
    state = copy_state(pipeline_staged("render_dashboard"), tmp_path / "state", quick_cfg)
    cfg = state.cfg
    real = pipeline.render_design
    monkeypatch.setattr(pipeline, "render_design", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")) if _closing.get("on") else real(*a, **k))
    _closing = {"on": True}
    with pytest.raises(OSError, match="disk full"):
        pipeline.run_task("report", "a", cfg)
    table = {r["run_key"]: r["status"] for r in pq.read_table(Path(cfg.paths.outputs_dir) / "dim_pipeline_run.parquet").to_pylist()}
    assert state_file(cfg, "a")["status"] == "failed" and runs_of(cfg)["a"] == "failed" and table["a"] == "failed" and verify_star_schema(cfg.paths.outputs_dir) == []
    assert {e.delivery_id: e.status for e in read_manifest(manifest_of(cfg))}[DAILY_ID] == "published"
    _closing["on"] = False
    pipeline.run_task("report", "a", cfg)
    assert runs_of(cfg)["a"] == "ok" and state_file(cfg, "a")["status"] == "ok"
    assert {e.delivery_id: e.status for e in read_manifest(manifest_of(cfg))}[DAILY_ID] == "loaded"


def test_a_failure_after_load_marks_the_run_failed_everywhere_without_a_path_and_a_repeat_reopens_it(pipeline_staged, tmp_path, quick_cfg, monkeypatch):
    """AC27, RNF12: a failure after ``load`` leaves ``failed`` in the state file (with the traceback), in SQLite and in the run table, and rewrites no other exported file; the message
    of the run says the task and the kind of error and carries no path of this machine (the run table is published); repeating the task reopens the run as ``running``."""
    state = copy_state(pipeline_staged("recover"), tmp_path / "state", quick_cfg)
    cfg = state.cfg
    exported = {name: digest for name, digest in published_digest(cfg).items() if name.startswith(("outputs/", "dashboard/", "reports/"))}
    real = pipeline.estimate_delivery

    def blew_up(*args, **kwargs):
        raise ValueError(f"cannot read {Path(cfg.paths.warehouse)} or {tmp_path / 'elsewhere' / 'file.bin'}")

    monkeypatch.setattr(pipeline, "estimate_delivery", blew_up)
    with pytest.raises(ValueError, match="cannot read"):
        pipeline.run_task("estimate", "a", cfg)
    saved = state_file(cfg, "a")
    assert saved["status"] == "failed" and saved["tasks"]["estimate"]["status"] == "failed" and "cannot read" in saved["tasks"]["estimate"]["traceback"]
    [(status, finished, message)] = query(cfg, "SELECT status, finished_at, message FROM pipeline_runs WHERE run_key = 'a'")
    assert status == "failed" and finished is not None and message == "estimate: ValueError: cannot read <path> or <path>"
    table = pq.read_table(Path(cfg.paths.outputs_dir) / "dim_pipeline_run.parquet").to_pylist()
    assert {r["run_key"]: r["status"] for r in table}["a"] == "failed" and verify_star_schema(cfg.paths.outputs_dir) == []
    assert str(tmp_path).encode() not in (Path(cfg.paths.outputs_dir) / "dim_pipeline_run.parquet").read_bytes()
    after = published_digest(cfg)
    changed = {name for name, digest in exported.items() if after[name] != digest}
    assert changed <= {"outputs/powerbi/dim_pipeline_run.parquet", "outputs/powerbi/manifest.json", "dashboard/powerbi-design.html", "outputs/site/summary.json",
                       "outputs/site/manifest.json"} and "outputs/powerbi/dim_pipeline_run.parquet" in changed
    monkeypatch.setattr(pipeline, "estimate_delivery", real)
    pipeline.run_task("estimate", "a", cfg)
    assert state_file(cfg, "a")["status"] == "running" and query(cfg, "SELECT status, finished_at, message FROM pipeline_runs WHERE run_key = 'a'") == [("running", None, "")]


def test_repeating_a_task_of_a_run_replaces_its_rule_results_and_does_not_fail_on_them(pipeline_staged, tmp_path, quick_cfg):
    """A task that adds rule results to the run's report (``fit_model`` adds M03 and M05) can be run again by the same run (a retry, ``--from fit_model``): its results replace the
    earlier ones, in the report and in ``validation_results``, and the report keeps the rules of the validation."""
    state = copy_state(pipeline_staged("fit_model"), tmp_path / "state", quick_cfg)
    cfg = state.cfg
    first = query(cfg, "SELECT rule_id, passed FROM validation_results WHERE run_key = 'a' ORDER BY rule_id")
    assert {"M03", "M05", "V10", "V13"} <= {rule for rule, _ in first}
    pipeline.run_task("fit_model", "a", cfg)
    assert query(cfg, "SELECT rule_id, passed FROM validation_results WHERE run_key = 'a' ORDER BY rule_id") == first
    report = json.loads((Path(cfg.paths.reports_dir) / "validation" / "history" / "a.json").read_text(encoding="utf-8"))
    assert sorted(r["rule_id"] for r in report["results"]) == [rule for rule, _ in first]


def test_a_run_with_no_delivery_records_no_delivery_and_refreshes_only_the_run_table_and_the_design(pipeline_replayed):
    """AC27, plan section 3, step 2: with nothing pending the run is ``no_delivery`` (its row, its state), the flow stops after ``deliver``, and what was exported is refreshed: the
    run table and the HTML, nothing else (the summary and the site are those of the run that loaded the last delivery)."""
    state, cfg = pipeline_replayed, pipeline_replayed.cfg
    assert [t["task"] for t in state.idle] == ["fetch_source", "deliver"] and state.idle[-1]["result"]["delivered"] is False
    [(status, delivery, finished, message)] = query(cfg, "SELECT status, delivery_id, finished_at, message FROM pipeline_runs WHERE run_key = 'idle'")
    assert (status, delivery) == ("no_delivery", None) and finished is not None and "no hay entregas pendientes" in message
    assert state_file(cfg, "idle")["status"] == "no_delivery"
    table = {r["run_key"]: r["status"] for r in pq.read_table(Path(cfg.paths.outputs_dir) / "dim_pipeline_run.parquet").to_pylist()}
    assert table["idle"] == "no_delivery" and verify_star_schema(cfg.paths.outputs_dir) == []
    after = published_digest(cfg)
    assert {name for name in after if after[name] != state.before_idle[name]} == {
        "promolift.sqlite", "outputs/powerbi/dim_pipeline_run.parquet", "outputs/powerbi/manifest.json", "dashboard/powerbi-design.html"}


# --- the refusals that depend on the other runs ----------------------------------------------------------------------------------


def test_a_run_whose_delivery_is_not_the_latest_loaded_refuses_the_model_tasks(pipeline_staged, tmp_path, quick_cfg):
    """AC28, plan section 22: ``recover``, ``fit_model``, ``estimate`` and ``evaluate`` work on the latest loaded delivery; a run whose delivery another run has since followed is
    refused (and writes nothing) in those."""
    state = copy_state(pipeline_staged("load"), tmp_path / "state", quick_cfg)
    cfg = state.cfg
    mark_delivery(manifest_of(cfg), DAILY_ID, "loaded", "a")       # what the close of "a" does last
    advance(cfg, "new", "load")
    assert query(cfg, "SELECT delivery_id FROM deliveries WHERE run_key = 'new'") == [("D2024-06-27",)]
    before = tree_state(state.root)
    for task_id in ("recover", "fit_model", "estimate", "evaluate"):
        with pytest.raises(RunRefusedError, match="calcula la última") as refused:
            pipeline.run_task(task_id, "a", cfg)
        assert refused.value.exit_code == 2
    assert tree_state(state.root) == before


def test_a_run_that_holds_a_delivery_cannot_deliver_another_one(pipeline_staged, tmp_path, quick_cfg):
    """Plan section 22: ``deliver`` in a run that already holds another delivery is refused; repeating it while that delivery is still the pending one is the same delivery."""
    state = copy_state(pipeline_staged("deliver"), tmp_path / "state", quick_cfg)
    cfg = state.cfg
    assert pipeline.run_task("deliver", "a", cfg)["delivery_id"] == DAILY_ID
    advance(cfg, "b", "load")
    mark_delivery(manifest_of(cfg), DAILY_ID, "loaded", "b")         # what the close of "b" does last
    before = tree_state(state.root)
    with pytest.raises(RunRefusedError, match="una corrida no cambia de entrega") as refused:
        pipeline.run_task("deliver", "a", cfg)
    assert refused.value.exit_code == 2 and tree_state(state.root) == before


def test_the_test_is_not_evaluated_under_another_configuration_before_its_seal_and_the_refusal_exits_2(pipeline_before_close, tmp_path, quick_cfg):
    """AC18, D17: while the seal has no test part, a run that reaches the instant the test week closes with a configuration that is not the sealed one is refused in every task
    before it writes (exit 2, ``EvaluationRefusedError`` turned into a ``RunRefusedError``), naming the key that differs; with the sealed one it runs."""
    state = copy_state(pipeline_before_close, tmp_path / "state", quick_cfg)
    cfg = state.cfg
    assert json.loads(Path(cfg.paths.seal).read_text(encoding="utf-8")).get("test") is None
    other = dataclasses.replace(cfg, bootstrap=dataclasses.replace(cfg.bootstrap, seed=cfg.bootstrap.seed + 1))
    before = tree_state(state.root)
    for task_id in TASK_IDS:
        with pytest.raises(RunRefusedError, match=r"bootstrap\.seed") as refused:
            pipeline.run_task(task_id, "other", other)
        assert refused.value.exit_code == 2
    with pytest.raises(RunRefusedError, match=r"bootstrap\.seed"):
        pipeline.run_all(other, run_key="other")
    assert tree_state(state.root) == before
    assert pipeline.run_task("fetch_source", "same", cfg)["train_sha256"]


# --- one writer ------------------------------------------------------------------------------------------------------------------


def test_every_writing_command_holds_the_writer_lock_and_a_second_writer_writes_nothing(pipeline_launched, tmp_path, quick_cfg, monkeypatch):
    """AC29, D26: ``run_task``, ``run_all`` and ``replay`` take the lock before the state file is touched: while another holder has it each is refused with exit 2 and the folder is
    the same bytes afterwards; while a task runs the file names the command and the run, and it is gone after (also after a task that failed)."""
    state = copy_state(pipeline_launched, tmp_path / "state", quick_cfg)
    cfg = state.cfg
    before = tree_state(state.root)
    calls = (lambda: pipeline.run_task("fetch_source", "x", cfg), lambda: pipeline.run_all(cfg, run_key="x"), lambda: pipeline.replay(cfg))
    with lock.sole_writer(cfg.paths.interim_dir, "another command", "other"):
        for call in calls:
            error = from_another_thread(call)
            assert isinstance(error, RunLockedError) and error.state == "thread" and error.exit_code == 2
        assert {k: v for k, v in tree_state(state.root).items() if k != "interim/pipeline.lock"} == before
    assert tree_state(state.root) == before
    seen: list[dict | None] = []

    def spy(ctx):
        seen.append(lock.read_holder(cfg.paths.interim_dir))
        if len(seen) == 3:
            raise RuntimeError("the third task failed")
        return {"spied": True}

    only = dataclasses.replace(pipeline.TASKS[0], func=spy)
    monkeypatch.setattr(pipeline, "TASKS", (only, *pipeline.TASKS[1:]))
    pipeline.run_task("fetch_source", "x", cfg)
    pipeline.run_all(cfg, only=["fetch_source"], run_key="y")
    assert [(h["command"], h["run_key"]) for h in seen] == [("task fetch_source", "x"), ("run", "y")]
    with pytest.raises(RuntimeError, match="third task failed"):
        pipeline.run_task("fetch_source", "z", cfg)
    assert lock.read_holder(cfg.paths.interim_dir) is None and not (Path(cfg.paths.interim_dir) / lock.LOCK_NAME).exists()
    between: list[dict | None] = []

    def stop_between_runs(*args, **kwargs):
        between.append(lock.read_holder(cfg.paths.interim_dir))      # replay holds the lock from before its first run: no other writer fits between two of them
        raise RuntimeError("stopped before the first run")

    monkeypatch.setattr(pipeline, "run_all", stop_between_runs)
    with pytest.raises(RuntimeError, match="stopped before the first run"):
        pipeline.replay(cfg)
    assert [h["command"] for h in between] == ["replay"] and lock.read_holder(cfg.paths.interim_dir) is None


def test_replay_with_nothing_pending_does_not_take_the_lock(pipeline_replayed, tmp_path, quick_cfg):
    """Plan section 22: a ``replay`` with no pending delivery returns at once and does not take the lock (so it runs while another process writes), and writes nothing."""
    state = copy_state(pipeline_replayed, tmp_path / "state", quick_cfg)
    cfg = state.cfg
    before = tree_state(state.root)
    with lock.sole_writer(cfg.paths.interim_dir, "another command", "other"):
        outcome: dict = {}
        error = from_another_thread(lambda: outcome.update(runs=pipeline.replay(cfg)))
        assert {k: v for k, v in tree_state(state.root).items() if k != "interim/pipeline.lock"} == before
    assert error is None and outcome["runs"] == [] and tree_state(state.root) == before


def test_unknown_tasks_and_incompatible_selections_are_usage_errors_before_writing(pipeline_launched, tmp_path, quick_cfg):
    """A task that does not exist, ``only`` with ``start``, an empty ``only`` and an ``until`` that is not a delivery of the plan or is earlier than the next pending one are
    ``UsageError``, and nothing is written."""
    state = copy_state(pipeline_launched, tmp_path / "state", quick_cfg)
    cfg = state.cfg
    before = tree_state(state.root)
    for call, message in (
        (lambda: pipeline.run_task("nope", "x", cfg), "tarea desconocida"), (lambda: pipeline.run_all(cfg, only=["report"], start="load"), "no se combinan"),
        (lambda: pipeline.run_all(cfg, only=[]), "al menos una tarea"), (lambda: pipeline.replay(cfg, until="D2023-01-01"), "no es una entrega del plan"),
        (lambda: pipeline.replay(cfg, until=LAUNCH_ID), "es anterior a la siguiente entrega pendiente"),
    ):
        with pytest.raises(UsageError, match=message):
            call()
    assert tree_state(state.root) == before


# --- AC35 and what the flow wraps ------------------------------------------------------------------------------------------------


def test_two_runs_of_the_launch_from_nothing_give_the_same_content_in_every_parquet_and_json_without_the_run_columns(pipeline_launched, tmp_path, quick_cfg, tiny_dir):
    """AC35, RNF01: the launch run, repeated from nothing, gives the same rows in every Parquet of the star model, the same site files, summary and seal, apart from what names the
    run. (The launch is where the model is fitted and the seal written; the whole synthetic replay twice is the real one of U19.)"""
    second = state_of(tmp_path / "second", quick_cfg, tiny_dir)
    pipeline.run_all(second.cfg, run_key="again")
    first, again = content_of(pipeline_launched.cfg), content_of(second.cfg)
    assert sorted(first) == sorted(again) and len(first) >= 25
    assert {name for name in first if first[name] != again[name]} == set()


def test_the_files_a_replay_publishes_carry_no_path_of_this_machine(pipeline_replayed):
    """RNF12: nothing the flow publishes (the star model, the site, the reports, the HTML) holds the folder of the run, the temporary folder or the user's, in either spelling."""
    cfg = pipeline_replayed.cfg
    files = [p for folder in (cfg.paths.outputs_dir, cfg.paths.site_dir, cfg.paths.reports_dir) for p in Path(folder).rglob("*") if p.is_file()] + [Path(cfg.paths.dashboard_html)]
    assert len(files) >= 30
    needles = {str(pipeline_replayed.root), pipeline_replayed.root.as_posix(), str(Path.home()), Path.home().as_posix(), tempfile.gettempdir(), Path(tempfile.gettempdir()).as_posix()}
    for path in files:
        data = path.read_bytes()
        assert not [n for n in needles if n.encode() in data], path.name


def test_the_flow_issues_each_test_day_once_and_evaluates_the_close_once(pipeline_replayed):
    """The tasks wrap ``estimate_delivery`` and ``evaluate`` and change nothing they do: the seven test days are issued (one run each), the close issues none and evaluates the test
    once, and the seal holds its launch and test parts; every run is ``ok`` and holds the delivery it loaded."""
    cfg = pipeline_replayed.cfg
    assert len(pipeline_replayed.runs) == 8 and [r[-1]["task"] for r in pipeline_replayed.runs] == ["report"] * 8
    days = query(cfg, "SELECT date_key, COUNT(*) FROM daily_cell GROUP BY date_key ORDER BY date_key")
    assert len(days) == 7 and all(n > 0 for _, n in days)
    assert query(cfg, "SELECT COUNT(DISTINCT run_key) FROM daily_cell") == [(7,)]
    deliveries = dict(query(cfg, "SELECT delivery_id, status FROM deliveries"))
    assert deliveries == {spec: "loaded" for spec in deliveries} and CLOSE_ID in deliveries and len(deliveries) == 9
    seal = json.loads(Path(cfg.paths.seal).read_text(encoding="utf-8"))
    assert seal["launch"]["run_key"] == "launch" and seal["test"]["as_of"].startswith("2024-07-03")
    evaluations = [next(t["result"] for t in run if t["task"] == "evaluate") for run in pipeline_replayed.runs]
    assert [e.get("test") for e in evaluations] == ["not_the_close"] * 7 + ["written"]
    assert query(cfg, "SELECT delivery_id, status FROM pipeline_runs WHERE run_key = ?", (seal["test"]["run_key"],)) == [(CLOSE_ID, "ok")]
    assert query(cfg, "SELECT COUNT(*) FROM eval_criteria WHERE seal_state = 'sealed'") == [(10,)]


# --- what the close rewrites alone, and what the tasks read -----------------------------------------------------------------------------------


def test_the_run_table_and_the_summary_are_rewritten_alone_and_a_set_that_does_not_verify_is_kept(pipeline_staged, tmp_path, quick_cfg):
    """AC27, D25: the close rewrites ``dim_pipeline_run.parquet`` and ``summary.json`` (each with its line of the manifest) and no other file of the set; over a folder whose files are
    not the ones the manifest names, the run table is not rewritten (a warning, every byte kept) and the summary refuses to be (``SiteExportError``)."""
    from promolift.dashboard.semantic_model import MODEL
    from promolift.export import export_run_table
    from promolift.registry import RunMeta
    from promolift.site_export import export_summary
    from promolift.warehouse import connect

    state = copy_state(pipeline_staged("render_dashboard"), tmp_path / "state", quick_cfg)
    cfg = state.cfg
    advance_closers = {"outputs": Path(cfg.paths.outputs_dir), "site": Path(cfg.paths.site_dir)}
    before = {name: tree_state(folder) for name, folder in advance_closers.items()}
    fetched = state_file(cfg, "a")["tasks"]["fetch_source"]
    view = pipeline.sealed_view(cfg, fetched["train_sha256"], fetched["eval_sha256"])
    meta = RunMeta("a", pipeline.datetime.fromisoformat(state_file(cfg, "a")["tasks"]["deliver"]["as_of"]))
    conn = connect(cfg.paths.warehouse)
    try:
        conn.execute("UPDATE pipeline_runs SET status = 'ok' WHERE run_key = 'a'")
        assert export_run_table(conn, cfg.paths.outputs_dir, MODEL, meta, view) == Path(cfg.paths.outputs_dir) / "dim_pipeline_run.parquet"
        export_summary(conn, cfg.paths.site_dir, meta, view, seal_path=cfg.paths.seal, max_total_bytes=cfg.site.max_total_bytes)
        after = {name: tree_state(folder) for name, folder in advance_closers.items()}
        assert {k for k in after["outputs"] if after["outputs"][k] != before["outputs"][k]} == {"dim_pipeline_run.parquet", "manifest.json"}
        assert {k for k in after["site"] if after["site"][k] != before["site"][k]} == {"summary.json", "manifest.json"}
        assert verify_star_schema(cfg.paths.outputs_dir) == [] and pipeline.verify_site(cfg.paths.site_dir) == []
        assert json.loads((Path(cfg.paths.site_dir) / "summary.json").read_text(encoding="utf-8"))["status"] == "ok"
        broken = Path(cfg.paths.outputs_dir) / "fact_forecast.parquet"
        broken.write_bytes(broken.read_bytes() + b"x")
        site_broken = Path(cfg.paths.site_dir) / "data.json"
        site_broken.write_bytes(site_broken.read_bytes() + b" ")
        kept, kept_site = tree_state(cfg.paths.outputs_dir), tree_state(cfg.paths.site_dir)
        assert export_run_table(conn, cfg.paths.outputs_dir, MODEL, meta, view) is None
        with pytest.raises(SiteExportError, match="no se reescribe el resumen"):
            export_summary(conn, cfg.paths.site_dir, meta, view, seal_path=cfg.paths.seal, max_total_bytes=cfg.site.max_total_bytes)
        assert tree_state(cfg.paths.outputs_dir) == kept and tree_state(cfg.paths.site_dir) == kept_site
    finally:
        conn.close()


def test_publishing_from_the_interim_folder_gives_the_bytes_of_publishing_from_memory(pipeline_launched, tiny_dir, cfg, tmp_path):
    """The ``deliver`` task reads the canonical hours one day at a time from the interim folder: the launch, a daily delivery and the close it publishes are the same bytes
    (the same SHA-256 in the manifest) as ``publish`` gives from the canonical data held in memory."""
    from promolift.deliveries import delivery_plan, publish
    from promolift.ingest import canonical, read_source
    from tests.fixtures.make_fixture import fixture_config

    accepted = fixture_config(cfg, tiny_dir)
    memory = canonical((read_source(accepted.source.train_path, "train", accepted)[0], read_source(accepted.source.eval_path, "eval", accepted)[0]), accepted)
    interim = pipeline._canonical_of(pipeline_launched.cfg.paths.interim_dir)
    plan = delivery_plan(accepted)
    for spec in (plan[0], plan[1], plan[-1]):
        assert publish(spec, interim, tmp_path / "interim", accepted).sha256 == publish(spec, memory, tmp_path / "memory", accepted).sha256, spec.delivery_id


def test_the_validation_of_a_run_says_which_file_each_sum_that_is_not_its_hours_comes_from():
    """V26 and V27 of the run's report name the files that showed the difference, from the counts ``fetch_source`` kept per file; counts written before they were kept per file
    are put on the training file."""
    from promolift.validate import validate_source

    fetched = {"sale_amount_mismatch_train": 0, "sale_amount_mismatch_eval": 3, "stock_count_mismatch_train": 2, "stock_count_mismatch_eval": 0}
    report = validate_source(pipeline._source_findings(fetched, pipeline.load_config()), run_key="r")
    found = {r.rule_id: (r.passed, r.series_days_affected, r.examples) for r in report.results if r.rule_id in ("V26", "V27")}
    assert found == {"V26": (False, 3, [{"files": ["eval"]}]), "V27": (False, 2, [{"files": ["train"]}])}
    old = validate_source(pipeline._source_findings({"sale_amount_mismatch": 4, "stock_count_mismatch": 0}, pipeline.load_config()), run_key="r")
    assert {r.rule_id: (r.passed, r.series_days_affected, r.examples) for r in old.results if r.rule_id in ("V26", "V27")} == {
        "V26": (False, 4, [{"files": ["train"]}]), "V27": (True, 0, [])}
