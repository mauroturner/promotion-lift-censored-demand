"""No leak of information (U07, U10; RNF06, AC11, AC12): a hidden hour, another day and the size of a delivery change no estimate."""

from __future__ import annotations

import numpy as np
import pytest

from promolift.cube import InterimError, day_inputs, open_loaded_cube
from promolift.days import PROMO
from promolift.masks import apply, first_stockout_pmf, mask_tail
from promolift.recovery import Recovery, candidates, hidden_mass, recover_day
from promolift.warehouse import connect
from tests.fixtures.launching import rebuilt_interim

LAUNCH = "L2024-06-25"
ALL = "C2024-07-03"


@pytest.fixture(scope="module")
def launch_store(store_upto):
    return store_upto(LAUNCH)


@pytest.fixture(scope="module")
def full_store(store_upto):
    return store_upto(ALL)


@pytest.fixture(scope="module")
def train_candidates(launch_store, quick_cfg):
    """R1, R2 and R3 fitted on the training block of the launch (the quick configuration: a small R3)."""
    from promolift.cube import load_block
    from promolift.split import block_of

    import pandas as pd

    cube = open_loaded_cube(launch_store.interim)
    conn = connect(launch_store.db)
    try:
        keys = cube.date_keys
        days = pd.to_datetime([f"{k // 10000}-{k // 100 % 100:02d}-{k % 100:02d}" for k in keys])
        in_train = (block_of(days, quick_cfg).to_numpy() == "train")
        block = load_block(cube, conn, keys, quick_cfg)
    finally:
        conn.close()
    pmf = first_stockout_pmf(block.stock, in_train)
    return block, in_train, pmf, candidates(block, in_train, pmf, quick_cfg)


def read_day(store, date_key, cfg):
    cube = open_loaded_cube(store.interim)
    conn = connect(store.db)
    try:
        return day_inputs(cube, conn, date_key, cfg)
    finally:
        conn.close()


def test_changing_a_hidden_hour_changes_no_estimate(launch_store, train_candidates, quick_cfg):
    block, in_train, pmf, recoveries = train_candidates
    assert [r.method for r in recoveries][:1] == ["r1"] and "r3" in [r.method for r in recoveries]
    inputs = read_day(launch_store, 20240615, quick_cfg)
    mask = mask_tail(inputs, pmf, np.random.default_rng(0))
    assert len(mask.rows) > 20 and mask.hidden.any()
    changed_sales = inputs.sales.copy()
    rows, cols = np.nonzero(mask.hidden)
    changed_sales[mask.rows[rows], cols] = changed_sales[mask.rows[rows], cols] * 7.0 + 123.0          # the hidden values are anything else
    other = type(inputs)(inputs.series_key, inputs.date_key, inputs.hours, changed_sales, inputs.stock, inputs.state, inputs.band, inputs.group)
    assert not np.array_equal(other.sales, inputs.sales)
    for rec in recoveries:
        a, b = hidden_mass(rec, inputs, mask), hidden_mass(rec, other, mask)
        assert np.array_equal(a[0], b[0]), rec.method                       # the estimates: exact equality
        assert not np.array_equal(a[1], b[1])                                # the truth is the one thing that did change
        assert np.array_equal(recover_day(rec, apply(inputs, mask)), recover_day(rec, apply(other, mask)), equal_nan=True), rec.method


def test_the_day_that_is_not_delivered_yet_cannot_be_read(launch_store, quick_cfg):
    with pytest.raises(KeyError, match="20240626"):
        read_day(launch_store, 20240626, quick_cfg)


def test_another_day_changes_no_recovery_of_this_day(published, full_store, train_candidates, quick_cfg, tmp_path):
    _block, _in_train, _pmf, recoveries = train_candidates

    def scramble(delivery_id, date_keys, sales):
        if delivery_id == "D2024-06-27":                      # another day of the test week
            sales *= 3.0
        if delivery_id == LAUNCH:                              # and a day of the launch other than the one that is recovered
            sales[:, int(np.searchsorted(date_keys, 20240610)), :] += 5.0
        return sales

    plain = type(full_store)(full_store.db, rebuilt_interim(published, tmp_path / "plain"), full_store.loaded)
    scrambled = type(full_store)(full_store.db, rebuilt_interim(published, tmp_path / "scrambled", scramble), full_store.loaded)
    for date_key in (20240626, 20240620):
        a, b = read_day(plain, date_key, quick_cfg), read_day(scrambled, date_key, quick_cfg)
        assert np.array_equal(a.sales, b.sales) and np.array_equal(a.stock, b.stock)
        for rec in recoveries:
            assert np.array_equal(recover_day(rec, a), recover_day(rec, b)), (date_key, rec.method)
    changed = read_day(scrambled, 20240627, quick_cfg)
    assert not np.array_equal(changed.sales, read_day(plain, 20240627, quick_cfg).sales)      # the probe does change the day it changes


def test_a_cube_that_is_not_the_one_its_manifest_names_is_refused_before_any_day_is_read(published, tmp_path, quick_cfg, full_store):
    folder = rebuilt_interim(published, tmp_path / "cube")
    victim = next((folder / "cube").glob("D2024-06-26.sales.npy"))
    data = victim.read_bytes()
    victim.write_bytes(data[:-8] + bytes(b ^ 0xFF for b in data[-8:]))      # the last values change whatever they were
    with pytest.raises(InterimError, match="no coincide"):
        read_day(type(full_store)(full_store.db, folder, ()), 20240626, quick_cfg)


def test_the_inputs_of_a_day_are_what_the_cube_and_the_warehouse_hold_for_it(launch_store, canonical, quick_cfg):
    inputs = read_day(launch_store, 20240615, quick_cfg)
    day = canonical.date_keys.tolist().index(20240615)
    first, last = quick_cfg.calendar.day_hours
    assert inputs.date_key == 20240615 and inputs.hours.tolist() == list(range(first, last + 1)) and inputs.series_key.tolist() == list(range(300))
    assert np.array_equal(inputs.sales, canonical.sales[:, day, first:last + 1]) and np.array_equal(inputs.stock, canonical.stock[:, day, first:last + 1])
    frame = canonical.series_days[canonical.series_days["date_key"] == 20240615].sort_values("series_key")
    assert np.array_equal(inputs.state, frame["day_state"].to_numpy()) and np.array_equal(inputs.band, frame["band"].to_numpy())
    assert np.array_equal(inputs.group, canonical.series.sort_values("series_key")["management_group_id"].to_numpy())
    assert (inputs.state == PROMO).any()


def test_a_block_of_days_is_each_day_of_the_cube_in_the_order_asked_for(launch_store, canonical, quick_cfg):
    from promolift.cube import load_block

    cube = open_loaded_cube(launch_store.interim)
    conn = connect(launch_store.db)
    try:
        block = load_block(cube, conn, [20240615, 20240601, 20240620], quick_cfg)
    finally:
        conn.close()
    assert block.date_keys.tolist() == [20240615, 20240601, 20240620] and block.sales.shape == (300, 3, 16) and block.state.shape == (300, 3)
    for position, key in enumerate(block.date_keys.tolist()):
        day = canonical.date_keys.tolist().index(key)
        assert np.array_equal(block.sales[:, position, :], canonical.sales[:, day, 6:22]) and np.array_equal(block.stock[:, position, :], canonical.stock[:, day, 6:22])
        frame = canonical.series_days[canonical.series_days["date_key"] == key].sort_values("series_key")
        assert np.array_equal(block.state[:, position], frame["day_state"].to_numpy()) and np.array_equal(block.band[:, position], frame["band"].to_numpy())
        assert block.day(position).date_key == key and np.array_equal(block.day(position).sales, block.sales[:, position, :])


def test_a_block_of_more_series_than_an_int16_holds_keeps_every_series_key_and_state(quick_cfg):
    """The real file has 50,000 series: a key past 32,767 must not wrap (found by the dry run of the launch on the real train block)."""
    import sqlite3

    from promolift.cube import load_block

    n = 50_000
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE series (series_key INTEGER PRIMARY KEY, management_group_id INTEGER NOT NULL)")
    conn.execute("CREATE TABLE series_days (series_key INTEGER, date_key INTEGER, day_state TEXT, band INTEGER)")
    conn.executemany("INSERT INTO series VALUES (?, ?)", [(k, k % 7) for k in range(n)])
    conn.executemany("INSERT INTO series_days VALUES (?, 20240601, ?, ?)", [(k, "promo" if k % 2 else "regular", k % 7 if k % 2 else None) for k in range(n)])

    class Cube:
        n_series = n

        def sales(self, date_key):
            return np.ones((n, 24), dtype=np.float32)

        def stock(self, date_key):
            return np.zeros((n, 24), dtype=np.int8)

    block = load_block(Cube(), conn, [20240601], quick_cfg)
    assert block.series_key.tolist() == list(range(n)) and block.group.tolist() == [k % 7 for k in range(n)]
    assert block.state[:, 0].tolist() == [0 if k % 2 else 1 for k in range(n)] and block.band[:, 0].tolist() == [k % 7 if k % 2 else -1 for k in range(n)]
