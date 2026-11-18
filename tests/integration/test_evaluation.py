"""The evaluation of the test week (U11; RF18, D16, D17, D18; AC18, AC22, AC23): it reads what was issued, writes the test part of the seal and the sealed rows once,
reproduces them on a repetition and keeps another configuration apart."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from dataclasses import replace

import pandas as pd
import pytest

from promolift import variants
from promolift.evaluation import EvaluationError, evaluate_test
from promolift.registry import TEST_KEYS, SealError, config_fingerprint, read_seal, sealed_view
from promolift.reporting import evaluate, ready_instant
from promolift.warehouse import connect
from tests.fixtures.weeks import clone
from tests.unit.test_seal import with_key

CRITERIA_IDS = [f"C{k:02d}" for k in range(1, 11)]
SEALED_TABLES = ("eval_criteria", "eval_replication", "eval_forecast", "eval_variants", "eval_pairs", "eval_leakage", "effect_estimates", "recovery_checks")


def rows(db, sql, params=()):
    conn = connect(db)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def digest(db, tables):
    """The SHA-256 of every sealed row of `tables` (the rows of another configuration, ``post_seal``, are not sealed and are left out)."""
    out = hashlib.sha256()
    for table in tables:
        where = " WHERE seal_state != 'post_seal'" if table in ("eval_criteria", "eval_replication", "eval_forecast", "eval_variants") else ""
        out.update(repr(rows(db, f"SELECT * FROM {table}{where} ORDER BY 1, 2, 3, 4")).encode())
    return out.hexdigest()


def test_the_evaluation_writes_the_test_part_of_the_seal_once_and_its_sealed_rows(evaluated_week):
    assert evaluated_week.out["test"] == "written" and evaluated_week.out["seal_state"] == "sealed"
    seal = read_seal(evaluated_week.seal)
    assert set(seal["test"]) == set(TEST_KEYS) and seal["test"]["config_sha256"] == seal["launch"]["config_sha256"] == config_fingerprint(evaluated_week.view)
    assert [c["id"] for c in seal["test"]["criteria"]] == CRITERIA_IDS and seal["test"]["run_key"] == "run-close"
    criteria = rows(evaluated_week.db, "SELECT criterion_id, seal_state, passed, verdict_es FROM eval_criteria ORDER BY criterion_id")
    assert [(r[0], r[1]) for r in criteria] == [(c, "sealed") for c in CRITERIA_IDS] and criteria[9][2] is None and all(r[3] for r in criteria)
    assert {r[0] for r in rows(evaluated_week.db, "SELECT DISTINCT scope FROM effect_estimates")} == {"launch", "valid_replication", "test"}
    assert {r[0] for r in rows(evaluated_week.db, "SELECT DISTINCT scope FROM recovery_checks")} == {"valid_v1", "valid_v2", "test"}
    assert {r[0] for r in rows(evaluated_week.db, "SELECT DISTINCT method FROM recovery_checks WHERE scope = 'test'")} >= {"r0", "r1"}
    assert rows(evaluated_week.db, "SELECT COUNT(*) FROM eval_replication WHERE seal_state = 'sealed'")[0][0] > 0
    assert {r[0] for r in rows(evaluated_week.db, "SELECT method FROM eval_forecast WHERE seal_state = 'sealed'")} == {"f0_no_lift", "f1_naive", "f2a_overall_lift", "f2_cell_lift"}
    assert {r[0] for r in rows(evaluated_week.db, "SELECT DISTINCT variant FROM eval_variants WHERE seal_state = 'sealed'")} == {
        "control_any_flag0", "series_only_intervals", "mcar_mask", "unflagged_band", "first_category_cell", "per_day_band"}
    assert {(r[0], r[1]) for r in rows(evaluated_week.db, "SELECT scope, ci_kind FROM eval_pairs")} == {("launch", "two_way"), ("launch", "series_only"), ("test", "two_way"), ("test", "series_only")}
    assert rows(evaluated_week.db, "SELECT COUNT(*) FROM eval_leakage")[0][0] == 3


def test_what_is_evaluated_is_what_was_issued(evaluated_week):
    """The lifts of the week are what the days issued and every figure of C01 to C09 is recomputed here from the issued tables."""
    daily = rows(evaluated_week.db, "SELECT version, SUM(observed), SUM(counterfactual) FROM daily_cell WHERE cell_key = 'all' GROUP BY version ORDER BY version")
    test = {r[0]: r for r in rows(evaluated_week.db, "SELECT version, observed, counterfactual, lift FROM effect_estimates WHERE scope = 'test' AND unit = 'overall' ORDER BY version")}
    for version, observed, counterfactual in daily:
        assert test[version][1] == pytest.approx(observed) and test[version][2] == pytest.approx(counterfactual) and test[version][3] == pytest.approx(observed / counterfactual - 1)
    masks = pd.DataFrame(rows(evaluated_week.db, "SELECT series_key, date_key, method, hidden_mass, estimate, day_state FROM mask_checks"), columns=["s", "d", "m", "truth", "est", "state"])
    criteria = {c["id"]: c for c in read_seal(evaluated_week.seal)["test"]["criteria"]}
    sealed_name = json.loads(rows(evaluated_week.db, "SELECT recovery_json FROM model_registry")[0][0])["name"]
    part = masks[masks["m"] == sealed_name]
    wape = (part["est"] - part["truth"]).groupby(part["s"]).sum().abs().sum() / part["truth"].sum()
    assert criteria["C01"]["value"] == pytest.approx(wape) and criteria["C02"]["value"] == pytest.approx(part["est"].sum() / part["truth"].sum() - 1)
    promo, regular = part[part["state"] == "promo"], part[part["state"] == "regular"]
    assert criteria["C03"]["value"] == pytest.approx((promo["est"].sum() / promo["truth"].sum()) / (regular["est"].sum() / regular["truth"].sum()) - 1)
    r1 = masks[masks["m"] == "r1"]
    assert criteria["C01"]["baseline_value"] == pytest.approx((r1["est"] - r1["truth"]).groupby(r1["s"]).sum().abs().sum() / r1["truth"].sum())
    assert criteria["C04"]["value"] == pytest.approx(test["recovered"][3]) and criteria["C04"]["baseline_value"] == pytest.approx(test["raw"][3])
    forecasts = pd.DataFrame(rows(evaluated_week.db, "SELECT method, forecast, observed_instock FROM forecasts WHERE scope = 'test'"), columns=["m", "f", "o"])

    def wape_of(method):
        part = forecasts[forecasts["m"] == method]
        return (part["f"] - part["o"]).abs().sum() / part["o"].sum()

    assert criteria["C08"]["value"] == pytest.approx(wape_of("f2_cell_lift")) and criteria["C08"]["baseline_value"] == pytest.approx(wape_of("f2a_overall_lift"))
    assert criteria["C09"]["value"] == pytest.approx(wape_of("f2_cell_lift")) and criteria["C09"]["baseline_value"] == pytest.approx(wape_of("f1_naive"))
    for cid in ("C01", "C04", "C08", "C09"):
        c = criteria[cid]
        assert c["ci_low"] <= c["ci_high"] and c["passed"] == (c["ci_low"] > 0 if cid == "C04" else c["ci_high"] < 0)


@pytest.mark.parametrize(("change", "mentions"), [
    ("UPDATE daily_cell SET observed = observed * 2 WHERE date_key = 20240628 AND version = 'raw' AND cell_key = 'all'", "20240628"),
    ("UPDATE daily_cell SET counterfactual = counterfactual + 1 WHERE date_key = 20240627 AND version = 'recovered' AND cell_key = 'all'", "20240627"),
    ("UPDATE daily_cell SET series_days = series_days + 1 WHERE date_key = 20240630 AND version = 'recovered' AND cell_key = 'all'", "20240630"),
    ("DELETE FROM daily_cell WHERE date_key = 20240702", "20240702")])
def test_the_evaluation_is_refused_when_the_week_is_not_the_issued_one(week_copy, change, mentions):
    """A warehouse whose daily rows are not the ones the days of the cube give is refused: the evaluation reads what was issued, it does not make it up."""
    w = week_copy()
    for trigger in ("daily_cell_no_update", "daily_cell_no_delete"):
        w.conn.execute(f"DROP TRIGGER {trigger}")
    w.conn.execute(change)
    before = w.seal.read_bytes()
    with pytest.raises(EvaluationError, match=mentions):
        evaluate_test(w.conn, w.cube, w.bundle, w.view)
    with pytest.raises(EvaluationError):
        evaluate(w.conn, w.cube, w.bundle, w.run, w.view, seal_path=w.seal)
    assert w.seal.read_bytes() == before and w.conn.execute("SELECT COUNT(*) FROM eval_criteria").fetchone()[0] == 0


def test_a_run_before_the_close_evaluates_nothing_and_writes_nothing(week_copy):
    w = week_copy()
    before = w.seal.read_bytes()
    out = evaluate(w.conn, w.cube, w.bundle, replace(w.run, as_of=ready_instant(w.view) - pd.Timedelta(seconds=1)), w.view, seal_path=w.seal)
    assert out["test"] == "pending" and out["ready_instant"] == "2024-07-03 00:00:00" and w.seal.read_bytes() == before
    assert w.conn.execute("SELECT COUNT(*) FROM eval_criteria").fetchone()[0] == 0


def test_a_repetition_with_the_sealed_configuration_is_unchanged_and_the_sealed_rows_never_change(evaluated_week, week_copy):
    before, seal_before = digest(evaluated_week.db, SEALED_TABLES), evaluated_week.seal.read_bytes()
    conn = connect(evaluated_week.db)
    again = evaluate(conn, evaluated_week.cube, evaluated_week.bundle, replace(evaluated_week.run, run_key="run-close-2"), evaluated_week.view, seal_path=evaluated_week.seal)
    conn.close()
    assert again["test"] == "sealed_before" and digest(evaluated_week.db, SEALED_TABLES) == before and evaluated_week.seal.read_bytes() == seal_before
    # a warehouse that lost its sealed rows (a rebuild from scratch) reproduces the seal to 6 decimals, leaves it as it is and stores the rows again
    w = week_copy()
    shutil.copyfile(evaluated_week.seal, w.seal)
    out = evaluate(w.conn, w.cube, w.bundle, replace(w.run, run_key="run-close-3"), w.view, seal_path=w.seal)
    assert out["test"] == "unchanged" and w.seal.read_bytes() == seal_before

    def normalised(db_rows):
        return [tuple(round(v, 6) if isinstance(v, float) else v for v in row if not (isinstance(v, str) and v.startswith("run-"))) for row in db_rows]

    for table in ("eval_criteria", "eval_replication", "eval_forecast", "eval_variants", "eval_pairs"):
        mine = [tuple(r) for r in w.conn.execute(f"SELECT * FROM {table} ORDER BY 1, 2, 3, 4")]
        assert normalised(mine) == normalised(rows(evaluated_week.db, f"SELECT * FROM {table} ORDER BY 1, 2, 3, 4")), table


def test_a_sealed_row_cannot_be_changed_deleted_or_inserted_twice(evaluated_week):
    conn = connect(evaluated_week.db)
    try:
        for sql in ("UPDATE eval_criteria SET passed = 1 WHERE seal_state = 'sealed'", "DELETE FROM eval_criteria WHERE seal_state = 'sealed'",
                    "UPDATE eval_variants SET value = 0 WHERE seal_state = 'sealed'", "DELETE FROM eval_pairs", "UPDATE eval_leakage SET value = 0",
                    "INSERT INTO eval_criteria SELECT * FROM eval_criteria WHERE criterion_id = 'C01' AND seal_state = 'sealed'"):
            with pytest.raises(sqlite3.DatabaseError, match="solo inserción"):
                conn.execute(sql)
    finally:
        conn.close()


def test_another_config_after_the_test_seal_is_post_seal_and_replaces_only_post_seal_rows(evaluated_week, launch_config, tmp_path):
    other = clone(evaluated_week.folder, tmp_path / "other", launch_config, evaluated_week.view.train_sha256_seen, evaluated_week.view.eval_sha256_seen)
    cfg = with_key(other.cfg, "ranking.min_series")
    view = sealed_view(cfg, evaluated_week.view.train_sha256_seen, evaluated_week.view.eval_sha256_seen)
    assert config_fingerprint(view) != config_fingerprint(evaluated_week.view)
    seal_before, sealed_before = other.seal.read_bytes(), digest(other.db, SEALED_TABLES)
    out = evaluate(other.conn, other.cube, evaluated_week.bundle, replace(evaluated_week.run, run_key="run-post"), view, seal_path=other.seal)
    assert out["test"] == "post_seal" and out["seal_state"] == "post_seal" and other.seal.read_bytes() == seal_before
    assert dict(other.conn.execute("SELECT seal_state, COUNT(*) FROM eval_criteria GROUP BY seal_state").fetchall()) == {"sealed": 10, "post_seal": 10}
    assert other.conn.execute("SELECT COUNT(*) FROM eval_criteria WHERE seal_state = 'sealed' AND run_key = 'run-close'").fetchone()[0] == 10
    again = evaluate(other.conn, other.cube, evaluated_week.bundle, replace(evaluated_week.run, run_key="run-post-2"), view, seal_path=other.seal)
    assert again["test"] == "post_seal" and {r[0] for r in other.conn.execute("SELECT run_key FROM eval_criteria WHERE seal_state = 'post_seal'")} == {"run-post-2"}
    other.conn.close()
    assert other.seal.read_bytes() == seal_before and digest(other.db, SEALED_TABLES) == sealed_before


def test_variants_are_computed_only_after_the_launch_part_of_the_seal_exists(week_copy):
    w = week_copy()
    w.seal.unlink()
    with pytest.raises(SealError, match="parte del lanzamiento"):
        variants.run(w.conn, w.cube, w.bundle, w.view, seal_path=w.seal)


def test_the_variants_say_what_they_changed_and_leave_the_criteria_as_they_were(evaluated_week):
    found: dict[str, list[str]] = {}
    for variant, unit_key in rows(evaluated_week.db, "SELECT variant, unit_key FROM eval_variants WHERE seal_state = 'sealed'"):
        found.setdefault(variant, []).append(unit_key)
    assert {"raw:all", "recovered:all"} <= set(found["control_any_flag0"]) and {k for k in found["per_day_band"] if k.startswith("20240626:")}
    assert any(k.startswith("r1:") for k in found["mcar_mask"]) and any(k.startswith("launch:") for k in found["series_only_intervals"])
    seal_criteria = {c["id"]: c["value"] for c in read_seal(evaluated_week.seal)["test"]["criteria"]}
    assert seal_criteria["C10"] is None and all(v is not None for k, v in seal_criteria.items() if k != "C10")


def test_the_week_is_resampled_with_the_seed_plus_one_and_the_zero_method_and_the_differences_are_what_they_say(evaluated_week):
    """The intervals of the week are the two-way draws of the week with ``seed + 1`` (independent of the launch's), R0 is exactly zero and every difference of the criteria
    lies inside its own interval."""
    from promolift.bootstrap import interval, two_way_draws_many
    from promolift.evaluation import load_periods, units_of

    w = evaluated_week
    periods = load_periods(connect(w.db), w.cube, w.bundle, w.view)
    rec = periods.week.rec["recovered"]
    unit_of, n_units = units_of(rec, periods.week, periods.n_bands, periods.n_groups)["overall"]
    low, high = interval(two_way_draws_many(rec, [(unit_of, n_units)], w.view.bootstrap.resamples, w.view.bootstrap.seed + 1)[0])
    stored = rows(w.db, "SELECT ci_low, ci_high FROM effect_estimates WHERE scope = 'test' AND version = 'recovered' AND unit = 'overall'")[0]
    assert stored == pytest.approx((float(low[0]), float(high[0])))
    same_seed_as_launch = interval(two_way_draws_many(rec, [(unit_of, n_units)], w.view.bootstrap.resamples, w.view.bootstrap.seed)[0])
    assert stored != pytest.approx((float(same_seed_as_launch[0][0]), float(same_seed_as_launch[1][0])), abs=1e-12)
    r0 = rows(w.db, "SELECT wape_series, bias FROM recovery_checks WHERE scope = 'test' AND method = 'r0'")[0]
    assert r0 == pytest.approx((1.0, -1.0))
    metrics = read_seal(w.seal)["test"]["metrics"]
    for name in ("f2_minus_f2a", "f2_minus_f1", "f2_minus_f0"):
        d = metrics["forecast"][name]
        assert d["ci_low"] <= d["value"] <= d["ci_high"], name
    d = metrics["effect"]["difference"]
    assert d["ci_low"] <= d["value"] <= d["ci_high"] and d["value"] == pytest.approx(metrics["effect"]["recovered"]["lift"] - metrics["effect"]["raw"]["lift"])


def test_the_variants_change_what_they_say_they_change(evaluated_week):
    v = {(r[0], r[1]): r[2] for r in rows(evaluated_week.db, "SELECT variant, unit_key, value FROM eval_variants WHERE seal_state = 'sealed'")}
    sealed = {r[0]: r[1] for r in rows(evaluated_week.db, "SELECT version, lift FROM effect_estimates WHERE scope = 'test' AND unit = 'overall'")}
    assert v[("control_any_flag0", "recovered:all")] != pytest.approx(sealed["recovered"]) and v[("control_any_flag0", "raw:all")] != pytest.approx(sealed["raw"])
    pairs = {(r[0], r[1]): r[2:] for r in rows(evaluated_week.db, "SELECT scope, ci_kind, cells, pairs, overlapping, median_width FROM eval_pairs")}
    for scope in ("launch", "test"):
        assert pairs[(scope, "series_only")][3] < pairs[(scope, "two_way")][3] and pairs[(scope, "series_only")][2] <= pairs[(scope, "two_way")][2]
        assert pairs[(scope, "series_only")][0] == pairs[(scope, "two_way")][0] and pairs[(scope, "series_only")][1] == pairs[(scope, "two_way")][1]
    assert v[("mcar_mask", "mask:series_days")] == rows(evaluated_week.db, "SELECT COUNT(*) FROM mask_checks WHERE method = 'r1'")[0][0]
    assert v[("mcar_mask", "r0:wape")] == pytest.approx(1.0) and 0 < v[("mcar_mask", "r1:wape")] < 1
    unflagged = {k: x for (var, k), x in v.items() if var == "unflagged_band"}
    assert unflagged["recovered:all"] is not None and unflagged["recovered:all"] != pytest.approx(sealed["recovered"])
    per_day = [(k, x) for (var, k), x in v.items() if var == "per_day_band"]
    assert {k.split(":")[0] for k, _ in per_day} == {"20240626", "20240627", "20240628", "20240629", "20240630", "20240701", "20240702"}


def test_the_replication_counts_only_the_cells_with_enough_series_in_both_the_launch_and_the_week(week_copy):
    w = week_copy()
    base = evaluate_test(w.conn, w.cube, w.bundle, w.view)
    launch, test = [r["series_launch"] for r in base.replication], [r["series_test"] for r in base.replication]
    limit = next(m for m in sorted(set(launch + test)) if sum(a >= m and b >= m for a, b in zip(launch, test, strict=True)) != sum(a >= m or b >= m for a, b in zip(launch, test, strict=True)))
    strict = replace(w.view, ranking=replace(w.view.ranking, min_series=limit))
    result = evaluate_test(w.conn, w.cube, w.bundle, strict)
    both = [r for r in result.replication if r["series_launch"] >= limit and r["series_test"] >= limit and r["lift_launch"] is not None and r["lift_test"] is not None]
    assert 0 < len(both) < len(result.replication) and result.metrics["replication"]["cells"] == len(both)
    assert {r["cell"] for r in result.replication if r["consistent"] is not None} == {r["cell"] for r in both}
    assert all(r["diff_ci_low"] is None for r in result.replication if r not in both)
