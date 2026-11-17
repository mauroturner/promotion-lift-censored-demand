"""Ranking of promotion cells with intervals: management group x discount depth, adjusted (recovered demand).

There is no promotion identifier in the data. A "promotion" here is a cell: a management group and a depth band
of the discount, on days with activity_flag = 1. Each cell's lift is measured against the same series' non-promo
days (V4 of s08: within series, hour matched, recovered demand). Intervals: bootstrap over series (B=500, seed 0).
Two cells "do not separate" when their intervals overlap. Train block only.
"""
import sys
from pathlib import Path
from itertools import combinations

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import train_only  # noqa: E402
from estimators import bootstrap_weights, weighted_ratio, recover, v_matched  # noqa: E402

meta, S, ST, T = train_only()
TS, TST, TP, TD = T["sales"], T["stock"], T["promo"], T["discount"]
n_series = T["n_series"]
valid = (TD > 0) & (TD <= 1.0)
group_of_series = meta.groupby("series").management_group_id.first().reindex(range(n_series)).to_numpy()
Wb = bootstrap_weights(n_series, B=500, seed=0)

# Recovered demand: promo state from activity_flag, imputation on all valid days (as s08, V4).
R, _, _ = recover(TS, TST, TP, valid)
bad_sh = (np.isnan(R) & valid[:, :, None]).any(axis=1)  # series-hours with no in-stock value (as s08, V4)
hour_ok = ~bad_sh
nm = (TP == 0) & valid
bands = [(0.0, 0.5), (0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 0.95), (0.95, 1.0)]
MIN_SERIES = 30  # below this a cell's bootstrap interval is not stable enough to rank


def band_label(lo, hi):
    return f"({lo:.2f}, {hi:.2f}]" if lo == 0.0 else f"[{lo:.2f}, {hi:.2f})" if hi < 1.0 else f"[{lo:.2f}, 1.00)"


def cell_result(pm):
    A, Bv, ok = v_matched(R, pm, nm, hour_ok=hour_ok)
    n_ok = int(ok.sum())
    n_days = int(pm.sum())
    if n_ok == 0:
        return None
    point = A.sum() / Bv.sum() - 1
    boot = weighted_ratio(A, Bv, Wb)
    boot = boot[np.isfinite(boot)]  # draws where the cell has no series in the sample are dropped
    lo, hi = np.quantile(boot, [0.025, 0.975])
    return point, lo, hi, n_ok, n_days


cells = {}
print("== Cells: management group x depth band (promo days = activity_flag 1, valid discount)")
print(f"{'group':>5} {'band':>14} {'series':>7} {'promo days':>11} {'lift':>9} {'95% interval':>22}")
for g in sorted(np.unique(group_of_series)):
    gsel = group_of_series == g
    for lo, hi in bands:
        if lo == 0.0:
            band = (TD > lo) & (TD <= hi)
        elif hi == 1.0:
            band = (TD >= lo) & (TD <= hi)
        else:
            band = (TD >= lo) & (TD < hi)
        pm = (TP == 1) & valid & band & gsel[:, None]
        res = cell_result(pm)
        if res is None:
            continue
        point, lo_ci, hi_ci, n_ok, n_days = res
        if n_ok < MIN_SERIES:
            print(f"{int(g):>5} {band_label(lo, hi):>14} {n_ok:>7,} {n_days:>11,} {point*100:+8.2f}%  (fewer than {MIN_SERIES} series: not ranked)")
            continue
        key = (int(g), band_label(lo, hi))
        cells[key] = (point, lo_ci, hi_ci, n_ok, n_days)
        print(f"{int(g):>5} {band_label(lo, hi):>14} {n_ok:>7,} {n_days:>11,} {point*100:+8.2f}% [{lo_ci*100:+8.2f}; {hi_ci*100:+8.2f}]")


def overlaps(a, b):
    return not (a[2] < b[1] or b[2] < a[1])


def pair_summary(items, name):
    pairs = list(combinations(items, 2))
    overlap = sum(1 for a, b in pairs if overlaps(items[a], items[b]))
    print(f"\n== Pairs of {name}: {len(pairs)}; pairs whose intervals overlap (do not separate): {overlap}; separated: {len(pairs) - overlap}")
    ranked = sorted(items.items(), key=lambda kv: -kv[1][0])
    for i, (k, v) in enumerate(ranked[:5], start=1):
        print(f"   rank {i}: {k} lift {v[0]*100:+.2f}% [{v[1]*100:+.2f}; {v[2]*100:+.2f}] series={v[3]:,}")
    top = ranked[0][1]
    overlapping_top = [k for k, v in ranked[1:] if overlaps(top, v)]
    print(f"   cells whose interval overlaps the top cell's: {len(overlapping_top)} of {len(ranked)-1}")


pair_summary(cells, "management-group x depth cells")

print("\n== By management group only (all depth bands together)")
by_group = {}
for g in sorted(np.unique(group_of_series)):
    gsel = group_of_series == g
    res = cell_result((TP == 1) & valid & gsel[:, None])
    if res is not None:
        by_group[int(g)] = res
        print(f"   group {int(g)}: lift {res[0]*100:+.2f}% [{res[1]*100:+.2f}; {res[2]*100:+.2f}] series={res[3]:,} promo days={res[4]:,}")
pair_summary(by_group, "management groups")

print("\n== By depth band only (all groups together)")
by_band = {}
for lo, hi in bands:
    if lo == 0.0:
        band = (TD > lo) & (TD <= hi)
    elif hi == 1.0:
        band = (TD >= lo) & (TD <= hi)
    else:
        band = (TD >= lo) & (TD < hi)
    pm_b = (TP == 1) & valid & band
    res = cell_result(pm_b)
    if res is not None:
        by_band[band_label(lo, hi)] = res
        A, Bv, ok = v_matched(R, pm_b, nm, hour_ok=hour_ok)
        r_s = A[ok & (Bv > 0)] / Bv[ok & (Bv > 0)] - 1
        print(f"   band {band_label(lo, hi)}: lift {res[0]*100:+.2f}% [{res[1]*100:+.2f}; {res[2]*100:+.2f}] series={res[3]:,} promo days={res[4]:,}; "
              f"median of series-level lifts {np.median(r_s)*100:+.2f}%")
pair_summary(by_band, "depth bands")
