"""The five small JSON files that the personal site copies (RF22, AC26; D36; plan, section 21). Adapted from project 05's ``site_export.py``.

``export_site`` writes ``summary.json``, ``data.json``, ``algorithms.json``, ``operation.json`` and ``validation_rules.json`` to the site folder from the star model (the ``star_*``
tables that ``export.build_powerbi_marts`` built, the very rows the Parquet files hold, so a figure on the site is the figure in the report), from the summary of the run
(``reporting.build_summary``, which takes the sealed criteria from the seal when the warehouse has none), from the seal and from the validation of each run. Until the test is sealed
with this configuration every result of the test is empty or ``null``: the star model hides the test week before it closed and this module shows only sealed rows.

The files are a contract that another repository consumes (item 3 of the risk list): a change of shape is a change of ``tests/contract/test_site_export.py``. Floats are rounded to what
the site shows; every file is ``json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=1)`` with a final newline, and the five together stay under ``max_total_bytes`` (``[site]``).

The five files are one export: each is replaced atomically and ``manifest.json``, written last, names each with its size and SHA-256. The old manifest is removed before the first file is
replaced, so a failure between two replacements leaves a folder with no manifest, which ``verify_site`` refuses; a reader takes the files through ``read_site``. A rule that counts
something cumulative (``source`` and ``latest``) is read once, from the latest loaded run that recorded it, and never summed over the runs (project 03, D94).
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from promolift import texts
from promolift.cube import ATTRIBUTION
from promolift.days import band_of
from promolift.files import write_atomic
from promolift.forecast import METHODS as FORECAST_METHODS
from promolift.leakage_demo import NOTES_ES
from promolift.registry import RunMeta, read_seal
from promolift.reporting import build_summary
from promolift.schema import date_key
from promolift.validate import RULES, Aggregation, Severity

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
SITE_FILES = ("summary.json", "data.json", "algorithms.json", "operation.json", "validation_rules.json")
MANIFEST_FILE = "manifest.json"
ENVELOPE = ("schema_version", "run_key", "as_of", "train_sha256", "eval_sha256", "attribution")
# Every table of the star model the export reads: the one list ``_require_star`` checks before anything is built (a test compares it with the tables the queries of this module name).
REQUIRED_STAR = ("star_dim_cell", "star_dim_date", "star_fact_band_effect", "star_fact_cell_effect", "star_fact_daily_cell", "star_fact_data_quality", "star_fact_example_day",
                 "star_fact_forecast", "star_fact_group_effect", "star_fact_hour_profile", "star_fact_leakage", "star_fact_overall_effect", "star_fact_recovery_check",
                 "star_fact_replication")
STATUS_WORST_FIRST = ("fail", "warn", "pass")


class SiteExportError(RuntimeError):
    """The site files cannot be written from this warehouse; nothing was replaced."""


class SiteSetError(FileNotFoundError):
    """The files of a site folder are not one export: one is missing or is not the file ``manifest.json`` names, or the manifest is."""


@dataclass(frozen=True)
class SiteFiles:
    """The five documents of a verified site folder and its manifest, parsed from the bytes that were checked against it."""

    summary: dict[str, Any]
    data: dict[str, Any]
    algorithms: dict[str, Any]
    operation: dict[str, Any]
    validation_rules: dict[str, Any]
    manifest: dict[str, Any]


# --- values -------------------------------------------------------------------------------------------------------------------------


def _num(value: Any, decimals: int) -> float | None:
    if value is None or pd.isna(value) or (isinstance(value, float) and not math.isfinite(value)):
        return None
    return round(float(value), decimals)


def _int(value: Any) -> int | None:
    return None if value is None or pd.isna(value) else int(value)


def _query(conn: sqlite3.Connection, sql: str, params: tuple | dict = ()) -> pd.DataFrame:
    return pd.read_sql_query(sql, conn, params=params)


def _require_star(conn: sqlite3.Connection) -> None:
    present = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    missing = [t for t in REQUIRED_STAR if t not in present]
    if missing:
        raise SiteExportError(f"faltan las tablas del modelo estrella {missing}: la tarea export las construye antes de escribir el sitio")


def _header(run: RunMeta, view: Any) -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "run_key": run.run_key, "as_of": run.as_of.strftime("%Y-%m-%d %H:%M:%S"), "train_sha256": view.train_sha256_seen,
            "eval_sha256": view.eval_sha256_seen, "attribution": ATTRIBUTION}


def _estimate(row: pd.Series | None) -> dict[str, float | None]:
    return {"value": None if row is None else _num(row["lift"], 3), "ci_low": None if row is None else _num(row["ci_low"], 3), "ci_high": None if row is None else _num(row["ci_high"], 3)}


def _overall(conn: sqlite3.Connection, scope: str, version: str, estimator: str, control: str) -> pd.Series | None:
    rows = _query(conn, "SELECT lift, ci_low, ci_high FROM star_fact_overall_effect WHERE scope = ? AND version_key = ? AND estimator = ? AND control = ? AND seal_state = 'sealed'",
                  (scope, version, estimator, control))
    return rows.iloc[0] if len(rows) else None


def _launch_cells(conn: sqlite3.Connection, version: str) -> pd.DataFrame:
    return _query(conn, "SELECT cell_key, lift, ci_low, ci_high, series, series_days, ranked, rank, tier FROM star_fact_cell_effect WHERE scope = 'launch' AND version_key = ? "
                        "AND ci_kind = 'two_way' AND seal_state = 'sealed' ORDER BY cell_key", (version,))


def _split_cell(cell: str) -> tuple[int, int]:
    group, band = cell[1:].split("-b")
    return int(group), int(band)


def _iso(key: int) -> str:
    text = str(int(key))
    return f"{text[:4]}-{text[4:6]}-{text[6:]}"


def _counts(conn: sqlite3.Connection) -> dict[str, Any]:
    row = conn.execute("SELECT COUNT(*), COUNT(DISTINCT store_id), COUNT(DISTINCT city_id), COUNT(DISTINCT product_id), COUNT(DISTINCT management_group_id), "
                       "COUNT(DISTINCT first_category_id) FROM series").fetchone()
    return dict(zip(("series", "stores", "cities", "products", "groups", "first_categories"), row, strict=True))


# --- summary.json ----------------------------------------------------------------------------------------------------------------------


def _summary(conn: sqlite3.Connection, run: RunMeta, view: Any, summary: dict[str, Any], seal: dict[str, Any] | None) -> dict[str, Any]:
    counts = _counts(conn)
    dates = _query(conn, "SELECT date FROM star_dim_date ORDER BY date_key")["date"]
    state = _query(conn, "SELECT SUM(series_days) AS series_days, SUM(promo) AS promo, SUM(stockout_rate * series_days) AS out FROM star_fact_data_quality").iloc[0]
    recovered = conn.execute("SELECT SUM(recovered_sum), SUM(raw_sum) FROM series_days WHERE recovered_sum IS NOT NULL AND date_key <= ?", (date_key(view.calendar.launch_last_day),)).fetchone()
    launch = seal["launch"] if seal else {}
    pairs = launch.get("effects", {}).get("pairs", {})
    cells = _launch_cells(conn, "recovered")
    row = conn.execute("SELECT status FROM pipeline_runs WHERE run_key = ?", (run.run_key,)).fetchone()
    sealed = summary["evaluation_status"] == "sealed"
    criteria = [{"id": c["criterion_id"], "name_es": c["name_es"], "passed": c["passed"] if sealed else None, "value": _num(c["value"], 4) if sealed else None,
                 "baseline_value": _num(c["baseline_value"], 4) if sealed else None, "ci_low": _num(c["ci_low"], 4) if sealed else None, "ci_high": _num(c["ci_high"], 4) if sealed else None,
                 "threshold_es": c["threshold_es"], "seen_by_research": c["seen_by_research"], "seen_by_planner": c["seen_by_planner"], "verdict_es": c["verdict_es"]}
                for c in summary["criteria"]]
    out: dict[str, Any] = {
        "status": row[0] if row else "running", "evaluation_status": summary["evaluation_status"],
        "headline": {
            "series": counts["series"], "stores": counts["stores"], "cities": counts["cities"], "products": counts["products"], "days": int(len(dates)),
            "period_start": str(dates.iloc[0]) if len(dates) else None, "period_end": str(dates.iloc[-1]) if len(dates) else None,
            "stockout_share": _num(state["out"] / state["series_days"], 3) if state["series_days"] else None, "promo_share": _num(state["promo"] / state["series_days"], 3) if state["series_days"] else None,
            "recovered_share": _num(recovered[0] / recovered[1] - 1.0, 3) if recovered and recovered[1] else None,
            "lift": {"naive": _estimate(_overall(conn, "launch", "raw", "naive_pooled", "regular")), "raw": _estimate(_overall(conn, "launch", "raw", "counterfactual", "regular")),
                     "recovered": _estimate(_overall(conn, "launch", "recovered", "counterfactual", "regular"))},
            "recovery": {"method": launch.get("recovery", {}).get("method"), "kappa": launch.get("recovery", {}).get("kappa"), "wape_v2": _num(launch.get("recovery", {}).get("wape_v2"), 3)},
            "cells_ranked": int(cells["ranked"].sum()) if len(cells) else 0, "tiers": int(cells[cells["ranked"] == 1]["tier"].nunique()) if len(cells) else 0,
            "pairs": pairs.get("pairs"), "pairs_overlapping": pairs.get("overlapping")},
        "criteria": criteria,
        "seal": summary.get("seal") or {"config_sha256": None, "launch_run_key": None, "test_run_key": None, "test_as_of": None}}
    if summary.get("sealed_from"):
        out["sealed_from"] = summary["sealed_from"]
    return out


# --- data.json ----------------------------------------------------------------------------------------------------------------------


def _data(conn: sqlite3.Connection, view: Any, seal: dict[str, Any] | None) -> dict[str, Any]:
    first_hour, last_hour = view.calendar.day_hours
    launch_last = date_key(view.calendar.launch_last_day)
    counts = _counts(conn)
    profile = _query(conn, "SELECT hour, SUM(mean_sales * series_days) AS sold, SUM(stockout_rate * series_days) AS out, SUM(series_days) AS n FROM star_fact_hour_profile "
                           "WHERE date_key <= ? GROUP BY hour ORDER BY hour", (launch_last,))
    days = _query(conn, "SELECT discount, activity_flag, day_state FROM series_days WHERE date_key <= ?", (launch_last,))
    states = days["day_state"].value_counts()
    total = int(len(days))
    discount, flag = days["discount"].to_numpy(), days["activity_flag"].to_numpy()
    band = band_of(discount, view)
    inside = (discount > 0) & (discount <= 1.0)
    edges = tuple(float(b) for b in view.days.bands)
    bins = [{"bin": k, "label_es": texts.band_label(edges, k), "rows": int(((band == k) & inside).sum()),
             "flag_share": _num(flag[(band == k) & inside].mean(), 3) if ((band == k) & inside).any() else None} for k in range(len(edges) - 1)]
    night = ~profile["hour"].between(first_hour, last_hour)
    sold = profile["sold"].sum()
    pmf = (seal or {}).get("launch", {}).get("recovery", {}).get("pmf") or []
    return {
        "hierarchy": {k: counts[k] for k in ("stores", "cities", "products", "groups", "first_categories")},
        "hour_profile": {"hour": profile["hour"].astype(int).tolist(), "mean_sales": [_num(v / n, 4) for v, n in zip(profile["sold"], profile["n"], strict=True)],
                         "stockout_rate": [_num(v / n, 3) for v, n in zip(profile["out"], profile["n"], strict=True)]},
        "first_stockout": {"hour": list(range(first_hour, first_hour + len(pmf))), "share": [_num(p, 3) for p in pmf]},
        "day_states": {"shares": {name: _num(int(states.get(name, 0)) / total, 4) if total else None for name in ("promo", "regular", "unflagged_cut", "anomalous")},
                       "counts": {name: int(states.get(name, 0)) for name in ("promo", "regular", "unflagged_cut", "anomalous")}},
        "discount_bins": bins,
        "anomalies": {"discount_zero": int((discount <= 0).sum()), "discount_over_one": int((discount > 1.0).sum()), "deep_band": int(((band == 0) & inside).sum()),
                      "flag_without_cut": int(((flag == 1) & (discount >= view.days.regular_min_discount) & (discount <= 1.0)).sum()), "cut_without_flag": int(states.get("unflagged_cut", 0))},
        "night_share": _num(profile["sold"][night].sum() / sold, 3) if sold else None,
        "split": [{"block": name, "label_es": texts.BLOCKS_ES[name], "first": getattr(view.split, name)[0].isoformat(), "last": getattr(view.split, name)[1].isoformat(),
                   "days": (getattr(view.split, name)[1] - getattr(view.split, name)[0]).days + 1} for name in ("train", "purge", "valid_v1", "valid_v2", "test")]}


# --- algorithms.json -------------------------------------------------------------------------------------------------------------------


def _bands(conn: sqlite3.Connection, view: Any) -> list[dict[str, Any]]:
    edges = tuple(float(b) for b in view.days.bands)
    rows = _query(conn, "SELECT version_key, band_key, day_state, lift, ci_low, ci_high, series FROM star_fact_band_effect WHERE scope = 'launch' AND control = 'regular' AND seal_state = 'sealed'")
    out = []
    for k in range(len(edges) - 1):
        def pick(version: str, state: str):
            part = rows[(rows["version_key"] == version) & (rows["day_state"] == state) & (rows["band_key"] == k)]
            return part.iloc[0] if len(part) else None

        rec, raw, unflagged = pick("recovered", "promo"), pick("raw", "promo"), pick("recovered", "unflagged_cut")
        out.append({"band": k, "label_es": texts.band_label(edges, k), "raw": None if raw is None else _num(raw["lift"], 3), "recovered": None if rec is None else _num(rec["lift"], 3),
                    "ci_low": None if rec is None else _num(rec["ci_low"], 3), "ci_high": None if rec is None else _num(rec["ci_high"], 3), "series": None if rec is None else _int(rec["series"]),
                    "unflagged": None if unflagged is None else _num(unflagged["lift"], 3)})
    return out


def _algorithms(conn: sqlite3.Connection, view: Any, seal: dict[str, Any] | None) -> dict[str, Any]:
    raw, recovered = _launch_cells(conn, "raw").set_index("cell_key"), _launch_cells(conn, "recovered").set_index("cell_key")
    groups = _query(conn, "SELECT group_key, lift, ci_low, ci_high, series FROM star_fact_group_effect WHERE scope = 'launch' AND version_key = 'recovered' AND seal_state = 'sealed' ORDER BY group_key")
    cells = []
    for key, row in recovered.iterrows():
        group, band = _split_cell(str(key))
        cells.append({"cell": key, "group": group, "band": band, "raw": _num(raw["lift"].get(key), 3), "recovered": _num(row["lift"], 3), "ci_low": _num(row["ci_low"], 3),
                      "ci_high": _num(row["ci_high"], 3), "series": _int(row["series"]), "ranked": bool(row["ranked"]), "rank": _int(row["rank"]), "tier": _int(row["tier"])})
    recovery = _query(conn, "SELECT scope, method_key, fit_blocks, wape_series, bias, chosen FROM star_fact_recovery_check WHERE mask = 'tail' AND seal_state = 'sealed' ORDER BY scope, method_key")
    pairs = _query(conn, "SELECT ci_kind, pairs, overlapping, median_width FROM eval_pairs WHERE scope = 'launch'")
    two, only = pairs[pairs["ci_kind"] == "two_way"], pairs[pairs["ci_kind"] == "series_only"]
    launch_pairs = (seal or {}).get("launch", {}).get("effects", {}).get("pairs", {})
    example = _query(conn, "SELECT hour, observed, recovered, in_stock FROM star_fact_example_day ORDER BY hour")
    leak = {r.check: r.value for r in _query(conn, 'SELECT "check", value FROM star_fact_leakage').itertuples()}
    return {
        "naive_vs_adjusted": {"naive_pooled": _estimate(_overall(conn, "launch", "raw", "naive_pooled", "regular")), "raw": _estimate(_overall(conn, "launch", "raw", "counterfactual", "regular")),
                              "recovered": _estimate(_overall(conn, "launch", "recovered", "counterfactual", "regular")),
                              "any_flag0_control": _estimate(_overall(conn, "test", "recovered", "counterfactual", "any_flag0"))},
        "example_day": {"hour": example["hour"].astype(int).tolist(), "observed": [_num(v, 3) for v in example["observed"]], "recovered": [_num(v, 3) for v in example["recovered"]],
                        "in_stock": example["in_stock"].astype(int).tolist()},
        "recovery": [{"method": r.method_key, "label_es": texts.method_label(r.method_key), "scope": r.scope, "fit_blocks": r.fit_blocks, "wape_series": _num(r.wape_series, 3), "bias": _num(r.bias, 3),
                      "chosen": bool(r.chosen)} for r in recovery.itertuples()],
        "bands": _bands(conn, view),
        "groups": [{"group": int(r.group_key), "recovered": _num(r.lift, 3), "ci_low": _num(r.ci_low, 3), "ci_high": _num(r.ci_high, 3), "series": _int(r.series)} for r in groups.itertuples()],
        "cells": cells,
        "intervals": {"two_way_median_width": _num(two["median_width"].iloc[0], 3) if len(two) else None, "series_only_median_width": _num(only["median_width"].iloc[0], 3) if len(only) else None,
                      "pairs": _int(two["pairs"].iloc[0]) if len(two) else launch_pairs.get("pairs"), "overlapping_two_way": _int(two["overlapping"].iloc[0]) if len(two) else launch_pairs.get("overlapping"),
                      "overlapping_series_only": _int(only["overlapping"].iloc[0]) if len(only) else None},
        "leakage": {"sale_amount_recovery_wape": _num(leak.get("reads_daily_total"), 3), "sealed_wape": _num(leak.get("chosen"), 3), "note_es": NOTES_ES["reads_daily_total"]}}


# --- operation.json --------------------------------------------------------------------------------------------------------------------


def _operation(conn: sqlite3.Connection) -> dict[str, Any]:
    daily = _query(conn, "SELECT d.date_key, d.version_key, c.band_key, d.observed, d.counterfactual, d.series_days FROM star_fact_daily_cell AS d JOIN star_dim_cell AS c ON c.cell_key = d.cell_key")
    stock = _query(conn, "SELECT date_key, stockout_rate FROM star_fact_data_quality").set_index("date_key")["stockout_rate"]
    days = []
    for key in sorted(daily["date_key"].unique()):
        part = daily[daily["date_key"] == key]
        lift = {v: part[part["version_key"] == v][["observed", "counterfactual"]].sum() for v in ("raw", "recovered")}
        days.append({"date": _iso(key), "promo_series_days": int(part[part["version_key"] == "recovered"]["series_days"].sum()), "stockout_rate": _num(stock.get(key), 3),
                     **{f"lift_{v}": _num(lift[v]["observed"] / lift[v]["counterfactual"] - 1.0, 3) if lift[v]["counterfactual"] else None for v in ("raw", "recovered")}})
    rec = daily[daily["version_key"] == "recovered"].groupby(["date_key", "band_key"])[["observed", "counterfactual", "series_days"]].sum().reset_index()
    rec = rec[rec["counterfactual"] > 0]
    day_bands = {"date": [_iso(k) for k in rec["date_key"]], "band": rec["band_key"].astype(int).tolist(),
                 "lift_recovered": [_num(o / c - 1.0, 3) for o, c in zip(rec["observed"], rec["counterfactual"], strict=True)], "series_days": rec["series_days"].astype(int).tolist()}
    replication = _query(conn, "SELECT cell_key, lift_launch, lift_test, consistent FROM star_fact_replication WHERE seal_state = 'sealed' ORDER BY cell_key")
    forecast = _query(conn, "SELECT scope, method_key, fit_blocks, wape, bias FROM star_fact_forecast WHERE seal_state = 'sealed'")
    cells = _launch_cells(conn, "recovered")
    tiers = [{"tier": int(t), "cells": sorted(part["cell_key"]), "lift_max": _num(part["lift"].max(), 3), "lift_min": _num(part["lift"].min(), 3)} for t, part in cells[cells["ranked"] == 1].groupby("tier")]
    methods = []
    for name in FORECAST_METHODS:
        valid, test = forecast[(forecast["scope"] == "valid") & (forecast["method_key"] == name)], forecast[(forecast["scope"] == "test") & (forecast["method_key"] == name)]
        methods.append({"method": name, "label_es": texts.FORECAST_LABELS_ES[name], "wape": _num(test["wape"].iloc[0], 3) if len(test) else None, "bias": _num(test["bias"].iloc[0], 3) if len(test) else None,
                        "valid_wape": _num(valid["wape"].iloc[0], 3) if len(valid) else None, "valid_bias": _num(valid["bias"].iloc[0], 3) if len(valid) else None,
                        "valid_fit_blocks": valid["fit_blocks"].iloc[0] if len(valid) else None})
    return {"days": days, "day_bands": day_bands,
            "replication": [{"cell": r.cell_key, "launch": _num(r.lift_launch, 3), "test": _num(r.lift_test, 3), "consistent": None if pd.isna(r.consistent) else bool(r.consistent)} for r in replication.itertuples()],
            "forecast": methods, "tiers_now": tiers}


# --- validation_rules.json ----------------------------------------------------------------------------------------------------------


def _loaded_rule_rows(conn: sqlite3.Connection) -> pd.DataFrame:
    """The rule results of the runs whose delivery is loaded, with each run's instant."""
    return _query(conn, "SELECT v.rule_id, v.passed, v.severity, v.series_days_affected, v.hours_affected, d.as_of FROM validation_results AS v "
                        "JOIN deliveries AS d ON d.run_key = v.run_key AND d.status = 'loaded' ORDER BY d.as_of, v.rule_id")


def _aggregated(rows: pd.DataFrame, rule_id: str) -> pd.DataFrame:
    """The rows of `rule_id` that its ``aggregation`` counts (plan, section 6): ``source`` and ``latest`` read once, from the latest loaded run that recorded the rule (a cumulative count
    summed over the runs would count the earlier series-days again; project 03's D94), ``per_run`` every loaded run."""
    mine = rows[rows["rule_id"] == rule_id]
    if RULES[rule_id].aggregation in (Aggregation.SOURCE, Aggregation.LATEST) and len(mine):
        mine = mine[mine["as_of"] == mine["as_of"].max()]
    return mine


def _validation(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = _loaded_rule_rows(conn)
    rules = []
    for rule_id, rule in RULES.items():
        mine = _aggregated(rows, rule_id)
        found = ["pass" if bool(p) else ("fail" if s == Severity.BLOCKING.value else "warn") for p, s in zip(mine["passed"], mine["severity"], strict=True)]
        status = "not_evaluated" if mine.empty else next(s for s in STATUS_WORST_FIRST if s in found)
        rules.append({"rule_id": rule_id, "name_es": rule.name_es, "severity": rule.severity.value, "scope": rule.scope, "aggregation": rule.aggregation.value, "status": status,
                      "series_days": int(mine["series_days_affected"].sum()), "hours": int(mine["hours_affected"].sum())})
    loaded, rejected = conn.execute("SELECT COALESCE(SUM(status = 'loaded'), 0), COALESCE(SUM(status = 'rejected'), 0) FROM deliveries").fetchone()
    return {"rules": rules, "totals": {"series_days": int(conn.execute("SELECT COUNT(*) FROM series_days").fetchone()[0]), "deliveries_loaded": int(loaded), "deliveries_rejected": int(rejected)}}


# --- reading, verifying and writing the set -------------------------------------------------------------------------------------------------


def _text(document: dict) -> str:
    return json.dumps(document, ensure_ascii=False, sort_keys=True, indent=1, allow_nan=False) + "\n"


def _read_checked(out_dir: Path) -> tuple[dict[str, bytes], dict[str, Any], list[str]]:
    out_dir = Path(out_dir)
    try:
        manifest = json.loads((out_dir / MANIFEST_FILE).read_text(encoding="utf-8"))
        files = manifest["files"]
        if not isinstance(files, dict) or not all(isinstance(e, dict) for e in files.values()):
            raise TypeError(MANIFEST_FILE)
    except FileNotFoundError:
        return {}, {}, [f"falta {MANIFEST_FILE} en {out_dir}: el conjunto no es una exportación completa"]
    except (ValueError, KeyError, TypeError):
        return {}, {}, [f"{MANIFEST_FILE} de {out_dir} no se puede leer"]
    problems = [] if sorted(files) == sorted(SITE_FILES) else [f"{MANIFEST_FILE} nombra {sorted(files)} y no los cinco archivos del sitio"]
    out: dict[str, bytes] = {}
    for name in SITE_FILES:
        path = out_dir / name
        if not path.is_file():
            problems.append(f"falta {name} en {out_dir}")
            continue
        data = path.read_bytes()
        entry = files.get(name, {})
        if len(data) != entry.get("bytes") or hashlib.sha256(data).hexdigest() != entry.get("sha256"):
            problems.append(f"{name} no es el que nombra {MANIFEST_FILE} (otro tamaño o SHA-256): los archivos no son de una misma exportación")
            continue
        try:
            document = json.loads(data.decode("utf-8"))
        except ValueError:
            problems.append(f"{name} no es un JSON legible")
            continue
        if any(document.get(key) != manifest.get(key) for key in ENVELOPE):
            problems.append(f"{name} no lleva el envoltorio de {MANIFEST_FILE} (la corrida, el instante o la fuente son otros)")
        out[name] = data
    return out, manifest, problems


def read_site(out_dir: Path) -> SiteFiles:
    """The five documents of `out_dir`, each read once and checked against ``manifest.json``; ``SiteSetError`` if they are not one export."""
    data, manifest, problems = _read_checked(out_dir)
    if problems:
        raise SiteSetError("; ".join(problems))
    documents = {name.removesuffix(".json"): json.loads(data[name].decode("utf-8")) for name in SITE_FILES}
    return SiteFiles(**documents, manifest=manifest)


def verify_site(out_dir: Path) -> list[str]:
    """What keeps the files of `out_dir` from being one export (``[]`` when the manifest names the five with their size and SHA-256 and each carries its envelope)."""
    return _read_checked(out_dir)[2]


def _write(texts_by_name: dict[str, str], out_dir: Path, cap: int, header: dict[str, Any]) -> list[Path]:
    out_dir = Path(out_dir)
    payloads = {name: texts_by_name[name].encode("utf-8") for name in SITE_FILES}
    total = sum(len(p) for p in payloads.values())
    if total > cap:
        raise SiteExportError(f"los archivos del sitio pesan {total} bytes y el tope es {cap}: no se escribió ninguno")
    manifest = _text({**header, "files": {n: {"bytes": len(p), "sha256": hashlib.sha256(p).hexdigest()} for n, p in payloads.items()}})
    (out_dir / MANIFEST_FILE).unlink(missing_ok=True)         # a set being rewritten has no manifest until its last file is written
    paths = [write_atomic(out_dir / name, texts_by_name[name]) for name in SITE_FILES]
    write_atomic(out_dir / MANIFEST_FILE, manifest)
    logger.info("site export %s: %d files, %d bytes", header["run_key"], len(paths), total)
    return paths


def export_site(conn: sqlite3.Connection, out_dir: Path, run: RunMeta, view: Any, *, seal_path: Path, max_total_bytes: int) -> list[Path]:
    """Write the five site files from the star model of `conn`, then ``manifest.json``; returns the five paths (``SITE_FILES`` order). Every document is built before the first file is
    replaced, and nothing is written if together they would pass `max_total_bytes` (``[site]``). `view` is the sealed view, as for ``export_star_schema``."""
    _require_star(conn)
    header = _header(run, view)
    summary, seal = build_summary(conn, view, run=run, seal_path=seal_path), read_seal(seal_path)
    documents = {"summary.json": _summary(conn, run, view, summary, seal), "data.json": _data(conn, view, seal), "algorithms.json": _algorithms(conn, view, seal),
                 "operation.json": _operation(conn), "validation_rules.json": _validation(conn)}
    return _write({name: _text({**header, **documents[name]}) for name in SITE_FILES}, out_dir, max_total_bytes, header)


__all__ = ["MANIFEST_FILE", "SITE_FILES", "SiteExportError", "SiteFiles", "SiteSetError", "export_site", "read_site", "verify_site"]
