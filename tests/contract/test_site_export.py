"""The five JSON files the site copies (U14; RF22, AC26; D36; plan, section 21): their shape (a contract that marca-personal consumes), their size, one export at a time under a manifest
written last, figures that are the ones of the Parquet files, rules read once and nothing of the test before the seal."""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from promolift import site_export
from promolift.dashboard.semantic_model import MODEL
from promolift.export import export_star_schema
from promolift.registry import RunMeta, read_seal, sealed_view
from promolift.reporting import evaluate
from promolift.site_export import MANIFEST_FILE, REQUIRED_STAR, SITE_FILES, SiteExportError, SiteSetError, export_site, read_site, verify_site
from promolift.validate import RULES, Aggregation
from promolift.warehouse import connect
from tests.fixtures.weeks import clone
from tests.unit.test_seal import with_key

ENVELOPE = {"schema_version", "run_key", "as_of", "train_sha256", "eval_sha256", "attribution"}
KEYS = {
    "summary.json": {"status", "evaluation_status", "headline", "criteria", "seal"},
    "data.json": {"hierarchy", "hour_profile", "first_stockout", "day_states", "discount_bins", "anomalies", "night_share", "split"},
    "algorithms.json": {"naive_vs_adjusted", "example_day", "recovery", "bands", "groups", "cells", "intervals", "leakage"},
    "operation.json": {"days", "day_bands", "replication", "forecast", "tiers_now", "overlap_groups_now"},
    "validation_rules.json": {"rules", "totals"}}
HEADLINE = {"series", "stores", "cities", "products", "days", "period_start", "period_end", "stockout_share", "promo_share", "recovered_share", "lift", "recovery", "cells_ranked", "tiers", "overlap_groups",
            "pairs", "pairs_overlapping"}
CRITERION = {"id", "name_es", "passed", "value", "baseline_value", "ci_low", "ci_high", "threshold_es", "seen_by_research", "seen_by_planner", "verdict_es"}


def parquet(star_export, name):
    return pd.read_parquet(star_export.out / f"{name}.parquet")


def test_the_five_files_follow_their_schema_and_stay_under_the_limit(star_export, site_files):
    site, out = site_files.site, site_files.out
    assert [p.name for p in site_files.paths] == list(SITE_FILES) and sorted(p.name for p in out.iterdir()) == sorted([*SITE_FILES, MANIFEST_FILE])
    documents = {"summary.json": site.summary, "data.json": site.data, "algorithms.json": site.algorithms, "operation.json": site.operation, "validation_rules.json": site.validation_rules}
    total = 0
    for name, document in documents.items():
        assert set(document) == ENVELOPE | KEYS[name], name
        raw = (out / name).read_bytes()
        total += len(raw)
        assert raw.decode("utf-8") == json.dumps(document, ensure_ascii=False, sort_keys=True, indent=1) + "\n" and not re.search(rb":\s*-?(NaN|Infinity)", raw)
        assert document["schema_version"] == 1 and document["run_key"] == "run-close" and document["as_of"] == "2024-07-03 00:00:00" and "CC BY 4.0" in document["attribution"]
        assert document["train_sha256"] == star_export.view.train_sha256_seen and document["eval_sha256"] == star_export.view.eval_sha256_seen
    assert total <= 200 * 1024 and total <= star_export.cfg.site.max_total_bytes
    assert set(site.manifest) == ENVELOPE | {"files"} and set(site.manifest["files"]) == set(SITE_FILES) and verify_site(out) == []
    summary = site.summary
    assert set(summary["headline"]) == HEADLINE and set(summary["headline"]["lift"]) == {"naive", "raw", "recovered"} and set(summary["headline"]["lift"]["raw"]) == {"value", "ci_low", "ci_high"}
    assert len(summary["criteria"]) == 10 and all(set(c) == CRITERION for c in summary["criteria"]) and [c["id"] for c in summary["criteria"]] == [f"C{k:02d}" for k in range(1, 11)]
    assert summary["evaluation_status"] == "sealed" and set(summary["seal"]) == {"config_sha256", "launch_run_key", "test_run_key", "test_as_of"} and summary["status"] == "ok"
    data = site.data
    assert any(round(v, 2) != v for v in data["hour_profile"]["mean_sales"]) and all(round(v, 4) == v for v in data["hour_profile"]["mean_sales"])        # four decimals, as the plan says
    assert len(data["hour_profile"]["hour"]) == 24 == len(data["hour_profile"]["mean_sales"]) == len(data["hour_profile"]["stockout_rate"])
    assert len(data["first_stockout"]["hour"]) == 16 == len(data["first_stockout"]["share"]) and abs(sum(data["first_stockout"]["share"]) - 1.0) < 0.02
    assert set(data["day_states"]) == {"shares", "counts"} and [b["bin"] for b in data["discount_bins"]] == list(range(7)) and [s["block"] for s in data["split"]] == ["train", "purge", "valid_v1", "valid_v2", "test"]
    assert set(data["anomalies"]) == {"discount_zero", "discount_over_one", "deep_band", "flag_without_cut", "cut_without_flag"} and set(data["hierarchy"]) == {"stores", "cities", "products", "groups", "first_categories"}
    algorithms = site.algorithms
    assert len(algorithms["bands"]) == 7 and len(algorithms["groups"]) == 7 and len(algorithms["cells"]) == 49 and len(algorithms["example_day"]["hour"]) == 16
    assert set(algorithms["cells"][0]) == {"cell", "group", "band", "raw", "recovered", "ci_low", "ci_high", "series", "ranked", "rank", "tier", "overlap_group"} and set(algorithms["bands"][0]) == {
        "band", "label_es", "raw", "recovered", "ci_low", "ci_high", "series", "unflagged"}
    assert set(algorithms["intervals"]) == {"two_way_median_width", "series_only_median_width", "pairs", "overlapping_two_way", "overlapping_series_only"} and set(algorithms["leakage"]) == {
        "sale_amount_recovery_wape", "sealed_wape", "note_es"}
    operation = site.operation
    assert len(operation["days"]) == 7 and [m["method"] for m in operation["forecast"]] == ["f0_no_lift", "f1_naive", "f2a_overall_lift", "f2_cell_lift"] and operation["tiers_now"]
    assert set(operation["day_bands"]) == {"date", "band", "lift_recovered", "series_days"} and set(operation["days"][0]) == {"date", "promo_series_days", "stockout_rate", "lift_raw", "lift_recovered"}
    rules = site.validation_rules
    assert [r["rule_id"] for r in rules["rules"]] == list(RULES) and set(rules["totals"]) == {"series_days", "deliveries_loaded", "deliveries_rejected"}
    assert all(set(r) == {"rule_id", "name_es", "severity", "scope", "aggregation", "status", "series_days", "hours"} for r in rules["rules"])


def test_every_figure_is_the_one_of_the_parquet_files_of_the_same_run(star_export, site_files):
    site = site_files.site
    overall = parquet(star_export, "fact_overall_effect")

    def lift(version, estimator, scope="launch", control="regular"):
        row = overall[(overall["scope"] == scope) & (overall["version_key"] == version) & (overall["estimator"] == estimator) & (overall["control"] == control) & (overall["seal_state"] == "sealed")].iloc[0]
        return {"value": round(row["lift"], 3), "ci_low": None if pd.isna(row["ci_low"]) else round(row["ci_low"], 3), "ci_high": None if pd.isna(row["ci_high"]) else round(row["ci_high"], 3)}

    assert site.summary["headline"]["lift"] == {"naive": lift("raw", "naive_pooled"), "raw": lift("raw", "counterfactual"), "recovered": lift("recovered", "counterfactual")}
    assert site.algorithms["naive_vs_adjusted"]["any_flag0_control"] == lift("recovered", "counterfactual", "test", "any_flag0")
    cells = parquet(star_export, "fact_cell_effect")
    mine = cells[(cells["scope"] == "launch") & (cells["version_key"] == "recovered")].set_index("cell_key")
    assert {c["cell"] for c in site.algorithms["cells"]} == set(mine.index)
    for c in site.algorithms["cells"]:
        row = mine.loc[c["cell"]]
        assert (c["recovered"], c["ci_low"], c["ci_high"], c["series"], c["ranked"]) == (round(row["lift"], 3), round(row["ci_low"], 3), round(row["ci_high"], 3), int(row["series"]), bool(row["ranked"]))
        assert (c["rank"], c["tier"], c["overlap_group"]) == tuple(None if pd.isna(row[k]) else int(row[k]) for k in ("rank", "tier", "overlap_group"))
    summary = parquet(star_export, "fact_evaluation_summary")
    summary = summary[summary["seal_state"] == "sealed"].set_index("criterion_id")
    for c in site.summary["criteria"]:
        row = summary.loc[c["id"]]
        assert c["verdict_es"] == row["verdict_es"] and c["value"] == (None if pd.isna(row["value"]) else round(row["value"], 4)) and c["passed"] == (None if pd.isna(row["passed"]) else bool(row["passed"]))
    example = parquet(star_export, "fact_example_day")
    assert site.algorithms["example_day"]["recovered"] == [round(v, 3) for v in example["recovered"]] and site.algorithms["example_day"]["hour"] == example["hour"].tolist()
    rep = parquet(star_export, "fact_replication").set_index("cell_key")
    shown = lambda x: None if pd.isna(x) else round(x, 3)  # noqa: E731
    assert {r["cell"]: (r["launch"], r["test"]) for r in site.operation["replication"]} == {k: (shown(v.lift_launch), shown(v.lift_test)) for k, v in rep.iterrows()}
    daily = parquet(star_export, "fact_daily_cell")
    day = daily[(daily["date_key"] == 20240626) & (daily["version_key"] == "recovered")]
    assert site.operation["days"][0]["lift_recovered"] == round(day["observed"].sum() / day["counterfactual"].sum() - 1, 3) and site.operation["days"][0]["date"] == "2024-06-26"
    recovery = parquet(star_export, "fact_recovery_check")
    assert {(r["scope"], r["method"]) for r in site.algorithms["recovery"]} == set(map(tuple, recovery[(recovery["mask"] == "tail") & (recovery["seal_state"] == "sealed")][["scope", "method_key"]].to_numpy()))
    assert site.summary["headline"]["cells_ranked"] == int(mine["ranked"].sum()) and site.summary["headline"]["days"] == len(parquet(star_export, "dim_date"))
    seal = read_seal(star_export.seal)
    assert site.summary["seal"] == {"config_sha256": seal["launch"]["config_sha256"], "launch_run_key": seal["launch"]["run_key"], "test_run_key": "run-close", "test_as_of": seal["test"]["as_of"]}
    assert site.data["first_stockout"]["share"] == [round(p, 3) for p in seal["launch"]["recovery"]["pmf"]]


def test_cumulative_rules_are_read_once_from_the_latest_loaded_run(star_export, launch_config, tmp_path):
    """A rule that counts something cumulative (``source`` and ``latest``) is read once, from the latest loaded run that recorded it; a ``per_run`` rule is summed over the loaded runs."""
    w = clone(star_export.folder, tmp_path / "rules", launch_config, star_export.view.train_sha256_seen, star_export.view.eval_sha256_seen)
    assert RULES["V01"].aggregation is Aggregation.SOURCE and RULES["M01"].aggregation is Aggregation.LATEST and RULES["V20"].aggregation is Aggregation.PER_RUN
    w.conn.execute("DELETE FROM validation_results")
    for run, series_days in (("run-L2024-06-25", 100), ("run-D2024-06-26", 130), ("run-D2024-06-27", 160)):
        for rule, severity in (("V01", "blocking"), ("M01", "blocking"), ("V20", "warning")):
            w.conn.execute("INSERT INTO validation_results VALUES (?, ?, 'x', ?, 'delivery', 'per_run', 1, ?, ?, '[]')", (run, rule, severity, series_days, series_days * 16))
    out = tmp_path / "site"
    export_site(w.conn, out, star_export.run, w.view, seal_path=w.seal, max_total_bytes=star_export.cfg.site.max_total_bytes)
    rules = {r["rule_id"]: r for r in read_site(out).validation_rules["rules"]}
    assert (rules["V01"]["series_days"], rules["V01"]["hours"]) == (160, 160 * 16) and (rules["M01"]["series_days"], rules["M01"]["hours"]) == (160, 160 * 16)      # the latest run, once
    assert (rules["V20"]["series_days"], rules["V20"]["status"]) == (100 + 130 + 160, "pass") and rules["V10"]["status"] == "not_evaluated" and rules["V01"]["status"] == "pass"
    w.conn.execute("UPDATE validation_results SET passed = 0 WHERE run_key = 'run-D2024-06-27' AND rule_id IN ('V01', 'V20')")
    export_site(w.conn, out, star_export.run, w.view, seal_path=w.seal, max_total_bytes=star_export.cfg.site.max_total_bytes)
    rules = {r["rule_id"]: r for r in read_site(out).validation_rules["rules"]}
    assert rules["V01"]["status"] == "fail" and rules["V20"]["status"] == "warn"
    assert read_site(out).validation_rules["totals"] == {"series_days": w.conn.execute("SELECT COUNT(*) FROM series_days").fetchone()[0], "deliveries_loaded": 9, "deliveries_rejected": 0}
    w.conn.close()


def test_a_failure_in_the_middle_of_the_writes_leaves_a_set_that_is_refused(star_export, launch_config, tmp_path, monkeypatch):
    w = clone(star_export.folder, tmp_path / "failing", launch_config, star_export.view.train_sha256_seen, star_export.view.eval_sha256_seen)
    out, cap = tmp_path / "site", star_export.cfg.site.max_total_bytes
    export_site(w.conn, out, star_export.run, w.view, seal_path=w.seal, max_total_bytes=cap)
    assert verify_site(out) == []
    real, calls = site_export.write_atomic, []

    def failing(path, data):
        calls.append(Path(path).name)
        if len(calls) == 3:
            raise OSError("disk full")
        return real(path, data)

    monkeypatch.setattr(site_export, "write_atomic", failing)
    with pytest.raises(OSError, match="disk full"):
        export_site(w.conn, out, RunMeta("run-again", star_export.run.as_of), w.view, seal_path=w.seal, max_total_bytes=cap)
    assert not (out / MANIFEST_FILE).exists() and MANIFEST_FILE not in calls
    assert "falta manifest.json" in verify_site(out)[0]
    with pytest.raises(SiteSetError, match="manifest.json"):
        read_site(out)
    monkeypatch.undo()
    export_site(w.conn, out, RunMeta("run-again", star_export.run.as_of), w.view, seal_path=w.seal, max_total_bytes=cap)
    assert verify_site(out) == [] and read_site(out).summary["run_key"] == "run-again"
    # a mixed set: one file of another export, or an envelope that is not the manifest's, is refused
    other = tmp_path / "other"
    export_site(w.conn, other, star_export.run, w.view, seal_path=w.seal, max_total_bytes=cap)
    shutil.copyfile(other / "data.json", out / "data.json")
    assert any("data.json" in p for p in verify_site(out)) and not verify_site(other)
    with pytest.raises(SiteSetError):
        read_site(out)
    # a file whose envelope is not the manifest's is refused even if its manifest line is rewritten to match
    document = json.loads((out / "data.json").read_text(encoding="utf-8"))
    document["run_key"] = "run-someone-else"
    text = json.dumps(document, ensure_ascii=False, sort_keys=True, indent=1) + chr(10)
    (out / "data.json").write_bytes(text.encode("utf-8"))
    manifest = json.loads((out / MANIFEST_FILE).read_text(encoding="utf-8"))
    manifest["files"]["data.json"] = {"bytes": len(text.encode("utf-8")), "sha256": __import__("hashlib").sha256(text.encode("utf-8")).hexdigest()}
    (out / MANIFEST_FILE).write_text(json.dumps(manifest), encoding="utf-8")
    assert verify_site(out) == ["data.json no lleva el envoltorio de manifest.json (la corrida, el instante o la fuente son otros)"]
    (out / "extra.json").write_text("{}", encoding="utf-8")
    export_site(w.conn, out, RunMeta("run-again", star_export.run.as_of), w.view, seal_path=w.seal, max_total_bytes=cap)
    assert verify_site(out) == []
    w.conn.close()


def test_the_size_limit_refuses_before_anything_is_replaced(star_export, launch_config, tmp_path):
    w = clone(star_export.folder, tmp_path / "limit", launch_config, star_export.view.train_sha256_seen, star_export.view.eval_sha256_seen)
    out = tmp_path / "site"
    export_site(w.conn, out, star_export.run, w.view, seal_path=w.seal, max_total_bytes=star_export.cfg.site.max_total_bytes)
    before = {p.name: p.read_bytes() for p in out.iterdir()}
    with pytest.raises(SiteExportError, match="el tope es 1000"):
        export_site(w.conn, out, RunMeta("run-big", star_export.run.as_of), w.view, seal_path=w.seal, max_total_bytes=1000)
    assert {p.name: p.read_bytes() for p in out.iterdir()} == before
    size = sum(len(v) for k, v in before.items() if k != MANIFEST_FILE)
    export_site(w.conn, out, star_export.run, w.view, seal_path=w.seal, max_total_bytes=size)                    # exactly the limit is allowed...
    with pytest.raises(SiteExportError, match=f"el tope es {size - 1}"):
        export_site(w.conn, out, star_export.run, w.view, seal_path=w.seal, max_total_bytes=size - 1)           # ...one byte over is not
    assert {p.name: p.read_bytes() for p in out.iterdir()} == before
    w.conn.execute("DROP TABLE star_fact_leakage")
    with pytest.raises(SiteExportError, match="star_fact_leakage"):
        export_site(w.conn, out, star_export.run, w.view, seal_path=w.seal, max_total_bytes=star_export.cfg.site.max_total_bytes)
    assert {p.name: p.read_bytes() for p in out.iterdir()} == before
    w.conn.close()


def test_every_star_table_the_queries_name_is_required_and_exists_in_the_model():
    named = set(re.findall(r"\bstar_(?:dim|fact)_\w+", Path(site_export.__file__).read_text(encoding="utf-8")))
    assert named == set(REQUIRED_STAR) and {n.removeprefix("star_") for n in REQUIRED_STAR} <= {t.name for t in MODEL.tables}


def test_nothing_of_the_test_week_is_published_before_it_is_sealed(issued_week, launch_config, tmp_path):
    w = clone(issued_week.folder, tmp_path / "pending", launch_config, issued_week.train, issued_week.eval)
    export_star_schema(w.conn, tmp_path / "powerbi", MODEL, issued_week.run, w.view, seal_path=w.seal, interim_dir=w.cfg.paths.interim_dir)
    out = tmp_path / "site"
    export_site(w.conn, out, issued_week.run, w.view, seal_path=w.seal, max_total_bytes=w.cfg.site.max_total_bytes)
    site = read_site(out)
    assert site.summary["evaluation_status"] == "pending" and all(c["passed"] is None and c["value"] is None and c["verdict_es"].startswith("Pendiente") for c in site.summary["criteria"])
    assert site.operation["replication"] == [] and all(m["wape"] is None and m["bias"] is None and m["valid_wape"] is not None for m in site.operation["forecast"])
    assert all(r["scope"] != "test" for r in site.algorithms["recovery"]) and site.algorithms["naive_vs_adjusted"]["any_flag0_control"] == {"value": None, "ci_low": None, "ci_high": None}
    assert site.algorithms["intervals"]["series_only_median_width"] is None and site.algorithms["intervals"]["overlapping_series_only"] is None and site.algorithms["intervals"]["pairs"] is not None
    assert len(site.operation["days"]) == 7 and "sealed_from" not in site.summary           # the days that were issued are tracking, not evaluation
    w.conn.close()


def test_a_post_seal_analysis_never_changes_what_the_site_says_of_the_sealed_one(star_export, site_files, evaluated_week, launch_config, tmp_path):
    w = clone(star_export.folder, tmp_path / "post", launch_config, evaluated_week.view.train_sha256_seen, evaluated_week.view.eval_sha256_seen)
    view = sealed_view(with_key(w.cfg, "ranking.min_series"), evaluated_week.view.train_sha256_seen, evaluated_week.view.eval_sha256_seen)
    assert evaluate(w.conn, w.cube, evaluated_week.bundle, replace(evaluated_week.run, run_key="run-post"), view, seal_path=w.seal)["test"] == "post_seal"
    assert w.conn.execute("SELECT COUNT(*) FROM eval_criteria WHERE seal_state = 'post_seal'").fetchone()[0] == 10
    export_star_schema(w.conn, tmp_path / "powerbi", MODEL, star_export.run, w.view, seal_path=w.seal, interim_dir=w.cfg.paths.interim_dir)
    assert "post_seal" in set(pd.read_parquet(tmp_path / "powerbi" / "fact_evaluation_summary.parquet")["seal_state"])
    out = tmp_path / "site"
    export_site(w.conn, out, star_export.run, w.view, seal_path=w.seal, max_total_bytes=w.cfg.site.max_total_bytes)
    mine = read_site(out)
    for name in ("summary", "data", "algorithms", "operation", "validation_rules"):
        assert getattr(mine, name) == getattr(site_files.site, name), name
    w.conn.close()


def test_figures_of_another_configuration_than_the_sealed_one_are_not_published_as_if_they_were_sealed(star_export, launch_config, tmp_path):
    """When the registered model is not the one of the seal, its launch figures are ``post_seal`` in the star model and the site shows none of them: only the sealed state is published."""
    import json as json_module

    w = clone(star_export.folder, tmp_path / "other_seal", launch_config, star_export.view.train_sha256_seen, star_export.view.eval_sha256_seen)
    document = json_module.loads(w.seal.read_text(encoding="utf-8"))
    document["launch"]["config_sha256"] = "e" * 64
    w.seal.write_text(json_module.dumps(document), encoding="utf-8")
    export_star_schema(w.conn, tmp_path / "powerbi", MODEL, star_export.run, w.view, seal_path=w.seal, interim_dir=w.cfg.paths.interim_dir)
    out = tmp_path / "site"
    export_site(w.conn, out, star_export.run, w.view, seal_path=w.seal, max_total_bytes=w.cfg.site.max_total_bytes)
    site = read_site(out)
    assert site.algorithms["cells"] == [] and site.algorithms["groups"] == [] and site.operation["tiers_now"] == [] and site.summary["headline"]["cells_ranked"] == 0
    assert site.summary["headline"]["lift"] == {k: {"value": None, "ci_low": None, "ci_high": None} for k in ("naive", "raw", "recovered")}
    assert all(b["raw"] is None and b["recovered"] is None for b in site.algorithms["bands"]) and [r for r in site.algorithms["recovery"] if r["scope"] != "test"] == []
    w.conn.close()
