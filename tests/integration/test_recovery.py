"""The recovery on the synthetic fixture (U07; RF09, D06; AC14): the candidates of the configuration, R3's fit and what each method does with hours it may
touch and hours it may not. The tripwire M01 joins this file in U09."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from promolift.cube import load_block, open_loaded_cube
from promolift.masks import first_stockout_pmf, mask_tail
from promolift.recovery import candidate_name, candidates, estimate, hidden_mass, recover_day
from promolift.split import block_of
from promolift.warehouse import connect

LAUNCH = "L2024-06-25"


@pytest.fixture(scope="module")
def train(store_upto, quick_cfg):
    store = store_upto(LAUNCH)
    cube = open_loaded_cube(store.interim)
    conn = connect(store.db)
    try:
        keys = cube.date_keys
        block = load_block(cube, conn, keys, quick_cfg)
    finally:
        conn.close()
    days = pd.to_datetime([f"{k // 10000}-{k // 100 % 100:02d}-{k % 100:02d}" for k in keys])
    in_train = block_of(days, quick_cfg).to_numpy() == "train"
    pmf = first_stockout_pmf(block.stock, in_train)
    return block, in_train, pmf, candidates(block, in_train, pmf, quick_cfg)


def test_the_candidates_are_r1_r2_with_each_kappa_in_ascending_order_and_r3(train, quick_cfg):
    _block, _days, _pmf, recoveries = train
    kappas = sorted(quick_cfg.recovery.kappas)
    assert [candidate_name(r) for r in recoveries] == ["r1", *[f"r2@{k:g}" for k in kappas], "r3"]
    assert [r.kappa for r in recoveries] == [None, *kappas, None]
    assert recoveries[-1].r3 is not None and all(r.r3 is None for r in recoveries[:-1])
    assert all(r.base is recoveries[0].base for r in recoveries)          # one base: the methods differ in what they do with it, not in what they learn


def test_a_method_changes_only_hours_without_stock_and_never_makes_negative_demand(train):
    block, _days, _pmf, recoveries = train
    day = block.day(60)                                                    # a day of the validation: the methods were fitted on the training days
    assert (day.stock == 1).any()
    for rec in recoveries:
        recovered = recover_day(rec, day)
        in_stock = day.stock == 0
        assert np.array_equal(recovered[in_stock], day.sales[in_stock]), rec.method
        assert np.isfinite(recovered).all() and (recovered >= 0).all(), rec.method
        assert (recovered[~in_stock] > 0).any(), rec.method                   # and it does put some demand back


def test_every_method_beats_zero_on_the_mass_of_a_tail_mask_of_the_validation_blocks(train):
    block, _days, pmf, recoveries = train
    rng = np.random.default_rng(0)
    totals = {}
    for position in range(54, 63):                                          # V1 of the fixture: 2024-06-08 to 06-16
        inputs = block.day(position)
        mask = mask_tail(inputs, pmf, rng)
        for rec in recoveries:
            est, true = hidden_mass(rec, inputs, mask)
            totals.setdefault(candidate_name(rec), [0.0, 0.0])
            totals[candidate_name(rec)][0] += float(np.abs(est - true).sum())
            totals[candidate_name(rec)][1] += float(true.sum())
    assert all(err / mass < 0.9 for err, mass in totals.values()), totals       # zero would be exactly 1.0


def test_r3_fits_the_same_model_twice(train, quick_cfg):
    block, in_train, pmf, recoveries = train
    again = candidates(block, in_train, pmf, quick_cfg)[-1]
    day = block.day(60)
    assert np.array_equal(estimate(recoveries[-1], day), estimate(again, day))
