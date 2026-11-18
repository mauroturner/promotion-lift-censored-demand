"""The synthetic censoring (U07; RF10, D07; AC14): the distribution of the first stock-out hour, the tail mask over the series-days that were in stock all day,
the mask at random and what applying one does."""

from __future__ import annotations

import numpy as np
import pytest

from promolift.cube import DayInputs
from promolift.days import ANOMALOUS, PROMO, REGULAR, UNFLAGGED
from promolift.masks import Mask, apply, first_stockout_pmf, mask_random, mask_tail, truth

H = 4
HOURS = np.arange(6, 6 + H)


def day(stock: list[list[int]], state: list[int], sales: np.ndarray | None = None) -> DayInputs:
    n = len(stock)
    return DayInputs(
        series_key=np.arange(n, dtype=np.int32), date_key=20240601, hours=HOURS,
        sales=np.arange(n * H, dtype=np.float32).reshape(n, H) + 1.0 if sales is None else sales.astype(np.float32),
        stock=np.array(stock, dtype=np.int8), state=np.array(state, dtype=np.int8), band=np.full(n, 2, dtype=np.int8), group=np.zeros(n, dtype=np.int64))


def test_the_first_stockout_pmf_counts_the_first_hour_without_stock_of_each_series_day_of_the_chosen_days():
    # (series, days, hours): day 0 has the first stock-outs at hours 2, 0 and none; day 1 (not chosen) would move the mass to hour 3
    stock = np.zeros((3, 2, H), dtype=np.int8)
    stock[0, 0, 2:] = 1
    stock[1, 0, 0:] = 1
    stock[1, 0, 1] = 0        # the first one is what counts, not the run
    stock[0, 1, 3] = 1
    stock[1, 1, 3] = 1
    stock[2, 1, 3] = 1
    pmf = first_stockout_pmf(stock, np.array([True, False]))
    assert pmf.tolist() == [0.5, 0.0, 0.5, 0.0]
    both = first_stockout_pmf(stock, np.array([True, True]))
    assert both.tolist() == pytest.approx([1 / 5, 0.0, 1 / 5, 3 / 5]) and both.sum() == pytest.approx(1.0)


def test_a_pmf_without_a_single_stockout_is_refused_instead_of_dividing_by_zero():
    with pytest.raises(ValueError, match="sin stock"):
        first_stockout_pmf(np.zeros((2, 2, H), dtype=np.int8), np.array([True, True]))


def test_a_tail_mask_takes_only_series_days_with_stock_all_day_and_a_promo_or_regular_state():
    inputs = day(stock=[[0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 1, 0], [0, 0, 0, 0], [0, 0, 0, 0]], state=[PROMO, REGULAR, PROMO, UNFLAGGED, ANOMALOUS])
    mask = mask_tail(inputs, np.array([0.25, 0.25, 0.25, 0.25]), np.random.default_rng(0))
    assert mask.rows.tolist() == [0, 1] and mask.hidden.shape == (2, H) and mask.cut.shape == (2,)


def test_a_tail_mask_hides_from_its_cut_to_the_last_hour_and_the_cut_is_a_clock_hour():
    inputs = day(stock=[[0] * H] * 3, state=[PROMO] * 3)
    mask = mask_tail(inputs, np.array([0.0, 0.0, 1.0, 0.0]), np.random.default_rng(0))
    assert mask.cut.tolist() == [8, 8, 8] and mask.hidden.tolist() == [[False, False, True, True]] * 3


def test_the_cut_of_a_tail_mask_follows_the_pmf_with_100000_draws():
    pmf = np.array([0.1, 0.2, 0.3, 0.4])
    n = 100_000
    inputs = day(stock=[[0] * H] * n, state=[REGULAR] * n)
    mask = mask_tail(inputs, pmf, np.random.default_rng(7))
    frequency = np.bincount(mask.cut - HOURS[0], minlength=H) / n
    # the standard error of a frequency is at most sqrt(0.25 / 100000) = 0.0016: a tolerance of 0.01 is six of them
    assert np.abs(frequency - pmf).max() < 0.01


def test_the_same_seed_gives_the_same_mask_and_another_seed_another():
    n = 500
    inputs = day(stock=[[0] * H] * n, state=[PROMO] * n)
    pmf = np.full(H, 0.25)
    first, again, other = (mask_tail(inputs, pmf, np.random.default_rng(seed)) for seed in (3, 3, 4))
    assert np.array_equal(first.rows, again.rows) and np.array_equal(first.hidden, again.hidden) and np.array_equal(first.cut, again.cut)
    assert not np.array_equal(first.cut, other.cut)
    a, b = (mask_random(inputs, 2, np.random.default_rng(seed)) for seed in (3, 3))
    assert np.array_equal(a.hidden, b.hidden)


def test_a_random_mask_hides_exactly_that_many_hours_of_each_eligible_series_day_and_has_no_cut():
    inputs = day(stock=[[0] * H, [1, 0, 0, 0], [0] * H, [0] * H], state=[PROMO, PROMO, REGULAR, UNFLAGGED])
    mask = mask_random(inputs, 3, np.random.default_rng(1))
    assert mask.rows.tolist() == [0, 2] and (mask.hidden.sum(axis=1) == 3).all() and (mask.cut == -1).all()


def test_applying_a_mask_marks_the_hidden_hours_without_stock_and_removes_their_sale_and_changes_nothing_else():
    inputs = day(stock=[[0] * H] * 3, state=[PROMO, REGULAR, PROMO])
    mask = Mask(np.array([0, 2]), np.array([[False, False, True, True], [False, True, True, True]]), np.array([8, 7]))
    before = (inputs.sales.copy(), inputs.stock.copy())
    hidden = apply(inputs, mask)
    assert np.array_equal(inputs.sales, before[0]) and np.array_equal(inputs.stock, before[1])    # the inputs are not changed
    assert hidden.stock.tolist() == [[0, 0, 1, 1], [0, 0, 0, 0], [0, 1, 1, 1]]
    assert np.isnan(hidden.sales[0, 2:]).all() and np.isnan(hidden.sales[2, 1:]).all() and not np.isnan(hidden.sales[1]).any()
    keep = ~np.isnan(hidden.sales)
    assert np.array_equal(hidden.sales[keep], inputs.sales[keep])
    for name in ("series_key", "hours", "state", "band", "group"):
        assert np.array_equal(getattr(hidden, name), getattr(inputs, name))
    assert hidden.date_key == inputs.date_key


def test_the_truth_of_a_mask_is_the_sale_of_the_hidden_hours_and_zero_elsewhere():
    inputs = day(stock=[[0] * H] * 2, state=[PROMO, PROMO], sales=np.array([[1.0, 2.0, 3.0, 4.0], [5.0, 6.0, 7.0, 8.0]]))
    mask = Mask(np.array([1]), np.array([[False, True, False, True]]), np.array([7]))
    assert truth(inputs, mask).tolist() == [[0.0, 6.0, 0.0, 8.0]]
