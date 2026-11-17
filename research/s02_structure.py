"""Grain, series, dates, hourly versus daily fields, and the paper's stated figures against the data.

Values use the train split only (2024-03-28 to 2024-06-25, 90 days). The eval split is counted in s01.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import train_only  # noqa: E402

meta, S, ST, T = train_only()
n_series, n_days = T["n_series"], T["n_days"]
TST = T["stock"]
print("== Grain")
print(f"1 row = one store-product-day with 24 hourly values. Rows (train): {len(meta):,}")
print(f"series (store x product): {n_series:,}; days per series: min={meta.groupby('series').size().min()} max={meta.groupby('series').size().max()}")
print(f"dates: {meta.dt.min().date()} to {meta.dt.max().date()} ({n_days} days, contiguous: {meta.dt.nunique() == n_days})")
print(f"hours per row: {S.shape[1]} (clock hours 0 to 23; the timezone is not stated in the card)")

print("\n== Hourly fields (vary within the day) and daily fields (one value per row)")
hourly = ["hours_sale", "hours_stock_status"]
daily = ["sale_amount", "stock_hour6_22_cnt", "discount", "holiday_flag", "activity_flag", "precpt", "avg_temperature", "avg_humidity", "avg_wind_level"]
print("   hourly:", hourly)
print("   daily :", daily)
print(f"   share of daily-field values that are constant inside the day by construction: 100% (one value per row)")
print(f"   sale_amount equals the sum of hours_sale (train, relative 1e-6): {np.mean(np.abs(meta.sale_amount.to_numpy() - S.sum(1)) <= 1e-6 * np.maximum(1, np.abs(meta.sale_amount.to_numpy()))):.6f}")

print("\n== Hourly profile (train, all series and days)")
prof = pd.DataFrame({
    "mean_sales": S.mean(axis=0),
    "share_stockout": ST.mean(axis=0),
    "share_zero_sales": (S == 0).mean(axis=0),
}, index=range(24))
print(prof.round(4).to_string())
print(f"peak sales hour (argmax of mean): {int(prof.mean_sales.idxmax())}; local maxima over 6-21: {[h for h in range(7, 21) if prof.mean_sales[h] > prof.mean_sales[h-1] and prof.mean_sales[h] > prof.mean_sales[h+1]]}")

print("\n== The paper's stated figures against train (arXiv 2505.16319 v5, sections 3.2 and 3.3)")
print(f"   stockout share at 06:00 (paper: below 2%): {prof.share_stockout[6]*100:.2f}%")
print(f"   stockout share at 20:00 (paper: peak 26%): {prof.share_stockout[20]*100:.2f}%")
print(f"   highest stockout share over 0-23 : hour {int(prof.share_stockout.idxmax())} = {prof.share_stockout.max()*100:.2f}%")
print(f"   stockout share over 06-21 (window of the card's stock_hour6_22_cnt): {TST[:, :, 6:22].mean()*100:.2f}%")
print(f"   stockout share over all 24 hours: {ST.mean()*100:.2f}%  (card: about 20% of the data)")
print(f"   sales peaks at 09:00 and 16:00 (paper: 9 AM and 4 PM): mean sales at 9={prof.mean_sales[9]:.4f} 16={prof.mean_sales[16]:.4f} 12={prof.mean_sales[12]:.4f}")

print("\n== Status 1 versus sales (is status 1 a stockout, i.e. missing sales?)")
z = S == 0
print(f"   P(zero sales | status 1) = {z[ST == 1].mean():.4f}")
print(f"   P(zero sales | status 0) = {z[ST == 0].mean():.4f}")
print(f"   mean sales | status 1 = {S[ST == 1].mean():.4f}; | status 0 = {S[ST == 0].mean():.4f}")

print("\n== Series completeness and runs of stockout (train)")
rows_per_series = meta.groupby("series").size()
print(f"   series with 90 days: {int((rows_per_series == 90).sum()):,} of {n_series:,}")
print(f"   missing hourly values (NaN) in sales: {int(np.isnan(S).sum())}")
dayshare = TST[:, :, 6:22].any(axis=2).mean()
print(f"   series-days with at least one stockout hour in 06-21: {dayshare*100:.2f}%")
allday = TST[:, :, 6:22].all(axis=2).mean()
print(f"   series-days with stockout in every hour of 06-21: {allday*100:.2f}%")
print(f"   series with no stockout hour at all in 90 days: {int((~TST.any(axis=(1, 2))).sum()):,} of {n_series:,}")
