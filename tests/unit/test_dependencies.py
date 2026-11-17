"""The environment and its dependencies (U01, item 5): every third-party module the code imports is a pinned direct requirement in the
file that corresponds to it (AC36, project 03 B6), every pin is exact (D33, RNF01), `pip check` is judged by its exit code (project 05's
R3-pip-check-stdout-substring) and the generated state stays out of Git."""

from __future__ import annotations

import ast
import functools
import importlib.metadata
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[2]
# Top-level names that belong to this project, not to a distribution
LOCAL_TOP_LEVEL = {"promolift", "tests"}
# The line that separates the direct pins (above) from the transitive ones (below) in every requirements file
TRANSITIVE_MARKER = "# transitive"
PIN = re.compile(r"([A-Za-z0-9][A-Za-z0-9_.-]*)==([A-Za-z0-9_.+!-]+)")
REQUIREMENT_NAME = re.compile(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
REQUIREMENT_FILES = ("requirements.txt", "requirements-dev.txt")
# The direct pins the landing declares itself (S5): everything else a direct pin needs has a row in LANDING-EXPANSION.md
LANDING_DECLARED = {"pandas", "scikit-learn"}


def normalize(name: str) -> str:
    """PEP 503 normalization: ``scikit_learn``, ``Scikit-Learn`` and ``scikit-learn`` are one distribution."""
    return re.sub(r"[-_.]+", "-", name).lower()


@dataclass
class Pins:
    direct: dict[str, str] = field(default_factory=dict)
    transitive: dict[str, str] = field(default_factory=dict)
    includes: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def all(self) -> dict[str, str]:
        return {**self.direct, **self.transitive}


def read_pins(path: Path) -> Pins:
    pins = Pins()
    section = pins.direct
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if raw.strip() == TRANSITIVE_MARKER:
            section = pins.transitive
            continue
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("-r "):
            pins.includes.append(line[3:].strip())
            continue
        match = PIN.fullmatch(line)
        if not match:
            pins.problems.append(f"{path.name}:{number}: {line!r} is not an exact == pin")
            continue
        name = normalize(match.group(1))
        if name in pins.all:
            pins.problems.append(f"{path.name}:{number}: {name} is pinned twice")
            continue
        section[name] = match.group(2)
    return pins


def all_pins(project: Path) -> dict[str, Pins]:
    return {name: read_pins(project / name) for name in REQUIREMENT_FILES}


def third_party_imports(root: Path, project: Path, local: frozenset[str]) -> dict[str, set[str]]:
    """Top-level module -> the files (relative to the project) that import it, for every absolute import of a module outside the
    standard library and outside this project."""
    found: dict[str, set[str]] = {}
    for path in sorted(root.rglob("*.py")):
        stat = path.stat()
        for top in _imported_tops(str(path), stat.st_mtime_ns, stat.st_size, local):
            found.setdefault(top, set()).add(path.relative_to(project).as_posix())
    return found


@functools.lru_cache(maxsize=4096)
def _imported_tops(path: str, mtime_ns: int, size: int, local: frozenset[str]) -> frozenset[str]:
    """The third-party top-level modules one file imports, parsed once per version of the file (its time and size are part of the key):
    the project's files are scanned by several tests."""
    del mtime_ns, size
    tree = ast.parse(Path(path).read_text(encoding="utf-8"), filename=path)
    tops = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module]
        else:
            continue
        for name in names:
            top = name.split(".", 1)[0]
            if top not in sys.stdlib_module_names and top != "__future__" and top not in LOCAL_TOP_LEVEL and top not in local:
                tops.add(top)
    return frozenset(tops)


@functools.cache
def installed_providers() -> dict[str, list[str]]:
    """``importlib.metadata.packages_distributions()``, read once per session: it scans every installed distribution, and what is
    installed does not change while the suite runs."""
    return importlib.metadata.packages_distributions()


def distribution_of(module: str) -> str:
    """The distribution that provides an importable top-level module (``sklearn`` -> ``scikit-learn``); the module's own name when
    nothing installed provides it, so a missing package is still reported by a recognisable name."""
    providers = installed_providers().get(module)
    return normalize(providers[0] if providers else module)


def dependency_problems(project: Path) -> list[str]:
    """Every third-party import of ``src/`` and ``research/`` must be a direct pin of requirements.txt (the Airflow image installs only
    that file); every one of ``tests/`` a direct pin of either file. A module pinned only in a transitive section is told so, and one
    that only requirements-dev.txt pins directly is a development tool that runtime code cannot import."""
    pins = all_pins(project)
    runtime, dev = pins["requirements.txt"], pins["requirements-dev.txt"]
    transitive = runtime.transitive | dev.transitive
    problems: list[str] = []
    for folder in ("src", "research", "tests"):
        root = project / folder
        if not root.is_dir():
            continue
        local = frozenset(path.stem for path in root.rglob("*.py")) if folder == "research" else frozenset()
        allowed = runtime.direct | dev.direct if folder == "tests" else runtime.direct
        for module, files in sorted(third_party_imports(root, project, local).items()):
            dist = distribution_of(module)
            if dist in allowed:
                continue
            if dist in dev.direct:
                kind = "is a development-only dependency (a direct pin of requirements-dev.txt), which runtime code cannot import"
            elif dist in transitive:
                kind = "is pinned only as a transitive dependency"
            else:
                kind = "is not pinned as a direct requirement"
            problems.append(f"{module} ({dist}) is imported by {', '.join(sorted(files))} but {kind}")
    return problems


def never_applies(marker: str) -> bool:
    """A requirement only an extra asks for, or only a Python older than the project's 3.11 (pyproject's requires-python): ``< "3.N"``
    for N up to 11 and ``<= "3.N"`` for N up to 10, in single or double quotes."""
    if "extra" in marker:
        return True
    older = re.search(r"""python_version\s*(<=|<)\s*(['"])3\.(\d+)\2""", marker)
    if older is None:
        return False
    minor = int(older.group(3))
    return minor <= 11 if older.group(1) == "<" else minor <= 10


def required_names(dist: str) -> set[str]:
    """The distributions a pinned distribution requires on some supported platform and Python."""
    names = set()
    for requirement in importlib.metadata.requires(dist) or []:
        if ";" in requirement and never_applies(requirement.split(";", 1)[1]):
            continue
        match = REQUIREMENT_NAME.match(requirement)
        if match:
            names.add(normalize(match.group(1)))
    return names


def pip_check_passed(command: list[str]) -> bool:
    """`pip check` is judged by its exit code and nothing it prints (project 05's R3-pip-check-stdout-substring): a pip release that
    words its report differently must not break the check, and a failing one that happens to print the success words must not pass."""
    return subprocess.run(command, capture_output=True, text=True, timeout=120).returncode == 0


def probe_project(tmp_path: Path, files: dict[str, str], drop: tuple[str, ...] = ()) -> Path:
    """A copy of the project's requirements files (without the pins whose names start with one of ``drop``) next to the given source
    files (path relative to the probe -> text)."""
    probe = tmp_path / "probe"
    probe.mkdir()
    for name in REQUIREMENT_FILES:
        lines = (PROJECT / name).read_text(encoding="utf-8").splitlines()
        kept = [line for line in lines if not line.startswith(tuple(f"{pin}==" for pin in drop))]
        (probe / name).write_text("\n".join(kept) + "\n", encoding="utf-8")
    for relative, text in files.items():
        (probe / relative).parent.mkdir(parents=True, exist_ok=True)
        (probe / relative).write_text(text, encoding="utf-8")
    return probe


# --- AC36: the imports and the pins ------------------------------------------------------------------------------------


def test_every_direct_import_is_a_pinned_requirement_and_documented(tmp_path):
    # the check itself, on a module that imports pyarrow with its pin removed, and then with pyarrow filed as a transitive pin
    source = {"src/promolift/parquet_probe.py": "import numpy as np\nimport pyarrow.parquet as pq\nfrom sklearn import metrics\n"}
    probe = probe_project(tmp_path, source, drop=("pyarrow",))
    assert dependency_problems(probe) == [
        "pyarrow (pyarrow) is imported by src/promolift/parquet_probe.py but is not pinned as a direct requirement"
    ]
    requirements = probe / "requirements.txt"
    requirements.write_text(requirements.read_text(encoding="utf-8") + "pyarrow==26.0.1\n", encoding="utf-8")
    assert dependency_problems(probe) == [
        "pyarrow (pyarrow) is imported by src/promolift/parquet_probe.py but is pinned only as a transitive dependency"
    ]
    # and on the project as it is: src/, research/ and tests/ import nothing that is not a direct pin of its file
    assert dependency_problems(PROJECT) == []
    # documented: a direct pin the landing does not declare has a row of the table in LANDING-EXPANSION.md (the row that adds
    # project 06 to it is U21's, with the other documents); SQLite is the standard library, and the table has its row too
    table = (PROJECT.parent / "LANDING-EXPANSION.md").read_text(encoding="utf-8").splitlines()
    names = [line.split("|")[1].strip().lower() for line in table if line.startswith("| ")]
    direct = all_pins(PROJECT)["requirements.txt"].direct | all_pins(PROJECT)["requirements-dev.txt"].direct
    undocumented = sorted(name for name in direct if name not in LANDING_DECLARED and not any(name in row for row in names))
    assert undocumented == [], f"direct pins outside the landing with no row in LANDING-EXPANSION.md: {undocumented}"


def test_a_development_only_direct_dependency_imported_by_src_is_reported_as_such(tmp_path):
    """pytest is a direct pin of requirements-dev.txt: runtime code that imports it is not wrongly told it is pinned as transitive."""
    probe = probe_project(tmp_path, {"src/promolift/uses_pytest.py": "import pytest\nimport numpy\n"})
    assert dependency_problems(probe) == [
        "pytest (pytest) is imported by src/promolift/uses_pytest.py but is a development-only dependency (a direct pin of "
        "requirements-dev.txt), which runtime code cannot import"
    ]


def test_the_scope_of_each_folder_and_the_names_of_the_unknown_modules(tmp_path, monkeypatch):
    """The tests may import any direct pin and are told the rest by name; research/ modules that import each other are local, not
    dependencies (the fallback of distribution_of for a module no installed distribution provides)."""
    probe = probe_project(tmp_path, {
        "tests/test_probe.py": "import pytest\nimport no_such_module_xyz\nimport colorama\nimport promolift\n",
        "research/s99_probe.py": "import numpy\nimport common\nimport pytest\n",
        "research/common.py": "import pandas\n",
    })
    assert distribution_of("no_such_module_xyz") == "no-such-module-xyz" and distribution_of("sklearn") == "scikit-learn"
    monkeypatch.setattr(sys.modules[__name__], "distribution_of", normalize)
    assert dependency_problems(probe) == [
        "pytest (pytest) is imported by research/s99_probe.py but is a development-only dependency (a direct pin of "
        "requirements-dev.txt), which runtime code cannot import",
        "colorama (colorama) is imported by tests/test_probe.py but is pinned only as a transitive dependency",
        "no_such_module_xyz (no-such-module-xyz) is imported by tests/test_probe.py but is not pinned as a direct requirement",
    ]


@pytest.mark.parametrize(("marker", "never"), [
    ('python_version < "3.8"', True), ("python_version < '3.8'", True), ('python_version < "3.11"', True), ('python_version < "3.12"', False),
    ('python_version <= "3.10"', True), ("python_version <= '3.10'", True), ('python_version <= "3.11"', False), ("python_version<='3.12'", False),
    ('extra == "test"', True), ('platform_system == "Windows"', False),
])
def test_a_marker_never_applies_only_to_extras_and_to_pythons_older_than_3_11(marker, never):
    """Single or double quotes and a strict or inclusive bound: ``<= "3.11"`` still applies to 3.11."""
    assert never_applies(marker) is never


# --- D33, RNF01: the pins ------------------------------------------------------------------------------------------------


def test_every_pin_is_exact_and_python_dateutil_is_below_3():
    pins = all_pins(PROJECT)
    runtime, dev = pins["requirements.txt"], pins["requirements-dev.txt"]
    assert runtime.problems + dev.problems == []
    assert runtime.includes == [] and dev.includes == ["requirements.txt"]
    assert not set(runtime.all) & set(dev.all), "the development file pins again what the file it includes already pins"
    # project 01 D44 and project 02 D55: version 4.x of python-dateutil conflicts with Airflow's own dependencies; six comes with 2.9
    assert int(runtime.all["python-dateutil"].split(".", 1)[0]) < 3
    assert runtime.all["python-dateutil"] == "2.9.0.post0" and runtime.all["six"] == "1.17.0"


def test_the_pins_are_project_05s_versions_without_what_only_research_imported():
    """D33: the same versions as project 05, with no direct SciPy (nothing here imports it; scikit-learn brings it as a transitive pin,
    D32) and matplotlib in requirements.txt because ``figures.py`` (U14) is runtime code, as in project 05 (D33's note of 2026-11-17)."""
    runtime = read_pins(PROJECT / "requirements.txt")
    assert runtime.direct == {"numpy": "2.4.6", "pandas": "2.3.3", "pyarrow": "26.0.1", "scikit-learn": "1.9.1", "matplotlib": "3.11.2"}
    assert runtime.transitive["scipy"] == "1.17.1" and "scipy" in required_names("scikit-learn")
    assert not {"statsmodels", "openpyxl", "shap", "numba", "llvmlite", "fastapi", "pydantic", "uvicorn", "httpx"} & set(runtime.all)
    assert runtime.transitive["cloudpickle"] == "3.1.2" and "cloudpickle" in required_names("joblib")
    dev = read_pins(PROJECT / "requirements-dev.txt")
    assert dev.direct == {"pytest": "9.2.0"}


def test_the_research_pins_are_the_runtime_pins_of_the_same_packages():
    """The research environment (docs/research.md) and the runtime one are the same versions: nothing new came in with the build."""
    research = read_pins(PROJECT / "requirements-research.txt").all
    runtime = read_pins(PROJECT / "requirements.txt").all
    assert research and {name: (version, runtime.get(name)) for name, version in research.items() if runtime.get(name) != version} == {}


def test_every_transitive_pin_is_required_by_another_pin():
    pins = all_pins(PROJECT)
    pinned = set().union(*(set(file.all) for file in pins.values()))
    required = set().union(*(required_names(name) for name in pinned))
    transitive = set().union(*(set(file.transitive) for file in pins.values()))
    orphans = sorted(transitive - required)
    assert orphans == [], f"pinned as transitive but required by no other pin: {orphans}"


def test_each_requirements_file_pins_everything_its_pins_require():
    """requirements.txt alone installs a complete runtime (the Airflow image installs only it); the development file adds what its own
    pins need on top of the file it includes."""
    pins = all_pins(PROJECT)
    runtime, dev = (set(pins[name].all) for name in REQUIREMENT_FILES)
    for pinned, available in ((runtime, runtime), (dev, runtime | dev)):
        missing = {name: sorted(required_names(name) - available) for name in pinned}
        assert {name: needs for name, needs in missing.items() if needs} == {}


def test_no_dependency_outside_the_declared_set_is_pinned():
    """D30 (no pytest-xdist), D32 (no statsmodels) and project 04's: no psutil, requests or lightgbm."""
    pinned = set().union(*(set(file.all) for file in all_pins(PROJECT).values()))
    assert not ({"statsmodels", "lightgbm", "xgboost", "pytest-xdist", "execnet", "psutil", "requests", "openpyxl", "shap", "numba"} & pinned)


def test_installed_versions_match_the_pins():
    pinned = set()
    wrong = {}
    for file in all_pins(PROJECT).values():
        pinned |= set(file.all.items())
    for name, version in sorted(pinned):
        try:
            installed = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            installed = None
        if installed != version:
            wrong[name] = (version, installed)
    assert not wrong, f"installed versions differ from the pins (pinned, installed): {wrong}"


def test_pip_check_is_judged_by_its_exit_code():
    # the judge, on commands whose words and exit code disagree
    assert pip_check_passed([sys.executable, "-c", "print('No broken requirements found.')"]) is True
    assert pip_check_passed([sys.executable, "-c", "print('No broken requirements found.'); raise SystemExit(1)"]) is False
    assert pip_check_passed([sys.executable, "-c", "print('pip words that changed in a later release')"]) is True
    # and the live environment: the exit code is the contract; the words pip prints are not
    assert pip_check_passed([sys.executable, "-m", "pip", "check", "--disable-pip-version-check"]) is True


# --- the project files ----------------------------------------------------------------------------------------------------


def test_pyproject_declares_the_package_the_pythons_and_the_marks():
    document = tomllib.loads((PROJECT / "pyproject.toml").read_text(encoding="utf-8"))
    assert document["project"]["name"] == "promolift"
    assert document["project"]["requires-python"] == ">=3.11,<3.14"
    options = document["tool"]["pytest"]["ini_options"]
    assert "-m 'not real_data and not docker'" in options["addopts"] and "--strict-markers" in options["addopts"]
    assert {mark.split(":", 1)[0] for mark in options["markers"]} == {"real_data", "docker", "slow"}
    assert options["pythonpath"] == ["src", "."]
    assert options["testpaths"] == ["tests"]


@pytest.mark.parametrize("entry", [
    "data/raw/", "data/interim/", "data/warehouse/", "data/models/", "data/quick/", "airflow/logs/", "airflow/config/", "airflow/plugins/",
    "airflow/.env", "reports/validation/history/", ".venv/", "__pycache__/", ".pytest_cache/",
])
def test_gitignore_keeps_generated_state_and_the_environment_out_of_git(entry):
    assert entry in (PROJECT / ".gitignore").read_text(encoding="utf-8").splitlines()


def test_the_seal_the_reports_the_research_and_the_published_outputs_are_not_ignored():
    """The seal, the reports, the Parquet of outputs/powerbi/, the site files, the dashboard and the research scripts with their outputs
    are versioned; only the generated state of the pipeline is not."""
    ignored = set((PROJECT / ".gitignore").read_text(encoding="utf-8").splitlines())
    assert not ({"reports/", "outputs/", "outputs/powerbi/", "outputs/site/", "reports/model_seal.json", "dashboard/", "docs/", "research/",
                 "research/plan/", "data/"} & ignored)


def test_the_docker_build_context_holds_only_requirements_txt():
    lines = [line for line in (PROJECT / ".dockerignore").read_text(encoding="utf-8").splitlines() if line and not line.startswith("#")]
    assert lines == ["*", "!requirements.txt"]


def test_the_package_imports_from_the_source_folder():
    import promolift

    assert Path(promolift.__file__).resolve().parent == PROJECT / "src" / "promolift"
    assert promolift.__version__ == "0.1.0"
