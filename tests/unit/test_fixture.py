"""The synthetic fixture (U03; D34): the real schema and calendar, the counts the generator says, a stock that runs out earlier on the days with
more demand, the planted patterns, the null variant, determinism, the malformed variants and the configuration that accepts a pair."""

from __future__ import annotations

import dataclasses
import hashlib
from datetime import date, timedelta

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from tests.fixtures.make_fixture import (
    ANOMALOUS,
    LIFT_BY_BAND,
    MALFORMED_RULES,
    N_GROUPS,
    NIGHT_HOURS,
    PROMO,
    REGULAR,
    SOURCE_ARROW_SCHEMA,
    SOURCE_COLUMNS,
    STATE_NAMES,
    UNFLAGGED,
    UNIT,
    FixtureTruth,
    Malformed,
    fixture_config,
    make_fixture,
    make_malformed,
)

TRAIN_DAYS, EVAL_DAYS = 90, 7


class Reading:
    """A Parquet file read by an independent reader (pyarrow, column by column), ordered by (store, product, day)."""

    def __init__(self, path):
        table = pq.read_table(path)
        self.table = table
        order = np.lexsort((np.array(table.column("dt").to_pylist()), table.column("product_id").to_numpy(), table.column("store_id").to_numpy()))
        self.order = order
        self.rows = len(table)
        self.sales = np.array(table.column("hours_sale").combine_chunks().flatten()).reshape(-1, 24)[order]
        self.stock = np.array(table.column("hours_stock_status").combine_chunks().flatten()).reshape(-1, 24)[order]
        for name in ("discount", "activity_flag", "holiday_flag", "sale_amount", "stock_hour6_22_cnt", "store_id", "product_id"):
            setattr(self, name, table.column(name).to_numpy()[order])
        self.dt = np.array(table.column("dt").to_pylist())[order]


@pytest.fixture(scope="module")
def readings(fixture_truth):
    return Reading(fixture_truth.train_path), Reading(fixture_truth.eval_path)


def test_truth_counts_match_the_parquet_and_stockouts_come_earlier_on_high_demand_days(fixture_truth, readings):
    t, (train, eval_) = fixture_truth, readings
    S = t.n_series
    assert (train.rows, eval_.rows) == (S * TRAIN_DAYS, S * EVAL_DAYS) and t.n_days == 97 and t.train_days == TRAIN_DAYS
    # every count the rules of the plan will look for, recomputed from the files, is the one the generator says
    for reading, days in ((train, slice(0, TRAIN_DAYS)), (eval_, slice(TRAIN_DAYS, 97))):
        expected = t.rule_counts(days)
        core = reading.stock[:, 6:22]
        got = {
            "series_days": reading.rows,
            "discount_zero": int((reading.discount == 0).sum()),
            "discount_above_one": int((reading.discount > 1).sum()),
            "discount_below_half": int(((reading.discount > 0) & (reading.discount < 0.5)).sum()),
            "flag_with_no_discount": int(((reading.activity_flag == 1) & (reading.discount == 1.0)).sum()),
            "fully_out": int((core.sum(axis=1) == 16).sum()),
            "night_out_hours": int(reading.stock[:, NIGHT_HOURS].sum()),
            "holiday_days": int(len(set(reading.dt[reading.holiday_flag == 1]))),
        }
        assert {key: expected[key] for key in got} == got
    # the day state and the band the generator drew are what the rule of D04 and the bands of D13 say about the file's flag and discount
    flat = lambda a: a[:, :TRAIN_DAYS].reshape(-1)  # noqa: E731
    flag, discount = train.activity_flag, train.discount
    by_rule = np.where((discount <= 0) | (discount > 1), ANOMALOUS, np.where(flag == 1, PROMO, np.where(discount >= 0.999, REGULAR, UNFLAGGED)))
    assert np.array_equal(by_rule, flat(t.state)), "the generator's day states follow the rule of D04"
    band = np.clip(np.digitize(discount, [0.5, 0.6, 0.7, 0.8, 0.9, 0.95]), 0, 6)
    cut = np.isin(by_rule, (PROMO, UNFLAGGED))
    assert np.array_equal(np.where(cut, band, -1), flat(t.band)), "the bands are those of D13, with the discount 1 in the last one"
    assert int(t.rule_counts(slice(0, TRAIN_DAYS))["day_state"]["anomalous"]) == int((by_rule == ANOMALOUS).sum())

    # the stock: the real file's shape (a fifth of the hours, a bit under half of the days with a stock-out, a few days with none)
    core = train.stock[:, 6:22]
    out_days = core.sum(axis=1) > 0
    assert 0.15 < core.mean() < 0.26 and 0.35 < out_days.mean() < 0.55 and 0.025 < (core.sum(axis=1) == 16).mean() < 0.06
    assert core[:, 15].mean() > 3 * core[:, 0].mean(), "stock-outs pile up towards the evening"
    until_the_end = core[out_days & (core.sum(axis=1) < 16), 15] == 1
    assert 0.80 < until_the_end.mean() < 0.95, "most stock-outs last until the day closes"

    # stock-outs come earlier on the days with more demand: promoted days against regular ones, and the top against the bottom third of
    # the days of every series
    first_out = np.where(out_days, np.argmax(core == 1, axis=1), -1)
    partial = out_days & (core.sum(axis=1) < 16) & (first_out > 0)
    promoted, regular = (by_rule == PROMO) & partial, (by_rule == REGULAR) & partial
    assert first_out[promoted].mean() < first_out[regular].mean() - 0.5
    assert out_days[by_rule == PROMO].mean() > out_days[by_rule == REGULAR].mean() + 0.05
    day_demand = t.latent[:, :TRAIN_DAYS, 6:22].sum(axis=2)
    ratio = (day_demand / np.median(day_demand, axis=1, keepdims=True)).reshape(-1)
    usual = (by_rule == REGULAR) & partial
    low, high = ratio <= np.quantile(ratio[usual], 1 / 3), ratio >= np.quantile(ratio[usual], 2 / 3)
    assert first_out[usual & high].mean() < first_out[usual & low].mean() - 0.5, "a day with more demand than usual runs out earlier"


def test_the_files_have_the_real_schema_and_the_real_calendar(fixture_truth, readings):
    t, (train, eval_) = fixture_truth, readings
    for path, days in ((t.train_path, TRAIN_DAYS), (t.eval_path, EVAL_DAYS)):
        file = pq.ParquetFile(path)
        assert file.schema_arrow.equals(SOURCE_ARROW_SCHEMA) and file.schema_arrow.names == list(SOURCE_COLUMNS) and len(SOURCE_COLUMNS) == 19
        assert file.metadata.num_rows == t.n_series * days and file.metadata.num_row_groups == -(-t.n_series * days // 1000)
    assert str(SOURCE_ARROW_SCHEMA.field("hours_sale").type) == "list<element: double>"
    assert str(SOURCE_ARROW_SCHEMA.field("hours_stock_status").type) == "list<element: int64>"
    first = date(2024, 3, 28)
    assert sorted(set(train.dt)) == [(first + timedelta(i)).isoformat() for i in range(TRAIN_DAYS)]
    assert sorted(set(eval_.dt)) == [(date(2024, 6, 26) + timedelta(i)).isoformat() for i in range(EVAL_DAYS)]
    assert train.dt[0] == "2024-03-28" and eval_.dt[-1] == "2024-07-02"
    for reading in (train, eval_):
        keys = set(zip(reading.store_id.tolist(), reading.product_id.tolist(), reading.dt.tolist()))
        assert len(keys) == reading.rows, "one row per (store, product, day)"
    assert t.n_series == 300 and train.holiday_flag.sum() / t.n_series == 31 and train.holiday_flag[train.dt == "2024-04-07"].sum() == 0, "31 of the 90 training days carry holiday_flag, as the real file"
    assert (t.train_bytes, t.train_sha256) == (t.train_path.stat().st_size, hashlib.sha256(t.train_path.read_bytes()).hexdigest())
    assert (t.eval_bytes, t.eval_sha256) == (t.eval_path.stat().st_size, hashlib.sha256(t.eval_path.read_bytes()).hexdigest())


def test_the_hierarchy_has_one_chain_per_product_one_city_per_store_and_seven_groups(fixture_truth, readings):
    table = readings[0].table.to_pandas()
    chain = ["management_group_id", "first_category_id", "second_category_id", "third_category_id"]
    assert table.groupby("product_id")[chain].nunique().max().max() == 1
    assert table.groupby("store_id")["city_id"].nunique().max() == 1
    assert table["management_group_id"].nunique() == N_GROUPS and table["city_id"].nunique() == 3
    assert table["store_id"].nunique() == 20 and table["product_id"].nunique() == 15 and table["first_category_id"].nunique() == 8
    assert (table.groupby("management_group_id")["first_category_id"].nunique() >= 1).all()
    assert table["store_id"].min() == 3 and table["product_id"].min() == 500, "the ids are not 0, 1, 2, ..."


def test_what_is_planted_is_in_the_files(fixture_truth, readings):
    t, (train, eval_) = fixture_truth, readings
    S = t.n_series
    counts = t.rule_counts()
    assert len(t.zero_series) == 1 and (t.discount[t.zero_series[0]] == 0).all() and (t.state[t.zero_series[0]] == ANOMALOUS).all()
    assert counts["discount_zero"] >= 97 + 4
    assert counts["discount_above_one"] == 6 and counts["discount_below_half"] > 0 and counts["flag_with_no_discount"] > 0
    assert (t.flag[(t.discount == 0)] == 1).sum() == 2, "two of the zero-discount rows carry the flag"
    assert (t.discount == 0.999).any() and (t.state[t.discount == 0.999] == REGULAR).all()
    assert counts["unflagged_cut"] > 0 and counts["fully_out"] > 0 and counts["night_out_hours"] > 0
    assert len(t.no_regular_series) == 9 and not (t.state[t.no_regular_series] == REGULAR).any()
    assert counts["series_without_regular_day"] >= 9 and t.rule_counts(slice(0, TRAIN_DAYS))["series_without_regular_day"] >= 9
    share = {name: counts["day_state"][name] / (S * 97) for name in STATE_NAMES}
    assert 0.30 < share["promo"] < 0.45 and 0.40 < share["regular"] < 0.60 and 0.08 < share["unflagged_cut"] < 0.25 and share["anomalous"] < 0.02
    # the identities of the real file
    for reading in (train, eval_):
        assert np.array_equal(reading.sale_amount, reading.sales.sum(axis=1)), "sale_amount is the sum of the hours"
        assert np.array_equal(reading.stock_hour6_22_cnt, reading.stock[:, 6:22].sum(axis=1)), "stock_hour6_22_cnt counts the hours 6 to 21"
        assert reading.sales.min() >= 0 and reading.sales.max() <= 1000 and set(np.unique(reading.stock)) <= {0, 1}
        assert np.allclose(reading.sales / UNIT, np.round(reading.sales / UNIT)), "sales are multiples of the unit"


def test_the_latent_demand_is_what_the_stock_let_sell_plus_what_it_hid(fixture_truth):
    t = fixture_truth
    in_stock, out = t.stock == 0, t.stock == 1
    assert (t.sales[in_stock] <= t.latent[in_stock] + 1e-9).all(), "an hour with stock never sells more than the demand"
    residual = t.sales[out] > 0
    assert 0.015 < residual.mean() < 0.045 and np.allclose(t.sales[out][residual], UNIT), "a few out-of-stock hours keep one unit of sale"
    hidden = t.hidden_demand()
    assert (hidden[in_stock] == 0).all() and hidden[:, :, 6:22].sum() > 0.1 * t.latent[:, :, 6:22].sum()
    # the cap hour is the only in-stock hour that sells less than its demand on a day that did not restock: some do, most do not
    censored = in_stock & (t.sales < t.latent - 1e-9)
    assert 0 < censored.sum() < 0.05 * in_stock.sum()
    assert t.latent.shape == t.sales.shape == t.stock.shape == (300, 97, 24)


def test_the_planted_lifts_fall_with_the_band_number_and_the_null_variant_has_none(fixture_truth, signal_truth):
    t = fixture_truth
    assert t.signal == "lift" and len(t.planted) == N_GROUPS * 7
    for g in range(N_GROUPS):
        lifts = [t.planted[(g, b)] for b in range(7)]
        assert lifts == sorted(lifts, reverse=True) and lifts[0] > 0.8 and lifts[-1] < 0.2, "deeper discounts carry the larger lifts"
    assert t.planted[(0, 0)] == LIFT_BY_BAND[0] and t.planted_unflagged == 0.15
    null = signal_truth("null")
    assert null.signal == "null" and set(null.planted.values()) == {0.0} and null.planted_unflagged == 0.0
    assert len(t.planted) == len(null.planted)


def test_the_null_variant_draws_the_same_structure_and_only_the_demand_changes(fixture_truth, signal_truth):
    t, null = fixture_truth, signal_truth("null")
    for name in ("state", "band", "flag", "discount", "holiday"):
        assert np.array_equal(getattr(t, name), getattr(null, name)), name
    assert t.series.equals(null.series) and t.dates == null.dates
    assert not np.array_equal(t.sales, null.sales) and t.sales.sum() > null.sales.sum()
    promo = t.state == PROMO
    ratio = t.latent[promo][:, 6:22].sum() / null.latent[promo][:, 6:22].sum()
    assert 1.3 < ratio < 1.8, "the planted lifts raise the demand of the promoted days by about half"
    regular = t.state == REGULAR
    assert abs(t.latent[regular][:, 6:22].sum() / null.latent[regular][:, 6:22].sum() - 1) < 0.05, "and leave the regular days alone"


def test_the_same_seed_writes_the_same_bytes_and_another_seed_other_ones(small_truth, tmp_path):
    again = make_fixture(tmp_path / "again", series=60, seed=0)
    assert (again.train_sha256, again.eval_sha256) == (small_truth.train_sha256, small_truth.eval_sha256)
    assert np.array_equal(again.latent, small_truth.latent) and np.array_equal(again.state, small_truth.state)
    other = make_fixture(tmp_path / "other", series=60, seed=1)
    assert other.train_sha256 != small_truth.train_sha256 and not np.array_equal(other.state, small_truth.state)


def test_the_arguments_are_checked_and_the_size_follows_them(tmp_path):
    with pytest.raises(ValueError, match="signal"):
        make_fixture(tmp_path / "x", series=10, signal="sparkle")
    with pytest.raises(ValueError, match="days"):
        make_fixture(tmp_path / "y", series=10, days=7)
    with pytest.raises(ValueError, match="series"):
        make_fixture(tmp_path / "z", series=0)
    small = make_fixture(tmp_path / "w", series=12, seed=3, days=20)
    assert (small.n_series, small.n_days, small.train_days) == (12, 20, 13)
    assert pq.ParquetFile(small.train_path).metadata.num_rows == 12 * 13 and pq.ParquetFile(small.eval_path).metadata.num_rows == 12 * 7


# --- the malformed variants ------------------------------------------------------------------------------------------------


def damaged(malformed: Malformed) -> pa.Table:
    return pq.read_table(malformed.dir / "train.parquet")


CHECKS = {
    "wrong_hash": lambda base, bad: bad.drop(["hours_sale"]).equals(base.drop(["hours_sale"])) and not bad.equals(base),
    "extra_column": lambda base, bad: bad.column_names == [*base.column_names, "extra"],
    "missing_column": lambda base, bad: set(base.column_names) - set(bad.column_names) == {"precpt"},
    "renamed_column": lambda base, bad: "price_factor" in bad.column_names and "discount" not in bad.column_names,
    "wrong_type": lambda base, bad: str(bad.schema.field("holiday_flag").type) == "string",
    "short_list": lambda base, bad: len(bad.column("hours_sale")[0]) == 23,
    "null_list": lambda base, bad: bad.column("hours_stock_status")[0].as_py() is None,
    "nan_value": lambda base, bad: bool(np.isnan(bad.column("hours_sale")[0].as_py()[0])),
    "negative_sale": lambda base, bad: bad.column("hours_sale")[0].as_py()[0] < 0,
    "sale_over_cap": lambda base, bad: bad.column("hours_sale")[0].as_py()[0] > 1000,
    "bad_status": lambda base, bad: 2 in bad.column("hours_stock_status")[0].as_py(),
    "duplicate_key": lambda base, bad: bad.column("dt")[0] == bad.column("dt")[1] and bad.column("store_id")[0] == bad.column("store_id")[1],
    "date_outside": lambda base, bad: bad.column("dt")[0].as_py() == "2024-08-01",
    "two_groups": lambda base, bad: bad.to_pandas().groupby("product_id")["management_group_id"].nunique().max() == 2,
    "missing_day": lambda base, bad: len(bad) == len(base) - 1,
    "oversize": lambda base, bad: bad.equals(base),
}


def test_every_malformed_kind_is_listed_with_its_rule_and_its_check():
    assert set(MALFORMED_RULES) == set(CHECKS) and len(MALFORMED_RULES) == 16
    assert {MALFORMED_RULES[k] for k in MALFORMED_RULES} == {"V01", "V02", "V03", "V04", "V05", "V06", "V07"}
    with pytest.raises(ValueError, match="unknown malformed kind"):
        make_malformed(None, "sparkle", None)  # type: ignore[arg-type]


@pytest.mark.parametrize("kind", sorted(MALFORMED_RULES))
def test_a_malformed_variant_is_the_fixture_damaged_in_one_way_and_names_its_rule(kind, malformed, small_truth):
    bad = malformed(kind)
    assert isinstance(bad, Malformed) and (bad.kind, bad.file, bad.rule) == (kind, "train", MALFORMED_RULES[kind])
    base = pq.read_table(small_truth.train_path)
    assert CHECKS[kind](base, damaged(bad)), kind
    assert (bad.dir / "eval.parquet").read_bytes() == small_truth.eval_path.read_bytes(), "the other file is the base's, byte for byte"
    assert small_truth.train_sha256 == hashlib.sha256(small_truth.train_path.read_bytes()).hexdigest(), "the base is untouched"
    if kind == "oversize":
        assert bad.limits == {"max_bytes": small_truth.train_path.stat().st_size - 1}
    else:
        assert bad.limits == {}
    assert (bad.hash_from == small_truth.dir) == (kind == "wrong_hash")
    if kind in ("short_list", "null_list", "nan_value", "negative_sale", "sale_over_cap", "bad_status", "duplicate_key", "date_outside",
                "two_groups", "missing_day", "wrong_hash"):
        other = [c for c in base.column_names if c not in ("hours_sale", "hours_stock_status", "dt", "management_group_id")]
        if kind != "missing_day":
            assert damaged(bad).select(other).equals(base.select(other)), "nothing else changed"


def test_fixture_config_accepts_the_real_sizes_and_hashes_of_a_pair(cfg, fixture_truth, malformed):
    accepted = fixture_config(cfg, fixture_truth.dir)
    assert (accepted.source.train_bytes, accepted.source.train_sha256) == (fixture_truth.train_bytes, fixture_truth.train_sha256)
    assert (accepted.source.eval_bytes, accepted.source.eval_sha256) == (fixture_truth.eval_bytes, fixture_truth.eval_sha256)
    assert accepted.source.train_path == fixture_truth.train_path and accepted.calendar == cfg.calendar
    assert dataclasses.replace(accepted.source, train_path=cfg.source.train_path, train_bytes=0, train_sha256="", eval_path=cfg.source.eval_path,
                               eval_bytes=0, eval_sha256="") == dataclasses.replace(
        cfg.source, train_bytes=0, train_sha256="", eval_bytes=0, eval_sha256="")
    bad = malformed("extra_column")
    assert fixture_config(cfg, bad.dir).source.train_sha256 == hashlib.sha256((bad.dir / "train.parquet").read_bytes()).hexdigest()
    assert isinstance(fixture_truth, FixtureTruth)
