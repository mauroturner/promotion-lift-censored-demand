"""The ranking of the cells and its indistinguishable groups (RF15, D13, D45; plan, section 13).

Only the cells with at least ``min_series`` series (and a lift and an interval) are ordered, from the largest lift down. Two cells whose intervals overlap, touching
included, are not presented as different (RF15): ``overlap_groups`` gives the connected components of the overlap graph of the ranked cells, numbered from the one with
the largest lift (1), and that is the indistinguishable group the star model, the dashboard and the site publish. The count of overlapping pairs is published with it.

``rank_cells`` keeps the ``tier`` the seal holds (D45): walking the order, a cell joins the open group if its interval overlaps that of any cell already in it, and otherwise
opens the next one. That walk never merges a cell into a group it already closed, so two overlapping cells can fall in different tiers (the evaluation's B1, L85); the
tier is kept because the launch and the test week were sealed with it, and it is published only as the sealed tier, never as the indistinguishable group.
"""

from __future__ import annotations

from itertools import combinations

import numpy as np
import pandas as pd


def _overlap(low: np.ndarray, high: np.ndarray, i: int, j: int) -> bool:
    return not (high[i] < low[j] or high[j] < low[i])


def overlap_pairs(low: np.ndarray, high: np.ndarray, ids: list[int]) -> list[tuple[int, int]]:
    """The pairs of `ids` (positions in `low` and `high`) whose intervals overlap; two that touch overlap."""
    return [(i, j) for i, j in combinations(ids, 2) if _overlap(low, high, i, j)]


def overlapping_pairs(low: np.ndarray, high: np.ndarray, ids: list[int]) -> tuple[int, int]:
    """``(pairs, overlapping)``: how many pairs `ids` form and how many of them overlap."""
    return len(ids) * (len(ids) - 1) // 2, len(overlap_pairs(low, high, ids))


def rank_cells(lift: np.ndarray, low: np.ndarray, high: np.ndarray, series: np.ndarray, min_series: int) -> pd.DataFrame:
    """One row per cell, in the order given: ``lift``, ``ci_low``, ``ci_high``, ``series``, ``ranked``, ``rank`` (1 = largest lift) and ``tier`` (the
    indistinguishable group); the last two are ``<NA>`` for a cell that is not ranked."""
    lift, low, high, series = (np.asarray(x, dtype=np.float64) for x in (lift, low, high, series))
    ranked = (series >= min_series) & np.isfinite(lift) & np.isfinite(low) & np.isfinite(high)
    positions = np.flatnonzero(ranked)
    order = positions[np.argsort(-lift[positions], kind="stable")]
    rank = pd.array([pd.NA] * len(lift), dtype="Int64")
    tier = pd.array([pd.NA] * len(lift), dtype="Int64")
    open_group: list[int] = []
    current = 0
    for place, cell in enumerate(order, start=1):
        if not open_group or not any(_overlap(low, high, cell, other) for other in open_group):
            current += 1
            open_group = []
        open_group.append(int(cell))
        rank[cell], tier[cell] = place, current
    return pd.DataFrame({"lift": lift, "ci_low": low, "ci_high": high, "series": series.astype(np.int64), "ranked": ranked, "rank": rank, "tier": tier})


def overlap_groups(lift: np.ndarray, low: np.ndarray, high: np.ndarray, ranked: np.ndarray) -> pd.arrays.IntegerArray:
    """The indistinguishable group of each cell (RF15, D45): the connected components of the graph whose nodes are the ranked cells and whose edges join two cells whose
    intervals overlap (touching included), numbered 1, 2, ... from the component of the cell with the largest lift; ``<NA>`` for a cell that is not ranked.

    Two overlapping cells are always in the same group, and a group is never split by a cell between them in the order: on a line, the union of a component's intervals is
    one segment, disjoint from the others, so the groups follow the order of the lifts."""
    lift, low, high = (np.asarray(x, dtype=np.float64) for x in (lift, low, high))
    positions = np.flatnonzero(np.asarray(ranked, dtype=bool))
    order = positions[np.argsort(-lift[positions], kind="stable")]
    parent = {int(cell): int(cell) for cell in order}

    def root(cell: int) -> int:
        while parent[cell] != cell:
            parent[cell] = parent[parent[cell]]
            cell = parent[cell]
        return cell

    for i, j in overlap_pairs(low, high, [int(cell) for cell in order]):
        parent[root(j)] = root(i)
    group = pd.array([pd.NA] * len(lift), dtype="Int64")
    number: dict[int, int] = {}
    for cell in order:            # walking from the largest lift, a component is numbered when its first cell is met
        top = root(int(cell))
        number.setdefault(top, len(number) + 1)
        group[cell] = number[top]
    return group


def spearman(x: np.ndarray, y: np.ndarray) -> float:
    """The rank correlation of two samples (ties take the mean rank), NaN if there are fewer than two points or one of them has no spread."""
    x, y = np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64)
    if len(x) < 2:
        return float("nan")
    return float(pd.Series(x).rank().corr(pd.Series(y).rank()))
