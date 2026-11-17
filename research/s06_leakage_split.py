"""Leakage risks, measured, and the proposed time split (dates in common.SPLIT_DATES).

Train split for values. The test block (eval split) is counted only, never read for values.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import train_only, SPLIT_DATES, load_split  # noqa: E402

meta, S, ST, T = train_only()
TS, TST, TP, TD = T["sales"], T["stock"], T["promo"], T["discount"]
W = slice(6, 22)

print("== 1. Daily fields that contain the hourly target (same-day leak)")
print(f"sale_amount == sum(hours_sale): {np.mean(np.abs(meta.sale_amount.to_numpy() - S.sum(axis=1)) <= 1e-6):.6f} of rows")
print(f"stock_hour6_22_cnt == stockout hours 6-21: {np.mean(meta.stock_hour6_22_cnt.to_numpy() == ST[:, 6:22].sum(axis=1)):.6f} of rows")
print("   Both are known only at the end of the day: they must not feed a forecast of that day's hours.")

print("\n== 2. Stockout flag at hour h and sales at hour h (concurrent censoring)")
z = S == 0
print(f"P(status 1 | zero sales) = {ST[z].mean():.4f}")
print(f"P(zero sales | status 1) = {z[ST == 1].mean():.4f}")
print(f"P(zero sales | status 0) = {z[ST == 0].mean():.4f}")
print("   The flag of hour h is almost a copy of 'no sales in h'. It cannot be an input for hour h.")

print("\n== 3. Daily weather and calendar fields: are they one value per city and day?")
per_city_day = meta.groupby(["city_id", "dt"]).precpt.nunique()
print(f"city-days whose precipitation takes one value across stores: {np.mean(per_city_day == 1)*100:.2f}% (of {len(per_city_day):,} city-days)")
per_series_std = meta.groupby(["city_id", "dt"]).avg_temperature.std().mean()
print(f"mean across city-days of the std of avg_temperature across stores: {per_series_std:.6f}")
print("   Weather is observed for the day it describes: a same-day forecast must use a forecast, not the observed value.")

print("\n== 4. Promotion fields: known in advance or set during the day? (not observable here)")
print(f"day-to-day changes of discount per series: {(np.diff(TD, axis=1) != 0).mean()*100:.2f}%")
print(f"day-to-day changes of activity_flag per series: {(np.diff(TP, axis=1) != 0).mean()*100:.2f}%")
print("   Whether these are planned in advance is not stated in the card. The paper says promotions can be anticipated (section 4.2).")

print("\n== 5. Evaluation on in-stock hours only (selection on a variable the promotion moves)")
print(f"share of promo days with a stockout hour in 06-21: {TST[TP.astype(bool)][:, W].any(axis=1).mean()*100:.2f}%")
print(f"share of non-promo days with a stockout hour in 06-21: {TST[~TP.astype(bool)][:, W].any(axis=1).mean()*100:.2f}%")
print("   Restricting to in-stock hours conditions on a variable that promotions raise (s03). Compare with the full sample.")

print("\n== 6. Continuity of the dataset's own split")
tr = load_split("train")[0]
te = load_split("eval")[0]
print(f"train last date {tr.dt.max().date()}, eval first date {te.dt.min().date()}: contiguous, no overlap = {bool(te.dt.min() == tr.dt.max() + pd.Timedelta(days=1))}")
ov = pd.merge(tr[["store_id", "product_id", "dt"]], te[["store_id", "product_id", "dt"]], on=["store_id", "product_id", "dt"]).shape[0]
print(f"(store, product, day) pairs shared by train and eval: {ov}")
print(f"eval rows (counted only): {len(te):,}; series: {te[['store_id', 'product_id']].drop_duplicates().shape[0]:,}; days: {te.dt.nunique()}")

print("\n== 7. Proposed split (common.SPLIT_DATES): days and hourly values per block (train split)")
dates = meta.dt
for block in ["train", "purge", "validation"]:
    a, b = (pd.Timestamp(x) for x in SPLIT_DATES[block])
    m = (dates >= a) & (dates <= b)
    n_days = dates[m].nunique()
    print(f"   {block:10s} {a.date()} to {b.date()}: days={n_days}, series-days={int(m.sum()):,}, hourly values={int(m.sum())*24:,}")
    if block == "validation":
        vmask = m.to_numpy()
        print(f"       stockout share 06-21: {ST[vmask][:, 6:22].mean()*100:.2f}%; promo share: {meta.activity_flag[vmask].mean()*100:.2f}%; mean hourly sales: {S[vmask].mean():.4f}")
    if block == "train":
        tmask = m.to_numpy()
        print(f"       stockout share 06-21: {ST[tmask][:, 6:22].mean()*100:.2f}%; promo share: {meta.activity_flag[tmask].mean()*100:.2f}%; mean hourly sales: {S[tmask].mean():.4f}")
a, b = (pd.Timestamp(x) for x in SPLIT_DATES["test"])
print(f"   test       {a.date()} to {b.date()}: counted only, rows={len(te):,} (not read for values)")
print("   Level shift between train and validation (mean hourly sales above) and the purge length are the decisions the plan must justify.")
