"""The star model for Power BI: the marts in SQLite and one Parquet file per table (RF20, AC24; D35; plan, section 19). Adapted from project 05's ``export.py``.

``build_powerbi_marts`` loads the reference tables that come from the code, the registry, the seal and the cube (``ref_*``: the versions, methods, blocks, weekdays, hours and
bands with their labels in Spanish, the state of the seal of the launch and the example series-day), rebuilds the tables of ``sql/marts/powerbi`` (``star_<name>``) and runs the
controls of ``sql/checks/model``, all in one transaction: a control with rows undoes it. Everything is **as of the run's instant**: a day that had not closed is not in the marts,
and nothing of the test week is while the week has not closed (D05, RNF06 a).

``export_star_schema`` writes every table of the semantic model with its Arrow schema and the run, the instant, the source and the attribution as file metadata, to
``outputs/powerbi``. A file over ``MAX_PARQUET_BYTES`` is an error before anything is written; each file is replaced atomically. The folder's ``manifest.json`` is removed before its
first file is written and written again after its last one, with the run and each file's name, bytes and SHA-256 (RNF05): ``verify_star_schema`` checks a folder against it,
so a set left half written by a failure has no manifest and is refused.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from promolift import texts
from promolift.cube import ATTRIBUTION, open_loaded_cube, open_recovered
from promolift.dashboard.semantic_model import SemanticModel, Table, arrow_schema, validate_model
from promolift.deliveries import delivery_plan
from promolift.files import write_atomic
from promolift.forecast import METHODS as FORECAST_METHODS
from promolift.launch import FIT_BLOCKS_VALID, launch_keys
from promolift.registry import MODEL_VERSION, RunMeta, read_registry, read_seal
from promolift.warehouse import apply_schema, rebuild_marts, run_checks, sql_params, stage_series_days, _fail_on

logger = logging.getLogger(__name__)

MAX_PARQUET_BYTES = 25 * 1024 * 1024        # a versioned file stays under GitHub's limits (RNF10)
STAR_PREFIX = "star_"
METADATA_KEYS = ("promolift.run_key", "promolift.as_of", "promolift.train_sha256", "promolift.eval_sha256", "promolift.attribution")
STAR_MANIFEST = "manifest.json"
MANIFEST_VERSION = 1
STAMP = "%Y-%m-%d %H:%M:%S"
EXAMPLE_CUT_RANGE = (12, 18)             # the first hour without stock of the example series-day, both included (plan, section 21)
EXAMPLE_MIN_SALE_HOURS = 4               # and the hours with sale it had before the stock ran out, at least


def metadata(run: RunMeta, view: Any) -> dict[str, str]:
    """What every Parquet file says about the run that wrote it (RNF07, RNF09)."""
    return dict(zip(METADATA_KEYS, (run.run_key, run.as_of.strftime(STAMP), view.train_sha256_seen, view.eval_sha256_seen, ATTRIBUTION), strict=True))


def example_day(cube: Any, recovered: np.ndarray, keys: np.ndarray, view: Any) -> tuple[int, int, np.ndarray] | None:
    """The example series-day of the plan's fixed rule (section 21): among the series-days of the launch period whose first hour without stock is between 12 and 18 and that
    sold in at least 4 hours before it, the one with the median recovered mass of the analysis hours (ties by series key, then date). Returns ``(series_key, date_key, rows)``
    with the 16 rows ``(hour, observed, recovered, in_stock)``, or None if no series-day qualifies."""
    first, last = view.calendar.day_hours
    n_hours = last - first + 1
    mass, series, days = [], [], []
    for position, key in enumerate(keys.tolist()):
        sales = np.asarray(cube.sales(key))[:, first:last + 1]
        out = np.asarray(cube.stock(key))[:, first:last + 1] == 1
        cut = out.argmax(axis=1)
        sold_before = ((sales > 0) & (np.arange(n_hours)[None, :] < cut[:, None])).sum(axis=1)
        picked = np.flatnonzero(out.any(axis=1) & (cut + first >= EXAMPLE_CUT_RANGE[0]) & (cut + first <= EXAMPLE_CUT_RANGE[1]) & (sold_before >= EXAMPLE_MIN_SALE_HOURS))
        if len(picked):
            mass.append(np.asarray(recovered[picked, position, first:last + 1], dtype=np.float64).sum(axis=1))
            series.append(picked)
            days.append(np.full(len(picked), key))
    if not series:
        return None
    mass, series, days = np.concatenate(mass), np.concatenate(series), np.concatenate(days)
    order = np.lexsort((days, series, mass))
    chosen = order[(len(order) - 1) // 2]
    s, key = int(series[chosen]), int(days[chosen])
    position = keys.tolist().index(key)
    observed = np.asarray(cube.sales(key))[s, first:last + 1]
    rows = np.column_stack([np.arange(first, last + 1), observed, np.asarray(recovered[s, position, first:last + 1], dtype=np.float64), 1 - np.asarray(cube.stock(key))[s, first:last + 1]])
    return s, key, rows


def _replace(conn: sqlite3.Connection, name: str, columns: str, rows: list[tuple]) -> None:
    conn.execute(f"DROP TABLE IF EXISTS {name}")
    conn.execute(f"CREATE TABLE {name} ({columns})")
    if rows:
        conn.executemany(f"INSERT INTO {name} VALUES ({', '.join('?' for _ in rows[0])})", rows)


def _launch_seal_state(conn: sqlite3.Connection, seal_path: Path) -> str:
    """``sealed`` if the registered model was fitted with the configuration of the seal, ``post_seal`` if with another one."""
    registered = read_registry(conn, MODEL_VERSION)
    if registered is None:
        raise RuntimeError(f"no hay un modelo registrado con la versión {MODEL_VERSION}: el modelo estrella se exporta después del lanzamiento")
    seal = read_seal(seal_path)
    return "sealed" if seal is not None and registered["config_sha256"] == seal["launch"]["config_sha256"] else "post_seal"


def _load_references(conn: sqlite3.Connection, view: Any, interim_dir: Path, seal_path: Path) -> None:
    """The ``ref_*`` tables the marts read."""
    first, last = view.calendar.day_hours
    bands = tuple(float(b) for b in view.days.bands)
    measured = [r[0] for r in conn.execute(
        "SELECT method FROM recovery_checks UNION SELECT substr(unit_key, 1, instr(unit_key, ':') - 1) FROM eval_variants WHERE variant = 'mcar_mask' AND unit_key NOT LIKE 'mask:%' ORDER BY 1")]
    methods = [(m, texts.METHOD_KINDS_ES["recovery"], texts.method_label(m), i) for i, m in enumerate(measured, start=1)]
    methods += [(m, texts.METHOD_KINDS_ES["forecast"], texts.FORECAST_LABELS_ES[m], len(measured) + i) for i, m in enumerate(FORECAST_METHODS, start=1)]
    _replace(conn, "ref_version", "version_key TEXT PRIMARY KEY, label_es TEXT", list(texts.VERSIONS_ES.items()))
    _replace(conn, "ref_method", "method_key TEXT PRIMARY KEY, kind_es TEXT, label_es TEXT, sort_order INTEGER", methods)
    _replace(conn, "ref_block", "block TEXT PRIMARY KEY, block_es TEXT", list(texts.BLOCKS_ES.items()))
    _replace(conn, "ref_weekday", "weekday INTEGER PRIMARY KEY, weekday_es TEXT", list(enumerate(texts.WEEKDAYS_ES)))
    _replace(conn, "ref_hour", "hour INTEGER PRIMARY KEY, in_analysis INTEGER, label_es TEXT", [(h, int(first <= h <= last), f"{h:02d}:00") for h in range(24)])
    _replace(conn, "ref_band", "band_key INTEGER PRIMARY KEY, discount_low REAL, discount_high REAL, depth_label_es TEXT",
             [(k, bands[k], bands[k + 1], texts.band_label(bands, k)) for k in range(len(bands) - 1)])
    _replace(conn, "ref_seal", "launch_state TEXT", [(_launch_seal_state(conn, seal_path),)])
    chosen = None
    folder = Path(interim_dir)
    if (folder / "cube").is_dir():
        launch_id, keys = delivery_plan(view)[0].delivery_id, launch_keys(view)
        chosen = example_day(open_loaded_cube(folder), open_recovered(folder, launch_id), keys, view)
    rows = [] if chosen is None else [(int(h), float(o), float(r), int(i)) for h, o, r, i in chosen[2]]
    _replace(conn, "ref_example_day", "hour INTEGER PRIMARY KEY, observed REAL, recovered REAL, in_stock INTEGER", rows)


def build_powerbi_marts(conn: sqlite3.Connection, run: RunMeta, view: Any, *, seal_path: Path, interim_dir: Path) -> None:
    """Rebuild the staging, the reference tables and the star model as of ``run.as_of`` and run its controls in one transaction; a control with rows undoes it all
    (``CheckFailedError``) and the marts keep what they had."""
    apply_schema(conn)
    params = {**sql_params(run.as_of, view), "min_series": int(view.ranking.min_series), "fit_blocks_valid": FIT_BLOCKS_VALID}
    params["test_closed"] = int(params["as_of_key"] > params["test_last_key"])
    conn.execute("BEGIN IMMEDIATE")
    try:
        stage_series_days(conn, run.as_of, view)
        _load_references(conn, view, interim_dir, seal_path)
        rebuild_marts(conn, "powerbi", params)
        _fail_on(run_checks(conn, "model", params), f"star model at {run.as_of}", "La exportación del modelo estrella")
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        logger.warning("star model at %s rolled back: the marts keep what they had", run.as_of)
        raise


_CONVERT = {
    "int8": int, "int16": int, "int32": int, "int64": int, "float64": float, "bool": bool, "string": str, "date": lambda v: date.fromisoformat(str(v)[:10]),
    "datetime": lambda v: datetime.fromisoformat(str(v)),
}


def _arrow_table(columns: list[tuple], table: Table) -> pa.Table:
    """The values of the columns (one tuple of values per column) as an Arrow table with the model's schema; a key with a missing value is an error."""
    arrays = []
    for column, values in zip(table.columns, columns, strict=True):
        if column.name in table.key and any(v is None for v in values):
            raise ValueError(f"{table.name}[{column.name}] tiene valores vacíos: una clave no puede")
        convert = _CONVERT[column.dtype]
        arrays.append(pa.array([None if v is None else convert(v) for v in values], type=arrow_schema(table).field(column.name).type))
    return pa.Table.from_arrays(arrays, schema=arrow_schema(table))


def _serialize(conn: sqlite3.Connection, table: Table, meta: dict[str, str]) -> bytes:
    names, order = (", ".join(f'"{name}"' for name in names) for names in (table.column_names, table.key))
    rows = conn.execute(f"SELECT {names} FROM {STAR_PREFIX}{table.name} ORDER BY {order}").fetchall()
    arrow = _arrow_table(list(zip(*rows, strict=True)) if rows else [()] * len(table.columns), table)
    arrow = arrow.replace_schema_metadata({**(arrow.schema.metadata or {}), **{k.encode(): v.encode("utf-8") for k, v in meta.items()}})
    sink = pa.BufferOutputStream()
    pq.write_table(arrow, sink, compression="snappy")
    return sink.getvalue().to_pybytes()


def _manifest_text(meta: dict[str, str], files: list[dict]) -> str:
    document = {"version": MANIFEST_VERSION, **{key.removeprefix("promolift."): value for key, value in meta.items()}, "files": files}
    return json.dumps(document, ensure_ascii=False, sort_keys=True, indent=1) + "\n"


def verify_star_schema(folder: Path) -> list[str]:
    """What does not match in `folder` against its ``manifest.json`` (empty when everything does): a missing or unreadable manifest, a listed file that is missing or whose bytes
    or SHA-256 differ, and a Parquet file the manifest does not list."""
    folder = Path(folder)
    try:
        manifest = json.loads((folder / STAR_MANIFEST).read_text(encoding="utf-8"))
        listed = {entry["name"]: entry for entry in manifest["files"]}
    except (OSError, ValueError, KeyError, TypeError) as error:
        return [f"{STAR_MANIFEST}: no hay un manifiesto legible ({type(error).__name__}); el conjunto no se usa"]
    problems = []
    for name, entry in listed.items():
        path = folder / name
        if not path.is_file():
            problems.append(f"{name}: falta el archivo que lista el manifiesto")
            continue
        data = path.read_bytes()
        if len(data) != entry.get("bytes") or hashlib.sha256(data).hexdigest() != entry.get("sha256"):
            problems.append(f"{name}: los bytes no son los del manifiesto")
    problems += [f"{path.name}: el manifiesto no lo lista" for path in sorted(folder.glob("*.parquet")) if path.name not in listed]
    return problems


def export_star_schema(conn: sqlite3.Connection, out_dir: Path, model: SemanticModel, run: RunMeta, view: Any, *, seal_path: Path, interim_dir: Path) -> list[Path]:
    """Rebuild the marts as of the run and write one Parquet file per table of `model` to `out_dir`, with the manifest last. Returns the paths in the model's order. The model
    is checked first and every file is serialized and measured before any is written."""
    problems = validate_model(model)
    if problems:
        raise ValueError(f"el modelo semántico es incoherente: {problems[0]}")
    meta = metadata(run, view)
    build_powerbi_marts(conn, run, view, seal_path=seal_path, interim_dir=interim_dir)
    payloads = {}
    for table in model.tables:
        data = _serialize(conn, table, meta)
        if len(data) > MAX_PARQUET_BYTES:
            raise ValueError(f"{table.name}.parquet pesa {len(data)} bytes, más de {MAX_PARQUET_BYTES}: no se escribe nada")
        payloads[table.name] = data
    out_dir = Path(out_dir)
    (out_dir / STAR_MANIFEST).unlink(missing_ok=True)         # a set being rewritten has no manifest until its last file is written
    paths = [write_atomic(out_dir / f"{table.name}.parquet", payloads[table.name]) for table in model.tables]
    files = [{"name": f"{t.name}.parquet", "bytes": len(payloads[t.name]), "sha256": hashlib.sha256(payloads[t.name]).hexdigest()} for t in model.tables]
    write_atomic(out_dir / STAR_MANIFEST, _manifest_text(meta, files))
    logger.info("star model at %s: %d files in %s", run.as_of, len(paths), out_dir)
    return paths
