"""DAG ``promolift_daily``: the eleven tasks of ``promolift.pipeline.TASKS``, wired in their order (RF23, AC32; plan, section 22; D24).
Adapted from project 05's ``flotsilica_daily.py``.

The DAG only wires: each task calls ``promolift.pipeline.run_task(task_id, run_id)``, the same function the command line runs, so Airflow and
``python -m promolift run`` do the same work in the same order. The task whose ``TaskSpec`` has ``short_circuit=True``, ``deliver``, is an
``@task.short_circuit``: with no delivery left to load the pipeline records the run as ``no_delivery`` in ``pipeline_runs`` and in its state
file, the task returns False and Airflow skips the rest. It runs every day at 01:00 UTC (a day with no delivery pending ends as
``no_delivery``), with one active run and one active task at a time, because the warehouse is a SQLite
file with a single writer (``airflow dags test`` in the debug service of the compose file runs outside that guard: the compose file says how to
run it). Each task also holds the pipeline's writer lock of the data folder while it runs, and a task that finds it held by another process is
refused (``RunLockedError``, a ``RunRefusedError``).

A rejection (``ValidationError``), a source that breaks a rule (``SourceError``), a leak (``LeakageError``) and a refusal (``RunRefusedError``)
fail the same way every time on the same data, so they fail the task at once with ``AirflowFailException``, with no retry; any other error
(the network, the disk) keeps the retries of its ``TaskSpec``.
"""

from __future__ import annotations

import logging
import math
from datetime import UTC, datetime, timedelta

from airflow.sdk import DAG, task
from airflow.sdk.exceptions import AirflowFailException

from promolift.cube import LeakageError
from promolift.lock import RunRefusedError
from promolift.pipeline import TASKS, TaskSpec, run_task
from promolift.schema import SourceError
from promolift.validate import ValidationError

logger = logging.getLogger(__name__)

SUMMARY_TEXT_CHARS = 200   # XCom gets a short text; the whole result stays in the run's state file


def run_without_retrying_a_rejection(task_id: str, run_id: str | None) -> dict:
    """``run_task``, except that a rejection, a source that breaks a rule, a leak or a refusal fails the task at once."""
    try:
        return run_task(task_id, run_id)
    except (ValidationError, SourceError, LeakageError, RunRefusedError) as error:
        raise AirflowFailException(str(error)) from error


def summary(task_id: str, result: dict) -> dict:
    """What a task tells Airflow (its UI shows it): the task and the flat part of its result, small and JSON. Booleans, numbers, short text
    and ``None`` are kept (a long text is cut at ``SUMMARY_TEXT_CHARS``, a number that is not finite becomes ``None`` with a warning that names the task and the key); lists and
    nested records stay in the run's state file."""
    out: dict = {"task": task_id}
    for key, value in result.items():
        if isinstance(value, float) and not math.isfinite(value):
            logger.warning("task %s: %s is %r and is published as None (XCom is JSON)", task_id, key, value)
            out[key] = None
        elif isinstance(value, str):
            out[key] = value[:SUMMARY_TEXT_CHARS]
        elif value is None or isinstance(value, (bool, int, float)):
            out[key] = value
    return out


def build_task(spec: TaskSpec):
    """One Airflow task for a ``TaskSpec`` (a function of its own, so the loop variable is never captured)."""
    options = {
        "task_id": spec.task_id,
        "retries": spec.retries,
        "retry_delay": timedelta(minutes=spec.retry_delay_min),
        "execution_timeout": timedelta(minutes=spec.timeout_min),
    }
    if spec.short_circuit:

        @task.short_circuit(**options)
        def step(run_id=None) -> bool:
            return bool(run_without_retrying_a_rejection(spec.task_id, run_id)["delivered"])

    else:

        @task(**options)
        def step(run_id=None) -> dict:
            return summary(spec.task_id, run_without_retrying_a_rejection(spec.task_id, run_id))

    return step()


with DAG(
    dag_id="promolift_daily",
    schedule="0 1 * * *",  # every day at 01:00 UTC
    start_date=datetime(2026, 11, 1, tzinfo=UTC),
    catchup=False,
    max_active_runs=1,
    max_active_tasks=1,
    tags=["promolift"],
    doc_md=__doc__,
) as dag:
    previous = None
    for spec in TASKS:
        current = build_task(spec)
        if previous is not None:
            previous >> current
        previous = current
