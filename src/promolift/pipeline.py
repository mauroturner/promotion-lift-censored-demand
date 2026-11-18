"""The tasks of a run, their state, the ordered close and the refusals (RF23, RNF01, RNF03; AC07, AC27, AC28, AC29; plan, sections 3 and 22; D25, D26, D39). Adapted from project 05's
``pipeline.py`` (its D29 and D30, with the corrections of its evaluation), from the design of this project.

``TASKS`` is the one list the command line and the Airflow DAG run, in this order, with these functions. Every task of a run works on the state file
``<interim>/runs/<run_key>.json`` (the start, the delivery, the status and the result of each task with its seconds and its memory peaks with their counter, or the whole traceback if
it failed) and, from ``load`` on, on the run's row of ``pipeline_runs``. The bodies of the model's tasks stay where they were written (``launch.fit_model``,
``daily.recover_delivery`` and ``daily.estimate_delivery``, ``reporting.evaluate``, ``export.export_star_schema``): a task here reads what the earlier ones left, builds the ``RunMeta``
and the sealed view they take and calls them.

* **One writer.** ``run_task``, ``run_all`` and ``replay`` hold ``lock.sole_writer`` from before the state file is touched until they return (D26): a second writer is
  ``RunLockedError`` (exit 2) and writes nothing. A ``replay`` with no pending delivery returns at once and does not take it.
* **Refusals before writing** (``RunRefusedError``, exit 2, no retry), in this order: any task of a run that ended (``ok`` or ``no_delivery``); ``deliver`` in a run that already
  holds another delivery; ``load`` when another run loaded the delivery, and every task after ``load`` unless this run loaded its own delivery; ``load`` without this run's
  validation report in ``reports/validation/history`` or with a blocking rule failing in it; the model tasks (``recover``, ``fit_model``, ``estimate``, ``evaluate``) when the run's
  delivery is not the latest loaded one; while the seal has no test part, every task of a run that would evaluate the test under a configuration that is not the sealed one
  (``registry.EvaluationRefusedError`` turned into a refused run, D17); and every task from ``load`` on of a run that holds no delivery (a new run: ``task load`` without
  ``--run-key``, B2 of project 05's evaluation). A new run's state file is written only once its first task passed them all.
* **The close.** The run stays ``running`` until ``report`` closes it in this order: SQLite ``ok``, ``dim_pipeline_run.parquet`` alone, ``summary.json`` and the site manifest, the
  HTML, and only then the delivery ``loaded`` in the manifest of deliveries. Closing never creates a run's row: it is ``load``'s.
* **A failure** after ``load`` marks the run ``failed`` in the state file and in SQLite and rewrites the run table, the summary and the HTML if they exist; each of those writes is
  tried on its own and logged if it fails, and the task's error is raised again. A run with no delivery records ``no_delivery`` and rewrites the run table and the HTML. The message
  of a run's row is published in the run table, so it never carries a path of this machine.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import tempfile
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from promolift import ingest
from promolift.config import PipelineConfig, load_config
from promolift.cube import open_cube, open_loaded_cube, open_recovered
from promolift.daily import estimate_delivery, recover_delivery
from promolift.dashboard.render import render_design
from promolift.dashboard.semantic_model import MODEL
from promolift.deliveries import (
    MANIFEST_NAME,
    DeliverySpec,
    ManifestEntry,
    delivery_plan,
    mark_delivery,
    next_pending,
    publish,
    read_delivery,
    read_manifest,
)
from promolift.export import export_run_table, export_star_schema, verify_star_schema
from promolift.files import write_atomic
from promolift.launch import fit_model as fit_frozen_model
from promolift.lock import RunLockedError, RunRefusedError, RunStateError, sole_writer
from promolift.registry import EvaluationRefusedError, RunMeta, SealError, check_test_evaluation, load_registered_bundle, read_seal, sealed_view
from promolift.reporting import build_summary, ready_instant, write_summary
from promolift.reporting import evaluate as evaluate_model
from promolift.schema import SourceError
from promolift.site_export import export_site, export_summary, verify_site
from promolift.sysinfo import MemoryPeaks, peak_memory
from promolift.validate import (
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
from promolift.warehouse import apply_schema, connect, load_delivery

logger = logging.getLogger(__name__)

__all__ = ["TASKS", "TASK_IDS", "RunContext", "RunLockedError", "RunRefusedError", "RunStateError", "TaskSpec", "UsageError", "replay", "run_all", "run_task"]

CLOSED_STATUSES = ("ok", "no_delivery")
MODEL_TASK_IDS = ("recover", "fit_model", "estimate", "evaluate")
CLOSING_STEPS = ("sqlite", "run_table", "summary", "html", "manifest")
RUN_COLUMNS = ("run_key", "started_at", "finished_at", "status", "delivery_id", "as_of", "train_sha256", "eval_sha256", "series_days_delivery", "rows_issued",
               "peak_working_set_mb", "peak_commit_mb", "memory_counter", "message")
STAMP = "%Y-%m-%d %H:%M:%S"
MESSAGE_LIMIT = 500


class UsageError(ValueError):
    """A command asked for something the flow does not do (an unknown task, two selections together): nothing was written."""


class ExportError(RuntimeError):
    """The exported files do not keep their contract (their manifest, the site's set)."""


@dataclass(frozen=True)
class RunContext:
    cfg: PipelineConfig
    run_key: str
    started_at: datetime
    state_path: Path


@dataclass(frozen=True)
class TaskSpec:
    """One task: its id, its function and the limits the Airflow DAG gives it (retries, minutes between them, timeout in minutes; Airflow enforces them, ``run_task`` runs a task
    once). ``short_circuit`` marks ``deliver``: with no delivery left the run ends there."""

    task_id: str
    func: Callable[[RunContext], dict]
    retries: int
    retry_delay_min: int
    timeout_min: int
    short_circuit: bool = False


# --- state ------------------------------------------------------------------------------------------------------------------


def make_run_key(source: str | datetime) -> str:
    if isinstance(source, datetime):
        return source.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    key = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in str(source)).strip("_")
    if not key:
        raise UsageError("una clave de corrida no puede estar vacía")
    return key


def _state_path(cfg: PipelineConfig, run_key: str) -> Path:
    return Path(cfg.paths.interim_dir) / "runs" / f"{run_key}.json"


def _read_state(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _write_state(path: Path, state: dict) -> None:
    write_atomic(path, json.dumps(state, indent=2, ensure_ascii=False, default=str) + "\n")


def _context(cfg: PipelineConfig, run_id: str | None, when: datetime) -> RunContext:
    """The run `run_id` (a new one at `when` if it has no state file yet). Nothing is written here: a new run's state file is created by its first task once that task passed
    every refusal (``_open``), so a refused run leaves nothing behind."""
    run_key = make_run_key(run_id if run_id is not None else when)
    path = _state_path(cfg, run_key)
    state = _read_state(path)
    started = datetime.fromisoformat(state["started_at"]) if state else when.replace(microsecond=0)
    return RunContext(cfg, run_key, started, path)


def _open(ctx: RunContext) -> None:
    """Create the state file of a new run (``running``, no task yet); a run that has one keeps it as it is."""
    if not ctx.state_path.exists():
        _write_state(ctx.state_path, {"run_key": ctx.run_key, "started_at": ctx.started_at.isoformat(timespec="seconds"), "status": "running", "tasks": {}})


def _task_result(ctx: RunContext, task_id: str) -> dict:
    result = _read_state(ctx.state_path).get("tasks", {}).get(task_id)
    if result is None or result.get("status") in ("failed", "rejected"):
        raise RunStateError(f"la corrida {ctx.run_key} no tiene el resultado de la tarea {task_id}: corra esa tarea antes "
                            f"(python -m promolift task {task_id} --run-key {ctx.run_key})")
    return result


def _save_task(ctx: RunContext, task_id: str, result: dict, status: str | None = None) -> None:
    state = _read_state(ctx.state_path)
    state.setdefault("tasks", {})[task_id] = result
    if status:
        state["status"] = status
    _write_state(ctx.state_path, state)


def _mark_rejected(ctx: RunContext, task_id: str, report: ValidationReport) -> None:
    state = _read_state(ctx.state_path)
    state["status"] = "rejected"
    state.setdefault("tasks", {})[task_id] = {"status": "rejected", "rules": [r.rule_id for r in report.results if not r.passed and r.severity is Severity.BLOCKING]}
    _write_state(ctx.state_path, state)


def _now_text() -> str:
    return datetime.now(UTC).strftime(STAMP)


def _stamp(value: datetime) -> str:
    return pd.Timestamp(value).strftime(STAMP)


def _peak() -> MemoryPeaks | None:
    """The process's memory peaks, or None: telemetry never discards the result of a task that finished."""
    try:
        return peak_memory()
    except Exception:
        logger.warning("could not measure the peak memory", exc_info=True)
        return None


_FOLDER = "<folder>"
_ABSOLUTE_PATH = re.compile(r"(?:<folder>|[A-Za-z]:[\\/]|\\\\|/(?:home|Users|tmp|var|private|mnt|opt|root|usr|etc|srv|run|media)/)[^\s'\"<>|]*")


def _without_paths(text: str, cfg: PipelineConfig) -> str:
    """`text` with every path of this machine taken out: each path that starts at a folder this machine is known by (the project's, the user's, the temporary one: they may hold
    spaces) or looks absolute becomes ``<path>``, whatever follows it. The message of a run's row is published in the run table (RNF09, D36)."""
    known = {str(cfg.project_root), Path(cfg.project_root).as_posix(), str(Path.home()), Path.home().as_posix(), tempfile.gettempdir(), Path(tempfile.gettempdir()).as_posix()}
    for folder in sorted((k for k in known if len(k) > 3), key=len, reverse=True):
        text = text.replace(folder, _FOLDER)
    return _ABSOLUTE_PATH.sub("<path>", text)


# --- the warehouse, as the tasks need it ----------------------------------------------------------------------------------------


def _read_only(cfg: PipelineConfig) -> sqlite3.Connection:
    """The warehouse for reading; before the first load there is none, and asking must not create it (AC07)."""
    path = Path(cfg.paths.warehouse)
    return sqlite3.connect(":memory:") if not path.exists() else sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)).fetchone() is not None


def _has_record(ctx: RunContext) -> bool:
    conn = _read_only(ctx.cfg)
    try:
        return _has_table(conn, "pipeline_runs") and conn.execute("SELECT 1 FROM pipeline_runs WHERE run_key = ?", (ctx.run_key,)).fetchone() is not None
    finally:
        conn.close()


def record_run(conn: sqlite3.Connection, fields: dict) -> None:
    """Create or update the run's row of ``pipeline_runs`` with `fields` (only the columns given change)."""
    unknown = set(fields) - set(RUN_COLUMNS)
    if unknown:
        raise ValueError(f"columnas desconocidas de pipeline_runs: {sorted(unknown)}")
    columns = [c for c in fields if c != "run_key"]
    updated = conn.execute(f"UPDATE pipeline_runs SET {', '.join(f'{c} = ?' for c in columns)} WHERE run_key = ?",
                           [*(fields[c] for c in columns), fields["run_key"]]).rowcount if columns else 0
    if not updated:
        names = list(fields)
        conn.execute(f"INSERT INTO pipeline_runs ({', '.join(names)}) VALUES ({', '.join('?' for _ in names)})", [fields[c] for c in names])


def _record(ctx: RunContext, **fields) -> None:
    if "message" in fields:
        fields["message"] = _without_paths(str(fields["message"]), ctx.cfg)[:MESSAGE_LIMIT]
    conn = connect(ctx.cfg.paths.warehouse)
    try:
        apply_schema(conn)
        record_run(conn, {"run_key": ctx.run_key, **fields})
    finally:
        conn.close()


def _store_validation(conn: sqlite3.Connection, report: ValidationReport) -> None:
    """The run's rule results in ``validation_results`` (their examples are keys of series-days and hours, never a measured value)."""
    own = not conn.in_transaction     # in autocommit each row would be a commit of its own (a sync of the file each)
    if own:
        conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("DELETE FROM validation_results WHERE run_key = ?", (report.run_key,))
        conn.executemany(
            "INSERT INTO validation_results (run_key, rule_id, name_es, severity, scope, aggregation, passed, series_days_affected, hours_affected, examples_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(report.run_key, r.rule_id, r.name_es, r.severity.value, r.scope, r.aggregation.value, int(r.passed), int(r.series_days_affected), int(r.hours_affected),
              json.dumps(r.examples, ensure_ascii=False, default=str)) for r in report.results])
    except BaseException:
        if own and conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    if own:
        conn.execute("COMMIT")


def _loaded_by(conn: sqlite3.Connection, delivery_id: str) -> str | None:
    if not _has_table(conn, "deliveries"):
        return None
    row = conn.execute("SELECT run_key FROM deliveries WHERE delivery_id = ? AND status = 'loaded'", (delivery_id,)).fetchone()
    return None if row is None else row[0]


def _latest_loaded(conn: sqlite3.Connection) -> tuple[str, str, datetime] | None:
    """``(delivery_id, kind, as_of)`` of the loaded delivery with the latest instant, or None before the first load. The close shares its instant with the last daily delivery, and
    it is the later one of the two."""
    if not _has_table(conn, "deliveries"):
        return None
    row = conn.execute("SELECT delivery_id, kind, as_of FROM deliveries WHERE status = 'loaded' ORDER BY as_of DESC, CASE kind WHEN 'close' THEN 2 WHEN 'daily' THEN 1 ELSE 0 END DESC LIMIT 1").fetchone()
    return None if row is None else (row[0], row[1], datetime.fromisoformat(row[2]))


def _deliveries_dir(cfg: PipelineConfig) -> Path:
    return Path(cfg.paths.raw_dir) / "deliveries"


def _manifest_path(cfg: PipelineConfig) -> Path:
    return _deliveries_dir(cfg) / MANIFEST_NAME


def _validation_dir(cfg: PipelineConfig) -> Path:
    return Path(cfg.paths.reports_dir) / "validation"


def _validation_report_path(cfg: PipelineConfig, run_key: str) -> Path:
    return _validation_dir(cfg) / "history" / f"{run_key}.json"


def _spec_of(cfg: PipelineConfig, delivery_id: str) -> DeliverySpec:
    [spec] = [s for s in delivery_plan(cfg) if s.delivery_id == delivery_id]
    return spec


def _entry_of(cfg: PipelineConfig, delivery_id: str) -> ManifestEntry:
    [entry] = [e for e in read_manifest(_manifest_path(cfg)) if e.delivery_id == delivery_id]
    return entry


def _meta(ctx: RunContext) -> RunMeta:
    """What the tasks that calculate for an instant take: the run and the instant of its delivery (the one of the latest loaded delivery for a run with none)."""
    delivered = _task_result(ctx, "deliver")
    return RunMeta(ctx.run_key, datetime.fromisoformat(delivered["as_of"]))


def _view(ctx: RunContext):
    """The sealed view of the run: the configuration's sealed keys and the hashes of the two files this run fetched."""
    fetched = _task_result(ctx, "fetch_source")
    return sealed_view(ctx.cfg, fetched["train_sha256"], fetched["eval_sha256"])


def _add_rules(ctx: RunContext, results: list) -> None:
    """Add rule results of the model steps to this run's report (its files and ``validation_results``); a rule the report already has is replaced, so repeating a task of a run
    does not fail on the result of its first time."""
    report = read_report(_validation_report_path(ctx.cfg, ctx.run_key))
    fresh = [r for r in results if r is not None]
    report = add_results(replace(report, results=[r for r in report.results if r.rule_id not in {f.rule_id for f in fresh}]), fresh)
    write_report(report, _validation_dir(ctx.cfg))
    conn = connect(ctx.cfg.paths.warehouse)
    try:
        _store_validation(conn, report)
    finally:
        conn.close()


# --- the canonical hours of the interim folder, as ``publish`` reads them --------------------------------------------------------


class _Hours:
    """The sale or the stock status of every canonical day, read one day at a time from the cube of the interim folder: ``hours[:, mask, :]`` is the ``(series, days, 24)`` array of
    the selected days, so publishing a delivery reads only its own days."""

    def __init__(self, cube: Any, date_keys: np.ndarray, field: str) -> None:
        self._read = getattr(cube, field)
        self._keys, self._empty = date_keys, np.empty((cube.n_series, 0, 24), dtype=np.float32 if field == "sales" else np.int8)

    def __getitem__(self, index: tuple) -> np.ndarray:
        keys = self._keys[index[1]]
        return np.stack([np.asarray(self._read(int(k))) for k in keys], axis=1) if len(keys) else self._empty


@dataclass
class _Canonical:
    """What ``deliveries.publish`` reads of the canonical data, from the files of the interim folder (the same members as ``ingest.Canonical``)."""

    series: pd.DataFrame
    series_days: pd.DataFrame
    date_keys: np.ndarray
    sales: _Hours
    stock: _Hours


def _canonical_of(interim_dir: Path) -> _Canonical:
    series, series_days = ingest.read_canonical(interim_dir)
    cube = open_cube(interim_dir)
    return _Canonical(series, series_days, cube.date_keys, _Hours(cube, cube.date_keys, "sales"), _Hours(cube, cube.date_keys, "stock"))


# --- tasks --------------------------------------------------------------------------------------------------------------------------


def fetch_source(ctx: RunContext) -> dict:
    """The pinned files and their canonical tables (RF01-RF03); a source rule that fails rejects the run and writes nothing to SQLite."""
    try:
        return ingest.fetch_source(ctx.cfg)
    except SourceError as error:
        report = validate_source(error, run_key=ctx.run_key)
        write_report(report, _validation_dir(ctx.cfg))
        _mark_rejected(ctx, "fetch_source", report)
        raise ValidationError(report) from error


def deliver(ctx: RunContext) -> dict:
    """Publish the next pending delivery; with none left the run ends as ``no_delivery`` and what was exported is refreshed (RF05)."""
    cfg = ctx.cfg
    fetched, view = _task_result(ctx, "fetch_source"), _view(ctx)
    plan = delivery_plan(view)
    spec = next_pending(_manifest_path(cfg), plan)
    if spec is None:
        message = f"no hay entregas pendientes: las {len(plan)} del plan ya están cargadas"
        _record(ctx, started_at=ctx.started_at.astimezone(UTC).strftime(STAMP), finished_at=_now_text(), status="no_delivery", train_sha256=fetched["train_sha256"],
                eval_sha256=fetched["eval_sha256"], message=message)
        conn = _read_only(cfg)
        try:
            latest = _latest_loaded(conn)       # the data the exports describe: the last loaded delivery's
        finally:
            conn.close()
        result = {"delivered": False, "run_status": "no_delivery", "message": message, "delivery_id": None if latest is None else latest[0],
                  "kind": None if latest is None else latest[1], "as_of": None if latest is None else latest[2].isoformat()}
        _save_task(ctx, "deliver", result, status="no_delivery")      # the refresh below reads this task's own result (``_meta``)
        _refresh_exports(ctx, summary=False, html=True, when="after a run with no delivery")
        return result
    conn = _read_only(cfg)
    try:
        owner = _loaded_by(conn, spec.delivery_id)
    finally:
        conn.close()
    if owner is not None and owner != ctx.run_key:
        raise RunStateError(f"la entrega {spec.delivery_id} ya está cargada por la corrida {owner} y el manifiesto no la marca cargada: retome esa corrida "
                            f"(python -m promolift run --run-key {owner} --from <tarea>; docs/runbook.md, R4)")
    entry = publish(spec, _canonical_of(cfg.paths.interim_dir), _deliveries_dir(cfg), view)
    return {"delivered": True, "delivery_id": spec.delivery_id, "kind": spec.kind, "as_of": spec.as_of.isoformat(), "series_days": entry.series_days, "sha256": entry.sha256}


def _source_findings(fetched: dict, cfg: PipelineConfig) -> tuple[ingest.SourceReport, ingest.SourceReport]:
    """What the two files showed when they were read, as ``validate_source`` takes it: only V26 and V27 (the counts of rows whose sums are not the hours') are used, per file; a
    canonical folder written before the counts were kept per file puts its totals on the training file."""
    def report(split: str) -> ingest.SourceReport:
        sale = fetched.get(f"sale_amount_mismatch_{split}", fetched.get("sale_amount_mismatch", 0) if split == "train" else 0)
        stock = fetched.get(f"stock_count_mismatch_{split}", fetched.get("stock_count_mismatch", 0) if split == "train" else 0)
        return ingest.SourceReport(split, 0, 0, 0, cfg.calendar.first_day, cfg.calendar.last_day, 0, 0, int(sale), int(stock))

    return report("train"), report("eval")


def validate(ctx: RunContext) -> dict:
    """Validate the delivery; a blocking rule puts it in quarantine, rejects the run and writes nothing to SQLite (RF06, RF07, AC07)."""
    cfg, view = ctx.cfg, _view(ctx)
    delivered, fetched = _task_result(ctx, "deliver"), _task_result(ctx, "fetch_source")
    spec, entry = _spec_of(cfg, delivered["delivery_id"]), _entry_of(cfg, delivered["delivery_id"])
    days, cube = read_delivery(_deliveries_dir(cfg), entry)
    conn = _read_only(cfg)
    try:
        by_delivery = validate_delivery(days, cube, spec, conn, view, entry=entry, out_dir=_deliveries_dir(cfg), run_key=ctx.run_key)
    finally:
        conn.close()
    if ingest.canonical_state(cfg.paths.interim_dir) != (fetched["train_sha256"], fetched["eval_sha256"]):
        raise RunStateError(f"las tablas canónicas de {cfg.paths.interim_dir} no son las de la fuente que leyó esta corrida: corra fetch_source "
                            f"(python -m promolift task fetch_source --run-key {ctx.run_key})")
    source = validate_source(_source_findings(fetched, cfg), run_key=ctx.run_key, train_sha256=fetched["train_sha256"], eval_sha256=fetched["eval_sha256"])
    report = combine_reports(source, by_delivery)
    write_report(report, _validation_dir(cfg))
    if report.blocking_failed:
        mark_delivery(_manifest_path(cfg), spec.delivery_id, "rejected", ctx.run_key)
        _mark_rejected(ctx, "validate", report)
        raise ValidationError(report)
    return {"delivery_id": spec.delivery_id, "series_days": entry.series_days, "warnings": [r.rule_id for r in report.results if not r.passed and r.severity is Severity.WARNING]}


def load(ctx: RunContext) -> dict:
    """Load the delivery in one transaction with its controls and open the run's row as ``running`` (RF08); a load that committed and is repeated by the same run records the run
    only."""
    cfg, view = ctx.cfg, _view(ctx)
    delivered, fetched = _task_result(ctx, "deliver"), _task_result(ctx, "fetch_source")
    spec, entry = _spec_of(cfg, delivered["delivery_id"]), _entry_of(cfg, delivered["delivery_id"])
    days, cube = read_delivery(_deliveries_dir(cfg), entry)
    series = ingest.read_canonical(cfg.paths.interim_dir)[0]
    conn = connect(cfg.paths.warehouse)
    try:
        resumed = _loaded_by(conn, spec.delivery_id) == ctx.run_key
        controls = None if resumed else len(load_delivery(conn, days, cube, spec, ctx.run_key, view, sha256=entry.sha256, series=series, interim_dir=cfg.paths.interim_dir).checks)
        record_run(conn, {"run_key": ctx.run_key, "started_at": ctx.started_at.astimezone(UTC).strftime(STAMP), "finished_at": None, "status": "running",
                          "delivery_id": spec.delivery_id, "as_of": _stamp(spec.as_of), "train_sha256": fetched["train_sha256"], "eval_sha256": fetched["eval_sha256"],
                          "series_days_delivery": entry.series_days, "message": ""})
        _store_validation(conn, read_report(_validation_report_path(cfg, ctx.run_key)))
    finally:
        conn.close()
    return {"series_days": entry.series_days, "as_of": spec.as_of.isoformat(), "controls": controls, "resumed": resumed}


def recover(ctx: RunContext) -> dict:
    """Recover the hours without stock of a daily delivery with the sealed method (RF10); the launch recovers its period in ``fit_model``, after choosing the method, and the close
    has no days."""
    cfg, view, meta = ctx.cfg, _view(ctx), _meta(ctx)
    spec = _spec_of(cfg, _task_result(ctx, "deliver")["delivery_id"])
    if spec.kind != "daily":
        return {"kind": spec.kind, "recovered_days": 0}
    conn = connect(cfg.paths.warehouse)
    try:
        recovered = recover_delivery(conn, open_loaded_cube(cfg.paths.interim_dir), load_registered_bundle(conn, cfg.paths.models_dir), spec, meta, view, interim_dir=cfg.paths.interim_dir)
    finally:
        conn.close()
    return {"kind": spec.kind, "recovered_days": int(recovered.shape[1]), "series": int(recovered.shape[0])}


def fit_model(ctx: RunContext) -> dict:
    """Train and freeze the model at the launch, or check the frozen one (M03, M05); the body is ``launch.fit_model``."""
    cfg, fetched = ctx.cfg, _task_result(ctx, "fetch_source")
    conn = connect(cfg.paths.warehouse)
    try:
        result = fit_frozen_model(cfg, conn, _meta(ctx), train_sha256=fetched["train_sha256"], eval_sha256=fetched["eval_sha256"])
    finally:
        conn.close()
    _add_rules(ctx, result.rules)
    return {"mode": result.mode, "seal": result.seal, "model_version": result.model_version, "config_sha256": result.config_sha256, "artifact_sha256": result.artifact_sha256,
            "method": result.recovery.get("method"), "kappa": result.recovery.get("kappa"), "rows": dict(result.rows)}


def estimate(ctx: RunContext) -> dict:
    """Issue once the effect, the forecasts and the masks of each day of a daily delivery with the frozen model (RF16); the launch issued its effects in ``fit_model`` and the close
    issues none. Records how many rows went into each table."""
    cfg, view, meta = ctx.cfg, _view(ctx), _meta(ctx)
    spec = _spec_of(cfg, _task_result(ctx, "deliver")["delivery_id"])
    if spec.kind != "daily":
        return {"kind": spec.kind, "issued": False, "rows": {}}
    conn = connect(cfg.paths.warehouse)
    try:
        done = estimate_delivery(conn, open_loaded_cube(cfg.paths.interim_dir), load_registered_bundle(conn, cfg.paths.models_dir), spec, meta, view,
                                 recovered=open_recovered(cfg.paths.interim_dir, spec.delivery_id))
    finally:
        conn.close()
    _add_rules(ctx, [model_result("I04", passed=True, series_days=sum(done.rows.values()))])
    return {"kind": spec.kind, "issued": done.issued, "rows": dict(done.rows), "skipped": int(len(done.skipped)), "skipped_cells": int(len(done.skipped_cells))}


def evaluate(ctx: RunContext) -> dict:
    """The test, once, in the run of the close, and its seal (RF18); ``EvaluationRefusedError`` is a refused run (exit 2), as the refusal before the tasks has it."""
    cfg = ctx.cfg
    kind = _spec_of(cfg, _task_result(ctx, "deliver")["delivery_id"]).kind
    if kind != "close":       # the last daily delivery has the instant of the close, but the close is where the test is evaluated (plan, section 3, step 8)
        return {"kind": kind, "test": "not_the_close"}
    conn = connect(cfg.paths.warehouse)
    try:
        return evaluate_model(conn, open_loaded_cube(cfg.paths.interim_dir), load_registered_bundle(conn, cfg.paths.models_dir), _meta(ctx), _view(ctx), seal_path=cfg.paths.seal)
    except EvaluationRefusedError as error:
        raise RunRefusedError(f"la corrida {ctx.run_key} no evalúa la prueba: {error}") from error
    finally:
        conn.close()


def export(ctx: RunContext) -> dict:
    """The star model for Power BI and the five site files, each set read back against its manifest (RF20, RF22). The run stays ``running``."""
    cfg, run, view = ctx.cfg, _meta(ctx), _view(ctx)
    conn = connect(cfg.paths.warehouse)
    try:
        paths = export_star_schema(conn, cfg.paths.outputs_dir, MODEL, run, view, seal_path=cfg.paths.seal, interim_dir=cfg.paths.interim_dir)
        site = export_site(conn, cfg.paths.site_dir, run, view, seal_path=cfg.paths.seal, max_total_bytes=cfg.site.max_total_bytes)
    finally:
        conn.close()
    problems = verify_star_schema(cfg.paths.outputs_dir) + verify_site(cfg.paths.site_dir)
    if problems:
        raise ExportError(f"lo exportado no es una misma exportación: {problems[0]} ({len(problems)} problemas)")
    return {"files": len(paths), "site_files": len(site)}


def render_dashboard(ctx: RunContext) -> dict:
    path = render_design(MODEL, ctx.cfg.paths.outputs_dir, ctx.cfg.paths.dashboard_html, _meta(ctx))
    return {"html": path.name, "bytes": path.stat().st_size}


# --- the close of a run -------------------------------------------------------------------------------------------------------------


def _run_peaks(ctx: RunContext) -> tuple[float | None, float | None, str | None]:
    tasks = _read_state(ctx.state_path).get("tasks", {}).values()
    now = _peak()
    working = [t.get("peak_working_set_mb") for t in tasks] + [now.working_set_mb if now else None]
    commit = [t.get("peak_commit_mb") for t in tasks] + [now.commit_mb if now else None]
    working, commit = [p for p in working if p is not None], [p for p in commit if p is not None]
    return (max(working) if working else None, max(commit) if commit else None, now.counter if now else None)


def _close_sqlite(ctx: RunContext) -> None:
    """Close the run's row as ``ok``; the row is ``load``'s, so a run without one is an error and never gets a row here."""
    working, commit, counter = _run_peaks(ctx)
    conn = connect(ctx.cfg.paths.warehouse)
    try:
        apply_schema(conn)
        if conn.execute("SELECT 1 FROM pipeline_runs WHERE run_key = ?", (ctx.run_key,)).fetchone() is None:
            raise RunStateError(f"la corrida {ctx.run_key} no tiene su fila en pipeline_runs: no cargó su entrega, así que no se cierra "
                                f"(python -m promolift run --run-key {ctx.run_key} --from validate)")
        issued = conn.execute("SELECT COUNT(*) FROM daily_cell WHERE run_key = ?", (ctx.run_key,)).fetchone()[0]
        record_run(conn, {"run_key": ctx.run_key, "status": "ok", "finished_at": _now_text(), "message": "ok", "rows_issued": int(issued),
                          "peak_working_set_mb": None if working is None else round(working, 1), "peak_commit_mb": None if commit is None else round(commit, 1),
                          "memory_counter": counter})
    finally:
        conn.close()


def _close_run_table(ctx: RunContext) -> None:
    conn = connect(ctx.cfg.paths.warehouse)
    try:
        export_run_table(conn, ctx.cfg.paths.outputs_dir, MODEL, _meta(ctx), _view(ctx))
    finally:
        conn.close()


def _close_summary(ctx: RunContext) -> None:
    cfg = ctx.cfg
    conn = connect(cfg.paths.warehouse)
    try:
        export_summary(conn, cfg.paths.site_dir, _meta(ctx), _view(ctx), seal_path=cfg.paths.seal, max_total_bytes=cfg.site.max_total_bytes)
    finally:
        conn.close()


def _close_html(ctx: RunContext) -> None:
    render_dashboard(ctx)


def _close_manifest(ctx: RunContext) -> None:
    mark_delivery(_manifest_path(ctx.cfg), _task_result(ctx, "deliver")["delivery_id"], "loaded", ctx.run_key)


_CLOSERS = {"sqlite": _close_sqlite, "run_table": _close_run_table, "summary": _close_summary, "html": _close_html, "manifest": _close_manifest}


def report(ctx: RunContext) -> dict:
    """Write the evaluation summary and the run's validation report as the latest, and close the run in ``CLOSING_STEPS`` order (plan, section 3, step 11)."""
    cfg = ctx.cfg
    conn = connect(cfg.paths.warehouse)
    try:
        summary = build_summary(conn, _view(ctx), run=_meta(ctx), seal_path=cfg.paths.seal)
    finally:
        conn.close()
    json_path, _md = write_summary(summary, cfg.paths.reports_dir)
    write_report(read_report(_validation_report_path(cfg, ctx.run_key)), _validation_dir(cfg))
    for step in CLOSING_STEPS:
        _CLOSERS[step](ctx)
    return {"summary": json_path.name, "evaluation_status": summary["evaluation_status"], "run_status": "ok"}


def _refresh_exports(ctx: RunContext, *, summary: bool, html: bool, when: str) -> None:
    """Rewrite what was exported before so it says what SQLite says now: the run table, this run's summary and the HTML; nothing is created. Each write is tried on its own and
    logged if it fails (the caller's outcome stands)."""
    cfg = ctx.cfg
    try:
        _meta(ctx), _view(ctx)
    except (RunStateError, KeyError, TypeError, ValueError) as error:
        logger.warning("could not read the metadata of run %s %s, so no exported file was rewritten: %s", ctx.run_key, when, error)
        return
    steps = [("run table", _close_run_table)]
    if summary and (Path(cfg.paths.site_dir) / "summary.json").exists():
        steps.append(("summary", _close_summary))
    if html and Path(cfg.paths.dashboard_html).exists():
        steps.append(("html", _close_html))
    for name, step in steps:
        try:
            step(ctx)
        except Exception as error:
            logger.warning("could not rewrite the %s %s (run %s): %s", name, when, ctx.run_key, error, exc_info=error)


# --- running tasks -----------------------------------------------------------------------------------------------------------------


TASKS: tuple[TaskSpec, ...] = (
    TaskSpec("fetch_source", fetch_source, 0, 0, 20),
    TaskSpec("deliver", deliver, 0, 0, 10, short_circuit=True),
    TaskSpec("validate", validate, 0, 0, 10),
    TaskSpec("load", load, 1, 5, 20),
    TaskSpec("recover", recover, 1, 5, 10),
    TaskSpec("fit_model", fit_model, 1, 5, 30),
    TaskSpec("estimate", estimate, 1, 5, 20),
    TaskSpec("evaluate", evaluate, 1, 5, 20),
    TaskSpec("export", export, 1, 5, 10),
    TaskSpec("render_dashboard", render_dashboard, 1, 5, 10),
    TaskSpec("report", report, 1, 5, 5),
)
TASK_IDS = tuple(t.task_id for t in TASKS)


def _spec(task_id: str) -> TaskSpec:
    for spec in TASKS:
        if spec.task_id == task_id:
            return spec
    raise UsageError(f"tarea desconocida {task_id!r}; las tareas son {', '.join(TASK_IDS)}")


def _held_delivery(ctx: RunContext) -> dict:
    return _read_state(ctx.state_path).get("tasks", {}).get("deliver", {})


def _refuse_a_closed_run(spec: TaskSpec, ctx: RunContext) -> None:
    status = _read_state(ctx.state_path).get("status")
    if status in CLOSED_STATUSES:
        raise RunRefusedError(f"la corrida {ctx.run_key} está cerrada (estado {status}): no se vuelve a abrir para correr {spec.task_id}; "
                              "otra entrega es otra corrida (python -m promolift run)")


def _refuse_a_second_delivery(spec: TaskSpec, ctx: RunContext) -> None:
    held = _held_delivery(ctx)
    if spec.task_id != "deliver" or not held.get("delivered"):
        return
    pending = next_pending(_manifest_path(ctx.cfg), delivery_plan(ctx.cfg))
    if pending is None or pending.delivery_id != held["delivery_id"]:
        raise RunRefusedError(f"la corrida {ctx.run_key} ya tiene la entrega {held['delivery_id']} y la siguiente pendiente es "
                              f"{'ninguna' if pending is None else pending.delivery_id}: una corrida no cambia de entrega (python -m promolift run)")


def _refuse_a_delivery_this_run_did_not_load(spec: TaskSpec, ctx: RunContext) -> None:
    if TASK_IDS.index(spec.task_id) < TASK_IDS.index("load"):
        return
    held = _held_delivery(ctx)
    if not held.get("delivered"):
        return
    conn = _read_only(ctx.cfg)
    try:
        owner = _loaded_by(conn, held["delivery_id"])
    finally:
        conn.close()
    if owner == ctx.run_key or (owner is None and spec.task_id == "load"):
        return
    if owner is None:
        raise RunRefusedError(f"la corrida {ctx.run_key} tiene la entrega {held['delivery_id']} pero no la cargó: {spec.task_id} trabaja sobre la entrega que cargó "
                              f"su corrida (python -m promolift run --run-key {ctx.run_key} --from validate)")
    raise RunRefusedError(f"la entrega {held['delivery_id']} la cargó la corrida {owner}: {spec.task_id} no corre en la corrida {ctx.run_key} "
                          f"(python -m promolift run --run-key {owner} --from <tarea>)")


def _refuse_a_load_its_validation_did_not_pass(spec: TaskSpec, ctx: RunContext) -> None:
    if spec.task_id != "load" or not _held_delivery(ctx).get("delivered"):
        return
    path = _validation_report_path(ctx.cfg, ctx.run_key)
    if not path.is_file():
        raise RunRefusedError(f"la corrida {ctx.run_key} no validó su entrega: load carga solo una entrega que la validación de su corrida aprobó "
                              f"(python -m promolift run --run-key {ctx.run_key} --from validate)")
    report = read_report(path)
    if report.blocking_failed:
        failing = ", ".join(r.rule_id for r in report.results if not r.passed and r.severity is Severity.BLOCKING)
        raise RunRefusedError(f"la validación de la corrida {ctx.run_key} rechazó su entrega ({failing}): load no carga una entrega rechazada (docs/runbook.md, R3)")


def _refuse_an_older_delivery(spec: TaskSpec, ctx: RunContext) -> None:
    held = _held_delivery(ctx)
    if spec.task_id not in MODEL_TASK_IDS or not held.get("delivered"):
        return
    conn = _read_only(ctx.cfg)
    try:
        latest = _latest_loaded(conn)
    finally:
        conn.close()
    if latest is not None and latest[0] != held["delivery_id"]:
        raise RunRefusedError(f"la corrida {ctx.run_key} es de la entrega {held['delivery_id']} (cálculo al {held['as_of']}) y la última cargada es la {latest[0]} "
                              f"(cálculo al {latest[2].isoformat()}): {spec.task_id} calcula la última entrega y no corre en esta corrida")


def _refuse_a_test_evaluation_under_another_configuration(spec: TaskSpec, ctx: RunContext) -> None:
    """D17: while the seal has its launch part and no test part, every task of the run of the close (the run ``evaluate`` evaluates the test
    in) is refused when its configuration is not the sealed one, before anything is written: the test is read once, with the sealed configuration; after the test part exists
    another configuration is post-seal, as before. The instant is that of the delivery the run holds or, before ``deliver``, of the next pending one; the hashes of the files are
    the ones this run fetched or, before ``fetch_source``, the sealed launch's. A seal that cannot be read is left to the tasks that read it."""
    cfg = ctx.cfg
    try:
        seal = read_seal(cfg.paths.seal)
    except SealError:
        return
    if seal is None or seal.get("test") is not None:
        return
    state = _read_state(ctx.state_path)
    held = state.get("tasks", {}).get("deliver") or {}
    if held:
        if not held.get("delivered"):
            return
        delivery_id, as_of, kind = held["delivery_id"], datetime.fromisoformat(held["as_of"]), held["kind"]
    else:
        pending = next_pending(_manifest_path(cfg), delivery_plan(cfg))
        if pending is None:
            return
        delivery_id, as_of, kind = pending.delivery_id, pending.as_of, pending.kind
    if kind != "close" or pd.Timestamp(as_of) < ready_instant(cfg):
        return
    fetched = state.get("tasks", {}).get("fetch_source") or {}
    train, eval_ = fetched.get("train_sha256") or seal["launch"]["train_sha256"], fetched.get("eval_sha256") or seal["launch"]["eval_sha256"]
    try:
        check_test_evaluation(cfg.paths.seal, sealed_view(cfg, train, eval_))
    except EvaluationRefusedError as error:
        raise RunRefusedError(f"la corrida {ctx.run_key} evaluaría la prueba (entrega {delivery_id}, cálculo al {as_of.isoformat()}) con una configuración que no es la "
                              f"sellada: {error} {spec.task_id} no corre.") from error


def _refuse_a_task_of_a_run_without_a_delivery(spec: TaskSpec, ctx: RunContext) -> None:
    """B2 of project 05's evaluation (AC28): a task from ``load`` on of a run that holds no delivery (a new run, as ``task <tarea>`` without ``--run-key`` is, or one whose
    ``deliver`` did not finish) has no delivery of its own to work on. It is refused before ``_open`` creates the state file, so nothing is written; before, the task raised
    ``RunStateError`` after that and the run was left ``failed`` (exit 1). It is the last refusal, so every refusal before it keeps its message."""
    if TASK_IDS.index(spec.task_id) < TASK_IDS.index("load") or _held_delivery(ctx).get("delivered"):
        return
    raise RunRefusedError(f"la corrida {ctx.run_key} no tiene una entrega: {spec.task_id} trabaja sobre la entrega que cargó su corrida; una corrida nueva empieza por "
                          "fetch_source (python -m promolift run) y una que ya empezó se continúa con su clave (python -m promolift run --run-key <clave> --from <tarea>). "
                          "No se escribió nada.")


def _reopen(ctx: RunContext) -> None:
    state = _read_state(ctx.state_path)
    if state.get("status") != "failed":
        return
    state["status"] = "running"
    _write_state(ctx.state_path, state)
    if _has_record(ctx):
        _record(ctx, status="running", finished_at=None, message="")


def _record_failure(ctx: RunContext, spec: TaskSpec, error: BaseException) -> None:
    """The state file, the run's row and the exported files say the task failed; each write on its own, logged if it fails, so the task's error is what the caller sees (AC27)."""
    message = f"{spec.task_id}: {type(error).__name__}: {error}"
    try:
        state = _read_state(ctx.state_path)
        state["status"] = "failed"
        state.setdefault("tasks", {})[spec.task_id] = {"status": "failed", "error": message[:MESSAGE_LIMIT], "traceback": "".join(traceback.format_exception(error))}
        _write_state(ctx.state_path, state)
    except Exception as failure:
        logger.warning("could not record the failure of %s in the state file of run %s", spec.task_id, ctx.run_key, exc_info=failure)
    try:
        if _has_record(ctx):
            _record(ctx, status="failed", finished_at=_now_text(), message=message)
    except Exception as failure:
        logger.warning("could not record the failure of %s in the warehouse for run %s", spec.task_id, ctx.run_key, exc_info=failure)
    try:
        if _has_record(ctx):
            _refresh_exports(ctx, summary=True, html=True, when=f"after {spec.task_id} failed")
    except Exception as failure:
        logger.warning("could not rewrite the exported files of run %s after %s failed", ctx.run_key, spec.task_id, exc_info=failure)


def _run_spec(spec: TaskSpec, ctx: RunContext) -> dict:
    """The refusals (nothing written), the task, and its result saved with its seconds and its memory peaks; a failure is recorded and raised."""
    _refuse_a_closed_run(spec, ctx)
    _refuse_a_second_delivery(spec, ctx)
    _refuse_a_delivery_this_run_did_not_load(spec, ctx)
    _refuse_a_load_its_validation_did_not_pass(spec, ctx)
    _refuse_an_older_delivery(spec, ctx)
    _refuse_a_test_evaluation_under_another_configuration(spec, ctx)
    _refuse_a_task_of_a_run_without_a_delivery(spec, ctx)
    started = time.perf_counter()
    _open(ctx)
    _reopen(ctx)
    try:
        result = spec.func(ctx)
    except (ValidationError, RunRefusedError):      # the first marked the run rejected itself; the second refused before writing: neither is a failure of the task
        raise
    except BaseException as error:
        _record_failure(ctx, spec, error)
        logger.error("task %s of run %s failed after %.1f s: %s", spec.task_id, ctx.run_key, time.perf_counter() - started, error)
        raise
    peaks = _peak()
    result = {**result, "seconds": round(time.perf_counter() - started, 2), "peak_working_set_mb": None if peaks is None else round(peaks.working_set_mb, 1),
              "peak_commit_mb": None if peaks is None or peaks.commit_mb is None else round(peaks.commit_mb, 1), "memory_counter": None if peaks is None else peaks.counter}
    try:
        _save_task(ctx, spec.task_id, result, status=result.get("run_status"))
    except BaseException as error:
        if result.get("run_status") in CLOSED_STATUSES:
            logger.error("task %s closed run %s as %s but its result could not be saved: run it again", spec.task_id, ctx.run_key, result["run_status"], exc_info=error)
            raise
        _record_failure(ctx, spec, error)
        raise
    logger.info("task %s of run %s: %.1f s", spec.task_id, ctx.run_key, result["seconds"])
    return result


def run_task(task_id: str, run_id: str | None = None, cfg: PipelineConfig | None = None, *, now: datetime | None = None) -> dict:
    """Run one task of the run `run_id` (a new run if None) holding the writer lock: what the Airflow DAG calls."""
    spec = _spec(task_id)
    cfg = cfg or load_config()
    when = (now or datetime.now(UTC)).astimezone(UTC)
    with sole_writer(cfg.paths.interim_dir, f"task {task_id}", make_run_key(run_id if run_id is not None else when)):
        return _run_spec(spec, _context(cfg, run_id, when))


def _select(only: list[str] | None, start: str | None) -> list[str]:
    if only is not None and not only:
        raise UsageError("`only` está vacío: indique al menos una tarea")
    if only and start is not None:
        raise UsageError("`only` y `start` no se combinan")
    ids = list(TASK_IDS)
    if start is not None:
        _spec(start)
        ids = ids[ids.index(start):]
    if only:
        for task_id in only:
            _spec(task_id)
        ids = [i for i in ids if i in only]
    return ids


def run_all(cfg: PipelineConfig, only: list[str] | None = None, start: str | None = None, run_key: str | None = None, *, now: datetime | None = None) -> list[dict]:
    """Run the tasks in order (all, the listed ones or from `start` on) holding the writer lock from before the first to after the last; a run with no delivery stops after
    ``deliver``."""
    ids = _select(only, start)
    when = (now or datetime.now(UTC)).astimezone(UTC)
    outcome = []
    with sole_writer(cfg.paths.interim_dir, "run", make_run_key(run_key if run_key is not None else when)):
        ctx = _context(cfg, run_key, when)
        for task_id in ids:
            spec = _spec(task_id)
            result = _run_spec(spec, ctx)
            outcome.append({"task": task_id, "result": result})
            if spec.short_circuit and not result.get("delivered", True):
                break
    return outcome


def replay(cfg: PipelineConfig, until: str | None = None) -> list[list[dict]]:
    """Run the pending deliveries one run after another up to `until`; with nothing pending nothing runs and the lock is not taken."""
    plan = delivery_plan(cfg)
    ids = [s.delivery_id for s in plan]
    if until is not None and until not in ids:
        raise UsageError(f"--until {until}: no es una entrega del plan ({', '.join(ids)})")
    last = len(plan) - 1 if until is None else ids.index(until)
    runs: list[list[dict]] = []
    pending = next_pending(_manifest_path(cfg), plan)
    if pending is None and until is not None:     # every delivery is loaded, `until` too: the same refusal as an `until` before the next pending one (A4 of project 05)
        raise UsageError(f"--until {until}: no hay entregas pendientes (las {len(plan)} del plan ya están cargadas); no hay nada que correr hasta ella. No se escribió nada.")
    if pending is None:
        return runs
    if plan.index(pending) > last:     # nothing up to `until` is pending: the option would be ignored in silence, so it is refused
        raise UsageError(f"--until {until}: es anterior a la siguiente entrega pendiente, {pending.delivery_id}; no hay nada que correr hasta ella. No se escribió nada.")
    with sole_writer(cfg.paths.interim_dir, "replay", None):
        while (pending := next_pending(_manifest_path(cfg), plan)) is not None and plan.index(pending) <= last:
            runs.append(run_all(cfg))
            if next_pending(_manifest_path(cfg), plan) == pending:
                raise RunStateError(f"la corrida de {pending.delivery_id} terminó sin cargar la entrega: el replay se detiene")
    return runs
