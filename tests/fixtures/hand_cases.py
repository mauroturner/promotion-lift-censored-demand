"""Small cases with the answer written by hand (plan, section 24): the code of the units that come later must give exactly these numbers.

Every case is built so that its answer can be found with pencil and paper; ``tests/unit/test_hand_cases.py`` recomputes each one with plain
Python loops (no NumPy reductions, no project code), so a mistake in a hand-written number is found here and not in the unit that trusts it.
Layouts follow the plan: arrays are ``[series, day, hour]`` over the 16 analysis hours (06 to 21), ``out`` is 1 where the hour had no stock.
"""

from __future__ import annotations

import numpy as np

# --- the state of a day and its band (plan, section 8; AC04) ------------------------------------------------------------------
# (activity_flag, discount, state, band_of(discount), stored band): the band of a discount in (0, 1] is the one of D13, the stored one only
# exists for a promo or an unflagged_cut day (None elsewhere); every edge of the rules is a row, with the flag on and off.
STATE_EDGES: list[tuple[int, float, str, int, int | None]] = [
    (0, 0.0, "anomalous", -1, None), (1, 0.0, "anomalous", -1, None),
    (0, 0.0001, "unflagged_cut", 0, 0), (1, 0.0001, "promo", 0, 0),
    (0, 0.4999, "unflagged_cut", 0, 0), (1, 0.4999, "promo", 0, 0),
    (0, 0.5, "unflagged_cut", 1, 1), (1, 0.5, "promo", 1, 1),
    (0, 0.6, "unflagged_cut", 2, 2), (1, 0.6, "promo", 2, 2),
    (0, 0.7, "unflagged_cut", 3, 3), (1, 0.7, "promo", 3, 3),
    (0, 0.8, "unflagged_cut", 4, 4), (1, 0.8, "promo", 4, 4),
    (0, 0.9, "unflagged_cut", 5, 5), (1, 0.9, "promo", 5, 5),
    (0, 0.95, "unflagged_cut", 6, 6), (1, 0.95, "promo", 6, 6),
    (0, 0.998, "unflagged_cut", 6, 6), (1, 0.998, "promo", 6, 6),
    (0, 0.999, "regular", 6, None), (1, 0.999, "promo", 6, 6),
    (0, 1.0, "regular", 6, None), (1, 1.0, "promo", 6, 6),
    (0, 1.001, "anomalous", -1, None), (1, 1.001, "anomalous", -1, None),
    (0, 1.088, "anomalous", -1, None), (1, 1.088, "anomalous", -1, None),
]

# --- R1 and R2 (plan, section 11; AC14): 2 series x 2 days, one hour without stock and one day without stock at all -----------------------
H = 16
_sales = np.zeros((2, 2, H))
_out = np.zeros((2, 2, H), dtype=np.int8)
_sales[0, 0, 14], _sales[0, 0, 15] = 0.4, 0.2           # series 0, day 0: regular, stock all day
_sales[0, 1, 14] = 0.6                                  # series 0, day 1: regular, hour 15 without stock (sells nothing)
_out[0, 1, 15] = 1
_sales[1, 0, 14], _sales[1, 0, 15] = 1.0, 1.0           # series 1, day 0: promo, stock all day
_out[1, 1, :] = 1                                       # series 1, day 1: regular, no stock from 06 to 21 (a fully_out day)
RECOVERY = {
    "sales": _sales,
    "out": _out,
    "flag": np.array([[0, 0], [1, 0]]),                 # activity_flag; the state is promo where it is 1 and regular where it is 0
    # R1: the series' mean of the hours with stock, by hour and by promo or not; series 0 hour 15 has stock only on day 0 (0.2); series 1's day
    # 1 has no stock-free value in its own state, so it takes the mean of its other day (1.0 at hours 14 and 15)
    "r1_base_series0": {14: 0.5, 15: 0.2},
    "r1_recovered_s0_d1_h15": 0.2,
    "r1_recovered_s1_d1": {14: 1.0, 15: 1.0},
    # R2 for series 0 day 1: O = 0.6 (what its hours with stock sold), E = 0.5 (what R1 gives for those hours), m = 0.7 (R1 over the 16 hours)
    "r2": {1.0: 0.2 * 13 / 12, 0.25: 0.2 * 31 / 27},
    "r2_O_E_m": (0.6, 0.5, 0.7),
    # the fully_out day: O = E = 0, so k = 1 and R2 gives R1
    "r2_recovered_s1_d1": {14: 1.0, 15: 1.0},
}

# --- IPF (plan, section 12; AC15): 2 series x 3 days, one group, one hour ------------------------------------------------------------
IPF_RANK1 = {"y": np.array([[1.0, 3.0, 2.0], [2.0, 6.0, 4.0]]), "counterfactual": np.array([[1.0, 3.0, 2.0], [2.0, 6.0, 4.0]])}
# one iteration from b = 1: a = row means, b = column sums over the sum of a
IPF_ONE_ITERATION = {
    "y": np.array([[2.0, 4.0, 6.0], [4.0, 4.0, 10.0]]),
    "a": np.array([4.0, 6.0]),
    "b": np.array([0.6, 0.8, 1.6]),
    "counterfactual": np.array([[2.4, 3.2, 6.4], [3.6, 4.8, 9.6]]),
}

# --- the two-way weights (plan, section 13; AC16): 3 series x 2 days ---------------------------------------------------------------------
BOOTSTRAP = {
    "observed": np.array([[2.0, 3.0], [1.0, 1.0], [4.0, 5.0]]),
    "counterfactual": np.array([[2.0, 2.0], [1.0, 2.0], [4.0, 4.0]]),
    # (series weights, day weights) -> (weighted observed, weighted counterfactual, lift)
    "draws": [
        ((2, 0, 1), (1, 1), 19.0, 16.0, 19 / 16 - 1),
        ((1, 1, 1), (2, 0), 14.0, 14.0, 0.0),
        ((0, 3, 0), (1, 1), 6.0, 9.0, 6 / 9 - 1),
    ],
}

# --- indistinguishable groups (plan, section 13; AC17): five cells, intervals that touch count as overlapping -------------------------------
# (id, lift, low, high)
TIERS_CELLS = [("a", 0.9, 0.7, 1.1), ("b", 0.8, 0.6, 1.0), ("c", 0.5, 0.4, 0.6), ("d", 0.3, 0.2, 0.35), ("e", 0.1, -0.1, 0.25)]
TIERS_EXPECTED = {"tier": {"a": 1, "b": 1, "c": 1, "d": 2, "e": 2}, "overlapping_pairs": {("a", "b"), ("b", "c"), ("d", "e")}, "pairs": 10}

# --- the metrics (requirements, section 8.1): the WAPE of the mass per series, the bias and the forecast WAPE ---------------------------------
METRICS = {
    "truth": [10.0, 20.0, 30.0],
    "estimate_a": [12.0, 18.0, 30.0],       # WAPE 4 / 60, bias 0
    "estimate_b": [9.0, 18.0, 36.0],        # WAPE 9 / 60, bias 0.05
    "wape_a": 4 / 60, "bias_a": 0.0, "wape_b": 9 / 60, "bias_b": 0.05,
    "observed": [10.0, 10.0, 10.0], "forecast": [8.0, 12.0, 10.0], "forecast_wape": 4 / 30,
}
