"""Validation of the source and of every delivery, and the validation report (RF06, D23; plan, section 6); adapted from project 05.

The rules are the table of the plan, section 6, in its order (``RULES``). Each declares its severity, its scope (``source``, ``delivery``, ``days`` or
``model``) and how it is published over runs (``aggregation``: ``source`` once, from the report of the source; ``per_run`` summed over the loaded runs;
``latest`` read once from the last loaded run, because it already holds the earlier ones: project 03's D94).

- The rules of the source (V01-V07, V26, V27) are not evaluated again here: the first task ran them while it read the two files, so
  ``validate_source`` turns its outcome (a ``SourceError`` naming the failing rule, or the two ``SourceReport`` of a clean read) into results.
- The rules of the delivery and of its days (V10-V15, V20-V25, I01, I02) read the delivery, the plan, its manifest entry and what the warehouse already
  holds (``deliveries`` and ``series_days``, plan section 5), which they only read.
- The rules of the model (I03, I04, M01-M06) are evaluated by their tasks, which add them with ``model_result`` and ``add_results``.

A rule that cannot be evaluated because an earlier blocking rule failed, or that another task evaluates, is listed in ``not_evaluated``; it is never
reported as passed. ``series_days_affected`` counts series-days and ``hours_affected`` the analysis hours they hold (16 for each, except the rules
that count hours: I01). An example names a series and a day by key and never what was measured in it.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from promolift.days import UNFLAGGED
from promolift.deliveries import DAYS_COLUMNS, SUM_COLUMNS, DeliverySpec, ManifestEntry, delivery_digest, delivery_plan, delivery_sums
from promolift.files import sha256_file, write_atomic
from promolift.ingest import SourceReport
from promolift.schema import FORBIDDEN_COLUMNS, SourceError, date_key

logger = logging.getLogger(__name__)

EXAMPLE_LIMIT = 5
SUM_TOLERANCE = 1e-9                 # V14: the sums of the file against the ones recomputed from the cube
_KEY = 1_000_000                     # a series-day as one integer: date_key * _KEY + series_key (series_key stays under a million)
_SAFE_RUN_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_PATH_KEYS = ("path",)               # keys of a SourceError problem that hold a path of this machine


class Severity(StrEnum):
    BLOCKING = "blocking"
    WARNING = "warning"
    INFO = "info"


class Aggregation(StrEnum):
    SOURCE = "source"
    PER_RUN = "per_run"
    LATEST = "latest"


SEVERITY_ES = {Severity.BLOCKING: "bloqueante", Severity.WARNING: "advertencia", Severity.INFO: "informativa"}
STATUS_ES = {"pass": "pasa", "fail": "falla", "warn": "advierte", "not_evaluated": "no evaluada"}


@dataclass(frozen=True)
class Rule:
    name_es: str
    severity: Severity
    scope: str               # "source", "delivery", "days" or "model"
    aggregation: Aggregation


_B, _W, _I = Severity.BLOCKING, Severity.WARNING, Severity.INFO
_S, _P, _L = Aggregation.SOURCE, Aggregation.PER_RUN, Aggregation.LATEST

# rule id -> rule, in the order of the table of the plan (section 6): the report's order; tests/contract/test_validate.py compares it with the table
RULES: dict[str, Rule] = {
    "V01": Rule("Cada archivo existe y tiene el tamaño y la huella aceptados (o la registrada, en modo rápido)", _B, "source", _S),
    "V02": Rule("Esquema exacto: las 19 columnas de la fuente, en orden y con su tipo", _B, "source", _S),
    "V03": Rule("Archivo, filas y grupos de filas dentro de sus topes; metadatos de pyarrow leídos antes que los datos", _B, "source", _S),
    "V04": Rule("Cada lista horaria con 24 valores, sin nulos ni NaN; venta finita en [0, tope]; estado en {0, 1}; campos diarios que se usan completos", _B, "source", _S),
    "V05": Rule("(tienda, producto, día) único; día AAAA-MM-DD dentro de la ventana de su archivo; train y eval sin solaparse y contiguos", _B, "source", _S),
    "V06": Rule("Jerarquía: cada producto con una sola cadena de categorías y un grupo; cada tienda con una ciudad", _B, "source", _S),
    "V07": Rule("Cada serie tiene todos los días de su ventana, y son las mismas series en los dos archivos", _B, "source", _S),
    "V10": Rule("La entrega es la siguiente del plan y su período empieza el día siguiente al fin de la anterior", _B, "delivery", _P),
    "V11": Rule("Cada serie-día de la entrega está dentro de su período", _B, "delivery", _P),
    "V12": Rule("Ninguna serie-día de la entrega está ya en el almacén ni repetida dentro de ella", _B, "delivery", _P),
    "V13": Rule("Series-días, archivos y SHA-256 son los del manifiesto; solo el cierre puede no tener filas", _B, "delivery", _P),
    "V14": Rule("Las sumas del archivo de días son las del cubo de la entrega, recalculadas", _B, "delivery", _P),
    "V15": Rule("La entrega no trae ninguna columna prohibida", _B, "delivery", _P),
    "V20": Rule("Descuento 0 (se cuenta y se excluye del efecto)", _W, "days", _P),
    "V21": Rule("Descuento mayor que 1 (se cuenta y se excluye del efecto)", _W, "days", _P),
    "V22": Rule("Descuento entre 0 y 0,5 (se usa: es la banda 0)", _W, "days", _P),
    "V23": Rule("Marca 1 con descuento 1 (se usa: banda 6)", _W, "days", _P),
    "V24": Rule("Marca 0 con descuento menor que 0,999 (efecto aparte, nunca control)", _W, "days", _P),
    "V25": Rule("Serie-día sin stock de 06 a 21 (se recupera con R1)", _W, "days", _P),
    "V26": Rule("El total diario de la venta es distinto de la suma de las horas (se cuenta; el campo no pasa de la lectura)", _W, "source", _S),
    "V27": Rule("El conteo de horas sin stock del archivo es distinto del conteo de 06 a 21 (se cuenta; el campo no pasa de la lectura)", _W, "source", _S),
    "I01": Rule("Horas sin stock de 0 a 5 y de 22 a 23 (solo cuenta: no se recuperan)", _I, "days", _P),
    "I02": Rule("Días con la marca de feriado (solo cuenta: los absorbe el factor del día)", _I, "days", _P),
    "I03": Rule("Series sin día regular en el período de ajuste (solo cuenta; quedan fuera del efecto)", _I, "model", _P),
    "I04": Rule("Filas emitidas (efectos, pronósticos, máscaras)", _I, "model", _P),
    "M01": Rule("Trampa de fuga: el error por serie del método elegido en V1 es menor que la mitad del de la media simple", _B, "model", _L),
    "M02": Rule("Las entradas de la recuperación y del contrafactual no tienen ninguna columna prohibida", _B, "model", _P),
    "M03": Rule("El artefacto tiene la huella registrada, antes de leerlo, y el .npz no trae objetos", _B, "model", _P),
    "M04": Rule("Aumentos, contrafactuales y pronósticos finitos; contrafactual positivo donde se divide", _B, "model", _P),
    "M05": Rule("La configuración es la sellada (si no, todo lo calculado es posterior al sello)", _W, "model", _L),
    "M06": Rule("V1 y V2 con al menos las series-días enmascarables mínimas, y cada bloque con días de promoción y regulares", _B, "model", _L),
}
SOURCE_BLOCKING = tuple(rule_id for rule_id, rule in RULES.items() if rule.scope == "source" and rule.severity is Severity.BLOCKING)
MODEL_RULES = tuple(rule_id for rule_id, rule in RULES.items() if rule.scope == "model")


@dataclass(frozen=True)
class RuleResult:
    rule_id: str
    name_es: str
    severity: Severity
    scope: str
    aggregation: Aggregation
    passed: bool
    series_days_affected: int
    hours_affected: int
    examples: list[dict]

    @property
    def status(self) -> str:
        """``pass``, ``fail`` (a blocking rule) or ``warn`` (a warning); an informative rule always passes."""
        if self.passed:
            return "pass"
        return "fail" if self.severity is Severity.BLOCKING else "warn"


@dataclass(frozen=True)
class ValidationReport:
    run_key: str
    train_sha256: str
    eval_sha256: str
    delivery_id: str | None
    series_days_delivery: int
    results: list[RuleResult]
    not_evaluated: tuple[str, ...] = field(default=())

    @property
    def blocking_failed(self) -> bool:
        return any(r.severity is Severity.BLOCKING and not r.passed for r in self.results)


class ValidationError(RuntimeError):
    """The run was rejected: at least one blocking rule failed (raised by the ``validate`` task)."""

    def __init__(self, report: ValidationReport) -> None:
        self.report = report
        failing = ", ".join(r.rule_id for r in report.results if r.severity is Severity.BLOCKING and not r.passed)
        super().__init__(f"la validación de {report.run_key} rechazó la corrida: fallan las reglas bloqueantes {failing}")


# --- helpers ------------------------------------------------------------------------------------------------------------------


def _py(value: Any) -> Any:
    """A JSON-friendly Python value from a numpy scalar."""
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if np.isnan(value) else float(value)
    return value


def _result(rule_id: str, passed: bool, series_days: int = 0, hours: int | None = None, examples: list[dict] | None = None, *, hours_per_day: int = 16
            ) -> RuleResult:
    rule = RULES[rule_id]
    return RuleResult(rule_id, rule.name_es, rule.severity, rule.scope, rule.aggregation, True if rule.severity is Severity.INFO else bool(passed),
                      int(series_days), int(series_days * hours_per_day if hours is None else hours), examples or [])


def _ordered(results: dict[str, RuleResult]) -> list[RuleResult]:
    return [results[rule_id] for rule_id in RULES if rule_id in results]


def _log_verdict(report: ValidationReport) -> None:
    blocking = [r.rule_id for r in report.results if r.status == "fail"]
    warnings = [r.rule_id for r in report.results if r.status == "warn"]
    logger.log(logging.WARNING if blocking else logging.INFO, "validation of %s (%s): %s; series-days=%d; blocking failed: %s; warnings: %s; not evaluated: %s",
               report.run_key, report.delivery_id or "source", "rejected" if blocking else "accepted", report.series_days_delivery,
               ", ".join(blocking) or "none", ", ".join(warnings) or "none", ", ".join(report.not_evaluated) or "none")


# --- the rules of the source ----------------------------------------------------------------------------------------------------


def _source_problem(problem: dict[str, Any]) -> dict[str, Any]:
    """A problem of a ``SourceError`` as an example: JSON-safe and without a path of this machine."""
    return {key: _py(value) if not isinstance(value, (list, dict)) else value for key, value in problem.items() if key not in _PATH_KEYS}


def validate_source(outcome: SourceError | tuple[SourceReport, SourceReport], *, run_key: str, train_sha256: str = "", eval_sha256: str = ""
                    ) -> ValidationReport:
    """The report of the rules of the source from what the first task found.

    A ``SourceError`` fails its rule (V01 to V07, nothing else), the blocking rules before it pass and every other rule is ``not_evaluated``.
    The two ``SourceReport`` of a clean read (train, eval) mean both files were read: V01-V07 pass and V26 and V27 count the rows where the two
    sums of the file differ from the hours (a warning, not a rejection).
    """
    results: dict[str, RuleResult] = {}
    if isinstance(outcome, SourceError):
        if outcome.rule_id not in SOURCE_BLOCKING:
            raise ValueError(f"{outcome.rule_id} no es una regla bloqueante de la fuente ({', '.join(SOURCE_BLOCKING)})")
        for rule_id in SOURCE_BLOCKING[: SOURCE_BLOCKING.index(outcome.rule_id)]:
            results[rule_id] = _result(rule_id, True)
        examples = [_source_problem(p) for p in outcome.problems[:EXAMPLE_LIMIT]] or [{"message": str(outcome)}]
        results[outcome.rule_id] = _result(outcome.rule_id, False, examples=examples)
    else:
        for rule_id in SOURCE_BLOCKING:
            results[rule_id] = _result(rule_id, True)
        for rule_id, total in (("V26", sum(r.sale_amount_mismatch for r in outcome)), ("V27", sum(r.stock_count_mismatch for r in outcome))):
            results[rule_id] = _result(rule_id, total == 0, total, examples=[{"files": [r.split for r in outcome if (r.sale_amount_mismatch if rule_id == "V26"
                                                                                                                    else r.stock_count_mismatch)]}] if total else [])
    report = ValidationReport(run_key, train_sha256, eval_sha256, None, 0, _ordered(results), tuple(r for r in RULES if r not in results))
    _log_verdict(report)
    return report


# --- what the warehouse already holds (read only) ---------------------------------------------------------------------------------


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)).fetchone() is not None


def loaded_deliveries(conn: sqlite3.Connection) -> set[str]:
    """The deliveries the warehouse holds as loaded (none before the first load)."""
    if not _table_exists(conn, "deliveries"):
        return set()
    return {row[0] for row in conn.execute("SELECT delivery_id FROM deliveries WHERE status = 'loaded'")}


def known_series_days(conn: sqlite3.Connection, first: int, last: int) -> set[int]:
    """The series-days already in ``series_days`` whose day is between the keys `first` and `last`, each as ``date_key * 1_000_000 + series_key``."""
    if not _table_exists(conn, "series_days"):
        return set()
    return {int(d) * _KEY + int(s) for s, d in conn.execute("SELECT series_key, date_key FROM series_days WHERE date_key BETWEEN ? AND ?", (first, last))}


# --- the rules of the delivery ------------------------------------------------------------------------------------------------------


def _require_columns(days: pd.DataFrame) -> None:
    missing = [name for name in DAYS_COLUMNS if name not in days.columns]
    if missing:
        raise ValueError(f"la entrega no tiene las columnas del esquema canónico de los días: faltan {', '.join(missing)}")


def _keys(days: pd.DataFrame, mask: np.ndarray) -> list[dict[str, int]]:
    """Up to ``EXAMPLE_LIMIT`` of the series-days of `days` selected by `mask`, by key."""
    chosen = days.loc[mask, ["series_key", "date_key"]].head(EXAMPLE_LIMIT)
    return [{"series_key": int(s), "date_key": int(d)} for s, d in zip(chosen["series_key"], chosen["date_key"])]


def _period(spec: DeliverySpec) -> list[str | None]:
    return [spec.first_day.isoformat() if spec.first_day else None, spec.last_day.isoformat() if spec.last_day else None]


def _rule_v10(days: pd.DataFrame, spec: DeliverySpec, loaded: set[str], view: Any, n_hours: int) -> RuleResult:
    plan = delivery_plan(view)
    index = next((i for i, planned in enumerate(plan) if planned.delivery_id == spec.delivery_id), None)
    problem: dict[str, Any] | None = None
    if index is None:
        problem = {"reason": "not_in_plan", "plan": [p.delivery_id for p in plan]}
    elif plan[index] != spec:
        problem = {"reason": "other_period", "period": _period(spec), "expected_period": _period(plan[index])}
    elif spec.delivery_id in loaded:
        problem = {"reason": "already_loaded"}
    else:
        missing = [p.delivery_id for p in plan[:index] if p.delivery_id not in loaded]
        if missing:
            problem = {"reason": "previous_not_loaded", "missing": missing}
    if problem is None:
        return _result("V10", True, hours_per_day=n_hours)
    return _result("V10", False, len(days), examples=[{"delivery_id": spec.delivery_id, **problem}], hours_per_day=n_hours)


def _rule_v11(days: pd.DataFrame, spec: DeliverySpec, n_hours: int) -> RuleResult:
    if spec.first_day is None or spec.last_day is None:     # the close has no period: it holds nothing
        outside = np.ones(len(days), dtype=bool)
    else:
        outside = ((days["date_key"] < date_key(spec.first_day)) | (days["date_key"] > date_key(spec.last_day))).to_numpy()
    return _result("V11", not outside.any(), int(outside.sum()), examples=_keys(days, outside), hours_per_day=n_hours)


def _rule_v12(days: pd.DataFrame, conn: sqlite3.Connection, n_hours: int) -> RuleResult:
    """A series-day that is already in the warehouse, or that comes twice in the delivery."""
    if days.empty:
        return _result("V12", True, hours_per_day=n_hours)
    combined = days["date_key"].to_numpy(dtype=np.int64) * _KEY + days["series_key"].to_numpy(dtype=np.int64)
    stored = known_series_days(conn, int(days["date_key"].min()), int(days["date_key"].max()))
    loaded = np.isin(combined, np.fromiter(stored, dtype=np.int64, count=len(stored))) if stored else np.zeros(len(days), dtype=bool)
    repeated = pd.Series(combined).duplicated(keep="first").to_numpy() & ~loaded
    bad = loaded | repeated
    examples = [{**e, "reason": "loaded" if loaded[i] else "repeated"} for e, i in zip(_keys(days, bad), np.flatnonzero(bad)[:EXAMPLE_LIMIT])]
    return _result("V12", not bad.any(), int(bad.sum()), examples=examples, hours_per_day=n_hours)


def _rule_v13(days: pd.DataFrame, spec: DeliverySpec, entry: ManifestEntry, out_dir: Path, n_hours: int) -> RuleResult:
    reasons = []
    if spec.kind == "close":
        if len(days):
            reasons.append("close_with_rows")
    elif days.empty:
        reasons.append("empty")
    if len(days) != entry.series_days:
        reasons.append("series_days_differ_from_manifest")
    actual: dict[str, str | None] = {}
    for key, name, expected in (("days", entry.days_file, entry.days_sha256), ("cube", entry.cube_file, entry.cube_sha256)):
        path = Path(out_dir) / name
        actual[key] = sha256_file(path) if path.is_file() else None
        if actual[key] is None:
            reasons.append(f"{key}_file_missing")
        elif actual[key] != expected:
            reasons.append(f"{key}_file_differs_from_manifest")
    if actual["days"] is not None and actual["cube"] is not None and delivery_digest(actual["days"], actual["cube"]) != entry.sha256:
        reasons.append("sha256_differs_from_manifest")
    if not reasons:
        return _result("V13", True, hours_per_day=n_hours)
    return _result("V13", False, len(days), examples=[{"delivery_id": entry.delivery_id, "reasons": reasons, "series_days": len(days),
                                                      "manifest_series_days": entry.series_days}], hours_per_day=n_hours)


def _rule_v14(days: pd.DataFrame, cube: tuple[np.ndarray, np.ndarray, np.ndarray], day_hours: tuple[int, int], n_hours: int) -> RuleResult:
    """The sums of each series-day of the file are the ones recomputed from the hours of the cube with the function that wrote them
    (``deliveries.delivery_sums``); a series-day the cube does not hold fails too."""
    date_keys, sales, stock = cube
    if days.empty:
        return _result("V14", True, hours_per_day=n_hours)
    sums = delivery_sums(sales, stock, day_hours)
    series = days["series_key"].to_numpy(dtype=np.int64)
    day_keys = days["date_key"].to_numpy(dtype=np.int64)
    if len(date_keys):
        column = np.searchsorted(date_keys, day_keys).clip(0, len(date_keys) - 1)
        present = (date_keys[column] == day_keys) & (series >= 0) & (series < sales.shape[0])
    else:                                       # a cube of no day holds none of the series-days of the file
        column, present = np.zeros(len(days), dtype=np.int64), np.zeros(len(days), dtype=bool)
    row = np.where(present, series, 0)
    differs = ~present
    first_column = np.full(len(days), "", dtype=object)
    first_column[~present] = "not_in_cube"
    for name in SUM_COLUMNS:
        stated = days[name].to_numpy(dtype=np.float64)
        expected = sums[name][row, column].astype(np.float64) if sums[name].size else np.zeros(len(days))
        wrong = present & ~np.isclose(stated, expected, rtol=SUM_TOLERANCE, atol=SUM_TOLERANCE)
        first_column[wrong & (first_column == "")] = name
        differs |= wrong
    examples = [{**e, "column": str(first_column[i])} for e, i in zip(_keys(days, differs), np.flatnonzero(differs)[:EXAMPLE_LIMIT])]
    return _result("V14", not differs.any(), int(differs.sum()), examples=examples, hours_per_day=n_hours)


def _rule_v15(days: pd.DataFrame, n_hours: int) -> RuleResult:
    """No forbidden column in the delivery's days."""
    extra = [name for name in days.columns if name in FORBIDDEN_COLUMNS]
    if not extra:
        return _result("V15", True, hours_per_day=n_hours)
    return _result("V15", False, len(days), examples=[{"columns": extra[:EXAMPLE_LIMIT], "count": len(extra)}], hours_per_day=n_hours)


def _warn(rule_id: str, days: pd.DataFrame, mask: np.ndarray, n_hours: int) -> RuleResult:
    """A warning over the series-days that match its rule: it warns when there are any."""
    mask = np.asarray(mask, dtype=bool)
    return _result(rule_id, not mask.any(), int(mask.sum()), examples=_keys(days, mask), hours_per_day=n_hours)


def _rule_i01(cube: tuple[np.ndarray, np.ndarray, np.ndarray], day_hours: tuple[int, int], n_hours: int) -> RuleResult:
    """Hours out of stock outside the analysis hours (0 to 5 and 22 to 23): they are counted and never recovered (D05)."""
    _keys_, _sales, stock = cube
    night = np.ones(24, dtype=bool)
    night[day_hours[0]:day_hours[1] + 1] = False
    out = (stock[:, :, night] == 1)
    per_day = out.sum(axis=2)
    return _result("I01", True, int((per_day > 0).sum()), int(out.sum()), [{"night_out_hours": int(out.sum()), "series_days": int((per_day > 0).sum())}],
                   hours_per_day=n_hours)


def validate_delivery(days: pd.DataFrame, cube: tuple[np.ndarray, np.ndarray, np.ndarray], spec: DeliverySpec, conn: sqlite3.Connection, view: Any, *,
                      entry: ManifestEntry, out_dir: Path, run_key: str) -> ValidationReport:
    """Validate one delivery against the plan, its manifest entry and what the warehouse holds; every rule of the delivery and of its days is evaluated.

    `days` and `cube` are the two files of the delivery as ``deliveries.read_delivery`` returns them (the series-days with their sums, and
    ``(date_keys, sales, stock)``); `view` has ``[calendar]`` (the plan of V10 and the analysis hours) and ``[days]`` (the thresholds of the warnings);
    `entry` and `out_dir` are the manifest line of the delivery and the folder of its two files, whose count and SHA-256 V13 compares. The warehouse
    is only read, and the frames are not changed.
    """
    _require_columns(days)
    first_hour, last_hour = view.calendar.day_hours
    n_hours = last_hour - first_hour + 1
    d = view.days
    discount, flag = days["discount"].to_numpy(), days["activity_flag"].to_numpy()
    with np.errstate(invalid="ignore"):
        zero = discount <= d.anomalous_max_discount
        above = discount > d.anomalous_min_discount
        below_half = (discount > d.anomalous_max_discount) & (discount < d.bands[1])
        no_cut_flag = (flag == 1) & (discount == d.bands[-1])
    results = {
        "V10": _rule_v10(days, spec, loaded_deliveries(conn), view, n_hours), "V11": _rule_v11(days, spec, n_hours),
        "V12": _rule_v12(days, conn, n_hours), "V13": _rule_v13(days, spec, entry, Path(out_dir), n_hours),
        "V14": _rule_v14(days, cube, (first_hour, last_hour), n_hours), "V15": _rule_v15(days, n_hours),
        "V20": _warn("V20", days, zero, n_hours), "V21": _warn("V21", days, above, n_hours), "V22": _warn("V22", days, below_half, n_hours),
        "V23": _warn("V23", days, no_cut_flag, n_hours), "V24": _warn("V24", days, days["day_state"].to_numpy() == UNFLAGGED, n_hours),
        "V25": _warn("V25", days, days["instock_hours"].to_numpy() == 0, n_hours),
        "I01": _rule_i01(cube, (first_hour, last_hour), n_hours),
        "I02": _result("I02", True, int((days["holiday_flag"] == 1).sum()), hours_per_day=n_hours),
    }
    report = ValidationReport(run_key, "", "", spec.delivery_id, len(days), _ordered(results), ())
    _log_verdict(report)
    return report


# --- the rules of the model (their tasks evaluate them) -----------------------------------------------------------------------------


def model_result(rule_id: str, *, passed: bool, series_days: int = 0, hours: int = 0, examples: list[dict] | None = None) -> RuleResult:
    """The result of a rule of the model (I03, I04, M01-M06), with the severity, scope and aggregation of its rule."""
    if rule_id not in MODEL_RULES:
        raise ValueError(f"{rule_id} no es una regla del modelo ({', '.join(MODEL_RULES)})")
    return _result(rule_id, passed, series_days, hours, examples)


def add_results(report: ValidationReport, results: Iterable[RuleResult]) -> ValidationReport:
    """The report with `results` added in the order of ``RULES``; a rule already in the report is refused (a result is written once)."""
    current = {r.rule_id: r for r in report.results}
    for result in results:
        if result.rule_id in current:
            raise ValueError(f"la regla {result.rule_id} ya está en el reporte de {report.run_key}")
        current[result.rule_id] = result
    return replace(report, results=_ordered(current), not_evaluated=tuple(r for r in report.not_evaluated if r not in current))


def combine_reports(source: ValidationReport, delivery: ValidationReport) -> ValidationReport:
    """The report of a run: the rules of the source and then those of the delivery, in the order of ``RULES``."""
    results = {r.rule_id: r for r in [*source.results, *delivery.results]}
    return replace(delivery, train_sha256=source.train_sha256 or delivery.train_sha256, eval_sha256=source.eval_sha256 or delivery.eval_sha256,
                   run_key=source.run_key or delivery.run_key, results=_ordered(results), not_evaluated=tuple(r for r in RULES if r not in results))


# --- report files ----------------------------------------------------------------------------------------------------------------


def _cell(text: str) -> str:
    """A table cell: a pipe or a newline would split the row."""
    return text.replace("|", "\\|").replace("\n", " ")


def _report_document(report: ValidationReport) -> dict[str, Any]:
    return {
        "run_key": report.run_key, "train_sha256": report.train_sha256, "eval_sha256": report.eval_sha256, "delivery_id": report.delivery_id,
        "series_days_delivery": report.series_days_delivery, "blocking_failed": report.blocking_failed, "not_evaluated": list(report.not_evaluated),
        "results": [{"rule_id": r.rule_id, "name_es": r.name_es, "severity": r.severity.value, "scope": r.scope, "aggregation": r.aggregation.value,
                     "status": r.status, "series_days_affected": r.series_days_affected, "hours_affected": r.hours_affected, "examples": r.examples}
                    for r in report.results],
    }


def _report_markdown(report: ValidationReport) -> str:
    verdict = "Rechazado: hay reglas bloqueantes que fallan." if report.blocking_failed else "Aceptado: ninguna regla bloqueante falla."
    lines = [
        "# Reporte de validación", "", f"- Corrida: `{report.run_key}`", f"- Resultado: **{verdict}**",
        f"- SHA-256 de `train.parquet`: `{report.train_sha256 or 'no disponible'}`", f"- SHA-256 de `eval.parquet`: `{report.eval_sha256 or 'no disponible'}`",
        f"- Entrega: {report.delivery_id or 'ninguna'}; series-días de la entrega: {report.series_days_delivery}", "", "## Reglas", "",
        "| ID | Regla | Severidad | Agregación | Estado | Series-días | Horas |", "| --- | --- | --- | --- | --- | ---: | ---: |",
    ]
    for r in report.results:
        lines.append(f"| {r.rule_id} | {_cell(r.name_es)} | {SEVERITY_ES[r.severity]} | {r.aggregation.value} | {STATUS_ES[r.status]} | "
                     f"{r.series_days_affected} | {r.hours_affected} |")
    if report.not_evaluated:
        lines += ["", "## No evaluadas", "", "No se pudieron evaluar porque una regla bloqueante anterior falló o porque las evalúa otra tarea: "
                  + ", ".join(report.not_evaluated) + "."]
    shown = [r for r in report.results if r.examples and (not r.passed or r.severity is Severity.INFO)]
    if shown:
        lines += ["", "## Ejemplos", ""]
        for r in shown:
            lines += [f"### {r.rule_id}: {_cell(r.name_es)}", ""] + [f"- `{json.dumps(example, ensure_ascii=False)}`" for example in r.examples] + [""]
    return "\n".join(lines).rstrip("\n") + "\n"


def write_report(report: ValidationReport, out_dir: Path) -> tuple[Path, Path]:
    """Write ``latest.json`` and ``latest.md`` and a copy per run in ``history/``; return the latest pair."""
    if not _SAFE_RUN_KEY.fullmatch(report.run_key):
        raise ValueError(f"run_key {report.run_key!r} no sirve como nombre de archivo")
    out_dir = Path(out_dir)
    text_json = json.dumps(_report_document(report), indent=2, ensure_ascii=False) + "\n"
    text_md = _report_markdown(report)
    for directory, stem in ((out_dir / "history", report.run_key), (out_dir, "latest")):
        write_atomic(directory / f"{stem}.json", text_json)
        write_atomic(directory / f"{stem}.md", text_md)
    return out_dir / "latest.json", out_dir / "latest.md"


def read_report(path: Path) -> ValidationReport:
    """The report written by ``write_report`` (``latest.json`` or a copy in ``history/``)."""
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    results = [RuleResult(r["rule_id"], r["name_es"], Severity(r["severity"]), r["scope"], Aggregation(r["aggregation"]), r["status"] == "pass",
                          r["series_days_affected"], r["hours_affected"], r["examples"]) for r in document["results"]]
    return ValidationReport(document["run_key"], document["train_sha256"], document["eval_sha256"], document["delivery_id"], document["series_days_delivery"],
                            results, tuple(document["not_evaluated"]))


__all__ = ["EXAMPLE_LIMIT", "RULES", "Aggregation", "Rule", "RuleResult", "Severity", "ValidationError", "ValidationReport", "add_results", "combine_reports",
           "model_result", "read_report", "validate_delivery", "validate_source", "write_report"]
