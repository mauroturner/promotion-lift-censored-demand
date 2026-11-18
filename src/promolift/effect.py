"""The counterfactual and the effects (RF12, RF13, D09-D11; plan, section 12).

**The model** (D09): what a series sells in an hour of a day without a promotion is ``a(s, h) * b(g(s), d)``: a level of the series at that hour times a factor of its
management group on that day. It is the Poisson model with series-hour and group-day effects, fitted by iterative proportional fitting (IPF) on the ``regular`` days
only (flag 0 and no cut), so the control is a day where nothing was going on. ``a`` absorbs the level and the hourly profile of every series; ``b`` absorbs the day of
the week, holidays, the shift between periods and the shocks that a group shares in a day. What it cannot absorb is why a promotion was launched when it was.

**The lift** (D10) of a unit is ``sum(observed) / sum(counterfactual) - 1`` over its series-days and the analysis hours; ``raw`` fits and observes on the sale as
recorded, ``recovered`` on the demand recovered where the stock ran out. A series with no regular day has no ``a`` and enters no effect.

Every value that counts here is an association within a series, adjusted for the hour and the day of the group: never a causal effect.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from promolift.days import ANOMALOUS, PROMO, REGULAR, UNFLAGGED

CONTROLS = ("regular", "any_flag0")


@dataclass(frozen=True)
class CubeView:
    """The hours of a run of days: ``values`` (series, days, hours) and the ``date_keys`` of the days."""

    values: np.ndarray
    date_keys: np.ndarray


@dataclass(frozen=True)
class Counterfactual:
    """``a`` (series, hours), NaN for a series with no day of control; ``b`` (groups, days) aligned with ``days``; ``group_ids`` the sorted management group ids
    that the rows of ``b`` stand for."""

    a: np.ndarray
    b: np.ndarray
    days: np.ndarray
    version: str
    group_ids: np.ndarray


@dataclass(frozen=True)
class Records:
    """What a unit's lift is computed from: for each series-day that has a counterfactual, its ``series`` and ``day`` (positions in the view), what was
    ``observed`` and what the model says (``counterfactual``), both summed over the hours; ``n_series`` and ``n_days`` are the series and the days of the view
    (the populations the intervals resample) and ``dropped`` the series-days asked for that have no counterfactual."""

    series: np.ndarray
    day: np.ndarray
    observed: np.ndarray
    counterfactual: np.ndarray
    n_series: int
    n_days: int
    dropped: int


@dataclass(frozen=True)
class Lifts:
    """The lift of the whole flagged period and of each cell, as the launch sealed them (the forecasts read them)."""

    overall: float
    cell: np.ndarray


def regular_mask(state: np.ndarray, control: str = "regular") -> np.ndarray:
    """The series-days of the control: only ``regular`` days (D04), or, for the variant ``any_flag0``, any day without the flag and with a valid discount."""
    state = np.asarray(state)
    if control == "regular":
        return state == REGULAR
    if control == "any_flag0":
        return (state == REGULAR) | (state == UNFLAGGED)
    raise ValueError(f"control desconocido: {control!r}; se esperaba uno de {', '.join(CONTROLS)}")


def _by_group(group: np.ndarray, weights: np.ndarray, n_groups: int) -> np.ndarray:
    """(groups, days): the sum of `weights` (series, days) of the series of each group."""
    out = np.empty((n_groups, weights.shape[1]))
    for day in range(weights.shape[1]):
        out[:, day] = np.bincount(group, weights=weights[:, day], minlength=n_groups)
    return out


def _day_sums(values: np.ndarray) -> np.ndarray:
    return values.sum(axis=2, dtype=np.float64)


def fit_ipf(values: CubeView, regular: np.ndarray, group: np.ndarray, iterations: int, *, n_groups: int, group_ids: np.ndarray, version: str = "") -> Counterfactual:
    """Fit ``a(s, h) * b(g, d)`` to the `regular` series-days (bool, series x days) of `values` by iterative proportional fitting from ``b = 1``, `iterations` times:
    ``a = sum of the control days / sum of b over them`` and then ``b = sum of the group's control days / sum of a over them``. `group` is the dense group position
    of each series. A series with no control day has ``a = NaN``; a group-day with no control keeps ``b = 1``."""
    v = values.values
    n_series, n_days, n_hours = v.shape
    control = np.asarray(regular, dtype=bool)
    on_control = control.astype(np.float64)
    control_sum = np.zeros((n_series, n_hours))
    for day in range(n_days):
        control_sum += v[:, day, :] * on_control[:, day, None]
    group_day = _by_group(group, _day_sums(v) * on_control, n_groups)
    b = np.ones((n_groups, n_days))
    a = np.full((n_series, n_hours), np.nan)
    for _ in range(iterations):
        denominator = (on_control * b[group]).sum(axis=1)
        has = denominator > 0
        a = np.where(has[:, None], control_sum / np.where(has, denominator, 1.0)[:, None], np.nan)
        level = np.nan_to_num(a).sum(axis=1)
        weights = _by_group(group, on_control * level[:, None], n_groups)
        b = np.where(weights > 0, group_day / np.where(weights > 0, weights, 1.0), 1.0)
    return Counterfactual(a, b, np.asarray(values.date_keys), version, np.asarray(group_ids))


def day_factor(values: CubeView, cf: Counterfactual, regular: np.ndarray, group: np.ndarray) -> np.ndarray:
    """``b`` (groups, days of `values`) of new days with ``cf.a`` held fixed: the group's control sale over what ``a`` says for the same series. Only series that
    have an ``a`` count, on both sides; a group with no control on a day has no factor (NaN)."""
    v = values.values
    fitted = np.isfinite(cf.a).all(axis=1)
    control = np.asarray(regular, dtype=bool) & fitted[:, None]
    on_control = control.astype(np.float64)
    level = np.nan_to_num(cf.a).sum(axis=1)
    n_groups = len(cf.group_ids)
    numerator = _by_group(group, _day_sums(v) * on_control, n_groups)
    denominator = _by_group(group, on_control * level[:, None], n_groups)
    return np.where(denominator > 0, numerator / np.where(denominator > 0, denominator, 1.0), np.nan)


def counterfactual(cf: Counterfactual, group: np.ndarray, series: np.ndarray, day: np.ndarray, hours: np.ndarray | None = None) -> np.ndarray:
    """What the model says for each series-day (`series` and `day` are positions): ``sum over the hours of a(s, h)`` times ``b(g(s), d)``. With `hours` (bool, one
    row per series-day), only those hours are summed. The one function every effect, forecast, variant and daily run gets the counterfactual from."""
    a = cf.a[series]
    a = np.nan_to_num(a) if hours is None else np.where(np.asarray(hours, dtype=bool), np.nan_to_num(a), 0.0)
    return a.sum(axis=1) * cf.b[group[series], day]


def records(values: CubeView, cf: Counterfactual, mask: np.ndarray, group: np.ndarray) -> Records:
    """The series-days of `mask` (bool, series x days) that have a counterfactual, with what they sold and what the model says; those that have none (a series
    with no control day, or a group-day with no factor) are counted in ``dropped`` and enter no effect."""
    mask = np.asarray(mask, dtype=bool)
    has_a = np.isfinite(cf.a).all(axis=1)
    series, day = np.nonzero(mask & has_a[:, None])
    model = counterfactual(cf, group, series, day)
    usable = np.isfinite(model)
    series, day, model = series[usable], day[usable], model[usable]
    observed = values.values[series, day, :].sum(axis=1, dtype=np.float64)
    return Records(series, day, observed, model, int(values.values.shape[0]), int(values.values.shape[1]), int(mask.sum()) - len(series))


def lifts(rec: Records, unit_of: np.ndarray, n_units: int) -> np.ndarray:
    """``sum(observed) / sum(counterfactual) - 1`` of each unit; `unit_of` gives the unit of each record (-1: none). A unit with no counterfactual mass is NaN."""
    unit_of = np.asarray(unit_of)
    keep = unit_of >= 0
    observed = np.bincount(unit_of[keep], weights=rec.observed[keep], minlength=n_units)
    expected = np.bincount(unit_of[keep], weights=rec.counterfactual[keep], minlength=n_units)
    return np.divide(observed, expected, out=np.full(n_units, np.nan), where=expected > 0) - 1.0


def cell_of(group: np.ndarray, band: np.ndarray, n_bands: int) -> np.ndarray:
    """The cell of each series-day: ``group position * n_bands + band``, ``-1`` where it has no band."""
    group, band = np.asarray(group), np.asarray(band)
    return np.where(band >= 0, group * n_bands + band, -1)


def cell_key(cell: int, group_ids: np.ndarray, n_bands: int) -> str:
    """``g<group id>-b<band>`` (requirements, section 7)."""
    group, band = divmod(int(cell), n_bands)
    return f"g{int(group_ids[group])}-b{band}"


def naive_pooled(values: CubeView, state: np.ndarray) -> float:
    """The account that goes wrong (D11): the mean daily sale of every promo series-day over the mean daily sale of every regular one, with no series and no day
    in it."""
    daily = _day_sums(values.values)
    state = np.asarray(state)
    return float(daily[state == PROMO].mean() / daily[state == REGULAR].mean() - 1.0)


__all__ = ["ANOMALOUS", "Counterfactual", "CubeView", "Lifts", "Records", "cell_key", "cell_of", "counterfactual", "day_factor", "fit_ipf", "lifts", "naive_pooled",
           "records", "regular_mask"]
