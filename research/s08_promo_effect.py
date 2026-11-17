"""First look at the promotion effect: naive versus adjusted for stockouts. Train block only.

Promotion indicator: activity_flag = 1 (primary, "marca de promoción"). Sensitivity: depth discount <= 0.9 against
discount == 1.0. Rows with discount 0 or above 1 are left out of every estimate (their count is printed).

Four estimates, each a relative lift of promo over non-promo sales (promo / non-promo - 1):
  V1 naive pooled: all rows of promo days against all rows of other days, every series and hour together.
  V2 within series, hour matched: for each series and hour, the mean on promo days over the mean on
     non-promo days of the same series; summed over hours and series (sales-weighted).
  V3 as V2, in-stock hours only (status 0): censoring removed by dropping stockout hours. Conditioning on
     stock status is conditioning on a variable promotions move (s03, s06).
  V4 as V2, recovered demand: each stockout hour takes the mean in-stock sales of the same series, hour and
     promo state (fallback: same series and hour in the other state). This assumes stockouts are random given
     series, hour and promo state, which is not established: stockouts also rise with demand.
Intervals: bootstrap over series (B=500, seed 0).
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import train_only  # noqa: E402
from estimators import bootstrap_weights, weighted_ratio, recover, v_matched  # noqa: E402

meta, S, ST, T = train_only()
TS, TST, TP, TD = T["sales"], T["stock"], T["promo"], T["discount"]
n_series = T["n_series"]
valid = (TD > 0) & (TD <= 1.0)
print(f"valid days (discount in (0, 1]): {int(valid.sum()):,} of {valid.size:,} series-days")
print(f"excluded: discount 0: {int((TD == 0).sum()):,}; discount above 1: {int((TD > 1).sum())}")
Wb = bootstrap_weights(n_series, B=500, seed=0)


def v_naive(pm, nm):
    """Pooled hourly sums and counts per series for promo and non-promo days."""
    pS = (TS * pm[:, :, None]).sum(axis=(1, 2))
    pN = pm.sum(axis=1) * 24.0
    nS = (TS * nm[:, :, None]).sum(axis=(1, 2))
    nN = nm.sum(axis=1) * 24.0
    return pS, pN, nS, nN


def report(label, point, boot, n_ok, n_promo_days):
    lo, hi = np.quantile(boot, [0.025, 0.975])
    print(f"{label:58s} lift = {point*100:+7.2f}%  95% [{lo*100:+7.2f}; {hi*100:+7.2f}]  series={n_ok:,}  promo series-days={n_promo_days:,}")


def run(defn, pm, nm, x_for_imp):
    print(f"\n== Definition: {defn}")
    print(f"   promo series-days: {int(pm.sum()):,}; non-promo series-days: {int(nm.sum()):,}; promo share of valid days: {pm.sum()/(pm.sum()+nm.sum())*100:.2f}%")
    pS, pN, nS, nN = v_naive(pm, nm)
    pt = (pS.sum() / pN.sum()) / (nS.sum() / nN.sum()) - 1
    boot = np.array([(w @ pS / (w @ pN)) / (w @ nS / (w @ nN)) - 1 for w in Wb])
    report("V1 naive pooled, raw sales, all hours", pt, boot, n_series, int(pm.sum()))
    A, Bv, ok = v_matched(TS, pm, nm)
    pt = A.sum() / Bv.sum() - 1
    report("V2 within series, hour matched, raw sales, all hours", pt, weighted_ratio(A, Bv, Wb), int(ok.sum()), int(pm.sum()))
    A, Bv, ok = v_matched(TS, pm, nm, instock=(TST == 0) & valid[:, :, None])
    pt = A.sum() / Bv.sum() - 1
    report("V3 within series, hour matched, in-stock hours only", pt, weighted_ratio(A, Bv, Wb), int(ok.sum()), int(pm.sum()))
    R, fb, miss = recover(TS, TST, x_for_imp, pm | nm)
    use3 = (pm | nm)[:, :, None]
    bad_sh = (np.isnan(R) & use3).any(axis=1)  # series-hours with a stockout and no in-stock value at all
    A, Bv, ok = v_matched(R, pm, nm, hour_ok=~bad_sh)
    pt = A.sum() / Bv.sum() - 1
    report("V4 within series, hour matched, recovered demand (adjusted)", pt, weighted_ratio(A, Bv, Wb), int(ok.sum()), int(pm.sum()))
    r_s = A[ok & (Bv > 0)] / Bv[ok & (Bv > 0)]  # per-series ratio, for comparison with the paper's median uplift
    q1, med, q3 = np.quantile(r_s, [0.25, 0.5, 0.75])
    print(f"   per-series ratio (promo / non-promo, 1 = no effect): median {med:.3f}, IQR {q1:.3f} to {q3:.3f}, series={r_s.size:,}")
    print("   The paper (section 3.2) reports a median promotion uplift of 1.43 with IQR 1.05 to 2.06; a different sample and definition.")
    print(f"   recovery: stockout hours on compared days={int(((TST == 1) & use3).sum()):,}; "
          f"(series,hour,promo) cells falling back to the other promo state={fb:,}; "
          f"series-hours with no in-stock value for this hour (excluded from V4)={int(bad_sh.sum()):,} of {bad_sh.size:,}")


pm_act = (TP == 1) & valid
nm_act = (TP == 0) & valid
run("activity_flag = 1 against activity_flag = 0 (primary)", pm_act, nm_act, TP)

pm_dep = valid & (TD <= 0.9)
nm_dep = valid & (TD == 1.0)
run("discount <= 0.9 against discount == 1.0 (sensitivity)", pm_dep, nm_dep, (TD <= 0.9).astype(np.int8))

print("\n== Stockout share on promo versus non-promo valid days (window 06-21), for context")
w = slice(6, 22)
print(f"   promo: {(TST[pm_act][:, w]).mean()*100:.2f}%; non-promo: {(TST[nm_act][:, w]).mean()*100:.2f}%")
