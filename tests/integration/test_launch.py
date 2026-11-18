"""The launch (U09; RF11, RF16, D08, D17, D19-D21; M01, M03, M05, M06; AC13, AC15, AC18, AC20, AC22): the recovery is chosen in V1 with methods fitted on the
training block, V2 only previews, the model is refitted with the 90 days and frozen, and the seal is written once."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
import shutil
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from promolift.launch import BlockSizeError, LaunchError, fit_model
from promolift.registry import (
    ARTIFACT_NAME,
    R3_NAME,
    ArtifactMismatchError,
    RunMeta,
    SealError,
    SealMismatchError,
    config_fingerprint,
    read_registry,
    read_seal,
    sealed_view,
)
from promolift.warehouse import connect
from tests.fixtures.launching import RUN, launch

BLOCK_OF_SCOPE = {"valid_v1": ("valid_v1",), "valid_v2": ("valid_v2",), "valid_replication": ("valid_v1", "valid_v2"), "valid": ("valid_v1", "valid_v2")}


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest() if Path(path).exists() else ""


def query(db: Path, sql: str, params=()):
    conn = connect(db)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def frame(db: Path, sql: str) -> pd.DataFrame:
    conn = connect(db)
    try:
        return pd.read_sql_query(sql, conn)
    finally:
        conn.close()


# --- what the launch writes ---------------------------------------------------------------------------------------------------------------------


def test_the_launch_freezes_the_model_registers_it_seals_it_and_issues_its_figures(launched, fixture_truth):
    result, cfg = launched.result, launched.cfg
    assert (result.mode, result.seal, result.model_version) == ("launch", "written", "v1")
    view = sealed_view(cfg, launched.train, launched.eval)
    assert result.config_sha256 == config_fingerprint(view)
    row = read_registry(connect(launched.db), "v1")
    assert row["artifact_sha256"] == result.artifact_sha256 == sha(cfg.paths.models_dir / ARTIFACT_NAME) and row["config_sha256"] == result.config_sha256
    chosen = result.recovery["name"]
    assert row["r3_sha256"] == sha(cfg.paths.models_dir / R3_NAME) is not None          # R3 is kept whichever method was chosen: the test week measures it (D20)
    assert result.bundle.r3 is not None and (result.bundle.recovery.r3 is not None) == (chosen == "r3")
    seal = read_seal(cfg.paths.seal)
    assert seal["launch"]["config_sha256"] == result.config_sha256 and seal["launch"]["recovery"]["name"] == chosen and "test" not in seal
    assert seal["launch"]["train_sha256"] == launched.train and seal["launch"]["eval_sha256"] == launched.eval
    assert row["validation_digest"] == seal["launch"]["validation_digest"] and json.loads(row["recovery_json"])["name"] == chosen
    counts = {t: query(launched.db, f"SELECT COUNT(*) FROM {t}")[0][0] for t in ("recovery_checks", "effect_estimates", "forecasts", "daily_cell", "mask_checks")}
    assert counts["recovery_checks"] > 10 and counts["effect_estimates"] > 40 and counts["forecasts"] > 1000 and counts["daily_cell"] == counts["mask_checks"] == 0
    assert result.rows == {"model_registry": 1, "recovery_checks": counts["recovery_checks"], "effect_estimates": counts["effect_estimates"], "forecasts": counts["forecasts"]}
    assert {r.rule_id for r in result.rules} >= {"M01", "M02", "M03", "M04", "M05", "M06", "I03", "I04"} and all(r.passed for r in result.rules if r.rule_id != "M05")
    assert [r for r in result.rules if r.rule_id == "M05"][0].passed is True


def test_every_validation_figure_names_the_blocks_its_method_saw_and_none_saw_its_own_block(launched):
    checks = frame(launched.db, "SELECT scope, fit_blocks FROM recovery_checks")
    effects = frame(launched.db, "SELECT scope, fit_blocks, unit FROM effect_estimates")
    assert set(checks["scope"]) == {"valid_v1", "valid_v2"} and set(checks["fit_blocks"]) == {"train"}
    assert set(effects["scope"]) == {"launch", "valid_replication"} and effects["fit_blocks"].str.len().min() > 0
    assert set(effects[effects["scope"] == "valid_replication"]["fit_blocks"]) == {"train"}
    assert set(effects[effects["scope"] == "launch"]["fit_blocks"]) == {"train+purge+valid_v1+valid_v2"}
    forecasts = frame(launched.db, "SELECT DISTINCT scope FROM forecasts")
    assert forecasts["scope"].tolist() == ["valid"]
    for scope, own in BLOCK_OF_SCOPE.items():
        rows = pd.concat([checks[checks["scope"] == scope], effects[effects["scope"] == scope]])
        for blocks in rows["fit_blocks"]:
            assert not set(blocks.split("+")) & set(own), (scope, blocks)
    validation = read_seal(launched.cfg.paths.seal)["launch"]["validation"]
    for part in ("recovery_v1", "recovery_v2", "replication", "forecast"):
        assert validation[part]["fit_blocks"] == "train", part


def test_the_choice_is_the_lowest_series_wape_in_v1_with_the_tie_rule_and_the_candidates_are_all_kept(launched):
    v1 = frame(launched.db, "SELECT method, wape_series FROM recovery_checks WHERE scope = 'valid_v1' AND mask = 'tail'").set_index("method")["wape_series"]
    expected_names = ["r0", "r1", *[f"r2@{k:g}" for k in sorted(launched.cfg.recovery.kappas)], "r3"]
    assert v1.index.tolist() == sorted(expected_names)
    best = None
    for name in [n for n in expected_names if n != "r0"]:                # the candidates in the order of preference; r0 is the reference
        if best is None or v1[name] < v1[best] - 1e-6:
            best = name
    chosen = launched.result.recovery
    assert chosen["name"] == best and chosen["wape_v1"] == pytest.approx(v1[best]) and v1["r0"] == pytest.approx(1.0)
    assert all(v1[n] < v1["r0"] for n in v1.index if n != "r0")
    kappas = sorted(launched.cfg.recovery.kappas)
    assert chosen["grid_edge"] == (("lower" if chosen["kappa"] == kappas[0] else "upper" if chosen["kappa"] == kappas[-1] else None) if chosen["method"] == "r2" else None)


def test_the_preview_in_v2_chooses_nothing_whatever_it_shows(launched, fresh, fixture_truth, launch_config, tmp_path):
    cfg, conn = fresh(recovery=dataclasses.replace(launched.cfg.recovery, mask_seed_v2=12345))
    other = launch(cfg, conn, fixture_truth)
    assert other.recovery["name"] == launched.result.recovery["name"] and other.recovery["wape_v1"] == launched.result.recovery["wape_v1"]
    mine = frame(launched.db, "SELECT method, wape_series FROM recovery_checks WHERE scope = 'valid_v2'")
    theirs = frame(cfg.paths.warehouse, "SELECT method, wape_series FROM recovery_checks WHERE scope = 'valid_v2'")
    assert not np.allclose(mine.sort_values("method")["wape_series"], theirs.sort_values("method")["wape_series"])      # another mask: other V2 figures, same model
    assert other.config_sha256 != launched.result.config_sha256


def test_the_launch_reads_nothing_from_the_test_block(launched, store_upto, fresh, fixture_truth, monkeypatch):
    from promolift.cube import LoadedCube

    last = 20240625
    read = []
    original = LoadedCube._load
    monkeypatch.setattr(LoadedCube, "_load", lambda self, date_key, field: (read.append(date_key), original(self, date_key, field))[1])
    cfg, conn = fresh()
    statements = []
    conn.set_trace_callback(statements.append)
    launch(cfg, conn, fixture_truth)
    assert read and max(read) <= last and min(read) == 20240328
    keys = {int(k) for s in statements for k in re.findall(r"date_key\s*=\s*(\d{8})", s)}
    assert keys and max(keys) <= last
    assert not any(re.search(r"\bdeliveries\b", s) and "D2024" in s for s in statements)


def test_a_launch_with_a_day_of_the_test_already_loaded_is_refused_before_anything_is_written(store_upto, launch_config, fixture_truth, tmp_path):
    store = store_upto("D2024-06-26")
    shutil.copytree(store.interim, tmp_path / "interim")
    shutil.copyfile(store.db, tmp_path / "w.sqlite")
    cfg = launch_config(tmp_path)
    before = sha(tmp_path / "w.sqlite")
    conn = connect(tmp_path / "w.sqlite")
    try:
        with pytest.raises(LaunchError, match="20240626"):
            fit_model(cfg, conn, RUN, train_sha256=fixture_truth.train_sha256, eval_sha256=fixture_truth.eval_sha256)
    finally:
        conn.close()
    assert sha(tmp_path / "w.sqlite") == before and not (tmp_path / "models").exists() and not cfg.paths.seal.exists()


# --- the trap and the demonstration of the leak --------------------------------------------------------------------------------------------------


def test_the_leak_demonstration_shows_what_reading_the_daily_total_gives_and_that_the_trap_would_stop_it(launched):
    table = launched.result.leakage.set_index("check_id")
    assert {"r1", "chosen", "reads_daily_total"} <= set(table.index)
    assert table.loc["reads_daily_total", "wape"] < 0.01 < table.loc["r1", "wape"] and bool(table.loc["reads_daily_total", "trips_m01"])
    assert not bool(table.loc["r1", "trips_m01"]) and not bool(table.loc["chosen", "trips_m01"])
    assert (launched.result.leakage["rows"] > 0).all()
    assert read_seal(launched.cfg.paths.seal)["launch"]["validation"]["leakage"]["reads_daily_total"]["trips_m01"] is True


# --- the seal, a repetition and a later run ---------------------------------------------------------------------------------------------------


def test_a_repetition_with_the_sealed_configuration_reproduces_the_seal_and_another_configuration_is_post_seal(launched, fresh, fixture_truth, tmp_path):
    seal = launched.cfg.paths.seal
    before = seal.read_bytes()
    cfg, conn = fresh(seal=seal)
    again = launch(cfg, conn, fixture_truth)
    assert again.seal == "unchanged" and again.config_sha256 == launched.result.config_sha256 and seal.read_bytes() == before
    assert again.artifact_sha256 == launched.result.artifact_sha256             # the same model gives the same bytes
    conn.close()
    other_cfg, other_conn = fresh(seal=seal, ranking=dataclasses.replace(launched.cfg.ranking, min_series=6))
    post = launch(other_cfg, other_conn, fixture_truth)
    assert post.seal == "post_seal" and post.config_sha256 != launched.result.config_sha256 and seal.read_bytes() == before
    assert json.loads(read_registry(other_conn, "v1")["recovery_json"])["seal"] == "post_seal"
    assert [r for r in post.rules if r.rule_id == "M05"][0].passed is False


def test_the_same_configuration_with_another_sealed_value_stops_the_launch_before_any_write(launched, fresh, fixture_truth, tmp_path):
    seal = tmp_path / "tampered_seal.json"
    document = json.loads(launched.cfg.paths.seal.read_text(encoding="utf-8"))
    document["launch"]["effects"]["overall"]["recovered"]["lift"] += 0.01
    seal.write_text(json.dumps(document, sort_keys=True), encoding="utf-8")
    cfg, conn = fresh(seal=seal)
    before = sha(tmp_path / "w.sqlite")
    with pytest.raises(SealMismatchError, match="effects.overall.recovered.lift"):
        launch(cfg, conn, fixture_truth)
    conn.close()
    assert sha(tmp_path / "w.sqlite") == before and not (tmp_path / "models").exists()
    assert json.loads(seal.read_text(encoding="utf-8")) == document


def test_a_later_run_loads_the_frozen_model_checks_its_hash_and_fits_nothing(launched, fixture_truth, launch_config, tmp_path):
    folder = tmp_path / "later"
    shutil.copytree(launched.folder, folder)
    cfg = launch_config(folder)
    cfg = dataclasses.replace(cfg, paths=dataclasses.replace(cfg.paths, interim_dir=folder / "interim"))
    conn = connect(folder / "w.sqlite")
    try:
        rows_before = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("model_registry", "effect_estimates", "forecasts", "recovery_checks")}
        later = fit_model(cfg, conn, RunMeta("run-later", datetime(2024, 6, 27)), train_sha256=launched.train, eval_sha256=launched.eval)
        assert (later.mode, later.seal, later.artifact_sha256) == ("verify", "match", launched.result.artifact_sha256)
        assert later.bundle.recovery.method == launched.result.bundle.recovery.method and np.array_equal(later.bundle.recovery.base, launched.result.bundle.recovery.base)
        assert rows_before == {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in rows_before}
        post = fit_model(cfg, conn, RunMeta("run-later", datetime(2024, 6, 27)), train_sha256="9" * 64, eval_sha256=launched.eval)
        assert post.seal == "post_seal" and post.mode == "verify"            # another source file: the model is the same, the figures are marked
        victim = cfg.paths.models_dir / ARTIFACT_NAME
        victim.write_bytes(victim.read_bytes() + b"\0")
        with pytest.raises(ArtifactMismatchError):
            fit_model(cfg, conn, RunMeta("run-later", datetime(2024, 6, 27)), train_sha256=launched.train, eval_sha256=launched.eval)
        victim.write_bytes(victim.read_bytes()[:-1])
        cfg.paths.seal.unlink()
        with pytest.raises(SealError, match="sello"):
            fit_model(cfg, conn, RunMeta("run-later", datetime(2024, 6, 27)), train_sha256=launched.train, eval_sha256=launched.eval)
    finally:
        conn.close()


def test_blocks_too_small_or_without_regular_days_are_refused_before_anything_is_written(fresh, fixture_truth, tmp_path):
    cfg, conn = fresh()
    cfg_small = dataclasses.replace(cfg, split=dataclasses.replace(cfg.split, min_masked_days=10**6))
    before = sha(tmp_path / "w.sqlite")
    with pytest.raises(BlockSizeError, match="valid_v1"):
        launch(cfg_small, conn, fixture_truth)
    conn.close()
    assert sha(tmp_path / "w.sqlite") == before and not (tmp_path / "models").exists() and not cfg.paths.seal.exists()


# --- the figures it issues ------------------------------------------------------------------------------------------------------------------


def test_the_published_effects_are_consistent_ordered_and_the_raw_one_is_below_the_recovered_one(launched):
    e = frame(launched.db, "SELECT * FROM effect_estimates WHERE scope = 'launch'")
    overall = e[e["unit"] == "overall"].set_index("version")
    assert set(overall.index) == {"raw", "recovered"} and overall.loc["raw", "lift"] < overall.loc["recovered", "lift"]
    measured = e[e["ci_low"].notna()]
    assert ((measured["ci_low"] <= measured["lift"]) & (measured["lift"] <= measured["ci_high"])).all() and set(measured["ci_kind"]) == {"two_way"}
    bands = e[(e["unit"] == "band") & (e["version"] == "recovered")].sort_values("unit_key")
    assert bands["unit_key"].tolist() == [f"b{k}" for k in range(7)] and (bands["lift"].diff().dropna() < 0).all()
    cells = e[(e["unit"] == "cell") & (e["version"] == "recovered")]
    ranked = cells[cells["ranked"] == 1].sort_values("lift", ascending=False)
    assert len(ranked) > 10 and (ranked["series"] >= launched.cfg.ranking.min_series).all() and ranked["tier"].is_monotonic_increasing and ranked["tier"].min() == 1
    assert cells[cells["ranked"] == 0]["tier"].isna().all() and cells["unit_key"].str.fullmatch(r"g\d+-b[0-6]").all()
    assert set(e["unit"]) == {"overall", "cell", "band", "group", "unflagged_band", "naive_pooled"} and set(e["control"]) == {"regular"}
    naive = e[e["unit"] == "naive_pooled"].set_index("version")
    assert naive["ci_low"].isna().all() and abs(naive.loc["raw", "lift"] - overall.loc["raw", "lift"]) < 0.5
    seal = read_seal(launched.cfg.paths.seal)["launch"]["effects"]
    assert seal["pairs"]["pairs"] > 0 and seal["overall"]["recovered"]["lift"] == pytest.approx(overall.loc["recovered", "lift"], abs=1e-6)


def test_the_forecasts_of_the_validation_are_four_per_promo_series_day_and_the_seal_says_what_the_rows_say(launched):
    f = frame(launched.db, "SELECT * FROM forecasts")
    assert set(f["scope"]) == {"valid"} and set(f["method"]) == {"f0_no_lift", "f1_naive", "f2a_overall_lift", "f2_cell_lift"}
    assert f.groupby(["series_key", "date_key"]).size().eq(4).all() and f["date_key"].min() == 20240608 and f["date_key"].max() == 20240625
    state = frame(launched.db, "SELECT series_key, date_key, day_state FROM series_days WHERE date_key BETWEEN 20240608 AND 20240625")
    promo = state[state["day_state"] == "promo"]
    joined = f.merge(promo, on=["series_key", "date_key"], how="left")
    assert joined["day_state"].eq("promo").all()                                      # forecasts only for promo series-days (chk_forecasts_only_promo_days)
    document = read_seal(launched.cfg.paths.seal)["launch"]["validation"]["forecast"]
    for method, part in f.groupby("method"):
        wape = (part["forecast"] - part["observed_instock"]).abs().sum() / part["observed_instock"].sum()
        assert document[method]["wape"] == pytest.approx(wape, abs=1e-6) and document[method]["rows"] == len(part)
    assert document["differences"]["f2_cell_lift_minus_f0_no_lift"]["ci_high"] < 0               # the lift of the cell improves the counterfactual alone, at least in the fixture


def test_the_published_effects_of_the_launch_are_those_of_the_ninety_days_and_the_artifact_holds_the_sealed_lifts(launched):
    bundle = launched.result.bundle
    e = frame(launched.db, "SELECT * FROM effect_estimates WHERE scope = 'launch' AND unit = 'overall'").set_index("version")
    for version in ("raw", "recovered"):
        assert bundle.lifts[version].overall == pytest.approx(e.loc[version, "lift"]) and bundle.cf[version].days.tolist()[0] == 20240328
        assert len(bundle.cf[version].days) == 90 and bundle.cf[version].b.shape == (7, 90)
    cells = frame(launched.db, "SELECT unit_key, lift FROM effect_estimates WHERE scope = 'launch' AND unit = 'cell' AND version = 'recovered'")
    for key, lift in zip(cells["unit_key"], cells["lift"], strict=True):
        group, band = map(int, re.fullmatch(r"g(\d+)-b(\d)", key).groups())
        assert bundle.lifts["recovered"].cell[int(np.searchsorted(bundle.group_ids, group)) * 7 + band] == pytest.approx(lift)


@pytest.mark.slow
def test_positive_control_through_the_launch_the_intervals_of_the_raw_and_the_recovered_lift_do_not_touch(launched):
    e = frame(launched.db, "SELECT version, lift, ci_low, ci_high FROM effect_estimates WHERE scope = 'launch' AND unit = 'overall'").set_index("version")
    assert e.loc["raw", "ci_high"] < e.loc["recovered", "ci_low"] and e.loc["recovered", "lift"] - e.loc["raw", "lift"] > 0.1


@pytest.mark.slow
def test_negative_control_through_the_launch_the_interval_of_the_total_contains_zero(signal_truth, launch_config, tmp_path):
    from promolift.deliveries import delivery_plan, publish, read_delivery
    from promolift.ingest import canonical as make_canonical
    from promolift.ingest import read_source
    from promolift.warehouse import load_delivery
    from tests.fixtures.make_fixture import fixture_config

    truth = signal_truth("null")
    cfg = fixture_config(launch_config(tmp_path), truth.dir)
    train, _ = read_source(cfg.source.train_path, "train", cfg)
    eval_, _ = read_source(cfg.source.eval_path, "eval", cfg)
    canon = make_canonical((train, eval_), cfg)
    spec = delivery_plan(cfg)[0]
    entry = publish(spec, canon, tmp_path / "deliveries", cfg)
    days, cube = read_delivery(tmp_path / "deliveries", entry)
    conn = connect(tmp_path / "w.sqlite")
    try:
        load_delivery(conn, days, cube, spec, "run-null", cfg, sha256=entry.sha256, series=canon.series, interim_dir=tmp_path / "interim")
        fit_model(cfg, conn, RUN, train_sha256=truth.train_sha256, eval_sha256=truth.eval_sha256)
        rows = pd.read_sql_query("SELECT version, unit, unit_key, lift, ci_low, ci_high FROM effect_estimates WHERE scope = 'launch' AND unit IN ('overall', 'band')", conn)
    finally:
        conn.close()
    assert len(rows) == 2 + 14
    measured = rows[rows["unit"] == "overall"]
    assert ((measured["ci_low"] <= 0.0) & (0.0 <= measured["ci_high"])).all(), measured
    bands = rows[rows["unit"] == "band"]
    assert ((bands["ci_low"] <= 0.0) & (0.0 <= bands["ci_high"])).all(), bands


def test_the_figures_of_v1_and_v2_are_those_of_methods_fitted_on_the_training_block_alone_and_the_frozen_model_is_the_one_fitted_with_the_ninety_days(launched):
    from promolift.cube import load_block, open_loaded_cube
    from promolift.masks import first_stockout_pmf
    from promolift.recovery import candidate_name, candidates, fit_base, mask_block, masked_estimate, wape_series
    from promolift.split import block_of

    cfg = launched.cfg
    cube = open_loaded_cube(cfg.paths.interim_dir)
    conn = connect(launched.db)
    try:
        block = load_block(cube, conn, cube.date_keys, cfg)
    finally:
        conn.close()
    blocks = block_of(pd.to_datetime([f"{k // 10000}-{k // 100 % 100:02d}-{k % 100:02d}" for k in block.date_keys]), cfg).to_numpy()
    pmf = first_stockout_pmf(block.stock, blocks == "train")
    recs = candidates(block, blocks == "train", pmf, cfg)
    for scope, name, seed in (("valid_v1", "valid_v1", cfg.recovery.mask_seed_v1), ("valid_v2", "valid_v2", cfg.recovery.mask_seed_v2)):
        masked = mask_block(block, np.flatnonzero(blocks == name), pmf, seed)
        stored = frame(launched.db, f"SELECT method, wape_series, hidden_mass FROM recovery_checks WHERE scope = '{scope}'").set_index("method")
        for rec in recs:
            assert stored.loc[candidate_name(rec), "wape_series"] == pytest.approx(wape_series(masked.series_key, masked_estimate(rec, masked), masked.truth), abs=1e-12)
        assert stored["hidden_mass"].nunique() == 1 and stored["hidden_mass"].iloc[0] == pytest.approx(masked.truth.sum())
    # the frozen model is the chosen method fitted again with every day of the launch: its base is not the one of the training block
    frozen = launched.result.bundle.recovery
    assert np.array_equal(frozen.base, fit_base(block)) and not np.array_equal(frozen.base, recs[0].base)
    assert (frozen.method, frozen.kappa) == (launched.result.recovery["method"], launched.result.recovery["kappa"])
    assert np.array_equal(launched.result.bundle.pmf, pmf)               # the distribution of the first hour without stock stays the training block's


def test_a_block_without_promo_or_without_regular_days_is_refused_by_name_before_anything_is_written(fresh, fixture_truth, tmp_path):
    cfg, conn = fresh()
    conn.execute("UPDATE series_days SET day_state = 'unflagged_cut' WHERE day_state = 'regular' AND date_key BETWEEN 20240608 AND 20240616")
    conn.close()
    conn = connect(tmp_path / "w.sqlite")
    before = sha(tmp_path / "w.sqlite")
    try:
        with pytest.raises(BlockSizeError, match=r"valid_v1 no tiene a la vez días promo y regulares"):
            launch(cfg, conn, fixture_truth)
    finally:
        conn.close()
    assert sha(tmp_path / "w.sqlite") == before and not (tmp_path / "models").exists()


def test_the_replication_says_what_the_rows_of_the_validation_say(launched):
    document = read_seal(launched.cfg.paths.seal)["launch"]["validation"]["replication"]
    valid = frame(launched.db, "SELECT unit, unit_key, lift, ci_low, ci_high, series FROM effect_estimates WHERE scope = 'valid_replication'")
    total = valid[valid["unit"] == "overall"].iloc[0]
    assert document["valid_lift"] == pytest.approx(total["lift"]) and (document["valid_ci_low"], document["valid_ci_high"]) == pytest.approx((total["ci_low"], total["ci_high"]))
    cells = valid[(valid["unit"] == "cell") & (valid["series"] >= launched.cfg.ranking.min_series)]
    assert 0 < document["cells_in_both"] <= len(cells) and document["days"] == 18
    assert document["spearman_cells"] > 0.5 and document["spearman_depth_valid"] == pytest.approx(1.0) and 0.0 <= document["share_consistent"] <= 1.0
    assert 0.0 <= document["share_inside_train_interval"] <= 1.0


def test_the_replication_holds_a_from_the_training_block_and_takes_the_day_factor_from_each_validation_day(launched):
    from promolift.cube import group_index, load_block, open_loaded_cube
    from promolift.days import PROMO
    from promolift.effect import CubeView, day_factor, fit_ipf, lifts, records, regular_mask
    from promolift.masks import first_stockout_pmf
    from promolift.recovery import candidate_name, candidates, recover_block
    from promolift.split import block_of

    cfg = launched.cfg
    cube = open_loaded_cube(cfg.paths.interim_dir)
    conn = connect(launched.db)
    try:
        block = load_block(cube, conn, cube.date_keys, cfg)
    finally:
        conn.close()
    blocks = block_of(pd.to_datetime([f"{k // 10000}-{k // 100 % 100:02d}-{k % 100:02d}" for k in block.date_keys]), cfg).to_numpy()
    train, valid = np.flatnonzero(blocks == "train"), np.flatnonzero(np.isin(blocks, ("valid_v1", "valid_v2")))
    pmf = first_stockout_pmf(block.stock, blocks == "train")
    chosen = next(r for r in candidates(block, blocks == "train", pmf, cfg) if candidate_name(r) == launched.result.recovery["name"])
    groups = np.unique(block.group)
    position = group_index(block.group, groups)
    views = {name: CubeView(recover_block(chosen, block, idx), block.date_keys[idx]) for name, idx in (("train", train), ("valid", valid))}
    cf = fit_ipf(views["train"], regular_mask(block.state[:, train]), position, cfg.effect.ipf_iterations, n_groups=len(groups), group_ids=groups, version="recovered")
    b = day_factor(views["valid"], cf, regular_mask(block.state[:, valid]), position)
    after = type(cf)(cf.a, b, block.date_keys[valid], "recovered", groups)
    rec = records(views["valid"], after, block.state[:, valid] == PROMO, position)
    expected = lifts(rec, np.zeros(len(rec.series), dtype=np.int64), 1)[0]
    stored = frame(launched.db, "SELECT lift FROM effect_estimates WHERE scope = 'valid_replication' AND unit = 'overall'")["lift"].iloc[0]
    assert stored == pytest.approx(expected, abs=1e-9)


def test_the_launch_recovers_the_hours_of_its_ninety_days_and_stores_them_once_with_the_night_and_the_hours_with_stock_as_they_were(launched):
    from promolift.cube import open_loaded_cube, open_recovered

    cfg = launched.cfg
    recovered = open_recovered(cfg.paths.interim_dir, "L2024-06-25")
    cube = open_loaded_cube(cfg.paths.interim_dir)
    assert recovered.shape == (300, 90, 24) and recovered.dtype == np.float32
    first, last = cfg.calendar.day_hours
    sums = frame(launched.db, "SELECT series_key, date_key, raw_sum, instock_hours, recovered_sum FROM series_days WHERE delivery_id = 'L2024-06-25' ORDER BY date_key, series_key")
    assert sums["recovered_sum"].notna().all() and len(sums) == 300 * 90
    for position in (0, 41, 89):
        key = int(cube.date_keys[position])
        original, stock = np.asarray(cube.sales(key)), np.asarray(cube.stock(key))
        night = np.r_[0:first, last + 1:24]
        assert np.array_equal(recovered[:, position, night], original[:, night])                       # the night is not recovered
        assert np.array_equal(recovered[:, position, first:last + 1][stock[:, first:last + 1] == 0], original[:, first:last + 1][stock[:, first:last + 1] == 0])   # nor the hours with stock
        assert (recovered[:, position, first:last + 1][stock[:, first:last + 1] == 1] >= 0).all()
        day = sums[sums["date_key"] == key].sort_values("series_key")
        assert day["recovered_sum"].to_numpy() == pytest.approx(recovered[:, position, first:last + 1].sum(axis=1, dtype=np.float64))
        assert day["recovered_sum"].sum() > day["raw_sum"].sum()          # a method replaces the sale of an hour without stock (a residual sale included) by its estimate
        assert (day["recovered_sum"].to_numpy()[day["instock_hours"].to_numpy() == 16] == pytest.approx(day["raw_sum"].to_numpy()[day["instock_hours"].to_numpy() == 16]))
    assert (sums["recovered_sum"] > sums["raw_sum"]).any()


def test_the_launch_never_keeps_the_mapped_days_of_the_cube_alive_together(fresh, fixture_truth, monkeypatch):
    """Every day of a delivery is a view of a memory map of the whole file: keeping 90 of them alive made the working set of the real launch 19 GB (found by the
    dry run on the real train block). At most a couple of views may be alive at any moment."""
    import weakref

    from promolift.cube import LoadedCube

    refs: list = []
    peak = [0]
    original = LoadedCube._load

    def watch(self, date_key, field):
        out = original(self, date_key, field)
        refs.append(weakref.ref(out))
        peak[0] = max(peak[0], sum(ref() is not None for ref in refs))
        return out

    monkeypatch.setattr(LoadedCube, "_load", watch)
    cfg, conn = fresh()
    launch(cfg, conn, fixture_truth)
    assert len(refs) > 90 and peak[0] <= 3, peak[0]
