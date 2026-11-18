"""The recovery of the demand that stock-outs hide (U07; RF09, RF11, D06-D08; AC14): R1 and R2 exact in a hand case, hours with stock never change, the
fallbacks of the base, R3 and the choice by the error of the mass per series."""

from __future__ import annotations

import numpy as np
import pytest

from promolift.cube import BlockInputs, DayInputs
from promolift.days import ANOMALOUS, PROMO, REGULAR
from promolift.masks import Mask
from promolift.recovery import Recovery, choose, estimate, fit_base, hidden_mass, recover_day, wape_series
from tests.fixtures import hand_cases as hc

H = 16
HOURS = np.arange(6, 22)


def hand_block() -> BlockInputs:
    """The 2 series x 2 days of ``hand_cases.RECOVERY``: series 0 regular both days (hour 15 out on day 1), series 1 promo on day 0 and regular, with no stock
    at all, on day 1."""
    flag = hc.RECOVERY["flag"]
    return BlockInputs(
        series_key=np.arange(2, dtype=np.int32), date_keys=np.array([20240601, 20240602], dtype=np.int32), hours=HOURS,
        sales=hc.RECOVERY["sales"], stock=hc.RECOVERY["out"].astype(np.int8),
        state=np.where(flag == 1, PROMO, REGULAR).astype(np.int8), band=np.where(flag == 1, 3, -1).astype(np.int8), group=np.zeros(2, dtype=np.int64))


def test_r1_and_r2_by_hand_and_in_stock_hours_never_change():
    block = hand_block()
    base = fit_base(block)
    assert base.shape == (2, 2, H)
    # series 0, regular: the mean of the hours with stock of its two days; series 1 promo: day 0; series 1 regular has no hour with stock of its own
    # state and falls back to the mean of every state
    assert base[0, 0, 14] == pytest.approx(hc.RECOVERY["r1_base_series0"][14]) and base[0, 0, 15] == pytest.approx(hc.RECOVERY["r1_base_series0"][15])
    assert base[1, 1, 14] == base[1, 1, 15] == 1.0 and base[1, 0, 14] == base[1, 0, 15] == 1.0
    assert (base[:, :, :14] == 0).all()
    day1 = block.day(1)
    r1 = recover_day(Recovery("r1", None, base), day1)
    assert r1[0, 15] == pytest.approx(hc.RECOVERY["r1_recovered_s0_d1_h15"])
    assert r1[1, 14] == pytest.approx(hc.RECOVERY["r1_recovered_s1_d1"][14]) and r1[1, 15] == pytest.approx(hc.RECOVERY["r1_recovered_s1_d1"][15])
    for kappa, value in hc.RECOVERY["r2"].items():
        r2 = recover_day(Recovery("r2", kappa, base), day1)
        assert r2[0, 15] == pytest.approx(value, abs=1e-12), kappa
        assert r2[1, 14] == pytest.approx(hc.RECOVERY["r2_recovered_s1_d1"][14]) and r2[1, 15] == pytest.approx(hc.RECOVERY["r2_recovered_s1_d1"][15])
        # the hours with stock are exactly what was sold
        in_stock = day1.stock == 0
        assert np.array_equal(r2[in_stock], day1.sales[in_stock])
    # the other day is not touched where it had stock either, and a day with no hour out comes back as it was
    day0 = block.day(0)
    for rec in (Recovery("r1", None, base), Recovery("r2", 1.0, base), Recovery("r0", None, base)):
        assert np.array_equal(recover_day(rec, day0), day0.sales)


def test_the_method_zero_recovers_nothing_and_estimates_zero():
    block = hand_block()
    rec = Recovery("r0", None, fit_base(block))
    assert (estimate(rec, block.day(1)) == 0).all()
    assert np.array_equal(recover_day(rec, block.day(1)), block.day(1).sales)


def test_the_base_of_a_state_without_hours_falls_back_to_every_state_and_then_to_zero():
    sales = np.zeros((3, 3, H), dtype=np.float32)
    stock = np.zeros((3, 3, H), dtype=np.int8)
    state = np.array([[PROMO, PROMO, PROMO], [REGULAR, REGULAR, PROMO], [PROMO, REGULAR, REGULAR]], dtype=np.int8)
    sales[0, :, 10] = [1.0, 3.0, 5.0]                    # series 0 only has promo days
    sales[1, 0, 10], sales[1, 1, 10], sales[1, 2, 10] = 2.0, 4.0, 10.0
    stock[2, :, :] = 1                                   # series 2 never has stock
    block = BlockInputs(np.arange(3, dtype=np.int32), np.array([1, 2, 3], dtype=np.int32), HOURS, sales, stock, state, np.full((3, 3), -1, dtype=np.int8),
                        np.zeros(3, dtype=np.int64))
    base = fit_base(block)
    assert base[0, 1, 10] == pytest.approx(3.0) and base[0, 0, 10] == pytest.approx(3.0)      # no regular day: the mean of the promo ones
    assert base[1, 0, 10] == pytest.approx(3.0) and base[1, 1, 10] == pytest.approx(10.0)       # regular days 2 and 4; the promo day 10
    assert (base[2] == 0).all()                                                                  # never in stock: zero
    # only some days: the base is fitted on the days asked for
    only_first = fit_base(block, np.array([True, False, False]))
    assert only_first[0, 1, 10] == pytest.approx(1.0) and only_first[1, 0, 10] == pytest.approx(2.0)
    assert only_first[1, 1, 10] == pytest.approx(2.0)                                             # no promo day among the days asked for: every state


def test_a_state_other_than_promo_uses_the_base_of_the_days_without_a_flag_and_an_anomalous_day_is_not_in_the_fit():
    sales = np.zeros((1, 3, H), dtype=np.float32)
    sales[0, :, 9] = [2.0, 4.0, 1000.0]
    state = np.array([[REGULAR, 2, ANOMALOUS]], dtype=np.int8)       # regular, unflagged_cut, anomalous
    block = BlockInputs(np.zeros(1, dtype=np.int32), np.array([1, 2, 3], dtype=np.int32), HOURS, sales, np.zeros((1, 3, H), dtype=np.int8), state,
                        np.full((1, 3), -1, dtype=np.int8), np.zeros(1, dtype=np.int64))
    base = fit_base(block)
    assert base[0, 0, 9] == pytest.approx(3.0)                       # regular and unflagged share the base of the days without a flag; anomalous is out


def test_a_day_whose_base_has_no_mass_recovers_zero_and_never_divides_by_zero():
    day = DayInputs(np.zeros(1, dtype=np.int32), 1, HOURS, np.zeros((1, H), dtype=np.float32), np.ones((1, H), dtype=np.int8), np.array([REGULAR], dtype=np.int8),
                    np.array([-1], dtype=np.int8), np.zeros(1, dtype=np.int64))
    base = np.zeros((1, 2, H))
    for rec in (Recovery("r1", None, base), Recovery("r2", 0.25, base)):
        out = recover_day(rec, day)
        assert np.isfinite(out).all() and (out == 0).all()


def test_an_hour_without_stock_never_changes_the_estimate_whatever_its_recorded_sale():
    block = hand_block()
    base = fit_base(block)
    day = block.day(1)
    other_sales = day.sales.copy()
    other_sales[day.stock == 1] = 99.0
    other = DayInputs(day.series_key, day.date_key, day.hours, other_sales, day.stock, day.state, day.band, day.group)
    for rec in (Recovery("r1", None, base), Recovery("r2", 0.25, base), Recovery("r2", 1.0, base)):
        assert np.array_equal(estimate(rec, day), estimate(rec, other))
        assert np.array_equal(recover_day(rec, day), recover_day(rec, other))


def test_wape_and_bias_of_the_mass_per_series_are_the_hand_metrics():
    truth = np.array(hc.METRICS["truth"])
    series = np.array([0, 1, 2])
    assert wape_series(series, np.array(hc.METRICS["estimate_a"]), truth) == pytest.approx(hc.METRICS["wape_a"])
    assert wape_series(series, np.array(hc.METRICS["estimate_b"]), truth) == pytest.approx(hc.METRICS["wape_b"])
    # two series-days of one series: their errors cancel in the mass of the series
    assert wape_series(np.array([0, 0]), np.array([12.0, 8.0]), np.array([10.0, 10.0])) == 0.0
    assert wape_series(np.array([0, 1]), np.array([12.0, 8.0]), np.array([10.0, 10.0])) == pytest.approx(0.2)


def test_the_choice_uses_series_level_wape_of_the_hidden_mass():
    # one series, four hours hidden: it sold 4 in the last one and nothing in the first three. R1 spreads 1 per hour: wrong in every hour (hourly WAPE 150 %,
    # worse than zero's 100 %) and right in the mass of the series (0 %). The hourly error would choose zero; the mass chooses R1.
    sales = np.array([[0.0, 0.0, 0.0, 4.0]], dtype=np.float32)
    day = DayInputs(np.zeros(1, dtype=np.int32), 1, HOURS[:4], sales, np.zeros((1, 4), dtype=np.int8), np.array([REGULAR], dtype=np.int8),
                    np.array([-1], dtype=np.int8), np.zeros(1, dtype=np.int64))
    mask = Mask(np.array([0]), np.array([[True, True, True, True]]), np.array([6]))
    base = np.ones((1, 2, 4))
    estimates, truth = {}, None
    for name in ("r0", "r1"):
        estimates[name], truth = hidden_mass(Recovery(name, None, base), day, mask)
    assert estimates["r0"].tolist() == [0.0] and estimates["r1"].tolist() == [4.0] and truth.tolist() == [4.0]
    hourly = {"r0": 4.0 / 4.0, "r1": (3 * 1.0 + 3.0) / 4.0}
    assert hourly["r0"] < hourly["r1"]                      # the hourly WAPE of the hand case prefers zero
    choice = choose(estimates, truth, np.array([0]))
    assert choice.name == "r1" and choice.wape == {"r0": 1.0, "r1": 0.0}


def test_the_choice_breaks_a_tie_toward_the_first_candidate_and_a_better_one_must_win_by_more_than_the_tolerance():
    truth = np.array([10.0, 20.0])
    series = np.array([0, 1])
    same = {"r1": np.array([12.0, 18.0]), "r2@0.25": np.array([12.0, 18.0]), "r3": np.array([12.0, 18.0])}
    assert choose(same, truth, series).name == "r1"
    nearly = {"r1": np.array([12.0, 18.0]), "r2@0.25": np.array([12.0, 18.0 + 1e-9])}      # better by far less than 1e-6: the first stays
    assert choose(nearly, truth, series).name == "r1"
    better = {"r1": np.array([12.0, 18.0]), "r2@0.25": np.array([11.0, 19.0])}
    chosen = choose(better, truth, series)
    assert chosen.name == "r2@0.25" and chosen.wape["r1"] == pytest.approx(4 / 30) and chosen.wape["r2@0.25"] == pytest.approx(2 / 30)
    with pytest.raises(ValueError, match="candidato"):
        choose({}, truth, series)


def test_a_promo_day_is_recovered_from_the_promo_base_and_any_other_day_from_the_base_of_the_days_without_a_flag():
    # one series with a promo base of 10 and a plain base of 2 at hour 12; the same hour is out of stock on a promo, a regular and an unflagged day
    base = np.zeros((1, 2, H))
    base[0, 0, 6], base[0, 1, 6] = 2.0, 10.0
    states = [PROMO, REGULAR, 2]
    for state, expected in zip(states, (10.0, 2.0, 2.0), strict=True):
        stock = np.zeros((1, H), dtype=np.int8)
        stock[0, 6] = 1
        day = DayInputs(np.zeros(1, dtype=np.int32), 1, HOURS, np.zeros((1, H)), stock, np.array([state], dtype=np.int8), np.array([3], dtype=np.int8),
                        np.zeros(1, dtype=np.int64))
        assert recover_day(Recovery("r1", None, base), day)[0, 6] == expected
        assert estimate(Recovery("r2", 1.0, base), day)[0, 6] == pytest.approx(expected * (0 + 1.0 * expected) / (0 + 1.0 * expected))
