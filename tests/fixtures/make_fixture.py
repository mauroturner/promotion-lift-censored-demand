"""The synthetic stand-in for FreshRetailNet-50K, with a latent demand that is known (plan, section 24; D34).

``make_fixture`` writes ``train.parquet`` and ``eval.parquet`` with the real schema and the real calendar (90 + 7 days from 2024-03-28),
a hierarchy of 7 management groups, a few cities, stores and products, and a demand that the generator knows hour by hour:

    lambda(s, h, d) = scale(s) * profile(h) * day(g, d) * (1 + lift(cell))     lift is 0 on every day that is not promoted

with Poisson noise on a sales unit of 0.1 (the real file's most common positive value). The planted lifts fall with the band number, that
is, they grow with the depth of the discount as in the real data. Stock is capped per series-day at a multiple of the demand that a day
without a promotion would bring, so a day with a promotion (more demand) runs out of stock earlier: **the censoring depends on the
demand**, which a synthetic mask cut at random cannot reproduce. The observed sale is the demand until the stock runs out; the rest of the
day sells nothing (with 3 % of out-of-stock hours keeping one unit of residual sale, as the real file's 2.9 %).

What is planted besides: a series whose discount is 0 every day, scattered discounts of 0 and above 1, flagged rows with no discount,
unflagged discounts, the discount 0.999, series with no regular day at all, whole days without stock, night hours without stock, and a
``sale_amount`` and a ``stock_hour6_22_cnt`` that agree with the hours. ``signal="null"`` sets every lift to 0 and draws everything
else the same way (the negative control). ``FixtureTruth`` keeps the state of each series-day, the latent demand of every hour and the
planted lift of each cell.

``make_malformed`` damages a copy of the fixture in one documented way and says which rule must catch it.
"""

from __future__ import annotations

import dataclasses
import hashlib
import shutil
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

FIRST_DAY = date(2024, 3, 28)
EVAL_DAYS = 7
HOURS = 24
FIRST_HOUR, LAST_HOUR = 6, 21                  # the analysis hours, both included
UNIT = 0.1                                     # the sales unit: sales are multiples of it
N_PRODUCTS = 15
N_GROUPS = 7
STATE_NAMES = ("promo", "regular", "unflagged_cut", "anomalous")
PROMO, REGULAR, UNFLAGGED, ANOMALOUS = range(4)
SIGNALS = ("lift", "null")

# The real training file's mean sale and out-of-stock rate by clock hour (read once from train.parquet, rounded to 5 and 4 decimals)
PROFILE = np.array([0.00845, 0.00494, 0.003, 0.00225, 0.00262, 0.01015, 0.03096, 0.06035, 0.09268, 0.10684, 0.09913, 0.07143, 0.05416,
                    0.05036, 0.05914, 0.07634, 0.08058, 0.05899, 0.03876, 0.02993, 0.0253, 0.01561, 0.01046, 0.00615])
NIGHT_OUT_RATE = np.array([0.4109, 0.3995, 0.3745, 0.3292, 0.2668, 0.174, 0.0624, 0.0496, 0.0565, 0.0714, 0.094, 0.1226, 0.1478, 0.1662,
                           0.1798, 0.1995, 0.2399, 0.2934, 0.3358, 0.364, 0.3875, 0.4099, 0.4192, 0.418])
NIGHT_HOURS = np.array([0, 1, 2, 3, 4, 5, 22, 23])
# Weekends and the holidays research.md names (4 to 6 April, 1 to 5 May and 8 to 10 June) carry holiday_flag = 1, except Sunday 7 April, which the
# real file marks as a working day: 31 of the 90 training days (read from train.parquet)
HOLIDAYS = {date(2024, 4, d) for d in (4, 5, 6)} | {date(2024, 5, d) for d in (1, 2, 3, 4, 5)} | {date(2024, 6, d) for d in (8, 9, 10)}
WORKING_DAYS = {date(2024, 4, 7)}
WEEKEND_FACTOR = 1.18

# The planted lifts: by band (the band number grows as the discount gets shallower, so the lift falls) and by management group
LIFT_BY_BAND = (1.20, 0.90, 0.70, 0.55, 0.40, 0.25, 0.12)
GROUP_MULTIPLIER = (1.0, 0.9, 1.1, 0.8, 1.2, 1.0, 0.95)
UNFLAGGED_LIFT = 0.15
# Thousandths of a discount that belong to each band of D13: [0, 0.5), [0.5, 0.6), ..., [0.9, 0.95), [0.95, 1]
BAND_THOUSANDTHS = ((200, 499), (500, 599), (600, 699), (700, 799), (800, 899), (900, 949), (950, 998))
PROMO_BAND_WEIGHTS = (0.01, 0.04, 0.12, 0.24, 0.44, 0.11, 0.04)
UNFLAGGED_BAND_WEIGHTS = (0.0, 0.0, 0.05, 0.10, 0.25, 0.25, 0.35)

SOURCE_COLUMNS = ("city_id", "store_id", "management_group_id", "first_category_id", "second_category_id", "third_category_id", "product_id",
                  "dt", "sale_amount", "hours_sale", "stock_hour6_22_cnt", "hours_stock_status", "discount", "holiday_flag", "activity_flag",
                  "precpt", "avg_temperature", "avg_humidity", "avg_wind_level")
SOURCE_ARROW_SCHEMA = pa.schema([
    ("city_id", pa.int64()), ("store_id", pa.int64()), ("management_group_id", pa.int64()), ("first_category_id", pa.int64()),
    ("second_category_id", pa.int64()), ("third_category_id", pa.int64()), ("product_id", pa.int64()), ("dt", pa.string()),
    ("sale_amount", pa.float64()), ("hours_sale", pa.list_(pa.field("element", pa.float64()))), ("stock_hour6_22_cnt", pa.int32()),
    ("hours_stock_status", pa.list_(pa.field("element", pa.int64()))), ("discount", pa.float64()), ("holiday_flag", pa.int32()), ("activity_flag", pa.int32()),
    ("precpt", pa.float64()), ("avg_temperature", pa.float64()), ("avg_humidity", pa.float64()), ("avg_wind_level", pa.float64()),
])

# Which rule of the plan (section 6) must catch each malformed variant; ``wrong_hash`` and ``oversize`` also need a limit that the test
# puts in the configuration (``Malformed.limits``)
MALFORMED_RULES = {
    "wrong_hash": "V01", "extra_column": "V02", "missing_column": "V02", "renamed_column": "V02", "wrong_type": "V02", "oversize": "V03",
    "short_list": "V04", "null_list": "V04", "nan_value": "V04", "negative_sale": "V04", "sale_over_cap": "V04", "bad_status": "V04",
    "duplicate_key": "V05", "date_outside": "V05", "two_groups": "V06", "missing_day": "V07",
}


@dataclass
class FixtureTruth:
    """What the generator knows. Arrays are indexed ``[series, day]`` (and ``[series, day, hour]``); the series are in the order of
    ``(store_id, product_id)``, the day 0 is 2024-03-28 and the hour is the clock hour (0-23)."""

    dir: Path
    train_path: Path
    eval_path: Path
    train_bytes: int
    eval_bytes: int
    train_sha256: str
    eval_sha256: str
    series: pd.DataFrame
    dates: list[date]
    train_days: int
    signal: str
    seed: int
    state: np.ndarray                  # int8 (S, D): PROMO, REGULAR, UNFLAGGED, ANOMALOUS
    band: np.ndarray                   # int8 (S, D): the band of a promo or unflagged day, -1 elsewhere
    flag: np.ndarray                   # int8 (S, D): activity_flag
    discount: np.ndarray               # float64 (S, D)
    holiday: np.ndarray                # int8 (D,)
    sales: np.ndarray                  # float64 (S, D, 24): what the file says
    stock: np.ndarray                  # int8 (S, D, 24): 1 = out of stock
    latent: np.ndarray                 # float64 (S, D, 24): the demand, whether or not the stock let it sell
    planted: dict[tuple[int, int], float]   # (group, band) -> planted lift of the cell
    planted_unflagged: float
    zero_series: np.ndarray            # series whose discount is 0 every day
    no_regular_series: np.ndarray      # series with no regular day at all
    extra: dict = field(default_factory=dict)

    @property
    def n_series(self) -> int:
        return len(self.series)

    @property
    def n_days(self) -> int:
        return len(self.dates)

    def hidden_demand(self) -> np.ndarray:
        """float64 (S, D, 24): the latent demand of the hours that were out of stock, 0 elsewhere."""
        return np.where(self.stock == 1, self.latent, 0.0)

    def rule_counts(self, days: slice | None = None) -> dict:
        """The counts the rules of the plan must find over the days of `days` (all of them by default), computed from the generator's arrays."""
        days = days or slice(None)
        state, flag, discount = self.state[:, days], self.flag[:, days], self.discount[:, days]
        stock = self.stock[:, days]
        core = stock[:, :, FIRST_HOUR:LAST_HOUR + 1]
        return {
            "series_days": int(state.size),
            "day_state": {name: int((state == code).sum()) for code, name in enumerate(STATE_NAMES)},
            "discount_zero": int((discount == 0).sum()),
            "discount_above_one": int((discount > 1).sum()),
            "discount_below_half": int(((discount > 0) & (discount < 0.5)).sum()),
            "flag_with_no_discount": int(((flag == 1) & (discount == 1.0)).sum()),
            "unflagged_cut": int((state == UNFLAGGED).sum()),
            "fully_out": int((core.sum(axis=2) == core.shape[2]).sum()),
            "night_out_hours": int(stock[:, :, NIGHT_HOURS].sum()),
            "holiday_days": int(self.holiday[days].sum()),
            "series_without_regular_day": int((~(state == REGULAR).any(axis=1)).sum()),
        }


@dataclass(frozen=True)
class Malformed:
    """A damaged copy of the fixture: where it is, which file holds the damage, the rule that must catch it and what the configuration
    must change for the rule to be reachable (``max_bytes`` or ``max_rows``); ``hash_from`` is the folder whose hashes the configuration
    keeps for ``wrong_hash`` (the damage is in the bytes, not in the accepted size)."""

    dir: Path
    file: str
    kind: str
    rule: str
    limits: dict = field(default_factory=dict)
    hash_from: Path | None = None


# --- the generator -----------------------------------------------------------------------------------------------------------


def _series_table(series: int) -> pd.DataFrame:
    """The first `series` pairs of (store, product), stores in order and products inside each store; every product has one chain of
    categories that ends in one management group, and every store one city."""
    stores = -(-series // N_PRODUCTS)
    rows = []
    for store in range(stores):
        for product in range(N_PRODUCTS):
            first_category = product // 2
            rows.append({
                "city_id": 1 + store % 3, "store_id": 10 * store + 3, "management_group_id": first_category % N_GROUPS,
                "first_category_id": 40 + first_category, "second_category_id": 20 + first_category // 2, "third_category_id": 100 + product,
                "product_id": 500 + 7 * product,
            })
    return pd.DataFrame(rows[:series]).sort_values(["store_id", "product_id"]).reset_index(drop=True)


def _draw_states(rng: np.random.Generator, n_series: int, n_days: int, group: np.ndarray):
    """Day states, bands, flags and discounts, and the series that carry a planted pattern."""
    S, D = n_series, n_days
    p = rng.beta(1.0, 1.6, S)                                   # the share of promoted days of each series
    stay = 0.75 + 0.25 * p
    start = 0.25 * p
    flagged = np.zeros((S, D), dtype=bool)
    current = rng.random(S) < p
    for d in range(D):                                          # promotions come in runs of a few days
        flagged[:, d] = current
        current = np.where(current, rng.random(S) < stay, rng.random(S) < start)
    zero_series = rng.choice(S, size=1, replace=False)
    others = np.setdiff1d(np.arange(S), zero_series)
    no_regular = rng.choice(others, size=max(1, round(0.03 * S)), replace=False)
    state = np.where(flagged, PROMO, REGULAR).astype(np.int8)
    cut_share = np.clip(0.22 * np.exp(0.7 * rng.standard_normal(S)), 0.0, 0.8)
    state[(~flagged) & (rng.random((S, D)) < cut_share[:, None])] = UNFLAGGED
    for s in no_regular:
        state[s][state[s] == REGULAR] = UNFLAGGED
    # anomalies: a series with discount 0 every day, scattered zeros (two of them flagged) and a few discounts above 1
    scatter = max(4, round(0.001 * S * D))
    free = np.argwhere((state != PROMO) & (~np.isin(np.arange(S), zero_series))[:, None])
    picks = free[rng.choice(len(free), size=scatter + 6, replace=False)]
    zero_rows, high_rows = picks[:scatter], picks[scatter:]
    promoted = np.argwhere((state == PROMO) & (~np.isin(np.arange(S), zero_series))[:, None])
    flagged_zero_rows = promoted[rng.choice(len(promoted), size=2, replace=False)]
    discount = np.ones((S, D))
    band = np.full((S, D), -1, dtype=np.int8)
    flag = (state == PROMO).astype(np.int8)
    for rows, kind in ((zero_rows, "zero"), (flagged_zero_rows, "zero"), (high_rows, "high")):
        for s, d in rows:
            state[s, d] = ANOMALOUS
            discount[s, d] = 0.0 if kind == "zero" else rng.integers(1001, 1089) / 1000
    state[zero_series[0], :] = ANOMALOUS
    discount[zero_series[0], :] = 0.0
    flag[zero_series[0], :] = 0
    for s, d in flagged_zero_rows:
        flag[s, d] = 1                                          # a flagged row whose discount is 0 (0.8 % of the real zeros)
    lo, hi = np.array(BAND_THOUSANDTHS).T
    for code, weights in ((PROMO, PROMO_BAND_WEIGHTS), (UNFLAGGED, UNFLAGGED_BAND_WEIGHTS)):
        rows = state == code
        n = int(rows.sum())
        drawn = rng.choice(len(weights), size=n, p=np.array(weights) / sum(weights))
        thousandths = rng.integers(lo[drawn], hi[drawn] + 1)
        values = thousandths / 1000
        if code == PROMO:                                       # half of the shallowest band has a flag and no discount at all
            values = np.where((drawn == 6) & (rng.random(n) < 0.5), 1.0, values)
        discount[rows] = values
        band[rows] = drawn
    regular = state == REGULAR
    discount[regular] = np.where(rng.random(int(regular.sum())) < 0.01, 0.999, 1.0)
    return state, band, flag, discount, zero_series, no_regular


def _stock_and_sales(rng: np.random.Generator, counts: np.ndarray, expected_core: np.ndarray):
    """Stock status and observed sale of every hour, from the demand in sales units (`counts`, (S, D, 24)).

    In the analysis hours the stock of a series-day is a multiple of the demand that a day without a promotion would bring: the demand of
    the hours so far is sold (in whole units) until it passes that stock, then the rest of the day sells nothing, with a few restocks. A few days have no
    stock at all. At night an hour is out of stock at the real rate of its clock hour."""
    S, D, _ = counts.shape
    core = counts[:, :, FIRST_HOUR:LAST_HOUR + 1]
    stock = np.exp(np.log(1.2) + 0.5 * rng.standard_normal((S, D))) * expected_core / UNIT      # in sales units
    closed = rng.random((S, D)) < 0.04
    stock[closed] = 0.0
    before = np.cumsum(core, axis=2) - core
    out = before >= stock[:, :, None]
    first_out = np.argmax(out, axis=2)
    had_out = out.any(axis=2) & ~closed
    restock = had_out & (rng.random((S, D)) < 0.14)
    back = first_out + rng.integers(1, 5, (S, D))
    refilled = restock[:, :, None] & (np.arange(core.shape[2])[None, None, :] >= back[:, :, None])
    out = out & ~refilled
    sold = np.where(out, 0.0, np.where(refilled, core, np.minimum(core, np.floor(np.maximum(stock[:, :, None] - before, 0.0)))))
    residual = out & (rng.random(out.shape) < 0.03)
    sold = np.where(residual, 1.0, sold)
    night = counts[:, :, NIGHT_HOURS]
    night_out = rng.random(night.shape) < NIGHT_OUT_RATE[NIGHT_HOURS]
    night_sold = np.where(night_out, np.where(rng.random(night.shape) < 0.03, 1.0, 0.0), night)
    sales = np.zeros(counts.shape)
    status = np.zeros(counts.shape, dtype=np.int8)
    sales[:, :, FIRST_HOUR:LAST_HOUR + 1] = sold * UNIT
    status[:, :, FIRST_HOUR:LAST_HOUR + 1] = out
    sales[:, :, NIGHT_HOURS] = night_sold * UNIT
    status[:, :, NIGHT_HOURS] = night_out
    return sales, status


def _list_column(values: np.ndarray, value_type: pa.DataType) -> pa.Array:
    offsets = pa.array(np.arange(0, values.size + 1, HOURS, dtype=np.int32))
    return pa.ListArray.from_arrays(offsets, pa.array(values.reshape(-1), type=value_type))


def _table(truth_arrays: dict, series: pd.DataFrame, rows: tuple[np.ndarray, np.ndarray], dates: list[date]) -> pa.Table:
    """The table of the series-days `rows` = (series index, day index) in the order given."""
    s_idx, d_idx = rows
    sales = truth_arrays["sales"][s_idx, d_idx]
    stock = truth_arrays["stock"][s_idx, d_idx]
    frame = series.iloc[s_idx]
    columns = {name: pa.array(frame[name].to_numpy(), type=SOURCE_ARROW_SCHEMA.field(name).type) for name in SOURCE_COLUMNS[:7]}
    columns["dt"] = pa.array([dates[d].isoformat() for d in d_idx])
    columns["sale_amount"] = pa.array(sales.sum(axis=1))
    columns["hours_sale"] = _list_column(sales, pa.float64())
    columns["stock_hour6_22_cnt"] = pa.array(stock[:, FIRST_HOUR:LAST_HOUR + 1].sum(axis=1).astype(np.int32), type=pa.int32())
    columns["hours_stock_status"] = _list_column(stock.astype(np.int64), pa.int64())
    columns["discount"] = pa.array(truth_arrays["discount"][s_idx, d_idx])
    columns["holiday_flag"] = pa.array(truth_arrays["holiday"][d_idx].astype(np.int32), type=pa.int32())
    columns["activity_flag"] = pa.array(truth_arrays["flag"][s_idx, d_idx].astype(np.int32), type=pa.int32())
    for name in SOURCE_COLUMNS[15:]:
        columns[name] = pa.array(truth_arrays["weather"][name][s_idx, d_idx])
    return pa.table(columns, schema=SOURCE_ARROW_SCHEMA)


def write_parquet(table: pa.Table, path: Path) -> tuple[int, str]:
    """Write `table` the way the dataset ships (row groups of 1,000 rows) and return its size and SHA-256."""
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path, row_group_size=1000)
    return path.stat().st_size, sha256_of(path)


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_fixture(out_dir: Path, series: int = 300, seed: int = 0, signal: str = "lift", days: int = 97) -> FixtureTruth:
    """Write ``train.parquet`` and ``eval.parquet`` into `out_dir` and return what the generator knows (the module docstring tells the model)."""
    if signal not in SIGNALS:
        raise ValueError(f"signal must be one of {SIGNALS}, not {signal!r}")
    if series < 1 or days < EVAL_DAYS + 1:
        raise ValueError(f"the fixture needs at least one series and {EVAL_DAYS + 1} days, got {series} and {days}")
    rng = np.random.default_rng(seed)
    out_dir = Path(out_dir)
    table = _series_table(series)
    S, D = len(table), days
    group = table["management_group_id"].to_numpy()
    dates = [FIRST_DAY + timedelta(days=i) for i in range(D)]
    weekend = np.array([d.weekday() >= 5 and d not in WORKING_DAYS for d in dates])
    holiday = (weekend | np.array([d in HOLIDAYS for d in dates])).astype(np.int8)
    level = np.where(holiday == 1, WEEKEND_FACTOR, 1.0)[None, :] * np.exp(0.08 * rng.standard_normal((N_GROUPS, D)))       # (group, day)
    state, band, flag, discount, zero_series, no_regular = _draw_states(rng, S, D, group)

    lift_cell = np.zeros((N_GROUPS, len(LIFT_BY_BAND)))
    unflagged_lift = 0.0
    if signal == "lift":
        lift_cell = np.outer(GROUP_MULTIPLIER, LIFT_BY_BAND)
        unflagged_lift = UNFLAGGED_LIFT
    lift = np.zeros((S, D))
    promo = state == PROMO
    lift[promo] = lift_cell[np.broadcast_to(group[:, None], (S, D))[promo], band[promo]]
    lift[state == UNFLAGGED] = unflagged_lift
    scale = np.exp(0.8 * rng.standard_normal(S))
    boost = np.where(discount == 0.0, 20.0, 1.0)                # the real rows with discount 0 sell about 20 times more
    base = scale[:, None] * level[group] * boost                # (S, D): the demand of a day with no promotion
    rate = base[:, :, None] * PROFILE[None, None, :] * (1.0 + lift)[:, :, None]
    counts = rng.poisson(rate / UNIT).astype(float)
    latent = counts * UNIT
    expected_core = base * PROFILE[FIRST_HOUR:LAST_HOUR + 1].sum()
    sales, stock = _stock_and_sales(rng, counts, expected_core)

    weather = {name: rng.normal(loc, spread, (S, D)) for name, loc, spread in
               (("precpt", 2.0, 3.0), ("avg_temperature", 22.0, 4.0), ("avg_humidity", 60.0, 10.0), ("avg_wind_level", 1.5, 0.5))}
    arrays = {"sales": sales, "stock": stock, "discount": discount, "flag": flag, "holiday": holiday, "weather": weather}
    train_days = D - EVAL_DAYS
    paths, sizes, hashes = {}, {}, {}
    for name, day_range in (("train", range(0, train_days)), ("eval", range(train_days, D))):
        s_idx = np.repeat(np.arange(S), len(day_range))
        d_idx = np.tile(np.array(day_range), S)
        paths[name] = out_dir / f"{name}.parquet"
        sizes[name], hashes[name] = write_parquet(_table(arrays, table, (s_idx, d_idx), dates), paths[name])
    planted = {(g, b): float(lift_cell[g, b]) for g in range(N_GROUPS) for b in range(len(LIFT_BY_BAND))}
    return FixtureTruth(
        dir=out_dir, train_path=paths["train"], eval_path=paths["eval"], train_bytes=sizes["train"], eval_bytes=sizes["eval"],
        train_sha256=hashes["train"], eval_sha256=hashes["eval"], series=table, dates=dates, train_days=train_days, signal=signal, seed=seed,
        state=state, band=band, flag=flag, discount=discount, holiday=holiday, sales=sales, stock=stock, latent=latent, planted=planted,
        planted_unflagged=unflagged_lift, zero_series=zero_series, no_regular_series=np.sort(no_regular),
    )


def fixture_config(cfg, folder: Path, *, train: Path | None = None, eval_: Path | None = None):
    """`cfg` pointed at the Parquet files of `folder` (or the two given paths) with their real sizes and hashes accepted."""
    train = Path(train or folder / "train.parquet")
    eval_ = Path(eval_ or folder / "eval.parquet")
    source = dataclasses.replace(
        cfg.source, train_path=train, train_bytes=train.stat().st_size, train_sha256=sha256_of(train),
        eval_path=eval_, eval_bytes=eval_.stat().st_size, eval_sha256=sha256_of(eval_))
    return dataclasses.replace(cfg, source=source)


# --- the malformed variants ----------------------------------------------------------------------------------------------------


def _replace_list_value(table: pa.Table, column: str, row: int, change) -> pa.Table:
    """A copy of `table` where the hourly list of `column` at `row` is `change(list)` (the other lists are untouched)."""
    values = table.column(column).to_pylist()
    values[row] = change(values[row])
    return table.set_column(table.schema.get_field_index(column), table.schema.field(column), pa.array(values, type=table.schema.field(column).type))


def _damage(table: pa.Table, kind: str) -> pa.Table:
    """`table` damaged in the way `kind` says, in its first row unless the kind says otherwise."""
    index = table.schema.get_field_index
    if kind == "wrong_hash":                                    # one value moves in the bytes; the size stays about the same
        return _replace_list_value(table, "hours_sale", 3, lambda v: [v[0] + 0.5, *v[1:]])
    if kind == "extra_column":
        return table.append_column("extra", pa.array(np.zeros(len(table))))
    if kind == "missing_column":
        return table.remove_column(index("precpt"))
    if kind == "renamed_column":
        return table.rename_columns(["price_factor" if name == "discount" else name for name in table.column_names])
    if kind == "wrong_type":
        return table.set_column(index("holiday_flag"), "holiday_flag", table.column("holiday_flag").cast(pa.string()))
    if kind == "short_list":
        return _replace_list_value(table, "hours_sale", 0, lambda v: v[:23])
    if kind == "null_list":
        values = table.column("hours_stock_status").to_pylist()
        values[0] = None
        return table.set_column(index("hours_stock_status"), table.schema.field("hours_stock_status"),
                                pa.array(values, type=table.schema.field("hours_stock_status").type))
    if kind == "nan_value":
        return _replace_list_value(table, "hours_sale", 0, lambda v: [float("nan"), *v[1:]])
    if kind == "negative_sale":
        return _replace_list_value(table, "hours_sale", 0, lambda v: [-0.5, *v[1:]])
    if kind == "sale_over_cap":
        return _replace_list_value(table, "hours_sale", 0, lambda v: [5000.0, *v[1:]])
    if kind == "bad_status":
        return _replace_list_value(table, "hours_stock_status", 0, lambda v: [2, *v[1:]])
    if kind == "duplicate_key":                                 # the second row of a series gets the date of its first row
        dts = table.column("dt").to_pylist()
        dts[1] = dts[0]
        return table.set_column(index("dt"), table.schema.field("dt"), pa.array(dts))
    if kind == "date_outside":
        dts = table.column("dt").to_pylist()
        dts[0] = "2024-08-01"
        return table.set_column(index("dt"), table.schema.field("dt"), pa.array(dts))
    if kind == "two_groups":                                    # the first row's product is also in another group
        groups = table.column("management_group_id").to_pylist()
        groups[0] = (groups[0] + 1) % N_GROUPS
        return table.set_column(index("management_group_id"), table.schema.field("management_group_id"), pa.array(groups, type=pa.int64()))
    if kind == "missing_day":
        return table.take(pa.array(np.delete(np.arange(len(table)), 5)))
    raise ValueError(f"unknown malformed kind {kind!r}; the known ones are {sorted(MALFORMED_RULES)}")


def make_malformed(base: FixtureTruth, kind: str, out_dir: Path) -> Malformed:
    """A copy of `base`'s two files in `out_dir` with `train.parquet` damaged in the way `kind` says (``MALFORMED_RULES`` names the rule that
    must catch it)."""
    if kind not in MALFORMED_RULES:
        raise ValueError(f"unknown malformed kind {kind!r}; the known ones are {sorted(MALFORMED_RULES)}")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(base.eval_path, out_dir / "eval.parquet")
    if kind == "oversize":                                      # nothing in the bytes: the test lowers the limit under the file's size
        shutil.copyfile(base.train_path, out_dir / "train.parquet")
        size = base.train_path.stat().st_size
        return Malformed(out_dir, "train", kind, MALFORMED_RULES[kind], {"max_bytes": size - 1})
    table = pq.read_table(base.train_path)
    write_parquet(_damage(table, kind), out_dir / "train.parquet")
    hash_from = base.dir if kind == "wrong_hash" else None
    return Malformed(out_dir, "train", kind, MALFORMED_RULES[kind], {}, hash_from)
