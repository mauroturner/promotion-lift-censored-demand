"""Schema, row counts, keys, hierarchy and internal consistency of FreshRetailNet-50K (full data).

Prints the figures used in docs/research.md, section "Cómo se verificaron los datos".
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import RAW, SPLIT_FILES, ID_COLS, DAILY_COLS, HOUR_COLS, load_all  # noqa: E402

print("== Schema (per split)")
for name, path in SPLIT_FILES.items():
    schema = pq.read_schema(path)
    print(f"{name}: {path.name}, {pq.ParquetFile(path).metadata.num_rows} rows, {len(schema.names)} columns")
    for field in schema:
        print(f"   {field.name}: {field.type}")

meta, sales, status = load_all()
print("\n== Row counts and days")
for s in ("train", "eval"):
    m = meta[meta.split == s]
    print(f"{s}: rows={len(m):,} series={m.series.nunique():,} dt min={m.dt.min().date()} dt max={m.dt.max().date()} distinct dt={m.dt.nunique()}")
    per_series = m.groupby("series").size()
    print(f"   rows per series: min={per_series.min()} median={per_series.median():.0f} max={per_series.max()}")
    dup = m.duplicated(["series", "dt"]).sum()
    print(f"   duplicate (series, dt) rows: {dup}")

print("\n== Distinct keys (all rows)")
for col in ID_COLS:
    print(f"   {col}: {meta[col].nunique():,}")
print(f"   (store_id, product_id) pairs = series: {meta.series.nunique():,}")
print(f"   distinct product_id (card says 865 SKUs, paper says 863): {meta.product_id.nunique()}")
print(f"   distinct store_id (card and paper say 898): {meta.store_id.nunique()}")
print(f"   distinct city_id (card and paper say 18): {meta.city_id.nunique()}")

print("\n== Hierarchy consistency (each child maps to one parent)")
for child, parent in [("store_id", "city_id"), ("product_id", "third_category_id"),
                      ("third_category_id", "second_category_id"), ("second_category_id", "first_category_id"),
                      ("first_category_id", "management_group_id"), ("product_id", "management_group_id")]:
    n_parent = meta.groupby(child)[parent].nunique()
    print(f"   {child} -> {parent}: children with >1 parent = {int((n_parent > 1).sum())} of {len(n_parent)}")

print("\n== Hourly fields")
print(f"   hours_sale shape {sales.shape}; min={sales.min():.4f} max={sales.max():.4f}; NaN={np.isnan(sales).sum()}; negative={int((sales < 0).sum())}")
print(f"   rows whose hourly sum is zero: {int((sales.sum(axis=1) == 0).sum()):,}")
vals = np.unique(status)
print(f"   hours_stock_status values: {vals.tolist()} (counts {[int((status == v).sum()) for v in vals]})")
print(f"   share of all 24-hour values that are stockout (status 1): {status.mean():.4f}")

print("\n== Daily fields consistency")
dsum = sales.sum(axis=1)
diff = np.abs(meta["sale_amount"].to_numpy() - dsum)
rel = diff / np.maximum(np.abs(meta["sale_amount"].to_numpy()), 1e-9)
print(f"   sale_amount vs sum(hours_sale): max abs diff={diff.max():.3e}; share within 1e-6 relative={np.mean(rel < 1e-6):.6f}")
print(f"   sale_amount: min={meta.sale_amount.min():.4f} max={meta.sale_amount.max():.4f} zero rows={int((meta.sale_amount == 0).sum())}")
c_full = status[:, 6:23].sum(axis=1)  # hours 6 through 22 inclusive
c_alt = status[:, 6:22].sum(axis=1)   # hours 6 through 21 inclusive
c_stat = meta["stock_hour6_22_cnt"].to_numpy()
print(f"   stock_hour6_22_cnt == sum(status[6..22]) : {np.mean(c_stat == c_full):.6f}")
print(f"   stock_hour6_22_cnt == sum(status[6..21]) : {np.mean(c_stat == c_alt):.6f}")
print(f"   stock_hour6_22_cnt min={c_stat.min()} max={c_stat.max()}")
print(f"   hours 0-5 and 23 with status 1 (share of those hours): {status[:, [0,1,2,3,4,5,23]].mean():.6f}")
print(f"   discount: min={meta.discount.min()} max={meta.discount.max()} distinct={meta.discount.nunique()}")
print("   discount top values (value: rows):")
for v, c in meta.discount.round(4).value_counts().head(12).sort_index().items():
    print(f"      {v}: {c:,}")
print(f"   activity_flag values: {sorted(meta.activity_flag.unique().tolist())} counts {meta.activity_flag.value_counts().sort_index().tolist()}")
print(f"   holiday_flag values: {sorted(meta.holiday_flag.unique().tolist())} counts {meta.holiday_flag.value_counts().sort_index().tolist()}")
for c in ["precpt", "avg_temperature", "avg_humidity", "avg_wind_level"]:
    print(f"   {c}: min={meta[c].min():.3f} max={meta[c].max():.3f} NaN={int(meta[c].isna().sum())}")
print(f"   NaN in any daily field: {int(meta[DAILY_COLS[1:]].isna().sum().sum())}")
print(f"   columns in the file: {ID_COLS + DAILY_COLS + HOUR_COLS}")
