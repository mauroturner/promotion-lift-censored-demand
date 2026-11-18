"""The four forecasts of the promo series-days of a day (U08; RF17, D15; RNF06 h; AC21)."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from promolift.cube import DayInputs
from promolift.days import PROMO, REGULAR
from promolift.effect import Counterfactual, CubeView, Lifts, cell_of
from promolift.forecast import METHODS, ForecastError, forecast_errors, forecasts
from tests.fixtures import hand_cases as hc

VIEW = SimpleNamespace(forecast=SimpleNamespace(naive_days=3))
HOURS = np.array([6, 7])
HISTORY_KEYS = np.array([20240529, 20240530, 20240531], dtype=np.int32)


def hand_day():
    """Five series on 2024-06-01: 0 and 1 promo with a counterfactual, 2 regular, 3 promo with no counterfactual and 4 promo in a group without a factor."""
    stock = np.zeros((5, 2), dtype=np.int8)
    stock[1, 1] = 1
    sales = np.array([[5.0, 9.0], [4.0, 0.0], [1.0, 1.0], [3.0, 3.0], [2.0, 2.0]])
    state = np.array([PROMO, PROMO, REGULAR, PROMO, PROMO], dtype=np.int8)
    band = np.array([2, 5, -1, 2, 2], dtype=np.int8)
    group = np.array([10, 10, 10, 10, 20], dtype=np.int64)
    inputs = DayInputs(np.arange(5, dtype=np.int32), 20240601, HOURS, sales, stock, state, band, group)
    a = np.array([[1.0, 2.0], [1.0, 1.0], [9.0, 9.0], [np.nan, np.nan], [5.0, 5.0]])
    cf = Counterfactual(a, np.zeros((2, 1)), np.array([20240601], dtype=np.int32), "recovered", np.array([10, 20]))
    b_day = np.array([2.0, np.nan])
    cell = np.full(14, np.nan)
    cell[cell_of(np.array([0]), np.array([2]), 7)[0]] = 0.5          # the lift of the cell of series 0; the cell of series 1 has none
    history = np.zeros((5, 3, 2))
    history[0] = [[1, 2], [3, 4], [5, 6]]
    history[1] = [[1, 9], [2, 10], [3, 11]]
    return inputs, cf, b_day, Lifts(0.25, cell), CubeView(history, HISTORY_KEYS)


def test_each_promo_series_day_gets_the_four_forecasts_of_its_in_stock_hours_by_hand():
    inputs, cf, b_day, lifts, history = hand_day()
    result = forecasts(cf, b_day, lifts, inputs, history, VIEW)
    frame = result.frame.set_index(["series_key", "method"])
    assert list(METHODS) == ["f0_no_lift", "f1_naive", "f2a_overall_lift", "f2_cell_lift"] and len(frame) == 8
    got = {k: v for k, v in frame["forecast"].items()}
    assert got[(0, "f0_no_lift")] == pytest.approx(6.0) and got[(0, "f2a_overall_lift")] == pytest.approx(7.5) and got[(0, "f2_cell_lift")] == pytest.approx(9.0)
    assert got[(0, "f1_naive")] == pytest.approx(7.0)                    # the mean of each hour of the three days before: 3 and 4
    assert got[(1, "f0_no_lift")] == pytest.approx(2.0) and got[(1, "f1_naive")] == pytest.approx(2.0)          # only hour 6 had stock
    assert got[(1, "f2a_overall_lift")] == pytest.approx(2.5) and got[(1, "f2_cell_lift")] == pytest.approx(2.5)   # no lift for its cell: the overall one
    assert frame["observed_instock"].xs(0, level="series_key").unique().tolist() == [14.0] and frame["observed_instock"].xs(1, level="series_key").unique().tolist() == [4.0]
    assert set(result.frame.columns) >= {"series_key", "date_key", "method", "forecast", "observed_instock", "cell"} and set(result.frame["date_key"]) == {20240601}


def test_a_promo_series_day_that_cannot_be_forecast_is_listed_with_its_reason_and_a_regular_day_is_not_a_promo_day():
    inputs, cf, b_day, lifts, history = hand_day()
    result = forecasts(cf, b_day, lifts, inputs, history, VIEW)
    assert sorted(result.skipped["series_key"].tolist()) == [3, 4] and 2 not in set(result.frame["series_key"]) | set(result.skipped["series_key"])
    reasons = dict(zip(result.skipped["series_key"], result.skipped["reason"], strict=True))
    assert reasons == {3: "no_regular_day", 4: "no_day_factor"}
    assert set(result.frame["series_key"]) == {0, 1} and len(result.frame) == 2 * len(METHODS)


def test_the_naive_forecast_reads_the_days_before_and_nothing_else():
    inputs, cf, b_day, lifts, history = hand_day()
    for keys in (np.array([20240528, 20240530, 20240531], dtype=np.int32), np.array([20240530, 20240531, 20240601], dtype=np.int32),
                 np.array([20240530, 20240531], dtype=np.int32)):
        with pytest.raises(ForecastError, match="historia"):
            forecasts(cf, b_day, lifts, inputs, CubeView(history.values[:, : len(keys)], keys), VIEW)
    scrambled = history.values.copy()
    scrambled[2:] = 99.0                                                  # other series' history does not matter to series 0 and 1
    again = forecasts(cf, b_day, lifts, inputs, CubeView(scrambled, history.date_keys), VIEW).frame
    assert again["forecast"].tolist() == forecasts(cf, b_day, lifts, inputs, history, VIEW).frame["forecast"].tolist()


def test_the_wape_and_the_bias_of_a_forecast_are_the_hand_metrics():
    import pandas as pd

    frame = pd.DataFrame({"method": ["f2_cell_lift"] * 3 + ["f1_naive"] * 3, "forecast": [*hc.METRICS["forecast"], 10.0, 10.0, 10.0],
                          "observed_instock": hc.METRICS["observed"] * 2})
    out = forecast_errors(frame).set_index("method")
    assert out.loc["f2_cell_lift", "wape"] == pytest.approx(hc.METRICS["forecast_wape"]) and out.loc["f2_cell_lift", "bias"] == 0.0
    assert out.loc["f1_naive", "wape"] == 0.0 and list(out.columns) == ["rows", "wape", "bias"]
