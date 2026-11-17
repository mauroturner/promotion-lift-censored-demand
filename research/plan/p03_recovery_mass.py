"""Planner check 3: recovery judged by the mass it puts back, not by hourly error.

p02 found that at the hour level no method beats predicting zero (hourly sales are intermittent). The effect
estimator only uses sums, so this script measures, on the same tail masks as p02 (seeds 0 and 1): the bias of the
hidden mass overall and by day state (promo vs. not), the lift bias that a state-dependent bias would create, and
WAPE of the hidden mass per series-day and per series. Fit on the train block; V1 and V2 as in p02.
Reads only data/raw/train.parquet; the eval split (sealed test week) is never opened.
"""
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import train_only, SPLIT_DATES  # noqa: E402

warnings.filterwarnings("ignore", category=RuntimeWarning)  # 0/0 where a group is empty (R0 lift bias) prints nan

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
inst = TST == 0
r1 = np.zeros((NS, 2, 24)); cnt_any = np.zeros((NS, 24)); sum_any = np.zeros((NS, 24))
for p in (0, 1):
    sel = inst[:, TR, :] & ((TP[:, TR] == p) & valid[:, TR])[:, :, None]
    s_ = np.where(sel, TS[:, TR, :], 0).sum(axis=1); c_ = sel.sum(axis=1)
    sum_any += s_; cnt_any += c_
    r1[:, p, :] = np.where(c_ > 0, s_ / np.maximum(c_, 1), np.nan)
any_mean = np.where(cnt_any > 0, sum_any / np.maximum(cnt_any, 1), 0.0)
for p in (0, 1):
    r1[:, p, :] = np.where(np.isnan(r1[:, p, :]), any_mean, r1[:, p, :])
win = TST[:, TR][:, :, 6:22] == 1
fo = (win.argmax(axis=2) + 6)[win.any(axis=2)]
pmf = np.bincount(fo, minlength=22)[6:22].astype(float); pmf /= pmf.sum()


def masked(days, seed):
    full = (TST[:, days][:, :, 6:22] == 0).all(axis=2) & valid[:, days]
    s, j = np.nonzero(full); d = days[j]
    cut = np.random.default_rng(seed).choice(H, size=len(s), p=pmf)
    return s, d, cut, H[None, :] >= cut[:, None]


def parts(s, d, hid):
    y = TS[s, d][:, 6:22]; base = r1[s, TP[s, d]][:, 6:22]; obs = ~hid
    return y, base, np.where(obs, y, 0).sum(1), np.where(obs, base, 0).sum(1), base.sum(1)


def feats(s, d, cut, hid, base, O, E, m):
    r, c = np.nonzero(hid)
    return np.column_stack([H[c], cut[r], base[r, c], O[r], E[r], m[r], TP[s[r], d[r]], 1 - TD[s[r], d[r]],
                            weekday[d[r]], group[s[r]]]), r, c


s, d, cut, hid = masked(TR, 1)
pick = np.random.default_rng(2).choice(len(s), 150_000, replace=False)
s, d, cut, hid = s[pick], d[pick], cut[pick], hid[pick]
y, base, O, E, m = parts(s, d, hid)
X, r, c = feats(s, d, cut, hid, base, O, E, m)
hgb = HistGradientBoostingRegressor(loss="poisson", max_iter=200, learning_rate=0.1, max_leaf_nodes=31,
                                    min_samples_leaf=50, early_stopping=False, random_state=0,
                                    categorical_features=[8, 9]).fit(X, y[r, c])

rng0 = np.random.default_rng(0)
for name, days in (("V1", V1), ("V2", V2)):
    full = (TST[:, days][:, :, 6:22] == 0).all(axis=2) & valid[:, days]
    s, j = np.nonzero(full); d = days[j]
    cut = rng0.choice(H, size=len(s), p=pmf); hid = H[None, :] >= cut[:, None]  # same draws as p02 (seed 0, V1 then V2)
    y, base, O, E, m = parts(s, d, hid)
    preds = {"R0 none": np.zeros_like(y), "R1 mean": base}
    for k in (0.5, 1.0):
        preds[f"R2 kappa={k}"] = base * ((O + k * m) / np.maximum(E + k * m, 1e-12))[:, None]
    X, r, c = feats(s, d, cut, hid, base, O, E, m)
    p3 = np.zeros_like(y); p3[r, c] = hgb.predict(X); preds["R3 HGB"] = p3
    promo = TP[s, d] == 1
    print(f"\n== {name}: {len(s):,} masked days ({promo.mean()*100:.1f}% promo), hidden mass {y[hid].sum():,.1f}")
    print(f"   {'method':<14} {'bias all':>9} {'bias promo':>11} {'bias other':>11} {'lift bias':>10} {'WAPE day':>9} {'WAPE series':>12}")
    for k, p in preds.items():
        ph = np.where(hid, p, 0).sum(1); yh = np.where(hid, y, 0).sum(1)
        b_all = ph.sum() / yh.sum() - 1
        b_p = ph[promo].sum() / yh[promo].sum() - 1; b_o = ph[~promo].sum() / yh[~promo].sum() - 1
        lift_bias = (1 + b_p) / (1 + b_o) - 1
        w_day = np.abs(ph - yh).sum() / yh.sum()
        u, inv = np.unique(s, return_inverse=True)
        w_ser = np.abs(np.bincount(inv, ph) - np.bincount(inv, yh)).sum() / yh.sum()
        print(f"   {k:<14} {b_all*100:+8.2f}% {b_p*100:+10.2f}% {b_o*100:+10.2f}% {lift_bias*100:+9.2f}% {w_day*100:8.2f}% {w_ser*100:11.2f}%")
