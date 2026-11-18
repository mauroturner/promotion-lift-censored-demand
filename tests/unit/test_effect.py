"""The counterfactual and the effects (U08; RF12, RF13, D09-D11; AC15): the iterative proportional fit exact in a hand case, a control made only of regular days,
a series without a regular day, the lift of a unit and its cell."""

from __future__ import annotations

import numpy as np
import pytest

from promolift.days import ANOMALOUS, PROMO, REGULAR, UNFLAGGED
from promolift.effect import (
    CubeView,
    Records,
    cell_key,
    cell_of,
    counterfactual,
    day_factor,
    fit_ipf,
    lifts,
    naive_pooled,
    records,
    regular_mask,
)
from tests.fixtures import hand_cases as hc

KEYS = np.array([20240601, 20240602, 20240603], dtype=np.int32)


def view_of(y: np.ndarray, keys: np.ndarray = KEYS) -> CubeView:
    """The hand values y[series, day] as a cube of one hour."""
    return CubeView(np.asarray(y, dtype=np.float64)[:, :, None], keys)


def fit(y, regular=None, iterations=1):
    y = np.asarray(y, dtype=np.float64)
    regular = np.ones(y.shape, dtype=bool) if regular is None else regular
    return fit_ipf(view_of(y, KEYS[: y.shape[1]]), regular, np.zeros(len(y), dtype=np.int64), iterations, n_groups=1, group_ids=np.array([7]), version="raw")


def test_ipf_by_hand_on_two_series_and_three_days():
    case = hc.IPF_ONE_ITERATION
    cf = fit(case["y"], iterations=1)
    assert cf.a.shape == (2, 1) and cf.b.shape == (1, 3) and cf.version == "raw" and cf.days.tolist() == KEYS.tolist() and cf.group_ids.tolist() == [7]
    assert cf.a[:, 0].tolist() == pytest.approx(case["a"].tolist()) and cf.b[0].tolist() == pytest.approx(case["b"].tolist())
    series, day = np.nonzero(np.ones((2, 3), dtype=bool))
    got = counterfactual(cf, np.zeros(2, dtype=np.int64), series, day)
    assert got.reshape(2, 3) == pytest.approx(case["counterfactual"])


def test_a_rank_one_table_is_reproduced_by_the_fit_and_more_iterations_change_nothing():
    case = hc.IPF_RANK1
    for iterations in (1, 2, 30):
        cf = fit(case["y"], iterations=iterations)
        series, day = np.nonzero(np.ones((2, 3), dtype=bool))
        assert counterfactual(cf, np.zeros(2, dtype=np.int64), series, day).reshape(2, 3) == pytest.approx(case["y"])


def test_the_control_is_only_regular_days():
    state = np.array([[REGULAR, UNFLAGGED, PROMO, ANOMALOUS], [REGULAR, REGULAR, UNFLAGGED, PROMO]], dtype=np.int8)
    assert regular_mask(state).tolist() == [[True, False, False, False], [True, True, False, False]]
    assert regular_mask(state, "any_flag0").tolist() == [[True, True, False, False], [True, True, True, False]]
    with pytest.raises(ValueError, match="control"):
        regular_mask(state, "everything")
    keys = np.array([1, 2, 3, 4], dtype=np.int32)
    y = np.array([[2.0, 40.0, 90.0, 7.0], [4.0, 6.0, 33.0, 80.0]])
    regular = regular_mask(state)

    def run(values):
        return fit_ipf(CubeView(values[:, :, None], keys), regular, np.zeros(2, dtype=np.int64), 5, n_groups=1, group_ids=np.array([0]))

    base = run(y)
    moved = y.copy()
    moved[~regular] *= 11.0                                     # whatever the other days sold, the fit does not see it
    other = run(moved)
    assert np.array_equal(base.a, other.a, equal_nan=True) and np.array_equal(base.b[:, regular.any(axis=0)], other.b[:, regular.any(axis=0)])
    changed = y.copy()
    changed[0, 0] += 5.0                                        # but a regular day does move it
    assert not np.array_equal(base.a, run(changed).a)


def test_a_series_without_a_regular_day_has_no_counterfactual_and_enters_no_effect():
    y = np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0], [7.0, 8.0, 9.0]])
    regular = np.array([[True, True, True], [True, True, False], [False, False, False]])
    cf = fit(y, regular, iterations=3)
    assert np.isnan(cf.a[2]).all() and np.isfinite(cf.a[:2]).all()
    group = np.zeros(3, dtype=np.int64)
    everything = np.ones((3, 3), dtype=bool)
    rec = records(view_of(y), cf, everything, group)
    assert sorted(set(rec.series.tolist())) == [0, 1] and len(rec.series) == 6 and rec.dropped == 3 and (rec.n_series, rec.n_days) == (3, 3)
    assert rec.observed.tolist() == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    # the lift of a unit counts the series that have a counterfactual only
    assert lifts(rec, np.zeros(len(rec.series), dtype=np.int64), 1)[0] == pytest.approx(rec.observed.sum() / rec.counterfactual.sum() - 1)


def test_the_day_factor_of_new_days_holds_a_fixed_and_leaves_out_series_that_have_none():
    y = hc.IPF_ONE_ITERATION["y"]
    cf = fit(y, iterations=1)                                   # a = [4, 6]
    new = np.array([[5.0, 20.0], [7.0, 4.0], [100.0, 100.0]])   # series 2 has no a: its sale must not inflate the group's factor
    a = np.vstack([cf.a, [[np.nan]]])
    cf3 = type(cf)(a, cf.b, cf.days, cf.version, cf.group_ids)
    b = day_factor(CubeView(new[:, :, None], np.array([20240610, 20240611], dtype=np.int32)), cf3, np.ones((3, 2), dtype=bool), np.zeros(3, dtype=np.int64))
    assert b.shape == (1, 2) and b[0].tolist() == pytest.approx([(5 + 7) / 10, (20 + 4) / 10])
    none = day_factor(CubeView(new[:, :, None], np.array([20240610, 20240611], dtype=np.int32)), cf3, np.zeros((3, 2), dtype=bool), np.zeros(3, dtype=np.int64))
    assert np.isnan(none).all()                                 # a group without a control that day has no factor


def test_the_lift_of_a_unit_is_the_observed_over_the_counterfactual_minus_one_and_a_unit_without_records_has_none():
    observed, counter = hc.BOOTSTRAP["observed"], hc.BOOTSTRAP["counterfactual"]
    series, day = np.nonzero(np.ones(observed.shape, dtype=bool))
    rec = Records(series, day, observed[series, day], counter[series, day], 3, 2, 0)
    assert lifts(rec, np.zeros(6, dtype=np.int64), 1)[0] == pytest.approx(16 / 15 - 1)
    unit = np.array([0, 0, 1, 1, 1, 1])
    assert lifts(rec, unit, 3).tolist()[:2] == pytest.approx([(2 + 3) / (2 + 2) - 1, (1 + 1 + 4 + 5) / (1 + 2 + 4 + 4) - 1]) and np.isnan(lifts(rec, unit, 3)[2])
    assert lifts(rec, np.array([0, -1, -1, -1, -1, 0]), 1)[0] == pytest.approx((2 + 5) / (2 + 4) - 1)      # a record with unit -1 is in no unit


def test_a_cell_is_a_group_and_a_band_and_its_key_names_the_group_id():
    assert cell_of(np.array([0, 2, 1]), np.array([3, 0, -1]), 7).tolist() == [3, 14, -1]
    assert cell_key(2 * 7 + 3, np.array([10, 20, 30]), 7) == "g30-b3" and cell_key(0, np.array([10, 20, 30]), 7) == "g10-b0"


def test_the_naive_pooled_lift_compares_the_mean_of_the_promo_days_with_the_mean_of_the_regular_days():
    state = np.array([[PROMO, REGULAR, REGULAR], [PROMO, PROMO, ANOMALOUS]], dtype=np.int8)
    y = np.array([[10.0, 4.0, 2.0], [20.0, 30.0, 1000.0]])
    assert naive_pooled(view_of(y), state) == pytest.approx(((10 + 20 + 30) / 3) / ((4 + 2) / 2) - 1)


def test_the_counterfactual_of_a_series_day_sums_only_the_hours_asked_for():
    a = np.array([[1.0, 2.0, 3.0]])
    cf = type(fit(hc.IPF_RANK1["y"]))(a, np.array([[2.0, 4.0]]), KEYS[:2], "raw", np.array([7]))
    full = counterfactual(cf, np.zeros(1, dtype=np.int64), np.array([0, 0]), np.array([0, 1]))
    some = counterfactual(cf, np.zeros(1, dtype=np.int64), np.array([0, 0]), np.array([0, 1]), np.array([[True, False, True], [False, False, True]]))
    assert full.tolist() == [12.0, 24.0] and some.tolist() == [8.0, 12.0]


def test_a_series_day_of_a_group_day_without_a_factor_has_no_counterfactual_and_is_counted_as_dropped():
    cf = fit(hc.IPF_ONE_ITERATION["y"], iterations=1)
    with_hole = type(cf)(cf.a, np.array([[0.6, np.nan, 1.6]]), cf.days, cf.version, cf.group_ids)
    rec = records(view_of(hc.IPF_ONE_ITERATION["y"]), with_hole, np.ones((2, 3), dtype=bool), np.zeros(2, dtype=np.int64))
    assert rec.day.tolist() == [0, 2, 0, 2] and rec.dropped == 2 and np.isfinite(rec.counterfactual).all()
