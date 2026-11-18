"""Shared fixtures, the automatic skipping of the real_data and docker marks and the fast suite's time limit (plan, section 24.1).

The fixtures of the units that come later (the synthetic Parquet files, the loaded warehouses, the launch, the sealed history, the site
files, the rendered design and the figures) are added by the unit that writes the code they need.
"""

from __future__ import annotations

import gc
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
