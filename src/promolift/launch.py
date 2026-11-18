"""The ``fit_model`` task: the launch freezes the model, and every later run checks that it is still the frozen one (RF11, RF16, D08, D17, D20, D21; M01, M03, M05,
M06; plan, sections 3 and 15).

At the **launch** (the first run: the registry has no model), with the 90 days of the launch loaded and nothing else (a day of the test in the cube refuses it):

1. the blocks are checked (M06) and the synthetic masks of V1 and V2 are drawn;
2. R1, R2 (each kappa) and R3 are **fitted on the training block** and scored on the V1 mask by the WAPE of the mass per series; the lowest wins, a tie goes to the
   simpler (D08); the trap M01 stops the launch if the winner is more than twice as good as the plain mean (D19), before anything is written;
3. V2 previews the same methods and chooses nothing; every figure of V1, V2, the replication and the forecasts carries ``fit_blocks = train`` (D21);
4. the replication (``a`` of the training block, the day factor of each validation day) and the forecasts of the validation are computed with the method fitted on the
   training block alone;
5. the method is **fitted again with the 90 days** (the same kappa), the period is recovered and the counterfactual of the two versions is fitted, and the published
   effects (total, cells, bands, groups, unflagged bands, the naive account) are estimated with their two-way intervals and the ranking;
6. the artifact (``launch.npz``, and ``r3.pkl`` for R3), the registry row, the rows of the validation and of the effects and the launch part of the seal are written, the
   seal's outcome having been decided first: the same configuration with other values stops here (``SealMismatchError``), another configuration is ``post_seal``.

In **every other run** nothing is fitted: the model is loaded through the registry only if the artifact has the registered SHA-256 (M03), and the state of the seal is
read (M05). ``fit_model`` takes the warehouse, the run and the configuration instead of the pipeline's context (U16 wraps it in the task).
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import timedelta
from typing import Any

import numpy as np
import pandas as pd

from promolift.bootstrap import interval, two_way_draws, two_way_draws_many
from promolift.cube import BlockInputs, group_index, load_block, open_loaded_cube, store_recovered
from promolift.deliveries import delivery_plan
from promolift.days import PROMO, REGULAR, UNFLAGGED
from promolift.effect import (
    CubeView,
    Lifts,
    Records,
    cell_key,
    cell_of,
    day_factor,
    fit_ipf,
    lifts,
    naive_pooled,
    records,
    regular_mask,
)
from promolift.forecast import forecast_errors, forecasts
from promolift.leakage_demo import leakage_table, leaky_hidden_mass
from promolift.masks import first_stockout_pmf
from promolift.ranking import overlapping_pairs, rank_cells, spearman
from promolift.recovery import (
    MaskedBlock,
    Recovery,
    candidate_name,
    candidates,
    choose,
    fit_r3,
    mask_block,
    masked_estimate,
    recover_block,
    refit,
    score_candidates,
    wape_series,
)
from promolift.registry import (
    ARTIFACT_NAME,
    MODEL_VERSION,
    R3_NAME,
    LaunchBundle,
    RunMeta,
    SealError,
    _rounded,
    artifact_digests,
    canonical_sha256,
    config_fingerprint,
    launch_seal_outcome,
    load_artifact,
    read_registry,
    register_model,
    save_artifact,
    seal_state,
    sealed_document,
    sealed_view,
    write_launch_seal,
)
from promolift.schema import date_key
from promolift.split import block_of, check_split
from promolift.validate import RuleResult, model_result
from promolift.warehouse import apply_schema, set_recovered_sums

logger = logging.getLogger(__name__)

FIT_BLOCKS_LAUNCH = "train+purge+valid_v1+valid_v2"
FIT_BLOCKS_VALID = "train"
VERSIONS = ("raw", "recovered")
FORECAST_PAIRS = (("f2_cell_lift", "f0_no_lift"), ("f2_cell_lift", "f2a_overall_lift"), ("f2_cell_lift", "f1_naive"))


class LaunchError(RuntimeError):
    """The launch cannot run with what the warehouse and the cube hold (nothing was written)."""


class LeakTripwireError(LaunchError):
    """M01: the method chosen in V1 is suspiciously good (D19): a possible leak of the target; the launch stops before writing anything (runbook R5)."""


class BlockSizeError(LaunchError):
    """M06: V1 or V2 has too few series-days to mask, or a block lacks promo or regular days (nothing was fitted or written)."""


@dataclass(frozen=True)
class LaunchResult:
    """What the task reports. ``recovery`` names the method chosen and its figures; ``rules`` are the results of the model rules (M01 to M06, I03, I04);
    ``rows`` how many rows of each table were issued; ``leakage`` the demonstration of the leak and ``document`` the launch part of the seal."""

    mode: str
    seal: str
    model_version: str
    config_sha256: str
    artifact_sha256: str
    r3_sha256: str | None
    recovery: dict[str, Any]
    rules: list[RuleResult]
    rows: dict[str, int]
    leakage: pd.DataFrame | None = None
    document: dict[str, Any] | None = None
    bundle: LaunchBundle | None = None


def _stamp(value: Any) -> str:
    return pd.Timestamp(value).strftime("%Y-%m-%d %H:%M:%S")


def _clean(value: Any) -> Any:
    """JSON-ready: NaN and infinities are None, numpy numbers are Python ones."""
    if isinstance(value, Mapping):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, np.ndarray):
        return [_clean(v) for v in value.tolist()]
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, (np.floating, float)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, (np.integer, int)) and not isinstance(value, bool):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def fit_model(cfg: Any, conn: sqlite3.Connection, run: RunMeta, *, train_sha256: str, eval_sha256: str,
              extra_candidates: Mapping[str, Callable[..., np.ndarray]] | None = None) -> LaunchResult:
    """The task of the launch and of the runs after it (see the module). `extra_candidates` maps a name to a function ``(inputs, mask, cube)`` that returns
    the hidden mass it estimates for each masked series-day: a control that competes with the methods in V1 so that a test can show the trap stop it."""
    view = sealed_view(cfg, train_sha256, eval_sha256)
    existing = read_registry(conn, MODEL_VERSION)
    if existing is not None:
        return _verify(cfg, view, existing)
    return _launch(cfg, conn, run, view, dict(extra_candidates or {}))


def _verify(cfg: Any, view: Any, row: Mapping[str, Any]) -> LaunchResult:
    bundle = load_artifact(cfg.paths.models_dir, row)
    config_sha256 = config_fingerprint(view)
    state = seal_state(cfg.paths.seal, config_sha256)
    if state == "none":
        raise SealError("no hay sello: el lanzamiento lo escribe y esta corrida no es el lanzamiento (docs/runbook.md, R7)")
    recovery = json.loads(row["recovery_json"])
    rules = [model_result("M03", passed=True), model_result("M05", passed=state == "match")]
    logger.info("fit_model: model %s verified, artifact %s, seal %s", row["model_version"], row["artifact_sha256"][:12], state)
    return LaunchResult("verify", state, row["model_version"], config_sha256, row["artifact_sha256"], row["r3_sha256"], recovery, rules, {}, None, None, bundle)


def _launch_keys(view: Any) -> np.ndarray:
    first, last = view.calendar.first_day, view.calendar.launch_last_day
    return np.array([date_key(first + timedelta(days=k)) for k in range((last - first).days + 1)], dtype=np.int32)


def _unit_series(rec: Records, unit_of: np.ndarray, n_units: int) -> np.ndarray:
    """How many distinct series each unit has."""
    keep = np.asarray(unit_of) >= 0
    pair = np.unique(np.asarray(unit_of)[keep].astype(np.int64) * rec.n_series + rec.series[keep])
    return np.bincount(pair // rec.n_series, minlength=n_units)


def _unit(rec: Records, unit_of: np.ndarray, n_units: int, draws: np.ndarray) -> dict[str, np.ndarray]:
    """What a family of units reports: lift, interval, sums, series and series-days."""
    keep = np.asarray(unit_of) >= 0
    low, high = interval(draws)
    return {"lift": lifts(rec, unit_of, n_units), "low": low, "high": high, "series": _unit_series(rec, unit_of, n_units),
            "observed": np.bincount(np.asarray(unit_of)[keep], weights=rec.observed[keep], minlength=n_units),
            "counterfactual": np.bincount(np.asarray(unit_of)[keep], weights=rec.counterfactual[keep], minlength=n_units),
            "series_days": np.bincount(np.asarray(unit_of)[keep], minlength=n_units)}


def _effect_row(scope: str, version: str, unit: str, key: str, fit_blocks: str, stats: dict[str, np.ndarray], at: int, ranking: pd.DataFrame | None = None) -> tuple:
    """A row of ``effect_estimates`` for the unit at position `at` of a family (a unit with no records has no lift: NaN is NULL)."""
    def number(x: float) -> float | None:
        return float(x) if np.isfinite(x) else None

    ranked = int(bool(ranking["ranked"].iloc[at])) if ranking is not None else 0
    tier = None if ranking is None or pd.isna(ranking["tier"].iloc[at]) else int(ranking["tier"].iloc[at])
    return (scope, version, unit, key, "regular", fit_blocks, number(stats["observed"][at]), number(stats["counterfactual"][at]), number(stats["lift"][at]),
            number(stats["low"][at]), number(stats["high"][at]), "two_way", int(stats["series"][at]), int(stats["series_days"][at]), ranked, tier)


def _grid_edge(chosen: Recovery, kappas: tuple[float, ...]) -> str | None:
    if chosen.method != "r2":
        return None
    ordered = sorted(kappas)
    return "lower" if chosen.kappa == ordered[0] else "upper" if chosen.kappa == ordered[-1] else None


def _check_block_states(block: BlockInputs, selections: Mapping[str, np.ndarray]) -> None:
    for name, chosen in selections.items():
        state = block.state[:, chosen]
        if not (state == PROMO).any() or not (state == REGULAR).any():
            raise BlockSizeError(f"M06: el bloque {name} no tiene a la vez días promo y regulares ({int((state == PROMO).sum())} y {int((state == REGULAR).sum())} series-días): "
                                 "no hay con qué estimar un efecto (docs/runbook.md, R5)")


def _check_masked(name: str, masked: MaskedBlock, minimum: int) -> None:
    if len(masked.truth) < minimum:
        raise BlockSizeError(f"M06: el bloque {name} tiene {len(masked.truth)} series-días enmascarables, menos de los {minimum} que pide [split] min_masked_days: "
                             "el error de la recuperación no se puede juzgar con tan pocos (docs/runbook.md, R5)")


def _launch(cfg: Any, conn: sqlite3.Connection, run: RunMeta, view: Any, extras: dict[str, Callable[..., np.ndarray]]) -> LaunchResult:
    check_split(view)
    r, naive_days, n_bands = view.recovery, view.forecast.naive_days, len(view.days.bands) - 1
    keys = _launch_keys(view)
    cube = open_loaded_cube(cfg.paths.interim_dir)
    held = cube.date_keys.tolist()
    later = [k for k in held if k > int(keys[-1])]
    if later:
        raise LaunchError(f"el lanzamiento se ajusta con los {len(keys)} días de su entrega y nada más, y el cubo ya tiene el día {later[0]} de la prueba: "
                          "ninguno se lee, pero el modelo no se congela después de ellos (docs/runbook.md, R5)")
    if not set(keys.tolist()) <= set(held):
        raise LaunchError(f"el cubo no tiene los {len(keys)} días del lanzamiento (le falta el {sorted(set(keys.tolist()) - set(held))[0]}); no se ajusta (docs/runbook.md, R5)")
    days = pd.DatetimeIndex([pd.Timestamp(year=int(k) // 10_000, month=int(k) // 100 % 100, day=int(k) % 100) for k in keys])
    block_names = block_of(days, view).to_numpy()
    in_train, in_v1, in_v2 = (block_names == name for name in ("train", "valid_v1", "valid_v2"))
    train_idx, v1_idx, v2_idx = (np.flatnonzero(m) for m in (in_train, in_v1, in_v2))
    valid_idx = np.flatnonzero(in_v1 | in_v2)
    block = load_block(cube, conn, keys, view)
    _check_block_states(block, {"train": in_train, "valid_v1": in_v1, "valid_v2": in_v2})
    group_ids = np.unique(block.group)
    gpos = group_index(block.group, group_ids)
    n_groups, n_cells = len(group_ids), len(group_ids) * n_bands
    pmf = first_stockout_pmf(block.stock, in_train)
    v1 = mask_block(block, v1_idx, pmf, r.mask_seed_v1)
    _check_masked("valid_v1", v1, view.split.min_masked_days)
    v2 = mask_block(block, v2_idx, pmf, r.mask_seed_v2)
    _check_masked("valid_v2", v2, view.split.min_masked_days)

    # --- the choice, in V1, with the methods fitted on the training block (D08) ---
    recs = candidates(block, in_train, pmf, view)
    names = [candidate_name(rec) for rec in recs]
    reference = next((rec for rec in recs if rec.method == "r1"), Recovery("r1", None, recs[0].base, None, group_ids))
    zero = Recovery("r0", None, reference.base, None, group_ids)
    estimates_v1 = {"r0": masked_estimate(zero, v1), "r1": masked_estimate(reference, v1)}
    estimates_v1.update({name: masked_estimate(rec, v1) for name, rec in zip(names, recs, strict=True) if name != "r1"})
    contenders = {name: estimates_v1[name] for name in names}
    for name, control in extras.items():
        contenders[name] = np.concatenate([np.asarray(control(inputs, mask, cube), dtype=np.float64) for inputs, mask in v1.parts])
    choice = choose(contenders, v1.truth, v1.series_key)
    r1_wape = wape_series(v1.series_key, estimates_v1["r1"], v1.truth)
    if choice.wape[choice.name] < r.leak_tripwire_ratio * r1_wape:
        raise LeakTripwireError(
            f"M01: posible fuga: el método {choice.name!r} da en V1 un WAPE por serie de {choice.wape[choice.name]:.4f}, menos de {r.leak_tripwire_ratio:g} veces el de "
            f"la media simple ({r1_wape:.4f}); una mejora real sobre ella ronda 0,85 veces (D19). El lanzamiento se detuvo y no escribió nada (docs/runbook.md, R5)")
    if choice.name not in names:
        raise LaunchError(f"el candidato {choice.name!r} no es un método del lanzamiento: un control extra solo sirve para probar la trampa M01")
    chosen = recs[names.index(choice.name)]

    # --- V1 and V2 as figures, all with the methods fitted on the training block (D21) ---
    estimates_v2 = {"r0": masked_estimate(zero, v2), "r1": masked_estimate(reference, v2)}
    estimates_v2.update({name: masked_estimate(rec, v2) for name, rec in zip(names, recs, strict=True) if name != "r1"})
    order = ["r0", *names]
    checks = {"valid_v1": score_candidates({n: estimates_v1[n] for n in order}, v1, resamples=view.bootstrap.recovery_resamples, seed=view.bootstrap.seed),
              "valid_v2": score_candidates({n: estimates_v2[n] for n in order}, v2, resamples=view.bootstrap.recovery_resamples, seed=view.bootstrap.seed)}
    leak_v2 = np.concatenate([leaky_hidden_mass(cube, inputs, mask) for inputs, mask in v2.parts])
    wape_v2 = {"r1": wape_series(v2.series_key, estimates_v2["r1"], v2.truth), "chosen": wape_series(v2.series_key, estimates_v2[choice.name], v2.truth),
               "reads_daily_total": wape_series(v2.series_key, leak_v2, v2.truth)}
    bias_v2 = {"r1": estimates_v2["r1"].sum() / v2.truth.sum() - 1, "chosen": estimates_v2[choice.name].sum() / v2.truth.sum() - 1, "reads_daily_total": leak_v2.sum() / v2.truth.sum() - 1}
    leakage = leakage_table(wape_v2, bias_v2, dict.fromkeys(wape_v2, len(v2.truth)), ratio=r.leak_tripwire_ratio)

    # --- the replication and the forecasts of the validation: a and the recovery from the training block alone ---
    n_hours = block.sales.shape[2]
    recovered_part = np.zeros((block.sales.shape[0], len(keys), n_hours), dtype=np.float32)
    part_idx = np.concatenate([train_idx, valid_idx])
    recovered_part[:, part_idx, :] = recover_block(chosen, block, part_idx)
    state = block.state
    band = block.band

    def view_of(values: np.ndarray, idx: np.ndarray) -> CubeView:
        return CubeView(values[:, idx, :], keys[idx])

    train_view, valid_view = view_of(recovered_part, train_idx), view_of(recovered_part, valid_idx)
    cf_train = fit_ipf(train_view, regular_mask(state[:, train_idx]), gpos, view.effect.ipf_iterations, n_groups=n_groups, group_ids=group_ids, version="recovered")
    rec_train = records(train_view, cf_train, state[:, train_idx] == PROMO, gpos)
    cell_train = cell_of(gpos[rec_train.series], band[:, train_idx][rec_train.series, rec_train.day], n_bands)
    total_train = np.zeros(len(rec_train.series), dtype=np.int64)
    d_total, d_cell = two_way_draws_many(rec_train, [(total_train, 1), (cell_train, n_cells)], view.bootstrap.resamples, view.bootstrap.seed)
    train_total, train_cells = _unit(rec_train, total_train, 1, d_total), _unit(rec_train, cell_train, n_cells, d_cell)
    b_valid = day_factor(valid_view, cf_train, regular_mask(state[:, valid_idx]), gpos)
    cf_valid = replace(cf_train, b=b_valid, days=keys[valid_idx])
    rec_valid = records(valid_view, cf_valid, state[:, valid_idx] == PROMO, gpos)
    band_valid = band[:, valid_idx][rec_valid.series, rec_valid.day]
    cell_valid = cell_of(gpos[rec_valid.series], band_valid, n_bands)
    total_valid = np.zeros(len(rec_valid.series), dtype=np.int64)
    v_total, v_cell, v_band = two_way_draws_many(rec_valid, [(total_valid, 1), (cell_valid, n_cells), (band_valid.astype(np.int64), n_bands)], view.bootstrap.resamples,
                                                 view.bootstrap.seed + 1)
    valid_total, valid_cells, valid_bands = _unit(rec_valid, total_valid, 1, v_total), _unit(rec_valid, cell_valid, n_cells, v_cell), _unit(rec_valid, band_valid.astype(np.int64), n_bands, v_band)
    both = ((train_cells["series"] >= view.ranking.min_series) & (valid_cells["series"] >= view.ranking.min_series) & np.isfinite(train_cells["lift"]) & np.isfinite(valid_cells["lift"]))
    difference_low, difference_high = interval(v_cell[:, both] - d_cell[:, both]) if both.any() else (np.array([]), np.array([]))
    finite = np.isfinite(valid_bands["lift"])
    replication = {
        "fit_blocks": FIT_BLOCKS_VALID, "days": int(len(valid_idx)), "cells_in_both": int(both.sum()),
        "spearman_cells": spearman(train_cells["lift"][both], valid_cells["lift"][both]),
        "share_consistent": float(((difference_low <= 0) & (difference_high >= 0)).mean()) if both.any() else None,
        "share_inside_train_interval": float(((valid_cells["lift"][both] >= train_cells["low"][both]) & (valid_cells["lift"][both] <= train_cells["high"][both])).mean()) if both.any() else None,
        "train_lift": train_total["lift"][0], "valid_lift": valid_total["lift"][0], "valid_ci_low": valid_total["low"][0], "valid_ci_high": valid_total["high"][0],
        "spearman_depth_valid": spearman(-np.arange(n_bands)[finite], valid_bands["lift"][finite])}
    lifts_train = Lifts(float(train_total["lift"][0]), train_cells["lift"])
    frames, skipped = [], 0
    for position in valid_idx.tolist():
        history = CubeView(block.sales[:, position - naive_days:position, :], keys[position - naive_days:position])
        result = forecasts(cf_train, b_valid[:, int(np.searchsorted(valid_idx, position))], lifts_train, block.day(position), history, view)
        frames.append(result.frame)
        skipped += len(result.skipped)
    forecast_frame = pd.concat(frames, ignore_index=True)
    day_of = np.searchsorted(keys[valid_idx], forecast_frame["date_key"].to_numpy())
    errors = forecast_errors(forecast_frame).set_index("method")
    by_method = {m: forecast_frame["method"].to_numpy() == m for m in errors.index}
    draws_of = {}
    for method in errors.index:
        part = forecast_frame[by_method[method]]
        pseudo = Records(part["series_key"].to_numpy().astype(np.intp), day_of[by_method[method]], (part["forecast"] - part["observed_instock"]).abs().to_numpy(),
                         part["observed_instock"].to_numpy(), block.sales.shape[0], len(valid_idx), 0)
        draws_of[method] = two_way_draws(pseudo, np.zeros(len(part), dtype=np.int64), 1, view.bootstrap.resamples, view.bootstrap.seed)[:, 0]
    differences = {}
    for left, right in FORECAST_PAIRS:
        low, high = interval((draws_of[left] - draws_of[right])[:, None])
        differences[f"{left}_minus_{right}"] = {"value": float(errors.loc[left, "wape"] - errors.loc[right, "wape"]), "ci_low": float(low[0]), "ci_high": float(high[0])}
    forecast_doc = {"fit_blocks": FIT_BLOCKS_VALID, "skipped": int(skipped), "differences": differences,
                    **{m: {"rows": int(errors.loc[m, "rows"]), "wape": float(errors.loc[m, "wape"]), "bias": float(errors.loc[m, "bias"])} for m in errors.index}}

    # --- the method fitted again with the 90 days, and the published effects ---
    everything = np.ones(len(keys), dtype=bool)
    final = refit(chosen, block, everything, pmf, view)
    final_r3 = final.r3 if final.method == "r3" else (fit_r3(block, everything, final.base, pmf, view) if "r3" in r.methods else None)
    recovered_all = recover_block(final, block, np.arange(len(keys)))
    cfs, estimates, all_records = {}, {}, {}
    for version, values in (("raw", block.sales), ("recovered", recovered_all)):
        cfs[version] = fit_ipf(CubeView(values, keys), regular_mask(state), gpos, view.effect.ipf_iterations, n_groups=n_groups, group_ids=group_ids, version=version)
        rec_all = records(CubeView(values, keys), cfs[version], state == PROMO, gpos)
        all_records[version] = rec_all
        unit_band = band[rec_all.series, rec_all.day].astype(np.int64)
        unit_cell = cell_of(gpos[rec_all.series], unit_band, n_bands)
        unit_group = gpos[rec_all.series].astype(np.int64)
        unit_total = np.zeros(len(rec_all.series), dtype=np.int64)
        draws = two_way_draws_many(rec_all, [(unit_total, 1), (unit_cell, n_cells), (unit_band, n_bands), (unit_group, n_groups)], view.bootstrap.resamples, view.bootstrap.seed)
        flagged = records(CubeView(values, keys), cfs[version], state == UNFLAGGED, gpos)
        unflagged_band = band[flagged.series, flagged.day].astype(np.int64)
        (unflagged_draws,) = two_way_draws_many(flagged, [(unflagged_band, n_bands)], view.bootstrap.resamples, view.bootstrap.seed)
        cells = _unit(rec_all, unit_cell, n_cells, draws[1])
        estimates[version] = {
            "overall": _unit(rec_all, unit_total, 1, draws[0]), "cell": cells, "band": _unit(rec_all, unit_band, n_bands, draws[2]),
            "group": _unit(rec_all, unit_group, n_groups, draws[3]), "unflagged_band": _unit(flagged, unflagged_band, n_bands, unflagged_draws),
            "ranking": rank_cells(cells["lift"], cells["low"], cells["high"], cells["series"], view.ranking.min_series),
            "naive": naive_pooled(CubeView(values, keys), state)}
    bundle = LaunchBundle(
        MODEL_VERSION, final, pmf, cfs, {v: Lifts(float(estimates[v]["overall"]["lift"][0]), estimates[v]["cell"]["lift"]) for v in VERSIONS}, group_ids, n_bands,
        (int(view.calendar.day_hours[0]), int(view.calendar.day_hours[1])), final_r3)

    # the hours of the launch as recovered: the file of the cube and the sums of the series-days (the night and the hours with stock as they were)
    first_hour, last_hour = view.calendar.day_hours
    # each day is copied out of its memory map at once: a view of a day keeps the whole file of the delivery mapped (90 of them were 19 GB on the real data)
    hours24 = np.stack([np.array(cube.sales(int(k)), dtype=np.float32) for k in keys], axis=1)
    hours24[:, :, first_hour:last_hour + 1] = recovered_all
    recovered_sums = recovered_all.sum(axis=2, dtype=np.float64)

    # --- the documents, the rows and the rules ---
    ranked_ids = [int(i) for i in np.flatnonzero(estimates["recovered"]["ranking"]["ranked"].to_numpy())]
    pair_count, overlap_count = overlapping_pairs(estimates["recovered"]["cell"]["low"], estimates["recovered"]["cell"]["high"], ranked_ids)

    def entry(family: str, version: str, key: str, at: int) -> dict[str, Any]:
        s = estimates[version][family]
        return {"key": key, "lift": s["lift"][at], "ci_low": s["low"][at], "ci_high": s["high"][at], "series": int(s["series"][at]), "series_days": int(s["series_days"][at])}

    cell_entries = []
    for at in range(n_cells):
        ranking = estimates["recovered"]["ranking"]
        if estimates["recovered"]["cell"]["series_days"][at]:
            cell_entries.append({**entry("cell", "recovered", cell_key(at, group_ids, n_bands), at), "rank": None if pd.isna(ranking["rank"].iloc[at]) else int(ranking["rank"].iloc[at]),
                                 "tier": None if pd.isna(ranking["tier"].iloc[at]) else int(ranking["tier"].iloc[at])})
    effects_doc = {
        "overall": {v: entry("overall", v, "all", 0) for v in VERSIONS}, "cells": cell_entries,
        "bands": [{**entry("band", "recovered", f"b{k}", k), "raw_lift": estimates["raw"]["band"]["lift"][k]} for k in range(n_bands)],
        "groups": [entry("group", "recovered", f"g{int(group_ids[k])}", k) for k in range(n_groups)],
        "pairs": {"pairs": pair_count, "overlapping": overlap_count},
        "naive_pooled": {v: estimates[v]["naive"] for v in VERSIONS}}
    score_doc = {scope: {row["method"]: {k: row[k] for k in ("wape_series", "bias", "bias_promo", "bias_regular", "lift_bias", "ci_low_vs_r1", "ci_high_vs_r1")} for row in rows}
                 for scope, rows in checks.items()}
    recovery_doc = {"method": chosen.method, "kappa": chosen.kappa, "name": choice.name, "grid_edge": _grid_edge(chosen, r.kappas), "wape_v1": choice.wape[choice.name],
                    "wape_v2": wape_v2["chosen"], "candidates_v1": {n: choice.wape[n] for n in names}, "pmf": pmf}
    validation = _clean({
        "recovery_v1": {"fit_blocks": FIT_BLOCKS_VALID, **score_doc["valid_v1"]}, "recovery_v2": {"fit_blocks": FIT_BLOCKS_VALID, **score_doc["valid_v2"]},
        "replication": replication, "forecast": forecast_doc,
        "leakage": {row.check_id: {"wape": row.wape, "trips_m01": row.trips_m01} for row in leakage.itertuples()}})
    digest = canonical_sha256(_rounded(validation))
    artifact_sha, r3_sha = artifact_digests(bundle)
    document = _clean({
        "run_key": run.run_key, "as_of": _stamp(run.as_of), "train_sha256": view.train_sha256_seen, "eval_sha256": view.eval_sha256_seen, "config_sha256": config_fingerprint(view),
        "sealed_config": sealed_document(view), "model_version": MODEL_VERSION, "artifact_sha256": artifact_sha, "r3_sha256": r3_sha, "recovery": recovery_doc,
        "effects": effects_doc, "validation": validation, "validation_digest": digest})
    outcome = launch_seal_outcome(cfg.paths.seal, document)           # refuses a repetition that does not reproduce the seal, before anything is written
    for what, ok in (("el aumento total", np.isfinite([estimates[v]["overall"]["lift"][0] for v in VERSIONS]).all()),
                     ("el contrafactual del total", all(estimates[v]["overall"]["counterfactual"][0] > 0 for v in VERSIONS)),
                     ("los pronósticos", bool(np.isfinite(forecast_frame["forecast"]).all()))):
        if not ok:
            raise LaunchError(f"M04: {what} no es finito o positivo: no se escribió nada (docs/runbook.md, R5)")

    check_rows = [(scope, "tail", row["method"], FIT_BLOCKS_VALID, row["series"], row["masked_days"], row["hidden_hours"], row["hidden_mass"], row["wape_series"], row["bias"],
                   row["bias_promo"], row["bias_regular"], row["lift_bias"], row["ci_low_vs_r1"], row["ci_high_vs_r1"]) for scope, rows in checks.items() for row in rows]
    effect_rows: list[tuple] = []
    for version in VERSIONS:
        for unit, family, keys_of in (("overall", "overall", ["all"]), ("cell", "cell", [cell_key(k, group_ids, n_bands) for k in range(n_cells)]),
                                      ("band", "band", [f"b{k}" for k in range(n_bands)]), ("group", "group", [f"g{int(g)}" for g in group_ids]),
                                      ("unflagged_band", "unflagged_band", [f"b{k}" for k in range(n_bands)])):
            stats = estimates[version][family]
            for at, key in enumerate(keys_of):
                if stats["series_days"][at]:
                    effect_rows.append(_effect_row("launch", version, unit, key, FIT_BLOCKS_LAUNCH, stats, at, estimates[version]["ranking"] if unit == "cell" else None))
        rows_all = all_records[version]
        promo_days = state == PROMO
        daily = CubeView((block.sales if version == "raw" else recovered_all), keys).values.sum(axis=2, dtype=np.float64)
        effect_rows.append(("launch", version, "naive_pooled", "all", "regular", FIT_BLOCKS_LAUNCH, float(daily[promo_days].mean()), float(daily[state == REGULAR].mean()),
                            float(estimates[version]["naive"]), None, None, None, int(len(np.unique(rows_all.series))), int(promo_days.sum()), 0, None))
    replication_ranking = rank_cells(valid_cells["lift"], valid_cells["low"], valid_cells["high"], valid_cells["series"], view.ranking.min_series)
    for unit, stats, keys_of, ranking in (("overall", valid_total, ["all"], None), ("cell", valid_cells, [cell_key(k, group_ids, n_bands) for k in range(n_cells)], replication_ranking),
                                          ("band", valid_bands, [f"b{k}" for k in range(n_bands)], None)):
        for at, key in enumerate(keys_of):
            if stats["series_days"][at]:
                effect_rows.append(_effect_row("valid_replication", "recovered", unit, key, FIT_BLOCKS_VALID, stats, at, ranking))
    forecast_rows = list(zip(forecast_frame["series_key"].astype(int).tolist(), forecast_frame["date_key"].astype(int).tolist(), forecast_frame["method"].tolist(),
                             forecast_frame["forecast"].astype(float).tolist(), forecast_frame["observed_instock"].astype(float).tolist(), ["valid"] * len(forecast_frame),
                             [run.run_key] * len(forecast_frame), strict=True))
    seal_label = "post_seal" if outcome == "post_seal" else "sealed"
    row = {"model_version": MODEL_VERSION, "trained_as_of": _stamp(run.as_of), "artifact_name": ARTIFACT_NAME, "artifact_sha256": artifact_sha, "r3_name": R3_NAME if r3_sha else None,
           "r3_sha256": r3_sha, "config_sha256": document["config_sha256"],
           "recovery_json": json.dumps(_clean({**recovery_doc, "seal": seal_label, "candidates_v2": {n: score_doc["valid_v2"][n]["wape_series"] for n in order}}), sort_keys=True),
           "validation_digest": digest}
    series_without_regular = int(np.isnan(cfs["recovered"].a[:, 0]).sum())

    # --- the writes: the artifact, then the database in one transaction, then the seal ---
    save_artifact(bundle, cfg.paths.models_dir)
    store_recovered(cfg.paths.interim_dir, delivery_plan(view)[0].delivery_id, keys, hours24)
    del hours24
    conn.execute("BEGIN IMMEDIATE")
    try:
        apply_schema(conn)
        register_model(conn, row)
        set_recovered_sums(conn, keys, recovered_sums)
        conn.executemany("INSERT INTO recovery_checks VALUES (" + ", ".join("?" * 15) + ")", check_rows)
        conn.executemany("INSERT INTO effect_estimates VALUES (" + ", ".join("?" * 16) + ")", effect_rows)
        conn.executemany("INSERT INTO forecasts VALUES (?, ?, ?, ?, ?, ?, ?)", forecast_rows)
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        logger.warning("launch %s rolled back: the registry and the figures were not written", run.run_key)
        raise
    seal = write_launch_seal(cfg.paths.seal, document)
    rows = {"model_registry": 1, "recovery_checks": len(check_rows), "effect_estimates": len(effect_rows), "forecasts": len(forecast_rows)}
    rules = [
        model_result("M01", passed=True, series_days=len(v1.truth)), model_result("M02", passed=True), model_result("M03", passed=True),
        model_result("M04", passed=True, series_days=len(forecast_frame)), model_result("M05", passed=seal != "post_seal"),
        model_result("M06", passed=True, series_days=len(v1.truth) + len(v2.truth)), model_result("I03", passed=True, series_days=series_without_regular),
        model_result("I04", passed=True, series_days=sum(rows.values()))]
    logger.info("fit_model %s: version %s, method %s, artifact %s, seal %s, rows %s", run.run_key, MODEL_VERSION, choice.name, artifact_sha[:12], seal, rows)
    return LaunchResult("launch", seal, MODEL_VERSION, document["config_sha256"], artifact_sha, r3_sha, {**recovery_doc, "pmf": pmf.tolist()}, rules, rows, leakage, document, bundle)
