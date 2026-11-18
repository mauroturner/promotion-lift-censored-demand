"""Deliveries: the feed that stands in for the daily load of a retailer over two static files (RF05, D18; plan, sections 3 and 6); adapted from project 05.

The canonical series-days and day tensors are cut into a fixed plan that comes from the calendar of the configuration: the launch
``L<launch_last_day>`` (every day from ``first_day``), one delivery ``D<day>`` per day until ``last_day`` and the close ``C<day after last_day>``,
which has no days and is where the test is evaluated once. The ``as_of`` of a delivery is 00:00 of the day after its last day (a day is known whole
when it closes, D05); the close's is 00:00 of the day after ``last_day``. A day, and every series-day of it, belongs to the delivery of its day.

Each delivery is two files: ``<id>.days.parquet`` (the series-days of the period with their state, band and the sums of 06 to 21: no hourly list)
and ``<id>.cube.npz`` (the sale and the stock status of its 24 hours, float32 and int8), listed in ``manifest.json``
(``{"version": 1, "entries": [...]}``, written to a temporary file and renamed) with its period, series-days and SHA-256 and a status that moves from
``published`` to ``loaded`` (or ``rejected``). Publishing is idempotent: the same days give the same bytes and leave the manifest untouched; a
loaded delivery is never replaced. The next pending delivery is always the first of the plan that is not loaded (runbook R4).
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
from dataclasses import asdict, dataclass, fields, replace
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from promolift.cube import ATTRIBUTION, ATTRIBUTION_KEY, delivery_cube_bytes, read_delivery_cube
from promolift.files import sha256_file, write_atomic
from promolift.schema import SERIES_DAYS_COLUMNS, SERIES_DAYS_SCHEMA, date_key

logger = logging.getLogger(__name__)

MANIFEST_NAME = "manifest.json"
MANIFEST_VERSION = 1
DELIVERY_KINDS = ("launch", "daily", "close")
DELIVERY_STATUSES = ("published", "loaded", "rejected")
DELIVERY_ID_KEY = b"promolift.delivery_id"
PERIOD_KEY = b"promolift.period"
DAY = timedelta(days=1)
# the series-days columns of the canonical table and the four sums of the analysis hours (06 to 21) that the load aggregates
SUM_COLUMNS = ("raw_sum", "instock_hours", "stockout_hours", "instock_sum")
DAYS_COLUMNS: tuple[str, ...] = (*SERIES_DAYS_COLUMNS, *SUM_COLUMNS)
DAYS_SCHEMA = pa.schema([*SERIES_DAYS_SCHEMA, ("raw_sum", pa.float64()), ("instock_hours", pa.int8()), ("stockout_hours", pa.int8()),
                         ("instock_sum", pa.float64())])
_NO_PERIOD = "none"


@dataclass(frozen=True)
class DeliverySpec:
    """One delivery of the plan: the days it holds (none for the close) and the instant the run that loads it has reached."""

    delivery_id: str
    kind: str
    first_day: date | None
    last_day: date | None
    as_of: datetime


@dataclass(frozen=True)
class ManifestEntry:
    delivery_id: str
    kind: str
    first_day: date | None
    last_day: date | None
    as_of: datetime
    series_days: int
    days_sha256: str
    cube_sha256: str
    sha256: str
    days_file: str
    cube_file: str
    published_at: str
    status: str
    run_key: str | None


def _midnight_after(day: date) -> datetime:
    return datetime.combine(day + DAY, time.min)


def delivery_plan(view: Any) -> list[DeliverySpec]:
    """The fixed plan of D18: the launch, one delivery per day after it and the close, contiguous, each with its ``as_of``. `view` is the
    configuration or its sealed view (anything with ``.calendar``)."""
    c = view.calendar
    plan = [DeliverySpec(f"L{c.launch_last_day.isoformat()}", "launch", c.first_day, c.launch_last_day, _midnight_after(c.launch_last_day))]
    day = c.launch_last_day + DAY
    while day <= c.last_day:
        plan.append(DeliverySpec(f"D{day.isoformat()}", "daily", day, day, _midnight_after(day)))
        day += DAY
    plan.append(DeliverySpec(f"C{(c.last_day + DAY).isoformat()}", "close", None, None, _midnight_after(c.last_day)))
    return plan


# --- the manifest ------------------------------------------------------------------------------------------------------------------


def _day(value: Any) -> date | None:
    return None if value is None else date.fromisoformat(value)


def _entry_from(raw: Any) -> ManifestEntry:
    names = {f.name for f in fields(ManifestEntry)}
    if not isinstance(raw, dict) or set(raw) != names:
        raise KeyError(f"claves distintas de las esperadas: {sorted(names ^ set(raw)) if isinstance(raw, dict) else raw!r}")
    values = dict(raw)
    values["as_of"] = datetime.fromisoformat(values["as_of"])
    for key in ("first_day", "last_day"):
        values[key] = _day(values[key])
    if not isinstance(values["series_days"], int) or isinstance(values["series_days"], bool) or values["series_days"] < 0:
        raise TypeError(f"series_days: se esperaba un entero, se recibió {values['series_days']!r}")
    for key in ("delivery_id", "days_sha256", "cube_sha256", "sha256", "days_file", "cube_file", "published_at"):
        if not isinstance(values[key], str):
            raise TypeError(f"{key}: se esperaba un texto, se recibió {values[key]!r}")
    if values["kind"] not in DELIVERY_KINDS:
        raise ValueError(f"kind: {values['kind']!r} no es uno de {', '.join(DELIVERY_KINDS)}")
    if values["status"] not in DELIVERY_STATUSES:
        raise ValueError(f"status: {values['status']!r} no es uno de {', '.join(DELIVERY_STATUSES)}")
    if values["run_key"] is not None and not isinstance(values["run_key"], str):
        raise TypeError(f"run_key: se esperaba un texto o null, se recibió {values['run_key']!r}")
    return ManifestEntry(**values)


def read_manifest(path: Path) -> list[ManifestEntry]:
    """The entries in the order they were published; a missing manifest is an empty list."""
    path = Path(path)
    if not path.exists():
        return []
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict) or document.get("version") != MANIFEST_VERSION or set(document) != {"version", "entries"}:
            raise KeyError("versión o claves de primer nivel inesperadas")
        entries = [_entry_from(raw) for raw in document["entries"]]
        ids = [e.delivery_id for e in entries]
        if len(set(ids)) != len(ids):
            raise ValueError("hay entregas repetidas")
    except (ValueError, KeyError, TypeError) as error:
        raise ValueError(f"{path} no es un manifiesto de entregas válido: {error}") from error
    return entries


def _write_manifest(path: Path, entries: list[ManifestEntry]) -> None:
    def encode(entry: ManifestEntry) -> dict[str, Any]:
        document = asdict(entry)
        for key in ("first_day", "last_day"):
            document[key] = None if document[key] is None else document[key].isoformat()
        document["as_of"] = document["as_of"].isoformat()
        return document

    write_atomic(Path(path), json.dumps({"version": MANIFEST_VERSION, "entries": [encode(e) for e in entries]}, indent=2, ensure_ascii=False) + "\n")


def next_pending(manifest: Path, plan: list[DeliverySpec]) -> DeliverySpec | None:
    """The first delivery of the plan that is not loaded: the next one to run, or None when the plan is complete.

    A delivery that is ``published`` or ``rejected`` stays the pending one (a failed run is repeated with the same delivery). An entry that is
    not in the plan, has another period, or is loaded after one that is not is an error (runbook R4): the plan is never skipped.
    """
    entries = {e.delivery_id: e for e in read_manifest(manifest)}
    by_id = {spec.delivery_id: spec for spec in plan}
    for delivery_id, entry in entries.items():
        spec = by_id.get(delivery_id)
        if spec is None:
            raise ValueError(f"el manifiesto trae la entrega {delivery_id}, que no está en el plan (runbook R4)")
        if (entry.kind, entry.first_day, entry.last_day, entry.as_of) != (spec.kind, spec.first_day, spec.last_day, spec.as_of):
            raise ValueError(f"la entrega {delivery_id} tiene otro período en el manifiesto ({entry.first_day} a {entry.last_day}) que en el plan "
                             f"({spec.first_day} a {spec.last_day}) (runbook R4)")
    pending: DeliverySpec | None = None
    for spec in plan:
        entry = entries.get(spec.delivery_id)
        loaded = entry is not None and entry.status == "loaded"
        if pending is None:
            if not loaded:
                pending = spec
        elif loaded:
            raise ValueError(f"la entrega {spec.delivery_id} está cargada pero la anterior, {pending.delivery_id}, no lo está (runbook R4)")
    return pending


def mark_delivery(manifest: Path, delivery_id: str, status: str, run_key: str | None = None) -> None:
    """Set the status of a delivery (and its run, if given); everything else in the manifest is kept.

    A loaded delivery stays loaded by the run that loaded it: marking it rejected or published, or loaded by another run, is refused and the
    manifest is not touched, because ``next_pending`` would offer it again and its series-days would load twice (project 03, D86 and D93). Out of
    ``published`` and ``rejected`` every status is allowed: a rejected delivery is published again and loaded by a later run."""
    if status not in DELIVERY_STATUSES:
        raise ValueError(f"status: {status!r} no es uno de {', '.join(DELIVERY_STATUSES)}")
    entries = read_manifest(manifest)
    entry = next((e for e in entries if e.delivery_id == delivery_id), None)
    if entry is None:
        raise ValueError(f"no hay una entrega {delivery_id} en el manifiesto {manifest}")
    if entry.status == "loaded" and (status != "loaded" or (run_key is not None and run_key != entry.run_key)):
        raise ValueError(f"la entrega {delivery_id} ya está cargada por la corrida {entry.run_key!r} y no pasa a {status!r}"
                         f"{'' if run_key is None else f' de la corrida {run_key!r}'}: sus series-días ya están en el almacén (runbook R4)")
    _write_manifest(Path(manifest), [
        replace(e, status=status, run_key=run_key if run_key is not None else e.run_key) if e.delivery_id == delivery_id else e for e in entries
    ])
    logger.info("manifest %s: delivery %s marked %s", manifest, delivery_id, status)


# --- publishing ------------------------------------------------------------------------------------------------------------------------


def delivery_sums(sales: np.ndarray, stock: np.ndarray, day_hours: tuple[int, int]) -> dict[str, np.ndarray]:
    """The sums of the analysis hours (``day_hours``, both included) of every series and day of `sales` (float32) and `stock` (int8, 1 = no stock),
    both ``[series, day, hour]``: the sale (``raw_sum``), the hours with and without stock and the sale of the hours with stock. The one function
    that publishing uses to write them and rule V14 to check them, so a delivery whose sums are not its own hours is found."""
    first, last = day_hours
    core = sales[:, :, first:last + 1].astype(np.float64)
    out = stock[:, :, first:last + 1] == 1
    n = last - first + 1
    in_stock = n - out.sum(axis=2)
    return {"raw_sum": core.sum(axis=2), "instock_hours": in_stock.astype(np.int8), "stockout_hours": (n - in_stock).astype(np.int8),
            "instock_sum": np.where(out, 0.0, core).sum(axis=2)}


def _select(spec: DeliverySpec, canon: Any, view: Any) -> tuple[pd.DataFrame, np.ndarray, np.ndarray, np.ndarray]:
    """The series-days of the period of `spec` with their sums, and the hours of its days: ``(days, date_keys, sales, stock)``."""
    if spec.first_day is None or spec.last_day is None:      # the close holds nothing
        mask = np.zeros(len(canon.date_keys), dtype=bool)
    else:
        mask = (canon.date_keys >= date_key(spec.first_day)) & (canon.date_keys <= date_key(spec.last_day))
    sales, stock = canon.sales[:, mask, :], canon.stock[:, mask, :]
    sums = delivery_sums(sales, stock, tuple(view.calendar.day_hours))
    keys = canon.date_keys[mask]
    rows = canon.series_days[canon.series_days["date_key"].isin(keys)].reset_index(drop=True)
    days = rows.assign(**{name: sums[name].T.reshape(-1) for name in SUM_COLUMNS})[list(DAYS_COLUMNS)]
    return days, keys, sales, stock


def _days_bytes(spec: DeliverySpec, days: pd.DataFrame) -> bytes:
    table = pa.Table.from_pandas(days.reset_index(drop=True)[list(DAYS_COLUMNS)], schema=DAYS_SCHEMA, preserve_index=False)
    period = _NO_PERIOD if spec.first_day is None or spec.last_day is None else f"{spec.first_day.isoformat()}/{spec.last_day.isoformat()}"
    metadata = {**(table.schema.metadata or {}), DELIVERY_ID_KEY: spec.delivery_id.encode("ascii"), PERIOD_KEY: period.encode("ascii"),
                ATTRIBUTION_KEY: ATTRIBUTION.encode("utf-8")}
    sink = io.BytesIO()
    pq.write_table(table.replace_schema_metadata(metadata), sink)
    return sink.getvalue()


def delivery_digest(days_sha256: str, cube_sha256: str) -> str:
    """The SHA-256 of a delivery: of the two file hashes, in the order days, cube (V13 compares it with the manifest's)."""
    return hashlib.sha256(f"{days_sha256}\n{cube_sha256}".encode("ascii")).hexdigest()


def publish(spec: DeliverySpec, canon: Any, out_dir: Path, view: Any) -> ManifestEntry:
    """Write the series-days and the hours of `spec`'s period as ``<out_dir>/<delivery_id>.days.parquet`` and ``.cube.npz`` and list them in
    ``<out_dir>/manifest.json``. `canon` is the canonical data (``ingest.canonical``); the period is selected here and the sums of the hours
    ``view.calendar.day_hours`` are computed here (``delivery_sums``).

    The same days give the same bytes, so publishing again changes nothing (not even the entry), and a file that went missing or was damaged is
    written again. If the days changed, a delivery that is not loaded is replaced (and goes back to ``published``); a loaded one is never
    replaced: its series-days are already in the warehouse. The files are written before the manifest, so a failure in between lists nothing.
    """
    out_dir = Path(out_dir)
    manifest_path = out_dir / MANIFEST_NAME
    days, keys, sales, stock = _select(spec, canon, view)
    payloads = {"days": _days_bytes(spec, days), "cube": delivery_cube_bytes(keys, sales, stock)}
    days_digest, cube_digest = (hashlib.sha256(payloads[k]).hexdigest() for k in ("days", "cube"))
    digest = delivery_digest(days_digest, cube_digest)
    files = {"days": out_dir / f"{spec.delivery_id}.days.parquet", "cube": out_dir / f"{spec.delivery_id}.cube.npz"}
    entries = read_manifest(manifest_path)
    existing = next((e for e in entries if e.delivery_id == spec.delivery_id), None)

    def write_files() -> None:
        for key, path in files.items():
            if not path.exists() or path.read_bytes() != payloads[key]:
                write_atomic(path, payloads[key])

    if existing is not None and existing.sha256 == digest:
        write_files()
        return existing
    if existing is not None and existing.status == "loaded":
        raise ValueError(f"la entrega {spec.delivery_id} ya está cargada en el almacén y sus días cambiaron en la fuente "
                         f"({existing.sha256[:12]} → {digest[:12]}); no se publica de nuevo (runbook R4)")
    write_files()
    entry = ManifestEntry(spec.delivery_id, spec.kind, spec.first_day, spec.last_day, spec.as_of, len(days), days_digest, cube_digest, digest,
                          files["days"].name, files["cube"].name, datetime.now(UTC).isoformat(timespec="seconds"), "published", None)
    _write_manifest(manifest_path, [entry if e.delivery_id == spec.delivery_id else e for e in entries] if existing else [*entries, entry])
    logger.info("published %s: %d series-days, sha256 %s", spec.delivery_id, entry.series_days, digest)
    return entry


def read_delivery(out_dir: Path, entry: ManifestEntry) -> tuple[pd.DataFrame, tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """``(days, (date_keys, sales, stock))`` of a published delivery, as ``publish`` wrote them."""
    folder = Path(out_dir)
    return pq.read_table(folder / entry.days_file).to_pandas(), read_delivery_cube(folder / entry.cube_file)


__all__ = ["DAYS_COLUMNS", "DAYS_SCHEMA", "MANIFEST_NAME", "DeliverySpec", "ManifestEntry", "delivery_digest", "delivery_plan", "delivery_sums",
           "mark_delivery", "next_pending", "publish", "read_delivery", "read_manifest"]
