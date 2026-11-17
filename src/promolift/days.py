"""The state of a day and its band (RF04; D03, D04, D13; plan, section 8).

A series-day is ``anomalous`` when its discount is not a number, is at or below ``anomalous_max_discount`` (0: no interpretable cut) or is above
``anomalous_min_discount`` (1: more than the price); otherwise ``promo`` when ``activity_flag`` is 1, ``regular`` when the flag is 0 and the
discount is at least ``regular_min_discount`` (a day with no cut: 1.0, or the 0.999 of 3,376 real rows) and ``unflagged_cut`` for the rest: a cut
with no flag, which has its own effect and is never a control.

The bands are those of ``[days] bands`` over the discount: with the default edges, band 0 is ``(0, 0.5)``, band 1 ``[0.5, 0.6)``, ... band 5
``[0.9, 0.95)`` and band 6 ``[0.95, 1]``; a flag with discount 1.0 falls in the last one. Only a ``promo`` or ``unflagged_cut`` day stores its band.
Both functions take the sealed view or the configuration (anything with ``.days``) and work on whole columns.

**The discount of the real file carries float32 noise** (found reading ``train.parquet`` in U04, decision D13's note of 2026-11-17): the same
"clean" discount is stored both as the double it was meant to be and as its float32 neighbour, so 3,338 of the 4.5 million rows hold
``0.8999999761581421`` where 15,234 others hold ``0.9`` (and ``0.699999988...`` for 0.7, ``0.949999988...`` for 0.95, ``0.7999993...`` for 0.8). A
comparison with an edge must not send the same discount to two bands, so a value within ``EDGE_TOLERANCE`` below an edge counts as the edge. The
tolerance is far under the 0.001 step of the discounts that are meant (and under the noise of float32 at these values, 6e-8 to 6e-7).
"""

from __future__ import annotations

from typing import Any

import numpy as np

PROMO, REGULAR, UNFLAGGED, ANOMALOUS = 0, 1, 2, 3
STATE_NAMES = ("promo", "regular", "unflagged_cut", "anomalous")
EDGE_TOLERANCE = 1e-6


def day_state(flag: np.ndarray, discount: np.ndarray, view: Any) -> np.ndarray:
    """int8 array of the shape of `flag`: ``PROMO``, ``REGULAR``, ``UNFLAGGED`` or ``ANOMALOUS`` of each series-day."""
    d = view.days
    flag = np.asarray(flag)
    discount = np.asarray(discount, dtype=np.float64)
    with np.errstate(invalid="ignore"):
        anomalous = ~np.isfinite(discount) | (discount <= d.anomalous_max_discount) | (discount > d.anomalous_min_discount)
        regular = discount + EDGE_TOLERANCE >= d.regular_min_discount
    state = np.where(flag == 1, PROMO, np.where(regular, REGULAR, UNFLAGGED))
    return np.where(anomalous, ANOMALOUS, state).astype(np.int8)


def band_of(discount: np.ndarray, view: Any) -> np.ndarray:
    """int8 array: the band of each discount in ``(0, 1]``, ``-1`` for a discount that is not a number, is 0 or is above 1."""
    edges = np.asarray(view.days.bands, dtype=np.float64)
    discount = np.asarray(discount, dtype=np.float64)
    with np.errstate(invalid="ignore"):
        valid = np.isfinite(discount) & (discount > edges[0]) & (discount <= edges[-1])
        band = np.searchsorted(edges[1:-1], np.where(valid, discount + EDGE_TOLERANCE, 0.5 * (edges[0] + edges[-1])), side="right")
    return np.where(valid, band, -1).astype(np.int8)


def day_band(state: np.ndarray, discount: np.ndarray, view: Any) -> np.ndarray:
    """int8 array: the stored band of a series-day: that of its discount when it is ``promo`` or ``unflagged_cut``, ``-1`` otherwise."""
    state = np.asarray(state)
    return np.where((state == PROMO) | (state == UNFLAGGED), band_of(discount, view), -1).astype(np.int8)
