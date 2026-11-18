"""The daily run (RF09, RF17, D15, D18; plan, sections 3, 14 and 15): the tasks ``recover`` and ``estimate`` of a delivery of the test week.

For each day of a daily delivery, with the model the launch froze (``LaunchBundle``) and nothing else:

* ``recover_delivery`` recovers the hours without stock of the day with the **sealed method**, stores the recovered hours of the delivery
  (``<delivery_id>.recovered.npy``: the analysis hours recovered, the night and the hours with stock as they were) and sets ``recovered_sum`` of its series-days;
* ``estimate_delivery`` fits the factor ``b(g, d)`` of the day with its own ``regular`` series-days and ``a`` held fixed (``effect.day_factor``), and issues, once,
  the effect of the day by cell, band and the whole day in the two versions (``daily_cell``), the four forecasts of each promo series-day (``forecasts``,
  ``scope = test``) and what each method estimates over the synthetic tail mask of the day next to the truth (``mask_checks``; the mask is drawn with the seed
  ``[mask_seed_test, date_key]``, so it is the same whichever way the days were delivered). The evaluation of the close reads these rows, not a new calculation.

A day uses its own hours, the sealed model and the ``naive_days`` days right before it, so what it issues does not depend on how many days a delivery brought (AC12)
nor on what arrived after (AC11). What is issued is never changed: the three tables are insert-only, and a day that is already issued is found out inside the
transaction that would write it and left alone. ``run_day`` refuses (``ScoringError``) a delivery that is not a loaded daily one, a run whose instant is not the
delivery's and a day that is not after the launch. The close has no days and issues nothing.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field, replace
from datetime import timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from promolift.cube import group_index, load_block, store_recovered
from promolift.days import PROMO, STATE_NAMES
from promolift.deliveries import DeliverySpec
from promolift.effect import Counterfactual, CubeView, Lifts, cell_key, cell_of, day_factor, lifts, records, regular_mask
from promolift.forecast import ForecastError, forecasts
from promolift.masks import mask_tail
from promolift.recovery import Recovery, candidate_name, hidden_mass, recover_day
from promolift.registry import LaunchBundle, RunMeta
from promolift.schema import date_key
from promolift.warehouse import apply_schema, set_recovered_sums

logger = logging.getLogger(__name__)

VERSIONS = ("raw", "recovered")


class ScoringError(RuntimeError):
    """The days of this delivery cannot be issued: it is not a loaded daily delivery, the run is not at its instant, or a day is not one after the launch."""


@dataclass(frozen=True)
class DayResult:
    """What ``estimate_delivery`` did: the delivery and its days, whether anything was issued (``False``: every day was already issued and nothing was touched),
    how many rows went into each table, the promo series-days that could not be forecast and why (``skipped``) and the cells that had promo series-days but no
    counterfactual (``skipped_cells``)."""

    delivery_id: str
    date_keys: tuple[int, ...]
    issued: bool
    rows: dict[str, int]
    skipped: pd.DataFrame = field(default_factory=pd.DataFrame)
    skipped_cells: pd.DataFrame = field(default_factory=pd.DataFrame)


def _days_of(conn: sqlite3.Connection, cube: Any, spec: DeliverySpec, run: RunMeta, view: Any) -> list[int]:
    """The days of a daily delivery that may be issued now, or a ``ScoringError``."""
    if spec.kind != "daily" or spec.first_day is None or spec.last_day is None:
        raise ScoringError(f"solo una entrega diaria se emite, y la entrega {spec.delivery_id} es de tipo {spec.kind}: el lanzamiento no se emite y el cierre evalúa")
    if pd.Timestamp(run.as_of) != pd.Timestamp(spec.as_of):
        raise ScoringError(f"el instante de la corrida ({run.as_of}) no es el de cierre de la entrega {spec.delivery_id} ({spec.as_of}): un día se emite cuando cierra")
    keys = [date_key(spec.first_day + timedelta(days=k)) for k in range((spec.last_day - spec.first_day).days + 1)]
    if keys[0] <= date_key(view.calendar.launch_last_day):
        raise ScoringError(f"el día {keys[0]} no es posterior al lanzamiento ({date_key(view.calendar.launch_last_day)}): el lanzamiento no se emite diariamente")
    row = conn.execute("SELECT status FROM deliveries WHERE delivery_id = ?", (spec.delivery_id,)).fetchone()
    if row is None or row[0] != "loaded":
        raise ScoringError(f"la entrega {spec.delivery_id} no está cargada en el almacén: no se emite un día que no es el de una entrega cargada")
    missing = [k for k in keys if k not in cube]
    if missing:
        raise ScoringError(f"el cubo de las entregas cargadas no tiene el día {missing[0]} de la entrega {spec.delivery_id}")
    return keys


def recover_delivery(conn: sqlite3.Connection, cube: Any, bundle: LaunchBundle, spec: DeliverySpec, run: RunMeta, view: Any, *, interim_dir: Path) -> np.ndarray:
    """The task ``recover``: recover each day of the delivery with the sealed method, store the result and set ``recovered_sum``; returns the recovered hours
    ``(series, days, 24)`` float32. Repeating it changes nothing: the stored hours are the same and a sum already set is not rewritten."""
    keys = _days_of(conn, cube, spec, run, view)
    first, last = view.calendar.day_hours
    block = load_block(cube, conn, keys, view)
    recovered = np.empty((block.sales.shape[0], len(keys), 24), dtype=np.float32)
    sums = np.empty((block.sales.shape[0], len(keys)))
    for position, key in enumerate(keys):
        day = recover_day(bundle.recovery, block.day(position))
        recovered[:, position, :] = cube.sales(key)
        recovered[:, position, first:last + 1] = day
        sums[:, position] = day.sum(axis=1)
    store_recovered(interim_dir, spec.delivery_id, np.array(keys, dtype=np.int32), recovered)
    conn.execute("BEGIN IMMEDIATE")
    try:
        apply_schema(conn)
        set_recovered_sums(conn, np.array(keys, dtype=np.int32), sums)
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    logger.info("recover %s: %d days, %d series", spec.delivery_id, len(keys), block.sales.shape[0])
    return recovered


def _unit_rows(date: int, version: str, rec: Any, inputs: Any, position: np.ndarray, group_ids: np.ndarray, n_bands: int, run_key: str) -> list[tuple]:
    """The ``daily_cell`` rows of a version: the whole day, each band and each cell that has series-days with a counterfactual."""
    band = inputs.band[rec.series].astype(np.int64)
    stock_hours = (inputs.stock[rec.series] == 1).sum(axis=1)
    families = (("all", np.zeros(len(rec.series), dtype=np.int64), 1, lambda k: "all"), ("band", band, n_bands, lambda k: f"b{k}"),
                ("cell", cell_of(position[rec.series], band, n_bands), len(group_ids) * n_bands, lambda k: cell_key(k, group_ids, n_bands)))
    rows = []
    for _name, unit_of, n_units, label in families:
        keep = unit_of >= 0
        observed = np.bincount(unit_of[keep], weights=rec.observed[keep], minlength=n_units)
        expected = np.bincount(unit_of[keep], weights=rec.counterfactual[keep], minlength=n_units)
        count = np.bincount(unit_of[keep], minlength=n_units)
        stockout = np.bincount(unit_of[keep], weights=stock_hours[keep], minlength=n_units)
        lift = lifts(rec, unit_of, n_units)
        for k in np.flatnonzero(count):
            rows.append((date, version, label(int(k)), float(observed[k]), float(expected[k]), float(lift[k]) if np.isfinite(lift[k]) else None, int(count[k]), int(stockout[k]), run_key))
    return rows


def estimate_delivery(conn: sqlite3.Connection, cube: Any, bundle: LaunchBundle, spec: DeliverySpec, run: RunMeta, view: Any, *, recovered: np.ndarray | None = None) -> DayResult:
    """The task ``estimate``: issue the days of the delivery (see the module). `recovered` is what ``recover_delivery`` returned; without it the days are recovered
    again, the same way. A day already issued is skipped inside the transaction and counted as not issued."""
    keys = _days_of(conn, cube, spec, run, view)
    first, last = view.calendar.day_hours
    n_bands = bundle.n_bands
    block = load_block(cube, conn, keys, view)
    position = group_index(block.group, bundle.group_ids)
    methods = {"r1": Recovery("r1", None, bundle.recovery.base, None, bundle.group_ids)}
    methods[candidate_name(bundle.recovery)] = bundle.recovery
    if bundle.r3 is not None and bundle.recovery.method != "r3":
        methods["r3"] = Recovery("r3", None, bundle.recovery.base, bundle.r3, bundle.group_ids)
    cell_rows: list[tuple] = []
    forecast_rows: list[tuple] = []
    mask_rows: list[tuple] = []
    skipped, skipped_cells, issued_days = [], [], []
    conn.execute("BEGIN IMMEDIATE")
    try:
        apply_schema(conn)
        for index, key in enumerate(keys):
            if conn.execute("SELECT 1 FROM daily_cell WHERE date_key = ? LIMIT 1", (key,)).fetchone() is not None:
                continue                                         # already issued: what was issued is never touched
            inputs = block.day(index)
            day = recovered[:, index, first:last + 1] if recovered is not None else recover_day(bundle.recovery, inputs)
            one_day = np.array([key], dtype=np.int32)
            b = {}
            for version, values in (("raw", inputs.sales), ("recovered", day)):
                shaped = CubeView(np.asarray(values, dtype=np.float32)[:, None, :], one_day)
                b[version] = day_factor(shaped, bundle.cf[version], regular_mask(inputs.state[:, None]), position)
                rec = records(shaped, replace(bundle.cf[version], b=b[version], days=one_day), (inputs.state == PROMO)[:, None], position)
                cell_rows.extend(_unit_rows(key, version, rec, inputs, position, bundle.group_ids, n_bands, run.run_key))
            promo = np.flatnonzero(inputs.state == PROMO)
            have = {row[2] for row in cell_rows if row[0] == key and row[1] == "recovered"}
            wanted = {cell_key(int(position[s]) * n_bands + int(inputs.band[s]), bundle.group_ids, n_bands) for s in promo}
            skipped_cells.extend({"date_key": key, "cell_key": missing, "reason": "no_counterfactual"} for missing in sorted(wanted - have))
            previous = [date_key(_day_before(key, k)) for k in range(view.forecast.naive_days, 0, -1)]
            try:
                history = CubeView(np.stack([np.array(cube.sales(k)[:, first:last + 1], dtype=np.float32) for k in previous], axis=1), np.array(previous, dtype=np.int32))
            except KeyError as error:
                raise ScoringError(f"la historia de la regla ingenua del día {key} no está en el cubo: {error}") from error
            try:
                made = forecasts(bundle.cf["recovered"], b["recovered"][:, 0], bundle.lifts["recovered"], inputs, history, view)
            except ForecastError as error:
                raise ScoringError(str(error)) from error
            frame = made.frame
            forecast_rows.extend(zip(frame["series_key"].astype(int).tolist(), frame["date_key"].astype(int).tolist(), frame["method"].tolist(), frame["forecast"].astype(float).tolist(),
                                     frame["observed_instock"].astype(float).tolist(), ["test"] * len(frame), [run.run_key] * len(frame), strict=True))
            skipped.append(made.skipped.assign(date_key=key))
            mask = mask_tail(inputs, bundle.pmf, np.random.default_rng([view.recovery.mask_seed_test, key]))
            for name, rec_method in methods.items():
                estimate, truth = hidden_mass(rec_method, inputs, mask)
                mask_rows.extend((int(s), key, name, int(cut), float(t), float(e), STATE_NAMES[st], run.run_key)
                                 for s, cut, t, e, st in zip(inputs.series_key[mask.rows], mask.cut, truth, estimate, inputs.state[mask.rows], strict=True))
            issued_days.append(key)
        conn.executemany("INSERT INTO daily_cell VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", cell_rows)
        conn.executemany("INSERT INTO forecasts VALUES (?, ?, ?, ?, ?, ?, ?)", forecast_rows)
        conn.executemany("INSERT INTO mask_checks VALUES (?, ?, ?, ?, ?, ?, ?, ?)", mask_rows)
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        logger.warning("estimate %s rolled back: nothing of its days was issued", spec.delivery_id)
        raise
    rows = {"daily_cell": len(cell_rows), "forecasts": len(forecast_rows), "mask_checks": len(mask_rows)}
    logger.info("estimate %s: days %s issued, rows %s", spec.delivery_id, issued_days, rows)
    return DayResult(spec.delivery_id, tuple(keys), bool(issued_days), rows, pd.concat(skipped, ignore_index=True) if skipped else pd.DataFrame(columns=["series_key", "reason", "date_key"]),
                     pd.DataFrame(skipped_cells, columns=["date_key", "cell_key", "reason"]))


def _day_before(key: int, days: int) -> Any:
    from datetime import date

    return date(key // 10_000, key // 100 % 100, key % 100) - timedelta(days=days)


def run_day(conn: sqlite3.Connection, cube: Any, bundle: LaunchBundle, run: RunMeta, spec: DeliverySpec, view: Any, *, interim_dir: Path) -> DayResult:
    """The days of a daily delivery: recover them with the sealed method and issue their effect, forecasts and masks."""
    recovered = recover_delivery(conn, cube, bundle, spec, run, view, interim_dir=interim_dir)
    return estimate_delivery(conn, cube, bundle, spec, run, view, recovered=recovered)


__all__ = ["Counterfactual", "DayResult", "Lifts", "ScoringError", "estimate_delivery", "recover_delivery", "run_day"]
