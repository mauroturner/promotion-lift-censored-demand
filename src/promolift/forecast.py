"""The forecasts that say whether the lift of a cell adds information (RF17, D15; plan, section 14).

For each ``promo`` series-day of a day, the sale of its **hours with stock** (the only ones whose demand was seen) is forecast four ways: ``f0_no_lift`` the
counterfactual of the series and the group on that day (``sum of a(s, h) * b(g, d)`` over those hours); ``f2a_overall_lift`` that times one overall lift;
``f2_cell_lift`` that times the lift of the series-day's cell (the overall one where the cell has none); and ``f1_naive`` the mean sale of the same hours over the
``naive_days`` days before, the rule of the series itself. A forecast reads the series' own history up to the day before, the sealed ``a`` and lifts, and the
control days of other series on the same day (for ``b``): it measures whether the cell's lift adds information, not a forecast that could be made the day before
(RNF06 h, D15).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from promolift.cube import DayInputs, group_index
from promolift.days import PROMO
from promolift.effect import Counterfactual, CubeView, Lifts, cell_of, counterfactual

METHODS = ("f0_no_lift", "f1_naive", "f2a_overall_lift", "f2_cell_lift")


class ForecastError(ValueError):
    """The history handed to a forecast is not the days right before the day."""


@dataclass(frozen=True)
class ForecastResult:
    """``frame``: ``series_key``, ``date_key``, ``cell``, ``method``, ``forecast`` and ``observed_instock`` of each forecast, four rows per series-day;
    ``skipped``: the promo series-days that could not be forecast and why (``no_regular_day`` or ``no_day_factor``)."""

    frame: pd.DataFrame
    skipped: pd.DataFrame


def _previous_days(date_key: int, count: int) -> list[int]:
    day = date(date_key // 10_000, date_key // 100 % 100, date_key % 100)
    return [int((day - timedelta(days=k)).strftime("%Y%m%d")) for k in range(count, 0, -1)]


def forecasts(cf: Counterfactual, b_day: np.ndarray, lifts: Lifts, inputs: DayInputs, history: CubeView, view: Any) -> ForecastResult:
    """The four forecasts of every promo series-day of `inputs` (one day). `cf` holds the sealed ``a`` and ``group_ids``, `b_day` the factor of each group on this
    day, `lifts` the sealed lifts and `history` the sale of the ``naive_days`` days right before the day, in order."""
    days = view.forecast.naive_days
    expected = _previous_days(inputs.date_key, days)
    if np.asarray(history.date_keys).tolist() != expected or history.values.shape[1] != days:
        raise ForecastError(f"la historia de la regla ingenua son los {days} días justo antes del {inputs.date_key} ({expected[0]} a {expected[-1]}), "
                            f"se recibió {np.asarray(history.date_keys).tolist()}")
    group = group_index(inputs.group, cf.group_ids)
    promo = np.flatnonzero(inputs.state == PROMO)
    has_a = np.isfinite(cf.a[inputs.series_key[promo]]).all(axis=1)
    has_b = np.isfinite(b_day[group[promo]])
    usable = promo[has_a & has_b]
    skipped = pd.DataFrame({"series_key": inputs.series_key[promo[~(has_a & has_b)]],
                            "reason": np.where(has_a[~(has_a & has_b)], "no_day_factor", "no_regular_day")})
    in_stock = inputs.stock[usable] == 0
    series = inputs.series_key[usable].astype(np.intp)
    day_cf = Counterfactual(cf.a, np.asarray(b_day)[:, None], np.array([inputs.date_key], dtype=np.int32), cf.version, cf.group_ids)
    f0 = counterfactual(day_cf, group, series, np.zeros(len(usable), dtype=np.intp), in_stock)
    cell = cell_of(group[usable], inputs.band[usable], len(view.days.bands) - 1)
    cell_lift = np.where(cell >= 0, lifts.cell[np.maximum(cell, 0)], np.nan)
    f1 = np.where(in_stock, history.values[series].mean(axis=1, dtype=np.float64), 0.0).sum(axis=1)
    observed = np.where(in_stock, inputs.sales[usable], 0.0).sum(axis=1, dtype=np.float64)
    forecast = {"f0_no_lift": f0, "f1_naive": f1, "f2a_overall_lift": f0 * (1.0 + lifts.overall),
                "f2_cell_lift": f0 * (1.0 + np.where(np.isfinite(cell_lift), cell_lift, lifts.overall))}
    frame = pd.concat([pd.DataFrame({"series_key": series.astype(np.int32), "date_key": inputs.date_key, "cell": cell, "method": method, "forecast": forecast[method],
                                     "observed_instock": observed}) for method in METHODS], ignore_index=True)
    return ForecastResult(frame.sort_values(["series_key", "method"], kind="stable").reset_index(drop=True), skipped.reset_index(drop=True))


def forecast_errors(frame: pd.DataFrame) -> pd.DataFrame:
    """``method``, ``rows``, ``wape`` (``sum |forecast - observed| / sum observed``) and ``bias`` (``sum (forecast - observed) / sum observed``) of each method."""
    rows = []
    for method, part in frame.groupby("method", sort=False):
        observed = part["observed_instock"].to_numpy(dtype=np.float64)
        gap = part["forecast"].to_numpy(dtype=np.float64) - observed
        rows.append({"method": method, "rows": len(part), "wape": float(np.abs(gap).sum() / observed.sum()), "bias": float(gap.sum() / observed.sum())})
    return pd.DataFrame(rows, columns=["method", "rows", "wape", "bias"])
