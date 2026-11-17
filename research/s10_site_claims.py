"""Measured figures for the claims of src/i18n/projects/promotion-lift.ts (contradiction table).

Train block only. Values come from the same tensors as s03 to s09; claims are quoted in the document, not parsed.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import train_only  # noqa: E402

meta, S, ST, T = train_only()
TS, TST, TP, TD = T["sales"], T["stock"], T["promo"], T["discount"]
n_series, n_days = T["n_series"], T["n_days"]
pday = TP.astype(bool)
week = np.arange(n_days) // 7

print("== Claim: 'descuentos todas las semanas'")
wk_chain = [pday[:, week == w].any() for w in range(int(week.max()) + 1)]
print(f"weeks with a promotion in at least one store-product series (chain level): {int(sum(wk_chain))} of {len(wk_chain)}")
wk_series = np.stack([pday[:, week == w].any(axis=1) for w in range(int(week.max()) + 1)], axis=1)
print(f"series-weeks with a promotion (series level): {wk_series.mean()*100:.2f}%")

print("\n== Claim: 'Una hora sin stock vende menos porque no hay qué vender' (sales drop, not demand)")
W = slice(6, 22)
s1 = TST[:, :, W] == 1
s0 = TST[:, :, W] == 0
sw = TS[:, :, W]
n1 = s1.sum(axis=1)
n0 = s0.sum(axis=1)
m1 = np.where(n1 > 0, (sw * s1).sum(axis=1) / np.maximum(n1, 1), np.nan)
m0 = np.where(n0 > 0, (sw * s0).sum(axis=1) / np.maximum(n0, 1), np.nan)
ok = ~np.isnan(m1) & ~np.isnan(m0)
print(f"series-hour pairs (06-21) with both states: {int(ok.sum()):,}")
print(f"ratio of stockout sales to in-stock sales, sales-weighted: {m1[ok].sum()/m0[ok].sum():.4f}")
print(f"stockout hours with positive sales: {(sw[s1] > 0).mean()*100:.2f}%")

print("\n== Claim: 'Las ventas se explican por el descuento, la marca de promoción y los efectos de la hora y del día'")
hour_profile = TS.mean(axis=(0, 1))
print(f"hour effect: mean sales range over the 24 hours from {hour_profile.min():.4f} to {hour_profile.max():.4f} (ratio {hour_profile.max()/hour_profile.min():.1f})")
dow = pd.date_range(meta.dt.min(), periods=n_days, freq="D").dayofweek.to_numpy()
daily = TS.sum(axis=2)  # (series, day)
rel = daily / daily.mean(axis=1, keepdims=True)  # each series relative to its own mean
for d in range(7):
    print(f"   weekday {d} (0=Mon): mean daily sales relative to each series' mean = {rel[:, dow == d].mean():.4f}")
print(f"day-of-week spread (max over min): {max(rel[:, dow == d].mean() for d in range(7)) / min(rel[:, dow == d].mean() for d in range(7)):.4f}")
grand = rel.mean()
between = sum(((rel[:, dow == d].mean() - grand) ** 2) * rel[:, dow == d].size for d in range(7))
print(f"share of daily sales variance (each series relative to its own mean) explained by weekday: {between / np.sum((rel - grand) ** 2):.5f}")

print("\n== Claim: 'promociones ordenadas por lo que suman' (ranking by sales added)")
print("   The lift in s08 and s09 is relative (promo over non-promo, in %). Hourly sales are normalized (card),")
print("   so absolute units cannot be ranked. Measured: relative lifts only.")

print("\n== Claim: 'Sin precio ni canal en el dataset' (schema, from s01)")
print("   Columns: city_id, store_id, management_group_id, first/second/third_category_id, product_id, dt,")
print("   sale_amount, hours_sale, stock_hour6_22_cnt, hours_stock_status, discount, holiday_flag, activity_flag,")
print("   precpt, avg_temperature, avg_humidity, avg_wind_level. No price and no sales channel column.")
print("   The paper (section 3.1) says hourly sales come from online order transaction systems.")

print("\n== Claim: 'Un ranking de qué promociones venden' (promotion identifier)")
print("   No promotion identifier: the data has activity_flag and discount only (s04). Rankings are over cells (s09).")

print("\n== Claim: 'Marca de promoción' versus discount (s04)")
print(f"   activity_flag = 1 with discount in (0.5, 0.9]: {int(((TP == 1) & (TD > 0.5) & (TD <= 0.9)).sum()):,} of {int((TP == 1).sum()):,}")
print(f"   activity_flag = 0 with discount below 1: {int(((TP == 0) & (TD < 1) & (TD > 0)).sum()):,}")
