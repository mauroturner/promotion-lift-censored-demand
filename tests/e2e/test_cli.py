"""The command line (U17; AC28, AC30; RF23; plan, section 22; D25): every documented option changes the result (one case per option), an incompatible combination exits with 2 before
anything is written, a task from ``load`` on of a new run exits with 2 and writes nothing, ``replay --until`` a delivery already loaded exits with 2 whether or not another is pending,
and the exit codes 0, 1, 2 and 3.

The commands run in this process (``cli.main``), from another working directory, over copies of the states the session built (``tests/fixtures/pipeline_state.py``) that
``write_config`` points a configuration file at. One test runs ``python -m promolift --help`` in another process from another directory."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from promolift import pipeline
from promolift.cli import build_parser
from promolift.config import ENV_CONFIG, ENV_HOME
from promolift.deliveries import MANIFEST_NAME, read_manifest
from promolift.lock import sole_writer
from promolift.pipeline import TASK_IDS
from promolift.reporting import RESULTS_END, RESULTS_START
from tests.e2e.cli_helpers import PROJECT_ROOT, cli, write_config
from tests.fixtures.pipeline_state import DAILY_ID, LAUNCH_ID, copy_state, tamper_delivery, tree_digest, tree_state


@pytest.fixture
def project(request, tmp_path, quick_cfg, monkeypatch):
    """``project(kind)``: a copy of a pipeline state with a configuration file that points at it (``config`` is its path), and another working directory. `kind` is ``launched``,
    a stage of ``pipeline_staged`` (``deliver``, ``load``, ``recover``...) or ``replayed``."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.delenv(ENV_CONFIG, raising=False)
    monkeypatch.delenv(ENV_HOME, raising=False)
    monkeypatch.chdir(elsewhere)

    def make(kind: str = "launched"):
        base = request.getfixturevalue("pipeline_launched" if kind == "launched" else "pipeline_replayed") if kind in ("launched", "replayed") else request.getfixturevalue("pipeline_staged")(kind)
        state = copy_state(base, tmp_path / "state", quick_cfg)
        state.config = str(write_config(state))
        return state

    return make


def state_file(state, run_key: str) -> dict:
    return json.loads((Path(state.cfg.paths.interim_dir) / "runs" / f"{run_key}.json").read_text(encoding="utf-8"))


def runs_of(state) -> set[str]:
    return {p.stem for p in (Path(state.cfg.paths.interim_dir) / "runs").glob("*.json")}


def manifest_of(state) -> dict[str, str]:
    return {e.delivery_id: e.status for e in read_manifest(Path(state.cfg.paths.raw_dir) / "deliveries" / MANIFEST_NAME)}


def ok(result) -> None:
    assert result.code == 0, (result.code, result.out, result.err)


# --- AC30: each documented option, given, changes what the command does -----------------------------------------------------------------------------------------


def only(project):
    state = project("launched")
    ok(cli("run", "--config", state.config, "--only", "fetch_source", "--run-key", "A1"))
    assert list(state_file(state, "A1")["tasks"]) == ["fetch_source"] and DAILY_ID not in manifest_of(state), "fetch_source alone delivers nothing"
    ok(cli("run", "--config", state.config, "--only", "fetch_source", "deliver", "--run-key", "A2"))
    assert list(state_file(state, "A2")["tasks"]) == ["fetch_source", "deliver"] and manifest_of(state)[DAILY_ID] == "published"


def start(project):
    """``run --from validate --run-key A2`` continued the run ``A2`` that ``--only fetch_source deliver`` had left, without running those two tasks again."""
    state = project("launched")
    ok(cli("run", "--config", state.config, "--only", "fetch_source", "deliver", "--run-key", "A2"))
    before = state_file(state, "A2")["tasks"]
    result = cli("run", "--config", state.config, "--from", "validate", "--run-key", "A2")
    ok(result)
    after = state_file(state, "A2")
    assert list(after["tasks"]) == list(TASK_IDS) and after["status"] == "ok" and manifest_of(state)[DAILY_ID] == "loaded"
    assert {task: after["tasks"][task] for task in before} == before, "the tasks before --from were not run again"
    shown = [line.split()[0] for line in result.out.splitlines() if line.split() and line.split()[0] in TASK_IDS]
    assert shown == list(TASK_IDS[TASK_IDS.index("validate"):])


def run_key(project):
    state = project("launched")
    base = runs_of(state)
    ok(cli("run", "--config", state.config, "--only", "fetch_source", "--run-key", "K7"))
    assert runs_of(state) == base | {"K7"}
    ok(cli("run", "--config", state.config, "--only", "fetch_source", "--run-key", "K7"))
    assert runs_of(state) == base | {"K7"}, "the same key continues the same run"
    ok(cli("run", "--config", state.config, "--only", "fetch_source"))
    new = runs_of(state) - base - {"K7"}
    assert len(new) == 1 and next(iter(new)).endswith("Z"), "without --run-key a new run takes its key from the clock"


def config(project):
    """``--config`` names the configuration the command reads: a task run with the configuration of one state writes the state file of its run under that state's folders (the
    folder of the other state, and the project's own, are left as they were)."""
    state = project("launched")
    other = Path(state.root).parent / "other"
    other.mkdir()
    ok(cli("task", "fetch_source", "--config", state.config, "--run-key", "C1"))
    assert (Path(state.cfg.paths.interim_dir) / "runs" / "C1.json").is_file()
    assert not (PROJECT_ROOT / "data" / "interim" / "runs" / "C1.json").exists() and list(other.iterdir()) == []


def verbose(project):
    state = project("launched")
    quiet = cli("run", "--config", state.config, "--only", "fetch_source", "--run-key", "V1")
    loud = cli("run", "--config", state.config, "--only", "fetch_source", "--run-key", "V2", "-v")
    ok(quiet), ok(loud)
    assert "INFO" not in quiet.err and "INFO" in loud.err, "-v shows the detail of each step"


def until(project):
    state = project("launched")
    result = cli("replay", "--config", state.config, "--until", DAILY_ID)
    ok(result)
    assert result.out.rstrip().endswith("1 corrida") and manifest_of(state)[DAILY_ID] == "loaded" and manifest_of(state).get("D2024-06-27") is None


def task(project):
    state = project("launched")
    result = cli("task", "fetch_source", "--config", state.config, "--run-key", "T1")
    ok(result)
    assert result.out.startswith("fetch_source:") and list(state_file(state, "T1")["tasks"]) == ["fetch_source"]


def make_fixture(project, tmp_path):
    project("launched")
    made = {}
    for name, extra in (("base", ()), ("series", ("--series", "30")), ("days", ("--days", "12")), ("seed", ("--seed", "5")), ("signal", ("--signal", "null"))):
        out = tmp_path / f"fixture_{name}"
        options = {"--series": "20", "--days": "10", **dict(zip(extra[::2], extra[1::2], strict=True))}
        ok(cli("make-fixture", str(out), *(arg for pair in options.items() for arg in pair), *(() if "--series" in options else ())))
        made[name] = ((out / "train.parquet").read_bytes(), pq.read_metadata(out / "train.parquet").num_rows)
    assert made["base"][1] == 20 * 3, "--series and --days: 20 series, 3 days of training (the 7 of the test are the other file)"
    assert made["series"][1] == 30 * 3 and made["days"][1] == 20 * 5, "each of those changes the size of the files"
    assert made["seed"][0] != made["base"][0] and made["signal"][0] != made["base"][0], "--seed and --signal change what is written"


def docs_sync(project):
    state = project("replayed")
    readme = Path(state.cfg.paths.readme)
    readme.write_text(f"# Project\n\n{RESULTS_START}\nold\n{RESULTS_END}\n", encoding="utf-8")
    result = cli("docs-sync", "--config", state.config)
    ok(result)
    summary = (Path(state.cfg.paths.reports_dir) / "evaluation_summary.md").read_text(encoding="utf-8").strip()
    assert readme.read_text(encoding="utf-8") == f"# Project\n\n{RESULTS_START}\n{summary}\n{RESULTS_END}\n" and "actualizado" in result.out
    again = cli("docs-sync", "--config", state.config)
    ok(again)
    assert "ya estaba al día" in again.out


CASES = {
    "--only": only, "--from": start, "--run-key": run_key, "--config": config, "-v": verbose, "--until": until, "TAREA": task, "--series": make_fixture, "--days": make_fixture,
    "--seed": make_fixture, "--signal": make_fixture, "SALIDA_DIR": make_fixture, "docs-sync": docs_sync,
}


def documented_options() -> set[str]:
    """Every option and positional of every command the parser documents, by the name the help shows (``-h`` left out)."""
    import argparse

    found: set[str] = set()
    parser = build_parser(TASK_IDS)
    for action in parser._subparsers._group_actions[0].choices.values():          # noqa: SLF001 (argparse has no public list of the commands)
        for item in action._actions:                                                  # noqa: SLF001
            if isinstance(item, argparse._HelpAction):                                # noqa: SLF001
                continue
            found.add(item.option_strings[-1] if item.option_strings and item.option_strings[-1] in ("--only", "--from", "--run-key", "--config", "--until", "--series", "--days",
                                                                                                    "--seed", "--signal") else (item.option_strings[0] if item.option_strings else item.metavar))
    commands = set(parser._subparsers._group_actions[0].choices)                       # noqa: SLF001
    return found | ({"docs-sync"} & commands)


def test_every_option_the_parser_documents_has_its_case():
    """AC30: a case is written for each option the parser documents (an option added without its case fails here), and each case is a function of this module."""
    assert documented_options() == set(CASES), documented_options() ^ set(CASES)


@pytest.mark.parametrize("case", sorted(set(CASES.values()), key=lambda f: f.__name__), ids=lambda f: f.__name__)
def test_every_documented_option_changes_the_result(case, project, tmp_path):
    """AC30: each option is given and the result is not the one without it (the cases above; the four options of ``make-fixture`` share one), over a copy of the state the
    session built."""
    case(project, tmp_path) if "tmp_path" in case.__code__.co_varnames[:case.__code__.co_argcount] else case(project)


# --- AC30: what exits with 2 before writing -------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("args, says", [
    (("run", "--only", "load", "--from", "load"), "no se combinan"),
    (("run", "--run-key", "x"), "--run-key"),
    (("run", "--only", "load"), "empieza por fetch_source"),
    (("run", "--from", "load"), "empieza por fetch_source"),
    (("run", "--from", "validate"), "empieza por fetch_source"),         # the pipeline would open a run for it and fail it with 1: the command refuses first
    (("replay", "--until", "D2023-01-01"), "no es una entrega del plan"),
    (("replay", "--until", LAUNCH_ID), "anterior a la siguiente entrega pendiente"),
    (("docs-sync",), "README"),
])
def test_incompatible_options_exit_2_before_writing(project, args, says):
    """AC30: a combination that cannot do what it says exits with 2 and names why, before a state file, a lock or any output is written (the tree is the same bytes)."""
    state = project("launched")
    if args[0] == "docs-sync":
        Path(state.cfg.paths.readme).unlink(missing_ok=True)
    before = tree_digest(state.root)
    result = cli(*args, "--config", state.config)
    assert result.code == 2 and says in result.err and result.out == "", (result.code, result.err)
    assert tree_digest(state.root) == before


def test_an_unknown_task_or_option_exits_2_from_the_parser(project):
    state = project("launched")
    before = tree_digest(state.root)
    for args in (("task", "nope"), ("run", "--only", "nope"), ("run", "--nope")):
        assert cli(*args, "--config", state.config).code == 2
    assert tree_digest(state.root) == before


def test_a_task_from_load_on_of_a_new_run_exits_2_and_writes_nothing(project):
    """AC28, B2 of project 05's evaluation: ``task load`` (and every task after it) without ``--run-key`` is a new run that holds no delivery: exit 2, the reason said, and not a byte
    written (before, it exited with 1 and left a ``failed`` run)."""
    state = project("launched")
    before = tree_digest(state.root)
    for task_id in TASK_IDS[TASK_IDS.index("load"):]:
        result = cli("task", task_id, "--config", state.config)
        assert result.code == 2 and "no tiene una entrega" in result.err and result.out == "", (task_id, result.code, result.err)
    assert tree_digest(state.root) == before


@pytest.mark.parametrize("kind, until, says", [("replayed", DAILY_ID, "no hay entregas pendientes"), ("launched", LAUNCH_ID, "anterior a la siguiente entrega pendiente")])
def test_replay_until_a_delivery_already_loaded_exits_2_whether_or_not_one_is_pending(project, kind, until, says):
    """AC30, A4 of project 05: ``--until`` a delivery that is already loaded exits with 2 and writes nothing, with every delivery loaded and with another one pending."""
    state = project(kind)
    before = tree_digest(state.root)
    result = cli("replay", "--config", state.config, "--until", until)
    assert result.code == 2 and says in result.err and "No se escribió nada" in result.err, (result.code, result.err)
    assert tree_digest(state.root) == before


# --- the exit codes 0, 1, 2 and 3 --------------------------------------------------------------------------------------------------------------------------------


def test_a_replay_with_nothing_pending_exits_0_without_the_lock(project):
    state = project("replayed")
    before = tree_digest(state.root)
    outcome: list = []

    def run() -> None:
        outcome.append(cli("replay", "--config", state.config))

    with sole_writer(state.cfg.paths.interim_dir, "another command", "other"):
        thread = threading.Thread(target=run)
        thread.start()
        thread.join(timeout=120)
    assert outcome[0].code == 0 and "no hay entregas pendientes" in outcome[0].out
    assert tree_digest(state.root) == before


def test_a_task_that_fails_exits_1_and_says_why(project, monkeypatch):
    """A task that raises exits with 1 and the line says its kind of error; ``-v`` adds the traceback; the run is ``failed`` in its state."""
    state = project("recover")
    monkeypatch.setattr(pipeline, "estimate_delivery", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("the estimate blew up")))
    result = cli("task", "estimate", "--config", state.config, "--run-key", "a")
    assert result.code == 1 and "falló: RuntimeError: the estimate blew up" in result.err and "Traceback" not in result.err
    assert state_file(state, "a")["status"] == "failed"
    assert "Traceback" in cli("task", "estimate", "--config", state.config, "--run-key", "a", "-v").err


def test_a_rejected_delivery_or_source_exits_3(project):
    """A delivery that fails a blocking rule and a source that is not the pinned one exit with 3 and say which rule; the delivery is ``rejected`` in its manifest."""
    state = project("deliver")
    tamper_delivery(state.cfg, DAILY_ID)
    result = cli("task", "validate", "--config", state.config, "--run-key", "a")
    assert result.code == 3 and "V13" in result.err and manifest_of(state)[DAILY_ID] == "rejected"
    source = Path(state.cfg.source.train_path)
    source.write_bytes(source.read_bytes() + b"changed after the hash was pinned")
    result = cli("task", "fetch_source", "--config", state.config, "--run-key", "s")
    assert result.code == 3 and "V01" in result.err


def test_a_closed_run_or_a_held_lock_exits_2_and_writes_nothing(project):
    """A task of a run that ended exits with 2; so does a command while another process holds the data folder (here, another thread of this one, which the lock refuses too)."""
    state = project("replayed")
    before = tree_digest(state.root)
    closed = sorted(runs_of(state))[0]
    result = cli("task", "report", "--config", state.config, "--run-key", closed)
    assert result.code == 2 and "está cerrada" in result.err
    outcome: list = []

    def run() -> None:
        outcome.append(cli("run", "--config", state.config, "--only", "fetch_source", "--run-key", "L1"))

    with sole_writer(state.cfg.paths.interim_dir, "another command", "other"):
        thread = threading.Thread(target=run)
        thread.start()
        thread.join(timeout=120)
        assert {k: v for k, v in tree_digest(state.root).items() if k != "interim/pipeline.lock"} == before
    assert outcome[0].code == 2 and "Otro hilo" in outcome[0].err
    assert tree_digest(state.root) == before


def test_figures_draw_the_nine_files_and_over_a_folder_that_is_not_one_export_exit_2_and_write_nothing(project):
    state = project("launched")
    result = cli("figures", "--config", state.config)
    ok(result)
    assert len(list(Path(state.cfg.paths.figures_dir).glob("*.png"))) == 9 and result.out.count("escribí") == 9
    (Path(state.cfg.paths.site_dir) / "manifest.json").unlink()
    before = tree_state(state.root)
    failed = cli("figures", "--config", state.config)
    assert failed.code == 2 and "manifest.json" in failed.err and tree_state(state.root) == before


def test_docs_sync_over_a_readme_without_its_markers_exits_2_and_leaves_it_as_it_was(project):
    state = project("replayed")
    readme = Path(state.cfg.paths.readme)
    readme.write_text("# Project\n\nno markers here\n", encoding="utf-8")
    before = tree_digest(state.root)
    result = cli("docs-sync", "--config", state.config)
    assert result.code == 2 and "results:start" in result.err and tree_digest(state.root) == before


def test_module_entry_point_runs_from_another_directory(tmp_path):
    """``python -m promolift --help`` in another process from another directory (the ``-m`` entry): it lists the commands and exits with 0."""
    env = {**os.environ, "PYTHONPATH": str(PROJECT_ROOT / "src")}
    done = subprocess.run([sys.executable, "-m", "promolift", "--help"], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0 and all(name in done.stdout for name in ("run", "replay", "task", "make-fixture", "figures", "docs-sync")), done.stderr
