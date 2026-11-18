"""The ranking of the cells and the groups that cannot be told apart (U08; RF15, D13; AC17)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from promolift.ranking import overlap_groups, overlap_pairs, pair_counts, rank_cells
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
    assert pair_counts(low, high, list(range(5))) == (hc.TIERS_EXPECTED["pairs"], len(hc.TIERS_EXPECTED["overlapping_pairs"]))
    assert pair_counts(low, high, [0, 1]) == (1, 1) and pair_counts(low, high, [0]) == (0, 0)


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


def _closed_group_case():
    cells = hc.CLOSED_GROUP_CELLS
    return (np.array([c[1] for c in cells]), np.array([c[2] for c in cells]), np.array([c[3] for c in cells]), [c[0] for c in cells])


def test_two_overlapping_cells_are_in_the_same_indistinguishable_group_even_when_one_overlaps_a_group_the_walk_closed():
    """B1 (L85): the groups are the connected components of the overlap graph (RF15), so r, which overlaps p and q, joins them in one group."""
    lift, low, high, names = _closed_group_case()
    ranked = rank_cells(lift, low, high, np.full(4, 100), 30)
    pairs = {(names[i], names[j]) for i, j in overlap_pairs(low, high, list(range(4)))}
    assert pairs == hc.CLOSED_GROUP_EXPECTED["overlapping_pairs"]
    assert dict(zip(names, overlap_groups(lift, low, high, ranked["ranked"]).tolist(), strict=True)) == hc.CLOSED_GROUP_EXPECTED["overlap_group"]


def test_the_sealed_tier_keeps_the_walk_the_seal_was_written_with():
    """The previous behavior, kept for the seal (D45): the walk compares a cell only with the open group, so r stays in q's tier and p keeps its own."""
    lift, low, high, names = _closed_group_case()
    assert dict(zip(names, rank_cells(lift, low, high, np.full(4, 100), 30)["tier"].tolist(), strict=True)) == hc.CLOSED_GROUP_EXPECTED["sealed_tier"]


def test_the_indistinguishable_groups_of_the_five_cells_and_of_unranked_cells():
    lift, low, high, names = arrays()
    assert dict(zip(names, overlap_groups(lift, low, high, np.ones(5, dtype=bool)).tolist(), strict=True)) == hc.TIERS_EXPECTED["tier"]
    ranked = np.array([True, False, True, True, True])     # without b, a and c do not overlap: a chain needs its middle cell
    assert overlap_groups(lift, low, high, ranked).tolist() == [1, pd.NA, 2, 3, 3]
    assert overlap_groups(np.array([]), np.array([]), np.array([]), np.array([], dtype=bool)).tolist() == []


def test_every_overlapping_pair_shares_a_group_and_every_group_is_connected_on_random_intervals():
    rng = np.random.default_rng(7)
    for _ in range(200):
        n = int(rng.integers(1, 30))
        lift = rng.normal(0, 1, n)
        low, high = lift - rng.uniform(0, 0.6, n), lift + rng.uniform(0, 0.6, n)
        group = np.array(overlap_groups(lift, low, high, np.ones(n, dtype=bool)).tolist())
        for i, j in overlap_pairs(low, high, list(range(n))):
            assert group[i] == group[j]
        for g in set(group.tolist()):
            members = np.flatnonzero(group == g)
            ordered = members[np.argsort(low[members])]
            assert all(low[c] <= high[ordered[:k]].max() for k, c in enumerate(ordered) if k), "a group is one connected segment"
        by_lift = group[np.argsort(-lift, kind="stable")]
        assert by_lift[0] == 1 and (np.diff(by_lift) >= 0).all() and set(by_lift.tolist()) == set(range(1, by_lift.max() + 1))
