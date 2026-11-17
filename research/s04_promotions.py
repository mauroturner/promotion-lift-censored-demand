"""How promotions are coded (activity_flag and discount), how often they appear, and their anomalies.

Train split only (2024-03-28 to 2024-06-25). Two fields carry the promotion: activity_flag (0/1, the card
calls it "activity indicator") and discount (1.0 means no discount, lower means a deeper cut).
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import train_only  # noqa: E402

meta, S, ST, T = train_only()
TP, TD = T["promo"], T["discount"]
n_series, n_days = T["n_series"], T["n_days"]
d = meta.discount.to_numpy()
act = meta.activity_flag.to_numpy()
ds = S.sum(axis=1)

print("== Discount values (rows, train)")
print(f"min={d.min()} max={d.max()} distinct={len(np.unique(d))}")
print(f"rows with discount exactly 1.0: {int((d == 1).sum()):,} ({(d == 1).mean()*100:.2f}%)")
print(f"rows with discount < 1: {int((d < 1).sum()):,} ({(d < 1).mean()*100:.2f}%)")
print(f"rows outside the site's stated range 0.5 to 1 (below 0.5 or above 1): {int(((d < 0.5) | (d > 1)).sum()):,} ({((d < 0.5) | (d > 1)).mean()*100:.2f}%)")
print(f"  of which discount == 0.0: {int((d == 0).sum()):,}; 0 < discount < 0.5: {int(((d > 0) & (d < 0.5)).sum()):,}; discount > 1: {int((d > 1).sum()):,}")

print("\n== Discount bins against activity_flag (rows, train)")
edges = [-0.001, 0.0001, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.999, 1.0001, 2]
labels = ["0", "(0,0.5)", "[0.5,0.6)", "[0.6,0.7)", "[0.7,0.8)", "[0.8,0.9)", "[0.9,0.95)", "[0.95,0.999)", "[0.999,1)", ">=1"]
binned = pd.cut(d, edges, labels=labels, right=False)
tab = pd.DataFrame({"bin": binned, "act": act}).groupby("bin", observed=False).agg(rows=("act", "size"), activity_share=("act", "mean"))
tab["rows"] = tab["rows"].astype(int)
print(tab.assign(activity_share=(tab.activity_share * 100).round(2)).to_string())

print("\n== The two fields disagree")
print(f"discount < 1 and activity_flag = 0: {int(((d < 1) & (act == 0)).sum()):,}")
print(f"discount = 1 (or above) and activity_flag = 1: {int(((d >= 1) & (act == 1)).sum()):,}")
print(f"activity_flag = 1 rows: {int((act == 1).sum()):,} ({act.mean()*100:.2f}%)")
print(f"activity_flag = 1 with discount in [0.5, 0.9]: {int(((act == 1) & (d >= 0.5) & (d <= 0.9)).sum()):,} of {int((act == 1).sum()):,}")
print(f"discount quantiles on activity_flag = 1 rows (p5, p25, p50, p75, p95): {np.quantile(d[act == 1], [0.05, 0.25, 0.5, 0.75, 0.95]).round(3).tolist()}")

print("\n== Anomalies")
z = d == 0
print(f"discount == 0: rows={int(z.sum()):,}, series={meta.series[z].nunique()}, products={meta.product_id[z].nunique()}, stores={meta.store_id[z].nunique()}")
print(f"  median daily sales on those rows: {np.median(ds[z]):.2f}; on all other rows: {np.median(ds[~z]):.2f}")
print(f"  series with discount 0 on every day: {int(meta.groupby('series').discount.apply(lambda x: (x == 0).all()).sum())}")
print(f"  activity_flag share on those rows: {act[z].mean()*100:.2f}%")
deep = (d > 0) & (d < 0.5)
print(f"0 < discount < 0.5: rows={int(deep.sum()):,}, series={meta.series[deep].nunique():,}, activity share={act[deep].mean()*100:.2f}%, median daily sales={np.median(ds[deep]):.2f}")
print(f"discount > 1: rows={int((d > 1).sum())}, activity share={act[d > 1].mean() if (d > 1).any() else float('nan')}")

print("\n== Coverage: how often a series is on promotion (train, 90 days, 13 weeks)")
pday = TP.astype(bool)
days_per_series = pday.sum(axis=1)
print(f"series-days with activity_flag = 1: {pday.mean()*100:.2f}%")
print(f"series with at least one promo day: {np.mean(days_per_series > 0)*100:.2f}%")
print(f"promo days per series: min={days_per_series.min()} p10={np.quantile(days_per_series,0.1):.0f} median={np.median(days_per_series):.0f} p90={np.quantile(days_per_series,0.9):.0f} max={days_per_series.max()}")
week = np.arange(n_days) // 7
weeks = np.unique(week)
wk_cov = np.stack([pday[:, week == w].any(axis=1) for w in weeks], axis=1)  # (series, week)
print(f"weeks in the window: {len(weeks)} (last week has {int((week == weeks[-1]).sum())} days)")
print(f"share of series with a promo in each week: {wk_cov.mean()*100:.2f}% (mean over weeks); min week {wk_cov.mean(axis=0).min()*100:.2f}%; max week {wk_cov.mean(axis=0).max()*100:.2f}%")
print(f"share of series with a promo in every full week (weeks 0-11): {np.mean(wk_cov[:, :12].all(axis=1))*100:.2f}%")
print(f"share of series with a promo in at least 1 of every week: {np.mean(wk_cov.any(axis=1))*100:.2f}%")
print(f"weekly coverage: share of (series, week) pairs with a promo: {wk_cov.mean()*100:.2f}%")

print("\n== Runs of consecutive promo days (train)")
runs = []
for s in range(n_series):
    x = np.concatenate([[0], pday[s].astype(int), [0]])
    edges_r = np.flatnonzero(np.diff(x))
    lengths = edges_r[1::2] - edges_r[0::2]
    runs.extend(lengths.tolist())
runs = np.array(runs)
print(f"promo runs: {len(runs):,}; run length median={np.median(runs):.0f} days, p90={np.quantile(runs,0.9):.0f}, max={runs.max()}")
print(f"runs per series: median={len(runs)/n_series:.2f} (mean)")

print("\n== Discount changes from one day to the next (within series, train)")
changes = (np.diff(TD, axis=1) != 0)
print(f"day-to-day pairs where the discount changes: {changes.mean()*100:.2f}%")
print(f"day-to-day pairs where activity_flag changes: {(np.diff(TP, axis=1) != 0).mean()*100:.2f}%")
