"""The evaluation of the test week and its criteria C01 to C10 (RF18, D16, D17, D21; AC22; plan, section 16; requirements, section 8.1).

**It reads what was issued.** The days of the test were issued one by one (``daily_cell``, ``forecasts``, ``mask_checks``; U10); the evaluation of the close reads those
tables for the recovery on the synthetic masks and for the forecasts, and rebuilds the effects of the week from the loaded days with the same functions the daily run
used (``effect.day_factor`` and ``effect.records`` with the sealed ``a``), because the intervals need the series-days and the tables hold only their sums. It then
checks, day by day and version by version, that what it rebuilt adds up to what ``daily_cell`` issued (``EvaluationError`` otherwise): it never makes up a number.

**The intervals.** The week is resampled with the two-way bootstrap (series and days, ``effect.records``), with the seed of the configuration plus one, so that its
draws are independent of the ones the launch published with the seed itself: the replication (C05 and C06) compares the sealed launch, whose draws are rebuilt here
with its own seed, with the week, resampling each one separately and subtracting resample by resample. The recovery (C01) is a bootstrap of series on the mask of the
days (``recovery.score_candidates``) and the forecasts (C08, C09) the two-way bootstrap again, paired between methods.

``figures`` are the numbers the criteria are made of, the ones the seal stores in the ``metrics`` of its test part; ``criteria_of`` rebuilds the criteria from those
figures and the sealed limits alone, so that a sealed result can be published again without the warehouse that made it (``criteria_from_seal``, D21).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

import numpy as np
import pandas as pd

from promolift import texts
from promolift.bootstrap import interval, two_way_draws, two_way_draws_many
from promolift.cube import BlockInputs, group_index, load_block
from promolift.days import PROMO, REGULAR
from promolift.effect import CubeView, Records, cell_key, cell_of, day_factor, records, regular_mask
from promolift.forecast import forecast_errors
from promolift.launch import FIT_BLOCKS_LAUNCH, clean, launch_keys, unit_stats
from promolift.ranking import pair_counts, rank_cells, spearman
from promolift.recovery import MaskedBlock, candidate_name, recover_block, score_candidates
from promolift.registry import LaunchBundle, SealError, sealed_document
from promolift.schema import date_key

VERSIONS = ("raw", "recovered")
SEED_OFFSET = 1             # the week is resampled with seed + 1: its draws are independent of the launch's (see the module)
SUM_TOLERANCE = 1e-6


class EvaluationError(RuntimeError):
    """The test week cannot be evaluated from what the warehouse and the cube hold: a day was not issued, or what the days give is not what was issued."""


# --- the days the evaluation reads, loaded once ----------------------------------------------------------------------------------------------


@dataclass(frozen=True, eq=False)
class Period:
    """A run of days of the cube read for the evaluation: the inputs ``block``, the dense group ``position`` of each series, the days as recovered with the sealed method,
    and the promo records of each version (with the counterfactual the period uses)."""

    keys: np.ndarray
    block: BlockInputs
    position: np.ndarray
    recovered: np.ndarray
    rec: dict[str, Records]


@dataclass(frozen=True, eq=False)
class Periods:
    """The test week and the launch period, as the evaluation and the variants read them."""

    week: Period
    launch: Period
    n_series: int
    n_bands: int
    n_groups: int


def week_keys(cube: Any, view: Any) -> np.ndarray:
    """The days of the test the cube holds, in order; ``EvaluationError`` if it lacks one of the days of the calendar."""
    first, last = date_key(view.calendar.launch_last_day), date_key(view.calendar.last_day)
    held = np.array([k for k in cube.date_keys.tolist() if first < k <= last], dtype=np.int32)
    days = (view.calendar.last_day - view.calendar.launch_last_day).days
    if len(held) != days:
        raise EvaluationError(f"la prueba tiene {days} días y el cubo de las entregas cargadas tiene {len(held)} de ellos: no se evalúa una semana incompleta")
    return held


def week_records(block: BlockInputs, position: np.ndarray, bundle: LaunchBundle, recovered: np.ndarray, version: str, *, control: str = "regular", target: int = PROMO) -> Records:
    """The records of the days of `block` in a version, the way the daily run built them: ``b`` of each day from the control days of that day with the sealed ``a`` held
    fixed (`control` picks which days are the control), the series-days of state `target`."""
    shaped = CubeView(np.asarray(block.sales if version == "raw" else recovered, dtype=np.float32), block.date_keys)
    cf = bundle.cf[version]
    b = day_factor(shaped, cf, regular_mask(block.state, control), position)
    return records(shaped, replace(cf, b=b, days=block.date_keys), block.state == target, position)


def load_periods(conn: sqlite3.Connection, cube: Any, bundle: LaunchBundle, view: Any) -> Periods:
    """Read the test week and the launch period from the cube and the warehouse and recover them with the sealed method."""
    n_bands = len(view.days.bands) - 1
    keys = week_keys(cube, view)
    issued = {int(r[0]) for r in conn.execute("SELECT DISTINCT date_key FROM daily_cell")}
    if issued != set(keys.tolist()):
        missing = sorted(set(keys.tolist()) - issued)
        raise EvaluationError(f"los días de la prueba que se emitieron no son los {len(keys)} de la semana: {'faltan ' + str(missing) if missing else 'sobran ' + str(sorted(issued - set(keys.tolist())))}")
    block = load_block(cube, conn, keys, view)
    position = group_index(block.group, bundle.group_ids)
    recovered = recover_block(bundle.recovery, block, np.arange(len(keys)))
    week = Period(keys, block, position, recovered, {v: week_records(block, position, bundle, recovered, v) for v in VERSIONS})
    lkeys = launch_keys(view)
    lblock = load_block(cube, conn, lkeys, view)
    lposition = group_index(lblock.group, bundle.group_ids)
    lrecovered = recover_block(bundle.recovery, lblock, np.arange(len(lkeys)))
    lrec = records(CubeView(lrecovered, lkeys), bundle.cf["recovered"], lblock.state == PROMO, lposition)
    launch = Period(lkeys, lblock, lposition, lrecovered, {"recovered": lrec})
    return Periods(week, launch, cube.n_series, n_bands, len(bundle.group_ids))


def units_of(rec: Records, period: Period, n_bands: int, n_groups: int) -> dict[str, tuple[np.ndarray, int]]:
    """The units of a period's records, each as ``(unit of every record, how many units)``: the whole, the cells, the bands and the groups."""
    band = period.block.band[rec.series, rec.day].astype(np.int64)
    group = period.position[rec.series].astype(np.int64)
    return {"overall": (np.zeros(len(rec.series), dtype=np.int64), 1), "cell": (cell_of(group, band, n_bands), n_groups * n_bands), "band": (band, n_bands),
            "group": (group, n_groups)}


def _check_against_issued(conn: sqlite3.Connection, periods: Periods) -> None:
    """What the days give is what ``daily_cell`` issued: the sums of every day and version (``EvaluationError`` naming the first that is not)."""
    week = periods.week
    for version in VERSIONS:
        rec = week.rec[version]
        observed = np.bincount(rec.day, weights=rec.observed, minlength=len(week.keys))
        expected = np.bincount(rec.day, weights=rec.counterfactual, minlength=len(week.keys))
        count = np.bincount(rec.day, minlength=len(week.keys))
        issued = {int(r[0]): r[1:] for r in conn.execute("SELECT date_key, observed, counterfactual, series_days FROM daily_cell WHERE version = ? AND cell_key = 'all'", (version,))}
        for position, key in enumerate(week.keys.tolist()):
            row = issued.get(key)
            mine = (float(observed[position]), float(expected[position]), int(count[position]))
            theirs = (0.0, 0.0, 0) if row is None else (float(row[0]), float(row[1]), int(row[2]))
            if mine[2] != theirs[2] or any(abs(a - b) > SUM_TOLERANCE * max(1.0, abs(b)) for a, b in zip(mine[:2], theirs[:2], strict=True)):
                raise EvaluationError(f"lo que dan los días no es lo que se emitió: el {key}, versión {version}, suma {mine[0]!r} observada, {mine[1]!r} contrafactual y {mine[2]} series-días "
                                      f"y daily_cell dice {theirs[0]!r}, {theirs[1]!r} y {theirs[2]}; se evalúa lo emitido y no otra cosa (docs/runbook.md, R7)")


# --- the result --------------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True, eq=False)
class EvaluationResult:
    """The test as it was issued: ``metrics`` (the figures of the criteria), ``recovery`` (a row per method on the mask of the days), ``effects`` (by version: the stats of
    the whole, the cells, the bands and the groups, and the ranking of the cells), ``replication`` (a row per cell), ``forecast``, ``days`` and ``pairs`` (the cells
    ranked and the pairs whose intervals overlap, for the launch and for the test with the two-way intervals)."""

    metrics: dict[str, Any]
    recovery: list[dict[str, Any]]
    effects: dict[str, dict[str, Any]]
    replication: list[dict[str, Any]]
    forecast: dict[str, Any]
    days: list[dict[str, Any]]
    pairs: dict[str, dict[str, Any]]
    group_ids: np.ndarray
    n_bands: int
    sealed_method: str


def _num(value: Any) -> float | None:
    return None if value is None or not np.isfinite(value) else float(value)


def _spearman(x: np.ndarray, y: np.ndarray) -> float | None:
    return _num(spearman(x, y)) if len(x) >= 2 else None


def recovery_rows(conn: sqlite3.Connection, bundle: LaunchBundle, view: Any) -> tuple[list[dict[str, Any]], str]:
    """One row per method on the synthetic tail masks of the test days as they were issued (``mask_checks``): R0 (zero) and each method that was stored; the sealed
    method's name is the second value. The WAPE of the mass per series, the bias, the bias by day state and the interval of series of the difference with R1."""
    stored = pd.DataFrame(conn.execute("SELECT series_key, date_key, method, cut_hour, hidden_mass, estimate, day_state FROM mask_checks ORDER BY method, date_key, series_key").fetchall(),
                          columns=["series_key", "date_key", "method", "cut_hour", "truth", "estimate", "state"])
    sealed = candidate_name(bundle.recovery)
    if stored.empty or "r1" not in set(stored["method"]):
        return [], sealed
    base = stored[stored["method"] == "r1"]
    last_hour = view.calendar.day_hours[1]
    masked = MaskedBlock([], base["series_key"].to_numpy(), base["date_key"].to_numpy(), np.where(base["state"] == "promo", PROMO, REGULAR).astype(np.int8),
                         base["truth"].to_numpy(dtype=np.float64), int((last_hour - base["cut_hour"] + 1).sum()))
    estimates: dict[str, np.ndarray] = {"r0": np.zeros(len(base))}
    for name in dict.fromkeys(["r1", sealed, "r3"]):
        part = stored[stored["method"] == name]
        if len(part):
            if not (part["series_key"].to_numpy() == base["series_key"].to_numpy()).all() or not (part["date_key"].to_numpy() == base["date_key"].to_numpy()).all():
                raise EvaluationError(f"mask_checks no tiene las mismas series-días para el método {name} que para r1")
            estimates[name] = part["estimate"].to_numpy(dtype=np.float64)
    rows = score_candidates(estimates, masked, resamples=view.bootstrap.recovery_resamples, seed=view.bootstrap.seed)
    return [{**row, "chosen": row["method"] == sealed} for row in rows], sealed


def _forecast_part(conn: sqlite3.Connection, periods: Periods, view: Any) -> dict[str, Any]:
    frame = pd.read_sql_query("SELECT series_key, date_key, method, forecast, observed_instock FROM forecasts WHERE scope = 'test' ORDER BY method, date_key, series_key", conn)
    if frame.empty:
        return {}
    errors = forecast_errors(frame).set_index("method")
    keys = periods.week.keys
    day_of = np.searchsorted(keys, frame["date_key"].to_numpy())
    draws = {}
    for method in errors.index:
        part = frame["method"].to_numpy() == method
        sub = frame[part]
        pseudo = Records(sub["series_key"].to_numpy().astype(np.intp), day_of[part], (sub["forecast"] - sub["observed_instock"]).abs().to_numpy(), sub["observed_instock"].to_numpy(),
                         periods.n_series, len(keys), 0)
        draws[method] = two_way_draws(pseudo, np.zeros(len(sub), dtype=np.int64), 1, view.bootstrap.resamples, view.bootstrap.seed + SEED_OFFSET)[:, 0]
    out: dict[str, Any] = {"series_days": int(errors.loc["f2_cell_lift", "rows"]) if "f2_cell_lift" in errors.index else 0,
                           "methods": {m: {"wape": float(errors.loc[m, "wape"]), "bias": float(errors.loc[m, "bias"]), "rows": int(errors.loc[m, "rows"])} for m in errors.index}}
    for name, (left, right) in {"f2_minus_f2a": ("f2_cell_lift", "f2a_overall_lift"), "f2_minus_f1": ("f2_cell_lift", "f1_naive"), "f2_minus_f0": ("f2_cell_lift", "f0_no_lift")}.items():
        if left in draws and right in draws:
            low, high = interval((draws[left] - draws[right])[:, None])
            out[name] = {"value": float(errors.loc[left, "wape"] - errors.loc[right, "wape"]), "ci_low": float(low[0]), "ci_high": float(high[0])}
    return out


def _median_width(stats: Mapping[str, np.ndarray], ranked: list[int]) -> float | None:
    return _num(np.median(stats["high"][ranked] - stats["low"][ranked])) if ranked else None


def pairs_of(stats: Mapping[str, np.ndarray], ranking: pd.DataFrame) -> dict[str, Any]:
    """The ranked cells, the pairs they form, how many overlap and the median width of their intervals."""
    ranked = [int(i) for i in np.flatnonzero(ranking["ranked"].to_numpy())]
    pairs, overlapping = pair_counts(stats["low"], stats["high"], ranked)
    return {"cells": len(ranked), "pairs": pairs, "overlapping": overlapping, "median_width": _median_width(stats, ranked)}


def evaluate_test(conn: sqlite3.Connection, cube: Any, bundle: LaunchBundle, view: Any, *, periods: Periods | None = None) -> EvaluationResult:
    """The evaluation of the test week from what the warehouse issued (see the module). `periods` are the days already read, if the caller has them."""
    periods = periods or load_periods(conn, cube, bundle, view)
    _check_against_issued(conn, periods)
    week, n_bands, n_groups = periods.week, periods.n_bands, periods.n_groups
    n_cells, min_series = n_groups * n_bands, view.ranking.min_series
    seed, resamples = view.bootstrap.seed + SEED_OFFSET, view.bootstrap.resamples
    group_ids = bundle.group_ids

    recovery, sealed = recovery_rows(conn, bundle, view)
    effects: dict[str, dict[str, Any]] = {}
    draws: dict[str, list[np.ndarray]] = {}
    for version in VERSIONS:
        rec = week.rec[version]
        units = units_of(rec, week, n_bands, n_groups)
        draws[version] = two_way_draws_many(rec, [units[k] for k in ("overall", "cell", "band", "group")], resamples, seed)
        stats = {name: unit_stats(rec, units[name][0], units[name][1], d) for name, d in zip(("overall", "cell", "band", "group"), draws[version], strict=True)}
        cells = stats["cell"]
        stats["ranking"] = rank_cells(cells["lift"], cells["low"], cells["high"], cells["series"], min_series)
        effects[version] = stats
    low, high = interval((draws["recovered"][0] - draws["raw"][0]))
    overall = {v: {"lift": _num(effects[v]["overall"]["lift"][0]), "ci_low": _num(effects[v]["overall"]["low"][0]), "ci_high": _num(effects[v]["overall"]["high"][0])} for v in VERSIONS}
    difference = {"value": _num(effects["recovered"]["overall"]["lift"][0] - effects["raw"]["overall"]["lift"][0]), "ci_low": _num(low[0]), "ci_high": _num(high[0])}
    effect_figures = {**overall, "difference": difference, "series_days": int(effects["recovered"]["overall"]["series_days"][0])}

    # the replication: the sealed launch (its draws, rebuilt with the seed it used) against the week (its own, independent draws)
    lrec = periods.launch.rec["recovered"]
    lunits = units_of(lrec, periods.launch, n_bands, n_groups)
    ldraws = two_way_draws_many(lrec, [lunits["cell"]], resamples, view.bootstrap.seed)[0]
    lcells = unit_stats(lrec, lunits["cell"][0], n_cells, ldraws)
    if not np.allclose(lcells["lift"], bundle.lifts["recovered"].cell, rtol=1e-6, atol=1e-9, equal_nan=True):
        raise SealError("el lanzamiento que se reconstruye con el artefacto no da los aumentos que el sello guardó; no se compara la prueba con él (docs/runbook.md, R6)")
    tcells, tdraws = effects["recovered"]["cell"], draws["recovered"][1]
    both = (lcells["series"] >= min_series) & (tcells["series"] >= min_series) & np.isfinite(lcells["lift"]) & np.isfinite(tcells["lift"])
    diff_low, diff_high = interval(tdraws[:, both] - ldraws[:, both]) if both.any() else (np.array([]), np.array([]))
    at = {int(k): i for i, k in enumerate(np.flatnonzero(both))}
    replication = []
    for k in range(n_cells):
        if not (lcells["series_days"][k] or tcells["series_days"][k]):
            continue
        has = k in at
        replication.append({
            "cell": cell_key(k, group_ids, n_bands), "series_launch": int(lcells["series"][k]), "series_test": int(tcells["series"][k]),
            "lift_launch": _num(lcells["lift"][k]), "ci_low_launch": _num(lcells["low"][k]), "ci_high_launch": _num(lcells["high"][k]),
            "lift_test": _num(tcells["lift"][k]), "ci_low_test": _num(tcells["low"][k]), "ci_high_test": _num(tcells["high"][k]),
            "diff_ci_low": _num(diff_low[at[k]]) if has else None, "diff_ci_high": _num(diff_high[at[k]]) if has else None,
            "consistent": bool(diff_low[at[k]] <= 0 <= diff_high[at[k]]) if has else None})
    bands = effects["recovered"]["band"]["lift"]
    finite = np.isfinite(bands)
    replication_figures = {"cells": int(both.sum()), "spearman": _spearman(lcells["lift"][both], tcells["lift"][both]),
                           "share_consistent": float(((diff_low <= 0) & (diff_high >= 0)).mean()) if both.any() else None,
                           "spearman_depth": _spearman(-np.arange(n_bands)[finite], bands[finite])}

    forecast = _forecast_part(conn, periods, view)
    chosen = next((r for r in recovery if r["method"] == sealed), None)
    r1 = next((r for r in recovery if r["method"] == "r1"), None)
    recovery_figures = None if chosen is None or r1 is None else {
        "method": sealed, "wape": chosen["wape_series"], "wape_r1": r1["wape_series"], "ci_low": chosen["ci_low_vs_r1"], "ci_high": chosen["ci_high_vs_r1"], "bias": chosen["bias"],
        "bias_promo": chosen["bias_promo"], "bias_regular": chosen["bias_regular"], "lift_bias": chosen["lift_bias"], "series": chosen["series"], "masked_days": chosen["masked_days"]}
    metrics = clean({"recovery": recovery_figures, "effect": effect_figures, "replication": replication_figures, "forecast": forecast or None})
    days = []
    for row in conn.execute("SELECT date_key, version, observed, counterfactual, lift, series_days, stockout_hours FROM daily_cell WHERE cell_key = 'all' ORDER BY date_key, version"):
        if not days or days[-1]["date_key"] != row[0]:
            days.append({"date_key": int(row[0])})
        days[-1].update({f"lift_{row[1]}": _num(row[4]), "series_days": int(row[5]), "stockout_hours": int(row[6])})
    pairs = {"launch": pairs_of(lcells, rank_cells(lcells["lift"], lcells["low"], lcells["high"], lcells["series"], min_series)), "test": pairs_of(tcells, effects["recovered"]["ranking"])}
    return EvaluationResult(metrics, recovery, effects, replication, forecast, days, pairs, group_ids, n_bands, sealed)


def figures(result: EvaluationResult, variants: int = 0) -> dict[str, Any]:
    """The numbers the criteria are made of, as the seal stores them in ``metrics`` (JSON-ready; ``None`` for what could not be computed), with how many variant
    figures were written and how many days the week has (what C10 says)."""
    return {**result.metrics, "variants": int(variants), "days": len(result.days)}


# --- the criteria (requirements.md, 8.1) --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Criterion:
    criterion_id: str
    name_es: str
    value: float | None
    baseline_value: float | None
    ci_low: float | None
    ci_high: float | None
    threshold_es: str
    passed: bool | None
    seen_by_research: str
    seen_by_planner: str
    verdict_es: str

    def seal_entry(self) -> dict[str, Any]:
        return {"id": self.criterion_id, "value": self.value, "baseline_value": self.baseline_value, "ci_low": self.ci_low, "ci_high": self.ci_high, "passed": self.passed,
                "verdict_es": self.verdict_es}


def _criterion(cid: str, thresholds: Mapping[str, str], value, baseline, passed: bool | None, verdict: str, ci=(None, None)) -> Criterion:
    text = texts.CRITERIA[cid]
    return Criterion(cid, text.name_es, value, baseline, ci[0], ci[1], thresholds[cid], passed, text.seen_by_research, text.seen_by_planner, verdict)


def _all(*values: Any) -> bool:
    return all(v is not None for v in values)


def criteria_of(figs: Mapping[str, Any], criteria_document: Mapping[str, Any]) -> list[Criterion]:
    """C01 to C10 from the figures of the test (``figures``) and the sealed limits of ``[criteria]``: nothing else, so the same function rebuilds a sealed criterion from
    the seal (``criteria_from_seal``). A criterion that cannot be computed is never passed; a tie never beats; a limit that is reached passes where the criterion says
    «at most» or «at least»."""
    thresholds = texts.thresholds_from(criteria_document)
    out: list[Criterion] = []

    def cannot(cid: str, why: str) -> None:
        out.append(_criterion(cid, thresholds, None, None, False, texts.cannot(why)))

    rec = figs.get("recovery") or {}
    if not _all(rec.get("wape"), rec.get("wape_r1"), rec.get("ci_low"), rec.get("ci_high")):
        cannot("C01", "la prueba no tiene máscaras de cola emitidas para comparar la recuperación con R1")
    else:
        ok = rec["ci_high"] < 0
        out.append(_criterion("C01", thresholds, rec["wape"], rec["wape_r1"], ok, texts.verdict("C01", ok, method=rec["method"], a=rec["wape"], b=rec["wape_r1"], low=rec["ci_low"], high=rec["ci_high"]),
                              (rec["ci_low"], rec["ci_high"])))
    if rec.get("bias") is None:
        cannot("C02", "la prueba no tiene máscaras de cola emitidas")
    else:
        limit = criteria_document["c02_max_abs_bias"]
        ok = abs(rec["bias"]) <= limit
        out.append(_criterion("C02", thresholds, rec["bias"], None, ok, texts.verdict("C02", ok, bias=rec["bias"], limit=limit)))
    if rec.get("lift_bias") is None:
        cannot("C03", "falta el sesgo de la recuperación en los días con promoción o en los regulares")
    else:
        limit = criteria_document["c03_max_abs_lift_bias"]
        ok = abs(rec["lift_bias"]) <= limit
        out.append(_criterion("C03", thresholds, rec["lift_bias"], None, ok, texts.verdict("C03", ok, lift_bias=rec["lift_bias"], limit=limit)))
    eff = figs.get("effect") or {}
    diff = eff.get("difference") or {}
    if not _all(diff.get("value"), diff.get("ci_low"), diff.get("ci_high"), (eff.get("raw") or {}).get("lift"), (eff.get("recovered") or {}).get("lift")):
        cannot("C04", "la prueba no tiene el aumento total en las dos versiones")
    else:
        ok = diff["ci_low"] > 0
        out.append(_criterion("C04", thresholds, eff["recovered"]["lift"], eff["raw"]["lift"], ok,
                              texts.verdict("C04", ok, a=eff["recovered"]["lift"], b=eff["raw"]["lift"], low=diff["ci_low"], high=diff["ci_high"]), (diff["ci_low"], diff["ci_high"])))
    rep = figs.get("replication") or {}
    if rep.get("spearman") is None:
        cannot("C05", "hay menos de dos celdas con series suficientes en el lanzamiento y en la prueba")
    else:
        limit = criteria_document["c05_min_spearman"]
        ok = rep["spearman"] >= limit
        out.append(_criterion("C05", thresholds, rep["spearman"], None, ok, texts.verdict("C05", ok, value=rep["spearman"], cells=rep["cells"], limit=limit)))
    if rep.get("share_consistent") is None:
        cannot("C06", "no hay celdas con series suficientes en el lanzamiento y en la prueba")
    else:
        limit = criteria_document["c06_min_consistent_share"]
        ok = rep["share_consistent"] >= limit
        out.append(_criterion("C06", thresholds, rep["share_consistent"], None, ok, texts.verdict("C06", ok, value=rep["share_consistent"], cells=rep["cells"], limit=limit)))
    if rep.get("spearman_depth") is None:
        cannot("C07", "la prueba tiene menos de dos bandas con aumento")
    else:
        limit = criteria_document["c07_min_spearman"]
        ok = rep["spearman_depth"] >= limit
        out.append(_criterion("C07", thresholds, rep["spearman_depth"], None, ok, texts.verdict("C07", ok, value=rep["spearman_depth"], limit=limit)))
    fc = figs.get("forecast") or {}
    methods = fc.get("methods") or {}
    for cid, key, other in (("C08", "f2_minus_f2a", "f2a_overall_lift"), ("C09", "f2_minus_f1", "f1_naive")):
        d = fc.get(key) or {}
        if not _all(d.get("ci_high"), (methods.get("f2_cell_lift") or {}).get("wape"), (methods.get(other) or {}).get("wape")):
            cannot(cid, "la prueba no tiene pronósticos emitidos de los dos métodos que se comparan")
            continue
        a, b = methods["f2_cell_lift"]["wape"], methods[other]["wape"]
        ok = d["ci_high"] < 0
        out.append(_criterion(cid, thresholds, a, b, ok, texts.verdict(cid, ok, a=a, b=b, low=d["ci_low"], high=d["ci_high"]), (d["ci_low"], d["ci_high"])))
    out.append(_criterion("C10", thresholds, None, None, None, texts.informative_verdict(int(figs.get("variants", 0)), int(figs.get("days", 0)))))
    return out


def evaluate_criteria(result: EvaluationResult, view: Any, variants: int = 0) -> list[Criterion]:
    """The criteria of an evaluation: ``criteria_of`` its figures and the sealed ``[criteria]`` of `view`; `variants` is how many variant figures were written."""
    return criteria_of(figures(result, variants), sealed_document(view)["criteria"])


def _rounded(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, Mapping):
        return {k: _rounded(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_rounded(v) for v in value]
    return value


def criteria_from_seal(seal: Mapping[str, Any]) -> list[Criterion]:
    """C01 to C10 rebuilt from the test part of the seal with ``criteria_of``; each must give back its own entry of the seal to 6 decimals, or the seal is not taken
    (``SealError``): a seal that the code no longer knows how to rebuild is never published (D21)."""
    test, launch = seal.get("test"), seal.get("launch")
    if not test or not launch:
        raise SealError("el sello no tiene la parte de la prueba: no hay criterios sellados")
    rebuilt = criteria_of(test["metrics"], launch["sealed_config"]["criteria"])
    sealed = {entry["id"]: entry for entry in test["criteria"]}
    for criterion in rebuilt:
        if _rounded(criterion.seal_entry()) != _rounded(sealed.get(criterion.criterion_id)):
            raise SealError(f"el criterio {criterion.criterion_id} del sello no se reconstruye desde sus cifras: lo sellado no se toma (docs/runbook.md, R7)")
    return rebuilt


__all__ = ["Criterion", "EvaluationError", "EvaluationResult", "FIT_BLOCKS_LAUNCH", "Period", "Periods", "criteria_from_seal", "criteria_of", "evaluate_criteria", "evaluate_test",
           "figures", "load_periods", "pairs_of", "recovery_rows", "units_of", "week_keys", "week_records"]
