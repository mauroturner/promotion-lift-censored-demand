"""The state of a day and its band (U04; RF04, D03, D04, D13; AC04): the rules of plan section 8, every edge of them tested one by one (project
05's B1: a rule written right whose edges nobody tested), with the config that carries them (sealed or not)."""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from promolift.config import SealedConfig
from promolift.days import ANOMALOUS, PROMO, REGULAR, STATE_NAMES, UNFLAGGED, band_of, day_band, day_state
from tests.fixtures import hand_cases as hc

SEEN = "a" * 64


def view_with(cfg, **changes):
    return dataclasses.replace(cfg, days=dataclasses.replace(cfg.days, **changes))


def test_every_boundary_of_the_day_state_and_band_rules(cfg):
    flags = np.array([row[0] for row in hc.STATE_EDGES])
    discounts = np.array([row[1] for row in hc.STATE_EDGES])
    for view in (cfg, SealedConfig.of(cfg, SEEN, SEEN)):
        states = day_state(flags, discounts, view)
        assert states.dtype == np.int8 and states.shape == flags.shape
        assert [STATE_NAMES[code] for code in states] == [row[2] for row in hc.STATE_EDGES]
        assert band_of(discounts, view).tolist() == [row[3] for row in hc.STATE_EDGES]
        stored = day_band(states, discounts, view)
        assert stored.dtype == np.int8 and stored.tolist() == [-1 if row[4] is None else row[4] for row in hc.STATE_EDGES]


def test_the_codes_and_names_are_the_ones_the_fixture_and_the_tables_use():
    assert (PROMO, REGULAR, UNFLAGGED, ANOMALOUS) == (0, 1, 2, 3) and STATE_NAMES == ("promo", "regular", "unflagged_cut", "anomalous")


def test_the_rules_follow_the_configuration_not_constants(cfg):
    """Every threshold is read from [days]: moving one moves the edge that it names and no other."""
    flags, discounts = np.array([0, 0, 0, 1]), np.array([0.99, 0.999, 1.0, 0.7])
    assert day_state(flags, discounts, cfg).tolist() == [UNFLAGGED, REGULAR, REGULAR, PROMO]
    assert day_state(flags, discounts, view_with(cfg, regular_min_discount=0.99)).tolist() == [REGULAR, REGULAR, REGULAR, PROMO]
    assert day_state(flags, discounts, view_with(cfg, regular_min_discount=1.0)).tolist() == [UNFLAGGED, UNFLAGGED, REGULAR, PROMO]
    low = view_with(cfg, anomalous_max_discount=0.75)
    assert day_state(np.array([0, 1, 0]), np.array([0.75, 0.7, 0.8]), low).tolist() == [ANOMALOUS, ANOMALOUS, UNFLAGGED]
    high = view_with(cfg, anomalous_min_discount=1.05)
    assert day_state(np.array([0, 0]), np.array([1.05, 1.06]), high).tolist() == [REGULAR, ANOMALOUS]
    moved = view_with(cfg, bands=(0.0, 0.25, 0.75, 1.0))
    assert band_of(np.array([0.1, 0.25, 0.74, 0.75, 1.0, 0.0, 1.5]), moved).tolist() == [0, 1, 1, 2, 2, -1, -1]
    assert day_band(day_state(np.array([1, 0, 0, 1]), np.array([0.1, 0.8, 1.0, 0.75]), moved), np.array([0.1, 0.8, 1.0, 0.75]), moved).tolist() == [0, 2, -1, 2]


def test_the_rules_handle_a_whole_column_without_changing_its_shape_or_inputs(cfg):
    rng = np.random.default_rng(0)
    flags = rng.integers(0, 2, 10_000).astype(np.int8)
    discounts = np.round(rng.uniform(-0.1, 1.2, 10_000), 3)
    before = (flags.copy(), discounts.copy())
    states = day_state(flags, discounts, cfg)
    assert states.shape == (10_000,) and set(np.unique(states)) == {PROMO, REGULAR, UNFLAGGED, ANOMALOUS}
    assert np.array_equal(flags, before[0]) and np.array_equal(discounts, before[1])
    # the same rule written out with a loop
    for flag, discount, state in zip(flags[:500], discounts[:500], states[:500]):
        if discount <= 0 or discount > 1:
            expected = ANOMALOUS
        elif flag == 1:
            expected = PROMO
        else:
            expected = REGULAR if discount >= 0.999 else UNFLAGGED
        assert state == expected
    assert day_state(np.array([], dtype=np.int8), np.array([]), cfg).shape == (0,)
    two_d = day_state(flags[:100].reshape(10, 10), discounts[:100].reshape(10, 10), cfg)
    assert two_d.shape == (10, 10) and np.array_equal(two_d.reshape(-1), states[:100])


def test_a_discount_that_is_not_a_number_is_anomalous_and_has_no_band(cfg):
    discounts = np.array([np.nan, np.inf, -np.inf])
    assert day_state(np.array([1, 0, 1]), discounts, cfg).tolist() == [ANOMALOUS] * 3
    assert band_of(discounts, cfg).tolist() == [-1, -1, -1]


def test_a_discount_stored_with_float32_noise_goes_where_its_clean_twin_goes(cfg):
    """The real file stores 0.9 both as 0.9 and as 0.8999999761581421 (D13's note of 2026-11-17): the noise must not move a row to the band below."""
    clean = np.array([0.7, 0.8, 0.9, 0.95, 0.6, 0.999])
    noisy = np.array([0.699999988079071, 0.7999993562698364, 0.8999999761581421, 0.949999988079071, 0.6000000238418579, 0.9990000128746033])
    assert float(np.float32(0.9)) != 0.9 and abs(float(np.float32(0.9)) - 0.9) < 1e-7, "the noisy values are the float32 neighbours of the clean ones"
    assert band_of(noisy, cfg).tolist() == band_of(clean, cfg).tolist() == [3, 4, 5, 6, 2, 6]
    flags = np.zeros(6, dtype=np.int8)
    assert day_state(flags, noisy, cfg).tolist() == day_state(flags, clean, cfg).tolist()
    # a cut that is really below an edge stays below it: the tolerance is far under the 0.001 step of the discounts that are meant
    below = np.array([0.8999989, 0.89999, 0.4999989, 0.99899])
    assert band_of(below, cfg).tolist() == [4, 4, 0, 6] and day_state(flags[:4], below, cfg).tolist() == [UNFLAGGED] * 4
    assert day_state(np.array([0]), np.array([0.9989995]), cfg).tolist() == [REGULAR], "0.999 less 5e-7 is the 0.999 of float32"
