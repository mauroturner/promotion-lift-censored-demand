"""The fast suite's time limit and what the suite collects (U03, AC38; D29): a full default session over the limit fails and says by
how much; a part of the suite never fails for its time; no helper is collected as a test. The limit is run in this process with
``pytester`` on a toy suite whose limit is 0 s."""

from __future__ import annotations

import ast
from pathlib import Path

TOY_PYPROJECT = """
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-m 'not real_data and not docker'"
markers = ["real_data: x", "docker: x"]
fast_suite_limit_s = "{limit}"
"""
TOY_CONFTEST = "from tests.fixtures.suite_budget import pytest_addoption, pytest_sessionfinish, pytest_sessionstart  # noqa: F401\n"
PROJECT = Path(__file__).resolve().parents[2]


def toy_suite(pytester, limit: str) -> None:
    pytester.makepyprojecttoml(TOY_PYPROJECT.format(limit=limit))
    pytester.makeconftest(TOY_CONFTEST)
    (pytester.path / "tests").mkdir(exist_ok=True)
    (pytester.path / "tests" / "test_toy.py").write_text("def test_one():\n    assert True\n\ndef test_two():\n    assert True\n", encoding="utf-8")


def test_a_full_default_session_over_the_limit_fails_and_says_by_how_much(pytester):
    toy_suite(pytester, "0")
    result = pytester.runpytest_inprocess()
    result.assert_outcomes(passed=2)
    assert result.ret == 1
    result.stdout.re_match_lines([r"La suite rápida tardó \d+\.\d\d s, \d+\.\d\d s por encima del límite de 0 s"])


def test_a_part_of_the_suite_or_a_session_under_the_limit_passes(pytester):
    toy_suite(pytester, "0")
    for args in (["-k", "one"], ["tests/test_toy.py"], ["-m", "not docker"], ["--deselect", "tests/test_toy.py::test_two"]):
        result = pytester.runpytest_inprocess(*args)
        assert result.ret == 0, args
        assert "La suite rápida tardó" not in result.stdout.str(), args
    toy_suite(pytester, "120")
    result = pytester.runpytest_inprocess()
    assert result.ret == 0 and "La suite rápida tardó" not in result.stdout.str()


def test_the_guards_mark_expression_is_the_default_one_of_pyproject():
    """The guard recognises the default selection by its mark expression, so it must be the one that pyproject.toml passes to every
    session; if they drifted apart, no session would ever be failed for its time."""
    import shlex
    import tomllib

    from tests.fixtures.suite_budget import DEFAULT_MARKEXPR

    pyproject = tomllib.loads((PROJECT / "pyproject.toml").read_text(encoding="utf-8"))
    tokens = shlex.split(pyproject["tool"]["pytest"]["ini_options"]["addopts"])
    assert tokens.count("-m") == 1 and tokens[tokens.index("-m") + 1] == DEFAULT_MARKEXPR


def test_the_project_limit_is_120_seconds_and_the_ten_slowest_are_reported(pytestconfig):
    import shlex
    import tomllib

    from tests.fixtures.suite_budget import FAST_SUITE_LIMIT_S

    assert FAST_SUITE_LIMIT_S == 120.0 and float(pytestconfig.getini("fast_suite_limit_s")) == 120.0
    addopts = shlex.split(tomllib.loads((PROJECT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["pytest"]["ini_options"]["addopts"])
    assert "--durations=10" in addopts, "the ten slowest tests of every session are printed for the record (plan, section 24.1)"


def uncollectable_helpers(project: Path) -> list[str]:
    """Names that pytest would collect as tests although they are not tests: a ``test*`` name imported into a test module (the product's
    ``test_delivery`` of project 04, A14), a ``test*`` function or ``Test*`` class defined in ``src/``, and a ``test_*`` function defined in
    a ``tests/`` file whose name is not ``test_*.py`` or ``conftest.py`` and that a test module could import."""
    found: list[str] = []
    for path in sorted((project / "tests").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        relative = path.relative_to(project).as_posix()
        is_test_file = path.name.startswith("test_") and path.suffix == ".py"
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and is_test_file:
                for alias in node.names:
                    if (alias.asname or alias.name).startswith(("test_", "Test")):
                        found.append(f"{relative}:{node.lineno} imports {alias.name!r} as {alias.asname or alias.name!r}")
        if not is_test_file and path.name != "conftest.py":
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
                    found.append(f"{relative}:{node.lineno} defines the helper {node.name!r}, which any test module that imports it would collect")
    for path in sorted((project / "src").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
                found.append(f"{path.relative_to(project).as_posix()}:{node.lineno} defines {node.name!r}")
            if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
                found.append(f"{path.relative_to(project).as_posix()}:{node.lineno} defines the class {node.name!r}")
    return found


def test_no_helper_outside_the_test_files_is_collected(tmp_path):
    # the check itself, on a copy of a project that has each of the three kinds
    probe = tmp_path / "probe"
    (probe / "src" / "pkg").mkdir(parents=True)
    (probe / "tests" / "unit").mkdir(parents=True)
    (probe / "tests" / "fixtures").mkdir(parents=True)
    (probe / "src" / "pkg" / "evaluation.py").write_text("def test_delivery():\n    pass\n\nclass TestRun:\n    pass\n", encoding="utf-8")
    (probe / "tests" / "unit" / "test_a.py").write_text("from pkg.evaluation import test_delivery\nfrom pkg.evaluation import test_delivery as ok\n"
                                                      "from pkg.evaluation import helper\n\ndef test_x():\n    pass\n", encoding="utf-8")
    (probe / "tests" / "fixtures" / "make.py").write_text("def test_value():\n    pass\n\ndef build():\n    pass\n", encoding="utf-8")
    (probe / "tests" / "conftest.py").write_text("def test_conftest_is_not_imported_by_tests():\n    pass\n", encoding="utf-8")
    assert uncollectable_helpers(probe) == [
        "tests/fixtures/make.py:1 defines the helper 'test_value', which any test module that imports it would collect",
        "tests/unit/test_a.py:1 imports 'test_delivery' as 'test_delivery'",   # line 2 imports it with another name: not collected
        "src/pkg/evaluation.py:1 defines 'test_delivery'",
        "src/pkg/evaluation.py:4 defines the class 'TestRun'",
    ]
    # and on the project as it is
    assert uncollectable_helpers(PROJECT) == []


def test_a_last_failed_session_is_a_part_of_the_suite_and_never_failed_for_its_time(pytester):
    """``--lf`` (stored by pytest under ``lf``, the name ``--last-failed`` shares) reruns only a part of the suite: it is not the full
    default selection, with or without something to rerun."""
    toy_suite(pytester, "0")
    (pytester.path / "tests" / "test_toy.py").write_text("def test_one():\n    assert False\n\ndef test_two():\n    assert True\n", encoding="utf-8")
    assert pytester.runpytest_inprocess().ret == 1  # a failing test is a failure, and the first run is the full selection
    for flag in ("--lf", "--last-failed"):
        result = pytester.runpytest_inprocess(flag)
        assert "La suite rápida tardó" not in result.stdout.str(), flag
        result.assert_outcomes(failed=1)
    (pytester.path / "tests" / "test_toy.py").write_text("def test_one():\n    assert True\n\ndef test_two():\n    assert True\n", encoding="utf-8")
    result = pytester.runpytest_inprocess("--lf")
    assert result.ret == 0 and "La suite rápida tardó" not in result.stdout.str()
