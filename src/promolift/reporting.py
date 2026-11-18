"""The task ``evaluate``, the summary and the results block of the README (RF18, RF19; AC19, AC22; D16, D17, D21; plan, sections 3 and 16).

``evaluate`` runs in every run after the launch. Before the close it says so and stores nothing. At the close (the run's ``as_of`` reaches the day after the last day of
the test) it evaluates the test **once**, from what was issued (``evaluation.evaluate_test``): the figures, the criteria C01 to C10 and the variants (after the launch
part of the seal), all written to the test part of the seal (``registry.write_test_seal``) and to the sealed rows of the warehouse, which are never written again. With
another configuration than the sealed one, if the seal already has its test part, everything is stored as ``post_seal`` and replaces only the post-seal rows; with
another configuration and no test part, ``registry.check_test_evaluation`` refuses before anything is written (D17).

``build_summary`` says what is known: the test pending (with the reason, and the figures of V1 and V2 labelled with the blocks their methods were fitted on), the sealed
criteria from the warehouse, or, when the warehouse has no sealed rows but the seal has its test part (a rebuild from scratch), the criteria rebuilt from the seal, each
checked against its entry (D21). ``write_summary`` writes ``evaluation_summary.json`` and ``.md``; ``sync_block`` copies the Markdown between two markers.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Mapping
from datetime import timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from promolift import texts, variants
from promolift.evaluation import Criterion, EvaluationResult, criteria_from_seal, evaluate_criteria, evaluate_test, figures, load_periods
from promolift.files import write_atomic
from promolift.launch import FIT_BLOCKS_LAUNCH, clean, effect_row, stamp
from promolift.leakage_demo import CHECKS_ES, NOTES_ES
from promolift.effect import cell_key
from promolift.registry import LaunchBundle, RunMeta, SealError, check_test_evaluation, config_fingerprint, read_seal, seal_state, sealed_document, write_test_seal
from promolift.texts import CRITERIA, es
from promolift.warehouse import apply_schema

logger = logging.getLogger(__name__)

SUMMARY_VERSION = 1
RESULTS_START, RESULTS_END = "<!-- results:start -->", "<!-- results:end -->"
STAMP = "%Y-%m-%d %H:%M:%S"


def ready_instant(view: Any) -> pd.Timestamp:
    """The instant the last day of the test is complete: the day after ``calendar.last_day``, at 00:00. The test is evaluated at the first run whose ``as_of`` reaches it."""
    return pd.Timestamp(view.calendar.last_day) + timedelta(days=1)


def criterion_dict(c: Criterion) -> dict[str, Any]:
    return {"criterion_id": c.criterion_id, "name_es": c.name_es, "value": c.value, "baseline_value": c.baseline_value, "ci_low": c.ci_low, "ci_high": c.ci_high,
            "threshold_es": c.threshold_es, "passed": c.passed, "seen_by_research": c.seen_by_research, "seen_by_planner": c.seen_by_planner, "verdict_es": c.verdict_es}


# --- the task ----------------------------------------------------------------------------------------------------------------


def _has_sealed_criteria(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM eval_criteria WHERE seal_state = 'sealed' LIMIT 1").fetchone() is not None


def _entries(result: EvaluationResult, version: str) -> dict[str, Any]:
    """The effects of a version as the seal's test part says them: the whole, the cells, the bands and the groups, each entry with its lift, interval and counts."""
    stats, ids, n_bands = result.effects[version], result.group_ids, result.n_bands
    ranking = stats["ranking"]

    def entry(family: str, key: str, at: int) -> dict[str, Any]:
        s = stats[family]
        return {"key": key, "lift": s["lift"][at], "ci_low": s["low"][at], "ci_high": s["high"][at], "series": int(s["series"][at]), "series_days": int(s["series_days"][at])}

    cells = [{**entry("cell", cell_key(k, ids, n_bands), k), "rank": None if pd.isna(ranking["rank"].iloc[k]) else int(ranking["rank"].iloc[k]),
              "tier": None if pd.isna(ranking["tier"].iloc[k]) else int(ranking["tier"].iloc[k])} for k in range(len(ids) * n_bands) if stats["cell"]["series_days"][k]]
    return {"overall": entry("overall", "all", 0), "cells": cells, "bands": [entry("band", f"b{k}", k) for k in range(n_bands) if stats["band"]["series_days"][k]],
            "groups": [entry("group", f"g{int(g)}", k) for k, g in enumerate(ids) if stats["group"]["series_days"][k]]}


def _test_part(run: RunMeta, config_sha256: str, result: EvaluationResult, criteria: list[Criterion], found: list[dict[str, Any]]) -> dict[str, Any]:
    return clean({
        "run_key": run.run_key, "as_of": stamp(run.as_of), "config_sha256": config_sha256, "criteria": [c.seal_entry() for c in criteria], "metrics": figures(result, len(found)),
        "recovery": {"method": result.sealed_method, "methods": result.recovery}, "effects": {v: _entries(result, v) for v in result.effects}, "replication": result.replication,
        "forecast": result.forecast, "variants": found, "days": result.days})


def store_result(conn: sqlite3.Connection, result: EvaluationResult, criteria: list[Criterion], found: list[dict[str, Any]], state: str, run_key: str, leakage: Mapping[str, Any]) -> None:
    """Write what an evaluation found, in one transaction. ``sealed``: the criteria, the replication, the forecast errors and the variants, the effects and the recovery of
    the week, the pairs that overlap and the demonstration of the leak (each once). ``post_seal``: only the first four, replacing the post-seal rows of the last analysis."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        apply_schema(conn)
        if state == "post_seal":
            for table in ("eval_criteria", "eval_replication", "eval_forecast", "eval_variants"):
                conn.execute(f"DELETE FROM {table} WHERE seal_state = 'post_seal'")
        conn.executemany("INSERT INTO eval_criteria VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [
            (c.criterion_id, state, c.name_es, c.value, c.baseline_value, c.ci_low, c.ci_high, c.threshold_es, None if c.passed is None else int(c.passed), c.seen_by_research,
             c.seen_by_planner, c.verdict_es, run_key) for c in criteria])
        conn.executemany("INSERT INTO eval_replication VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [
            (r["cell"], state, r["series_launch"], r["series_test"], r["lift_launch"], r["ci_low_launch"], r["ci_high_launch"], r["lift_test"], r["ci_low_test"], r["ci_high_test"],
             r["diff_ci_low"], r["diff_ci_high"], None if r["consistent"] is None else int(r["consistent"]), run_key) for r in result.replication])
        conn.executemany("INSERT INTO eval_forecast VALUES (?, ?, ?, ?, ?, ?, ?)", [
            (m, state, FIT_BLOCKS_LAUNCH, v["wape"], v["bias"], v["rows"], run_key) for m, v in (result.forecast.get("methods") or {}).items()])
        conn.executemany("INSERT INTO eval_variants VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", [
            (r["variant"], r["unit_key"], state, r["value"], r["ci_low"], r["ci_high"], r["series"], r["series_days"], run_key) for r in found])
        if state == "sealed":
            ids, n_bands = result.group_ids, result.n_bands
            effect_rows = []
            for version, stats in result.effects.items():
                for unit, family, keys in (("overall", "overall", ["all"]), ("cell", "cell", [cell_key(k, ids, n_bands) for k in range(len(ids) * n_bands)]),
                                           ("band", "band", [f"b{k}" for k in range(n_bands)]), ("group", "group", [f"g{int(g)}" for g in ids])):
                    effect_rows += [effect_row("test", version, unit, key, FIT_BLOCKS_LAUNCH, stats[family], at, stats["ranking"] if unit == "cell" else None)
                                    for at, key in enumerate(keys) if stats[family]["series_days"][at]]
            conn.executemany("INSERT INTO effect_estimates VALUES (" + ", ".join("?" * 16) + ")", effect_rows)
            conn.executemany("INSERT INTO recovery_checks VALUES (" + ", ".join("?" * 15) + ")", [
                ("test", "tail", r["method"], FIT_BLOCKS_LAUNCH, r["series"], r["masked_days"], r["hidden_hours"], r["hidden_mass"], r["wape_series"], r["bias"], r["bias_promo"],
                 r["bias_regular"], r["lift_bias"], r["ci_low_vs_r1"], r["ci_high_vs_r1"]) for r in result.recovery])
            only = {(r["unit_key"].split(":")[0], r["unit_key"].split(":")[1]): r["value"] for r in found if r["variant"] == "series_only_intervals"}
            pairs = [(scope, "two_way", p["cells"], p["pairs"], p["overlapping"], p["median_width"], run_key) for scope, p in result.pairs.items()]
            pairs += [(scope, "series_only", int(only[(scope, "cells")]), int(only[(scope, "pairs")]), int(only[(scope, "overlapping")]), only[(scope, "median_width")], run_key)
                      for scope in ("launch", "test") if (scope, "cells") in only]
            conn.executemany("INSERT INTO eval_pairs VALUES (?, ?, ?, ?, ?, ?, ?)", pairs)
            conn.executemany("INSERT INTO eval_leakage VALUES (?, ?, ?, ?, ?)", [(name, CHECKS_ES[name], v["wape"], NOTES_ES[name], run_key) for name, v in leakage.items()])
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        logger.warning("evaluate %s rolled back: nothing of the evaluation was stored", run_key)
        raise


def evaluate(conn: sqlite3.Connection, cube: Any, bundle: LaunchBundle, run: RunMeta, view: Any, *, seal_path: Path) -> dict[str, Any]:
    """Evaluate what the run's ``as_of`` allows (see the module). Returns what the run records (JSON-ready): ``test`` is ``pending``, ``sealed_before``, ``written``,
    ``unchanged`` (a repetition that reproduces the seal) or ``post_seal``."""
    config_sha256 = config_fingerprint(view)
    state = seal_state(seal_path, config_sha256)
    if state == "none":
        raise SealError("no hay sello: el lanzamiento escribe su parte antes de que se evalúe la prueba (docs/runbook.md, R7)")
    rows_state = "sealed" if state == "match" else "post_seal"
    ready = ready_instant(view)
    out: dict[str, Any] = {"seal_state": rows_state, "test": "pending", "ready_instant": ready.strftime(STAMP)}
    if pd.Timestamp(run.as_of) < ready:
        return out
    mode = check_test_evaluation(seal_path, view)                      # refuses before anything is written if it must (D17)
    apply_schema(conn)
    if rows_state == "sealed" and _has_sealed_criteria(conn):
        out["test"] = "sealed_before"
        return out
    periods = load_periods(conn, cube, bundle, view)
    result = evaluate_test(conn, cube, bundle, view, periods=periods)
    found = variants.run(conn, cube, bundle, view, seal_path=seal_path, periods=periods)
    criteria = evaluate_criteria(result, view, len(found))
    part = _test_part(run, config_sha256, result, criteria, found)
    outcome = write_test_seal(seal_path, part) if mode in ("first", "repeat") else "post_seal"
    store_result(conn, result, criteria, found, rows_state, run.run_key, (read_seal(seal_path)["launch"]["validation"].get("leakage") or {}))
    out.update(test=outcome, criteria={c.criterion_id: c.passed for c in criteria})
    logger.info("evaluate %s: test %s (%s), criteria met %s", run.run_key, outcome, rows_state, [c.criterion_id for c in criteria if c.passed])
    return out


# --- the summary -------------------------------------------------------------------------------------------------------------


def _criteria_rows(conn: sqlite3.Connection, state: str) -> list[dict[str, Any]]:
    columns = ("criterion_id", "name_es", "value", "baseline_value", "ci_low", "ci_high", "threshold_es", "passed", "seen_by_research", "seen_by_planner", "verdict_es")
    out = []
    for row in conn.execute(f"SELECT {', '.join(columns)} FROM eval_criteria WHERE seal_state = ? ORDER BY criterion_id", (state,)).fetchall():
        entry = dict(zip(columns, row, strict=True))
        entry["passed"] = None if entry["passed"] is None else bool(entry["passed"])
        out.append(entry)
    return out


def _validation(conn: sqlite3.Connection) -> dict[str, Any]:
    """The recovery of V1 and V2 as the launch stored it, each with the blocks its methods were fitted on (D21): ``{scope: {fit_blocks, methods: {name: figures}}}``."""
    out: dict[str, Any] = {}
    for scope, method, fit_blocks, wape, bias in conn.execute(
            "SELECT scope, method, fit_blocks, wape_series, bias FROM recovery_checks WHERE scope IN ('valid_v1', 'valid_v2') AND mask = 'tail' ORDER BY scope, rowid"):
        part = out.setdefault(f"recovery_{scope[-2:]}", {"fit_blocks": fit_blocks, "methods": {}})
        part["methods"][method] = {"wape_series": wape, "bias": bias}
    return out


def pending_criteria(view: Any, reason: str) -> list[dict[str, Any]]:
    thresholds = texts.thresholds_from(sealed_document(view)["criteria"])
    return [{"criterion_id": cid, "name_es": c.name_es, "value": None, "baseline_value": None, "ci_low": None, "ci_high": None, "threshold_es": thresholds[cid], "passed": None,
             "seen_by_research": c.seen_by_research, "seen_by_planner": c.seen_by_planner, "verdict_es": "Pendiente: " + reason} for cid, c in CRITERIA.items()]


def build_summary(conn: sqlite3.Connection, view: Any, *, run: RunMeta, seal_path: Path) -> dict[str, Any]:
    """What the summary says (see the module): ``evaluation_status`` is ``pending``, ``sealed`` or ``post_seal`` (this run's configuration is not the sealed one),
    ``sealed_from`` is ``seal`` when the criteria come from the seal."""
    apply_schema(conn)
    state = seal_state(seal_path, config_fingerprint(view))
    rows_state = "sealed" if state == "match" else "post_seal"
    seal = read_seal(seal_path)
    summary: dict[str, Any] = {"schema_version": SUMMARY_VERSION, "run_key": run.run_key, "as_of": pd.Timestamp(run.as_of).strftime(STAMP), "train_sha256": view.train_sha256_seen,
                               "eval_sha256": view.eval_sha256_seen, "validation": _validation(conn), "test": None, "post_seal": None, "pending_reason_es": None}
    sealed_rows = _criteria_rows(conn, "sealed")
    post_rows = _criteria_rows(conn, "post_seal") if rows_state == "post_seal" else []
    if sealed_rows:
        summary.update(evaluation_status="sealed", criteria=sealed_rows, test=(seal or {}).get("test", {}).get("metrics"))
    elif seal is not None and seal.get("test") is not None:
        summary.update(evaluation_status="sealed", criteria=[criterion_dict(c) for c in criteria_from_seal(seal)], test=seal["test"]["metrics"], sealed_from="seal")
    elif post_rows:
        summary.update(evaluation_status="post_seal", criteria=post_rows)
    else:
        reason = texts.pending_reason(ready_instant(view).strftime(STAMP), summary["as_of"])
        summary.update(evaluation_status="pending", pending_reason_es=reason, criteria=pending_criteria(view, reason))
    if post_rows and summary["evaluation_status"] == "sealed":
        summary["post_seal"] = {"criteria": post_rows}
    if seal is not None:
        summary["seal"] = {"config_sha256": seal["launch"]["config_sha256"], "launch_run_key": seal["launch"]["run_key"], "test_run_key": (seal.get("test") or {}).get("run_key"),
                           "test_as_of": (seal.get("test") or {}).get("as_of")}
    return summary


def _cell(text: Any) -> str:
    """A cell of a Markdown table: its pipes escaped, so «|sesgo|» stays inside its cell."""
    return str(text).replace("|", r"\|")


def _validation_lines(validation: Mapping[str, Any]) -> list[str]:
    """The WAPE of the mass per series and the bias of each method on V2, labelled as validation (not the test) and with the blocks the methods were fitted on."""
    v2 = validation.get("recovery_v2") or {}
    if not v2:
        return []
    lines = [f"Validación (V2, no la prueba; métodos ajustados con {v2['fit_blocks']}): recuperación sobre la máscara de cola.", "", "| Método | WAPE por serie | Sesgo |", "| --- | ---: | ---: |"]
    lines += [f"| {_cell(texts.method_label(name))} | {es(m['wape_series'], 1, percent=True)} | {es(m['bias'], 1, percent=True)} |" for name, m in v2["methods"].items()]
    return lines + [""]


def summary_markdown(summary: Mapping[str, Any]) -> str:
    """The Markdown of the summary, in Spanish: the state, each criterion with its number and its verdict (also «no supera»), and below, the post-seal analysis if there is
    one. A pending summary says why, and shows only the validation."""
    lines = ["## Resultados", ""]
    status = summary["evaluation_status"]
    if status == "pending":
        lines += [f"**Prueba pendiente.** {summary['pending_reason_es']}", ""]
        lines += _validation_lines(summary.get("validation") or {})
    else:
        origin = " (tomados del sello)" if summary.get("sealed_from") == "seal" else ""
        lines += [f"Criterios fijados antes de construir, evaluados una vez sobre la prueba{origin}.", "", "| Criterio | Umbral | Valor | Cumple | Veredicto |", "| --- | --- | ---: | --- | --- |"]
        for c in summary["criteria"]:
            passed = "informativo" if c["passed"] is None else ("sí" if c["passed"] else "no")
            lines.append(f"| {c['criterion_id']} {_cell(c['name_es'])} | {_cell(c['threshold_es'])} | {es(c['value'], 3)} | {passed} | {_cell(c['verdict_es'])} |")
        lines.append("")
        lines += _validation_lines(summary.get("validation") or {})
    post = summary.get("post_seal")
    if post and post.get("criteria"):
        lines += ["### Análisis posterior al sello", "", "Con otra configuración que la sellada: no reemplaza lo sellado.", ""]
        lines += [f"- {c['criterion_id']}: {c['verdict_es']}" for c in post["criteria"]]
        lines.append("")
    lines.append(f"Estado: {status}. Corrida {summary['run_key']} del {summary['as_of']}.")
    return "\n".join(lines) + "\n"


def write_summary(summary: Mapping[str, Any], reports_dir: Path) -> tuple[Path, Path]:
    """``evaluation_summary.json`` and ``evaluation_summary.md`` in `reports_dir`, each written atomically."""
    reports_dir = Path(reports_dir)
    json_path, md_path = reports_dir / "evaluation_summary.json", reports_dir / "evaluation_summary.md"
    write_atomic(json_path, json.dumps(clean(dict(summary)), ensure_ascii=False, sort_keys=True, indent=1, allow_nan=False) + "\n")
    write_atomic(md_path, summary_markdown(summary))
    return json_path, md_path


def _check_text(text: str, name: str, start_marker: str, end_marker: str) -> None:
    if text.count(start_marker) != 1 or text.count(end_marker) != 1 or text.index(start_marker) > text.index(end_marker):
        raise ValueError(f"{name} debe tener una vez {start_marker} y después una vez {end_marker}")


def check_markers(path: Path, start_marker: str, end_marker: str) -> str:
    """The text of `path` if it has both markers, in order and once each; otherwise a ``ValueError`` and nothing else happens."""
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    _check_text(text, path.name, start_marker, end_marker)
    return text


def replace_block(text: str, name: str, start_marker: str, end_marker: str, content: str) -> str:
    """`text` (the file `name`) with what is between its two markers replaced by `content` (the markers stay); nothing is read or written. A text without both markers,
    in order and once each, is a ``ValueError`` that names the file: ``docs-sync`` computes every new text with this before it writes any."""
    _check_text(text, name, start_marker, end_marker)
    head, rest = text.split(start_marker)
    _old, tail = rest.split(end_marker)
    return f"{head}{start_marker}\n{content.strip()}\n{end_marker}{tail}"


def sync_block(path: Path, start_marker: str, end_marker: str, content: str) -> bool:
    """Replace what is between the two markers of `path` with `content` (the markers stay). True if the file changed. A file without both markers, in order and once each,
    is a ``ValueError`` and is not touched."""
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    new = replace_block(text, path.name, start_marker, end_marker, content)
    if new == text:
        return False
    write_atomic(path, new)
    return True
