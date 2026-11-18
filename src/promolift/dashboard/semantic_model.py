"""The semantic model of the Power BI report: the single source of its tables and relationships (RF20, RF21, AC24, AC25; D35; plan, sections 19 and 20). Adapted from project
05's ``dashboard/semantic_model.py``.

Tables with their columns (type, description, unit) and relationships (all one to many, single direction, active) live here; the Arrow schema of every Parquet file, the
data dictionary and the HTML design come from this module. Names of tables, columns and files are in English; descriptions and labels in Spanish (RNF13). The measures
(DAX) and the five pages of the report live here too (U13): ``validate_model`` checks the tables and the relationships (U12) and, from U13, that every DAX reference and
every field of a visual is a column or a measure of the model, because no measure runs in the project.
"""

from __future__ import annotations

import re
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
    _c("tier", "int32", "Grupo sellado: el número que guarda el sello, de un recorrido que compara cada celda solo con el grupo abierto, así que dos celdas que se pisan "
                        "pueden quedar en grupos distintos (B1, D45); vacío si no se ordena. No es el grupo indistinguible."),
    _c("overlap_group", "int32", "Grupo indistinguible: las celdas unidas por intervalos que se pisan, directamente o por una cadena de celdas (componentes conexos del "
                                 "grafo de solapes, RF15); 1 es el del mayor aumento; análisis posterior al sello sobre los intervalos sellados (D45); vacío si no se ordena."),
    FIT_BLOCKS, SEAL_STATE,
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

# --- the measures and the pages (plan, section 20; U13) --------------------------------------------------------------------------------------------------------------

INTEGER, PERCENT, DECIMAL_3, DATETIME_FORMAT, TEXT_FORMAT = "#,0", "0.0%", "0.000", "yyyy-mm-dd hh:mm", "@"
_CELL = 'fact_cell_effect[ci_kind] = "two_way", fact_cell_effect[seal_state] = "sealed"'
_LAUNCH_CELLS = 'fact_cell_effect[scope] = "launch", fact_cell_effect[version_key] = "recovered", fact_cell_effect[seal_state] = "sealed"'
_OVERALL = 'fact_overall_effect[scope] = "launch", fact_overall_effect[seal_state] = "sealed"'
_RECOVERED_DAY = 'fact_daily_cell[version_key] = "recovered"'

MEASURES: tuple[Measure, ...] = (
    Measure("Aumento", f"CALCULATE ( SELECTEDVALUE ( fact_cell_effect[lift] ), {_CELL} )", PERCENT,
            "Aumento de la celda (o del conjunto de celdas que deja la selección) con el intervalo de dos vías y la configuración sellada; el alcance y la versión los dan los segmentadores y las filas del visual."),
    Measure("Aumento sellado", f'CALCULATE ( SELECTEDVALUE ( fact_cell_effect[lift] ), fact_cell_effect[scope] = "launch", {_CELL} )', PERCENT,
            "Aumento de la celda en el lanzamiento (los 90 días), con la configuración sellada: lo que la semana de prueba compara."),
    Measure("Límite inferior", f"CALCULATE ( SELECTEDVALUE ( fact_cell_effect[ci_low] ), {_CELL} )", PERCENT, "Límite inferior del intervalo del 95 % del aumento de la celda."),
    Measure("Límite superior", f"CALCULATE ( SELECTEDVALUE ( fact_cell_effect[ci_high] ), {_CELL} )", PERCENT, "Límite superior del intervalo del 95 % del aumento de la celda."),
    Measure("Celdas ordenadas", f'CALCULATE ( COUNTROWS ( fact_cell_effect ), fact_cell_effect[ranked] = TRUE (), {_LAUNCH_CELLS}, fact_cell_effect[ci_kind] = "two_way" )', INTEGER,
            "Celdas del lanzamiento con series suficientes para entrar en el ranking, en la demanda recuperada."),
    Measure("Grupos indistinguibles", f"CALCULATE ( DISTINCTCOUNT ( fact_cell_effect[overlap_group] ), fact_cell_effect[ranked] = TRUE (), {_LAUNCH_CELLS} )", INTEGER,
            "Grupos de celdas que no se distinguen entre sí (sus intervalos se pisan, directamente o por una cadena de celdas) en el ranking del lanzamiento; análisis "
            "posterior al sello (D45)."),
    Measure("Aumento total recuperado", f'CALCULATE ( SELECTEDVALUE ( fact_overall_effect[lift] ), fact_overall_effect[version_key] = "recovered", '
                                        f'fact_overall_effect[estimator] = "counterfactual", fact_overall_effect[control] = "regular", {_OVERALL} )', PERCENT,
            "Aumento total del lanzamiento con la demanda recuperada, contra el contrafactual de la misma serie y la misma hora. La medida fija la versión: el segmentador de versión no la cambia."),
    Measure("Aumento total crudo", f'CALCULATE ( SELECTEDVALUE ( fact_overall_effect[lift] ), fact_overall_effect[version_key] = "raw", '
                                   f'fact_overall_effect[estimator] = "counterfactual", fact_overall_effect[control] = "regular", {_OVERALL} )', PERCENT,
            "Aumento total del lanzamiento con la venta cruda, contra el contrafactual. La medida fija la versión: el segmentador de versión no la cambia."),
    Measure("Lo que esconden los quiebres", "[Aumento total recuperado] - [Aumento total crudo]", PERCENT,
            "Diferencia entre el aumento con la demanda recuperada y el crudo: lo que las horas sin stock escondían del efecto."),
    Measure("Aumento de la cuenta ingenua", f'CALCULATE ( SELECTEDVALUE ( fact_overall_effect[lift] ), fact_overall_effect[estimator] = "naive_pooled", '
                                            f'fact_overall_effect[version_key] = "raw", {_OVERALL} )', PERCENT,
            "La cuenta que sale mal: la venta media de las series-días con promoción sobre la de las regulares, sin serie ni día, con la venta cruda."),
    Measure("Aumento del día", f"DIVIDE ( CALCULATE ( SUM ( fact_daily_cell[observed] ), {_RECOVERED_DAY} ), CALCULATE ( SUM ( fact_daily_cell[counterfactual] ), {_RECOVERED_DAY} ) ) - 1", PERCENT,
            "Aumento de los días y las celdas elegidos con la demanda recuperada, desde lo que se emitió cada día de la semana de prueba."),
    Measure("Tasa de quiebre", "DIVIDE ( SUMX ( fact_hour_profile, fact_hour_profile[stockout_rate] * fact_hour_profile[series_days] ), SUM ( fact_hour_profile[series_days] ) )", PERCENT,
            "Parte de las series-días sin stock en las horas, los días y los grupos elegidos."),
    Measure("Venta media por hora", "DIVIDE ( SUMX ( fact_hour_profile, fact_hour_profile[mean_sales] * fact_hour_profile[series_days] ), SUM ( fact_hour_profile[series_days] ) )", DECIMAL_3,
            "Venta media por serie-día de las horas elegidas (venta normalizada, sin unidades)."),
    Measure("Demanda recuperada (%)", "DIVIDE ( SUM ( fact_stockout_daily[recovered_mass] ), SUM ( fact_stockout_daily[raw_mass] ) ) - 1", PERCENT,
            "Cuánto suma la recuperación a la venta cruda de las series-días elegidas (las que ya tienen su recuperación)."),
    Measure("WAPE del pronóstico", 'CALCULATE ( SELECTEDVALUE ( fact_forecast[wape] ), fact_forecast[scope] = "test", fact_forecast[seal_state] = "sealed" )', PERCENT,
            "WAPE de un método de pronóstico en la semana de prueba con la configuración sellada (si no, una fila posterior al sello vaciaría la cifra)."),
    Measure("WAPE de la recuperación", 'CALCULATE ( SELECTEDVALUE ( fact_recovery_check[wape_series] ), fact_recovery_check[mask] = "tail", fact_recovery_check[seal_state] = "sealed" )', PERCENT,
            "WAPE de la masa oculta por serie de un método de recuperación en el bloque elegido, sobre la máscara de cola, con la configuración sellada."),
    Measure("Celdas que mantienen su nivel (%)", 'DIVIDE ( CALCULATE ( COUNTROWS ( fact_replication ), fact_replication[consistent] = TRUE (), fact_replication[seal_state] = "sealed" ), '
                                                  'CALCULATE ( COUNTROWS ( fact_replication ), NOT ISBLANK ( fact_replication[consistent] ), fact_replication[seal_state] = "sealed" ) )', PERCENT,
            "Parte de las celdas comparables cuyo intervalo de la diferencia prueba − sellado contiene 0: el nivel se repite (C06)."),
    Measure("Veredicto", 'CALCULATE ( SELECTEDVALUE ( fact_evaluation_summary[verdict_es] ), fact_evaluation_summary[seal_state] = "sealed" )', TEXT_FORMAT,
            "Veredicto de un criterio con la configuración sellada."),
    Measure("Series-días con promoción (%)", "DIVIDE ( SUM ( fact_data_quality[promo] ), SUM ( fact_data_quality[series_days] ) )", PERCENT, "Parte de las series-días con promoción en los días elegidos."),
    Measure("Última fecha de cálculo", 'CALCULATE ( MAX ( dim_pipeline_run[as_of] ), dim_pipeline_run[status] = "ok" )', DATETIME_FORMAT, "Instante de cálculo de la última corrida terminada bien."),
    Measure("Reglas bloqueantes fallidas", 'CALCULATE ( COUNTROWS ( fact_validation ), fact_validation[severity] = "bloqueante", fact_validation[status] = "falla" )', INTEGER,
            "Resultados de reglas bloqueantes que fallaron, en las corridas cargadas."),
)

NOT_FILTERED = " (no lo filtra{plural} {names})"
_G, _D, _S = "Grupo", "Fecha", "Estado del día"
PAGES: tuple[Page, ...] = (
    Page("Qué promociones venden", (
        Visual("slicer", "Versión", ("dim_version[label_es]",), 0, 0, 6, 1),
        Visual("slicer", "Grupo", ("dim_cell[group_key]",), 6, 0, 6, 1),
        Visual("card", "Aumento total recuperado" + NOT_FILTERED.format(plural="", names="el grupo"), ("[Aumento total recuperado]",), 0, 1, 3, 1),
        Visual("card", "Lo que esconden los quiebres" + NOT_FILTERED.format(plural="", names="el grupo"), ("[Lo que esconden los quiebres]",), 3, 1, 3, 1),
        Visual("card", "Aumento de la cuenta ingenua" + NOT_FILTERED.format(plural="", names="el grupo"), ("[Aumento de la cuenta ingenua]",), 6, 1, 2, 1),
        Visual("card", "Celdas ordenadas", ("[Celdas ordenadas]",), 8, 1, 2, 1),
        Visual("card", "Grupos indistinguibles", ("[Grupos indistinguibles]",), 10, 1, 2, 1),
        Visual("barChart", "Celdas ordenadas por aumento, con su intervalo y su grupo indistinguible", ("dim_cell[label_es]", "[Aumento]", "[Límite inferior]", "[Límite superior]",
                                                                                                      "fact_cell_effect[overlap_group]"), 0, 2, 8, 7),
        Visual("table", "Celdas con pocas series, sin ordenar", ("dim_cell[label_es]", "fact_cell_effect[series]", "fact_cell_effect[ranked]", "[Aumento]"), 8, 2, 4, 7),
    )),
    Page("Las horas sin stock y la demanda que esconden", (
        Visual("slicer", _D, ("dim_date[date]",), 0, 0, 4, 1),
        Visual("slicer", _G, ("dim_group[label_es]",), 4, 0, 4, 1),
        Visual("slicer", _S, ("fact_hour_profile[day_state]",), 8, 0, 4, 1),
        Visual("lineChart", "Tasa de quiebre y venta media por hora", ("dim_hour[hour]", "dim_hour[in_analysis]", "[Tasa de quiebre]", "[Venta media por hora]"), 0, 1, 6, 4),
        Visual("lineChart", "Un día de ejemplo: venta observada y recuperada por hora" + NOT_FILTERED.format(plural="n", names="la fecha, el grupo ni el estado del día"),
               ("fact_example_day[hour]", "fact_example_day[observed]", "fact_example_day[recovered]"), 6, 1, 6, 4),
        Visual("table", "Comprobación de la recuperación en V1, V2 y la prueba" + NOT_FILTERED.format(plural="n", names="la fecha, el grupo ni el estado del día"),
               ("fact_recovery_check[scope]", "dim_method[label_es]", "[WAPE de la recuperación]", "fact_recovery_check[bias]", "fact_recovery_check[chosen]"), 0, 5, 6, 4),
        Visual("barChart", "Demanda recuperada (%) por grupo" + NOT_FILTERED.format(plural="n", names="el estado del día"), ("dim_group[label_es]", "[Demanda recuperada (%)]"), 6, 5, 6, 4),
    )),
    Page("Por descuento y por grupo", (
        Visual("barChart", "Aumento por banda de descuento, en las dos versiones", ("dim_band[depth_label_es]", "dim_version[label_es]", "fact_band_effect[lift]"), 0, 0, 6, 4),
        Visual("barChart", "Descuento sin marca: el aumento de los días con rebaja y sin promoción", ("dim_band[depth_label_es]", "fact_band_effect[lift]", "fact_band_effect[day_state]"), 6, 0, 6, 4),
        Visual("barChart", "Aumento por grupo de gestión", ("dim_group[label_es]", "fact_group_effect[lift]"), 0, 4, 6, 5),
        Visual("barChart", "La cuenta ingenua, el contrafactual y el control con cualquier día sin marca",
               ("fact_overall_effect[estimator]", "fact_overall_effect[control]", "fact_overall_effect[lift]", "dim_version[label_es]"), 6, 4, 6, 5),
    )),
    Page("La semana de prueba", (
        Visual("table", "Criterios C01-C10", ("fact_evaluation_summary[criterion_id]", "fact_evaluation_summary[name_es]", "fact_evaluation_summary[value]", "fact_evaluation_summary[threshold_es]",
                                              "fact_evaluation_summary[seen_by_research]", "fact_evaluation_summary[seen_by_planner]", "[Veredicto]"), 0, 0, 12, 3),
        Visual("card", "Celdas que mantienen su nivel (%)", ("[Celdas que mantienen su nivel (%)]",), 0, 3, 4, 1),
        Visual("scatter", "Aumento sellado contra el de la prueba, por celda (con la diagonal)", ("fact_replication[lift_launch]", "fact_replication[lift_test]", "dim_cell[label_es]"), 0, 4, 6, 5),
        Visual("barChart", "WAPE de F0, F1, F2a y F2 en la prueba", ("dim_method[label_es]", "[WAPE del pronóstico]"), 6, 3, 6, 3),
        Visual("table", "Aumento del día por banda en cada día de la prueba", ("dim_date[date]", "dim_cell[band_key]", "[Aumento del día]"), 6, 6, 6, 3),
    )),
    Page("Calidad de datos y corridas", (
        Visual("card", "Series-días con promoción (%)", ("[Series-días con promoción (%)]",), 0, 0, 4, 1),
        Visual("card", "Reglas bloqueantes fallidas", ("[Reglas bloqueantes fallidas]",), 4, 0, 4, 1),
        Visual("card", "Última fecha de cálculo", ("[Última fecha de cálculo]",), 8, 0, 4, 1),
        Visual("barChart", "Series-días de cada día según su estado", ("dim_date[date]", "fact_data_quality[promo]", "fact_data_quality[regular]", "fact_data_quality[unflagged_cut]",
                                                                      "fact_data_quality[anomalous]"), 0, 1, 8, 4),
        Visual("table", "Demostración de la fuga: una recuperación que lee el total diario", ("fact_leakage[check_es]", "fact_leakage[value]", "fact_leakage[note_es]"), 8, 1, 4, 4),
        Visual("table", "Reglas de validación", ("fact_validation[rule_id]", "fact_validation[name_es]", "fact_validation[severity]", "fact_validation[series_days_affected]",
                                                 "fact_validation[hours_affected]", "fact_validation[status]"), 0, 5, 6, 4),
        Visual("table", "Corridas", ("dim_pipeline_run[run_key]", "dim_pipeline_run[delivery_id]", "dim_pipeline_run[as_of]", "dim_pipeline_run[status]", "dim_pipeline_run[rows_issued]",
                                     "dim_pipeline_run[message]"), 6, 5, 6, 4),
    )),
)
MODEL = SemanticModel(TABLES, RELATIONSHIPS, MEASURES, PAGES)


def arrow_schema(table: Table) -> pa.Schema:
    """The Arrow schema of a table: its columns in order with their types."""
    return pa.schema([pa.field(c.name, ARROW_TYPES[c.dtype]) for c in table.columns])


def validate_model(model: SemanticModel) -> list[str]:
    """What is incoherent in `model` (empty when nothing is): unique table names, known types, keys among the columns, relationships between a dimension's whole key
    and a fact's column of the same type, one to many, single direction and active; then the measures (``_measure_problems``) and the pages (``_page_problems``)."""
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
    return problems + _measure_problems(model) + _page_problems(model)


# --- the static checks that stand in for running the measures (item 6 of the risks: no DAX runs anywhere in the project) -----------------------------------------------------------------

_COLUMN_REF = re.compile(r"(?<![\w'])([A-Za-z_]\w*)\[(\w+)\]")
_MEASURE_REF = re.compile(r"(?<![\w\]'])\[([^\[\]]+)\]")
_FUNCTION_CALL = re.compile(r"\b([A-Z][A-Z0-9.]*)(?=\s*\()")
_LITERAL_COMPARISON = re.compile(r'\b([a-z_]\w*)\[(\w+)\]\s*=\s*"([^"]*)"')
_REMOVES_FILTERS = re.compile(r"\b(ALL|ALLEXCEPT|ALLSELECTED|REMOVEFILTERS|CROSSFILTER|USERELATIONSHIP|KEEPFILTERS)\b")
DAX_FUNCTIONS = frozenset({"CALCULATE", "COUNTROWS", "DISTINCTCOUNT", "DIVIDE", "MAX", "SELECTEDVALUE", "SUM", "SUMX", "NOT", "ISBLANK", "TRUE"})


def dax_column_refs(dax: str) -> set[tuple[str, str]]:
    """The ``table[column]`` references of a DAX expression."""
    return set(_COLUMN_REF.findall(dax))


def dax_measure_refs(dax: str) -> set[str]:
    """The ``[Measure]`` references of a DAX expression: a bracket not attached to a table."""
    return set(_MEASURE_REF.findall(dax))


def visual_tables(model: SemanticModel, visual: Visual) -> set[str]:
    """The tables a visual reads: those of its columns and, through the DAX of its measures and of the measures they name, those the measures name by a column or whole."""
    found: set[str] = set()
    pending, seen = list(visual.fields), set()
    while pending:
        field = pending.pop()
        if field.startswith("["):
            name = field[1:-1]
            measure = next((m for m in model.measures if m.name_es == name), None)
            if measure is not None and name not in seen:
                seen.add(name)
                found |= {t.name for t in model.tables if re.search(rf"\b{t.name}\b", measure.dax)}
                pending += [f"[{n}]" for n in dax_measure_refs(measure.dax)]
        else:
            found.add(field.split("[")[0])
    return {t for t in found if any(table.name == t for table in model.tables)}


def _field_problem(model: SemanticModel, field: str) -> str | None:
    """Why the field of a visual does not resolve, or None."""
    if field.startswith("["):
        return None if any(f"[{m.name_es}]" == field for m in model.measures) else f"la medida {field} no existe"
    match = re.fullmatch(r"([A-Za-z_]\w*)\[(\w+)\]", field)
    if match is None:
        return f"el campo {field!r} no es una columna ni una medida"
    table, column = match.groups()
    return None if any(t.name == table and column in t.column_names for t in model.tables) else f"la columna {field} no existe"


def _measure_problems(model: SemanticModel) -> list[str]:
    problems: list[str] = []
    names = [m.name_es for m in model.measures]
    problems += [f"la medida [{n}] está repetida" for n in sorted({n for n in names if names.count(n) > 1})]
    columns = {t.name: {c.name: c for c in t.columns} for t in model.tables}
    uses: dict[str, set[str]] = {}
    for m in model.measures:
        label = f"[{m.name_es}]"
        if m.dax.count("(") != m.dax.count(")"):
            problems.append(f"{label}: paréntesis sin cerrar en el DAX")
        if m.dax.count('"') % 2:
            problems.append(f"{label}: comillas sin cerrar en el DAX")
        problems += [f"{label}: {t}[{c}] no existe" for t, c in sorted(dax_column_refs(m.dax)) if c not in columns.get(t, {})]
        problems += [f"{label}: {w} no es una tabla" for w in sorted(set(re.findall(r"\b(?:dim|fact)_\w+", m.dax)) - set(columns))]
        problems += [f"{label}: la función {f} no es de las que usa el plan" for f in sorted(set(_FUNCTION_CALL.findall(m.dax)) - DAX_FUNCTIONS)]
        uses[m.name_es] = dax_measure_refs(m.dax)
        problems += [f"{label}: la medida [{r}] no existe o es ella misma" for r in sorted(uses[m.name_es]) if r not in names or r == m.name_es]
        for table, column, literal in _LITERAL_COMPARISON.findall(m.dax):
            if column in columns.get(table, {}) and literal not in columns[table][column].description_es:
                problems.append(f"{label}: compara {table}[{column}] con '{literal}', que la columna no toma")
        problems += [f"{label}: {w} quita los filtros de los segmentadores" for w in sorted(set(_REMOVES_FILTERS.findall(m.dax)))]
        if not m.format_string or not m.description_es:
            problems.append(f"{label}: necesita un formato y una descripción")

    def circle(name: str, path: tuple[str, ...]) -> bool:
        return name in path or any(circle(n, (*path, name)) for n in uses.get(name, ()) if n in uses and n != name)

    problems += [f"las medidas [{n}] se llaman en círculo" for n in sorted(uses) if any(circle(r, (n,)) for r in uses[n] if r in uses and r != n)]
    return problems


def _page_problems(model: SemanticModel) -> list[str]:
    problems: list[str] = []
    titles = [p.name_es for p in model.pages]
    problems += [f"página repetida: {t}" for t in sorted({t for t in titles if titles.count(t) > 1})]
    related = {(r.dim_table, r.fact_table) for r in model.relationships}
    kinds = {t.name: t.kind for t in model.tables}
    for page in model.pages:
        if not page.visuals:
            problems.append(f"{page.name_es}: sin visuales")
        taken: dict[tuple[int, int], str] = {}
        for v in page.visuals:
            label = f"{page.name_es}: {v.title_es}"
            problems += [f"{label}: {why}" for field in v.fields if (why := _field_problem(model, field)) is not None]
            if v.kind == "slicer" and (len(v.fields) != 1 or v.fields[0].startswith("[")):
                problems.append(f"{label}: un segmentador usa una sola columna")
            tables = visual_tables(model, v)
            dims, facts = sorted(t for t in tables if kinds[t] == "dimension"), sorted(t for t in tables if kinds[t] == "fact")
            if len(facts) >= 2 and not dims:
                problems.append(f"{label}: dos hechos sin una dimensión que los una")
            if len(dims) >= 2 and not facts:
                problems.append(f"{label}: dos dimensiones sin un hecho que las una")
            problems += [f"{label}: {d} y {f} no se unen por ninguna relación" for d in dims for f in facts if (d, f) not in related]
            if v.w < 1 or v.h < 1 or v.x < 0 or v.y < 0 or v.x + v.w > PAGE_COLUMNS or v.y + v.h > PAGE_ROWS:
                problems.append(f"{label}: sale de la grilla de {PAGE_COLUMNS} x {PAGE_ROWS}")
                continue
            cells = [(cx, cy) for cx in range(v.x, v.x + v.w) for cy in range(v.y, v.y + v.h)]
            clash = next((taken[c] for c in cells if c in taken), None)
            if clash is not None:
                problems.append(f"{label}: se superpone con {clash}")
            taken.update({c: v.title_es for c in cells})
    return problems
