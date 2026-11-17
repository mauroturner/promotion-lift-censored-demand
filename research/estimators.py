"""Estimators shared by the promotion scripts (s08, s09). Arrays are dense tensors [series, day(, hour)].

No file reading here: callers pass the tensors from common.train_only().
"""
import numpy as np


def bootstrap_weights(n_series, B=500, seed=0):
    """B bootstrap draws over series, as count weights (B, n_series)."""
    rng = np.random.default_rng(seed)
    return np.stack([np.bincount(rng.integers(0, n_series, n_series), minlength=n_series) for _ in range(B)]).astype(float)


def weighted_ratio(A, Bv, w):
    """Sales-weighted ratio minus one, for each bootstrap weight row in w (B, n_series)."""
    return (w @ A) / (w @ Bv) - 1


def recover(TS, TST, x, use):
    """Recovered demand. Stockout hours on the days in `use` take the mean in-stock sales of the same series,
    hour and promo state x (1/0); fallback: the same series and hour in the other state. Returns
    (R, fallback_cells, unrecoverable_values); R keeps NaN where no in-stock value exists at all."""
    x3 = x.astype(bool)[:, :, None]
    u3 = use[:, :, None]
    inst = (TST == 0) & u3
    stats = {}
    for p in (True, False):
        sel = inst & (x3 == p)
        stats[p] = ((TS * sel).sum(axis=1), sel.sum(axis=1))
    s_all = stats[True][0] + stats[False][0]
    c_all = stats[True][1] + stats[False][1]
    mean_all = np.where(c_all > 0, s_all / np.maximum(c_all, 1), np.nan)
    imp = {}
    fallback = 0
    for p in (True, False):
        s_, c_ = stats[p]
        fallback += int(((c_ == 0) & (c_all > 0)).sum())
        imp[p] = np.where(c_ > 0, s_ / np.maximum(c_, 1), mean_all)
    stock_hours = (TST == 1) & u3
    imputed = np.where(x3, imp[True][:, None, :], imp[False][:, None, :])
    R = np.where(stock_hours, imputed, TS)
    missing = int(np.isnan(R[stock_hours]).sum())
    return R, fallback, missing


def v_matched(values, pm, nm, instock=None, hour_ok=None):
    """Within-series, hour-matched numerator A and denominator B per series.

    For each series and hour: mean of values on promo days (pm) over mean on non-promo days (nm); with
    instock (S, D, 24) bool, only in-stock hours count. A series-hour contributes only if both groups have
    values and hour_ok is True. np.where masks keep NaN on unselected days out of the sums."""
    if hour_ok is None:
        hour_ok = np.ones((values.shape[0], values.shape[2]), dtype=bool)
    pm3 = pm[:, :, None]
    nm3 = nm[:, :, None]
    sel_p = pm3 if instock is None else (pm3 & instock)
    sel_n = nm3 if instock is None else (nm3 & instock)
    pc = sel_p.sum(axis=1)
    nc = sel_n.sum(axis=1)
    Mh = np.where(sel_p, values, 0.0).sum(axis=1) / np.maximum(pc, 1)
    Nh = np.where(sel_n, values, 0.0).sum(axis=1) / np.maximum(nc, 1)
    good = hour_ok & (pc > 0) & (nc > 0)
    A = np.where(good, Mh, 0.0).sum(axis=1)
    Bv = np.where(good, Nh, 0.0).sum(axis=1)
    return A, Bv, good.any(axis=1)
