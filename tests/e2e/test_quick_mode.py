"""The quick mode, isolated (U17, AC31; RNF04; D27): from another working directory, with ``PROMOLIFT_HOME`` on a clean clone of the project's configuration, the documented
commands write only under ``data/quick/``: not a byte and not a modification time anywhere else of the clone, nothing in the working directory, and nothing in this repository's
project.

Project 01 wrote its quick run over the versioned outputs and resolved a relative path against the directory of the command. The replay is ``make-fixture`` and ``replay --until``
(the launch and the first daily delivery) over a clone that has only ``config/``, with the fixture reduced to 20 series (a whole replay of the quick configuration is for U19: plan,
section 24.1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from promolift.config import ENV_HOME, load_config
from tests.e2e.cli_helpers import PROJECT_ROOT, at_home, cli, fingerprint, quick_project
from tests.fixtures.pipeline_state import DAILY_ID

QUICK = "data/quick/"


def changed(before: dict, after: dict) -> set[str]:
    return {name for name in set(before) | set(after) if before.get(name) != after.get(name)}


@pytest.fixture(scope="module")
def quick_replay(tmp_path_factory: pytest.TempPathFactory):
    """The quick fixture and the quick replay up to the first daily delivery, run once from another working directory over a clean clone: the exit codes, what they wrote and the
    fingerprints of the clone, of the working directory and of this repository's project before and after."""
    from types import SimpleNamespace

    base = tmp_path_factory.mktemp("quick_clone")
    home, elsewhere = quick_project(base / "clone"), base / "elsewhere"
    elsewhere.mkdir()
    before, real_before = fingerprint(home), fingerprint(PROJECT_ROOT)
    with at_home(home, elsewhere):
        made = cli("make-fixture", "data/quick", "--series", "20")
        result = cli("replay", "--config", "config/pipeline.quick.toml", "--until", DAILY_ID)
    return SimpleNamespace(home=home, elsewhere=elsewhere, made=made, result=result, before=before, after=fingerprint(home), real_before=real_before, real_after=fingerprint(PROJECT_ROOT))


@pytest.mark.slow
def test_quick_replay_from_other_cwd_touches_only_data_quick(quick_replay):
    """AC31: the fixture and the replay end with 0, every file they created or changed is under ``data/quick/`` of the clone, the working directory stays empty and this repository's
    project is as it was (the quick run writes none of its versioned outputs, its warehouse or its reports)."""
    assert quick_replay.made.code == 0 and quick_replay.result.code == 0, (quick_replay.made.err, quick_replay.result.err)
    assert set(quick_replay.before) == {f"config/{p.name}" for p in (PROJECT_ROOT / "config").iterdir()}, "the clone was clean: only its configuration"
    touched = changed(quick_replay.before, quick_replay.after)
    assert touched and all(name.startswith(QUICK) for name in touched), sorted(n for n in touched if not n.startswith(QUICK))
    assert list(Path(quick_replay.elsewhere).iterdir()) == [], "nothing in the directory the commands were started from"
    assert changed(quick_replay.real_before, quick_replay.real_after) == set(), "the repository's project was not touched"
    quick = Path(quick_replay.home) / "data" / "quick"
    for name in ("train.parquet", "eval.parquet", "source.lock.json", "promolift.sqlite", "outputs/powerbi/manifest.json", "outputs/site/manifest.json", "dashboard/powerbi-design.html",
                 "reports/evaluation_summary.json", "reports/model_seal.json"):
        assert (quick / name).is_file(), name
    assert "2 corridas" in quick_replay.result.out and f"entrega {DAILY_ID}" in quick_replay.result.out


def test_every_path_of_the_quick_configuration_is_under_data_quick(monkeypatch):
    monkeypatch.delenv(ENV_HOME, raising=False)
    cfg = load_config(Path("config/pipeline.quick.toml"))
    quick = (PROJECT_ROOT / "data" / "quick").resolve()
    paths = [cfg.source.train_path, cfg.source.eval_path, *vars(cfg.paths).values()]
    assert all(Path(p).resolve().is_relative_to(quick) for p in paths), [str(p) for p in paths]


def test_a_refusal_in_a_new_clone_leaves_only_its_configuration(tmp_path):
    """A6 (L85): a command refused with 2 in a clone that has only ``config/`` leaves nothing behind, not even the empty ``data/quick/interim/`` its lock made."""
    home, elsewhere = quick_project(tmp_path / "clone"), tmp_path / "elsewhere"
    elsewhere.mkdir()
    before = fingerprint(home)
    with at_home(home, elsewhere):
        for args in (("task", "load"), ("run", "--only", "validate", "--from", "load"), ("replay", "--until", "X2024-01-01")):
            result = cli(*args, "--config", "config/pipeline.quick.toml")
            assert result.code == 2, (args, result.err)
            assert fingerprint(home) == before and sorted(p.name for p in Path(home).iterdir()) == ["config"], args
