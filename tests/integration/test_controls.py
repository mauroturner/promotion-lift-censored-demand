"""The controls of the estimator (U08; D34, AC15): a lift that is planted in the synthetic fixture, with stock-outs that depend on the demand, must be found
(the positive control) and a fixture with no lift must give an interval that holds 0 (the negative one). The truth is the latent demand the generator drew.

What the positive control shows, in three steps, and why:

* with **the true demand** put back into the hours without stock (the oracle), the interval of the total and of every band holds the planted lift: the
  estimator (the fit, the records, the weights) can find a known effect;
* with the demand **recovered** by R2, the lift moves from the raw one toward the truth in every band and closes most of the gap, but the interval of the total
  does not hold the truth: a method that learns the level of a series from the hours that had stock reads low where stock-outs come on the days of more demand
  (the censoring that the synthetic mask cannot reproduce, D07); the remaining gap is a limit of the recovery and is told as such (D34, note of U08);
* the **raw** lift is below both.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from promolift.bootstrap import interval, two_way_draws
from promolift.cube import BlockInputs, group_index
from promolift.days import PROMO, REGULAR
from promolift.effect import CubeView, fit_ipf, lifts, naive_pooled, records, regular_mask
from promolift.masks import first_stockout_pmf
from promolift.recovery import Recovery, fit_base, recover_day
from promolift.split import block_of
from tests.fixtures.make_fixture import FIRST_HOUR, LAST_HOUR

HOURS = slice(FIRST_HOUR, LAST_HOUR + 1)
LAUNCH_DAYS = 90
BANDS = 7
RESAMPLES = 200
pytestmark = pytest.mark.slow


def estimates(truth, cfg):
    """The overall and per-band lift of the train block of a fixture, with the sale as recorded (``raw``), with the demand recovered by R2 (``recovered``) and
    with the true demand in the hours without stock (``oracle``); each with its two-way interval and the truth of what it estimates."""
    n = truth.n_series
    keys = np.array([int(d.strftime("%Y%m%d")) for d in truth.dates[:LAUNCH_DAYS]], dtype=np.int32)
    in_train = block_of(pd.to_datetime([d.isoformat() for d in truth.dates[:LAUNCH_DAYS]]), cfg).to_numpy() == "train"
    sales = truth.sales[:, :LAUNCH_DAYS, HOURS].astype(np.float32)
    stock, state, band = truth.stock[:, :LAUNCH_DAYS, HOURS], truth.state[:, :LAUNCH_DAYS], truth.band[:, :LAUNCH_DAYS]
    group = truth.series["management_group_id"].to_numpy()
    block = BlockInputs(np.arange(n, dtype=np.int32), keys, np.arange(FIRST_HOUR, LAST_HOUR + 1), sales, stock, state, band, group)
    groups = np.unique(group)
    rec = Recovery("r2", 0.25, fit_base(block, in_train), None, groups)
    recovered = np.stack([recover_day(rec, block.day(d)) for d in range(LAUNCH_DAYS)], axis=1).astype(np.float32)
    oracle = np.where(stock == 1, truth.latent[:, :LAUNCH_DAYS, HOURS], sales).astype(np.float32)
    days = np.flatnonzero(in_train)
    position = group_index(group, groups)
    out = {}
    for version, values in (("raw", sales), ("recovered", recovered), ("oracle", oracle)):
        view = CubeView(values[:, days], keys[days])
        flag = state[:, days]
        cf = fit_ipf(view, regular_mask(flag), position, cfg.effect.ipf_iterations, n_groups=len(groups), group_ids=groups, version=version)
        rec_ = records(view, cf, flag == PROMO, position)
        unit = band[:, days][rec_.series, rec_.day].astype(np.int64)
        total = np.zeros(len(unit), dtype=np.int64)
        low_t, high_t = interval(two_way_draws(rec_, total, 1, RESAMPLES, 0))
        low_b, high_b = interval(two_way_draws(rec_, unit, BANDS, RESAMPLES, 0))
        # the truth of the same series-days: the demand they had, over the demand they would have had without the planted lift of their cell
        latent = truth.latent[:, :LAUNCH_DAYS, HOURS].sum(axis=2)[:, days][rec_.series, rec_.day]
        planted = np.array([truth.planted[(int(group[s]), int(b))] for s, b in zip(rec_.series, unit, strict=True)])
        out[version] = SimpleNamespace(
            total=lifts(rec_, total, 1)[0], total_ci=(low_t[0], high_t[0]), band=lifts(rec_, unit, BANDS), band_ci=(low_b, high_b),
            true_total=latent.sum() / (latent / (1 + planted)).sum() - 1,
            true_band=np.array([latent[unit == k].sum() / (latent[unit == k] / (1 + planted[unit == k])).sum() - 1 for k in range(BANDS)]),
            series=len(np.unique(rec_.series)))
    return out


@pytest.fixture(scope="module")
def lift_estimates(signal_truth, quick_cfg):
    return estimates(signal_truth("lift"), quick_cfg)


@pytest.fixture(scope="module")
def null_estimates(signal_truth, quick_cfg):
    return estimates(signal_truth("null"), quick_cfg)


def test_positive_control_with_the_true_demand_the_interval_of_the_total_and_of_every_band_holds_the_planted_lift(lift_estimates):
    oracle = lift_estimates["oracle"]
    assert oracle.series > 200 and oracle.true_total > 0.3
    assert oracle.total_ci[0] <= oracle.true_total <= oracle.total_ci[1]
    low, high = oracle.band_ci
    assert ((low <= oracle.true_band) & (oracle.true_band <= high)).all(), (oracle.band, oracle.true_band, low, high)
    assert np.all(np.diff(oracle.true_band) < 0) and np.all(np.diff(oracle.band) < 0)           # deeper bands lift more, in the truth and in the estimate


def test_positive_control_recovers_the_planted_lift_and_raw_falls_below(lift_estimates):
    raw, recovered, oracle = (lift_estimates[v] for v in ("raw", "recovered", "oracle"))
    # the raw lift is below the recovered one, which is below the truth: the stock-outs hide part of the effect and recovering puts part of it back
    assert raw.total < recovered.total < recovered.true_total
    assert raw.total_ci[1] < recovered.total_ci[0]                      # and the two intervals do not even touch
    closed = (recovered.total - raw.total) / (recovered.true_total - raw.total)
    assert closed > 0.7, closed
    for k in range(BANDS):
        assert raw.band[k] < recovered.true_band[k] and abs(recovered.band[k] - recovered.true_band[k]) < abs(raw.band[k] - recovered.true_band[k]), k
    assert abs(oracle.total - oracle.true_total) < 0.5 * abs(recovered.total - recovered.true_total)     # what is left is the recovery's, not the estimator's


def test_negative_control_interval_contains_zero(null_estimates):
    for version in ("raw", "recovered", "oracle"):
        found = null_estimates[version]
        assert found.true_total == pytest.approx(0.0, abs=1e-12)
        assert found.total_ci[0] <= 0.0 <= found.total_ci[1], (version, found.total, found.total_ci)
        low, high = found.band_ci
        assert ((low <= 0.0) & (0.0 <= high)).all(), (version, found.band, low, high)


def test_naive_pooled_lift_differs_from_the_counterfactual_on_a_mixed_fixture():
    # twelve series with no effect at all: four large ones are promoted on every other day and eight small ones never are, so promoted days are the large series'
    # days and the pooled comparison reads a lift that is only the mix of products (research.md: +11 % naive against +34 % matched)
    rng = np.random.default_rng(0)
    size = np.array([100.0] * 4 + [5.0] * 8)
    days = 10
    values = size[:, None] * (1.0 + 0.02 * rng.standard_normal((12, days)))
    state = np.full((12, days), REGULAR, dtype=np.int8)
    state[:4, ::2] = PROMO
    view = CubeView(values[:, :, None], np.arange(days, dtype=np.int32))
    cf = fit_ipf(view, regular_mask(state), np.zeros(12, dtype=np.int64), 10, n_groups=1, group_ids=np.array([0]))
    matched = lifts(records(view, cf, state == PROMO, np.zeros(12, dtype=np.int64)), np.zeros(20, dtype=np.int64), 1)[0]
    naive = naive_pooled(view, state)
    assert naive > 3.0 and abs(matched) < 0.05, (naive, matched)
