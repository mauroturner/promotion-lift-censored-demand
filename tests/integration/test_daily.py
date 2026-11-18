"""The daily run (U10; RF17, D15, D18; AC11, AC12, AC14, AC21): each day of the test is recovered with the sealed method, its effect and its forecasts are issued
once and never change, and what is issued does not depend on how the days were delivered."""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from promolift.cube import open_loaded_cube, open_recovered
from promolift.daily import DayResult, ScoringError, estimate_delivery, recover_delivery, run_day
from promolift.deliveries import DeliverySpec
from promolift.days import PROMO, STATE_NAMES
from promolift.effect import CubeView, cell_key, counterfactual, day_factor, lifts, records, regular_mask
from promolift.forecast import METHODS
from promolift.masks import mask_tail
from promolift.recovery import Recovery, candidate_name, hidden_mass
from promolift.registry import RunMeta, sealed_view
from promolift.warehouse import connect, load_delivery
from tests.fixtures.launching import rebuilt_interim

TABLES = ("daily_cell", "forecasts", "mask_checks")


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


def table_digest(db: Path, run_key: bool = False) -> str:
    """The SHA-256 of the issued rows of the three daily tables in key order, without the column that names the run unless asked for."""
    digest = hashlib.sha256()
    for table, where, order in (("daily_cell", "1", "date_key, version, cell_key"), ("forecasts", "scope = 'test'", "date_key, series_key, method"),
                                ("mask_checks", "1", "date_key, series_key, method")):
        rows = frame(db, f"SELECT * FROM {table} WHERE {where} ORDER BY {order}")
        if not run_key:
            rows = rows.drop(columns=["run_key"])
        digest.update(table.encode() + rows.to_csv(index=False).encode("utf-8"))
    return digest.hexdigest()


@pytest.fixture(scope="module")
def world(launched, published, cfg, tmp_path_factory):
    """The launch store and the sealed model of ``launched``, and what a test needs to load the days of the test one delivery after another."""
    view = sealed_view(launched.cfg, launched.train, launched.eval)

    def loader(folder: Path):
        shutil.copytree(launched.folder / "interim", folder / "interim")
        shutil.copyfile(launched.db, folder / "w.sqlite")
        return SimpleNamespace(db=folder / "w.sqlite", interim=folder / "interim")

    def load(world, delivery_id, series):
        conn = connect(world.db)
        try:
            entry, days, cube = published.items[delivery_id]
            spec = next(s for s in published.plan if s.delivery_id == delivery_id)
            load_delivery(conn, days, cube, spec, f"run-{delivery_id}", cfg, sha256=entry.sha256, series=series, interim_dir=world.interim)
            return spec
        finally:
            conn.close()

    return SimpleNamespace(view=view, bundle=launched.result.bundle, loader=loader, load=load, launched=launched)


@pytest.fixture(scope="module")
def first_day(world, canonical, tmp_path_factory):
    """The first day of the test loaded and issued: ``(world, spec, result)``."""
    folder = tmp_path_factory.mktemp("daily_first")
    mine = world.loader(folder)
    spec = world.load(mine, "D2024-06-26", canonical.series)
    conn = connect(mine.db)
    try:
        cube = open_loaded_cube(mine.interim)
        result = run_day(conn, cube, world.bundle, RunMeta("run-day-1", spec.as_of), spec, world.view, interim_dir=mine.interim)
    finally:
        conn.close()
    return SimpleNamespace(mine=mine, spec=spec, result=result)


def day_inputs_of(mine, view, date_key):
    from promolift.cube import day_inputs

    conn = connect(mine.db)
    try:
        return day_inputs(open_loaded_cube(mine.interim), conn, date_key, view)
    finally:
        conn.close()


# --- what a day issues --------------------------------------------------------------------------------------------------------------------


def test_each_test_day_issues_one_row_per_cell_and_per_promo_series_day_and_never_changes_it(first_day, world):
    result, db = first_day.result, first_day.mine.db
    assert isinstance(result, DayResult) and result.issued and result.delivery_id == "D2024-06-26" and result.date_keys == (20240626,)
    inputs = day_inputs_of(first_day.mine, world.view, 20240626)
    promo = np.flatnonzero(inputs.state == PROMO)
    cells = frame(db, "SELECT * FROM daily_cell")
    assert set(cells["version"]) == {"raw", "recovered"} and set(cells["date_key"]) == {20240626} and set(cells["run_key"]) == {"run-day-1"}
    for version in ("raw", "recovered"):
        part = cells[cells["version"] == version]
        keys = set(part["cell_key"])
        expected = {f"g{int(g)}-b{int(b)}" for g, b in set(zip(inputs.group[promo], inputs.band[promo], strict=True))}
        assert keys >= {"all"} and {k for k in keys if k.startswith("g")} <= expected          # a cell with a promo series-day, or the reason it has no row
        assert {f"b{k}" for k in range(7) if (inputs.band[promo] == k).any()} <= keys
        assert part[part["cell_key"] == "all"]["series_days"].iloc[0] + len(result.skipped) == len(promo)        # every promo series-day is in the day or has its reason
    forecasts = frame(db, "SELECT * FROM forecasts WHERE scope = 'test'")
    assert set(forecasts["scope"]) == {"test"} and set(forecasts["method"]) == set(METHODS) and set(forecasts["run_key"]) == {"run-day-1"}
    per = forecasts.groupby("series_key").size()
    assert per.eq(4).all() and len(per) + len(result.skipped) == len(promo)                      # a forecast per promo series-day, or its reason
    assert set(forecasts["series_key"]) <= set(inputs.series_key[promo].tolist()) and set(result.skipped["reason"]) <= {"no_regular_day", "no_day_factor"}
    assert result.rows == {"daily_cell": len(cells), "forecasts": len(forecasts), "mask_checks": result.rows["mask_checks"]} and result.rows["mask_checks"] > 0
    before = table_digest(db, run_key=True)
    again = run_day(connect(db), open_loaded_cube(first_day.mine.interim), world.bundle, RunMeta("run-day-1-again", first_day.spec.as_of), first_day.spec, world.view,
                    interim_dir=first_day.mine.interim)
    assert not again.issued and again.rows == {"daily_cell": 0, "forecasts": 0, "mask_checks": 0} and table_digest(db, run_key=True) == before        # issued once


def test_the_effect_of_the_day_is_the_observed_over_the_sealed_counterfactual_with_the_factor_of_that_day(first_day, world):
    inputs = day_inputs_of(first_day.mine, world.view, 20240626)
    cells = frame(first_day.mine.db, "SELECT * FROM daily_cell").set_index(["version", "cell_key"])
    from promolift.cube import group_index
    from promolift.recovery import recover_day

    values = {"raw": inputs.sales, "recovered": recover_day(world.bundle.recovery, inputs)}
    position = group_index(inputs.group, world.bundle.group_ids)
    for version, sales in values.items():
        view = CubeView(np.asarray(sales, dtype=np.float32)[:, None, :], np.array([20240626], dtype=np.int32))
        b = day_factor(view, world.bundle.cf[version], regular_mask(inputs.state[:, None]), position)
        cf = replace(world.bundle.cf[version], b=b, days=view.date_keys)
        rec = records(view, cf, (inputs.state == PROMO)[:, None], position)
        row = cells.loc[(version, "all")]
        assert row["observed"] == pytest.approx(rec.observed.sum()) and row["counterfactual"] == pytest.approx(rec.counterfactual.sum())
        assert row["lift"] == pytest.approx(rec.observed.sum() / rec.counterfactual.sum() - 1) and row["series_days"] == len(rec.series)
        assert row["stockout_hours"] == int(inputs.stock[rec.series].sum())
        band = inputs.band[rec.series]
        for k in range(7):
            if (band == k).any():
                assert cells.loc[(version, f"b{k}"), "lift"] == pytest.approx(rec.observed[band == k].sum() / rec.counterfactual[band == k].sum() - 1)
    assert cells.loc[("recovered", "all"), "lift"] > cells.loc[("raw", "all"), "lift"]


def test_the_forecasts_of_the_day_are_the_four_methods_of_the_in_stock_hours_with_the_sealed_a_and_the_factor_of_the_day(first_day, world):
    inputs = day_inputs_of(first_day.mine, world.view, 20240626)
    forecasts = frame(first_day.mine.db, "SELECT * FROM forecasts WHERE scope = 'test'").set_index(["series_key", "method"])
    series = int(forecasts.index.get_level_values("series_key")[0])
    a = world.bundle.cf["recovered"].a[series]
    in_stock = inputs.stock[series] == 0
    assert forecasts.loc[(series, "f0_no_lift"), "observed_instock"] == pytest.approx(float(inputs.sales[series][in_stock].sum()))
    f0, f2a = forecasts.loc[(series, "f0_no_lift"), "forecast"], forecasts.loc[(series, "f2a_overall_lift"), "forecast"]
    assert f2a == pytest.approx(f0 * (1 + world.bundle.lifts["recovered"].overall)) and (f0 > 0) and np.isfinite(a).all()
    assert forecasts.loc[(series, "f2_cell_lift"), "forecast"] > 0 and forecasts.loc[(series, "f1_naive"), "forecast"] >= 0


def test_the_synthetic_mask_of_the_day_follows_its_seed_and_stores_what_each_method_estimates_next_to_the_truth(first_day, world):
    inputs = day_inputs_of(first_day.mine, world.view, 20240626)
    stored = frame(first_day.mine.db, "SELECT * FROM mask_checks")
    mask = mask_tail(inputs, world.bundle.pmf, np.random.default_rng([world.view.recovery.mask_seed_test, 20240626]))
    names = sorted(set(stored["method"]))
    chosen = candidate_name(world.bundle.recovery)
    assert set(names) == {"r1", chosen, "r3"} and "r0" not in names
    assert set(stored["day_state"]) <= {"promo", "regular"} and set(stored["run_key"]) == {"run-day-1"}
    methods = {"r1": Recovery("r1", None, world.bundle.recovery.base, None, world.bundle.group_ids), chosen: world.bundle.recovery,
               "r3": Recovery("r3", None, world.bundle.recovery.base, world.bundle.r3, world.bundle.group_ids)}
    for name in names:
        part = stored[stored["method"] == name].sort_values("series_key")
        assert part["series_key"].tolist() == sorted(inputs.series_key[mask.rows].tolist()) and part["cut_hour"].tolist() == mask.cut[np.argsort(inputs.series_key[mask.rows])].tolist()
        estimate, truth = hidden_mass(methods[name], inputs, mask)
        order = np.argsort(inputs.series_key[mask.rows])
        assert part["estimate"].to_numpy() == pytest.approx(estimate[order]) and part["hidden_mass"].to_numpy() == pytest.approx(truth[order])
        assert part["day_state"].tolist() == [STATE_NAMES[s] for s in inputs.state[mask.rows][order]]


def test_the_day_is_recovered_with_the_sealed_method_and_its_hours_are_stored_with_the_night_and_the_hours_with_stock_as_they_were(first_day, world):
    mine = first_day.mine
    recovered = open_recovered(mine.interim, "D2024-06-26")
    inputs = day_inputs_of(mine, world.view, 20240626)
    cube = open_loaded_cube(mine.interim)
    first, last = world.view.calendar.day_hours
    original, stock = np.asarray(cube.sales(20240626)), np.asarray(cube.stock(20240626))
    assert recovered.shape == (300, 1, 24)
    night = np.r_[0:first, last + 1:24]
    assert np.array_equal(recovered[:, 0, night], original[:, night])
    assert np.array_equal(recovered[:, 0, first:last + 1][stock[:, first:last + 1] == 0], original[:, first:last + 1][stock[:, first:last + 1] == 0])
    sums = frame(mine.db, "SELECT series_key, raw_sum, recovered_sum FROM series_days WHERE date_key = 20240626 ORDER BY series_key")
    assert sums["recovered_sum"].to_numpy() == pytest.approx(recovered[:, 0, first:last + 1].sum(axis=1, dtype=np.float64))
    whole_day = stock[:, first:last + 1].sum(axis=1) == 0
    assert sums["recovered_sum"].to_numpy()[whole_day] == pytest.approx(sums["raw_sum"].to_numpy()[whole_day])
    assert query(mine.db, "SELECT COUNT(*) FROM series_days WHERE recovered_sum IS NULL AND date_key <= 20240626")[0][0] == 0
    assert (inputs.stock == 1).any()


# --- no leak, the size of the delivery, and what a day may be ------------------------------------------------------------------------------------


def test_another_day_of_the_test_changes_nothing_that_this_day_issues(world, published, first_day, store_upto, tmp_path):
    """Every later day is already loaded, and in the second run scrambled: the issue of the first day is the same one, byte for byte (RNF06 b)."""
    full = store_upto("C2024-07-03")
    spec = first_day.spec
    expected = table_digest(first_day.mine.db)
    for name, scramble in (("plain", False), ("scrambled", True)):
        folder = tmp_path / name
        folder.mkdir()
        shutil.copyfile(full.db, folder / "w.sqlite")

        def modify(delivery_id, date_keys, sales, scramble=scramble):
            if scramble and delivery_id not in ("L2024-06-25", "D2024-06-26"):
                sales *= 3.0
            return sales

        interim = rebuilt_interim(published, folder / "interim", modify)
        conn = connect(folder / "w.sqlite")
        try:
            run_day(conn, open_loaded_cube(interim), world.bundle, RunMeta("run-26", spec.as_of), spec, world.view, interim_dir=interim)
        finally:
            conn.close()
        assert table_digest(folder / "w.sqlite") == expected, name


@pytest.mark.slow
def test_daily_figures_are_identical_with_one_day_and_seven_day_deliveries(world, published, canonical, cfg, tmp_path):
    from promolift.deliveries import publish, read_delivery

    one_by_one = world.loader(tmp_path / "one_by_one")
    for spec in [s for s in published.plan if s.kind == "daily"]:
        world.load(one_by_one, spec.delivery_id, canonical.series)
        conn = connect(one_by_one.db)
        try:
            run_day(conn, open_loaded_cube(one_by_one.interim), world.bundle, RunMeta(f"run-{spec.delivery_id}", spec.as_of), spec, world.view, interim_dir=one_by_one.interim)
        finally:
            conn.close()
    seven = world.loader(tmp_path / "seven")
    spec7 = DeliverySpec("D2024-06-26_7", "daily", date(2024, 6, 26), date(2024, 7, 2), datetime(2024, 7, 3))
    entry = publish(spec7, canonical, tmp_path / "d7", cfg)
    days, cube = read_delivery(tmp_path / "d7", entry)
    conn = connect(seven.db)
    try:
        load_delivery(conn, days, cube, spec7, "run-7", cfg, sha256=entry.sha256, series=canonical.series, interim_dir=seven.interim)
        result = run_day(conn, open_loaded_cube(seven.interim), world.bundle, RunMeta("run-7", spec7.as_of), spec7, world.view, interim_dir=seven.interim)
    finally:
        conn.close()
    assert result.date_keys == tuple(range(20240626, 20240629)) + (20240629, 20240630, 20240701, 20240702) or len(result.date_keys) == 7
    assert table_digest(one_by_one.db) == table_digest(seven.db)
    assert query(one_by_one.db, "SELECT COUNT(DISTINCT date_key) FROM daily_cell")[0][0] == 7 and query(seven.db, "SELECT COUNT(*) FROM forecasts")[0][0] > 7 * 100


def test_a_day_that_is_not_the_one_of_its_delivery_is_refused_before_anything_is_written(first_day, world, published, store_upto, tmp_path):
    db = tmp_path / "w.sqlite"
    shutil.copyfile(first_day.mine.db, db)
    interim = tmp_path / "interim"
    shutil.copytree(first_day.mine.interim, interim)
    before = table_digest(db, run_key=True)
    cube = open_loaded_cube(interim)
    conn = connect(db)
    try:
        spec = first_day.spec
        for bad, match in ((replace(spec, kind="close", first_day=None, last_day=None), "diaria"), (replace(spec, kind="launch"), "diaria"),
                           (DeliverySpec("D2024-06-27", "daily", date(2024, 6, 27), date(2024, 6, 27), datetime(2024, 6, 28)), "no está cargada"),
                           (DeliverySpec("D2024-06-20", "daily", date(2024, 6, 20), date(2024, 6, 20), datetime(2024, 6, 21)), "lanzamiento")):
            with pytest.raises(ScoringError, match=match):
                run_day(conn, cube, world.bundle, RunMeta("run-x", bad.as_of), bad, world.view, interim_dir=interim)
        with pytest.raises(ScoringError, match="instante"):
            run_day(conn, cube, world.bundle, RunMeta("run-x", datetime(2024, 6, 25)), spec, world.view, interim_dir=interim)
    finally:
        conn.close()
    assert table_digest(db, run_key=True) == before


def test_the_close_issues_nothing_and_the_two_steps_can_be_run_apart(world, published, canonical, tmp_path):
    mine = world.loader(tmp_path / "apart")
    spec = world.load(mine, "D2024-06-26", canonical.series)
    conn = connect(mine.db)
    try:
        cube = open_loaded_cube(mine.interim)
        run = RunMeta("run-apart", spec.as_of)
        recovered = recover_delivery(conn, cube, world.bundle, spec, run, world.view, interim_dir=mine.interim)
        assert recovered.shape == (300, 1, 24) and query(mine.db, "SELECT COUNT(*) FROM daily_cell")[0][0] == 0           # recovering emits no effect yet
        result = estimate_delivery(conn, cube, world.bundle, spec, run, world.view, recovered=recovered)
        assert result.issued and result.rows["daily_cell"] > 10
        repeated = recover_delivery(conn, cube, world.bundle, spec, run, world.view, interim_dir=mine.interim)
        assert np.array_equal(repeated, recovered)                                                                          # recovering again changes nothing
    finally:
        conn.close()


def test_a_day_never_keeps_the_mapped_days_of_the_cube_alive_together(world, canonical, tmp_path, monkeypatch):
    import weakref

    from promolift.cube import LoadedCube

    mine = world.loader(tmp_path / "views")
    spec = world.load(mine, "D2024-06-26", canonical.series)
    refs: list = []
    peak = [0]
    original = LoadedCube._load

    def watch(self, date_key, field):
        out = original(self, date_key, field)
        refs.append(weakref.ref(out))
        peak[0] = max(peak[0], sum(ref() is not None for ref in refs))
        return out

    monkeypatch.setattr(LoadedCube, "_load", watch)
    conn = connect(mine.db)
    try:
        run_day(conn, open_loaded_cube(mine.interim), world.bundle, RunMeta("run-views", spec.as_of), spec, world.view, interim_dir=mine.interim)
    finally:
        conn.close()
    assert len(refs) > 7 and peak[0] <= 3, peak[0]
