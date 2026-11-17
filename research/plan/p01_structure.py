"""Planner check 1: discount values near 1, the day states the plan defines, night hours and stock-out timing.

Reads only data/raw/train.parquet (the dataset's train split, 2024-03-28 to 2024-06-25) through
research/common.train_only(); the eval split (the sealed test week) is never opened.
Run from the project folder: .venv/Scripts/python -I research/plan/p01_structure.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import train_only, SPLIT_DATES  # noqa: E402

meta, S, ST, T = train_only()
TS, TST, TP, TD = T["sales"], T["stock"], T["promo"], T["discount"]
S_, D_ = T["n_series"], T["n_days"]
origin = pd.Timestamp(SPLIT_DATES["train"][0])
print(f"series {S_:,}, days {D_}, rows {len(meta):,}")

d = meta.discount.to_numpy()
print("\n== Discount values at or above 0.999")
hi = d[d >= 0.999]
vals, cnt = np.unique(np.round(hi, 6), return_counts=True)
order = np.argsort(-cnt)[:8]
for v, c in zip(vals[order], cnt[order]):
    print(f"   {v:.6f}: {c:,}")
print(f"   exactly 1.0: {int((d == 1.0).sum()):,}; in [0.999, 1): {int(((d >= 0.999) & (d < 1)).sum()):,}; > 1: {int((d > 1).sum()):,}")

# Day states (plan D04): promo = flag 1 with 0 < discount <= 1; regular = flag 0 and discount >= REG;
# unflagged_cut = flag 0 and 0 < discount < REG; anomalous = discount 0 or > 1.
print("\n== Day states by the regular-day threshold REG (series-days, train split)")
anomalous = (TD <= 0) | (TD > 1)
for REG in (0.999, 0.95, 0.9):
    promo = (TP == 1) & ~anomalous
    regular = (TP == 0) & ~anomalous & (TD >= REG)
    cut = (TP == 0) & ~anomalous & (TD < REG)
    both = promo.any(axis=1) & regular.any(axis=1)
    print(f"   REG={REG}: promo {promo.mean()*100:.2f}%, regular {regular.mean()*100:.2f}%, unflagged cut {cut.mean()*100:.2f}%, "
          f"anomalous {anomalous.mean()*100:.2f}%; series with promo and regular days {int(both.sum()):,}")

print("\n== Sales by hour window (train split)")
tot = TS.sum()
day_win = TS[:, :, 6:22].sum()
print(f"   share of sales in hours 06-21: {day_win/tot*100:.2f}%; hours 0-5 and 22-23: {(1-day_win/tot)*100:.2f}%")

print("\n== Stock-out timing in hours 06-21 (series-days)")
win = TST[:, :, 6:22] == 1
any_out = win.any(axis=2)
first = np.where(any_out, win.argmax(axis=2) + 6, -1)
print(f"   series-days with a stock-out in 06-21: {any_out.mean()*100:.2f}%; fully in stock 06-21: {(~any_out).mean()*100:.2f}%")
fo = first[any_out]
q = np.percentile(fo, [10, 25, 50, 75, 90])
print(f"   first stock-out hour: p10 {q[0]:.0f}, p25 {q[1]:.0f}, median {q[2]:.0f}, p75 {q[3]:.0f}, p90 {q[4]:.0f}")
# Does a stock-out run to the end of the window once it starts?
after = np.zeros_like(any_out)
for s0 in range(0, S_, 5000):
    w = win[s0:s0 + 5000]
    f = first[s0:s0 + 5000]
    h = np.arange(6, 22)[None, None, :]
    tail = h >= np.where(f < 0, 99, f)[:, :, None]
    after[s0:s0 + 5000] = np.where(f >= 0, (w | ~tail).all(axis=2), False)
print(f"   stock-out days where, once out, the item stays out until 21 h: {after[any_out].mean()*100:.2f}%")
hist = np.bincount(fo, minlength=22)[6:22]
print("   first stock-out hour distribution (06..21, % of days with a stock-out):", np.round(hist / hist.sum() * 100, 1).tolist())
