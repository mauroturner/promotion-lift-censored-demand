"""The variants of the evaluation (RF18, D04, D12, D16; C10; plan, section 16): what the test says if one assumption is changed, informed and never used to choose.

``run`` is called only inside the evaluation of the test and only after the launch part of the seal is written (``SealError`` otherwise): the variants read the test, so
nothing that chooses (``recovery.choose``, ``effect``, ``ranking``, ``forecast``, ``launch``) may read their table or import this module (a static test reads those
files). Each result is a dict ``variant``, ``unit_key``, ``value``, ``ci_low``, ``ci_high``, ``series`` and ``series_days`` that the seal stores in its test part and
``eval_variants`` holds:

* ``control_any_flag0``: the week's total and band lifts when the control of each day is any day without the flag (regular days and days with a cut and no flag), in the
  two versions, with the sealed ``a`` held (the lift the research computed, +45 % against +61 % on the training block);
* ``series_only_intervals``: the intervals of the cells of the launch and of the week when only series are resampled, and how many pairs of ranked cells overlap, next to
  the two-way ones (the 1.8 times of ``research/plan/p04``);
* ``mcar_mask``: the recovery on three hours hidden at random instead of the tail, on the same series-days (the WAPE of the mass per series and the bias of each method);
* ``unflagged_band``: the lift of the days with a cut and no flag, by band: their own effect, never the control;
* ``first_category_cell``: the lift of the first category by band instead of the management group by band;
* ``per_day_band``: the lift of each day of the week by band.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import numpy as np

from promolift.bootstrap import two_way_draws_many
from promolift.days import UNFLAGGED
from promolift.effect import cell_of
from promolift.evaluation import SEED_OFFSET, VERSIONS, Periods, load_periods, pairs_of, units_of, week_records
from promolift.launch import unit_stats
from promolift.masks import mask_random
from promolift.ranking import rank_cells
from promolift.recovery import Recovery, candidate_name, hidden_mass, wape_series
from promolift.registry import LaunchBundle, SealError, read_seal


def _row(variant: str, unit_key: str, value: float | None, low: float | None = None, high: float | None = None, series: int | None = None, series_days: int | None = None) -> dict[str, Any]:
    def number(x: float | None) -> float | None:
        return None if x is None or not np.isfinite(x) else float(x)

    return {"variant": variant, "unit_key": unit_key, "value": number(value), "ci_low": number(low), "ci_high": number(high), "series": series, "series_days": series_days}


def _stats_rows(variant: str, prefix: str, stats: dict[str, np.ndarray], keys: list[str]) -> list[dict[str, Any]]:
    return [_row(variant, f"{prefix}{key}", stats["lift"][k], stats["low"][k], stats["high"][k], int(stats["series"][k]), int(stats["series_days"][k]))
            for k, key in enumerate(keys) if stats["series_days"][k]]


def _control(periods: Periods, bundle: LaunchBundle, view: Any) -> list[dict[str, Any]]:
    week, rows = periods.week, []
    for version in VERSIONS:
        rec = week_records(week.block, week.position, bundle, week.recovered, version, control="any_flag0")
        units = units_of(rec, week, periods.n_bands, periods.n_groups)
        names = ("overall", "band")
        draws = two_way_draws_many(rec, [units[k] for k in names], view.bootstrap.resamples, view.bootstrap.seed + SEED_OFFSET)
        for name, d in zip(names, draws, strict=True):
            keys = ["all"] if name == "overall" else [f"b{k}" for k in range(periods.n_bands)]
            rows += _stats_rows("control_any_flag0", f"{version}:", unit_stats(rec, units[name][0], units[name][1], d), keys)
    return rows


def _series_only(periods: Periods, view: Any) -> list[dict[str, Any]]:
    rows = []
    for scope, period, seed in (("launch", periods.launch, view.bootstrap.seed), ("test", periods.week, view.bootstrap.seed + SEED_OFFSET)):
        rec = period.rec["recovered"]
        unit_of, n_units = units_of(rec, period, periods.n_bands, periods.n_groups)["cell"]
        stats = unit_stats(rec, unit_of, n_units, two_way_draws_many(rec, [(unit_of, n_units)], view.bootstrap.resamples, seed, days=False)[0])
        found = pairs_of(stats, rank_cells(stats["lift"], stats["low"], stats["high"], stats["series"], view.ranking.min_series))
        rows += [_row("series_only_intervals", f"{scope}:{name}", found[name]) for name in ("cells", "pairs", "overlapping", "median_width")]
    return rows


def _mcar(periods: Periods, bundle: LaunchBundle, view: Any) -> list[dict[str, Any]]:
    week = periods.week
    methods = {"r1": Recovery("r1", None, bundle.recovery.base, None, bundle.group_ids), candidate_name(bundle.recovery): bundle.recovery}
    if bundle.r3 is not None:
        methods.setdefault("r3", Recovery("r3", None, bundle.recovery.base, bundle.r3, bundle.group_ids))
    series, truth, estimates = [], [], {name: [] for name in methods}
    for position, key in enumerate(week.keys.tolist()):
        inputs = week.block.day(position)
        mask = mask_random(inputs, view.recovery.mcar_hours, np.random.default_rng([view.recovery.mask_seed_test, key, 1]))
        series.append(inputs.series_key[mask.rows])
        for name, method in methods.items():
            estimate, true = hidden_mass(method, inputs, mask)
            estimates[name].append(estimate)
        truth.append(true)
    series_key, truth_all = np.concatenate(series), np.concatenate(truth)
    rows = [_row("mcar_mask", "r0:wape", wape_series(series_key, np.zeros(len(truth_all)), truth_all)), _row("mcar_mask", "mask:series_days", float(len(truth_all)))]
    for name, parts in estimates.items():
        estimate = np.concatenate(parts)
        rows += [_row("mcar_mask", f"{name}:wape", wape_series(series_key, estimate, truth_all)), _row("mcar_mask", f"{name}:bias", estimate.sum() / truth_all.sum() - 1.0)]
    return rows


def _unflagged(periods: Periods, bundle: LaunchBundle, view: Any) -> list[dict[str, Any]]:
    week, rows = periods.week, []
    for version in VERSIONS:
        rec = week_records(week.block, week.position, bundle, week.recovered, version, target=UNFLAGGED)
        units = units_of(rec, week, periods.n_bands, periods.n_groups)
        names = ("overall", "band")
        draws = two_way_draws_many(rec, [units[k] for k in names], view.bootstrap.resamples, view.bootstrap.seed + SEED_OFFSET)
        stats = {name: unit_stats(rec, units[name][0], units[name][1], d) for name, d in zip(names, draws, strict=True)}
        rows.append(_row("unflagged_band", f"{version}:all", stats["overall"]["lift"][0], stats["overall"]["low"][0], stats["overall"]["high"][0], int(stats["overall"]["series"][0]),
                         int(stats["overall"]["series_days"][0])))
        rows += _stats_rows("unflagged_band", f"{version}:", stats["band"], [f"b{k}" for k in range(periods.n_bands)])
    return rows


def _first_category(conn: sqlite3.Connection, periods: Periods, view: Any) -> list[dict[str, Any]]:
    week, n_bands = periods.week, periods.n_bands
    category = np.array([r[0] for r in conn.execute("SELECT first_category_id FROM series ORDER BY series_key")], dtype=np.int64)
    ids = np.unique(category)
    position = np.searchsorted(ids, category)
    rec = week.rec["recovered"]
    band = week.block.band[rec.series, rec.day].astype(np.int64)
    unit_of, n_units = cell_of(position[rec.series], band, n_bands), len(ids) * n_bands
    stats = unit_stats(rec, unit_of, n_units, two_way_draws_many(rec, [(unit_of, n_units)], view.bootstrap.resamples, view.bootstrap.seed + SEED_OFFSET)[0])
    keys = [f"fc{int(ids[k // n_bands])}-b{k % n_bands}" for k in range(n_units)]
    return _stats_rows("first_category_cell", "recovered:", stats, keys)


def _per_day_band(periods: Periods) -> list[dict[str, Any]]:
    week, n_bands = periods.week, periods.n_bands
    rec = week.rec["recovered"]
    band = week.block.band[rec.series, rec.day].astype(np.int64)
    unit_of, n_units = rec.day.astype(np.int64) * n_bands + band, len(week.keys) * n_bands
    observed = np.bincount(unit_of, weights=rec.observed, minlength=n_units)
    expected = np.bincount(unit_of, weights=rec.counterfactual, minlength=n_units)
    count = np.bincount(unit_of, minlength=n_units)
    return [_row("per_day_band", f"{int(week.keys[k // n_bands])}:b{k % n_bands}", observed[k] / expected[k] - 1.0 if expected[k] > 0 else None, series_days=int(count[k]))
            for k in range(n_units) if count[k]]


def run(conn: sqlite3.Connection, cube: Any, bundle: LaunchBundle, view: Any, *, seal_path: Path, periods: Periods | None = None) -> list[dict[str, Any]]:
    """The variants of ``[variants]`` for the test (see the module). Only after the launch part of the seal is written; `periods` are the days already read."""
    if read_seal(Path(seal_path)) is None:
        raise SealError("las variantes se calculan después de la parte del lanzamiento del sello, que no está escrita (docs/runbook.md, R7)")
    periods = periods or load_periods(conn, cube, bundle, view)
    v, rows = view.variants, []
    if v.control_any_flag0:
        rows += _control(periods, bundle, view)
    if v.series_only_intervals:
        rows += _series_only(periods, view)
    if v.mcar_mask:
        rows += _mcar(periods, bundle, view)
    rows += _unflagged(periods, bundle, view)
    if v.first_category_cells:
        rows += _first_category(conn, periods, view)
    return rows + _per_day_band(periods)
