"""Shared fixtures, the automatic skipping of the real_data and docker marks and the fast suite's time limit (plan, section 24.1).

The fixtures of the units that come later (the synthetic Parquet files, the loaded warehouses, the launch, the sealed history, the site
files, the rendered design and the figures) are added by the unit that writes the code they need.
"""

from __future__ import annotations

import gc
import os
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from tests.fixtures.suite_budget import pytest_addoption, pytest_sessionfinish, pytest_sessionstart  # noqa: F401  (the time limit, D29)

pytest_plugins = ["pytester"]

# The session fixtures keep the fixture's frames, its warehouses and the fitted launches alive for the whole run, and every full collection of the
# garbage collector walks all of them again. The thresholds are raised so that it runs far less often; garbage in cycles is still freed, only
# later. It changes no value and no test (project 04, D93).
gc.set_threshold(200_000, 100, 100)

@pytest.fixture(scope="session", autouse=True)
def _no_flush_to_the_device():
    """``os.fsync`` makes a file survive a power cut, which no test can cause, and on this machine it takes about a seventh of the time of the suite (every atomic write, the
    registry and the lock call it; D29). The session runs without it; a test that is about the flush replaces ``os.fsync`` with its own spy, which wins over this one."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(os, "fsync", lambda descriptor: None)
        yield


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REAL_TRAIN = PROJECT_ROOT / "data" / "raw" / "train.parquet"
REAL_EVAL = PROJECT_ROOT / "data" / "raw" / "eval.parquet"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip, instead of failing, the tests whose external requirement is missing (they are not selected by default either)."""
    skips = {
        "real_data": (not (REAL_TRAIN.exists() and REAL_EVAL.exists()), "the real Parquet files are not in data/raw/"),
        "docker": (shutil.which("docker") is None, "docker is not installed"),
    }
    for item in items:
        for mark, (missing, reason) in skips.items():
            if mark in item.keywords and missing:
                item.add_marker(pytest.mark.skip(reason=reason))


@pytest.fixture(scope="session")
def project_root() -> Path:
    return PROJECT_ROOT


@pytest.fixture(scope="session")
def cfg():
    """The default configuration, loaded once (it is immutable)."""
    from promolift.config import load_config

    return load_config(PROJECT_ROOT / "config" / "pipeline.toml")


@pytest.fixture(scope="session")
def quick_cfg():
    """The quick-mode configuration, loaded once."""
    from promolift.config import load_config

    return load_config(PROJECT_ROOT / "config" / "pipeline.quick.toml")


# --- the synthetic fixture, its sizes and its variants ---------------------------------------------------------------


@pytest.fixture(scope="session")
def fixture_truth(tmp_path_factory: pytest.TempPathFactory):
    """The standard synthetic Parquet pair (300 series x 97 days, seed 0, the planted lifts) and what the generator knows."""
    from tests.fixtures.make_fixture import make_fixture

    return make_fixture(tmp_path_factory.mktemp("fixture"), series=300, seed=0, signal="lift")


@pytest.fixture(scope="session")
def fixture_dir(fixture_truth) -> Path:
    return fixture_truth.dir


@pytest.fixture(scope="session")
def small_truth(tmp_path_factory: pytest.TempPathFactory):
    """The 60-series fixture, for the tests whose subject is one row, one rule or one error: a defect in one row is found by the same code
    whatever the size of the rest, and the standard pair costs more to write and to read."""
    from tests.fixtures.make_fixture import make_fixture

    return make_fixture(tmp_path_factory.mktemp("small_fixture"), series=60, seed=0, signal="lift")


@pytest.fixture(scope="session")
def small_dir(small_truth) -> Path:
    return small_truth.dir


@pytest.fixture(scope="session")
def signal_truth(tmp_path_factory: pytest.TempPathFactory, fixture_truth) -> Callable[[str], object]:
    """``signal_truth(kind)``: the standard fixture with the planted lifts (``lift``, the positive control) or with none (``null``, the
    negative one), each built once per session."""
    from tests.fixtures.make_fixture import make_fixture

    built: dict[str, object] = {"lift": fixture_truth}

    def build(kind: str):
        if kind not in built:
            built[kind] = make_fixture(tmp_path_factory.mktemp(f"signal_{kind}"), series=300, seed=0, signal=kind)
        return built[kind]

    return build


@pytest.fixture(scope="session")
def signal_dir(signal_truth: Callable[[str], object]) -> Callable[[str], Path]:
    """``signal_dir(kind)``: the folder of ``signal_truth(kind)``."""
    return lambda kind: signal_truth(kind).dir


@pytest.fixture(scope="session")
def malformed(tmp_path_factory: pytest.TempPathFactory, small_truth) -> Callable[[str], object]:
    """``malformed(kind)``: the small fixture damaged in one documented way (a ``Malformed``), each kind built once per session."""
    from tests.fixtures.make_fixture import make_malformed

    built: dict[str, object] = {}

    def build(kind: str):
        if kind not in built:
            built[kind] = make_malformed(small_truth, kind, tmp_path_factory.mktemp(f"malformed_{kind}"))
        return built[kind]

    return build


@pytest.fixture
def copy_of(tmp_path: Path) -> Callable[[Path], Path]:
    """``copy_of(path)``: a copy of a file or a folder inside this test's ``tmp_path``, for a test that writes."""

    def copy(path: Path) -> Path:
        target = tmp_path / path.name
        if path.is_dir():
            shutil.copytree(path, target)
        else:
            shutil.copy2(path, target)
        return target

    return copy


# --- configurations that point at a fixture, the fixture read once --------------------------------------------------------------------------


@pytest.fixture
def cfg_for(cfg, tmp_path: Path):
    """``cfg_for(folder, malformed=None, **source_changes)``: the default configuration pointed at the Parquet pair of `folder`, with its real
    sizes and hashes accepted and every generated folder inside this test's ``tmp_path``; a ``Malformed`` brings its own limits and, for
    ``wrong_hash``, the hashes of the pair it was damaged from."""
    import dataclasses

    from tests.fixtures.make_fixture import fixture_config

    def build(folder: Path, malformed=None, **source_changes):
        built = fixture_config(cfg, folder)
        source = built.source
        if malformed is not None:
            if malformed.hash_from is not None:
                base = fixture_config(cfg, malformed.hash_from).source
                source = dataclasses.replace(source, train_bytes=base.train_bytes, train_sha256=base.train_sha256)
            source = dataclasses.replace(source, **malformed.limits)
        source = dataclasses.replace(source, **source_changes)
        paths = dataclasses.replace(
            cfg.paths, raw_dir=tmp_path / "raw", interim_dir=tmp_path / "interim", warehouse=tmp_path / "warehouse" / "promolift.sqlite",
            models_dir=tmp_path / "models", outputs_dir=tmp_path / "outputs" / "powerbi", site_dir=tmp_path / "outputs" / "site",
            reports_dir=tmp_path / "reports", seal=tmp_path / "reports" / "model_seal.json", dashboard_html=tmp_path / "dashboard" / "design.html",
            readme=tmp_path / "README.md", figures_dir=tmp_path / "figures")
        return dataclasses.replace(built, source=source, paths=paths)

    return build


@pytest.fixture(scope="session")
def canonical(cfg, fixture_truth):
    """The standard fixture, read strictly once (train and eval) and made canonical: what ``ingest.canonical`` returns."""
    from promolift.ingest import canonical as make_canonical
    from promolift.ingest import read_source
    from tests.fixtures.make_fixture import fixture_config

    accepted = fixture_config(cfg, fixture_truth.dir)
    train, _ = read_source(accepted.source.train_path, "train", accepted)
    eval_, _ = read_source(accepted.source.eval_path, "eval", accepted)
    return make_canonical((train, eval_), accepted)


@pytest.fixture(scope="session")
def published(cfg, canonical, tmp_path_factory: pytest.TempPathFactory):
    """Every delivery of the plan, published once from the standard fixture: ``plan``, ``out_dir`` and ``items[delivery_id] = (entry, days, cube)``
    with the delivery read back from its two files."""
    from dataclasses import dataclass, field

    from promolift.deliveries import delivery_plan, publish, read_delivery

    @dataclass
    class Published:
        plan: list
        out_dir: Path
        items: dict = field(default_factory=dict)

    out = tmp_path_factory.mktemp("deliveries")
    result = Published(delivery_plan(cfg), out)
    for spec in result.plan:
        entry = publish(spec, canonical, out, cfg)
        days, cube = read_delivery(out, entry)
        result.items[spec.delivery_id] = (entry, days, cube)
    return result


# --- warehouses with their deliveries loaded (U07 on) -------------------------------------------------------------------------------------------


@pytest.fixture(scope="session")
def store_upto(cfg, canonical, published, tmp_path_factory: pytest.TempPathFactory):
    """``store_upto(delivery_id)``: a ``Store`` (``db``, ``interim``, ``loaded``) with every delivery of the plan up to `delivery_id` loaded into one
    warehouse and into the cube of the loaded deliveries, each built once per session. Read-only: a test that writes works on ``copy_store``."""
    from dataclasses import dataclass

    from promolift.warehouse import connect, load_delivery

    @dataclass(frozen=True)
    class Store:
        db: Path
        interim: Path
        loaded: tuple[str, ...]

    built: dict[str, Store] = {}

    def build(delivery_id: str) -> Store:
        if delivery_id not in built:
            ids = [spec.delivery_id for spec in published.plan]
            take = ids[: ids.index(delivery_id) + 1]
            folder = tmp_path_factory.mktemp(f"store_{delivery_id}")
            conn = connect(folder / "w.sqlite")
            try:
                for spec in published.plan:
                    if spec.delivery_id in take:
                        entry, days, cube_files = published.items[spec.delivery_id]
                        load_delivery(conn, days, cube_files, spec, f"run-{spec.delivery_id}", cfg, sha256=entry.sha256, series=canonical.series,
                                      interim_dir=folder / "interim")
            finally:
                conn.close()
            built[delivery_id] = Store(folder / "w.sqlite", folder / "interim", tuple(take))
        return built[delivery_id]

    return build


@pytest.fixture
def copy_store(tmp_path: Path):
    """``copy_store(store)``: a copy of a ``Store`` inside this test's ``tmp_path``, for a test that loads or writes."""

    def copy(store):
        from dataclasses import replace

        shutil.copytree(store.interim, tmp_path / "interim")
        shutil.copyfile(store.db, tmp_path / "w.sqlite")
        return replace(store, db=tmp_path / "w.sqlite", interim=tmp_path / "interim")

    return copy


# --- the launch (U09 on) ---------------------------------------------------------------------------------------------------------------------


@pytest.fixture(scope="session")
def launch_config(quick_cfg):
    """``launch_config(folder, interim=None, **changes)``: the quick configuration with every folder it writes inside `folder` (and the cube read from `interim`);
    `changes` replace keys of ``recovery``, ``split`` and so on as ``section=<replacement section>``."""
    import dataclasses

    def build(folder: Path, interim: Path | None = None, **sections):
        paths = dataclasses.replace(
            quick_cfg.paths, interim_dir=interim or folder / "interim", models_dir=folder / "models", seal=folder / "reports" / "model_seal.json",
            warehouse=folder / "w.sqlite", reports_dir=folder / "reports")
        return dataclasses.replace(quick_cfg, paths=paths, **sections)

    return build


@pytest.fixture(scope="session")
def launched(store_upto, launch_config, fixture_truth, tmp_path_factory: pytest.TempPathFactory):
    """The launch of the standard fixture, run once (the quick configuration, a small R3): a warehouse, a cube and a folder of its own, the ``LaunchResult`` and
    the configuration. Read-only; a test that launches again works on ``copy_store`` and its own folder."""
    from datetime import datetime
    from types import SimpleNamespace

    from promolift.launch import fit_model
    from promolift.registry import RunMeta
    from promolift.warehouse import connect

    store = store_upto("L2024-06-25")
    folder = tmp_path_factory.mktemp("launched")
    shutil.copytree(store.interim, folder / "interim")
    shutil.copyfile(store.db, folder / "w.sqlite")
    cfg = launch_config(folder)
    conn = connect(folder / "w.sqlite")
    try:
        result = fit_model(cfg, conn, RunMeta("run-launch", datetime(2024, 6, 26)), train_sha256=fixture_truth.train_sha256, eval_sha256=fixture_truth.eval_sha256)
    finally:
        conn.close()
    return SimpleNamespace(folder=folder, cfg=cfg, result=result, db=folder / "w.sqlite", train=fixture_truth.train_sha256, eval=fixture_truth.eval_sha256)


@pytest.fixture
def fresh(launch_config, store_upto, tmp_path: Path):
    """``fresh(seal=None, **sections)``: a launch-ready copy of the launch store (a warehouse without the model and its cube) in this test's folder, and the
    quick configuration pointed at it: ``(cfg, conn)``. The connections are closed when the test ends."""
    import dataclasses

    from promolift.warehouse import connect

    store = store_upto("L2024-06-25")
    opened = []

    def build(seal: Path | None = None, **sections):
        shutil.copytree(store.interim, tmp_path / "interim", dirs_exist_ok=True)
        shutil.copyfile(store.db, tmp_path / "w.sqlite")
        cfg = launch_config(tmp_path, **sections)
        if seal is not None:
            cfg = dataclasses.replace(cfg, paths=dataclasses.replace(cfg.paths, seal=seal))
        conn = connect(tmp_path / "w.sqlite")
        opened.append(conn)
        return cfg, conn

    yield build
    for conn in opened:
        conn.close()


# --- the issued week of the test (U11 on) ----------------------------------------------------------------------------------------------------


@pytest.fixture(scope="session")
def issued_week(launched, published, canonical, cfg, launch_config, tmp_path_factory: pytest.TempPathFactory):
    """The launch store of ``launched`` with the seven days of the test loaded and issued one delivery after another, and the close loaded (it has no rows): what the
    evaluation of the test reads. Built once per session and read-only; a test that evaluates works on ``week_copy``."""
    from datetime import datetime
    from types import SimpleNamespace

    from promolift.cube import open_loaded_cube
    from promolift.daily import run_day
    from promolift.registry import RunMeta, sealed_view
    from promolift.warehouse import connect, load_delivery

    folder = tmp_path_factory.mktemp("issued_week")
    for name in ("interim", "models", "reports"):
        shutil.copytree(launched.folder / name, folder / name)
    shutil.copyfile(launched.db, folder / "w.sqlite")
    week_cfg = launch_config(folder)
    view = sealed_view(week_cfg, launched.train, launched.eval)
    bundle = launched.result.bundle
    conn = connect(folder / "w.sqlite")
    try:
        for spec in published.plan:
            if spec.kind == "launch":
                continue
            entry, days, cube_files = published.items[spec.delivery_id]
            load_delivery(conn, days, cube_files, spec, f"run-{spec.delivery_id}", cfg, sha256=entry.sha256, series=canonical.series, interim_dir=folder / "interim")
            if spec.kind == "daily":
                run_day(conn, open_loaded_cube(folder / "interim"), bundle, RunMeta(f"run-{spec.delivery_id}", spec.as_of), spec, view, interim_dir=folder / "interim")
    finally:
        conn.close()
    close = published.plan[-1]
    return SimpleNamespace(folder=folder, cfg=week_cfg, view=view, bundle=bundle, db=folder / "w.sqlite", interim=folder / "interim", train=launched.train, eval=launched.eval,
                           run=RunMeta("run-close", close.as_of), close=close)


@pytest.fixture
def week_copy(issued_week, launch_config, tmp_path: Path):
    """``week_copy()``: a copy of ``issued_week`` inside this test's ``tmp_path`` for a test that evaluates, with its configuration, a connection and the loaded cube."""
    from types import SimpleNamespace

    from promolift.cube import open_loaded_cube
    from promolift.registry import sealed_view
    from promolift.warehouse import connect

    opened = []

    def copy(**sections):
        folder = tmp_path / "week"
        shutil.copytree(issued_week.folder, folder)
        week_cfg = launch_config(folder, **sections)
        conn = connect(folder / "w.sqlite")
        opened.append(conn)
        return SimpleNamespace(folder=folder, cfg=week_cfg, view=sealed_view(week_cfg, issued_week.train, issued_week.eval), conn=conn, db=folder / "w.sqlite",
                               cube=open_loaded_cube(folder / "interim"), bundle=issued_week.bundle, run=issued_week.run, seal=week_cfg.paths.seal)

    yield copy
    for conn in opened:
        conn.close()


@pytest.fixture(scope="session")
def evaluated_week(issued_week, launch_config, tmp_path_factory: pytest.TempPathFactory):
    """The issued week evaluated once as the run of the close, on a copy of its own: the connection of ``clone`` is closed, ``out`` is what ``evaluate`` returned.
    Read-only; a test that writes works on a ``clone`` of its ``folder``."""
    from types import SimpleNamespace

    from promolift.reporting import evaluate
    from tests.fixtures.weeks import clone

    w = clone(issued_week.folder, tmp_path_factory.mktemp("evaluated_week") / "w", launch_config, issued_week.train, issued_week.eval)
    out = evaluate(w.conn, w.cube, issued_week.bundle, issued_week.run, w.view, seal_path=w.seal)
    w.conn.close()
    return SimpleNamespace(**{**vars(w), "out": out, "bundle": issued_week.bundle, "run": issued_week.run, "folder": w.db.parent})


# --- the star model of Power BI (U12 on) --------------------------------------------------------------------------------------------------------


@pytest.fixture(scope="session")
def star_export(evaluated_week, launch_config, tmp_path_factory: pytest.TempPathFactory):
    """The star model exported once from a copy of the evaluated week, with two runs and their validation rules written into the copy first (nothing else writes them
    yet): ``out`` (the folder of the Parquet files), ``paths``, ``db``, ``view``, ``run``, ``cfg``. Read-only; a test that writes works on a ``clone``."""
    from types import SimpleNamespace

    from promolift.dashboard.semantic_model import MODEL
    from promolift.export import export_star_schema
    from promolift.registry import RunMeta
    from tests.fixtures.weeks import clone

    folder = tmp_path_factory.mktemp("star_export")
    w = clone(evaluated_week.folder, folder / "w", launch_config, evaluated_week.view.train_sha256_seen, evaluated_week.view.eval_sha256_seen)
    for run_key, status, as_of in (("run-launch", "ok", "2024-06-26 00:00:00"), ("run-close", "ok", "2024-07-03 00:00:00")):
        w.conn.execute("INSERT INTO pipeline_runs VALUES (?, '2026-11-18 10:00:00', '2026-11-18 10:01:00', ?, NULL, ?, ?, ?, 0, 0, 100.5, 120.5, 'PeakWorkingSetSize', 'ok')",
                       (run_key, status, as_of, evaluated_week.view.train_sha256_seen, evaluated_week.view.eval_sha256_seen))
        for rule, name, severity, passed in (("V10", "La entrega es la siguiente del plan", "blocking", 1), ("V20", "Descuento 0", "warning", 0), ("I01", "Horas sin stock de noche", "info", 0)):
            w.conn.execute("INSERT INTO validation_results VALUES (?, ?, ?, ?, 'delivery', 'per_run', ?, 3, 48, '[]')", (run_key, rule, name, severity, passed))
    run = RunMeta("run-close", evaluated_week.run.as_of)
    out = folder / "powerbi"
    paths = export_star_schema(w.conn, out, MODEL, run, w.view, seal_path=w.seal, interim_dir=w.cfg.paths.interim_dir)
    w.conn.close()
    return SimpleNamespace(out=out, paths=paths, db=w.db, view=w.view, run=run, cfg=w.cfg, seal=w.seal, folder=w.db.parent)


@pytest.fixture(scope="session")
def rendered_html(star_export, tmp_path_factory: pytest.TempPathFactory):
    """The HTML design rendered once from the exported star model: ``path`` and ``html``."""
    from types import SimpleNamespace

    from promolift.dashboard.render import render_design
    from promolift.dashboard.semantic_model import MODEL

    path = render_design(MODEL, star_export.out, tmp_path_factory.mktemp("design") / "powerbi-design.html", star_export.run)
    return SimpleNamespace(path=path, html=path.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def site_files(star_export, tmp_path_factory: pytest.TempPathFactory):
    """The five site files written once from the exported star model (the sealed test week): ``out``, ``paths`` and ``site`` (what ``read_site`` verified)."""
    from types import SimpleNamespace

    from promolift.site_export import export_site, read_site
    from promolift.warehouse import connect

    out = tmp_path_factory.mktemp("site") / "site"
    conn = connect(star_export.db)
    try:
        paths = export_site(conn, out, star_export.run, star_export.view, seal_path=star_export.seal, max_total_bytes=star_export.cfg.site.max_total_bytes)
    finally:
        conn.close()
    return SimpleNamespace(out=out, paths=paths, site=read_site(out))


@pytest.fixture(scope="session")
def figures_written_for_bytes(site_files, tmp_path_factory: pytest.TempPathFactory):
    """The nine figures drawn once from the site files: the paths of the PNG files."""
    from promolift.figures import write_figures

    return write_figures(site_files.out, tmp_path_factory.mktemp("figures_bytes"))


# --- the flow of the small fixture, task by task (U16 on) ------------------------------------------------------------------------------------------


@pytest.fixture(scope="session")
def tiny_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The 20-series fixture, for the flow of the tasks: what a run does does not depend on how many series it has, and each of its runs costs less."""
    from tests.fixtures.make_fixture import make_fixture

    return make_fixture(tmp_path_factory.mktemp("tiny_fixture"), series=20, seed=0, signal="lift").dir


@pytest.fixture(scope="session")
def pipeline_launched(tmp_path_factory: pytest.TempPathFactory, quick_cfg, tiny_dir):
    """The launch run of the 60-series fixture, run once through the eleven tasks (``run_all``): ``root``, ``cfg`` and ``results`` (what each task returned). A test that writes
    works on ``copy_state``."""
    from promolift import pipeline
    from tests.fixtures.pipeline_state import state_of

    state = state_of(tmp_path_factory.mktemp("pipeline_launched") / "state", quick_cfg, tiny_dir)
    state.results = pipeline.run_all(state.cfg, run_key="launch")
    return state


@pytest.fixture(scope="session")
def pipeline_staged(tmp_path_factory: pytest.TempPathFactory, pipeline_launched, quick_cfg):
    """``pipeline_staged(upto)``: a state of the 60-series flow after the launch run in which the run ``a`` took the next pending delivery and ran its tasks up to ``upto``
    (``deliver``, ``load``, ``recover``, ``render_dashboard``...). Each stage is built once per session on a copy of the nearest earlier one, so the tests that need a run
    half done copy it instead of running its tasks again. Read-only; a test that writes works on ``copy_state``."""
    from promolift import pipeline
    from tests.fixtures.pipeline_state import copy_state

    built: dict[str, object] = {}

    def stage(upto: str):
        if upto not in built:
            order = pipeline.TASK_IDS
            earlier = [task for task in built if order.index(task) < order.index(upto)]
            base = max(earlier, key=order.index) if earlier else None
            state = copy_state(built[base] if base else pipeline_launched, tmp_path_factory.mktemp(f"staged_{upto}") / "state", quick_cfg)
            for task_id in order[(order.index(base) + 1 if base else 0): order.index(upto) + 1]:
                pipeline.run_task(task_id, "a", state.cfg)
            built[upto] = state
        return built[upto]

    return stage


@pytest.fixture(scope="session")
def pipeline_before_close(tmp_path_factory: pytest.TempPathFactory, pipeline_launched, quick_cfg):
    """A copy of ``pipeline_launched`` with the seven daily deliveries replayed (``runs``): the close is the pending delivery and the seal has no test part."""
    from promolift import pipeline
    from tests.fixtures.pipeline_state import copy_state

    state = copy_state(pipeline_launched, tmp_path_factory.mktemp("pipeline_before_close") / "state", quick_cfg)
    state.runs = pipeline.replay(state.cfg, until="D2024-07-02")
    return state


@pytest.fixture(scope="session")
def pipeline_replayed(tmp_path_factory: pytest.TempPathFactory, pipeline_before_close, quick_cfg):
    """The whole plan, built once from a copy of ``pipeline_before_close``: the close run after the seven daily ones (``runs``, eight in all), and then a run with no delivery left
    (``idle``); ``before_idle`` is the digest of what is published before that last run."""
    from promolift import pipeline
    from tests.fixtures.pipeline_state import copy_state, published_digest

    state = copy_state(pipeline_before_close, tmp_path_factory.mktemp("pipeline_replayed") / "state", quick_cfg)
    state.runs = [*pipeline_before_close.runs, *pipeline.replay(state.cfg)]
    state.before_idle = published_digest(state.cfg)
    state.idle = pipeline.run_all(state.cfg, run_key="idle")
    return state
