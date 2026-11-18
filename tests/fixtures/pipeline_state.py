"""The flow of the small fixture, task by task, for the tests of the run state, the close and the refusals (U16): the quick configuration pointed at a copy of the 60-series
Parquet pair, every folder under one root, and the states the session builds once (a launched one and a replayed one) that each test copies.

The fixture has 90 days of training and the 7 days of the test, so the plan is the real one: the launch ``L2024-06-25``, seven daily deliveries and the close. A copy of a state
is a plain ``copytree``: nothing the flow writes holds a path of this machine, so a copy at another root is the same state, read through its own configuration."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import shutil
import sqlite3
import types
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

LAUNCH_ID, DAILY_ID, CLOSE_ID = "L2024-06-25", "D2024-06-26", "C2024-07-03"
LAYOUT = {
    "raw_dir": "raw", "interim_dir": "interim", "warehouse": "promolift.sqlite", "models_dir": "models", "outputs_dir": "outputs/powerbi", "site_dir": "outputs/site",
    "reports_dir": "reports", "seal": "reports/model_seal.json", "dashboard_html": "dashboard/powerbi-design.html", "readme": "README.md", "figures_dir": "figures",
}


def pipeline_config(root: Path, quick_cfg: Any, source_dir: Path | None = None) -> Any:
    """The quick configuration with every folder under `root`; the Parquet pair of `source_dir` is copied to ``root/source`` and accepted with its real sizes and hashes."""
    from tests.fixtures.make_fixture import fixture_config

    root = Path(root)
    built = quick_cfg
    if source_dir is not None:
        target = root / "source"
        target.mkdir(parents=True, exist_ok=True)
        for name in ("train.parquet", "eval.parquet"):
            shutil.copy2(Path(source_dir) / name, target / name)
        built = fixture_config(quick_cfg, target)
    return dataclasses.replace(built, paths=dataclasses.replace(built.paths, **{name: root / relative for name, relative in LAYOUT.items()}), project_root=root)


def state_of(root: Path, quick_cfg: Any, source_dir: Path | None = None) -> types.SimpleNamespace:
    return types.SimpleNamespace(root=Path(root), cfg=pipeline_config(root, quick_cfg, source_dir))


def copy_state(state: types.SimpleNamespace, target: Path, quick_cfg: Any) -> types.SimpleNamespace:
    """A copy of a state at `target` with its own configuration, for a test that writes. The source files are copied with it (``root/source``)."""
    shutil.copytree(state.root, target)
    return types.SimpleNamespace(root=Path(target), cfg=dataclasses.replace(
        state.cfg, source=dataclasses.replace(state.cfg.source, train_path=Path(target) / "source" / "train.parquet", eval_path=Path(target) / "source" / "eval.parquet"),
        paths=dataclasses.replace(state.cfg.paths, **{name: Path(target) / relative for name, relative in LAYOUT.items()}), project_root=Path(target)))


def tree_digest(root: Path) -> dict[str, str]:
    """The SHA-256 of every file under `root`, by its path relative to it: two equal digests are the same bytes everywhere."""
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(Path(root).rglob("*")) if path.is_file()}


def published_digest(cfg: Any) -> dict[str, str]:
    """What AC07 compares, by its path under the root: the SQLite file, the star model (every Parquet and its manifest), the HTML, every JSON of the site and the seal."""
    paths = [Path(cfg.paths.warehouse), Path(cfg.paths.dashboard_html), Path(cfg.paths.seal), *sorted(Path(cfg.paths.outputs_dir).glob("*")),
             *sorted(Path(cfg.paths.site_dir).glob("*.json"))]
    return {path.relative_to(cfg.project_root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def tamper_delivery(cfg: Any, delivery_id: str) -> None:
    """Drop the last series-day from the days file of a published delivery: its rows and its SHA-256 are no longer the manifest's (V13)."""
    path = Path(cfg.paths.raw_dir) / "deliveries" / f"{delivery_id}.days.parquet"
    table = pq.read_table(path)
    pq.write_table(table.slice(0, table.num_rows - 1).replace_schema_metadata(table.schema.metadata), path)


def query(cfg: Any, sql: str, params: tuple = ()) -> list[tuple]:
    """Rows of a read-only query on the warehouse of a state."""
    conn = sqlite3.connect(f"{Path(cfg.paths.warehouse).resolve().as_uri()}?mode=ro", uri=True)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def runs_of(cfg: Any) -> dict[str, str]:
    """``{run_key: status}`` of the runs of a state, in the order they started."""
    return dict(query(cfg, "SELECT run_key, status FROM pipeline_runs ORDER BY started_at, run_key"))


RUN_KEYS = ("run_key", "launch_run_key", "test_run_key")


def _without_run(value: Any) -> Any:
    """A JSON document without the keys that name the run that wrote it (and the artifact's bytes, which are not a value)."""
    if isinstance(value, dict):
        return {k: _without_run(v) for k, v in value.items() if k not in (*RUN_KEYS, "artifact_sha256", "r3_sha256")}
    if isinstance(value, list):
        return [_without_run(v) for v in value]
    return value


def content_of(cfg: Any) -> dict[str, Any]:
    """What a flow published, without the columns of the run (AC35): the rows of every Parquet of the star model but the run table (each without its ``run_key`` column, in a
    fixed order), every JSON of the site but its manifest, the summary and the seal."""
    out: dict[str, Any] = {}
    for path in sorted(Path(cfg.paths.outputs_dir).glob("*.parquet")):
        if path.stem == "dim_pipeline_run":
            continue
        rows = [{k: v for k, v in row.items() if k != "run_key"} for row in pq.read_table(path).to_pylist()]
        out[path.name] = sorted(rows, key=lambda row: json.dumps(row, sort_keys=True, default=str))
    for path in sorted(Path(cfg.paths.site_dir).glob("*.json")):
        if path.name != "manifest.json":
            out[f"site/{path.name}"] = _without_run(json.loads(path.read_text(encoding="utf-8")))
    for path in (Path(cfg.paths.reports_dir) / "evaluation_summary.json", Path(cfg.paths.seal)):
        out[path.name] = _without_run(json.loads(path.read_text(encoding="utf-8")))
    return out
