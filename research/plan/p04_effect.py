"""Planner check 4: the promotion-effect estimator, its intervals, and a replication from train to validation.

Counterfactual: a multiplicative model m(s, h, d) = a(s, h) * b(g, d) (series-hour level times a day factor of the
management group), fitted by iterative proportional fitting (the Poisson maximum-likelihood fit of that model) on
regular days only (activity_flag 0 and discount >= 0.999). The lift of a cell (management group x depth band of the
flag days) is sum(observed) / sum(counterfactual) - 1 over its promo series-days, hours 06-21. Raw sales and
recovered demand (R2 of p02-p03, kappa 1.0, stock-out hours replaced) give the two versions.
Intervals: bootstrap over series only, and two-way (series and days, product weights), B = 500, seed 0,
with the fitted a and b held fixed. Train block 2024-03-28..05-31 for the fit; validation 06-08..06-25 to replicate.
Reads only data/raw/train.parquet; the eval split (sealed test week) is never opened.
"""
import sys
import time
import warnings
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import train_only, SPLIT_DATES  # noqa: E402

warnings.filterwarnings("ignore", category=RuntimeWarning)  # cells with no promo series-day give 0/0 = nan, kept out of every count

t0 = time.time()
meta, S, ST, T = train_only()
NS, ND = T["n_series"], T["n_days"]
Y = T["sales"][:, :, 6:22].copy(); OUT = T["stock"][:, :, 6:22] == 1
TP, TD = T["promo"], T["discount"]
del S, ST
origin = pd.Timestamp(SPLIT_DATES["train"][0])
idx = lambda s: (pd.Timestamp(s) - origin).days  # noqa: E731
TR = np.arange(idx("2024-03-28"), idx("2024-05-31") + 1)
VA = np.arange(idx("2024-06-08"), idx("2024-06-25") + 1)
valid = (TD > 0) & (TD <= 1)
promo = (TP == 1) & valid
regular = (TP == 0) & valid & (TD >= 0.999)
cutday = (TP == 0) & valid & (TD < 0.999)
group = meta.groupby("series").management_group_id.first().reindex(range(NS)).to_numpy().astype(int)
G = group.max() + 1
BANDS = [(0.0, 0.5), (0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 0.95), (0.95, 1.0001)]
band = np.full((NS, ND), -1)
for i, (lo, hi) in enumerate(BANDS):
    band[(TD > lo) & (TD < hi) if i == 0 else (TD >= lo) & (TD < hi)] = i

# Recovered demand: R2 with kappa 1.0, base means from the train block's in-stock hours.
inst = ~OUT
base = np.zeros((NS, 2, 16))
for p in (0, 1):
    sel = inst[:, TR] & ((TP[:, TR] == p) & valid[:, TR])[:, :, None]
    base[:, p] = np.where(sel, Y[:, TR], 0).sum(1) / np.maximum(sel.sum(1), 1)
st = TP.astype(int)
B_ = base[np.arange(NS)[:, None], st]          # (S, D, 16)
O_ = np.where(inst, Y, 0).sum(2); E_ = np.where(inst, B_, 0).sum(2); M_ = B_.sum(2)
k = (O_ + 1.0 * M_) / np.maximum(E_ + 1.0 * M_, 1e-12)
YR = np.where(OUT, B_ * k[:, :, None], Y)
del B_
print(f"recovered mass added on hours 06-21 of the train split: {(YR.sum() / Y.sum() - 1) * 100:.2f}% of raw sales")


def fit_ipf(V, days, iters=30):
    """a (S, 16) and b (G, D) on regular days of `days`; series without a regular day get a = NaN."""
    R = np.zeros((NS, ND), bool); R[:, days] = regular[:, days]
    Ysh = np.where(R[:, :, None], V, 0).sum(1)                       # (S, 16)
    num_gd = np.zeros((G, ND)); np.add.at(num_gd, group, np.where(R[:, :, None], V, 0).sum(2))
    b = np.ones((G, ND))
    for _ in range(iters):
        den_s = (R * b[group]).sum(1)
        a = np.where(den_s[:, None] > 0, Ysh / np.maximum(den_s[:, None], 1e-12), np.nan)
        asum = np.nan_to_num(a).sum(1)
        den_gd = np.zeros((G, ND)); np.add.at(den_gd, group, R * asum[:, None])
        b = np.where(den_gd > 0, num_gd / np.maximum(den_gd, 1e-12), 1.0)
    return a, b


def day_factor(V, a, days):
    """b(g, d) for `days` with a held fixed (how a later week is scored)."""
    R = np.zeros((NS, ND), bool); R[:, days] = regular[:, days]
    asum = np.nan_to_num(a).sum(1)
    num = np.zeros((G, ND)); den = np.zeros((G, ND))
    np.add.at(num, group, np.where(R[:, :, None], V, 0).sum(2)); np.add.at(den, group, R * asum[:, None])
    return np.where(den > 0, num / np.maximum(den, 1e-12), np.nan)


def records(V, a, b, mask):
    s, d = np.nonzero(mask & ~np.isnan(a[:, 0])[:, None])
    return s, d, V[s, d].sum(1), np.nan_to_num(a[s]).sum(1) * b[group[s], d]


def cell_boot(s, d, num, den, cell, ncell, B=500, seed=0, twoway=True):
    rng = np.random.default_rng(seed)
    pt = np.bincount(cell, num, ncell) / np.bincount(cell, den, ncell) - 1
    draws = np.empty((B, ncell))
    for i in range(B):
        w = np.bincount(rng.integers(0, NS, NS), minlength=NS)[s].astype(float)
        if twoway:
            w = w * np.bincount(rng.integers(0, ND, ND), minlength=ND)[d]
        with np.errstate(invalid="ignore", divide="ignore"):
            draws[i] = np.bincount(cell, w * num, ncell) / np.bincount(cell, w * den, ncell) - 1
    return pt, draws


def ci(draws):
    return np.nanquantile(draws, 0.025, axis=0), np.nanquantile(draws, 0.975, axis=0)


def n_series(s, cell, ncell):
    return np.array([len(np.unique(s[cell == c])) for c in range(ncell)])


fits = {}
for ver, V in (("raw", Y), ("recovered", YR)):
    a, b = fit_ipf(V, TR)
    fits[ver] = (a, b)
    s, d, num, den = records(V, a, b, promo[:, :] & np.isin(np.arange(ND), TR)[None, :])
    one = np.zeros(len(s), int)
    pt, dr = cell_boot(s, d, num, den, one, 1)
    lo, hi = ci(dr)
    print(f"\n== {ver}: overall flag-day lift on the train block {pt[0]*100:+.2f}% [{lo[0]*100:+.2f}; {hi[0]*100:+.2f}] "
          f"(two-way), {len(np.unique(s)):,} series, {len(s):,} promo series-days")
    sc, dc, numc, denc = records(V, a, b, cutday & np.isin(np.arange(ND), TR)[None, :])
    pc, drc = cell_boot(sc, dc, numc, denc, np.zeros(len(sc), int), 1)
    print(f"   unflagged discount days (flag 0, discount < 0.999): lift {pc[0]*100:+.2f}% [{ci(drc)[0][0]*100:+.2f}; {ci(drc)[1][0]*100:+.2f}]")
print(f"   no regular day in the train block (excluded): {int(np.isnan(fits['raw'][0][:, 0]).sum()):,} series")

# Sensitivity: control = every flag-0 day with a valid discount (the research's comparison).
reg_saved = regular.copy(); regular = (TP == 0) & valid
a_s, b_s = fit_ipf(YR, TR)
s, d, num, den = records(YR, a_s, b_s, promo & np.isin(np.arange(ND), TR)[None, :])
print(f"\n== sensitivity, control = any flag-0 day: recovered overall lift {(num.sum()/den.sum()-1)*100:+.2f}%")
regular = reg_saved

# Cells on the train block, recovered version: series-only vs. two-way intervals.
a, b = fits["recovered"]
mask_tr = promo & np.isin(np.arange(ND), TR)[None, :]
s, d, num, den = records(YR, a, b, mask_tr)
cell = group[s] * len(BANDS) + band[s, d]
ncell = G * len(BANDS)
ns = n_series(s, cell, ncell)
pt, dr2 = cell_boot(s, d, num, den, cell, ncell, twoway=True)
_, dr1 = cell_boot(s, d, num, den, cell, ncell, twoway=False)
rk = np.nonzero(ns >= 30)[0]
l2, h2 = ci(dr2); l1, h1 = ci(dr1)
w2 = (h2 - l2)[rk]; w1 = (h1 - l1)[rk]
print(f"\n== cells (group x band), recovered, train block: {len(rk)} with >= 30 series of {ncell}")
print(f"   median interval width: series-only {np.median(w1)*100:.2f} points, two-way {np.median(w2)*100:.2f} points "
      f"(ratio {np.median(w2 / w1):.2f})")


def overlaps(lo, hi, ids):
    pairs = list(combinations(ids, 2))
    return len(pairs), sum(1 for i, j in pairs if not (hi[i] < lo[j] or hi[j] < lo[i]))


for nm_, lo, hi in (("series-only", l1, h1), ("two-way", l2, h2)):
    n, ov = overlaps(lo, hi, rk)
    print(f"   {nm_}: {n} pairs, {ov} overlap ({ov/n*100:.1f}%)")
raw_a, raw_b = fits["raw"]
sr, dr_, numr, denr = records(Y, raw_a, raw_b, mask_tr)
cr = group[sr] * len(BANDS) + band[sr, dr_]
ptr = np.bincount(cr, numr, ncell) / np.bincount(cr, denr, ncell) - 1
gap = (pt - ptr)[rk]
print(f"   recovered minus raw lift by cell: median {np.median(gap)*100:+.2f} points, min {gap.min()*100:+.2f}, max {gap.max()*100:+.2f}")
print("   by band (all groups), recovered two-way:")
bcell = band[s, d]
pb, drb = cell_boot(s, d, num, den, bcell, len(BANDS))
lb, hb = ci(drb)
for i, (lo_, hi_) in enumerate(BANDS):
    print(f"     band {lo_:.2f}-{min(hi_, 1):.2f}: {pb[i]*100:+7.2f}% [{lb[i]*100:+7.2f}; {hb[i]*100:+7.2f}]")
nb, ovb = overlaps(lb, hb, range(len(BANDS)))
print(f"   band pairs overlapping (two-way): {ovb} of {nb}")

# Replication on the validation block: a frozen from train, b(g, d) from validation regular days.
bv = day_factor(YR, a, VA)
mask_va = promo & np.isin(np.arange(ND), VA)[None, :]
sv, dv, numv, denv = records(YR, a, bv, mask_va)
cv = group[sv] * len(BANDS) + band[sv, dv]
nsv = n_series(sv, cv, ncell)
ptv, drv = cell_boot(sv, dv, numv, denv, cv, ncell, seed=1)
both = np.intersect1d(rk, np.nonzero(nsv >= 30)[0])
rho = pd.Series(pt[both]).rank().corr(pd.Series(ptv[both]).rank())
diff = drv[:, both] - dr2[:, both]
dl, dh = np.nanquantile(diff, [0.025, 0.975], axis=0)
consistent = ((dl <= 0) & (dh >= 0)).mean()
inside = ((ptv[both] >= l2[both]) & (ptv[both] <= h2[both])).mean()
print(f"\n== replication on validation ({len(VA)} days): {len(both)} cells ranked in both")
print(f"   Spearman of cell lifts, train vs. validation: {rho:.3f}")
print(f"   cells whose validation-minus-train interval contains 0: {consistent*100:.1f}%; validation point inside the train interval: {inside*100:.1f}%")
print(f"   overall validation lift: {(numv.sum()/denv.sum()-1)*100:+.2f}%")

# Forecast check on validation promo series-days, in-stock hours 06-21, daily in-stock mass.
lift_cell = np.where(np.isfinite(pt), pt, 0.0)
s_, d_ = sv, dv
ins = ~OUT[s_, d_]
yv = np.where(ins, Y[s_, d_], 0).sum(1)
m0 = np.where(ins, np.nan_to_num(a[s_]) * bv[group[s_], d_][:, None], 0).sum(1)
f2 = m0 * (1 + lift_cell[cv])
f1 = np.where(ins, np.mean([Y[s_, d_ - j] for j in range(1, 8)], axis=0), 0).sum(1)
ok = np.isfinite(m0)
for nm_, f in (("F0 no lift", m0), ("F1 last 7 days, same hour", f1), ("F2 with the cell lift", f2)):
    print(f"   {nm_:<28} WAPE {np.abs(f[ok]-yv[ok]).sum()/yv[ok].sum()*100:6.2f}%  bias {(f[ok]-yv[ok]).sum()/yv[ok].sum()*100:+6.2f}%")
rng = np.random.default_rng(0)
dd = []
e0 = np.abs(m0 - yv); e2 = np.abs(f2 - yv); e1 = np.abs(f1 - yv)
for _ in range(500):
    w = np.bincount(rng.integers(0, NS, NS), minlength=NS)[s_] * np.bincount(rng.integers(0, ND, ND), minlength=ND)[d_]
    w = w * ok
    dd.append(((w * e2).sum() - (w * e0).sum()) / (w * yv).sum())
dd = np.array(dd)
print(f"   WAPE(F2) - WAPE(F0), two-way 95%: [{np.quantile(dd, 0.025)*100:+.2f}; {np.quantile(dd, 0.975)*100:+.2f}] points")
print(f"\nelapsed {time.time()-t0:.1f} s")
