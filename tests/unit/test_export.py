"""The example series-day of the star model (U12; plan, sections 19 and 21), by hand: the rule's edges one by one and the median of the candidates."""

from __future__ import annotations

import numpy as np
import pytest

from promolift.export import example_day


class FakeCube:
    def __init__(self, sales, stock):
        self._sales, self._stock = sales, stock

    def sales(self, key):
        return self._sales[key]

    def stock(self, key):
        return self._stock[key]


class View:
    class calendar:      # noqa: N801
        day_hours = (6, 21)


def build(cuts, sold_before=None, masses=None):
    """One day, one series per entry of `cuts` (the first clock hour without stock, or None for a series that never ran out); every hour before the cut sells 1 unit unless
    `sold_before[s]` limits how many hours sold. The recovered mass of series s is masses[s]."""
    n = len(cuts)
    sales, stock = np.zeros((n, 24), dtype=np.float32), np.zeros((n, 24), dtype=np.int8)
    for s, cut in enumerate(cuts):
        end = 22 if cut is None else cut
        k = end - 6 if sold_before is None or sold_before[s] is None else sold_before[s]
        sales[s, 6:6 + k] = 1.0
        if cut is not None:
            stock[s, cut:22] = 1
    recovered = np.zeros((n, 1, 24), dtype=np.float32)
    recovered[:, 0, 6] = masses if masses is not None else np.arange(n) + 1.0
    return FakeCube({20240601: sales}, {20240601: stock}), recovered


@pytest.mark.parametrize(("cut", "sold", "qualifies"), [
    (11, None, False), (12, None, True), (15, None, True), (18, None, True), (19, None, False),      # the first hour without stock: between 12 and 18, both included
    (15, 3, False), (15, 4, True), (None, None, False)])                                              # sold in at least 4 hours before it; a series that never ran out
def test_the_rule_takes_only_series_days_that_ran_out_between_12_and_18_after_selling_in_four_hours(cut, sold, qualifies):
    cube, recovered = build([cut], sold_before=[sold], masses=[30.0])
    found = example_day(cube, recovered, np.array([20240601], dtype=np.int32), View)
    assert (found is not None) == qualifies
    if qualifies:
        s, key, rows = found
        assert (s, key) == (0, 20240601) and rows[:, 0].tolist() == list(range(6, 22)) and rows[:, 2][0] == 30.0
        assert rows[:, 3].tolist() == [1] * (cut - 6) + [0] * (22 - cut) and rows[:, 1].tolist() == [1.0] * (sold if sold is not None else cut - 6) + [0.0] * (16 - (sold if sold is not None else cut - 6))


def test_with_an_even_number_of_candidates_the_lower_median_is_taken_and_ties_go_by_series_then_date():
    cube, recovered = build([13, 14, 15, 16], masses=[5, 5, 5, 9])
    s, _key, _rows = example_day(cube, recovered, np.array([20240601], dtype=np.int32), View)
    assert s == 1                                         # masses 5, 5, 5, 9 sorted by (mass, series): series 0, 1, 2, 3; index (4 - 1) // 2 = 1
    day, _ = build([15])
    two_days = FakeCube({20240601: day.sales(20240601), 20240602: day.sales(20240601)}, {20240601: day.stock(20240601), 20240602: day.stock(20240601)})
    both = np.zeros((1, 2, 24), dtype=np.float32)
    both[:, :, 6] = 7.0
    s, key, _ = example_day(two_days, both, np.array([20240601, 20240602], dtype=np.int32), View)
    assert (s, key) == (0, 20240601)                      # the same series on two dates with the same mass: the earlier date is the lower one


def test_no_series_day_that_qualifies_gives_none():
    cube, recovered = build([None, 10, 20])
    assert example_day(cube, recovered, np.array([20240601], dtype=np.int32), View) is None
