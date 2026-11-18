"""The ranking of the cells and its indistinguishable groups (RF15, D13; plan, section 13).

Only the cells with at least ``min_series`` series (and a lift and an interval) are ordered, from the largest lift down. Two cells whose intervals overlap, touching
included, are not presented as different: walking the order, a cell joins the open group if its interval overlaps that of any cell already in it, and otherwise
opens the next one. The tier is that group's number (1 is the one with the largest lifts), and the count of overlapping pairs is published with the ranking.
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
