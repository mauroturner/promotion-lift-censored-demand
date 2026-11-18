"""The ranking of the cells and the groups that cannot be told apart (U08; RF15, D13; AC17)."""

from __future__ import annotations

import numpy as np

from promolift.ranking import overlap_pairs, overlapping_pairs, rank_cells
from tests.fixtures import hand_cases as hc


def arrays():
    cells = hc.TIERS_CELLS
    return (np.array([c[1] for c in cells]), np.array([c[2] for c in cells]), np.array([c[3] for c in cells]), [c[0] for c in cells])


def test_overlapping_cells_share_a_tier():
    lift, low, high, names = arrays()
    ranked = rank_cells(lift, low, high, np.full(5, 100), 30)
    assert dict(zip(names, ranked["tier"].tolist(), strict=True)) == hc.TIERS_EXPECTED["tier"]
    assert dict(zip(names, ranked["rank"].tolist(), strict=True)) == {"a": 1, "b": 2, "c": 3, "d": 4, "e": 5} and ranked["ranked"].all()


def test_the_pairs_that_overlap_are_counted_exactly_and_touching_intervals_overlap():
    lift, low, high, names = arrays()
    pairs = overlap_pairs(low, high, list(range(5)))
    assert {(names[i], names[j]) for i, j in pairs} == hc.TIERS_EXPECTED["overlapping_pairs"]
    assert overlapping_pairs(low, high, list(range(5))) == (hc.TIERS_EXPECTED["pairs"], len(hc.TIERS_EXPECTED["overlapping_pairs"]))
    assert overlapping_pairs(low, high, [0, 1]) == (1, 1) and overlapping_pairs(low, high, [0]) == (0, 0)


def test_a_tier_is_not_a_chain_by_the_first_cell_only_a_cell_that_overlaps_no_one_of_the_open_group_starts_another():
    # b overlaps a, c overlaps b but not a: c still joins the open group, because it overlaps one of its cells; d overlaps nobody and opens the next
    lift = np.array([0.9, 0.7, 0.5, 0.1])
    low, high = np.array([0.8, 0.6, 0.4, -0.2]), np.array([1.0, 0.8, 0.6, 0.3])
    assert rank_cells(lift, low, high, np.full(4, 50), 30)["tier"].tolist() == [1, 1, 1, 2]


def test_cells_below_min_series_are_not_ranked():
    lift, low, high, _ = arrays()
    series = np.array([100, 29, 30, 100, 100])
    out = rank_cells(lift, low, high, series, 30)
    assert out["ranked"].tolist() == [True, False, True, True, True]
    assert out["rank"].isna().tolist() == [False, True, False, False, False] and out["tier"].isna().tolist() == [False, True, False, False, False]
    assert out["rank"].dropna().tolist() == [1, 2, 3, 4] and out["tier"].dropna().tolist() == [1, 2, 3, 3]


def test_a_cell_without_a_lift_or_an_interval_is_not_ranked_and_the_order_follows_the_lift_not_the_input_order():
    lift = np.array([0.1, np.nan, 0.9, 0.5])
    low, high = np.array([0.0, np.nan, 0.8, 0.4]), np.array([0.2, np.nan, 1.0, 0.6])
    out = rank_cells(lift, low, high, np.full(4, 100), 30)
    assert out["ranked"].tolist() == [True, False, True, True] and out["rank"].tolist()[0] == 3 and out["rank"].tolist()[2] == 1 and out["rank"].tolist()[3] == 2
    assert list(out.columns) == ["lift", "ci_low", "ci_high", "series", "ranked", "rank", "tier"] and out["lift"].tolist()[:1] == [0.1]
