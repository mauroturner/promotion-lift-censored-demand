"""The recovery of the demand that stock-outs hide (RF09, RF11, D06-D08; plan, section 11).

An hour without stock sells nothing whatever the demand was. Four methods say what it would have sold, from the least to the most they use:

* **R0** zero: the sale as observed, the reference every other method has to beat;
* **R1** the mean sale of the series at that hour, over the days of its state (``promo`` when the day carries the flag, otherwise the days without it) on which it
  had stock; a series with no such day takes the mean over the days of any state, and one with none at all, 0;
* **R2** R1 scaled by the level of the same day: ``k = (O + kappa * m) / (E + kappa * m)`` with O what the hours with stock of the day sold, E what R1 says
  for those hours and m what R1 says for all of them; kappa pulls ``k`` toward 1 when the day has few hours with stock to learn from. A day with no stock at
  all has O = E = 0 and gets R1; a day whose base has no mass gets 0;
* **R3** a ``HistGradientBoostingRegressor`` with a Poisson loss on the hour, the first hour without stock, R1, O, E, m, the flag, the band, the weekday and the
  group, fitted on tail masks of the training block.

Only the hours without stock change: an hour with stock keeps what it sold, and the sale recorded at an hour without stock is never read (AC11). A recovery of
one day reads that day and what was fitted before it, nothing else (``DayInputs`` holds nothing else). Methods are judged on the mass they give back **summed per
series** (the grain the lift sums over), never per hour, where zero cannot be beaten (D07).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from promolift.cube import INPUT_COLUMNS, BlockInputs, DayInputs, build_inputs, group_index
from promolift.days import ANOMALOUS, PROMO
from promolift.masks import Mask, apply, mask_tail, truth

METHODS = ("r0", "r1", "r2", "r3")
TIE_TOLERANCE = 1e-6
_CATEGORICAL = [INPUT_COLUMNS.index("weekday"), INPUT_COLUMNS.index("group")]


@dataclass(frozen=True)
class Recovery:
    """A fitted method: ``base`` is (series, 2, hours): R1 of each series for a day without the flag (0) and with it (1); ``r3`` is R3's model and ``groups``
    the sorted management group ids it was fitted with."""

    method: str
    kappa: float | None
    base: np.ndarray
    r3: Any | None = None
    groups: np.ndarray | None = None


@dataclass(frozen=True)
class Choice:
    """What ``choose`` picked and the WAPE of the mass per series of each candidate (in the order they were given)."""

    name: str
    wape: dict[str, float]


def candidate_name(rec: Recovery) -> str:
    """``r1``, ``r2@<kappa>`` or ``r3``: how a candidate is named in the choice, the tables and the seal."""
    return f"r2@{rec.kappa:g}" if rec.method == "r2" else rec.method


def fit_base(block: BlockInputs, days: np.ndarray | None = None) -> np.ndarray:
    """R1: ``(series, 2, hours)``, the mean sale of the hours with stock of each series by hour and by whether the day carries the flag, over the `days` of the
    block asked for (a bool per day; all of them by default). An anomalous day is not in the fit. Where the state has no hour with stock the mean over both states
    is used, and where there is none either, 0."""
    n_series, n_days, n_hours = block.sales.shape
    chosen = np.ones(n_days, dtype=bool) if days is None else np.asarray(days, dtype=bool)
    total = np.zeros((n_series, 2, n_hours))
    count = np.zeros((n_series, 2, n_hours))
    for day in np.flatnonzero(chosen):
        state = block.state[:, day]
        usable = (block.stock[:, day, :] == 0) & (state != ANOMALOUS)[:, None]
        sold = np.where(usable, block.sales[:, day, :], 0.0)
        flagged = (state == PROMO)[:, None]
        for which, picked in ((1, usable & flagged), (0, usable & ~flagged)):
            total[:, which, :] += np.where(picked, sold, 0.0)
            count[:, which, :] += picked
    pooled_count = count.sum(axis=1)
    pooled = np.divide(total.sum(axis=1), pooled_count, out=np.zeros((n_series, n_hours)), where=pooled_count > 0)
    return np.divide(total, count, out=np.broadcast_to(pooled[:, None, :], total.shape).copy(), where=count > 0)


def _masses(inputs: DayInputs, r1: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """O, E and m of each series-day: what its hours with stock sold, what R1 says for them and what R1 says for every hour."""
    in_stock = inputs.stock == 0
    observed = np.where(in_stock, inputs.sales, 0.0).sum(axis=1, dtype=np.float64)
    return observed, np.where(in_stock, r1, 0.0).sum(axis=1), r1.sum(axis=1)


def _weekday(date_key: int) -> int:
    return date(date_key // 10_000, date_key // 100 % 100, date_key % 100).weekday()


def _r3_frame(inputs: DayInputs, r1: np.ndarray, rows: np.ndarray, groups: np.ndarray) -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    """The features of R3 for every hour without stock of `rows`, checked by ``build_inputs``; and the row and column of each."""
    sub = replace(inputs, series_key=inputs.series_key[rows], sales=inputs.sales[rows], stock=inputs.stock[rows], state=inputs.state[rows],
                  band=inputs.band[rows], group=inputs.group[rows])
    r1_rows = r1[rows]
    observed, expected, total = _masses(sub, r1_rows)
    out_rows, out_cols = np.nonzero(sub.stock == 1)
    first_out = inputs.hours[(sub.stock == 1).argmax(axis=1)]
    frame = pd.DataFrame({
        "hour": inputs.hours[out_cols], "cut": first_out[out_rows], "base": r1_rows[out_rows, out_cols], "observed_mass": observed[out_rows],
        "expected_mass": expected[out_rows], "total_mass": total[out_rows], "promo": (sub.state[out_rows] == PROMO).astype(np.int8),
        "depth": sub.band[out_rows], "weekday": _weekday(inputs.date_key), "group": group_index(sub.group[out_rows], groups)})
    return build_inputs(frame), out_rows, out_cols


def estimate(rec: Recovery, inputs: DayInputs) -> np.ndarray:
    """``(series, hours)``: what the method says every hour of the day would have sold. The sale recorded at an hour without stock is never read; at an hour with
    stock the value is only the method's own and ``recover_day`` replaces it by what was sold."""
    n_series, n_hours = inputs.stock.shape
    if rec.method == "r0":
        return np.zeros((n_series, n_hours))
    r1 = rec.base[inputs.series_key.astype(np.intp), (inputs.state == PROMO).astype(np.intp), :]
    if rec.method == "r1":
        return r1
    if rec.method == "r2":
        observed, expected, total = _masses(inputs, r1)
        denominator = expected + rec.kappa * total
        k = np.divide(observed + rec.kappa * total, denominator, out=np.ones(n_series), where=denominator > 0)
        return r1 * k[:, None]
    if rec.method == "r3":
        out = np.zeros((n_series, n_hours))
        rows = np.flatnonzero((inputs.stock == 1).any(axis=1))
        if len(rows):
            frame, out_rows, out_cols = _r3_frame(inputs, r1, rows, rec.groups)
            out[rows[out_rows], out_cols] = rec.r3.predict(frame.to_numpy(dtype=np.float64))
        return out
    raise ValueError(f"método de recuperación desconocido: {rec.method!r}; se esperaba uno de {', '.join(METHODS)}")


def recover_day(rec: Recovery, inputs: DayInputs) -> np.ndarray:
    """``(series, hours)``: the sale of the day with every hour without stock replaced by what the method estimates for it; the hours with stock come back as they
    were."""
    guess = estimate(rec, inputs)
    return np.where(inputs.stock == 1, guess, inputs.sales)


def hidden_mass(rec: Recovery, inputs: DayInputs, mask: Mask) -> tuple[np.ndarray, np.ndarray]:
    """``(estimate, truth)`` per masked series-day: what the method gives back over the hours the mask hides, recovering the day as it would be seen with the
    hours hidden, and what those hours really sold."""
    seen = apply(inputs, mask)
    part = replace(seen, series_key=seen.series_key[mask.rows], sales=seen.sales[mask.rows], stock=seen.stock[mask.rows], state=seen.state[mask.rows],
                   band=seen.band[mask.rows], group=seen.group[mask.rows])
    recovered = recover_day(rec, part)
    return np.where(mask.hidden, recovered, 0.0).sum(axis=1), truth(inputs, mask).sum(axis=1)


def wape_series(series_key: np.ndarray, estimate: np.ndarray, truth: np.ndarray) -> float:
    """``Σ_s |Σ estimate − Σ truth| / Σ truth``, each sum over the series-days of the series ``s`` (requirements, section 8.1)."""
    _unique, inverse = np.unique(series_key, return_inverse=True)
    gap = np.bincount(inverse, weights=np.asarray(estimate, dtype=np.float64) - np.asarray(truth, dtype=np.float64))
    mass = float(np.asarray(truth, dtype=np.float64).sum())
    if mass <= 0:
        raise ValueError("la masa oculta es 0: no hay con qué calcular el WAPE por serie")
    return float(np.abs(gap).sum() / mass)


def choose(candidates: Mapping[str, np.ndarray], truth: np.ndarray, series_key: np.ndarray, *, tolerance: float = TIE_TOLERANCE) -> Choice:
    """The candidate with the lowest WAPE of the mass per series. `candidates` maps a name to its estimate per masked series-day, in the order of preference:
    a later one replaces an earlier one only if it is better by more than `tolerance` (a tie goes to the simpler method, D08)."""
    if not candidates:
        raise ValueError("no hay ningún candidato entre los que elegir")
    wape = {name: wape_series(series_key, guess, truth) for name, guess in candidates.items()}
    best = None
    for name, value in wape.items():
        if best is None or value < wape[best] - tolerance:
            best = name
    return Choice(best, wape)


def fit_r3(block: BlockInputs, days: np.ndarray, base: np.ndarray, pmf: np.ndarray, view: Any) -> HistGradientBoostingRegressor:
    """R3, fitted on tail masks of the `days` of the block (at most ``r3_train_days`` series-days, drawn at random): the target is what each hidden hour sold."""
    r = view.recovery
    groups = np.unique(block.group)
    rng = np.random.default_rng(r.random_state)
    per_day = []
    for day in np.flatnonzero(np.asarray(days, dtype=bool)):
        inputs = block.day(day)
        mask = mask_tail(inputs, pmf, rng)
        per_day.append((day, mask))
    total = sum(len(mask.rows) for _day, mask in per_day)
    if total == 0:
        raise ValueError("no hay series-días enmascarables en los días de ajuste de R3")
    keep = np.sort(np.random.default_rng([r.random_state, 1]).choice(total, size=min(total, r.r3_train_days), replace=False))
    frames, targets, start = [], [], 0
    for day, mask in per_day:
        picked = keep[(keep >= start) & (keep < start + len(mask.rows))] - start
        start += len(mask.rows)
        if not len(picked):
            continue
        inputs = block.day(day)
        sub = Mask(mask.rows[picked], mask.hidden[picked], mask.cut[picked])
        seen = apply(inputs, sub)
        r1 = base[inputs.series_key.astype(np.intp), (inputs.state == PROMO).astype(np.intp), :]
        frame, out_rows, out_cols = _r3_frame(seen, r1, sub.rows, groups)
        frames.append(frame)
        targets.append(inputs.sales[sub.rows[out_rows], out_cols].astype(np.float64))
    model = HistGradientBoostingRegressor(
        loss="poisson", max_iter=r.r3_max_iter, learning_rate=r.r3_learning_rate, max_leaf_nodes=r.r3_max_leaf_nodes, min_samples_leaf=r.r3_min_samples_leaf,
        early_stopping=False, random_state=r.random_state, categorical_features=_CATEGORICAL)
    return model.fit(pd.concat(frames).to_numpy(dtype=np.float64), np.concatenate(targets))


def candidates(block: BlockInputs, days: np.ndarray, pmf: np.ndarray, view: Any) -> list[Recovery]:
    """The methods of the configuration fitted on the `days` of the block, in the order of preference of the choice: R1, R2 with each kappa from the smallest and
    R3. They share one base."""
    base = fit_base(block, days)
    groups = np.unique(block.group)
    chosen = view.recovery.methods
    out: list[Recovery] = []
    if "r1" in chosen:
        out.append(Recovery("r1", None, base, None, groups))
    if "r2" in chosen:
        out.extend(Recovery("r2", float(kappa), base, None, groups) for kappa in sorted(view.recovery.kappas))
    if "r3" in chosen:
        out.append(Recovery("r3", None, base, fit_r3(block, days, base, pmf, view), groups))
    return out
