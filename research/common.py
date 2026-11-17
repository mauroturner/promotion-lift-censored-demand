"""Shared loader for FreshRetailNet-50K (CC BY 4.0). Reads Parquet only; never executes file content.

Hourly fields are fixed-length lists of 24 values per row (one per clock hour, 0 to 23).
The loader checks that every list has length 24 and no nulls before converting it to a NumPy array.
"""
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

PROJECT = Path(__file__).resolve().parents[1]
RAW = PROJECT / "data" / "raw"
OUT = PROJECT / "data" / "interim" / "research"
OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SPLIT_FILES = {"train": RAW / "train.parquet", "eval": RAW / "eval.parquet"}
ID_COLS = ["city_id", "store_id", "management_group_id", "first_category_id",
           "second_category_id", "third_category_id", "product_id"]
DAILY_COLS = ["dt", "sale_amount", "stock_hour6_22_cnt", "discount", "holiday_flag",
              "activity_flag", "precpt", "avg_temperature", "avg_humidity", "avg_wind_level"]
HOUR_COLS = ["hours_sale", "hours_stock_status"]
HOURS = 24

# Proposed time split (docs/research.md, section "Fuga de información y partición propuesta").
# Fitted models use only the train block; the purge keeps 7-day lag windows from crossing into validation.
# Naive baselines have no parameters and use rolling history up to the day before each forecast.
# The test block is the dataset's own eval split: only its structure and row counts are read.
SPLIT_DATES = {
    "train": ("2024-03-28", "2024-05-31"),
    "purge": ("2024-06-01", "2024-06-07"),
    "validation": ("2024-06-08", "2024-06-25"),
    "test": ("2024-06-26", "2024-07-02"),
}


def _fixed_list(col, label, dtype):
    """Return an (n, 24) array from a Parquet list column, refusing any other shape, null or NaN."""
    arr = col.combine_chunks()
    if arr.null_count:
        raise ValueError(f"{label}: {arr.null_count} null lists")
    lengths = arr.value_lengths().to_numpy(zero_copy_only=False)
    if not np.all(lengths == HOURS):
        raise ValueError(f"{label}: list lengths other than {HOURS} found")
    flat = arr.flatten().to_numpy(zero_copy_only=False).astype(np.float64)
    if np.isnan(flat).any():
        raise ValueError(f"{label}: NaN values")
    return flat.astype(dtype).reshape(len(arr), HOURS)


def load_split(name):
    """Return (meta, sales, status) for one split: meta has one row per store-product-day,
    sales is (n, 24) float64 hourly sales, status is (n, 24) int8 hourly out-of-stock flags."""
    table = pq.read_table(SPLIT_FILES[name], columns=ID_COLS + DAILY_COLS + HOUR_COLS)
    meta = table.select(ID_COLS + DAILY_COLS).to_pandas()
    sales = _fixed_list(table.column("hours_sale"), f"{name}.hours_sale", np.float64)
    status = _fixed_list(table.column("hours_stock_status"), f"{name}.hours_stock_status", np.int8)
    meta["split"] = name
    meta["dt"] = pd.to_datetime(meta["dt"], format="%Y-%m-%d")
    return meta, sales, status


def load_all():
    """Train and eval stacked in one table, with a series code (store, product) and a day index."""
    parts = [load_split(s) for s in ("train", "eval")]
    meta = pd.concat([p[0] for p in parts], ignore_index=True)
    sales = np.vstack([p[1] for p in parts])
    status = np.vstack([p[2] for p in parts])
    meta["series"] = meta.groupby(["store_id", "product_id"], sort=True).ngroup().astype(np.int32)
    meta["day"] = (meta["dt"] - meta["dt"].min()).dt.days.astype(np.int16)
    return meta, sales, status


def to_tensors(meta, sales, status):
    """Dense arrays indexed [series, day] (and [series, day, hour] for the hourly values).

    Returns a dict: sales (S, D, 24) float64, stock (S, D, 24) int8, promo (S, D) int8 from activity_flag,
    discount (S, D) float64, and the number of series and days. Every (series, day) must appear once."""
    n_series = int(meta.series.max()) + 1
    n_days = int(meta.day.max()) + 1
    key = meta.series.to_numpy() * n_days + meta.day.to_numpy()
    if len(np.unique(key)) != len(key):
        raise ValueError("duplicate (series, day) rows")
    flat_sales = np.full((n_series * n_days, HOURS), np.nan)
    flat_stock = np.zeros((n_series * n_days, HOURS), dtype=np.int8)
    flat_promo = np.zeros(n_series * n_days, dtype=np.int8)
    flat_disc = np.full(n_series * n_days, np.nan)
    flat_sales[key] = sales
    flat_stock[key] = status
    flat_promo[key] = meta.activity_flag.to_numpy()
    flat_disc[key] = meta.discount.to_numpy()
    return {
        "sales": flat_sales.reshape(n_series, n_days, HOURS),
        "stock": flat_stock.reshape(n_series, n_days, HOURS),
        "promo": flat_promo.reshape(n_series, n_days),
        "discount": flat_disc.reshape(n_series, n_days),
        "n_series": n_series,
        "n_days": n_days,
    }


def train_only():
    """Train split (2024-03-28 to 2024-06-25) as tensors. The eval split (2024-06-26 to 2024-07-02) is
    left out: the research reads it only for structure and counts (s01)."""
    meta, sales, status = load_split("train")
    meta["series"] = meta.groupby(["store_id", "product_id"], sort=True).ngroup().astype(np.int32)
    meta["day"] = (meta["dt"] - meta["dt"].min()).dt.days.astype(np.int16)
    return meta, sales, status, to_tensors(meta, sales, status)
