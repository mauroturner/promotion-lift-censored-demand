"""Naive day-ahead baselines for hourly sales, on the proposed validation block.

Each forecast for day d uses only days before d (rolling history). Baselines have no fitted parameters, except
the hour profile of baseline 4, which is taken from the train block (SPLIT_DATES) only.
Two targets are scored: every hour (raw sales, censored by stockouts) and in-stock hours only (status 0).
The test block is never read here. Intervals: bootstrap over series (B=200, seed 0).
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import train_only, SPLIT_DATES  # noqa: E402

meta, S, ST, T = train_only()
TS, TST = T["sales"], T["stock"]
n_series = T["n_series"]
origin = pd.Timestamp(SPLIT_DATES["train"][0])
d0 = (pd.Timestamp(SPLIT_DATES["validation"][0]) - origin).days
d1 = (pd.Timestamp(SPLIT_DATES["validation"][1]) - origin).days
days = np.arange(d0, d1 + 1)
print(f"validation days: {len(days)} (index {d0}..{d1}), series: {n_series:,}, hourly values: {n_series*len(days)*24:,}")
print(f"history used: from index 0 (train block starts {SPLIT_DATES['train'][0]}), so the first validation day has 72 days of history")

# Hour profile from the train block only: mean sales by hour divided by the mean over all hours.
tr = np.arange(0, (pd.Timestamp(SPLIT_DATES["train"][1]) - origin).days + 1)
prof_h = TS[:, tr, :].mean(axis=(0, 1))
prof = prof_h / prof_h.mean()
print("hour profile (train block), first and peak hours:", np.round(prof[[0, 6, 9, 16, 21]], 3).tolist())

y = TS[:, days, :]
inst = TST[:, days, :] == 0
pred = {}
pred["1 same hour, previous day"] = TS[:, days - 1, :]
pred["2 same hour, mean of last 7 days"] = np.mean([TS[:, days - k, :] for k in range(1, 8)], axis=0)
pred["3 same hour, mean of last 28 days"] = np.mean([TS[:, days - k, :] for k in range(1, 29)], axis=0)
level7 = np.mean([TS[:, days - k, :].mean(axis=2) for k in range(1, 8)], axis=0)  # (series, days)
pred["4 last-7-day level times train hour profile"] = level7[:, :, None] * prof[None, None, :]
pred["0 always zero (reference)"] = np.zeros_like(y)


def metrics(p, mask, boot_w):
    e = np.abs(p - y)
    abs_s = (e * mask).sum(axis=(1, 2))
    n_s = mask.sum(axis=(1, 2)).astype(float)
    y_s = (y * mask).sum(axis=(1, 2))
    bias_s = ((p - y) * mask).sum(axis=(1, 2))
    mae = abs_s.sum() / n_s.sum()
    wape = abs_s.sum() / y_s.sum()
    bias = bias_s.sum() / y_s.sum()
    maes = (boot_w @ abs_s) / (boot_w @ n_s)
    return mae, np.quantile(maes, 0.025), np.quantile(maes, 0.975), wape, bias


rng = np.random.default_rng(0)
B = 200
W = np.stack([np.bincount(rng.integers(0, n_series, n_series), minlength=n_series) for _ in range(B)]).astype(float)
all_mask = np.ones_like(y, dtype=bool)
for name, p in pred.items():
    mae, lo, hi, wape, bias = metrics(p, all_mask, W)
    print(f"{name:42s} all hours : MAE={mae:.4f} [{lo:.4f}; {hi:.4f}]  WAPE={wape*100:6.2f}%  bias={bias*100:+7.2f}%")
print()
for name, p in pred.items():
    mae, lo, hi, wape, bias = metrics(p, inst, W)
    print(f"{name:42s} in-stock  : MAE={mae:.4f} [{lo:.4f}; {hi:.4f}]  WAPE={wape*100:6.2f}%  bias={bias*100:+7.2f}%")
print()
print(f"share of validation hours with status 0 (in stock): {inst.mean()*100:.2f}%")
print(f"mean hourly sales, validation: {y.mean():.4f}; train block: {TS[:, tr, :].mean():.4f}")
print(f"relative level shift validation vs train: {(y.mean()/TS[:, tr, :].mean()-1)*100:+.2f}%")

print("\nDaily totals (sum of the 24 hours), all series and days; the paper reports WAPE on daily demand (its section 4.2)")
yd = y.sum(axis=2)  # (series, days)
dpred = {
    "1 previous day total": TS[:, days - 1, :].sum(axis=2),
    "2 mean of last 7 day totals": np.mean([TS[:, days - k, :].sum(axis=2) for k in range(1, 8)], axis=0),
    "3 mean of last 28 day totals": np.mean([TS[:, days - k, :].sum(axis=2) for k in range(1, 29)], axis=0),
}
for name, p in dpred.items():
    e = np.abs(p - yd)
    e_s = e.sum(axis=1)
    y_s = yd.sum(axis=1)
    p_s = (p - yd).sum(axis=1)
    wape = e_s.sum() / y_s.sum()
    wapes = (W @ e_s) / (W @ y_s)
    print(f"{name:30s} WAPE={wape*100:6.2f}% [{np.quantile(wapes,0.025)*100:6.2f}; {np.quantile(wapes,0.975)*100:6.2f}]  bias={p_s.sum()/y_s.sum()*100:+7.2f}%")
print(f"daily total, validation mean: {yd.mean():.4f}; share of series-days with zero total: {np.mean(yd == 0)*100:.2f}%")
