"""Source ingestion (RF01-RF03): the pinned files, the strict reader, the canonical tables and tensors.

The two Parquet files are untrusted data (D02, D05). The pipeline never downloads them (``research/s00_download.py`` does, runbook R1), reads
them with pyarrow only, never deserializes an object from them and never reads a column it does not use.

* ``check_source`` (V01, and the byte cap of V03) compares the size and the SHA-256 of both files with the accepted ones (the size first: a file of
  another size is never hashed) or, in quick mode, with the hashes registered in ``source.lock.json`` next to the files.
* ``read_source`` (V02-V07, V26, V27) reads one file: the footer first (V02: the exact schema; V03: the rows and row groups under their caps), then
  the data in batches of ``BATCH_ROWS`` rows (V04: every hourly list has 24 values, none null or NaN, the sale finite in [0, ``max_hourly_sale``], the
  status 0 or 1, and the daily fields it keeps non-null and finite, the flags 0 or 1, the identifiers non-negative; V05: the day is ``YYYY-MM-DD`` and
  inside the window of the file, the key (store, product, day) is unique; V06: one chain of categories and one group per product, one city per store;
  V07: every series has every day of the window). The first failing rule ends the read. The two sums that contain the hidden hours
  (``sale_amount``, ``stock_hour6_22_cnt``) are read only to count where they differ from the hours (V26, V27) and are then dropped, and the
  weather is never read (D05).
* ``canonical`` (V05, V07) turns the frames of the two files into the series table, the series-days table (with the state and the band of every day)
  and the two tensors of every day; ``write_canonical`` writes them and, last, their manifest.
* ``fetch_source`` is the first task: it checks the files (V01), reads and writes the canonical files only when they are missing or are not the
  ones the manifest names for these two hashes, and registers the quick-mode hashes only after both files were read without a failing rule. A
  rejected source writes nothing and leaves what was there untouched.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from promolift.config import PipelineConfig
from promolift.cube import (
    FIELDS,
    INTERIM_MANIFEST,
    INTERIM_MANIFEST_VERSION,
    TABLES,
    InterimError,
    manifest_problem,
    write_table,
    write_tensor,
)
from promolift.days import STATE_NAMES, day_band, day_state
from promolift.files import sha256_file, write_atomic
from promolift.schema import (
    DAILY_KEPT,
    ID_COLUMNS,
    SERIES_DAYS_SCHEMA,
    SERIES_SCHEMA,
    SOURCE_SCHEMA,
    SourceError,
)

BATCH_ROWS = 100_000
MAX_ROW_GROUPS = 100_000           # a footer that names more row groups than this is not one of the two files (V03)
MAX_ID = 2**31                     # identifiers are non-negative and fit in 31 bits (V04): a series is one 62-bit key
EXAMPLES = 5                       # how many failing keys a rule names (keys, never measured values)
SPLITS = ("train", "eval")
LOCK_NAME = "source.lock.json"
LOCK_VERSION = 1
SUM_TOLERANCE = 1e-9               # V26: relative to the sum of the hours (the real file differs by 7e-15 at most)
RUNBOOK_R1 = "runbook R1: docs/runbook.md"
RUNBOOK_R2 = "runbook R2: docs/runbook.md"

_HEX64 = re.compile(r"[0-9a-f]{64}")
_DATE_TEXT = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$"
_READ_COLUMNS = (*ID_COLUMNS, "dt", "hours_sale", "hours_stock_status", *DAILY_KEPT, "sale_amount", "stock_hour6_22_cnt")

__all__ = ["INTERIM_MANIFEST", "InterimError", "SourceFrames", "SourceReport", "Canonical", "canonical", "canonical_state", "check_source",
           "fetch_source", "read_canonical", "read_source", "read_source_lock", "write_canonical", "write_source_lock", "sha256_file"]


@dataclass(frozen=True)
class SourceReport:
    """What the reader saw (V02-V07 passed): the rows, the series, the distinct days and the first and last one, the bytes and row groups of the
    file, and how many rows have a ``sale_amount`` that is not the sum of the hours (V26) or a ``stock_hour6_22_cnt`` that is not the count of
    their out-of-stock analysis hours (V27)."""

    split: str
    rows: int
    series: int
    days: int
    first_day: date
    last_day: date
    size_bytes: int
    row_groups: int
    sale_amount_mismatch: int
    stock_count_mismatch: int


@dataclass(frozen=True)
class SourceFrames:
    """One file, as the pipeline may keep it: the identifiers, the day, the three daily fields it uses and the two hourly lists as arrays. Rows are
    in the order of the file. No forbidden column is a field."""

    split: str
    ids: pd.DataFrame            # the 7 identifier columns, int64
    date_key: np.ndarray         # int32, YYYYMMDD
    flag: np.ndarray             # int8, activity_flag
    discount: np.ndarray         # float64
    holiday: np.ndarray          # int8, holiday_flag
    sales: np.ndarray            # float32 (rows, 24)
    stock: np.ndarray            # int8 (rows, 24), 1 = out of stock


@dataclass
class Canonical:
    """The canonical data of both files: ``series`` (``series_key`` and the identifiers), ``series_days`` (one row per series and day, sorted by day
    then series, with the state and the band), ``sales`` and ``stock`` as ``[series, day, hour]`` arrays over the ``date_keys`` and the counts."""

    series: pd.DataFrame
    series_days: pd.DataFrame
    sales: np.ndarray            # float32 (series, days, 24)
    stock: np.ndarray            # int8 (series, days, 24)
    date_keys: np.ndarray        # int32 (days,)
    counts: dict[str, Any]


def _rule(rule_id: str, message: str, runbook: str | None = None, **problem: Any) -> SourceError:
    runbook = runbook or (RUNBOOK_R1 if rule_id == "V01" else RUNBOOK_R2)
    return SourceError(rule_id, f"{message} ({runbook})", [{"rule_id": rule_id, **problem}])


def _window(split: str, cfg: Any) -> tuple[date, date]:
    """The first and the last day a file may hold: train the launch, eval the days after it."""
    c = cfg.calendar
    return (c.first_day, c.launch_last_day) if split == "train" else (c.launch_last_day + timedelta(days=1), c.last_day)


# --- V01: the pinned files ---------------------------------------------------------------------------------------------------


def read_source_lock(path: Path) -> dict[str, Any] | None:
    """The hashes that quick mode registered, or None if none are. Anything else than the exact format is V01."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        files = document["files"]
        valid = (isinstance(document, dict) and set(document) == {"version", "files"} and document["version"] == LOCK_VERSION
                 and isinstance(files, dict) and set(files) == set(SPLITS)
                 and all(isinstance(v, dict) and set(v) == {"sha256", "size"} and isinstance(v["sha256"], str) and _HEX64.fullmatch(v["sha256"])
                         and isinstance(v["size"], int) and not isinstance(v["size"], bool) for v in files.values()))
    except (OSError, ValueError, KeyError, TypeError):
        valid = False
    if not valid:
        raise _rule("V01", f"{path} no es un registro válido de las huellas de la fuente (se esperaba {{version, files: {{train, eval}}}})", path=str(path))
    return document


def write_source_lock(path: Path, files: dict[str, tuple[str, int]]) -> None:
    """Register the hash and size of each file (``{"train": (sha256, size), "eval": (sha256, size)}``)."""
    document = {"version": LOCK_VERSION, "files": {name: {"sha256": digest, "size": size} for name, (digest, size) in files.items()}}
    write_atomic(Path(path), json.dumps(document, indent=2, sort_keys=True) + "\n")


def check_source(cfg: PipelineConfig) -> tuple[str, str]:
    """V01 (and the byte cap of V03): both files exist and are the accepted ones, or, in quick mode, the registered ones. Returns the SHA-256 of
    the train and of the eval file. Writes nothing and downloads nothing: a missing or different file is refused with the runbook R1 (D02). The
    existence, the size and the cap of both files are checked before any file is hashed."""
    source = cfg.source
    files = (("train", Path(source.train_path), source.train_bytes, source.train_sha256),
             ("eval", Path(source.eval_path), source.eval_bytes, source.eval_sha256))
    for name, path, accepted_bytes, accepted_sha in files:
        if not path.is_file():
            raise _rule("V01", f"no existe el archivo de la fuente {path}: hay que colocarlo ahí", path=str(path), file=name, reason="missing")
        size = path.stat().st_size
        if accepted_sha and size != accepted_bytes:
            raise _rule("V01", f"el archivo {path} pesa {size} bytes y se aceptan {accepted_bytes}; no se cambió nada", path=str(path), file=name,
                        reason="size", expected=accepted_bytes, actual=size)
        if size > source.max_bytes:     # the cap is held before the file is read or hashed
            raise _rule("V03", f"el archivo {path} pesa {size} bytes, por encima del límite de {source.max_bytes} ([source] max_bytes)", path=str(path),
                        file=name, size=size, max_bytes=source.max_bytes)
    registered = read_source_lock(Path(source.train_path).parent / LOCK_NAME)
    digests = []
    for name, path, _accepted_bytes, accepted_sha in files:
        digest = sha256_file(path)
        expected = accepted_sha or (registered["files"][name]["sha256"] if registered is not None else "")
        if expected and digest != expected:
            what = "aceptada" if accepted_sha else "registrada"
            raise _rule("V01", f"el archivo {path} tiene la huella SHA-256 {digest} y la {what} es {expected}; no se cambió nada", path=str(path), file=name,
                        reason="sha256", expected=expected, actual=digest)
        digests.append(digest)
    return digests[0], digests[1]


# --- V02-V07, V26, V27: the strict reader --------------------------------------------------------------------------------------


def _schema_problem(file_schema: pa.Schema) -> str | None:
    """What differs between the file's schema and ``SOURCE_SCHEMA`` (names, order, types), or None."""
    have, want = file_schema.names, SOURCE_SCHEMA.names
    extra, missing = [n for n in have if n not in want], [n for n in want if n not in have]
    if extra or missing:
        return f"las columnas no son las {len(want)} de la fuente: de más {extra or 'ninguna'}, faltan {missing or 'ninguna'}"
    if have != want:
        return f"las columnas están en otro orden que el de la fuente: {have}"
    for name in want:
        if file_schema.field(name).type != SOURCE_SCHEMA.field(name).type:
            return f"la columna {name} es {file_schema.field(name).type} y se esperaba {SOURCE_SCHEMA.field(name).type}"
    return None


def _no_nulls(array: pa.Array, column: str) -> None:
    if array.null_count:
        raise _rule("V04", f"la columna {column} tiene {array.null_count} nulos en un lote del archivo", column=column, nulls=array.null_count)


def _hourly(array: pa.Array, column: str) -> np.ndarray:
    """The (rows, 24) values of a list column, or V04: a null list, a list that does not have 24 values, a null inside a list."""
    if array.null_count:
        raise _rule("V04", f"{column}: hay {array.null_count} listas nulas", column=column, nulls=array.null_count)
    lengths = array.value_lengths().to_numpy(zero_copy_only=False)
    wrong = lengths != 24
    if wrong.any():
        raise _rule("V04", f"{column}: {int(wrong.sum())} listas no tienen 24 valores (la primera tiene {int(lengths[wrong][0])})", column=column,
                    lists=int(wrong.sum()))
    values = array.flatten()
    if values.null_count:
        raise _rule("V04", f"{column}: {values.null_count} valores nulos dentro de las listas", column=column, nulls=values.null_count)
    return values.to_numpy(zero_copy_only=False).reshape(-1, 24)


def _days_of(array: pa.Array, window: tuple[date, date], split: str) -> np.ndarray:
    """The day of each row as int64 days since 1970-01-01, or V05: not ``YYYY-MM-DD``, not a real date, or outside the window of the file."""
    if array.null_count:
        raise _rule("V04", f"la columna dt tiene {array.null_count} nulos", column="dt", nulls=array.null_count)
    shaped = pc.match_substring_regex(array, _DATE_TEXT)
    if not pc.all(shaped).as_py():
        bad = array.filter(pc.invert(shaped))[0].as_py()
        raise _rule("V05", f"dt: {pc.sum(pc.invert(shaped)).as_py()} valores no tienen el formato AAAA-MM-DD (por ejemplo {bad!r})", column="dt")
    parsed = pc.strptime(array, "%Y-%m-%d", "s", error_is_null=True)
    if parsed.null_count:
        raise _rule("V05", f"dt: {parsed.null_count} valores no son una fecha real", column="dt")
    days = parsed.cast(pa.date32()).to_numpy(zero_copy_only=False).astype("datetime64[D]").astype(np.int64)
    first, last = (np.datetime64(window[0], "D").astype(np.int64), np.datetime64(window[1], "D").astype(np.int64))
    outside = (days < first) | (days > last)
    if outside.any():
        example = (np.datetime64(int(days[outside][0]), "D")).astype(date).isoformat()
        raise _rule("V05", f"dt: {int(outside.sum())} filas están fuera de la ventana de {split} ({window[0]} a {window[1]}), por ejemplo {example}",
                    column="dt", rows=int(outside.sum()), window=[window[0].isoformat(), window[1].isoformat()])
    return days


def _date_keys(days: np.ndarray) -> np.ndarray:
    """YYYYMMDD of int64 days since 1970-01-01."""
    d = days.astype("datetime64[D]")
    year = d.astype("datetime64[Y]").astype(np.int64) + 1970
    month = d.astype("datetime64[M]").astype(np.int64) % 12 + 1
    day = (d - d.astype("datetime64[M]")).astype(np.int64) + 1
    return (year * 10_000 + month * 100 + day).astype(np.int32)


def _flag(array: pa.Array, column: str) -> np.ndarray:
    _no_nulls(array, column)
    values = array.to_numpy(zero_copy_only=False)
    if not np.isin(values, (0, 1)).all():
        raise _rule("V04", f"{column}: {int((~np.isin(values, (0, 1))).sum())} valores no son 0 ni 1", column=column)
    return values.astype(np.int8)


def _examples(keys: np.ndarray, days: np.ndarray, bad: np.ndarray) -> list[dict[str, int]]:
    """Up to ``EXAMPLES`` of the (store, product, day) keys of the rows in `bad` (identifiers and days, never a measured value)."""
    out = []
    for index in np.flatnonzero(bad)[:EXAMPLES]:
        out.append({"store_id": int(keys[index] >> 31), "product_id": int(keys[index] & (MAX_ID - 1)),
                    "date_key": int(_date_keys(days[index:index + 1])[0])})
    return out


def read_source(path: Path, split: str, cfg: Any) -> tuple[SourceFrames, SourceReport]:
    """Read and check one file strictly (V02-V07, V26, V27); the first failing rule raises ``SourceError`` and nothing is returned."""
    if split not in SPLITS:
        raise ValueError(f"split debe ser 'train' o 'eval', se recibió {split!r}")
    path = Path(path)
    source = cfg.source
    window = _window(split, cfg)
    if not path.is_file():
        raise _rule("V01", f"no existe el archivo de la fuente {path}: hay que colocarlo ahí", path=str(path), reason="missing")
    size = path.stat().st_size
    if size > source.max_bytes:
        raise _rule("V03", f"el archivo {path} pesa {size} bytes, por encima del límite de {source.max_bytes} ([source] max_bytes)", size=size)
    try:
        parquet = pq.ParquetFile(path)
        metadata, file_schema = parquet.metadata, parquet.schema_arrow
    except (pa.ArrowException, OSError) as error:
        raise _rule("V02", f"{path} no es un archivo Parquet legible ({type(error).__name__})", path=str(path)) from None
    problem = _schema_problem(file_schema)
    if problem:
        raise _rule("V02", f"esquema distinto del de la fuente: {problem}", path=str(path))
    if metadata.num_rows > source.max_rows:
        raise _rule("V03", f"el archivo tiene {metadata.num_rows} filas, por encima del límite de {source.max_rows} ([source] max_rows)",
                    rows=metadata.num_rows, max_rows=source.max_rows)
    if metadata.num_row_groups > MAX_ROW_GROUPS:
        raise _rule("V03", f"el archivo tiene {metadata.num_row_groups} grupos de filas, por encima del límite de {MAX_ROW_GROUPS}",
                    row_groups=metadata.num_row_groups)
    first_hour, last_hour = cfg.calendar.day_hours

    ids, days, flag, discount, holiday, sales_f32, stock = [], [], [], [], [], [], []
    sale_mismatch = stock_mismatch = 0
    for batch in parquet.iter_batches(batch_size=BATCH_ROWS, columns=list(_READ_COLUMNS)):
        part = {}
        for column in ID_COLUMNS:
            array = batch.column(column)
            _no_nulls(array, column)
            values = array.to_numpy(zero_copy_only=False)
            if ((values < 0) | (values >= MAX_ID)).any():
                raise _rule("V04", f"{column}: hay identificadores negativos o de más de 31 bits", column=column)
            part[column] = values
        days.append(_days_of(batch.column("dt"), window, split))
        hours_sale = _hourly(batch.column("hours_sale"), "hours_sale")
        hours_stock = _hourly(batch.column("hours_stock_status"), "hours_stock_status")
        if not np.isfinite(hours_sale).all() or (hours_sale < 0).any() or (hours_sale > source.max_hourly_sale).any():
            raise _rule("V04", f"hours_sale: hay ventas no finitas, negativas o por encima de {source.max_hourly_sale} ([source] max_hourly_sale)",
                        column="hours_sale")
        if not np.isin(hours_stock, (0, 1)).all():
            raise _rule("V04", "hours_stock_status: hay estados que no son 0 ni 1", column="hours_stock_status")
        discounts = batch.column("discount")
        _no_nulls(discounts, "discount")
        discount_values = discounts.to_numpy(zero_copy_only=False)
        if not np.isfinite(discount_values).all():
            raise _rule("V04", f"discount: {int((~np.isfinite(discount_values)).sum())} valores no finitos", column="discount")
        flag.append(_flag(batch.column("activity_flag"), "activity_flag"))
        holiday.append(_flag(batch.column("holiday_flag"), "holiday_flag"))
        discount.append(discount_values)
        # V26 and V27: the two sums are compared with the hours, counted and dropped
        amount, count = batch.column("sale_amount"), batch.column("stock_hour6_22_cnt")
        _no_nulls(amount, "sale_amount")
        _no_nulls(count, "stock_hour6_22_cnt")
        totals = hours_sale.sum(axis=1)
        sale_mismatch += int((np.abs(amount.to_numpy(zero_copy_only=False) - totals) > SUM_TOLERANCE * np.maximum(1.0, np.abs(totals))).sum())
        stock_mismatch += int((hours_stock[:, first_hour:last_hour + 1].sum(axis=1) != count.to_numpy(zero_copy_only=False)).sum())
        ids.append(pd.DataFrame(part))
        sales_f32.append(hours_sale.astype(np.float32))
        stock.append(hours_stock.astype(np.int8))
    if not ids:
        raise _rule("V05", "el archivo no tiene filas", rows=0)
    frame, day = pd.concat(ids, ignore_index=True), np.concatenate(days)
    store, product = frame["store_id"].to_numpy(), frame["product_id"].to_numpy()
    keys = (store << 31) | product
    unique_keys, inverse = np.unique(keys, return_inverse=True)
    n_days = int(np.datetime64(window[1], "D").astype(np.int64) - np.datetime64(window[0], "D").astype(np.int64)) + 1
    first_epoch = int(np.datetime64(window[0], "D").astype(np.int64))
    combined = inverse.astype(np.int64) * 1024 + (day - first_epoch)
    _, position, repeats = np.unique(combined, return_index=True, return_counts=True)
    if (repeats > 1).any():
        bad = np.zeros(len(frame), dtype=bool)
        bad[position[repeats > 1]] = True
        raise _rule("V05", f"la clave (tienda, producto, día) se repite en {int((repeats > 1).sum())} casos (por ejemplo "
                    f"{_examples(keys, day, bad)[0]})", rows=int((repeats > 1).sum()), examples=_examples(keys, day, bad))
    chain = ["product_id", "management_group_id", "first_category_id", "second_category_id", "third_category_id"]
    products = frame[chain].drop_duplicates()
    if products["product_id"].duplicated().any():
        raise _rule("V06", f"el producto {int(products['product_id'][products['product_id'].duplicated()].iloc[0])} tiene más de una cadena de "
                    "categorías o más de un grupo de gestión", rule="product_chain")
    stores = frame[["store_id", "city_id"]].drop_duplicates()
    if stores["store_id"].duplicated().any():
        raise _rule("V06", f"la tienda {int(stores['store_id'][stores['store_id'].duplicated()].iloc[0])} tiene más de una ciudad", rule="store_city")
    per_series = np.bincount(inverse)
    if (per_series != n_days).any():
        bad_series = np.flatnonzero(per_series != n_days)
        raise _rule("V07", f"{len(bad_series)} series no tienen los {n_days} días de la ventana de {split} (la serie "
                    f"{int(unique_keys[bad_series[0]] >> 31)}-{int(unique_keys[bad_series[0]] & (MAX_ID - 1))} tiene {int(per_series[bad_series[0]])})",
                    series=len(bad_series), days=n_days)
    distinct_days = np.unique(day)
    frames = SourceFrames(
        split=split, ids=frame, date_key=_date_keys(day), flag=np.concatenate(flag), discount=np.concatenate(discount),
        holiday=np.concatenate(holiday), sales=np.concatenate(sales_f32), stock=np.concatenate(stock))
    report = SourceReport(
        split=split, rows=len(frame), series=len(unique_keys), days=len(distinct_days), first_day=window[0] + timedelta(days=int(distinct_days[0] - first_epoch)),
        last_day=window[0] + timedelta(days=int(distinct_days[-1] - first_epoch)), size_bytes=size, row_groups=metadata.num_row_groups,
        sale_amount_mismatch=sale_mismatch, stock_count_mismatch=stock_mismatch)
    return frames, report


# --- the canonical tables --------------------------------------------------------------------------------------------------------


def _calendar_keys(cfg: Any) -> np.ndarray:
    c = cfg.calendar
    count = (c.last_day - c.first_day).days + 1
    return np.array([(c.first_day + timedelta(days=i)).year * 10_000 + (c.first_day + timedelta(days=i)).month * 100 + (c.first_day + timedelta(days=i)).day
                     for i in range(count)], dtype=np.int32)


def canonical(frames: tuple[SourceFrames, ...], cfg: Any) -> Canonical:
    """The canonical data of the frames of the train file and of the eval file (in that order): the series (V07: the same in both files, V06: with one
    hierarchy), the series-days with their state and band, and the tensors by series, day and hour. V05: the two files together hold every day of the
    calendar once. No forbidden column exists in the frames, so none can reach the result."""
    if len(frames) != 2 or [f.split for f in frames] != list(SPLITS):
        raise ValueError("se esperaban los marcos de train y de eval, en ese orden")
    train, eval_ = frames
    date_keys = _calendar_keys(cfg)
    seen = np.concatenate([np.unique(train.date_key), np.unique(eval_.date_key)])
    if len(seen) != len(np.unique(seen)) or not np.array_equal(np.sort(seen), date_keys):
        raise _rule("V05", f"train y eval juntos no cubren los {len(date_keys)} días del calendario una vez cada uno, sin solaparse y sin huecos",
                    days=len(np.unique(seen)), calendar_days=len(date_keys))
    per_file = [f.ids.drop_duplicates() for f in frames]
    one, other = (set(zip(p["store_id"], p["product_id"])) for p in per_file)
    if one != other:
        raise _rule("V07", f"las series de train ({len(one)}) y las de eval ({len(other)}) no son las mismas", train_series=len(one), eval_series=len(other))
    series = per_file[0].sort_values(["store_id", "product_id"]).reset_index(drop=True)
    merged = pd.concat(per_file).drop_duplicates()
    if len(merged) != len(series):
        raise _rule("V06", "una serie (tienda, producto) cambia de jerarquía entre el archivo de train y el de eval", rule="series_hierarchy")
    series.insert(0, "series_key", np.arange(len(series), dtype=np.int32))
    sorted_keys = (series["store_id"].to_numpy() << 31) | series["product_id"].to_numpy()
    n_series, n_days = len(series), len(date_keys)
    sales = np.zeros((n_series, n_days, 24), dtype=np.float32)
    stock = np.zeros((n_series, n_days, 24), dtype=np.int8)
    series_key, date_key, flag, discount, holiday = [], [], [], [], []
    for frame in frames:
        rows = np.searchsorted(sorted_keys, (frame.ids["store_id"].to_numpy() << 31) | frame.ids["product_id"].to_numpy()).astype(np.int32)
        day = np.searchsorted(date_keys, frame.date_key)
        sales[rows, day] = frame.sales
        stock[rows, day] = frame.stock
        series_key.append(rows)
        date_key.append(frame.date_key)
        flag.append(frame.flag)
        discount.append(frame.discount)
        holiday.append(frame.holiday)
    series_key, date_key, flag = np.concatenate(series_key), np.concatenate(date_key), np.concatenate(flag)
    discount, holiday = np.concatenate(discount), np.concatenate(holiday)
    order = np.lexsort((series_key, date_key))
    series_key, date_key, flag, discount, holiday = series_key[order], date_key[order], flag[order], discount[order], holiday[order]
    state = day_state(flag, discount, cfg)
    series_days = pd.DataFrame({
        "series_key": series_key, "date_key": date_key, "activity_flag": flag, "discount": discount, "holiday_flag": holiday, "day_state": state,
        "band": day_band(state, discount, cfg)})
    counts = {
        "series": n_series, "days": n_days, "series_days": len(series_days), "rows": {"train": len(train.sales), "eval": len(eval_.sales)},
        "day_state": {name: int((state == code).sum()) for code, name in enumerate(STATE_NAMES)},
        "discount_zero": int((discount == 0).sum()), "discount_above_one": int((discount > 1).sum()),
        "discount_below_half": int(((discount > 0) & (discount < 0.5)).sum()), "flag_with_no_discount": int(((flag == 1) & (discount == 1.0)).sum()),
    }
    return Canonical(series=series, series_days=series_days, sales=sales, stock=stock, date_keys=date_keys, counts=counts)


def write_canonical(canon: Canonical, interim_dir: Path, train_sha256: str, eval_sha256: str) -> None:
    """Write the two tables, the tensors of every day and, last, ``interim_manifest.json`` with the hash of each file and of the two sources. The old
    manifest is removed first: a failure in the middle leaves files without a manifest, which every reader refuses and the task rebuilds."""
    folder = Path(interim_dir)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / INTERIM_MANIFEST).unlink(missing_ok=True)
    files = {}
    for name, frame, schema in (("series.parquet", canon.series, SERIES_SCHEMA), ("series_days.parquet", canon.series_days, SERIES_DAYS_SCHEMA)):
        files[name] = write_table(folder, name, pa.Table.from_pandas(frame, schema=schema, preserve_index=False), train_sha256, eval_sha256)
    for index, key in enumerate(canon.date_keys.tolist()):
        for field in FIELDS:
            array = getattr(canon, field)[:, index, :]
            files[f"canonical/{key}.{field}.npy"] = write_tensor(folder, key, field, array)
    manifest = {"version": INTERIM_MANIFEST_VERSION, "train_sha256": train_sha256, "eval_sha256": eval_sha256, "counts": canon.counts, "files": files}
    write_atomic(folder / INTERIM_MANIFEST, json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def canonical_state(interim_dir: Path) -> tuple[str, str] | None:
    """The SHA-256 of the train and the eval files the canonical files were built from, or None if they are not the files their manifest names."""
    problem, document = manifest_problem(interim_dir)
    return None if problem is not None else (document["train_sha256"], document["eval_sha256"])


def read_canonical(interim_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """``(series, series_days)``; ``InterimError`` if the files are not the ones their manifest names."""
    problem, _document = manifest_problem(interim_dir)
    if problem is not None:
        raise InterimError(problem)
    folder = Path(interim_dir)
    return pq.read_table(folder / TABLES[0]).to_pandas(), pq.read_table(folder / TABLES[1]).to_pandas()


# --- the first task ----------------------------------------------------------------------------------------------------------


def fetch_source(cfg: PipelineConfig) -> dict[str, Any]:
    """Task 1: make sure the files are the pinned ones (V01) and that the canonical files are built from them.

    The canonical files are rebuilt only when they are missing, do not match their manifest or come from other hashes, so repeating the task changes
    nothing. A rejected source writes nothing; in quick mode the hashes are registered only after both files were read without a failing rule (or,
    when the canonical files are current, when the registry is missing). Returns the hashes, whether anything was built and the counts."""
    source, interim_dir = cfg.source, cfg.paths.interim_dir
    train_sha, eval_sha = check_source(cfg)
    lock = Path(source.train_path).parent / LOCK_NAME
    sizes = {"train": Path(source.train_path).stat().st_size, "eval": Path(source.eval_path).stat().st_size}
    pinned = bool(source.train_sha256 and source.eval_sha256)

    def register() -> None:
        if not pinned and read_source_lock(lock) is None:
            write_source_lock(lock, {"train": (train_sha, sizes["train"]), "eval": (eval_sha, sizes["eval"])})

    result: dict[str, Any] = {"train_sha256": train_sha, "eval_sha256": eval_sha}
    if canonical_state(interim_dir) == (train_sha, eval_sha):
        register()
        return result | {"built": False, **manifest_problem(interim_dir)[1]["counts"]}
    train, train_report = read_source(source.train_path, "train", cfg)
    eval_, eval_report = read_source(source.eval_path, "eval", cfg)
    canon = canonical((train, eval_), cfg)
    canon.counts["sale_amount_mismatch"] = train_report.sale_amount_mismatch + eval_report.sale_amount_mismatch
    canon.counts["stock_count_mismatch"] = train_report.stock_count_mismatch + eval_report.stock_count_mismatch
    for split, report in (("train", train_report), ("eval", eval_report)):      # which file each total comes from, for V26 and V27 of the run (U16)
        canon.counts[f"sale_amount_mismatch_{split}"], canon.counts[f"stock_count_mismatch_{split}"] = report.sale_amount_mismatch, report.stock_count_mismatch
    write_canonical(canon, interim_dir, train_sha, eval_sha)
    register()
    return result | {"built": True, **canon.counts}
