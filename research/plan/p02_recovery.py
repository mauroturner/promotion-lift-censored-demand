"""Planner check 2: recovered demand validated by synthetic censoring of in-stock hours, where the truth is known.

Mask: on days fully in stock from 06 to 21 h, a cut hour is drawn from the train block's distribution of the first
stock-out hour, and hours cut..21 are hidden (86% of real stock-outs last until 21 h: p01). The hidden sales are the
truth. Methods fit on the train block (2024-03-28..05-31) only; kappa and the method are compared on V1
(06-08..06-16) and previewed on V2 (06-17..06-25). Also an MCAR mask (three random hours) as a contrast.
Reads only data/raw/train.parquet; the eval split (sealed test week) is never opened.
"""
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import train_only, SPLIT_DATES  # noqa: E402

t0 = time.time()
meta, S, ST, T = train_only()
TS, TST, TP, TD = T["sales"], T["stock"], T["promo"], T["discount"]
NS, ND = T["n_series"], T["n_days"]
origin = pd.Timestamp(SPLIT_DATES["train"][0])
idx = lambda s: (pd.Timestamp(s) - origin).days  # noqa: E731
TR = np.arange(idx("2024-03-28"), idx("2024-05-31") + 1)
V1 = np.arange(idx("2024-06-08"), idx("2024-06-16") + 1)
V2 = np.arange(idx("2024-06-17"), idx("2024-06-25") + 1)
H = np.arange(6, 22)
valid = (TD > 0) & (TD <= 1)
group = meta.groupby("series").management_group_id.first().reindex(range(NS)).to_numpy()
weekday = np.array([(origin + pd.Timedelta(days=int(k))).weekday() for k in range(ND)])

# R1: mean in-stock sales by series, hour and promo state on the train block; fallback: any state; then 0.
inst = (TST == 0)
r1 = np.zeros((NS, 2, 24))
cnt_any = np.zeros((NS, 24)); sum_any = np.zeros((NS, 24))
for p in (0, 1):
    sel = inst[:, TR, :] & ((TP[:, TR] == p) & valid[:, TR])[:, :, None]
    s_ = np.where(sel, TS[:, TR, :], 0).sum(axis=1); c_ = sel.sum(axis=1)
    sum_any += s_; cnt_any += c_
    r1[:, p, :] = np.where(c_ > 0, s_ / np.maximum(c_, 1), np.nan)
any_mean = np.where(cnt_any > 0, sum_any / np.maximum(cnt_any, 1), 0.0)
for p in (0, 1):
    r1[:, p, :] = np.where(np.isnan(r1[:, p, :]), any_mean, r1[:, p, :])

# First stock-out hour distribution on the train block (06..21).
win = TST[:, TR][:, :, 6:22] == 1
fo = (win.argmax(axis=2) + 6)[win.any(axis=2)]
pmf = np.bincount(fo, minlength=22)[6:22].astype(float); pmf /= pmf.sum()


def masked_days(days, rng, kind):
    """Return arrays (s, d, cut) for fully in-stock valid days; MCAR returns a (n, 16) hidden mask instead of a tail."""
    full = (TST[:, days][:, :, 6:22] == 0).all(axis=2) & valid[:, days]
    s, j = np.nonzero(full)
    d = days[j]
    if kind == "tail":
        cut = rng.choice(H, size=len(s), p=pmf)
        hid = H[None, :] >= cut[:, None]
    else:
        hid = np.zeros((len(s), 16), bool)
        pick = np.argsort(rng.random((len(s), 16)), axis=1)[:, :3]
        np.put_along_axis(hid, pick, True, axis=1)
        cut = np.full(len(s), -1)
    return s, d, cut, hid


def predict(s, d, hid, kappa):
    y = TS[s, d][:, 6:22]
    base = r1[s, TP[s, d]][:, 6:22]
    obs = ~hid
    O = np.where(obs, y, 0).sum(axis=1); E = np.where(obs, base, 0).sum(axis=1); m = base.sum(axis=1)
    out = {"R0 none (zero)": np.zeros_like(y), "R1 series-hour-state mean": base}
    for k in kappa:
        kk = (O + k * m) / np.maximum(E + k * m, 1e-12)
        out[f"R2 kappa={k}"] = base * kk[:, None]
    return y, out, O, E, m, base


def wape(y, p, hid):
    return np.abs(p - y)[hid].sum() / y[hid].sum(), (p - y)[hid].sum() / y[hid].sum()


def boot_diff(y, pa, pb, hid, s, B=200, seed=0):
    """Series bootstrap of WAPE(a) - WAPE(b) on the hidden hours (cluster: series)."""
    ea = np.where(hid, np.abs(pa - y), 0).sum(axis=1); eb = np.where(hid, np.abs(pb - y), 0).sum(axis=1)
    yy = np.where(hid, y, 0).sum(axis=1)
    u, inv = np.unique(s, return_inverse=True)
    A = np.bincount(inv, ea); Bb = np.bincount(inv, eb); Y = np.bincount(inv, yy)
    rng = np.random.default_rng(seed)
    w = np.stack([np.bincount(rng.integers(0, len(u), len(u)), minlength=len(u)) for _ in range(B)]).astype(float)
    dif = (w @ A - w @ Bb) / (w @ Y)
    return np.quantile(dif, [0.025, 0.975])


def features(s, d, cut, hid, O, E, m, base):
    """One row per hidden hour: hour, cut, base mean, observed and expected mass before the cut, promo, depth, weekday, group."""
    r, c = np.nonzero(hid)
    return np.column_stack([H[c], cut[r], base[r, c], O[r], E[r], m[r], TP[s[r], d[r]], 1 - TD[s[r], d[r]],
                            weekday[d[r]], group[s[r]]]), r, c


KAPPA = [0, 0.25, 0.5, 1.0, 2.0]
rng = np.random.default_rng(0)
res = {}
for name, days in (("V1", V1), ("V2", V2)):
    s, d, cut, hid = masked_days(days, rng, "tail")
    y, preds, O, E, m, base = predict(s, d, hid, KAPPA)
    res[name] = (s, d, cut, hid, y, preds, O, E, m, base)
    print(f"\n== {name}: tail mask on {len(s):,} fully in-stock days, {int(hid.sum()):,} hidden hours, hidden sales {y[hid].sum():,.1f}")
    for k, p in preds.items():
        w, b = wape(y, p, hid)
        print(f"   {k:<28} WAPE {w*100:6.2f}%  bias {b*100:+6.2f}%")

# R3: HistGradientBoosting (Poisson loss) on tail masks of train-block days, 150,000 sampled days.
s, d, cut, hid = masked_days(TR, np.random.default_rng(1), "tail")
pick = np.random.default_rng(2).choice(len(s), 150_000, replace=False)
s, d, cut, hid = s[pick], d[pick], cut[pick], hid[pick]
y, _, O, E, m, base = predict(s, d, hid, [])
X, r, c = features(s, d, cut, hid, O, E, m, base)
t1 = time.time()
hgb = HistGradientBoostingRegressor(loss="poisson", max_iter=200, learning_rate=0.1, max_leaf_nodes=31,
                                    min_samples_leaf=50, early_stopping=False, random_state=0,
                                    categorical_features=[8, 9])
hgb.fit(X, y[r, c])
print(f"\nR3 fit on {len(X):,} hidden hours of train-block days in {time.time()-t1:.1f} s")
for name in ("V1", "V2"):
    s, d, cut, hid, y, preds, O, E, m, base = res[name]
    X, r, c = features(s, d, cut, hid, O, E, m, base)
    p = np.zeros_like(y); p[r, c] = hgb.predict(X)
    preds["R3 HGB poisson"] = p
    w, b = wape(y, p, hid)
    print(f"   {name} R3 HGB poisson               WAPE {w*100:6.2f}%  bias {b*100:+6.2f}%")

best_k = min(KAPPA, key=lambda k: wape(res["V1"][4], res["V1"][5][f"R2 kappa={k}"], res["V1"][3])[0])
print(f"\nkappa chosen on V1: {best_k}")
s, d, cut, hid, y, preds, *_ = res["V2"]
for a, b in ((f"R2 kappa={best_k}", "R1 series-hour-state mean"), ("R3 HGB poisson", f"R2 kappa={best_k}"),
             ("R3 HGB poisson", "R1 series-hour-state mean")):
    lo, hi = boot_diff(y, preds[a], preds[b], hid, s)
    print(f"   V2 WAPE({a}) - WAPE({b}): 95% series-bootstrap interval [{lo*100:+.2f}; {hi*100:+.2f}] points")

# Error by cut hour on V2 for the kappa chosen (the late cuts carry little mass).
print("\n== V2 by cut hour (chosen R2): hidden sales share, WAPE")
for h0 in (6, 10, 14, 18, 21):
    sel = cut == h0
    if sel.any():
        w, _ = wape(y[sel], preds[f"R2 kappa={best_k}"][sel], hid[sel])
        print(f"   cut {h0:>2}: days {int(sel.sum()):,}, WAPE {w*100:.2f}%")

print("\n== MCAR contrast on V2 (three random hours hidden)")
s, d, cut, hid = masked_days(V2, np.random.default_rng(3), "mcar")
y, preds, O, E, m, base = predict(s, d, hid, [best_k])
for k, p in preds.items():
    w, b = wape(y, p, hid)
    print(f"   {k:<28} WAPE {w*100:6.2f}%  bias {b*100:+6.2f}%")
print(f"\nelapsed {time.time()-t0:.1f} s")
