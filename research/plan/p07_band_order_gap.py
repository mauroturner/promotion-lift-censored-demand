"""Planner check 7: the depth-order correlation of the bands (C07) and the interval of recovered minus raw (C04).

Reuses p04_effect.py (imported silently). Spearman between band depth (1 - discount, deepest first) and the band's
recovered lift on the train block and on the validation block (a from train, day factor from validation).
Recovered minus raw overall flag-day lift on the train block with a paired two-way bootstrap (500, seed 0):
the same series and day weights for both versions.
Reads only data/raw/train.parquet; the eval split (sealed test week) is never opened.
"""
import contextlib
import io
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
with contextlib.redirect_stdout(io.StringIO()):
    import p04_effect as e  # noqa: E402

depth_rank = np.arange(len(e.BANDS))  # band 0 is the deepest
pb = e.pb
print("train band lifts (recovered):", [f"{v*100:+.2f}%" for v in pb])
print(f"Spearman(depth, lift), train: {pd.Series(-depth_rank).corr(pd.Series(pb), method='spearman'):.3f}")
bandv = e.band[e.sv, e.dv]
pv = np.bincount(bandv, e.numv, len(e.BANDS)) / np.bincount(bandv, e.denv, len(e.BANDS)) - 1
print("validation band lifts (recovered):", [f"{v*100:+.2f}%" for v in pv])
print(f"Spearman(depth, lift), validation: {pd.Series(-depth_rank).corr(pd.Series(pv), method='spearman'):.3f}")

ar, br = e.fits["raw"]; ac, bc = e.fits["recovered"]
s, d, n_rec, d_rec = e.records(e.YR, ac, bc, e.mask_tr)
s2, d2, n_raw, d_raw = e.records(e.Y, ar, br, e.mask_tr)
assert np.array_equal(s, s2) and np.array_equal(d, d2)
gap = (n_rec.sum() / d_rec.sum()) - (n_raw.sum() / d_raw.sum())
rng = np.random.default_rng(0)
dr = []
for _ in range(500):
    w = (np.bincount(rng.integers(0, e.NS, e.NS), minlength=e.NS)[s] * np.bincount(rng.integers(0, e.ND, e.ND), minlength=e.ND)[d]).astype(float)
    dr.append((w * n_rec).sum() / (w * d_rec).sum() - (w * n_raw).sum() / (w * d_raw).sum())
print(f"recovered minus raw overall lift, train: {gap*100:+.2f} points, paired two-way 95% [{np.quantile(dr, 0.025)*100:+.2f}; {np.quantile(dr, 0.975)*100:+.2f}]")
