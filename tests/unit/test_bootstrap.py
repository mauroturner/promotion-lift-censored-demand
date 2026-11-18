"""The intervals (U08; RF14, D12; AC16): the two-way weights, whole series and whole days, seeded; and the series-only draws of the criteria."""

from __future__ import annotations

import itertools

import numpy as np
import pytest

from promolift.bootstrap import interval, series_draws, two_way_draws, weighted_sums
from promolift.effect import Records
from tests.fixtures import hand_cases as hc


def hand_records() -> Records:
    observed, counter = hc.BOOTSTRAP["observed"], hc.BOOTSTRAP["counterfactual"]
    series, day = np.nonzero(np.ones(observed.shape, dtype=bool))
    return Records(series, day, observed[series, day], counter[series, day], 3, 2, 0)


def compositions(total: int, parts: int):
    """Every way to give `parts` units a whole number of draws that adds up to `total`."""
    for cut in itertools.combinations_with_replacement(range(parts), total):
        yield np.bincount(cut, minlength=parts)


def possible_lifts(rec: Records, with_days: bool) -> list[float]:
    out = []
    day_options = list(compositions(rec.n_days, rec.n_days)) if with_days else [np.ones(rec.n_days, dtype=int)]
    for sw in compositions(rec.n_series, rec.n_series):
        for dw in day_options:
            num, den = weighted_sums(rec, np.zeros(len(rec.series), dtype=np.int64), 1, sw, dw)
            if den[0] > 0:
                out.append(float(num[0] / den[0] - 1))
    return out


def test_the_weighted_sums_of_three_series_and_two_days_are_the_ones_written_by_hand():
    rec = hand_records()
    unit = np.zeros(6, dtype=np.int64)
    for series_weights, day_weights, observed, counter, lift in hc.BOOTSTRAP["draws"]:
        num, den = weighted_sums(rec, unit, 1, np.array(series_weights), np.array(day_weights))
        assert (num[0], den[0]) == (observed, counter) and num[0] / den[0] - 1 == pytest.approx(lift)


def test_two_way_draws_weight_whole_series_and_whole_days_and_are_seeded():
    rec = hand_records()
    unit = np.zeros(6, dtype=np.int64)
    draws = two_way_draws(rec, unit, 1, 400, 0)
    assert draws.shape == (400, 1)
    allowed = possible_lifts(rec, True)
    assert len(allowed) > 10
    for value in draws[:, 0]:                                  # every draw is the lift of some whole number of copies of each series and each day
        assert min(abs(value - a) for a in allowed) < 1e-12
    assert len(np.unique(draws.round(12))) > 5                  # and they are not all the same one
    again, other = two_way_draws(rec, unit, 1, 400, 0), two_way_draws(rec, unit, 1, 400, 1)
    assert np.array_equal(draws, again) and not np.array_equal(draws, other)


def test_the_series_only_variant_keeps_every_day_once():
    rec = hand_records()
    draws = two_way_draws(rec, np.zeros(6, dtype=np.int64), 1, 300, 0, days=False)
    allowed = possible_lifts(rec, False)
    assert all(min(abs(v - a) for a in allowed) < 1e-12 for v in draws[:, 0])
    assert not np.array_equal(draws, two_way_draws(rec, np.zeros(6, dtype=np.int64), 1, 300, 0, days=True))


def test_each_unit_gets_its_own_lift_from_the_same_weights_and_a_unit_without_records_is_nan():
    rec = hand_records()
    unit = np.array([0, 0, 1, 1, 1, 1])
    draws = two_way_draws(rec, unit, 3, 50, 0)
    assert draws.shape == (50, 3) and np.isnan(draws[:, 2]).all()
    whole = two_way_draws(rec, np.zeros(6, dtype=np.int64), 1, 50, 0)
    num0, num1 = [two_way_draws(Records(rec.series, rec.day, rec.observed * (unit == u), rec.counterfactual * (unit == u), 3, 2, 0), np.zeros(6, dtype=np.int64),
                                1, 50, 0) for u in (0, 1)]
    assert np.isfinite(whole).all() and np.isfinite(num0[np.isfinite(num0)]).all() and np.isfinite(draws[:, :2][np.isfinite(draws[:, :2])]).all()


def test_two_versions_of_the_same_records_share_their_weights_so_their_difference_is_paired():
    rec = hand_records()
    doubled = Records(rec.series, rec.day, 2 * rec.observed + rec.counterfactual, rec.counterfactual, 3, 2, 0)      # lift' = 2 * lift + 2 draw by draw
    a, b = (two_way_draws(r, np.zeros(6, dtype=np.int64), 1, 100, 5) for r in (rec, doubled))
    assert np.allclose(b, 2 * a + 2)


def test_the_interval_is_the_2_5_and_97_5_percentiles_of_each_column_and_ignores_nan():
    draws = np.column_stack([np.arange(101, dtype=float), np.full(101, np.nan), np.r_[np.arange(100, dtype=float), np.nan]])
    low, high = interval(draws)
    assert low[0] == pytest.approx(2.5) and high[0] == pytest.approx(97.5) and np.isnan(low[1]) and np.isnan(high[1])
    assert low[2] == pytest.approx(2.475) and high[2] == pytest.approx(96.525)


def test_series_draws_weight_whole_series_pair_the_columns_and_are_seeded():
    numerators = np.array([[1.0, 4.0], [2.0, 2.0], [3.0, 1.0]])
    denominator = np.array([10.0, 10.0, 10.0])
    draws = series_draws(numerators, denominator, 200, 0)
    assert draws.shape == (200, 2)
    allowed = [[float(w @ numerators[:, k] / (w @ denominator)) for k in range(2)] for w in compositions(3, 3)]
    for row in draws:
        assert min(abs(row[0] - a[0]) + abs(row[1] - a[1]) for a in allowed) < 1e-12      # both columns come from one set of weights
    assert np.array_equal(draws, series_draws(numerators, denominator, 200, 0)) and not np.array_equal(draws, series_draws(numerators, denominator, 200, 1))
