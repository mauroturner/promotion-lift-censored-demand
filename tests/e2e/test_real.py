"""The real files (``real_data``; not in the default suite). Until U19, no test here reads ``eval.parquet`` beyond its size, its hash and its
schema, and none goes past the launch (D17): U04's part reads ``train.parquet`` only."""

from __future__ import annotations

import numpy as np
import pyarrow.parquet as pq
import pytest

from promolift.days import ANOMALOUS, PROMO, REGULAR, UNFLAGGED, band_of, day_state
from promolift.ingest import check_source, read_source
from promolift.schema import SOURCE_SCHEMA
from tests.conftest import REAL_EVAL, REAL_TRAIN

pytestmark = pytest.mark.real_data


@pytest.fixture(scope="module")
def real_train(cfg):
    return read_source(REAL_TRAIN, "train", cfg)


def test_the_real_files_have_the_accepted_sizes_and_hashes_and_the_eval_file_is_only_checked_that_way(cfg):
    assert check_source(cfg) == (cfg.source.train_sha256, cfg.source.eval_sha256)
    assert pq.read_schema(REAL_EVAL).remove_metadata().equals(SOURCE_SCHEMA)
    assert pq.ParquetFile(REAL_EVAL).metadata.num_rows == 350_000, "the row count comes from the footer: no value of the file is read"


def test_the_strict_read_of_the_real_train_file_finds_what_research_and_the_planner_measured(real_train, cfg):
    frames, report = real_train
    assert (report.rows, report.series, report.days) == (4_500_000, 50_000, 90)
    assert (report.first_day.isoformat(), report.last_day.isoformat()) == ("2024-03-28", "2024-06-25")
    assert (report.sale_amount_mismatch, report.stock_count_mismatch) == (0, 0), "sale_amount and stock_hour6_22_cnt are the sums of the hours (research.md, s01)"
    assert frames.sales.shape == (4_500_000, 24) and float(frames.sales.max()) <= cfg.source.max_hourly_sale
    assert frames.ids["management_group_id"].nunique() == 7 and frames.ids["store_id"].nunique() == 898 and frames.ids["product_id"].nunique() == 865


def test_the_day_states_of_the_real_train_file_are_the_planners_percentages(real_train, cfg):
    frames, _report = real_train
    states = day_state(frames.flag, frames.discount, cfg)
    share = {name: float((states == code).mean()) for name, code in (("promo", PROMO), ("regular", REGULAR), ("unflagged_cut", UNFLAGGED), ("anomalous", ANOMALOUS))}
    assert {k: round(v * 100, 2) for k, v in share.items()} == {"promo": 37.84, "regular": 47.69, "unflagged_cut": 14.11, "anomalous": 0.36}
    assert int((frames.discount == 0).sum()) == 16_039 and int((frames.discount > 1).sum()) == 34
    assert int(((frames.discount > 0) & (frames.discount < 0.5)).sum()) == 15_886
    assert int(((frames.flag == 1) & (frames.discount == 1.0)).sum()) == 38_378
    assert int((frames.discount == 1.0).sum()) == 2_181_121, "the discount of a day with no cut is exactly 1.0 (p01)"
    bands = band_of(frames.discount, cfg)
    assert set(np.unique(bands[states == PROMO])) == set(range(7))
    # the bands of every row with 0 < discount <= 1: research.md's table had [15886, 78127, 207326, 429102, 847707, 411689] before the 3,338 rows
    # that hold a float32 neighbour of 0.7, 0.8, 0.9 or 0.95 went to the band their clean twins are in (D13's note of 2026-11-17)
    assert np.bincount(bands[bands >= 0], minlength=7).tolist() == [15886, 78127, 207268, 429131, 845609, 412692, 2495214]
    noisy = (frames.discount != 0.9) & (np.abs(frames.discount - 0.9) < 1e-6)
    assert int(noisy.sum()) == 2127 and set(np.unique(bands[noisy])) == {5} and set(np.unique(bands[frames.discount == 0.9])) == {5}
