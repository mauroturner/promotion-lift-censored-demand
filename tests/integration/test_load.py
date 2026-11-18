"""The warehouse (U06; RF08, D22; AC07, AC08): a delivery is added to SQLite in one transaction with the staging table rebuilt for its instant and
the controls of the load; a control with rows undoes everything, down to the file; the SQL rule of the day states is the Python one at every
boundary; and the staging blocks are those of ``split.block_of``."""

from __future__ import annotations

import dataclasses
import hashlib
import shutil
import sqlite3
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from promolift import warehouse
from promolift.days import STATE_NAMES, day_band, day_state
from promolift.split import BLOCKS, block_of
from promolift.warehouse import (
    CheckFailedError,
    DeliveryAlreadyLoadedError,
    EmptyDeliveryError,
    apply_schema,
    connect,
    load_delivery,
    rebuild_staging,
    run_checks,
    sql_params,
)
from tests.fixtures import hand_cases as hc

SHA = "a" * 64
CHECKS = ["chk_day_state_rules", "chk_delivery_period", "chk_hours_add_up", "chk_profile_matches_days", "chk_series_day_unique"]


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest() if Path(path).exists() else ""


def failing(checks) -> list[str]:
    return [c.check_id for c in checks if c.violations]


def tables(conn) -> list[str]:
    return [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]


def spec_of(published, delivery_id):
    return next(s for s in published.plan if s.delivery_id == delivery_id)


def load(conn, published, canonical, cfg, delivery_id, *, days=None, cube=None, series=None, run_key="run-1"):
    entry, own_days, own_cube = published.items[delivery_id]
    return load_delivery(conn, own_days if days is None else days, own_cube if cube is None else cube, spec_of(published, delivery_id), run_key, cfg,
                         sha256=entry.sha256, series=canonical.series if series is None else series)


@pytest.fixture
def db(tmp_path):
    return tmp_path / "w.sqlite"


@pytest.fixture(scope="module")
def launched_db(published, canonical, cfg, tmp_path_factory):
    """A warehouse that holds the launch, built once: the tests that start from a loaded launch work on a copy of it."""
    path = tmp_path_factory.mktemp("launched") / "w.sqlite"
    conn = connect(path)
    try:
        load(conn, published, canonical, cfg, "L2024-06-25")
    finally:
        conn.close()
    return path


@pytest.fixture
def after_launch(launched_db, tmp_path):
    path = tmp_path / "w.sqlite"
    shutil.copyfile(launched_db, path)
    return path


# --- a first load -----------------------------------------------------------------------------------------------------------------------------


def test_the_launch_is_loaded_with_its_series_days_its_sums_and_its_profile(db, published, canonical, cfg, fixture_truth):
    conn = connect(db)
    try:
        result = load(conn, published, canonical, cfg, "L2024-06-25")
        entry, days, _cube = published.items["L2024-06-25"]
        assert (result.delivery_id, result.as_of, result.series_days) == ("L2024-06-25", datetime(2024, 6, 26), 27000)
        assert [c.check_id for c in result.checks] == [*CHECKS, "chk_sums_match_cube"] and failing(result.checks) == []
        assert result.staged == 27000 and result.profile_rows > 0
        assert conn.execute("SELECT COUNT(*) FROM series").fetchone()[0] == 300 and conn.execute("SELECT COUNT(*) FROM series_days").fetchone()[0] == 27000
        assert conn.execute("SELECT * FROM deliveries").fetchall() == [("L2024-06-25", "launch", "2024-03-28", "2024-06-25", "2024-06-26 00:00:00", 27000,
                                                                      entry.sha256, "loaded", "run-1")]
        stored = pd.read_sql_query("SELECT * FROM series_days ORDER BY date_key, series_key", conn)
        assert stored["series_key"].tolist() == days["series_key"].tolist() and stored["date_key"].tolist() == days["date_key"].tolist()
        assert stored["day_state"].tolist() == [STATE_NAMES[c] for c in days["day_state"]]
        assert stored["band"].isna().tolist() == (days["band"] < 0).tolist() and stored["band"].dropna().astype(int).tolist() == days["band"][days["band"] >= 0].tolist()
        for column in ("activity_flag", "holiday_flag", "discount", "raw_sum", "instock_hours", "stockout_hours", "instock_sum"):
            assert np.array_equal(stored[column].to_numpy(), days[column].to_numpy()), column
        assert stored["recovered_sum"].isna().all() and (stored["fully_out"] == (days["instock_hours"] == 0)).all()
        assert stored["delivery_id"].eq("L2024-06-25").all()
        series = pd.read_sql_query(f"SELECT {', '.join(canonical.series.columns)} FROM series ORDER BY series_key", conn)
        pd.testing.assert_frame_equal(series, canonical.series, check_dtype=False)      # the series are the canonical ones
        assert not conn.in_transaction
    finally:
        conn.close()


def test_the_hour_profile_is_the_sale_and_the_stockouts_of_every_hour_by_day_group_and_state(db, published, canonical, cfg):
    conn = connect(db)
    try:
        load(conn, published, canonical, cfg, "L2024-06-25")
        group = canonical.series.set_index("series_key")["management_group_id"].to_numpy()
        state = canonical.series_days.pivot(index="series_key", columns="date_key", values="day_state")
        rows = conn.execute("SELECT date_key, management_group_id, hour, day_state, series_days, sales_sum, stockout_count FROM hour_profile").fetchall()
        assert {r[2] for r in rows} == set(range(24)) and {r[3] for r in rows} <= set(STATE_NAMES) and len({r[3] for r in rows}) >= 3
        for date_key, g, hour, name, n, sales_sum, out_count in rows[::97][:80]:
            members = (group == g) & (state[date_key].to_numpy() == STATE_NAMES.index(name))
            day = canonical.date_keys.tolist().index(date_key)
            assert n == int(members.sum())
            assert sales_sum == pytest.approx(float(canonical.sales[members, day, hour].astype(np.float64).sum()), abs=1e-9)
            assert out_count == int(canonical.stock[members, day, hour].sum())
        assert conn.execute("SELECT COUNT(DISTINCT hour) FROM hour_profile").fetchone()[0] == 24
        assert conn.execute("SELECT MIN(date_key), MAX(date_key) FROM hour_profile").fetchone() == (20240328, 20240625)
    finally:
        conn.close()


def test_failed_check_rolls_back_a_first_load(db, published, canonical, cfg):
    """A control with rows undoes the first load down to the tables: the file exists (SQLite created it) and holds nothing, and the next load works."""
    _entry, days, _cube = published.items["L2024-06-25"]
    broken = days.copy()
    broken.loc[10, "instock_hours"] = broken.loc[10, "instock_hours"] + 1          # instock + stockout hours are not the 16 analysis hours any more
    conn = connect(db)
    try:
        with pytest.raises(CheckFailedError, match=r"La carga se deshizo.*chk_hours_add_up: 1 filas") as raised:
            load(conn, published, canonical, cfg, "L2024-06-25", days=broken)
        assert failing(raised.value.checks) == ["chk_hours_add_up"] and not conn.in_transaction
        assert tables(conn) == [], "the schema was created inside the transaction and went with it"
    finally:
        conn.close()
    conn = connect(db)
    try:
        assert tables(conn) == []
        assert load(conn, published, canonical, cfg, "L2024-06-25").series_days == 27000
    finally:
        conn.close()


def test_a_failed_load_leaves_the_file_as_it_was_byte_for_byte(after_launch, published, canonical, cfg):
    db = after_launch
    before = sha(db)
    _entry, days, cube = published.items["D2024-06-26"]
    bad_state = days.copy()
    bad_state.loc[3, "day_state"] = (bad_state.loc[3, "day_state"] + 1) % 4         # a state that the stored flag and discount do not give
    bad_sum = days.copy()
    bad_sum.loc[5, "raw_sum"] += 0.5                                               # a sum that is not the cube's
    for name, broken, expected in (("state", bad_state, "chk_day_state_rules"), ("sum", bad_sum, "chk_sums_match_cube")):
        conn = connect(db)
        try:
            with pytest.raises(CheckFailedError, match=expected):
                load(conn, published, canonical, cfg, "D2024-06-26", days=broken)
            assert not conn.in_transaction
        finally:
            conn.close()
        assert sha(db) == before, name


# --- the plan, loaded delivery after delivery ----------------------------------------------------------------------------------------------------


def test_the_whole_plan_loads_and_the_staging_holds_the_days_that_had_closed_at_each_instant(db, published, canonical, cfg):
    conn = connect(db)
    try:
        held = 0
        for spec in published.plan:
            result = load(conn, published, canonical, cfg, spec.delivery_id, run_key=f"run-{spec.delivery_id}")
            entry = published.items[spec.delivery_id][0]
            held += entry.series_days
            assert result.series_days == entry.series_days and result.as_of == spec.as_of and failing(result.checks) == []
            assert result.staged == held if spec.kind != "close" else result.staged == 29100
            assert conn.execute("SELECT COUNT(*) FROM stg_series_days").fetchone()[0] == result.staged
            assert conn.execute("SELECT MAX(date_key) FROM stg_series_days").fetchone()[0] < spec.as_of.year * 10000 + spec.as_of.month * 100 + spec.as_of.day
        assert conn.execute("SELECT COUNT(*) FROM series_days").fetchone()[0] == 29100 and conn.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0] == 9
        assert conn.execute("SELECT status, COUNT(*) FROM deliveries GROUP BY status").fetchall() == [("loaded", 9)]
        assert conn.execute("SELECT series_days FROM deliveries WHERE kind = 'close'").fetchone() == (0,)
        assert failing(run_checks(conn, "load", sql_params(spec.as_of, cfg))) == []
    finally:
        conn.close()


def test_an_empty_delivery_is_refused_except_the_close_which_must_be_empty(after_launch, published, canonical, cfg):
    conn = connect(after_launch)
    try:
        _entry, days, cube = published.items["D2024-06-26"]
        empty_cube = (cube[0][:0], cube[1][:, :0], cube[2][:, :0])
        with pytest.raises(EmptyDeliveryError, match="no tiene series-días.*el almacén queda como estaba"):
            load(conn, published, canonical, cfg, "D2024-06-26", days=days.iloc[0:0], cube=empty_cube)
        with pytest.raises(ValueError, match="el cierre no tiene series-días"):
            load(conn, published, canonical, cfg, "C2024-07-03", days=days, cube=cube)
        assert conn.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0] == 1 and not conn.in_transaction
        for spec in published.plan[1:-1]:
            load(conn, published, canonical, cfg, spec.delivery_id)
        result = load(conn, published, canonical, cfg, "C2024-07-03")
        assert result.series_days == 0 and result.profile_rows == 0 and result.staged == 29100
    finally:
        conn.close()


def test_a_delivery_that_is_already_loaded_is_refused_and_changes_nothing(after_launch, published, canonical, cfg):
    db = after_launch
    before = sha(db)
    conn = connect(db)
    try:
        with pytest.raises(DeliveryAlreadyLoadedError, match="La entrega L2024-06-25 ya está cargada"):
            load(conn, published, canonical, cfg, "L2024-06-25", run_key="run-2")
        assert not conn.in_transaction
    finally:
        conn.close()
    assert sha(db) == before


def test_a_series_day_that_is_repeated_inside_the_delivery_or_already_loaded_rolls_everything_back(after_launch, published, canonical, cfg):
    db = after_launch
    before = sha(db)
    _entry, days, _cube = published.items["D2024-06-26"]
    repeated = pd.concat([days, days.iloc[[4]]], ignore_index=True)
    earlier = days.copy()
    earlier.loc[0, "date_key"] = 20240625                                           # a series-day of the launch
    for broken in (repeated, earlier):
        conn = connect(db)
        try:
            with pytest.raises(sqlite3.IntegrityError):
                load(conn, published, canonical, cfg, "D2024-06-26", days=broken)
            assert not conn.in_transaction
        finally:
            conn.close()
        assert sha(db) == before


def test_the_series_are_stored_once_and_a_series_whose_hierarchy_changed_is_refused(after_launch, published, canonical, cfg):
    db = after_launch
    conn = connect(db)
    try:
        load(conn, published, canonical, cfg, "D2024-06-26")
        assert conn.execute("SELECT COUNT(*) FROM series").fetchone()[0] == 300
        changed = canonical.series.copy()
        changed.loc[7, "management_group_id"] = (changed.loc[7, "management_group_id"] + 1) % 7
        before = sha(db)
        conn.close()
        conn = connect(db)
        with pytest.raises(ValueError, match=r"la serie 7 \(tienda \d+, producto \d+\) cambió de jerarquía"):
            load(conn, published, canonical, cfg, "D2024-06-27", series=changed)
        assert not conn.in_transaction and sha(db) == before
    finally:
        conn.close()


def test_a_delivery_without_a_column_of_its_schema_or_a_series_without_its_columns_is_a_wrong_delivery(db, published, canonical, cfg):
    conn = connect(db)
    try:
        days = published.items["L2024-06-25"][1]
        with pytest.raises(ValueError, match="faltan raw_sum"):
            load(conn, published, canonical, cfg, "L2024-06-25", days=days.drop(columns="raw_sum"))
        with pytest.raises(ValueError, match="faltan city_id"):
            load(conn, published, canonical, cfg, "L2024-06-25", series=canonical.series.drop(columns="city_id"))
        assert tables(conn) == []
    finally:
        conn.close()


# --- the controls, one by one -------------------------------------------------------------------------------------------------------------------------


@pytest.fixture
def loaded(after_launch):
    conn = connect(after_launch)
    yield conn
    conn.close()


def check(conn, cfg, name):
    (result,) = run_checks(conn, "load", sql_params(datetime(2024, 6, 26), cfg), only=[name])
    return result


@pytest.mark.parametrize(("name", "damage"), [
    ("chk_day_state_rules", "UPDATE series_days SET day_state = 'regular' WHERE rowid IN (SELECT rowid FROM series_days WHERE day_state = 'promo' LIMIT 3)"),
    ("chk_day_state_rules", "UPDATE series_days SET band = NULL WHERE rowid IN (SELECT rowid FROM series_days WHERE day_state = 'promo' LIMIT 1)"),
    ("chk_day_state_rules", "UPDATE series_days SET band = 6 WHERE rowid IN (SELECT rowid FROM series_days WHERE day_state = 'regular' LIMIT 1)"),
    ("chk_delivery_period", "UPDATE deliveries SET last_day = '2024-06-01'"),
    ("chk_delivery_period", "UPDATE deliveries SET series_days = series_days + 1"),
    ("chk_hours_add_up", "UPDATE series_days SET stockout_hours = stockout_hours + 1 WHERE series_key = 3 AND date_key = 20240401"),
    ("chk_hours_add_up", "UPDATE series_days SET fully_out = 1 - fully_out WHERE series_key = 3 AND date_key = 20240401"),
    ("chk_profile_matches_days", "UPDATE hour_profile SET sales_sum = sales_sum + 0.01 WHERE hour = 10 AND date_key = 20240401 AND management_group_id = 0"),
    ("chk_profile_matches_days", "UPDATE hour_profile SET stockout_count = stockout_count + 1 WHERE hour = 12 AND date_key = 20240402"),
    ("chk_profile_matches_days", "UPDATE hour_profile SET series_days = series_days + 1 WHERE hour = 7 AND date_key = 20240403"),
    ("chk_profile_matches_days", "DELETE FROM hour_profile WHERE date_key = 20240404"),
])
def test_each_control_finds_the_damage_that_it_is_for(loaded, cfg, name, damage):
    assert check(loaded, cfg, name).violations == 0
    loaded.execute("BEGIN")
    changed = loaded.execute(damage).rowcount
    assert changed >= 1
    assert check(loaded, cfg, name).violations >= 1, damage
    loaded.execute("ROLLBACK")
    assert check(loaded, cfg, name).violations == 0


def test_a_profile_row_with_no_series_days_is_found(loaded, cfg):
    loaded.execute("BEGIN")
    loaded.execute("INSERT INTO hour_profile VALUES (20240101, 0, 10, 'promo', 5, 1.0, 0, 'L2024-06-25')")
    result = check(loaded, cfg, "chk_profile_matches_days")
    loaded.execute("ROLLBACK")
    assert result.violations == 1 and result.sample[0][-1] == "profile_without_days"


def test_the_control_of_unique_series_days_finds_a_repeat_in_a_table_without_its_key(cfg):
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.execute("CREATE TABLE series_days (series_key INTEGER, date_key INTEGER)")
    conn.executemany("INSERT INTO series_days VALUES (?, ?)", [(1, 20240328), (1, 20240328), (2, 20240328)])
    (result,) = run_checks(conn, "load", sql_params(datetime(2024, 6, 26), cfg), only=["chk_series_day_unique"])
    assert (result.violations, result.sample) == (1, [(1, 20240328, 2)])


def test_the_control_against_the_cube_checks_a_fixed_sample_of_the_stored_sums(loaded, published, cfg):
    from promolift.warehouse import SAMPLE_SERIES_DAYS, check_sums_match_cube

    assert SAMPLE_SERIES_DAYS == 1000
    cube = published.items["L2024-06-25"][2]
    spec = spec_of(published, "L2024-06-25")
    clean = check_sums_match_cube(loaded, spec, cube, cfg)
    assert (clean.check_id, clean.violations, clean.sample) == ("chk_sums_match_cube", 0, [])
    rows = loaded.execute("SELECT series_key, date_key FROM series_days WHERE delivery_id = 'L2024-06-25' ORDER BY date_key, series_key").fetchall()
    positions = np.linspace(0, len(rows) - 1, 1000).astype(int)
    inside, outside = rows[positions[10]], next(r for i, r in enumerate(rows) if i not in set(positions.tolist()))
    for victim, expected in ((inside, 1), (outside, 0)):
        loaded.execute("BEGIN")
        loaded.execute("UPDATE series_days SET raw_sum = raw_sum + 0.001 WHERE series_key = ? AND date_key = ?", victim)
        assert check_sums_match_cube(loaded, spec, cube, cfg).violations == expected
        loaded.execute("ROLLBACK")
    loaded.execute("BEGIN")
    loaded.execute("UPDATE series_days SET instock_hours = instock_hours - 1, stockout_hours = stockout_hours + 1 WHERE series_key = ? AND date_key = ?", inside)
    assert check_sums_match_cube(loaded, spec, cube, cfg).violations == 1
    loaded.execute("ROLLBACK")
    short = loaded.execute("SELECT COUNT(*) FROM series_days").fetchone()[0]
    assert short == 27000


# --- the rule of the day state, in SQL and in Python ---------------------------------------------------------------------------------------------------


def scaffold(conn, n):
    conn.execute("INSERT INTO deliveries VALUES ('X', 'launch', '2024-03-28', '2024-06-25', '2024-06-26 00:00:00', ?, 'x', 'loaded', 'r')", (n,))
    for i in range(n):
        conn.execute("INSERT INTO series VALUES (?, ?, 1, ?, 0, 40, 20, 100)", (i, 10 * i + 3, 500 + i))


def insert_edges(conn, view, flags, discounts):
    states = day_state(flags, discounts, view)
    bands = day_band(states, discounts, view)
    rows = [(i, 20240328, "X", STATE_NAMES[int(states[i])], None if bands[i] < 0 else int(bands[i]), int(flags[i]), float(discounts[i]), 0, 1.0, 16, 0, 1.0, None, 0)
            for i in range(len(flags))]
    conn.executemany("INSERT INTO series_days VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    return states, bands


def test_sql_and_python_day_states_agree_on_every_boundary(db, cfg):
    """The rule of D04 and D13 in SQL accepts the state and the band that ``days`` gives at every edge of the hand cases, with the flag on and off, and
    names exactly the rows whose state or band is changed: so the two rules are one rule. Also under another [days] configuration."""
    flags = np.array([row[0] for row in hc.STATE_EDGES])
    discounts = np.array([row[1] for row in hc.STATE_EDGES])
    moved = dataclasses.replace(cfg, days=dataclasses.replace(cfg.days, regular_min_discount=0.99, anomalous_min_discount=1.05, bands=(0.0, 0.3, 0.75, 1.0)))
    for view in (cfg, moved):
        conn = connect(db)
        try:
            apply_schema(conn)
            scaffold(conn, len(flags))
            states, _bands = insert_edges(conn, view, flags, discounts)
            params = sql_params(datetime(2024, 6, 26), view)
            (result,) = run_checks(conn, "load", params, only=["chk_day_state_rules"])
            assert result.violations == 0, (view.days, result.sample)
            if view is cfg:
                assert [STATE_NAMES[int(s)] for s in states] == [row[2] for row in hc.STATE_EDGES]
            # change the state of every row to another state: every row is found, none is missed
            conn.execute("UPDATE series_days SET day_state = CASE day_state WHEN 'promo' THEN 'regular' WHEN 'regular' THEN 'unflagged_cut' "
                         "WHEN 'unflagged_cut' THEN 'anomalous' ELSE 'promo' END")
            assert run_checks(conn, "load", params, only=["chk_day_state_rules"])[0].violations == len(flags)
            # restore the states and move every stored band by one: only the rows that have a band are found
            conn.execute("DELETE FROM series_days")
            insert_edges(conn, view, flags, discounts)
            conn.execute("UPDATE series_days SET band = band + 1 WHERE band IS NOT NULL")
            with_band = conn.execute("SELECT COUNT(*) FROM series_days WHERE band IS NOT NULL").fetchone()[0]
            assert run_checks(conn, "load", params, only=["chk_day_state_rules"])[0].violations == with_band > 0
        finally:
            conn.close()
        db.unlink()


def test_the_rule_in_sql_follows_the_threshold_it_is_given_and_the_float32_noise(db, cfg):
    conn = connect(db)
    try:
        apply_schema(conn)
        flags = np.zeros(6, dtype=np.int8)
        discounts = np.array([0.8999999761581421, 0.699999988079071, 0.9, 0.9990000128746033, 0.8999989, 0.5])
        scaffold(conn, 6)
        insert_edges(conn, cfg, flags, discounts)
        params = sql_params(datetime(2024, 6, 26), cfg)
        assert run_checks(conn, "load", params, only=["chk_day_state_rules"])[0].violations == 0
        assert conn.execute("SELECT band FROM series_days ORDER BY series_key").fetchall() == [(5,), (3,), (5,), (None,), (4,), (1,)]
        assert run_checks(conn, "load", {**params, "edge_tolerance": 0.0}, only=["chk_day_state_rules"])[0].violations == 2
        assert run_checks(conn, "load", {**params, "regular_min_discount": 0.9995}, only=["chk_day_state_rules"])[0].violations >= 1
    finally:
        conn.close()


# --- the blocks of the staging --------------------------------------------------------------------------------------------------------------------------


def test_the_blocks_of_the_staging_are_those_of_split_block_of_under_two_partitions(after_launch, cfg):
    conn = connect(after_launch)
    try:
        alternative = dataclasses.replace(cfg, split=dataclasses.replace(
            cfg.split, train=(date(2024, 3, 28), date(2024, 5, 20)), purge=(date(2024, 5, 21), date(2024, 5, 27)),
            valid_v1=(date(2024, 5, 29), date(2024, 6, 12)), valid_v2=(date(2024, 6, 14), date(2024, 6, 25))))
        for view in (cfg, alternative):
            rebuild_staging(conn, datetime(2024, 6, 26), view)
            stored = pd.read_sql_query("SELECT DISTINCT date_key, block FROM stg_series_days ORDER BY date_key", conn)
            days = pd.DatetimeIndex(pd.to_datetime(stored["date_key"].astype(str), format="%Y%m%d"))
            python = block_of(days, view)
            assert python.tolist() == stored["block"].tolist() and len(stored) == 90
            assert set(stored["block"]) <= set(BLOCKS) and {"train", "purge", "valid_v1", "valid_v2"} <= set(stored["block"])
        assert "outside" in set(pd.read_sql_query("SELECT DISTINCT block FROM stg_series_days", conn)["block"]), "the alternative leaves days in no window"
    finally:
        conn.close()


def test_the_staging_for_an_instant_holds_the_days_that_had_closed_at_it_whatever_the_warehouse_holds_since(after_launch, published, canonical, cfg):
    conn = connect(after_launch)
    try:
        for spec in published.plan[1:4]:
            load(conn, published, canonical, cfg, spec.delivery_id)
        checks = rebuild_staging(conn, datetime(2024, 6, 27), cfg)
        assert failing(checks) == [] and conn.execute("SELECT COUNT(*), MAX(date_key) FROM stg_series_days").fetchone() == (27300, 20240626)
        rebuild_staging(conn, datetime(2024, 6, 26), cfg)
        assert conn.execute("SELECT COUNT(*), MAX(date_key) FROM stg_series_days").fetchone() == (27000, 20240625)
        rebuild_staging(conn, datetime(2024, 3, 28), cfg)
        assert conn.execute("SELECT COUNT(*) FROM stg_series_days").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM series_days").fetchone()[0] == 27900, "the series-days themselves are not touched"
        columns = [r[1] for r in conn.execute("PRAGMA table_info(stg_series_days)")]
        assert columns[:3] == ["series_key", "date_key", "delivery_id"] and "block" in columns and "management_group_id" in columns
    finally:
        conn.close()


def test_a_failed_staging_rebuild_leaves_the_warehouse_as_it_was(after_launch, cfg):
    conn = connect(after_launch)
    try:
        before = conn.execute("SELECT COUNT(*) FROM stg_series_days").fetchone()[0]
        conn.execute("UPDATE series_days SET stockout_hours = stockout_hours + 1 WHERE series_key = 1 AND date_key = 20240401")
        with pytest.raises(CheckFailedError, match=r"La preparación de las series-días \(staging\) se deshizo.*chk_hours_add_up"):
            rebuild_staging(conn, datetime(2024, 6, 27), cfg)
        assert not conn.in_transaction and conn.execute("SELECT COUNT(*) FROM stg_series_days").fetchone()[0] == before
    finally:
        conn.close()
    assert warehouse.CHECK_GROUPS == ("load", "model")
