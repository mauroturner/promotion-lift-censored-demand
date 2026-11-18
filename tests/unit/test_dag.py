"""The Airflow DAG without Airflow (U18, AC32; RF23; plan, section 22; D24): its text with ``ast`` and its wiring with a stand-in for
``airflow.sdk``. Adapted from project 05's ``tests/unit/test_dag.py``."""

from __future__ import annotations

import ast
import importlib.util
import logging
import sys
import types
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from promolift.pipeline import CLOSED_STATUSES, TASK_IDS, TASKS

DAG_FILE = Path(__file__).resolve().parents[2] / "airflow" / "dags" / "promolift_daily.py"


def keywords(call: ast.Call) -> dict[str, ast.expr]:
    return {k.arg: k.value for k in call.keywords if k.arg}


@pytest.fixture(scope="module")
def tree() -> ast.Module:
    return ast.parse(DAG_FILE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def dag_call(tree: ast.Module) -> ast.Call:
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "DAG"]
    assert len(calls) == 1
    return calls[0]


# --- the wiring, with a stand-in for airflow.sdk --------------------------------------------------------------------------------------


class Node:
    def __init__(self, function, options):
        self.function, self.options, self.downstream = function, options, []

    def __rshift__(self, other):
        self.downstream.append(other)
        return other


class FakeDag:
    instances: list[FakeDag] = []
    current: FakeDag | None = None

    def __init__(self, **options):
        self.options, self.nodes = options, []
        FakeDag.instances.append(self)

    def __enter__(self):
        FakeDag.current = self
        return self

    def __exit__(self, *exc):
        return False


class FakeFailException(Exception):
    """Stand-in for ``airflow.sdk.exceptions.AirflowFailException``: the task fails at once, with no retry."""


class FakeTask:
    def _decorator(self, kind, options):
        def wrap(function):
            def build():
                node = Node(function, {"kind": kind, **options})
                FakeDag.current.nodes.append(node)
                return node

            return build

        return wrap

    def __call__(self, **options):
        return self._decorator("task", options)

    def short_circuit(self, **options):
        return self._decorator("short_circuit", options)


@pytest.fixture()
def loaded_dag(monkeypatch):
    sdk = types.ModuleType("airflow.sdk")
    sdk.DAG, sdk.task = FakeDag, FakeTask()
    exceptions = types.ModuleType("airflow.sdk.exceptions")
    exceptions.AirflowFailException = FakeFailException
    monkeypatch.setitem(sys.modules, "airflow", types.ModuleType("airflow"))
    monkeypatch.setitem(sys.modules, "airflow.sdk", sdk)
    monkeypatch.setitem(sys.modules, "airflow.sdk.exceptions", exceptions)
    FakeDag.instances.clear()
    spec = importlib.util.spec_from_file_location("promolift_daily_dag", DAG_FILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert len(FakeDag.instances) == 1
    return module, FakeDag.instances[0]


# --- the RED of U27 ------------------------------------------------------------------------------------------------------------------


def test_tasks_match_cli_order(loaded_dag) -> None:
    """AC32, RF23: the DAG and ``python -m promolift run`` walk the same tasks of ``pipeline.TASKS`` in the same order, each one after the
    one before it, in a line; ``--only``, ``--from`` and the ``task`` command offer those tasks and no others."""
    from promolift.cli import build_parser

    _, dag = loaded_dag
    commands = build_parser(TASK_IDS)._subparsers._group_actions[0].choices
    only = next(a for a in commands["run"]._actions if a.dest == "only")
    start = next(a for a in commands["run"]._actions if a.dest == "start")
    single = next(a for a in commands["task"]._actions if a.dest == "task")
    ids = [n.options["task_id"] for n in dag.nodes]
    assert ids == list(only.choices) == list(start.choices) == list(single.choices) == list(TASK_IDS) == [t.task_id for t in TASKS]
    assert len(ids) == 11 and len(set(ids)) == 11
    for before, after in zip(dag.nodes, dag.nodes[1:], strict=False):
        assert before.downstream == [after]
    assert dag.nodes and dag.nodes[-1].downstream == []


# --- the text of the file ----------------------------------------------------------------------------------------------------------


def test_the_dag_has_its_id_the_daily_schedule_no_catchup_and_one_active_run_and_task(dag_call: ast.Call) -> None:
    options = keywords(dag_call)
    assert ast.literal_eval(options["dag_id"]) == "promolift_daily"
    assert ast.literal_eval(options["schedule"]) == "0 1 * * *", "every day, 01:00 UTC"
    assert ast.literal_eval(options["catchup"]) is False
    assert ast.literal_eval(options["max_active_runs"]) == 1 and ast.literal_eval(options["max_active_tasks"]) == 1
    assert ast.literal_eval(options["tags"]) == ["promolift"]
    start = options["start_date"]
    assert isinstance(start, ast.Call) and [ast.literal_eval(a) for a in start.args] == [2026, 11, 1]


def test_it_uses_the_airflow_3_sdk_and_the_functions_of_the_pipeline(tree: ast.Module) -> None:
    imports = {(n.module, a.name) for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
    assert {("airflow.sdk", "DAG"), ("airflow.sdk", "task"), ("promolift.pipeline", "TASKS"), ("promolift.pipeline", "run_task")} <= imports


def test_the_tasks_come_from_the_task_list_and_no_task_id_is_typed_in_the_dag(tree: ast.Module) -> None:
    loops = [n for n in ast.walk(tree) if isinstance(n, ast.For)]
    assert any(isinstance(n.iter, ast.Name) and n.iter.id == "TASKS" for n in loops)
    assert [n for loop in loops for n in ast.walk(loop) if isinstance(n, ast.BinOp) and isinstance(n.op, ast.RShift)], "chained with >> in the loop"
    strings = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert not strings & set(TASK_IDS)


def test_the_dag_builds_one_task_per_spec_with_its_limits(loaded_dag) -> None:
    _, dag = loaded_dag
    assert len(dag.nodes) == len(TASKS) == 11
    for node, spec in zip(dag.nodes, TASKS, strict=True):
        assert node.options["retries"] == spec.retries
        assert node.options["retry_delay"] == timedelta(minutes=spec.retry_delay_min)
        assert node.options["execution_timeout"] == timedelta(minutes=spec.timeout_min)
        assert node.options["kind"] == ("short_circuit" if spec.short_circuit else "task")
    assert dag.options["start_date"] == datetime(2026, 11, 1, tzinfo=UTC)


def test_each_task_runs_its_own_pipeline_task_with_the_run_id_of_airflow(loaded_dag, monkeypatch) -> None:
    module, dag = loaded_dag
    calls = []

    def fake_run_task(task_id, run_id=None, cfg=None, **kwargs):
        calls.append((task_id, run_id))
        return {"delivered": task_id != "deliver", "rows": 7, "seconds": 1.5, "nested": {"left": "out"}, "note": "x" * 500, "nan": float("nan")}

    monkeypatch.setattr(module, "run_task", fake_run_task)
    results = [node.function(run_id="scheduled__x") for node in dag.nodes]
    assert calls == [(task_id, "scheduled__x") for task_id in TASK_IDS], "not the last loop variable eleven times"
    assert results[TASK_IDS.index("deliver")] is False, "no delivery left stops the run: the short circuit gets False"
    rest = [(task_id, r) for task_id, r in zip(TASK_IDS, results, strict=True) if task_id != "deliver"]
    assert all(r == {"task": task_id, "delivered": True, "rows": 7, "seconds": 1.5, "note": "x" * 200, "nan": None} for task_id, r in rest), rest[0]


def test_a_rejection_a_source_error_a_leak_or_a_refusal_fails_at_once_and_a_transport_error_keeps_its_retries(loaded_dag, monkeypatch) -> None:
    """Plan, section 22: a ``ValidationError``, a ``SourceError``, a ``LeakageError`` and a ``RunRefusedError`` (also the lock, a
    ``RunLockedError``) fail with ``AirflowFailException``, with no retry; any other error keeps the task's retries."""
    from types import SimpleNamespace

    from promolift.cube import LeakageError
    from promolift.lock import RunLockedError, RunRefusedError
    from promolift.schema import SourceError
    from promolift.validate import ValidationError

    module, dag = loaded_dag

    def raising(error):
        def run(task_id, run_id=None, cfg=None, **kwargs):
            raise error

        return run

    rejected = ValidationError(SimpleNamespace(run_key="manual__x", results=[]))
    monkeypatch.setattr(module, "run_task", raising(rejected))
    for node in dag.nodes:   # the short circuit and the plain tasks alike
        with pytest.raises(FakeFailException, match="manual__x") as caught:
            node.function(run_id="manual__x")
        assert caught.value.__cause__ is rejected
    deterministic = (SourceError("V01", "el archivo no tiene el tamaño aceptado"), LeakageError("M01: MAE_V1 0,2 contra 1,1"),
                     RunRefusedError("la corrida x está cerrada"), RunLockedError("Otro proceso escribe esta carpeta", path=Path("x"), holder=None, state="alive"))
    for error in deterministic:
        monkeypatch.setattr(module, "run_task", raising(error))
        for index in (0, 1, 5):   # a plain task, the short circuit and another plain task
            with pytest.raises(FakeFailException) as caught:
                dag.nodes[index].function(run_id="manual__x")
            assert caught.value.__cause__ is error and str(error) in str(caught.value)
    unreachable = ConnectionError("the server did not answer")
    monkeypatch.setattr(module, "run_task", raising(unreachable))
    for node in dag.nodes:
        with pytest.raises(ConnectionError):
            node.function(run_id="manual__x")


def test_the_docstring_names_the_short_circuit_task_and_the_status_the_pipeline_records(tree: ast.Module) -> None:
    doc = ast.get_docstring(tree)
    [short] = [spec.task_id for spec in TASKS if spec.short_circuit]
    assert f"``{short}``" in doc and "short_circuit=True" in doc
    assert "``no_delivery``" in doc and "no_delivery" in CLOSED_STATUSES and "pipeline_runs" in doc


def test_a_number_that_is_not_finite_is_published_as_none_and_a_warning_names_the_task_and_the_key(loaded_dag, caplog) -> None:
    """R4-nan-masking-in-xcom-summary (U27): the summary of a task keeps blanking NaN and infinity (XCom is JSON), but no longer in silence: one warning
    per value says which task and which key, so a metric that came back NaN is not read as a plain ``None``."""
    module, _ = loaded_dag
    with caplog.at_level(logging.WARNING):
        made = module.summary("evaluate", {"auc": float("nan"), "loss": float("inf"), "floor": float("-inf"), "rows": 7, "share": 0.5, "note": None})
    assert made == {"task": "evaluate", "auc": None, "loss": None, "floor": None, "rows": 7, "share": 0.5, "note": None}
    warned = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warned) == 3 and all("evaluate" in m for m in warned)
    assert [key for key in ("auc", "loss", "floor") if sum(key in m for m in warned) == 1] == ["auc", "loss", "floor"]
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        module.summary("evaluate", {"auc": 0.8, "rows": 7})
    assert caplog.records == [], "a finite value says nothing"
