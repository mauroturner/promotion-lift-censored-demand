"""Planner check 6: the recovery choice by WAPE of the hidden mass per series (the grain the lift sums over).

Reuses p03_recovery_mass.py (imported silently: same train-block fit, R3 model and seeds). On the tail masks of V1
(choice) and V2 (preview): series-level WAPE and bias for R1, R2 with kappa in {0.25, 0.5, 1, 2} and R3; the
choice on V1; on V2 the 95% series-bootstrap interval (B = 500, seed 0) of the chosen method minus R1 and minus R3.
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
    import p03_recovery_mass as r  # noqa: E402

rng0 = np.random.default_rng(0)
out = {}
for name, days in (("V1", r.V1), ("V2", r.V2)):
    full = (r.TST[:, days][:, :, 6:22] == 0).all(axis=2) & r.valid[:, days]
    s, j = np.nonzero(full); d = days[j]
    cut = rng0.choice(r.H, size=len(s), p=r.pmf); hid = r.H[None, :] >= cut[:, None]
    y, base, O, E, m = r.parts(s, d, hid)
    preds = {"R1": base}
    for k in (0.25, 0.5, 1.0, 2.0):
        preds[f"R2 k={k}"] = base * ((O + k * m) / np.maximum(E + k * m, 1e-12))[:, None]
    X, rr, cc = r.feats(s, d, cut, hid, base, O, E, m)
    p3 = np.zeros_like(y); p3[rr, cc] = r.hgb.predict(X); preds["R3"] = p3
    u, inv = np.unique(s, return_inverse=True)
    yh = np.bincount(inv, np.where(hid, y, 0).sum(1))
    sums = {k: np.bincount(inv, np.where(hid, p, 0).sum(1)) for k, p in preds.items()}
    out[name] = (yh, sums)
    print(f"== {name}: {len(u):,} series with a masked day")
    for k, ph in sums.items():
        print(f"   {k:<10} series WAPE {np.abs(ph - yh).sum()/yh.sum()*100:6.2f}%  bias {(ph.sum()/yh.sum()-1)*100:+6.2f}%")
yh, sums = out["V1"]
choice = min(sums, key=lambda k: np.abs(sums[k] - yh).sum())
print(f"chosen on V1: {choice}")
yh, sums = out["V2"]
rng = np.random.default_rng(0)
W = np.stack([np.bincount(rng.integers(0, len(yh), len(yh)), minlength=len(yh)) for _ in range(500)]).astype(float)
for other in ("R1", "R3"):
    dif = (W @ np.abs(sums[choice] - yh) - W @ np.abs(sums[other] - yh)) / (W @ yh)
    print(f"   V2 series WAPE({choice}) - WAPE({other}): [{np.quantile(dif, 0.025)*100:+.2f}; {np.quantile(dif, 0.975)*100:+.2f}] points")
