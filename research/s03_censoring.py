"""How stockouts censor observed sales: how often, when, where, and what they do to observed sales.

Train split only (2024-03-28 to 2024-06-25). The window 06-21 is the one the card uses for stock_hour6_22_cnt
(the count is the hours 6 to 21 inclusive; s01 verified it). Night hours are reported separately.
Observed sales during a stockout are not demand: this script measures the drop, it does not recover demand.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import train_only  # noqa: E402

meta, S, ST, T = train_only()
TS, TST, TP = T["sales"], T["stock"], T["promo"]
TD = T["discount"]
W = slice(6, 22)  # hours 6 to 21 inclusive
print("== Prevalence (window 06-21, train)")
print(f"stockout share of series-hours: {TST[:, :, W].mean()*100:.2f}%")
by_hour = pd.Series(TST[:, :, W].mean(axis=(0, 1)), index=range(6, 22))
print("by hour (06..21):", (by_hour * 100).round(1).to_dict())
dow = pd.Series(meta.dt.dt.dayofweek.values)
share_day = TST[:, :, W].mean(axis=(0, 2))  # per day
dow_day = pd.Series(pd.date_range(meta.dt.min(), periods=T["n_days"], freq="D").dayofweek)
print("by weekday (0=Mon .. 6=Sun):", (pd.Series(share_day).groupby(dow_day.values).mean() * 100).round(2).to_dict())
per_series = TST[:, :, W].mean(axis=(1, 2))
print(f"per-series stockout share (window): min={per_series.min()*100:.2f}% p10={np.quantile(per_series,0.10)*100:.2f}% median={np.median(per_series)*100:.2f}% p90={np.quantile(per_series,0.90)*100:.2f}% max={per_series.max()*100:.2f}%")

print("\n== By category (management group, 7 values)")
grp = meta.groupby("series").management_group_id.first().reindex(range(T["n_series"])).to_numpy()
for g in sorted(np.unique(grp)):
    sel = grp == g
    print(f"   group {int(g)}: series={int(sel.sum()):,} stockout share={TST[sel][:, :, W].mean()*100:.2f}%")

print("\n== Sales in stockout hours versus in-stock hours (same series, same hour, window 06-21)")
# For every series x hour: mean sales with status 1 and with status 0 (over days where both exist).
s1 = (TST[:, :, W] == 1)
s0 = (TST[:, :, W] == 0)
sales_w = TS[:, :, W]
n1 = s1.sum(axis=1)
n0 = s0.sum(axis=1)
m1 = np.where(n1 > 0, (sales_w * s1).sum(axis=1) / np.maximum(n1, 1), np.nan)
m0 = np.where(n0 > 0, (sales_w * s0).sum(axis=1) / np.maximum(n0, 1), np.nan)
ok = ~np.isnan(m1) & ~np.isnan(m0)
print(f"series-hour pairs with both states: {int(ok.sum()):,} of {m1.size:,}")
print(f"share of those pairs where stockout sales are below in-stock sales: {np.mean(m1[ok] < m0[ok])*100:.2f}%")
ratio = (m1[ok].sum()) / (m0[ok].sum())
print(f"sales-weighted ratio stockout / in-stock across pairs: {ratio:.4f} (drop of {(1-ratio)*100:.2f}%)")
print(f"mean sales | stockout = {sales_w[s1].mean():.4f}; | in stock = {sales_w[s0].mean():.4f}")
print(f"share of stockout hours with positive sales: {(sales_w[s1] > 0).mean()*100:.2f}%")
print(f"share of in-stock hours with zero sales: {(sales_w[s0] == 0).mean()*100:.2f}%")

print("\n== Night hours (0-5, 22-23) for comparison (not in the window)")
night = [0, 1, 2, 3, 4, 5, 22, 23]
print(f"stockout share at night: {TST[:, :, night].mean()*100:.2f}%; mean sales at night stockout: {TS[:, :, night][TST[:, :, night] == 1].mean():.4f}")

print("\n== Does a promotion raise the stockout share? (within series, window 06-21)")
pday = TP.astype(bool)  # (series, day)
share_sd = TST[:, :, W].mean(axis=2)  # (series, day)
diffs = []
for s in range(T["n_series"]):
    a = pday[s]
    if a.any() and (~a).any():
        diffs.append(share_sd[s, a].mean() - share_sd[s, ~a].mean())
diffs = np.array(diffs)
print(f"series with both promo and non-promo days: {len(diffs):,}")
print(f"mean within-series difference in stockout share (promo minus non-promo): {diffs.mean()*100:+.2f} points")
print(f"median: {np.median(diffs)*100:+.2f} points; share of series with a higher stockout share on promo days: {np.mean(diffs > 0)*100:.2f}%")
rng = np.random.default_rng(0)
boot = [np.mean(diffs[rng.integers(0, len(diffs), len(diffs))]) for _ in range(500)]
print(f"bootstrap 95% interval over series (B=500, seed 0): [{np.quantile(boot,0.025)*100:+.2f}; {np.quantile(boot,0.975)*100:+.2f}] points")

print("\n== Stockout share by discount depth on promo days (window 06-21, depth from the discount field)")
dd = TD[pday]
ss = share_sd[pday]
edges = [0.0, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 1.0001]
for lo, hi in zip(edges[:-1], edges[1:]):
    sel = (dd > lo) & (dd <= hi) if lo > 0 else (dd > 0) & (dd <= hi)
    if sel.any():
        print(f"   ({lo:.2f}, {min(hi,1.0):.2f}]: promo days={int(sel.sum()):,} stockout share={ss[sel].mean()*100:.2f}%")
