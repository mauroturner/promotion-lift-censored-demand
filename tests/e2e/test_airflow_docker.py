"""``airflow dags test`` in Docker, twice, in quick mode (U18, AC32, AC33; RNF02; plan, section 22; D24). Mark ``docker``: not in the default
selection, and skipped unless the Docker engine is running. Adapted from project 05's ``tests/e2e/test_airflow_docker.py``.

Run it with ``pytest -m docker``. It builds the image of ``airflow/`` (several minutes the first time), runs ``pip check`` in it, starts the
database and the initialization service of the compose file, runs the DAG ``promolift_daily`` on the synthetic source twice in a row and checks
that the first run is the launch and the second the first daily delivery, that what the launch fixed (the model artifact, its registry row
and the seal) did not change, and that the day of that delivery has its ``daily_cell`` rows. It writes only inside ``data/quick/`` (git-ignored), the
``airflow/logs``, ``airflow/config`` and ``airflow/plugins`` folders the containers use and the empty ``data/raw``, ``outputs``, ``reports`` and
``dashboard`` folders that the mounts create when they are missing, with throwaway secrets passed through the environment (the four of the compose
file, the password of the metadata database included).

What it creates it removes, also when it fails (A13 of project 04's evaluation): the stack with its database volume and its network
(``docker compose down --volumes``), the image ``promolift-airflow:3.4.0`` and the two external images when this test pulled or built them (an
image that was there before the test stays), and the folders above. It refuses to start when the compose project already has containers, volumes or
networks, so it never removes what another run left; the build cache of Docker is not an image, a volume or a network and is not touched.
"""

from __future__ import annotations

import base64
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from tests.fixtures.make_fixture import make_fixture

PROJECT = Path(__file__).resolve().parents[2]
AIRFLOW = PROJECT / "airflow"
QUICK = PROJECT / "data" / "quick"
CREATED = ("logs", "config", "plugins")                       # folders of airflow/ that the bind mounts create
MOUNTED = ("data/raw", "data", "outputs", "reports", "dashboard")   # folders of the project that the mounts create when they are missing (children first)
IMAGE = "promolift-airflow:3.4.0"                             # the compose file's image of the Airflow services (tests/unit/test_compose.py checks the name)
PROJECT_NAME = "promolift-airflow"                            # the compose file's ``name``: the label of everything the stack creates
EXTERNAL = (                                                   # the two images the build and the stack pull, by version and digest (projects 04's and 05's, D24)
    "apache/airflow:3.4.0@sha256:a8d9d19c563c768b2bc605ef26440f28a9164ea886064e99c599b057432ff572",
    "postgres:16.9@sha256:ddfe3e8713e3ee5b8f286082cb12512488dfbf3f5a1ecb0b74a42e6055af0a5f",
)
QUICK_CONFIG = "/opt/promolift/config/pipeline.quick.toml"
LAUNCH_ID, FIRST_DELIVERY_ID, FIRST_DAY_KEY = "L2024-06-25", "D2024-06-26", 20240626    # the plan of the quick configuration: the launch and the first daily delivery
BUILD_TIMEOUT_S = 1800
STEP_TIMEOUT_S = 900
TEARDOWN_TIMEOUT_S = 300

pytestmark = pytest.mark.docker

CURRENT: dict[str, str] = {}   # the secrets of the running test, the same for every docker call of it


def throwaway_secrets() -> dict[str, str]:
    """The four secrets of the compose file, new for each test: it has no default for any (AC33)."""
    return {
        "PROMOLIFT_DB_PASSWORD": secrets.token_hex(24),
        "PROMOLIFT_FERNET_KEY": base64.urlsafe_b64encode(os.urandom(32)).decode(),
        "PROMOLIFT_JWT_SECRET": secrets.token_urlsafe(48),
        "PROMOLIFT_ADMIN_PASSWORD": secrets.token_urlsafe(16),
    }


def docker(*args: str, timeout: int = STEP_TIMEOUT_S, check: bool = True, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    environment = {**os.environ, **(CURRENT if env is None else env), "ENV_FILE_PATH": str(AIRFLOW / ".env.example"), "PROMOLIFT_CONFIG": QUICK_CONFIG}
    try:
        return subprocess.run(["docker", *args], cwd=AIRFLOW, env=environment, capture_output=True, text=True, timeout=timeout, check=check, encoding="utf-8")
    except subprocess.TimeoutExpired as error:
        pytest.fail(f"docker {' '.join(args)} did not end in {timeout} s:\n" + str(error.stdout or "")[-1500:] + str(error.stderr or "")[-1500:])


def rows(query: str, params: tuple = ()) -> list[tuple]:
    conn = sqlite3.connect(f"{(QUICK / 'promolift.sqlite').as_uri()}?mode=ro", uri=True)
    try:
        return conn.execute(query, params).fetchall()
    finally:
        conn.close()


def image_exists(reference: str) -> bool:
    return docker("image", "inspect", reference, check=False).returncode == 0


def leftovers() -> dict[str, list[str]]:
    """What the compose project owns on this machine, by its label: nothing before the test and nothing after its teardown."""
    label = f"label=com.docker.compose.project={PROJECT_NAME}"
    kinds = {"containers": ("ps", "-a", "-q"), "volumes": ("volume", "ls", "-q"), "networks": ("network", "ls", "-q")}
    return {kind: docker(*command, "--filter", label, check=False).stdout.split() for kind, command in kinds.items()}


def teardown(existing: set[str], existing_mounts: set[str], *, image_existed: bool, external_existed: tuple[str, ...] = ()) -> list[str]:
    """Remove the stack with its volume and network, the image this test built (`image_existed` False), the external images it pulled (those not in
    `external_existed`), the folders it created; return what could not be done. Each step is tried even if another failed."""
    problems: list[str] = []

    def attempt(what: str, *args: str) -> None:
        try:
            done = docker(*args, check=False, timeout=TEARDOWN_TIMEOUT_S)
            if done.returncode != 0:
                problems.append(f"{what} returned {done.returncode}:\n" + (done.stdout + done.stderr)[-2000:])
        except (Exception, pytest.fail.Exception) as error:
            problems.append(f"{what} did not finish: {error}")

    attempt("docker compose down --volumes", "compose", "down", "--volumes")
    if not image_existed:
        attempt(f"docker image rm {IMAGE}", "image", "rm", IMAGE)   # before the bases: it is built on one of them
    for reference in EXTERNAL:
        if reference not in external_existed:
            attempt(f"docker image rm {reference}", "image", "rm", reference)
    for folder in [QUICK] + [AIRFLOW / name for name in CREATED if name not in existing]:
        shutil.rmtree(folder, ignore_errors=True)
        if folder.exists():
            problems.append(f"{folder} could not be removed")
    for name in MOUNTED:
        folder = PROJECT / name
        if name not in existing_mounts and folder.exists():
            try:
                folder.rmdir()
            except OSError:
                problems.append(f"{folder} was created by the mounts and is not empty: {sorted(p.name for p in folder.iterdir())[:5]}")
    return problems


def dags_test() -> subprocess.CompletedProcess:
    return docker("compose", "--profile", "debug", "run", "--rm", "airflow-cli", "airflow", "dags", "test", "promolift_daily", check=False)


def folder_bytes(folder: Path) -> dict[str, bytes]:
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file()}


@pytest.fixture(autouse=True)
def secrets_of_this_test():
    CURRENT.clear()
    CURRENT.update(throwaway_secrets())
    yield
    CURRENT.clear()


@pytest.fixture()
def engine():
    if shutil.which("docker") is None or subprocess.run(["docker", "info"], capture_output=True).returncode != 0:
        pytest.skip("the Docker engine is not running")


def test_the_compose_file_needs_each_secret_and_puts_the_database_password_in_the_connection_string(engine) -> None:
    """Without one secret (or with it empty) the file does not render and names it; with all four, the connection string and the PostgreSQL
    service carry the database password. Nothing is built or started."""
    given = dict(CURRENT)
    rendered = docker("compose", "config", env=given, check=False)
    assert rendered.returncode == 0, rendered.stderr[-2000:]
    assert f"postgresql+psycopg://airflow:{given['PROMOLIFT_DB_PASSWORD']}@postgres/airflow" in rendered.stdout
    assert f"POSTGRES_PASSWORD: {given['PROMOLIFT_DB_PASSWORD']}" in rendered.stdout
    assert re.search(r"target: /opt/promolift/data/raw\s+read_only: true", rendered.stdout), "the two Parquet files are mounted read-only"
    for name in given:
        missing = docker("compose", "config", env={k: v for k, v in given.items() if k != name}, check=False)
        assert missing.returncode != 0 and name in missing.stderr, (name, missing.stderr[-800:])
        blank = docker("compose", "config", env={**given, name: ""}, check=False)
        assert blank.returncode != 0 and name in blank.stderr, (name, "empty", blank.stderr[-800:])


def test_dags_test_twice_in_quick_mode_and_leaves_nothing_behind(engine) -> None:
    """AC32: the image passes ``pip check`` (judged by its exit code, not by a text of its output); ``airflow dags test promolift_daily`` runs the launch and then the
    first daily delivery with the model of the launch unchanged, and the day of that delivery has its ``daily_cell`` rows. The teardown (A13) leaves no container, volume or network of
    the project and no image this test created."""
    assert not QUICK.exists(), "data/quick is left over from another run (run `docker compose down --volumes` in airflow/ and delete it)"
    assert leftovers() == {"containers": [], "volumes": [], "networks": []}, "the compose project already exists: this test would remove what it did not create"
    existing = {name for name in CREATED if (AIRFLOW / name).exists()}
    existing_mounts = {name for name in MOUNTED if (PROJECT / name).exists()}
    image_existed = image_exists(IMAGE)
    external_existed = tuple(reference for reference in EXTERNAL if image_exists(reference))
    try:
        QUICK.mkdir(parents=True)
        make_fixture(QUICK, series=20, seed=0)
        for step in (("compose", "build"), ("compose", "up", "airflow-init")):
            done = docker(*step, check=False, timeout=BUILD_TIMEOUT_S if step[1] == "build" else STEP_TIMEOUT_S)
            assert done.returncode == 0, f"docker {' '.join(step)} failed:\n" + (done.stdout + done.stderr)[-3000:]
        check = "pip check && python -c 'import pandas, sklearn, pyarrow, matplotlib, promolift.pipeline'"
        consistent = docker("compose", "--profile", "debug", "run", "--rm", "airflow-cli", "bash", "-c", check, check=False)
        assert consistent.returncode == 0, (consistent.stdout + consistent.stderr)[-2000:]

        first = dags_test()
        assert first.returncode == 0, first.stdout[-3000:] + first.stderr[-3000:]
        registry = "SELECT model_version, trained_as_of, artifact_name, artifact_sha256, config_sha256 FROM model_registry"
        seal_path = QUICK / "reports" / "model_seal.json"
        launch_model, launch_seal, launch_artifact = rows(registry), seal_path.read_bytes(), folder_bytes(QUICK / "models")
        assert [r[0] for r in rows("SELECT delivery_id FROM pipeline_runs ORDER BY as_of")] == [LAUNCH_ID]
        assert len(launch_model) == 1 and launch_seal and launch_artifact

        second = dags_test()
        assert second.returncode == 0, second.stdout[-3000:] + second.stderr[-3000:]
        assert rows("SELECT delivery_id, status FROM pipeline_runs ORDER BY as_of") == [(LAUNCH_ID, "ok"), (FIRST_DELIVERY_ID, "ok")]
        assert rows("SELECT delivery_id, status FROM deliveries WHERE status != 'published' ORDER BY as_of") == [(LAUNCH_ID, "loaded"), (FIRST_DELIVERY_ID, "loaded")]
        assert rows(registry) == launch_model and seal_path.read_bytes() == launch_seal, "the model and its seal are the launch's"
        assert folder_bytes(QUICK / "models") == launch_artifact
        [(issued,)] = rows("SELECT rows_issued FROM pipeline_runs WHERE delivery_id = ?", (FIRST_DELIVERY_ID,))
        [(cells,)] = rows("SELECT COUNT(*) FROM daily_cell WHERE date_key = ?", (FIRST_DAY_KEY,))
        assert issued > 0 and cells > 0, "the day of the first delivery has its rows, issued with the model of the launch"
        assert (QUICK / "outputs" / "site" / "summary.json").is_file() and (QUICK / "dashboard" / "powerbi-design.html").is_file()
    finally:
        problems = teardown(existing, existing_mounts, image_existed=image_existed, external_existed=external_existed)
        left = leftovers()
        if any(left.values()):
            problems.append(f"the compose project still owns {left}")
        if not image_existed and image_exists(IMAGE):
            problems.append(f"{IMAGE} is still there")
        if problems:
            sys.stderr.write("TEARDOWN FAILED:\n" + "\n".join(problems) + "\n")
    assert not problems, "the teardown failed, so the next run will find leftovers:\n" + "\n".join(problems)
