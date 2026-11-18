"""The fast suite's time limit (plan, section 24.1; decision D29): a full default session that takes longer than the limit fails
and says by how much.

``tests/conftest.py`` imports the three hooks, so they run in every session. A session is the full default selection when it was
started without test paths (pytest took the ``testpaths`` of pyproject.toml), without ``-k``, ``--deselect`` or ``--lf``, and with the
default mark expression; any other selection is a part of the suite and is never failed for its time. The limit is the ini option
``fast_suite_limit_s`` (180 s by default), so a toy suite can set it to 0. The ten slowest tests of every session are printed by
pytest itself (``--durations=10`` in pyproject.toml), for the record.
"""

from __future__ import annotations

import time

import pytest

FAST_SUITE_LIMIT_S = 180.0
DEFAULT_MARKEXPR = "not real_data and not docker"
_START = pytest.StashKey[float]()


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addini("fast_suite_limit_s", "time limit of a full default session, in seconds (D29)", default=str(FAST_SUITE_LIMIT_S))


def pytest_sessionstart(session: pytest.Session) -> None:
    session.config.stash[_START] = time.perf_counter()


def is_full_default_selection(config: pytest.Config) -> bool:
    """Whether the session runs the whole default suite: no test paths, no -k, no --deselect, no --lf and the default marks."""
    option = config.option
    return (
        config.args_source is not pytest.Config.ArgsSource.ARGS
        and not getattr(option, "keyword", "")
        and not getattr(option, "deselect", None)
        and not getattr(option, "lf", False)
        and getattr(option, "markexpr", "") == DEFAULT_MARKEXPR
    )


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    config = session.config
    if _START not in config.stash or not is_full_default_selection(config):
        return
    elapsed = time.perf_counter() - config.stash[_START]
    limit = float(config.getini("fast_suite_limit_s"))
    if elapsed <= limit:
        return
    session.exitstatus = pytest.ExitCode.TESTS_FAILED
    message = f"La suite rápida tardó {elapsed:.2f} s, {elapsed - limit:.2f} s por encima del límite de {limit:g} s"
    reporter = config.pluginmanager.get_plugin("terminalreporter")
    if reporter is not None:
        reporter.write_line(message, red=True, bold=True)
    else:  # pragma: no cover - pytest always has its terminal reporter unless -p no:terminal
        print(message)
