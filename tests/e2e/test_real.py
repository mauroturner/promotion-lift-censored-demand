"""The real files (``real_data``; not in the default suite). Until U19, no test here reads ``eval.parquet`` beyond its size, its hash and its
schema, and none goes past the launch (D17): U04's part reads ``train.parquet`` only.

U19's part (the last two tests) checks what the complete real replay left. It reads outputs and starts no run: the first evaluation of the test week is that replay itself
(D17), made once. Without the outputs those tests fail (they do not skip) and say which file is missing."""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
import pytest

from promolift import registry
from promolift.days import ANOMALOUS, PROMO, REGULAR, UNFLAGGED, band_of, day_state
from promolift.evaluation import criteria_from_seal
from promolift.export import verify_star_schema
from promolift.ingest import check_source, read_source
from promolift.schema import SOURCE_SCHEMA
from promolift.site_export import read_site, verify_site
from promolift.sysinfo import POSIX_COUNTER, WINDOWS_COUNTER
from tests.conftest import REAL_EVAL, REAL_TRAIN

pytestmark = pytest.mark.real_data


@pytest.fixture(scope="module")
def real_train(cfg):
    return read_source(REAL_TRAIN, "train", cfg)


def test_the_real_files_have_the_accepted_sizes_and_hashes_and_the_eval_file_is_only_checked_that_way(cfg):
    assert check_source(cfg) == (cfg.source.train_sha256, cfg.source.eval_sha256)
    assert pq.read_schema(REAL_EVAL).remove_metadata().equals(SOURCE_SCHEMA)
    assert pq.ParquetFile(REAL_EVAL).metadata.num_rows == 350_000, "the row count comes from the footer: no value of the file is read"


def test_the_strict_read_of_the_real_train_file_finds_what_research_and_the_planner_measured(real_train, cfg):
    frames, report = real_train
    assert (report.rows, report.series, report.days) == (4_500_000, 50_000, 90)
    assert (report.first_day.isoformat(), report.last_day.isoformat()) == ("2024-03-28", "2024-06-25")
    assert (report.sale_amount_mismatch, report.stock_count_mismatch) == (0, 0), "sale_amount and stock_hour6_22_cnt are the sums of the hours (research.md, s01)"
    assert frames.sales.shape == (4_500_000, 24) and float(frames.sales.max()) <= cfg.source.max_hourly_sale
    assert frames.ids["management_group_id"].nunique() == 7 and frames.ids["store_id"].nunique() == 898 and frames.ids["product_id"].nunique() == 865


def test_the_day_states_of_the_real_train_file_are_the_planners_percentages(real_train, cfg):
    frames, _report = real_train
    states = day_state(frames.flag, frames.discount, cfg)
    share = {name: float((states == code).mean()) for name, code in (("promo", PROMO), ("regular", REGULAR), ("unflagged_cut", UNFLAGGED), ("anomalous", ANOMALOUS))}
    assert {k: round(v * 100, 2) for k, v in share.items()} == {"promo": 37.84, "regular": 47.69, "unflagged_cut": 14.11, "anomalous": 0.36}
    assert int((frames.discount == 0).sum()) == 16_039 and int((frames.discount > 1).sum()) == 34
    assert int(((frames.discount > 0) & (frames.discount < 0.5)).sum()) == 15_886
    assert int(((frames.flag == 1) & (frames.discount == 1.0)).sum()) == 38_378
    assert int((frames.discount == 1.0).sum()) == 2_181_121, "the discount of a day with no cut is exactly 1.0 (p01)"
    bands = band_of(frames.discount, cfg)
    assert set(np.unique(bands[states == PROMO])) == set(range(7))
    # the bands of every row with 0 < discount <= 1: research.md's table had [15886, 78127, 207326, 429102, 847707, 411689] before the 3,338 rows
    # that hold a float32 neighbour of 0.7, 0.8, 0.9 or 0.95 went to the band their clean twins are in (D13's note of 2026-11-17)
    assert np.bincount(bands[bands >= 0], minlength=7).tolist() == [15886, 78127, 207268, 429131, 845609, 412692, 2495214]
    noisy = (frames.discount != 0.9) & (np.abs(frames.discount - 0.9) < 1e-6)
    assert int(noisy.sum()) == 2127 and set(np.unique(bands[noisy])) == {5} and set(np.unique(bands[frames.discount == 0.9])) == {5}


# --- U19: what the complete real replay left (AC03, AC04, AC34, AC35) -----------------------------------------------------------------------------------------------------------

SERIES, LAUNCH_DAYS, DAILY_RUNS, SERIES_DAYS, STORES, PRODUCTS, GROUPS = 50_000, 90, 7, 4_850_000, 898, 865, 7
LAUNCH_SHARES = {"promo": 37.84, "regular": 47.69, "unflagged_cut": 14.11, "anomalous": 0.36}   # requirements.md, section 4 (train.parquet)
MAX_PEAK_WORKING_SET_MB, MAX_TOTAL_S, MAX_LAUNCH_S, MAX_DAILY_S, MAX_PARQUET_BYTES = 12 * 1024, 20 * 60, 12 * 60, 60, 25 * 1024 * 1024   # RNF02, RNF03, AC34
STAR_PARQUETS = 25


def require(path: Path) -> Path:
    assert path.is_file(), f"falta {path.name}: la repetición real completa no corrió (python -m promolift replay)"
    return path


def seconds(started: str, finished: str) -> float:
    return (datetime.fromisoformat(finished) - datetime.fromisoformat(started)).total_seconds()


@pytest.fixture(scope="module")
def outputs(cfg):
    paths = cfg.paths
    seal_path, summary_path = require(Path(paths.seal)), require(Path(paths.reports_dir) / "evaluation_summary.json")
    warehouse = require(Path(paths.warehouse))
    read = {"seal": json.loads(seal_path.read_text(encoding="utf-8")), "summary": json.loads(summary_path.read_text(encoding="utf-8")),
            "site": read_site(Path(paths.site_dir)), "seal_path": seal_path, "powerbi": Path(paths.outputs_dir)}
    conn = sqlite3.connect(f"{warehouse.as_uri()}?mode=ro", uri=True)
    try:
        yield {"conn": conn, **read}
    finally:
        conn.close()


def _runs(conn):
    return conn.execute("SELECT p.run_key, p.started_at, p.finished_at, p.status, p.peak_working_set_mb, p.memory_counter, d.kind, p.delivery_id FROM pipeline_runs p "
                        "LEFT JOIN deliveries d ON d.delivery_id = p.delivery_id ORDER BY p.started_at").fetchall()


def test_real_counts_seal_and_summary_consistency(cfg, outputs):
    conn, seal, summary, site = outputs["conn"], outputs["seal"], outputs["summary"], outputs["site"]

    # AC03: the series and series-days of the files, by delivery, in the warehouse and on the site
    assert conn.execute("SELECT COUNT(*) FROM series").fetchone()[0] == SERIES
    assert conn.execute("SELECT COUNT(*), COUNT(DISTINCT store_id), COUNT(DISTINCT product_id), COUNT(DISTINCT management_group_id) FROM series").fetchone() == (SERIES, STORES, PRODUCTS, GROUPS)
    assert conn.execute("SELECT COUNT(*) FROM series_days").fetchone()[0] == SERIES_DAYS
    assert conn.execute("SELECT COUNT(DISTINCT date_key) FROM series_days WHERE date_key <= 20240625").fetchone()[0] == LAUNCH_DAYS
    deliveries = conn.execute("SELECT d.delivery_id, d.kind, d.series_days, COUNT(s.series_key), d.status FROM deliveries d LEFT JOIN series_days s USING (delivery_id) "
                              "GROUP BY d.delivery_id ORDER BY CASE d.kind WHEN 'launch' THEN 0 WHEN 'daily' THEN 1 ELSE 2 END, d.delivery_id").fetchall()
    assert [d[1] for d in deliveries] == ["launch"] + ["daily"] * DAILY_RUNS + ["close"] and {d[4] for d in deliveries} == {"loaded"}
    assert [(d[2], d[3]) for d in deliveries] == [(SERIES * LAUNCH_DAYS,) * 2] + [(SERIES, SERIES)] * DAILY_RUNS + [(0, 0)]

    # AC04: the day states of the launch days are the planner's percentages (requirements.md, section 4), now counted in SQL
    states = dict(conn.execute("SELECT day_state, COUNT(*) FROM series_days WHERE date_key <= 20240625 GROUP BY 1"))
    shares = {name: round(100 * count / (SERIES * LAUNCH_DAYS), 2) for name, count in states.items()}
    assert shares == LAUNCH_SHARES

    # The seal: both parts, one configuration, the pinned files, and the same ten criteria in the seal, the summary and the site (D17, D21)
    assert set(seal) == {"version", "launch", "test"} and seal["test"] is not None
    launch, test = seal["launch"], seal["test"]
    fingerprint = registry.config_fingerprint(registry.sealed_view(cfg, cfg.source.train_sha256, cfg.source.eval_sha256))
    assert launch["config_sha256"] == test["config_sha256"] == fingerprint == summary["seal"]["config_sha256"] == site.summary["seal"]["config_sha256"]
    assert launch["train_sha256"] == cfg.source.train_sha256 == summary["train_sha256"] and launch["eval_sha256"] == cfg.source.eval_sha256 == summary["eval_sha256"]
    assert registry.seal_state(outputs["seal_path"], fingerprint) == "match"
    assert launch["as_of"] == "2024-06-26 00:00:00" and test["as_of"] == "2024-07-03 00:00:00"
    sealed = criteria_from_seal(seal)
    assert [c.criterion_id for c in sealed] == [f"C{n:02d}" for n in range(1, 11)] == [c["id"] for c in test["criteria"]]
    assert summary["evaluation_status"] == site.summary["evaluation_status"] == "sealed" and summary["post_seal"] is None
    assert [c["criterion_id"] for c in summary["criteria"]] == [c["id"] for c in site.summary["criteria"]] == [c.criterion_id for c in sealed]
    for criterion, in_summary, on_site, in_seal in zip(sealed, summary["criteria"], site.summary["criteria"], test["criteria"], strict=True):
        assert in_summary["verdict_es"] == on_site["verdict_es"] == in_seal["verdict_es"] == criterion.verdict_es, criterion.criterion_id
        assert in_summary["passed"] == on_site["passed"] == in_seal["passed"] == criterion.passed, criterion.criterion_id
    assert [site.summary["seal"][key] for key in ("launch_run_key", "test_run_key")] == [launch["run_key"], test["run_key"]]

    # The runs: the launch, the seven daily deliveries and the close, each ok and in order, then the runs without a delivery
    runs = _runs(conn)
    assert [r[6] for r in runs[:9]] == ["launch"] + ["daily"] * DAILY_RUNS + ["close"] and {r[3] for r in runs[:9]} == {"ok"}
    assert len(runs) > 9 and {r[3] for r in runs[9:]} == {"no_delivery"}, "the run without a delivery follows the nine runs of the replay (RNF02)"
    assert runs[8][0] == summary["run_key"] == site.summary["run_key"] and conn.execute("SELECT COUNT(*) FROM deliveries WHERE status != 'loaded'").fetchone()[0] == 0

    # AC34 (RNF02, RNF03): times from the records of the runs; the peak of the working set with its counter named; every Parquet within its size
    assert not verify_site(Path(cfg.paths.site_dir)) and not verify_star_schema(outputs["powerbi"])
    assert sum(seconds(r[1], r[2]) for r in runs) <= MAX_TOTAL_S, "la repetición completa con la corrida sin entrega pasa de 20 min (RNF02)"
    assert seconds(runs[0][1], runs[0][2]) <= MAX_LAUNCH_S, "el lanzamiento pasa de 12 min (RNF02)"
    counter = WINDOWS_COUNTER if sys.platform == "win32" else POSIX_COUNTER
    assert {r[5] for r in runs[:9]} == {counter} and max(r[4] for r in runs[:9]) <= MAX_PEAK_WORKING_SET_MB, f"el pico de {counter} pasa de 12 GB (RNF03)"
    parquets = sorted(outputs["powerbi"].glob("*.parquet"))
    assert len(parquets) == STAR_PARQUETS and max(p.stat().st_size for p in parquets) <= MAX_PARQUET_BYTES

    # RNF12: nothing published carries a path of this machine or the name of its user
    published = [*Path(cfg.paths.site_dir).glob("*.json"), *parquets, Path(cfg.paths.reports_dir) / "evaluation_summary.json", Path(cfg.paths.reports_dir) / "evaluation_summary.md",
                 outputs["seal_path"], Path(cfg.paths.dashboard_html), outputs["powerbi"] / "manifest.json"]
    for path in published:
        data = require(path).read_bytes()
        assert b":\\Users" not in data and b"C:\\" not in data and b"/Users/" not in data and b"mauro" not in data.lower(), path.name


def test_every_daily_run_takes_at_most_the_required_seconds(outputs):
    """RNF02: a daily run (its eleven tasks, from the run record) takes at most 60 s. Kept apart so that a miss of this one limit does not hide what the other test checks."""
    runs = _runs(outputs["conn"])
    assert [r[6] for r in runs[1:8]] == ["daily"] * DAILY_RUNS
    assert [round(seconds(r[1], r[2])) for r in runs[1:8] if seconds(r[1], r[2]) > MAX_DAILY_S] == [], "una corrida diaria pasa de 60 s (RNF02)"


def test_a_rebuild_from_the_seal_compares_what_the_seal_fixes(cfg, outputs):
    """A1 of project 05's evaluation: a rebuild with the seal in place gives its runs their own keys and leaves the seal as it was, so the seal's run keys are those of the
    warehouse only when this warehouse wrote it. What the seal fixes (the configuration, the files, the instants and the ten criteria) is compared in every case, and the criteria are
    this warehouse's own sealed evaluation, not a copy taken from the seal (AC19, AC35)."""
    conn, seal, summary = outputs["conn"], outputs["seal"], outputs["summary"]
    launch, test = seal["launch"], seal["test"]
    runs = _runs(conn)
    assert summary.get("sealed_from") != "seal", "the summary took the criteria from the seal: this warehouse holds no sealed evaluation of its own"
    own = conn.execute("SELECT criterion_id, passed, verdict_es FROM eval_criteria WHERE seal_state = 'sealed' ORDER BY criterion_id").fetchall()
    fixed = [(c["id"], None if c["passed"] is None else int(c["passed"]), c["verdict_es"]) for c in test["criteria"]]   # C10 has no threshold
    assert [tuple(r) for r in own] == sorted(fixed), "the sealed rows of this warehouse give the ten criteria the seal fixes"
    assert registry.config_fingerprint(registry.sealed_view(cfg, cfg.source.train_sha256, cfg.source.eval_sha256)) == launch["config_sha256"] == test["config_sha256"]
    assert (launch["as_of"], test["as_of"]) == ("2024-06-26 00:00:00", "2024-07-03 00:00:00")
    if runs[0][0] == launch["run_key"]:
        assert runs[8][0] == test["run_key"], "the warehouse that wrote the launch part of the seal wrote its test part too"
    else:
        assert runs[8][0] != test["run_key"], "a rebuilt warehouse has its own run keys, and the seal keeps those of the run that wrote it"
