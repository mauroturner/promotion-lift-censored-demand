"""Are promotions confounded with season, weekday, store, product or category?

Train split only. The outcome is the activity_flag (promotion) on each series-day. Each factor is scored by
eta-squared: the share of the promotion variance that the factor's groups explain (between-group sum of squares
over total sum of squares). Eta-squared rises with the number of groups, so the many-group factors (series,
product, store) are read against their group sizes, not on their own.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import train_only  # noqa: E402

meta, S, ST, T = train_only()
x = meta.activity_flag.to_numpy().astype(float)
grand = x.mean()
total_ss = ((x - grand) ** 2).sum()


def eta2(labels):
    """Return eta-squared, omega-squared (bias-corrected for the number of groups) and the group count."""
    g = pd.DataFrame({"g": labels, "x": x}).groupby("g")["x"].agg(["sum", "size"])
    means = g["sum"] / g["size"]
    between = (g["size"] * (means - grand) ** 2).sum()
    k = len(g)
    n = len(x)
    ms_within = (total_ss - between) / (n - k)
    omega = (between - (k - 1) * ms_within) / (total_ss + ms_within)
    return between / total_ss, omega, k


print(f"promo share (activity_flag = 1) over the train rows: {grand*100:.2f}%")
print("\n== Eta-squared by factor (share of promo variance explained; groups in brackets)")
dow = meta.dt.dt.dayofweek.to_numpy()
week = (meta["day"].to_numpy() // 7)
factors = {
    "weekday (7)": dow,
    "week of window (13)": week,
    "holiday_flag (2)": meta.holiday_flag.to_numpy(),
    "city (18)": meta.city_id.to_numpy(),
    "management group (7)": meta.management_group_id.to_numpy(),
    "first category (32)": meta.first_category_id.to_numpy(),
    "store (898)": meta.store_id.to_numpy(),
    "product (865)": meta.product_id.to_numpy(),
    "day (90)": meta.day.to_numpy(),
    "series (50,000)": meta.series.to_numpy(),
}
for name, labels in factors.items():
    e, om, k = eta2(labels)
    print(f"   {name:24s} eta2 = {e:.4f}  omega2 = {om:.4f}  [groups={k}]")

print("\n== Promo share by level (only the small factors)")
for name, labels in [("weekday", dow), ("week", week), ("holiday_flag", meta.holiday_flag.to_numpy()), ("management group", meta.management_group_id.to_numpy())]:
    t = pd.DataFrame({"g": labels, "x": x}).groupby("g")["x"].agg(["mean", "size"])
    print(f"   {name}: " + ", ".join(f"{int(i)}={r['mean']*100:.1f}%" for i, r in t.iterrows()))

print("\n== Spread of promo share across stores and cities (groups of at least 100 rows)")
for name, labels in [("store", meta.store_id.to_numpy()), ("city", meta.city_id.to_numpy())]:
    t = pd.DataFrame({"g": labels, "x": x}).groupby("g")["x"].agg(["mean", "size"])
    t = t[t["size"] >= 100]
    print(f"   {name}: groups={len(t)}, promo share min={t['mean'].min()*100:.1f}% median={t['mean'].median()*100:.1f}% max={t['mean'].max()*100:.1f}%")

print("\n== Series-level promo share (train)")
per = meta.groupby("series").activity_flag.mean()
print(f"   min={per.min()*100:.1f}% p10={per.quantile(0.1)*100:.1f}% median={per.median()*100:.1f}% p90={per.quantile(0.9)*100:.1f}% max={per.max()*100:.1f}%")
print(f"   share of series with promo share below 5%: {np.mean(per < 0.05)*100:.2f}%; above 95%: {np.mean(per > 0.95)*100:.2f}%")

print("\n== Promotion and holidays")
print(f"   promo share on holiday rows: {x[meta.holiday_flag.to_numpy() == 1].mean()*100:.2f}%; non-holiday: {x[meta.holiday_flag.to_numpy() == 0].mean()*100:.2f}%")
by_day = meta.groupby("dt").holiday_flag.agg(["mean", "size"])
flagged = by_day[by_day["mean"] > 0.5]
print(f"   days with holiday_flag = 1 for most stores: {len(flagged)} of {len(by_day)}")
print("   their dates: " + ", ".join(str(d.date()) for d in flagged.index))
print(f"   share of store-product-day rows with holiday_flag = 1 (train): {meta.holiday_flag.mean()*100:.2f}%")
print(f"   holiday_flag varies across stores within a day: {int((meta.groupby('dt').holiday_flag.nunique() > 1).sum())} days of {len(by_day)}")
