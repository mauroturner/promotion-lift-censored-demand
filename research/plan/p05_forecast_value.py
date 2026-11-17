"""Planner check 5: what the cell lift adds to a forecast beyond one average lift, and R2 against R1 with intervals.

Reuses p04_effect.py (imported with its printing silenced: same data, fits and validation scoring), then on the
validation promo series-days (in-stock hours 06-21, daily in-stock mass):
F2a = counterfactual x (1 + one overall flag-day lift of the train block); F2 = x (1 + the lift of the cell).
Also the convergence of the 30 IPF iterations, and, on the V2 tail mask of p02-p03, the day-level WAPE of the
hidden mass for R2 (kappa 1.0) minus R1 with a series-bootstrap interval.
Reads only data/raw/train.parquet; the eval split (sealed test week) is never opened.
"""
import contextlib
import io
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
with contextlib.redirect_stdout(io.StringIO()):
    import p04_effect as e  # noqa: E402

a, b = e.fits["recovered"]
s, d, num, den = e.records(e.YR, a, b, e.mask_tr)
overall = num.sum() / den.sum() - 1
sv, dv, cv, bv = e.sv, e.dv, e.cv, e.bv
ins = ~e.OUT[sv, dv]
yv = np.where(ins, e.Y[sv, dv], 0).sum(1)
m0 = np.where(ins, np.nan_to_num(a[sv]) * bv[e.group[sv], dv][:, None], 0).sum(1)
ok = np.isfinite(m0)
f2 = m0 * (1 + e.lift_cell[cv]); f2a = m0 * (1 + overall)
print(f"overall flag-day lift of the train block (recovered): {overall*100:+.2f}%")
for nm_, f in (("F2a one overall lift", f2a), ("F2 cell lift", f2)):
    print(f"   {nm_:<22} WAPE {np.abs(f[ok]-yv[ok]).sum()/yv[ok].sum()*100:6.2f}%  bias {(f[ok]-yv[ok]).sum()/yv[ok].sum()*100:+6.2f}%")
rng = np.random.default_rng(0)
dd = []
for _ in range(500):
    w = (np.bincount(rng.integers(0, e.NS, e.NS), minlength=e.NS)[sv] * np.bincount(rng.integers(0, e.ND, e.ND), minlength=e.ND)[dv]) * ok
    dd.append(((w * np.abs(f2 - yv)).sum() - (w * np.abs(f2a - yv)).sum()) / (w * yv).sum())
print(f"   WAPE(F2) - WAPE(F2a), two-way 95%: [{np.quantile(dd, 0.025)*100:+.2f}; {np.quantile(dd, 0.975)*100:+.2f}] points")

# IPF convergence: largest relative change of b between iteration 30 and 60.
a30, b30 = e.fit_ipf(e.YR, e.TR, iters=30)
a60, b60 = e.fit_ipf(e.YR, e.TR, iters=60)
print(f"IPF: max |b60/b30 - 1| on train days = {np.nanmax(np.abs(b60[:, e.TR] / b30[:, e.TR] - 1)):.2e}")

# R2 (kappa 1.0) vs R1 on the V2 tail mask: day-level WAPE of the hidden mass, series bootstrap.
sys.argv = ["p03"]
with contextlib.redirect_stdout(io.StringIO()):
    import p03_recovery_mass as r  # noqa: E402
rng0 = np.random.default_rng(0)
for name, days in (("V1", r.V1), ("V2", r.V2)):
    full = (r.TST[:, days][:, :, 6:22] == 0).all(axis=2) & r.valid[:, days]
    s2, j = np.nonzero(full); d2 = days[j]
    cut = rng0.choice(r.H, size=len(s2), p=r.pmf); hid = r.H[None, :] >= cut[:, None]
y, base, O, E, m = r.parts(s2, d2, hid)
p1 = base; p2 = base * ((O + m) / np.maximum(E + m, 1e-12))[:, None]
yh = np.where(hid, y, 0).sum(1); e1 = np.abs(np.where(hid, p1, 0).sum(1) - yh); e2 = np.abs(np.where(hid, p2, 0).sum(1) - yh)
u, inv = np.unique(s2, return_inverse=True)
A1, A2, YY = np.bincount(inv, e1), np.bincount(inv, e2), np.bincount(inv, yh)
rng = np.random.default_rng(0)
W = np.stack([np.bincount(rng.integers(0, len(u), len(u)), minlength=len(u)) for _ in range(500)]).astype(float)
dif = (W @ A2 - W @ A1) / (W @ YY)
print(f"V2 day-level WAPE: R1 {A1.sum()/YY.sum()*100:.2f}%, R2 {A2.sum()/YY.sum()*100:.2f}%; "
      f"R2 - R1 95% series bootstrap [{np.quantile(dif, 0.025)*100:+.2f}; {np.quantile(dif, 0.975)*100:+.2f}] points")
