"""The semantic model of the Power BI report: the single source of its tables and relationships (RF20, RF21, AC24, AC25; D35; plan, sections 19 and 20). Adapted from project
05's ``dashboard/semantic_model.py``.

Tables with their columns (type, description, unit) and relationships (all one to many, single direction, active) live here; the Arrow schema of every Parquet file, the
data dictionary and the HTML design come from this module. Names of tables, columns and files are in English; descriptions and labels in Spanish (RNF13). The measures
(DAX) and the five pages of the report live here too (U13): ``validate_model`` checks the tables and the relationships (U12) and, from U13, that every DAX reference and
every field of a visual is a column or a measure of the model, because no measure runs in the project.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pyarrow as pa

ARROW_TYPES = {"int8": pa.int8(), "int16": pa.int16(), "int32": pa.int32(), "int64": pa.int64(), "float64": pa.float64(), "string": pa.string(), "bool": pa.bool_(),
               "date": pa.date32(), "datetime": pa.timestamp("us")}


@dataclass(frozen=True)
class Column:
    name: str
    dtype: str    # a key of ARROW_TYPES
    description_es: str
    unit: str | None = None


@dataclass(frozen=True)
class Table:
    name: str
    kind: Literal["dimension", "fact"]
    key: tuple[str, ...]          # a dimension's unique key or a fact's grain
    columns: tuple[Column, ...]
    description_es: str = ""

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.columns)


@dataclass(frozen=True)
class Relationship:
    rel_id: str
    dim_table: str
    dim_column: str
    fact_table: str
    fact_column: str
    cardinality: str = "one_to_many"
    cross_filter: str = "single"
    active: bool = True


@dataclass(frozen=True)
class Measure:
    name_es: str
    dax: str
    format_string: str
    description_es: str


@dataclass(frozen=True)
class Visual:
    kind: str                     # slicer, card, table, barChart, lineChart, scatter
    title_es: str
    fields: tuple[str, ...]       # "table[column]" or "[Measure]"
    x: int
    y: int
    w: int
    h: int


@dataclass(frozen=True)
class Page:
    name_es: str
    visuals: tuple[Visual, ...]


@dataclass(frozen=True)
class SemanticModel:
    tables: tuple[Table, ...]
    relationships: tuple[Relationship, ...]
    measures: tuple[Measure, ...] = ()
    pages: tuple[Page, ...] = ()

    def table(self, name: str) -> Table:
        return next(t for t in self.tables if t.name == name)

    def measure(self, name: str) -> Measure:
        return next(m for m in self.measures if m.name_es == name)


def _c(name: str, dtype: str, description_es: str, unit: str | None = None) -> Column:
    return Column(name, dtype, description_es, unit)


SCOPE_EFFECT = _c("scope", "string", "De dónde sale la cifra: launch (los 90 días del lanzamiento), valid_replication (la validación, con todo ajustado en el entrenamiento) o test (la semana de prueba).")
SCOPE_RECOVERY = _c("scope", "string", "Bloque medido: valid_v1 y valid_v2 (validación, métodos ajustados en el entrenamiento) o test (la semana de prueba).")
VERSION_KEY = _c("version_key", "string", "Versión de la venta: raw (la venta cruda) o recovered (la demanda recuperada).")
CELL_KEY = _c("cell_key", "string", "Celda: grupo de gestión por banda de descuento, como g<grupo>-b<banda>.")
GROUP_KEY = _c("group_key", "int8", "Grupo de gestión (el conjunto no los nombra).")
BAND_KEY = _c("band_key", "int8", "Banda de descuento, de 0 (la más profunda) a 6 (la más baja).")
CITY_KEY = _c("city_key", "int16", "Ciudad (el conjunto solo las numera).")
DATE_KEY = _c("date_key", "int32", "Fecha, como AAAAMMDD.")
HOUR = _c("hour", "int8", "Hora del día, de 0 a 23 (hora local supuesta, D05).")
METHOD_KEY = _c("method_key", "string", "Método: de recuperación (r0, r1, r2@κ, r3) o de pronóstico (f0 a f2).")
DAY_STATE = _c("day_state", "string", "Estado del día de la serie: promo, regular, unflagged_cut o anomalous.")
RUN_KEY = _c("run_key", "string", "Corrida que lo escribió.")
SEAL_STATE = _c("seal_state", "string", "sealed (la configuración sellada) o post_seal (otra, posterior al sello).")
FIT_BLOCKS = _c("fit_blocks", "string", "Con qué bloques se ajustó el método que dio la cifra (train, o el período del lanzamiento): nada se mide como fuera de muestra con su propio bloque.")
LIFT = _c("lift", "float64", "Aumento: venta observada sobre contrafactual, menos 1; una asociación dentro de la serie, no una causa.", "fracción")
CI_LOW = _c("ci_low", "float64", "Límite inferior del intervalo del 95 %.", "fracción")
CI_HIGH = _c("ci_high", "float64", "Límite superior del intervalo del 95 %.", "fracción")
SERIES = _c("series", "int32", "Series (tienda por producto) con series-días en la unidad.", "series")
SERIES_DAYS = _c("series_days", "int32", "Series-días en la unidad.", "series-días")

DIM_DATE = Table("dim_date", "dimension", ("date_key",), (
    DATE_KEY, _c("date", "date", "Fecha."), _c("weekday_es", "string", "Nombre del día de la semana."), _c("is_weekend", "bool", "Sábado o domingo."),
    _c("holiday_flag", "int8", "1 si alguna serie marca el día como feriado, 0 si no."), _c("block", "string", "Bloque de la partición en el tiempo."),
    _c("block_es", "string", "Bloque de la partición, en español."),
), "Calendario de los días cargados que ya habían cerrado, con su bloque.")
DIM_HOUR = Table("dim_hour", "dimension", ("hour",), (
    HOUR, _c("in_analysis", "bool", "La hora está entre las que analiza el proyecto (06 a 21)."), _c("label_es", "string", "La hora, como «06:00»."),
), "Las 24 horas del día.")
DIM_GROUP = Table("dim_group", "dimension", ("group_key",), (GROUP_KEY, _c("label_es", "string", "Grupo, como «Grupo 3».")), "Los grupos de gestión.")
DIM_BAND = Table("dim_band", "dimension", ("band_key",), (
    BAND_KEY, _c("discount_low", "float64", "Borde bajo del descuento (como factor del precio) de la banda."), _c("discount_high", "float64", "Borde alto del descuento de la banda."),
    _c("depth_label_es", "string", "Profundidad de la rebaja, como «más del 50 %» o «hasta 5 %»."),
), "Las siete bandas de descuento.")
DIM_CELL = Table("dim_cell", "dimension", ("cell_key",), (
    CELL_KEY, GROUP_KEY, BAND_KEY, _c("label_es", "string", "Celda, como «Grupo 3, rebaja de 40 a 50 %»."),
), "Las celdas: cada grupo de gestión con cada banda; lleva el grupo y la banda como columnas (sin copo de nieve).")
DIM_VERSION = Table("dim_version", "dimension", ("version_key",), (VERSION_KEY, _c("label_es", "string", "Versión, en español.")), "Las dos versiones de la venta.")
DIM_METHOD = Table("dim_method", "dimension", ("method_key",), (
    METHOD_KEY, _c("kind_es", "string", "Clase: recuperación o pronóstico."), _c("label_es", "string", "Método, en español."),
), "Los métodos de recuperación y de pronóstico.")
DIM_CITY = Table("dim_city", "dimension", ("city_key",), (CITY_KEY, _c("label_es", "string", "Ciudad, como «Ciudad 3».")), "Las ciudades.")
DIM_MODEL = Table("dim_model", "dimension", ("model_key",), (
    _c("model_key", "string", "Modelo congelado del lanzamiento (su versión)."), _c("model_version", "string", "Versión del modelo."),
    _c("recovery_method", "string", "Método de recuperación elegido en V1."), _c("kappa", "float64", "κ de R2; vacía para otros métodos."),
    _c("config_sha256", "string", "Huella de la configuración sellada del modelo."), SEAL_STATE,
), "El modelo congelado del lanzamiento.")
DIM_PIPELINE_RUN = Table("dim_pipeline_run", "dimension", ("run_key",), (
    RUN_KEY, _c("started_at", "datetime", "Inicio."), _c("finished_at", "datetime", "Fin."), _c("status", "string", "Estado: running, ok, failed, rejected o no_delivery."),
    _c("delivery_id", "string", "Entrega que cargó."), _c("as_of", "datetime", "Instante de cálculo de la corrida."), _c("train_sha256", "string", "Huella de train.parquet."),
    _c("eval_sha256", "string", "Huella de eval.parquet."), _c("series_days_delivery", "int64", "Series-días de la entrega.", "series-días"),
    _c("rows_issued", "int64", "Filas emitidas.", "filas"), _c("peak_working_set_mb", "float64", "Pico del conjunto de trabajo.", "MB"),
    _c("peak_commit_mb", "float64", "Pico de memoria confirmada (informativo).", "MB"), _c("memory_counter", "string", "Contador de memoria que dio las cifras."),
    _c("message", "string", "Mensaje de la corrida."),
), "Las corridas del flujo.")

FACT_CELL_EFFECT = Table("fact_cell_effect", "fact", ("scope", "version_key", "cell_key", "ci_kind", "seal_state"), (
    SCOPE_EFFECT, VERSION_KEY, CELL_KEY, _c("observed", "float64", "Suma de la venta observada de las series-días de la celda en las horas de 06 a 21 (venta normalizada)."),
    _c("counterfactual", "float64", "Suma de lo que el modelo dice para esas series-días sin promoción (venta normalizada)."), LIFT, CI_LOW, CI_HIGH,
    _c("ci_kind", "string", "Intervalo: two_way (series y días) o series_only."), SERIES, SERIES_DAYS,
    _c("ranked", "bool", "La celda tiene series suficientes y entra en el ranking."), _c("rank", "int32", "Lugar en el ranking por aumento (1 es el mayor); vacío si no se ordena."),
    _c("tier", "int32", "Grupo indistinguible: las celdas del mismo número no se distinguen entre sí; vacío si no se ordena."), FIT_BLOCKS, SEAL_STATE,
), "El aumento de cada celda por alcance y versión, con su intervalo y su lugar en el ranking.")
FACT_BAND_EFFECT = Table("fact_band_effect", "fact", ("scope", "version_key", "band_key", "control", "day_state", "seal_state"), (
    SCOPE_EFFECT, VERSION_KEY, BAND_KEY, _c("control", "string", "Días de control: regular (sin marca y sin rebaja) o any_flag0 (cualquier día sin marca)."), LIFT, CI_LOW, CI_HIGH,
    SERIES, SERIES_DAYS, _c("day_state", "string", "Días medidos: promo, o unflagged_cut (rebaja sin marca: su propio efecto)."), SEAL_STATE,
), "El aumento de cada banda de descuento, y el de los días con rebaja sin marca.")
FACT_GROUP_EFFECT = Table("fact_group_effect", "fact", ("scope", "version_key", "group_key", "seal_state"), (
    SCOPE_EFFECT, VERSION_KEY, GROUP_KEY, LIFT, CI_LOW, CI_HIGH, SERIES, SEAL_STATE,
), "El aumento de cada grupo de gestión.")
FACT_OVERALL_EFFECT = Table("fact_overall_effect", "fact", ("scope", "version_key", "estimator", "control", "seal_state"), (
    SCOPE_EFFECT, VERSION_KEY, _c("estimator", "string", "naive_pooled (la cuenta que mezcla productos) o counterfactual (la misma serie y la misma hora)."),
    _c("control", "string", "Días de control: regular o any_flag0."), LIFT, CI_LOW, CI_HIGH, SERIES_DAYS, SEAL_STATE,
), "El aumento total, con la cuenta ingenua al lado del contrafactual.")
FACT_DAILY_CELL = Table("fact_daily_cell", "fact", ("date_key", "version_key", "cell_key"), (
    DATE_KEY, VERSION_KEY, CELL_KEY, _c("observed", "float64", "Suma de la venta observada de las series-días con promoción de la celda ese día."),
    _c("counterfactual", "float64", "Suma de lo que el modelo sellado dice para esas series-días, con el factor de ese día."), _c("lift", "float64", "Aumento del día de la celda.", "fracción"),
    SERIES_DAYS, _c("stockout_hours", "int32", "Horas sin stock de 06 a 21 de esas series-días.", "horas"),
), "Lo que se emitió cada día de la semana de prueba por celda.")
FACT_HOUR_PROFILE = Table("fact_hour_profile", "fact", ("date_key", "group_key", "hour", "day_state"), (
    DATE_KEY, GROUP_KEY, HOUR, DAY_STATE, SERIES_DAYS, _c("mean_sales", "float64", "Venta media de la hora por serie-día (venta normalizada).", "venta normalizada"),
    _c("stockout_rate", "float64", "Parte de las series-días sin stock en la hora.", "proporción"),
), "La venta y los quiebres por hora, día, grupo y estado del día.")
FACT_STOCKOUT_DAILY = Table("fact_stockout_daily", "fact", ("date_key", "city_key", "group_key"), (
    DATE_KEY, CITY_KEY, GROUP_KEY, SERIES_DAYS, _c("stockout_rate", "float64", "Parte de las horas de 06 a 21 sin stock.", "proporción"),
    _c("raw_mass", "float64", "Venta cruda de las series-días ya recuperadas (venta normalizada)."),
    _c("recovered_mass", "float64", "Demanda recuperada de esas mismas series-días (venta normalizada); vacía si ninguna se recuperó todavía."),
), "Los quiebres y la demanda recuperada por día, ciudad y grupo.")
FACT_RECOVERY_CHECK = Table("fact_recovery_check", "fact", ("scope", "mask", "method_key", "seal_state"), (
    SCOPE_RECOVERY, _c("mask", "string", "Máscara sintética: tail (la cola del día, como un quiebre) o mcar (tres horas al azar, un contraste)."), METHOD_KEY, FIT_BLOCKS,
    _c("wape_series", "float64", "WAPE de la masa oculta por serie.", "fracción"), _c("bias", "float64", "Sesgo total de la masa recuperada.", "fracción"),
    _c("bias_promo", "float64", "Sesgo en los días con promoción.", "fracción"), _c("bias_regular", "float64", "Sesgo en los días regulares.", "fracción"),
    _c("lift_bias", "float64", "Sesgo que eso induce en el aumento.", "fracción"), _c("ci_low_vs_r1", "float64", "Límite inferior del intervalo del 95 % de WAPE(método) − WAPE(R1).", "fracción"),
    _c("ci_high_vs_r1", "float64", "Límite superior del intervalo del 95 % de WAPE(método) − WAPE(R1).", "fracción"), _c("chosen", "bool", "Es el método que eligió el lanzamiento."), SEAL_STATE,
), "La comprobación de la recuperación con horas que se conocen.")
FACT_FORECAST = Table("fact_forecast", "fact", ("scope", "method_key", "seal_state"), (
    _c("scope", "string", "valid (validación, todo ajustado en el entrenamiento) o test (la semana de prueba)."), METHOD_KEY, FIT_BLOCKS,
    _c("wape", "float64", "WAPE de la masa de las horas con stock de las series-días con promoción.", "fracción"), _c("bias", "float64", "Sesgo del pronóstico.", "fracción"),
    SERIES_DAYS, SEAL_STATE,
), "Los pronósticos F0, F1, F2a y F2: si el aumento de la celda agrega información.")
FACT_REPLICATION = Table("fact_replication", "fact", ("cell_key", "seal_state"), (
    CELL_KEY, _c("lift_launch", "float64", "Aumento sellado del lanzamiento.", "fracción"), _c("ci_low_launch", "float64", "Límite inferior del lanzamiento.", "fracción"),
    _c("ci_high_launch", "float64", "Límite superior del lanzamiento.", "fracción"), _c("lift_test", "float64", "Aumento de la semana de prueba.", "fracción"),
    _c("ci_low_test", "float64", "Límite inferior de la prueba.", "fracción"), _c("ci_high_test", "float64", "Límite superior de la prueba.", "fracción"),
    _c("diff_ci_low", "float64", "Límite inferior del intervalo de la diferencia prueba − sellado.", "fracción"),
    _c("diff_ci_high", "float64", "Límite superior del intervalo de la diferencia prueba − sellado.", "fracción"),
    _c("consistent", "bool", "El intervalo de la diferencia contiene 0; vacío si la celda no tiene series suficientes en las dos."), SEAL_STATE,
), "El aumento sellado de cada celda frente al de la semana de prueba.")
FACT_EVALUATION_SUMMARY = Table("fact_evaluation_summary", "fact", ("criterion_id", "seal_state"), (
    _c("criterion_id", "string", "Criterio, de C01 a C10."), _c("name_es", "string", "Nombre del criterio."), _c("value", "float64", "Valor medido."),
    _c("baseline_value", "float64", "Valor de la base con que se compara."), _c("ci_low", "float64", "Límite inferior del intervalo."), _c("ci_high", "float64", "Límite superior del intervalo."),
    _c("threshold_es", "string", "Umbral, en español."), _c("passed", "bool", "Cumple; vacío en el informativo."), _c("seen_by_research", "string", "Si la investigación lo vio antes."),
    _c("seen_by_planner", "string", "Si el plan lo vio antes."), _c("verdict_es", "string", "Veredicto, en español."), SEAL_STATE,
), "Los criterios de la prueba y su veredicto.")
FACT_EXAMPLE_DAY = Table("fact_example_day", "fact", ("hour",), (
    HOUR, _c("observed", "float64", "Venta observada de la hora (venta normalizada)."), _c("recovered", "float64", "Demanda recuperada de la hora."),
    _c("in_stock", "int8", "1 si la hora tenía stock, 0 si no."),
), "La serie-día de ejemplo (la de mediana de la regla fija del plan, sección 21): venta observada y recuperada por hora.")
FACT_LEAKAGE = Table("fact_leakage", "fact", ("check",), (
    _c("check", "string", "Comprobación."), _c("check_es", "string", "Qué se hizo, en español."), _c("value", "float64", "WAPE por serie en la máscara de V2.", "fracción"),
    _c("note_es", "string", "Lo que enseña."),
), "La demostración de la fuga: una recuperación que lee el total diario parece casi perfecta.")
FACT_DATA_QUALITY = Table("fact_data_quality", "fact", ("date_key",), (
    DATE_KEY, SERIES_DAYS, _c("promo", "int32", "Series-días con promoción.", "series-días"), _c("regular", "int32", "Series-días regulares (sin marca y sin rebaja).", "series-días"),
    _c("unflagged_cut", "int32", "Series-días con rebaja y sin marca.", "series-días"), _c("anomalous", "int32", "Series-días con descuento 0 o mayor que 1.", "series-días"),
    _c("fully_out", "int32", "Series-días sin stock de 06 a 21.", "series-días"), _c("stockout_rate", "float64", "Parte de las horas de 06 a 21 sin stock.", "proporción"),
), "La calidad de los datos, día por día.")
FACT_VALIDATION = Table("fact_validation", "fact", ("run_key", "rule_id"), (
    RUN_KEY, _c("rule_id", "string", "Regla de validación."), _c("name_es", "string", "Nombre de la regla."), _c("severity", "string", "bloqueante, advertencia o informativa."),
    _c("scope", "string", "Alcance: source, delivery, days o model."), _c("aggregation", "string", "Cómo se agrega entre corridas: source, per_run o latest."),
    _c("status", "string", "pasa, falla (bloqueante que no pasa) o advierte."), _c("series_days_affected", "int64", "Series-días afectadas.", "series-días"),
    _c("hours_affected", "int64", "Horas afectadas.", "horas"),
), "El resultado de cada regla en cada corrida.")

TABLES: tuple[Table, ...] = (DIM_DATE, DIM_HOUR, DIM_GROUP, DIM_BAND, DIM_CELL, DIM_VERSION, DIM_METHOD, DIM_CITY, DIM_MODEL, DIM_PIPELINE_RUN,
                             FACT_CELL_EFFECT, FACT_BAND_EFFECT, FACT_GROUP_EFFECT, FACT_OVERALL_EFFECT, FACT_DAILY_CELL, FACT_HOUR_PROFILE, FACT_STOCKOUT_DAILY,
                             FACT_RECOVERY_CHECK, FACT_FORECAST, FACT_REPLICATION, FACT_EVALUATION_SUMMARY, FACT_EXAMPLE_DAY, FACT_LEAKAGE, FACT_DATA_QUALITY, FACT_VALIDATION)
# (dimension, its key, the facts it filters), in the order of the plan's table of relationships (R01 to R21)
_RELATIONSHIPS = (
    ("dim_date", "date_key", ("fact_daily_cell", "fact_hour_profile", "fact_stockout_daily", "fact_data_quality")),
    ("dim_cell", "cell_key", ("fact_cell_effect", "fact_daily_cell", "fact_replication")),
    ("dim_band", "band_key", ("fact_band_effect",)),
    ("dim_group", "group_key", ("fact_group_effect", "fact_hour_profile", "fact_stockout_daily")),
    ("dim_version", "version_key", ("fact_cell_effect", "fact_band_effect", "fact_group_effect", "fact_overall_effect", "fact_daily_cell")),
    ("dim_method", "method_key", ("fact_recovery_check", "fact_forecast")),
    ("dim_hour", "hour", ("fact_hour_profile",)),
    ("dim_city", "city_key", ("fact_stockout_daily",)),
    ("dim_pipeline_run", "run_key", ("fact_validation",)),
)
RELATIONSHIPS: tuple[Relationship, ...] = tuple(
    Relationship(f"R{number:02d}", dim, key, fact, key) for number, (dim, key, fact) in enumerate(
        ((dim, key, fact) for dim, key, facts in _RELATIONSHIPS for fact in facts), start=1))
PAGE_COLUMNS, PAGE_ROWS = 12, 9
MODEL = SemanticModel(TABLES, RELATIONSHIPS)


def arrow_schema(table: Table) -> pa.Schema:
    """The Arrow schema of a table: its columns in order with their types."""
    return pa.schema([pa.field(c.name, ARROW_TYPES[c.dtype]) for c in table.columns])


def validate_model(model: SemanticModel) -> list[str]:
    """What is incoherent in `model` (empty when nothing is): unique table names, known types, keys among the columns, and relationships between a dimension's whole key
    and a fact's column of the same type, one to many, single direction and active."""
    problems: list[str] = []
    names = [t.name for t in model.tables]
    if len(set(names)) != len(names):
        problems.append("hay tablas repetidas")
    by_name = {t.name: t for t in model.tables}
    for table in model.tables:
        columns = {c.name: c for c in table.columns}
        if len(columns) != len(table.columns):
            problems.append(f"{table.name} repite una columna")
        problems += [f"{table.name}[{c.name}] tiene un tipo desconocido {c.dtype}" for c in table.columns if c.dtype not in ARROW_TYPES]
        problems += [f"la clave {k} de {table.name} no es una columna" for k in table.key if k not in columns]
    for r in model.relationships:
        dim, fact = by_name.get(r.dim_table), by_name.get(r.fact_table)
        if dim is None or fact is None or dim.kind != "dimension" or fact.kind != "fact":
            problems.append(f"{r.rel_id} no une una dimensión con un hecho")
            continue
        if dim.key != (r.dim_column,):
            problems.append(f"{r.rel_id} no usa la clave entera de {dim.name}")
        dim_col = next((c for c in dim.columns if c.name == r.dim_column), None)
        fact_col = next((c for c in fact.columns if c.name == r.fact_column), None)
        if dim_col is None or fact_col is None or dim_col.dtype != fact_col.dtype:
            problems.append(f"{r.rel_id}: {r.fact_table}[{r.fact_column}] no es una columna del tipo de {r.dim_table}[{r.dim_column}]")
        if (r.cardinality, r.cross_filter, r.active) != ("one_to_many", "single", True):
            problems.append(f"{r.rel_id} no es uno a varios, de filtro unidireccional y activa")
    return problems
