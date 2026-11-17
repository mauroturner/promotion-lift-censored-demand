"""The hand cases (U03): each answer written by hand in ``tests/fixtures/hand_cases.py`` is recomputed here with plain Python loops, so a
mistake in a hand-written number is found before the unit that trusts it."""

from __future__ import annotations

import pytest

import numpy as np

from tests.fixtures import hand_cases as hc


def classify(flag: int, discount: float) -> tuple[str, int, int | None]:
    """The rules of D04 and D13 written out in the plainest way."""
    if discount <= 0 or discount > 1:
        return "anomalous", -1, None
    edges = [0.5, 0.6, 0.7, 0.8, 0.9, 0.95]
    band = sum(1 for edge in edges if discount >= edge)
    state = "promo" if flag == 1 else ("regular" if discount >= 0.999 else "unflagged_cut")
    return state, band, band if state in ("promo", "unflagged_cut") else None


@pytest.mark.parametrize(("flag", "discount", "state", "band", "stored"), hc.STATE_EDGES)
def test_the_state_and_band_edges_are_what_the_rules_say(flag, discount, state, band, stored):
    assert classify(flag, discount) == (state, band, stored)


def test_the_state_edges_cover_every_edge_with_the_flag_on_and_off():
    discounts = sorted({row[1] for row in hc.STATE_EDGES})
    assert discounts == [0.0, 0.0001, 0.4999, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.998, 0.999, 1.0, 1.001, 1.088]
    assert all({(0, d), (1, d)} <= {(row[0], row[1]) for row in hc.STATE_EDGES} for d in discounts)


def test_r1_and_r2_by_hand_follow_their_definitions():
    sales, out, flag = hc.RECOVERY["sales"], hc.RECOVERY["out"], hc.RECOVERY["flag"]
    states = [[flag[s][d] for d in range(2)] for s in range(2)]

    def r1_base(s: int, d: int, h: int) -> float:
        """The mean of the hours with stock of series s at hour h, over the days of the state of day d; with none, over every day; with none, 0."""
        same = [sales[s][e][h] for e in range(2) if states[s][e] == states[s][d] and not out[s][e][h]]
        anyday = [sales[s][e][h] for e in range(2) if not out[s][e][h]]
        return sum(same) / len(same) if same else (sum(anyday) / len(anyday) if anyday else 0.0)

    assert (r1_base(0, 1, 14), r1_base(0, 1, 15)) == pytest.approx((0.5, 0.2))
    assert hc.RECOVERY["r1_base_series0"] == {14: pytest.approx(0.5), 15: pytest.approx(0.2)}
    assert r1_base(0, 1, 15) == pytest.approx(hc.RECOVERY["r1_recovered_s0_d1_h15"])
    assert {h: r1_base(1, 1, h) for h in (14, 15)} == hc.RECOVERY["r1_recovered_s1_d1"] and all(r1_base(1, 1, h) == 0 for h in range(14))
    # R2 of series 0 day 1
    observed = sum(sales[0][1][h] for h in range(16) if not out[0][1][h])
    expected = sum(r1_base(0, 1, h) for h in range(16) if not out[0][1][h])
    mass = sum(r1_base(0, 1, h) for h in range(16))
    assert (observed, expected, mass) == pytest.approx(hc.RECOVERY["r2_O_E_m"])
    for kappa, value in hc.RECOVERY["r2"].items():
        k = (observed + kappa * mass) / (expected + kappa * mass)
        assert r1_base(0, 1, 15) * k == pytest.approx(value, abs=1e-15), kappa
    # the day without stock at all: O = E = 0, so k = 1 and R2 is R1
    k = (0 + 1.0 * 2.0) / (0 + 1.0 * 2.0)
    assert k == 1 and {h: r1_base(1, 1, h) * k for h in (14, 15)} == hc.RECOVERY["r2_recovered_s1_d1"]
    assert all(out[1][1][h] for h in range(16)) and sum(out[0][1]) == 1 and sum(out[0][0]) == 0


def test_the_ipf_cases_by_hand():
    y, cf = hc.IPF_RANK1["y"], hc.IPF_RANK1["counterfactual"]
    assert (y == cf).all()
    # a rank-1 matrix is fitted exactly, whatever the number of iterations: a = row sums / column count, b = column sums / sum of a
    a = [sum(row) / 3 for row in y]
    b = [sum(y[s][d] for s in range(2)) / sum(a) for d in range(3)]
    np.testing.assert_allclose([[a[s] * b[d] for d in range(3)] for s in range(2)], cf, atol=1e-12)
    case = hc.IPF_ONE_ITERATION
    a = [sum(row) / 3 for row in case["y"]]
    b = [sum(case["y"][s][d] for s in range(2)) / sum(a) for d in range(3)]
    assert a == pytest.approx(case["a"].tolist()) and b == pytest.approx(case["b"].tolist())
    np.testing.assert_allclose([[a[s] * b[d] for d in range(3)] for s in range(2)], case["counterfactual"], atol=1e-12)
    assert abs(sum(case["counterfactual"].reshape(-1)) - sum(case["y"].reshape(-1))) < 1e-12, "the fit keeps the total"


def test_the_two_way_weights_by_hand():
    observed, counterfactual = hc.BOOTSTRAP["observed"], hc.BOOTSTRAP["counterfactual"]
    for series_weights, day_weights, obs_sum, cf_sum, lift in hc.BOOTSTRAP["draws"]:
        o = sum(series_weights[s] * day_weights[d] * observed[s][d] for s in range(3) for d in range(2))
        c = sum(series_weights[s] * day_weights[d] * counterfactual[s][d] for s in range(3) for d in range(2))
        assert (o, c) == (obs_sum, cf_sum) and o / c - 1 == pytest.approx(lift)
        assert sum(series_weights) == 3 and sum(day_weights) == 2, "a draw takes as many series and days as there are, with repetition"


def test_the_indistinguishable_groups_by_hand():
    cells = sorted(hc.TIERS_CELLS, key=lambda cell: -cell[1])

    def overlap(one, other) -> bool:
        return max(one[2], other[2]) <= min(one[3], other[3])

    groups: list[list] = []
    for cell in cells:
        if groups and any(overlap(cell, member) for member in groups[-1]):
            groups[-1].append(cell)
        else:
            groups.append([cell])
    tiers = {cell[0]: number + 1 for number, group in enumerate(groups) for cell in group}
    assert tiers == hc.TIERS_EXPECTED["tier"]
    pairs = {(one[0], other[0]) for i, one in enumerate(hc.TIERS_CELLS) for other in hc.TIERS_CELLS[i + 1:] if overlap(one, other)}
    assert pairs == hc.TIERS_EXPECTED["overlapping_pairs"] and len(hc.TIERS_CELLS) * (len(hc.TIERS_CELLS) - 1) // 2 == hc.TIERS_EXPECTED["pairs"]
    # a and c do not overlap but share a group through b: a group is a chain, and the case says so
    assert not overlap(hc.TIERS_CELLS[0], hc.TIERS_CELLS[2]) and tiers["a"] == tiers["c"]


def test_the_metrics_by_hand():
    m = hc.METRICS
    for name in ("a", "b"):
        truth, estimate = m["truth"], m[f"estimate_{name}"]
        wape = sum(abs(e - t) for e, t in zip(estimate, truth)) / sum(truth)
        bias = sum(estimate) / sum(truth) - 1
        assert wape == pytest.approx(m[f"wape_{name}"]) and bias == pytest.approx(m[f"bias_{name}"], abs=1e-12)
    wape = sum(abs(f - o) for f, o in zip(m["forecast"], m["observed"])) / sum(m["observed"])
    assert wape == pytest.approx(m["forecast_wape"])
