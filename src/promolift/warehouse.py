"""The SQLite warehouse: connection, SQL runner, schema, the load of a delivery and the controls (RF08, D22; plan, sections 5 and 7); adapted from project 05.

Rules of the runner, the same as in projects 01 to 05:

- autocommit connection (``isolation_level=None``); transactions are explicit ``BEGIN IMMEDIATE``;
- ``journal_mode=DELETE`` (WAL does not behave on Docker Desktop mounts), ``synchronous=FULL``, ``foreign_keys=ON``;
- never ``executescript()``: it commits the open transaction first. SQL files are split into statements with ``sqlite3.complete_statement`` and
  run one by one with named parameters, so a failure can roll the whole load back;
- the staging table is rebuilt inside the transaction (``DROP TABLE IF EXISTS`` and ``CREATE TABLE AS``), so SQLite rolls it back too. For a later instant under the
  same parameters it is extended instead (D46): the days that closed since are added and the recovered sums set since are copied, and ``stg_series_days_meta`` records
  the instant, the parameters and the rows it was built with; anything else (an earlier instant, another partition, a record that does not describe the table) is a full
  rebuild, and triggers remove the record when ``series_days`` or ``series`` change in a way the flow does not (``sql/staging/stg_series_days_meta.sql``). The result is the same rows in the same order as a full rebuild (``tests/integration/test_load.py``).

A load is all or nothing: the series-days of the delivery, its row in ``deliveries``, the series it brings, its hour profile, ``stg_series_days``
rebuilt for its instant and the controls of ``sql/checks/load/`` (and the one against the cube) are one transaction. A delivery that is empty (but
for the close), already loaded, repeats a series-day or fails a control leaves the warehouse byte for byte as it was. The transaction is rolled
back with ``ROLLBACK`` and the error that made it necessary is the one that reaches the caller (the lesson of project 05's
R4-store-validation-commit-on-error: a failure never commits).
"""

from __future__ import annotations

import functools
import json
import logging
import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd

from promolift.cube import store_delivery_cube
from promolift.days import EDGE_TOLERANCE, STATE_NAMES
from promolift.deliveries import DAYS_COLUMNS, DeliverySpec, delivery_sums
from promolift.schema import SERIES_COLUMNS, date_key

logger = logging.getLogger(__name__)

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"
CHECK_GROUPS = ("load", "model")
MART_GROUPS = ("powerbi",)
SAMPLE_LIMIT = 5
SAMPLE_SERIES_DAYS = 1000      # chk_sums_match_cube: the series-days of a delivery compared with its cube (every one when it has fewer)
SUM_TOLERANCE = 1e-6           # chk_sums_match_cube and chk_profile_matches_days
BUSY_TIMEOUT_MS = 30_000       # an overlapping writer waits this long for the write lock before failing (runbook R8)
CACHE_KIB = 65_536             # the page cache of a connection (negative ``cache_size`` is in KiB): the 2 MB default is smaller than what a control reads
CHUNK_ROWS = 100_000           # the rows of one executemany
STAGING = ("staging/stg_series_days.sql",)
STAGING_EXTEND = "staging/stg_series_days_extend.sql"
STAGING_META = "stg_series_days_meta"
STAGING_META_SQL = "staging/stg_series_days_meta.sql"
BLOCK_NAMES = ("train", "purge", "valid_v1", "valid_v2", "test")
SERIES_DAY_COLUMNS = ("series_key", "date_key", "delivery_id", "day_state", "band", "activity_flag", "discount", "holiday_flag", "raw_sum",
                      "instock_hours", "stockout_hours", "instock_sum", "recovered_sum", "fully_out")
PROFILE_COLUMNS = ("date_key", "management_group_id", "hour", "day_state", "series_days", "sales_sum", "stockout_count", "delivery_id")


@dataclass(frozen=True)
class CheckResult:
    check_id: str
    violations: int
    sample: list[tuple]


@dataclass(frozen=True)
class LoadResult:
    delivery_id: str
    as_of: datetime
    series_days: int           # series-days of the delivery now in series_days
    profile_rows: int          # rows of hour_profile that this delivery added
    staged: int                # rows of stg_series_days after the load: every series-day of a day that had closed at the delivery's instant
    checks: list[CheckResult]


class EmptyDeliveryError(RuntimeError):
    """The delivery has no series-days (and is not the close): nothing was written and the warehouse keeps what it had."""

    def __init__(self, run_key: str, delivery_id: str) -> None:
        super().__init__(f"La carga {run_key} se rechazó: la entrega {delivery_id} no tiene series-días y el almacén queda como estaba")


class DeliveryAlreadyLoadedError(RuntimeError):
    """The delivery is already in the warehouse: loading it again would duplicate its series-days."""

    def __init__(self, delivery_id: str) -> None:
        super().__init__(f"La entrega {delivery_id} ya está cargada en el almacén; no se carga de nuevo")


class CheckFailedError(RuntimeError):
    """A control returned rows: the transaction was rolled back."""

    def __init__(self, checks: list[CheckResult], step: str = "La carga") -> None:
        self.checks, self.step = checks, step
        failing = [c for c in checks if c.violations]
        detail = "; ".join(f"{c.check_id}: {c.violations} filas, por ejemplo {c.sample[:2]}" for c in failing)
        super().__init__(f"{step} se deshizo; controles con filas que los violan: {detail}")


class CubeStoreError(RuntimeError):
    """The delivery was loaded into SQLite but its hours could not be copied to the cube of the loaded deliveries (runbook R12): storing them again
    (``cube.store_delivery_cube``) finishes the job, and until then none of the delivery's days is visible through the cube."""

    def __init__(self, delivery_id: str, error: BaseException) -> None:
        super().__init__(f"La entrega {delivery_id} quedó cargada en el almacén pero su cubo no se copió ({type(error).__name__}: {error}); "
                         "volver a copiarlo termina la carga (docs/runbook.md, R12)")


class SchemaDriftError(RuntimeError):
    """A table of the warehouse does not have the columns its SQL definition declares (runbook R11)."""

    def __init__(self, table: str, source: str, missing: tuple[str, ...], unexpected: tuple[str, ...], retyped: tuple[str, ...]) -> None:
        self.table, self.missing, self.unexpected, self.retyped = table, missing, unexpected, retyped
        parts = [text for text, columns in ((f"faltan las columnas {list(missing)}", missing), (f"sobran las columnas {list(unexpected)}", unexpected),
                                            (f"tienen otro tipo las columnas {list(retyped)}", retyped)) if columns]
        super().__init__(f"La tabla {table} no coincide con su definición en sql/schema/{source}: {'; '.join(parts)}. "
                         "El almacén lo creó una versión anterior: se reconstruye desde cero (docs/runbook.md, R11).")


# --- connection and SQL files -------------------------------------------------------------------------------------------


def connect(path: Path) -> sqlite3.Connection:
    """Open (creating the folder and the file) the warehouse in autocommit mode with the project's pragmas."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None)
    conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(f"PRAGMA cache_size=-{CACHE_KIB}")   # memory only: nothing in the file or in a result depends on it
    return conn


def _has_sql(text: str) -> bool:
    """True if `text` has anything besides whitespace, semicolons and comments."""
    i, n = 0, len(text)
    while i < n:
        if text.startswith("--", i):
            end = text.find("\n", i)
            i = n if end == -1 else end + 1
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end == -1 else end + 2
        elif text[i].isspace() or text[i] == ";":
            i += 1
        else:
            return True
    return False


def split_statements(sql_text: str) -> list[str]:
    """Split a SQL file into statements, keeping semicolons inside strings, comments and triggers (a new list: the split is cached by text)."""
    return list(_split_statements(sql_text))


@functools.lru_cache(maxsize=256)
def _split_statements(sql_text: str) -> tuple[str, ...]:
    statements: list[str] = []
    start = 0
    for position, character in enumerate(sql_text):
        if character == ";" and sqlite3.complete_statement(sql_text[start : position + 1]):
            chunk = sql_text[start : position + 1]
            if _has_sql(chunk):
                statements.append(chunk.strip())
            start = position + 1
    if _has_sql(sql_text[start:]):   # a last statement without its semicolon
        statements.append(sql_text[start:].strip())
    return tuple(statements)


def run_sql_file(conn: sqlite3.Connection, path: Path, params: Mapping[str, object] | None = None) -> None:
    """Execute the statements of a SQL file one by one, binding the named parameters each uses."""
    for statement in split_statements(Path(path).read_text(encoding="utf-8")):
        conn.execute(statement, dict(params or {}))


def _stamp(value: datetime | pd.Timestamp) -> str:
    """An instant as the warehouse stores it: ``YYYY-MM-DD HH:MM:SS``."""
    return pd.Timestamp(value).strftime("%Y-%m-%d %H:%M:%S")


def sql_params(as_of: datetime, view: Any) -> dict[str, object]:
    """The named parameters the SQL files may use: the day of the instant the staging is built for, the edges of the blocks of the split as day keys, the
    thresholds of the day states and the edges of the bands, and the analysis hours."""
    d, c = view.days, view.calendar
    first_hour, last_hour = c.day_hours
    params: dict[str, object] = {
        "as_of_key": date_key(as_of.date()), "regular_min_discount": float(d.regular_min_discount), "anomalous_max_discount": float(d.anomalous_max_discount),
        "anomalous_min_discount": float(d.anomalous_min_discount), "band_edges": json.dumps([float(edge) for edge in d.bands[1:-1]]),
        "band_first_edge": float(d.bands[0]), "band_last_edge": float(d.bands[-1]),
        "edge_tolerance": EDGE_TOLERANCE, "first_hour": int(first_hour), "last_hour": int(last_hour), "analysis_hours": int(last_hour - first_hour + 1),
    }
    for name in BLOCK_NAMES:
        first, last = getattr(view.split, name)
        params[f"{name}_first_key"], params[f"{name}_last_key"] = date_key(first), date_key(last)
    return params


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)).fetchone() is not None


def _declared_tables(path: Path) -> dict[str, dict[str, str]]:
    """``{table: {column: declared type}}`` of a schema file, read by creating its tables in memory (cached by the file's size and time)."""
    stat = Path(path).stat()
    return _declared_tables_cached(str(path), stat.st_size, stat.st_mtime_ns)


@functools.lru_cache(maxsize=16)
def _declared_tables_cached(path: str, size: int, mtime_ns: int) -> dict[str, dict[str, str]]:
    del size, mtime_ns   # only part of the cache key
    scratch = sqlite3.connect(":memory:")
    try:
        for statement in split_statements(Path(path).read_text(encoding="utf-8")):
            scratch.execute(statement)
        names = [r[0] for r in scratch.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")]
        return {t: {r[1]: (r[2] or "").upper() for r in scratch.execute(f'PRAGMA table_info("{t}")')} for t in names}
    finally:
        scratch.close()


def _check_no_drift(conn: sqlite3.Connection, path: Path) -> None:
    for table, declared in _declared_tables(path).items():
        if not _table_exists(conn, table):
            continue
        actual = {r[1]: (r[2] or "").upper() for r in conn.execute(f'PRAGMA table_info("{table}")')}
        missing = tuple(c for c in declared if c not in actual)
        unexpected = tuple(c for c in actual if c not in declared)
        retyped = tuple(c for c in declared if c in actual and declared[c] != actual[c])
        if missing or unexpected or retyped:
            raise SchemaDriftError(table, Path(path).name, missing, unexpected, retyped)


def apply_schema(conn: sqlite3.Connection) -> None:
    """Create the tables of ``sql/schema`` that do not exist yet (idempotent; keeps the data). A table that exists with other columns than its
    file declares is not migrated: ``SchemaDriftError`` names it and its columns.

    Called in autocommit mode, the statements run in one transaction of their own, which is committed whatever happens (what an error leaves is what each statement
    before it did, as in autocommit), because a statement outside a transaction takes and gives back the file's lock by itself, which is most of the cost of a no-op
    ``CREATE ... IF NOT EXISTS`` when everything exists. Called inside the caller's transaction, it joins it."""
    own = not conn.in_transaction
    if own:
        conn.execute("BEGIN")
    try:
        for path in sorted((SQL_DIR / "schema").glob("*.sql")):
            _check_no_drift(conn, path)
            run_sql_file(conn, path)
    finally:
        if own and conn.in_transaction:
            conn.execute("COMMIT")


def rebuild_marts(conn: sqlite3.Connection, group: Literal["powerbi"], params: Mapping[str, object] | None = None) -> list[str]:
    """Rebuild the marts of a group (``sql/marts/<group>/mart_*.sql``, in file-name order) inside the caller's transaction: each file drops its table and creates it
    again from the tables it reads, so a rollback undoes it too. Returns the names of the files run."""
    if group not in MART_GROUPS:
        raise ValueError(f"grupo de marts desconocido: {group!r}; se esperaba uno de {', '.join(MART_GROUPS)}")
    if not conn.in_transaction:
        raise RuntimeError("los marts se reconstruyen dentro de una transacción abierta, para que una falla los deshaga")
    paths = sorted((SQL_DIR / "marts" / group).glob("mart_*.sql"))
    for path in paths:
        run_sql_file(conn, path, params)
    return [path.stem for path in paths]


# --- controls --------------------------------------------------------------------------------------------------------------


def run_checks(conn: sqlite3.Connection, group: Literal["load", "model"], params: Mapping[str, object] | None = None, *, only: Iterable[str] | None = None
               ) -> list[CheckResult]:
    """Run the controls of a group, in file-name order (or only those named in `only`); each file selects the rows that break its rule (none: it passes)."""
    if group not in CHECK_GROUPS:
        raise ValueError(f"grupo de controles desconocido: {group!r}; se esperaba uno de {', '.join(CHECK_GROUPS)}")
    bound = dict(params or {})
    paths = sorted((SQL_DIR / "checks" / group).glob("chk_*.sql"))
    if only is not None:
        wanted = list(only)
        unknown = [name for name in wanted if name not in {p.stem for p in paths}]
        if unknown:
            raise ValueError(f"no hay un control {', '.join(unknown)} en el grupo {group}")
        paths = [p for p in paths if p.stem in wanted]
    results = []
    for path in paths:
        statements = split_statements(path.read_text(encoding="utf-8"))
        if len(statements) != 1:
            raise ValueError(f"{path.name} debe tener exactamente un SELECT y tiene {len(statements)} sentencias")
        select = statements[0].rstrip().rstrip(";")
        violations = conn.execute(f"SELECT COUNT(*) FROM ({select})", bound).fetchone()[0]
        sample = conn.execute(f"SELECT * FROM ({select}) LIMIT {SAMPLE_LIMIT}", bound).fetchall() if violations else []
        results.append(CheckResult(path.stem, int(violations), sample))
    return results


def check_sums_match_cube(conn: sqlite3.Connection, spec: DeliverySpec, cube: tuple[np.ndarray, np.ndarray, np.ndarray], view: Any) -> CheckResult:
    """``chk_sums_match_cube``: a fixed sample of ``SAMPLE_SERIES_DAYS`` series-days of the delivery (every one when it has fewer; the same
    positions every time, spread over its days and series) as they are *stored* in ``series_days`` against the sums recomputed from the cube of the
    delivery with ``deliveries.delivery_sums``, to 1e-6. The rest is V14's, over every series-day, before the load."""
    rows = conn.execute("SELECT series_key, date_key, raw_sum, instock_hours, stockout_hours, instock_sum FROM series_days WHERE delivery_id = ? "
                        "ORDER BY date_key, series_key", (spec.delivery_id,)).fetchall()
    date_keys, sales, stock = cube
    if not rows:
        return CheckResult("chk_sums_match_cube", 0, [])
    positions = np.arange(len(rows)) if len(rows) <= SAMPLE_SERIES_DAYS else np.linspace(0, len(rows) - 1, SAMPLE_SERIES_DAYS).astype(int)
    sums = delivery_sums(sales, stock, tuple(view.calendar.day_hours))
    bad = []
    for position in positions:
        series, day, *stored = rows[int(position)]
        column = int(np.searchsorted(date_keys, day))
        if column >= len(date_keys) or date_keys[column] != day or not 0 <= series < sales.shape[0]:
            bad.append((series, day, "not_in_cube"))
            continue
        expected = (sums["raw_sum"][series, column], sums["instock_hours"][series, column], sums["stockout_hours"][series, column],
                    sums["instock_sum"][series, column])
        if any(abs(float(a) - float(b)) > SUM_TOLERANCE for a, b in zip(stored, expected)):
            bad.append((series, day, "sum_differs"))
    return CheckResult("chk_sums_match_cube", len(bad), bad[:SAMPLE_LIMIT])


def _fail_on(checks: list[CheckResult], what: str, step: str = "La carga") -> None:
    """``CheckFailedError`` if a control has rows. It is raised inside the caller's open transaction, so the log says which control failed;
    the caller logs «rolled back» only once its ROLLBACK has run."""
    failing = [c for c in checks if c.violations]
    for c in failing:
        logger.error("%s: control %s failed, violations=%d sample=%s", what, c.check_id, c.violations, c.sample)
    if failing:
        raise CheckFailedError(checks, step)


# --- load ------------------------------------------------------------------------------------------------------------------


def _require(frame: pd.DataFrame, columns: tuple[str, ...], what: str) -> None:
    missing = [name for name in columns if name not in frame.columns]
    if missing:
        raise ValueError(f"{what} no tiene las columnas del esquema canónico: faltan {', '.join(missing)}")


def _store_series(conn: sqlite3.Connection, series: pd.DataFrame) -> None:
    """Add the series the warehouse does not have yet; one it has must be the same (a changed hierarchy is refused)."""
    stored = pd.read_sql_query("SELECT * FROM series ORDER BY series_key", conn)
    if len(stored):
        merged = series[list(SERIES_COLUMNS)].merge(stored, on="series_key", how="inner", suffixes=("", "_stored"))
        for name in SERIES_COLUMNS[1:]:
            different = merged[merged[name] != merged[f"{name}_stored"]]
            if len(different):
                row = different.iloc[0]
                raise ValueError(f"la serie {int(row['series_key'])} (tienda {int(row['store_id'])}, producto {int(row['product_id'])}) cambió de jerarquía: "
                                 f"{name} era {int(row[f'{name}_stored'])} y ahora es {int(row[name])}")
        new = series[~series["series_key"].isin(stored["series_key"])]
    else:
        new = series
    if len(new):
        conn.executemany(f"INSERT INTO series ({', '.join(SERIES_COLUMNS)}) VALUES ({', '.join('?' for _ in SERIES_COLUMNS)})",
                         new[list(SERIES_COLUMNS)].astype(int).itertuples(index=False, name=None))


def _series_day_rows(days: pd.DataFrame, delivery_id: str, analysis_hours: int) -> Iterable[list[tuple]]:
    """The rows of ``series_days`` of a delivery, in chunks: the state as its name, no band as NULL, the recovery not yet done as NULL."""
    names = np.array(STATE_NAMES, dtype=object)
    for start in range(0, len(days), CHUNK_ROWS):
        part = days.iloc[start:start + CHUNK_ROWS]
        band = part["band"].to_numpy()
        yield list(zip(
            part["series_key"].tolist(), part["date_key"].tolist(), [delivery_id] * len(part), names[part["day_state"].to_numpy()].tolist(),
            [None if b < 0 else int(b) for b in band], part["activity_flag"].tolist(), part["discount"].tolist(), part["holiday_flag"].tolist(),
            part["raw_sum"].tolist(), part["instock_hours"].tolist(), part["stockout_hours"].tolist(), part["instock_sum"].tolist(), [None] * len(part),
            (part["instock_hours"].to_numpy() == 0).astype(int).tolist(), strict=True))


def _profile_rows(days: pd.DataFrame, cube: tuple[np.ndarray, np.ndarray, np.ndarray], series: pd.DataFrame, delivery_id: str) -> list[tuple]:
    """The hour profile of a delivery: for each day, management group, hour and day state with series-days, how many series-days, how much they sold
    in that hour and how many were out of stock in it. Every hour of the day is kept (the night too)."""
    date_keys, sales, stock = cube
    n_series, n_days = sales.shape[0], sales.shape[1]
    group_of = series.sort_values("series_key")["management_group_id"].to_numpy()[:n_series]
    groups, group_index = np.unique(group_of, return_inverse=True)
    state = np.full((n_series, n_days), -1, dtype=np.int64)
    columns = np.searchsorted(date_keys, days["date_key"].to_numpy())
    state[days["series_key"].to_numpy(), columns] = days["day_state"].to_numpy()
    n_groups, n_states = len(groups), len(STATE_NAMES)
    key = ((np.arange(n_days)[None, :] * n_groups + group_index[:, None]) * n_states + np.where(state >= 0, state, 0)).reshape(-1)
    valid = (state >= 0).reshape(-1)
    size = n_days * n_groups * n_states
    counts = np.bincount(key[valid], minlength=size)
    present = np.flatnonzero(counts)
    rows: list[tuple] = []
    for hour in range(24):
        sold = np.bincount(key[valid], weights=sales[:, :, hour].reshape(-1)[valid].astype(np.float64), minlength=size)
        out = np.bincount(key[valid], weights=stock[:, :, hour].reshape(-1)[valid].astype(np.float64), minlength=size)
        for cell in present:
            day_index, rest = divmod(int(cell), n_groups * n_states)
            group_position, state_code = divmod(rest, n_states)
            rows.append((int(date_keys[day_index]), int(groups[group_position]), hour, STATE_NAMES[state_code], int(counts[cell]), float(sold[cell]),
                         int(round(out[cell])), delivery_id))
    return rows


def _staging_record(conn: sqlite3.Connection) -> tuple[int, str, int] | None:
    """``(as_of_key, parameters, rows)`` the staging was last built with, or None without a record (a warehouse from before D46, or one rebuilt by hand)."""
    if not (_table_exists(conn, STAGING_META) and _table_exists(conn, "stg_series_days")):
        return None
    rows = conn.execute(f"SELECT as_of_key, params, staged_rows FROM {STAGING_META}").fetchall()
    return rows[0] if len(rows) == 1 else None


def _rebuild(conn: sqlite3.Connection, as_of: datetime, view: Any) -> None:
    """Bring ``stg_series_days`` to the instant `as_of`: extended from the instant it holds when that is possible (D46), rebuilt whole otherwise."""
    params = sql_params(as_of, view)
    key, rest = int(params["as_of_key"]), json.dumps({k: v for k, v in params.items() if k != "as_of_key"}, sort_keys=True)
    record = _staging_record(conn)
    extend = (record is not None and record[1] == rest and record[0] <= key
              and conn.execute("SELECT COUNT(*) FROM stg_series_days").fetchone()[0] == record[2]
              and conn.execute("SELECT COUNT(*) FROM series_days WHERE date_key < ?", (record[0],)).fetchone()[0] == record[2])
    if extend:
        run_sql_file(conn, SQL_DIR / STAGING_EXTEND, {**params, "from_key": record[0]})
    else:
        for name in STAGING:
            run_sql_file(conn, SQL_DIR / name, params)
    staged = int(conn.execute("SELECT COUNT(*) FROM stg_series_days").fetchone()[0])
    run_sql_file(conn, SQL_DIR / STAGING_META_SQL)
    conn.execute(f"DELETE FROM {STAGING_META}")
    conn.execute(f"INSERT INTO {STAGING_META} VALUES (?, ?, ?)", (key, rest, staged))


def stage_series_days(conn: sqlite3.Connection, as_of: datetime, view: Any) -> None:
    """Rebuild ``stg_series_days`` for the instant `as_of` inside the caller's open transaction (``rebuild_staging`` is the same with a transaction and the load controls of
    its own): what a calculation for an instant reads is what had closed at it."""
    if not conn.in_transaction:
        raise RuntimeError("la preparación de las series-días se reconstruye dentro de una transacción abierta, para que una falla la deshaga")
    _rebuild(conn, as_of, view)


def load_delivery(conn: sqlite3.Connection, days: pd.DataFrame, cube: tuple[np.ndarray, np.ndarray, np.ndarray], spec: DeliverySpec, run_key: str,
                  view: Any, *, sha256: str, series: pd.DataFrame, interim_dir: Path | None = None) -> LoadResult:
    """Add a validated delivery to the warehouse and rebuild ``stg_series_days`` for its instant, in one transaction (RF08).

    `days` and `cube` are the delivery as ``deliveries.read_delivery`` returns it; `series` is the canonical series table (the series the warehouse does not
    have yet are added, and one it has must be unchanged); `sha256` is the delivery's fingerprint in the manifest, recorded in ``deliveries``. A delivery
    with no series-days is refused, except the close, which loads empty and must be empty; one already loaded is refused too. If anything fails, a series-day
    that repeats or a control included, the transaction is rolled back and the warehouse keeps exactly what it had.

    With `interim_dir`, the hours of the delivery are copied to ``<interim_dir>/cube/`` (``cube.store_delivery_cube``) after the commit and never before it,
    so a rejected load leaves the cube byte for byte as it was; if that copy fails, ``CubeStoreError`` says the delivery is loaded without its cube.
    """
    _require(days, DAYS_COLUMNS, "la entrega")
    _require(series, SERIES_COLUMNS, "los datos de las series")
    if spec.kind == "close":
        if len(days):
            raise ValueError(f"el cierre no tiene series-días, y la entrega {spec.delivery_id} trae {len(days)}")
    elif days.empty:
        raise EmptyDeliveryError(run_key, spec.delivery_id)
    analysis_hours = view.calendar.day_hours[1] - view.calendar.day_hours[0] + 1
    conn.execute("BEGIN IMMEDIATE")
    try:
        apply_schema(conn)
        existing = conn.execute("SELECT status FROM deliveries WHERE delivery_id = ?", (spec.delivery_id,)).fetchone()
        if existing is not None and existing[0] == "loaded":
            raise DeliveryAlreadyLoadedError(spec.delivery_id)
        _store_series(conn, series)
        conn.execute(
            "INSERT INTO deliveries (delivery_id, kind, first_day, last_day, as_of, series_days, sha256, status, run_key) "
            "VALUES (:delivery_id, :kind, :first_day, :last_day, :as_of, :series_days, :sha256, 'loaded', :run_key) "
            "ON CONFLICT (delivery_id) DO UPDATE SET kind = excluded.kind, first_day = excluded.first_day, last_day = excluded.last_day, "
            "as_of = excluded.as_of, series_days = excluded.series_days, sha256 = excluded.sha256, status = 'loaded', run_key = excluded.run_key",
            {"delivery_id": spec.delivery_id, "kind": spec.kind, "first_day": None if spec.first_day is None else spec.first_day.isoformat(),
             "last_day": None if spec.last_day is None else spec.last_day.isoformat(), "as_of": _stamp(spec.as_of), "series_days": len(days),
             "sha256": sha256, "run_key": run_key},
        )
        placeholders = ", ".join("?" for _ in SERIES_DAY_COLUMNS)
        for chunk in _series_day_rows(days, spec.delivery_id, analysis_hours):
            conn.executemany(f"INSERT INTO series_days ({', '.join(SERIES_DAY_COLUMNS)}) VALUES ({placeholders})", chunk)
        profile = _profile_rows(days, cube, series, spec.delivery_id) if len(days) else []
        conn.executemany(f"INSERT INTO hour_profile ({', '.join(PROFILE_COLUMNS)}) VALUES ({', '.join('?' for _ in PROFILE_COLUMNS)})", profile)
        _rebuild(conn, spec.as_of, view)
        checks = [*run_checks(conn, "load", sql_params(spec.as_of, view)), check_sums_match_cube(conn, spec, cube, view)]
        _fail_on(checks, f"load {run_key}")
        loaded = int(conn.execute("SELECT COUNT(*) FROM series_days WHERE delivery_id = ?", (spec.delivery_id,)).fetchone()[0])
        if loaded != len(days):
            raise RuntimeError(f"La carga {run_key} se deshizo: se esperaban {len(days)} series-días de {spec.delivery_id} y hay {loaded}")
        staged = int(conn.execute("SELECT COUNT(*) FROM stg_series_days").fetchone()[0])
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        logger.warning("load %s rolled back: the warehouse keeps what it had", run_key)
        raise
    if interim_dir is not None:
        try:
            store_delivery_cube(interim_dir, spec.delivery_id, *cube)
        except BaseException as error:
            raise CubeStoreError(spec.delivery_id, error) from error
    logger.info("load %s: delivery=%s series_days=%d profile_rows=%d staged=%d controls=%d", run_key, spec.delivery_id, loaded, len(profile), staged, len(checks))
    return LoadResult(spec.delivery_id, spec.as_of, loaded, len(profile), staged, checks)


def set_recovered_sums(conn: sqlite3.Connection, date_keys: np.ndarray, sums: np.ndarray) -> int:
    """Set ``series_days.recovered_sum`` (``sums`` is series x days, over the analysis hours) for the days `date_keys`, only where it is still NULL: what was
    recovered is issued once and is never rewritten. In the caller's transaction; returns how many series-days it set."""
    changed = 0
    for column, key in enumerate(np.asarray(date_keys).tolist()):
        cursor = conn.executemany("UPDATE series_days SET recovered_sum = ? WHERE series_key = ? AND date_key = ? AND recovered_sum IS NULL",
                                  ((float(value), series, int(key)) for series, value in enumerate(np.asarray(sums)[:, column].tolist())))
        changed += cursor.rowcount
    return changed


def rebuild_staging(conn: sqlite3.Connection, as_of: datetime, view: Any) -> list[CheckResult]:
    """Rebuild ``stg_series_days`` for the instant `as_of` from ``series_days`` and ``series``, which are not touched: whatever the warehouse holds
    since, a calculation for an instant gets what had closed at it (RNF06 a). One transaction with the controls of the load; a control with rows undoes it."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        apply_schema(conn)
        _rebuild(conn, as_of, view)
        checks = run_checks(conn, "load", sql_params(as_of, view))
        _fail_on(checks, f"staging at {as_of}", "La preparación de las series-días (staging)")
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        logger.warning("staging at %s rolled back: the warehouse keeps what it had", as_of)
        raise
    return checks
