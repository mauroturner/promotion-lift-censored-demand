"""The intervals (RF14, D12; plan, section 13).

**Two ways** (D12): each resample gives every series a whole number of copies (the draws of ``integers(0, S, S)`` counted) and every day another, and a series-day
weighs the product of the two; the counterfactual stays fixed. A series is resampled whole because its hours and its days are not independent; a day is resampled
whole because the series of one day share its shocks. Resampling only series (``days=False``) is the variant that ignores the second (it gives intervals 1.8 times
narrower on the real data, ``research/plan/p04``). Weights come from a generator seeded with the configuration's seed, so a repeated run draws the same ones; and two
sets of records with the same shape and the same seed draw the same weights, so their difference is paired.
"""

from __future__ import annotations

import warnings

import numpy as np

from promolift.effect import Records

LOW, HIGH = 2.5, 97.5


def weighted_sums(rec: Records, unit_of: np.ndarray, n_units: int, series_weights: np.ndarray, day_weights: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """``(observed, counterfactual)`` of each unit with every record weighted by its series' weight times its day's weight."""
    unit_of = np.asarray(unit_of)
    keep = unit_of >= 0
    weight = (np.asarray(series_weights, dtype=np.float64)[rec.series] * np.asarray(day_weights, dtype=np.float64)[rec.day])[keep]
    numerator = np.bincount(unit_of[keep], weights=weight * rec.observed[keep], minlength=n_units)
    denominator = np.bincount(unit_of[keep], weights=weight * rec.counterfactual[keep], minlength=n_units)
    return numerator, denominator


def two_way_draws_many(rec: Records, units: list[tuple[np.ndarray, int]], resamples: int, seed: int, *, days: bool = True) -> list[np.ndarray]:
    """``two_way_draws`` for several families of units at once (each ``(unit_of, n_units)``) over the same weights: the draws of every family are the ones a
    separate call with the same seed gives, for the price of computing the weights of the records once."""
    rng = np.random.default_rng(seed)
    out = [np.full((resamples, n_units), np.nan) for _unit_of, n_units in units]
    ones = np.ones(rec.n_days)
    keep = [np.asarray(unit_of) >= 0 for unit_of, _n in units]
    for draw in range(resamples):
        series_weights = np.bincount(rng.integers(0, rec.n_series, rec.n_series), minlength=rec.n_series)
        day_weights = np.bincount(rng.integers(0, rec.n_days, rec.n_days), minlength=rec.n_days) if days else ones
        weight = series_weights[rec.series] * day_weights[rec.day].astype(np.float64)
        for family, (unit_of, n_units) in enumerate(units):
            mask, unit = keep[family], np.asarray(unit_of)
            numerator = np.bincount(unit[mask], weights=(weight * rec.observed)[mask], minlength=n_units)
            denominator = np.bincount(unit[mask], weights=(weight * rec.counterfactual)[mask], minlength=n_units)
            out[family][draw] = np.divide(numerator, denominator, out=np.full(n_units, np.nan), where=denominator > 0) - 1.0
    return out


def two_way_draws(rec: Records, unit_of: np.ndarray, n_units: int, resamples: int, seed: int, *, days: bool = True) -> np.ndarray:
    """``(resamples, n_units)`` lifts of the weighted records, resampling the series of the view and, unless `days` is false, its days too. A unit whose
    weighted counterfactual is 0 gives NaN."""
    return two_way_draws_many(rec, [(unit_of, n_units)], resamples, seed, days=days)[0]


def interval(draws: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """The 2.5 and 97.5 percentiles of each column of `draws`, ignoring NaN (a column of NaN gives NaN)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        low, high = np.nanpercentile(draws, [LOW, HIGH], axis=0)
    return low, high


def series_draws(numerators: np.ndarray, denominator: np.ndarray, resamples: int, seed: int) -> np.ndarray:
    """``(resamples, columns)``: ``sum(w * numerator) / sum(w * denominator)`` for each column of `numerators` (series, columns), with the weights `w` of a
    series bootstrap shared by all the columns: the difference of two columns is paired (the criteria C01 to C03 compare methods on the same resamples)."""
    numerators = np.asarray(numerators, dtype=np.float64).reshape(len(denominator), -1)
    denominator = np.asarray(denominator, dtype=np.float64)
    n = len(denominator)
    rng = np.random.default_rng(seed)
    out = np.empty((resamples, numerators.shape[1]))
    for draw in range(resamples):
        weights = np.bincount(rng.integers(0, n, n), minlength=n).astype(np.float64)
        out[draw] = (weights @ numerators) / (weights @ denominator)
    return out
