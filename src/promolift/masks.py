"""The synthetic censoring of in-stock hours (RF10, D07; plan, section 11): the truth of a recovery is known only where hours that had stock are hidden on
purpose, so every method is judged on hours it is not allowed to see (AC11).

A tail mask imitates what a stock-out is: the 86 % of real stock-outs that last until the end of the day (research.md). It takes the series-days that had stock
from the first to the last analysis hour and whose state is ``promo`` or ``regular``, draws for each a cut hour from the distribution of the first stock-out hour of
the training block (``first_stockout_pmf``, which is sealed) and hides every hour from the cut. A mask at random hides ``hours`` hours chosen at random instead,
for the contrast of C10. Applying a mask marks the hidden hours as out of stock and removes their sale (``NaN``): the method sees what a real stock-out would
leave it. What it does not reproduce is that real stock-outs come on the days of more demand (D07); the synthetic fixture plants that.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

from promolift.cube import DayInputs
from promolift.days import PROMO, REGULAR


@dataclass(frozen=True)
class Mask:
    """The series-days of a day that a mask hides hours of: ``rows`` index the series of the day's inputs, ``hidden`` (rows, hours) says which hours,
    ``cut`` is the clock hour a tail mask starts at (-1 for a mask at random)."""

    rows: np.ndarray
    hidden: np.ndarray
    cut: np.ndarray


def first_stockout_pmf(stock: np.ndarray, days_mask: np.ndarray) -> np.ndarray:
    """The distribution of the first hour without stock (one probability per analysis hour) over the series-days that had a stock-out, on the days of
    `days_mask` (bool, one per day) of `stock` (series, days, hours; 1 = no stock). ``ValueError`` if no series-day had one."""
    chosen = np.asarray(stock)[:, np.asarray(days_mask, dtype=bool), :] == 1
    any_out = chosen.any(axis=2)
    if not any_out.any():
        raise ValueError("los días elegidos no tienen ninguna serie-día sin stock: no hay distribución de la primera hora sin stock")
    first = chosen.argmax(axis=2)[any_out]
    counts = np.bincount(first, minlength=chosen.shape[2]).astype(np.float64)
    return counts / counts.sum()


def _eligible(inputs: DayInputs) -> np.ndarray:
    """The rows that a mask may take: in stock from the first to the last hour of the analysis and a promo or regular day."""
    return np.flatnonzero((inputs.stock == 0).all(axis=1) & ((inputs.state == PROMO) | (inputs.state == REGULAR)))


def mask_tail(inputs: DayInputs, pmf: np.ndarray, rng: np.random.Generator) -> Mask:
    """The tail mask of a day: each eligible series-day hides every hour from a cut drawn from `pmf` (one draw per series-day, in the order of the series)."""
    rows = _eligible(inputs)
    n_hours = inputs.sales.shape[1]
    cut = rng.choice(n_hours, size=len(rows), p=pmf)
    return Mask(rows, np.arange(n_hours)[None, :] >= cut[:, None], inputs.hours[cut])


def mask_random(inputs: DayInputs, hours: int, rng: np.random.Generator) -> Mask:
    """The mask at random of a day: each eligible series-day hides `hours` hours chosen at random."""
    rows = _eligible(inputs)
    n_hours = inputs.sales.shape[1]
    chosen = np.argsort(rng.random((len(rows), n_hours)), axis=1)[:, :hours]
    hidden = np.zeros((len(rows), n_hours), dtype=bool)
    np.put_along_axis(hidden, chosen, True, axis=1)
    return Mask(rows, hidden, np.full(len(rows), -1, dtype=np.int64))


def apply(inputs: DayInputs, mask: Mask) -> DayInputs:
    """The inputs as a method would get them if the hidden hours had been a stock-out: those hours marked out of stock and their sale ``NaN``. A new
    object; `inputs` is not changed."""
    sales, stock = inputs.sales.copy(), inputs.stock.copy()
    rows, columns = np.nonzero(mask.hidden)
    sales[mask.rows[rows], columns] = np.nan
    stock[mask.rows[rows], columns] = 1
    return replace(inputs, sales=sales, stock=stock)


def truth(inputs: DayInputs, mask: Mask) -> np.ndarray:
    """The sale of the hidden hours (rows of the mask, hours), zero where the mask hides nothing: what a method is judged against."""
    return np.where(mask.hidden, inputs.sales[mask.rows], 0.0)


__all__ = ["Mask", "apply", "first_stockout_pmf", "mask_random", "mask_tail", "truth"]
