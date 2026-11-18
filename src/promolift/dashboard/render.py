"""The HTML design of the Power BI report, generated from the semantic model and the exported Parquet (RF21, AC25; plan, section 20; D35). Adapted from project 05's
``dashboard/render.py``; it is not imported from it.

One self-contained page (inline CSS, inline SVG, no scripts, no fonts or images from the network) with the steps to build the report in Power BI Desktop, the diagram of the model, the
relationships, the Power Query code of each table, the DAX measures and the five pages placed on a 12 x 9 grid, each visual with a preview drawn from the exported tables. Nothing here is
typed by hand twice: change ``semantic_model.py`` and render again.

Rules for what a preview shows. Every text that comes from the data goes through ``html.escape``. The previews are the figures of the exported tables with no slicer applied: the document says
that no measure was run (there is no Power BI here), so a card is what the table says, not what the DAX would give. An evaluation shows the sealed rows of the test week and, when there are
none, says that what it shows is validation and not the test. A lift is an association within the series and the page never calls it anything else (D09); the cells that overlap are drawn in
the same color and the page says that they do not differ from each other (D13). The file is written through ``files.write_atomic``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from html import escape
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from promolift.cube import ATTRIBUTION
from promolift.dashboard import svg
from promolift.dashboard.semantic_model import PAGE_COLUMNS, PAGE_ROWS, Page, SemanticModel, Visual, dax_measure_refs, validate_model
from promolift.files import write_atomic
from promolift.registry import RunMeta

logger = logging.getLogger(__name__)

PAGE_WIDTH_PX, PAGE_HEIGHT_PX = 1280, 720
CELL_W, CELL_H = PAGE_WIDTH_PX / PAGE_COLUMNS, PAGE_HEIGHT_PX / PAGE_ROWS
HEADER_PX = 26
TABLE_ROWS = 9              # the most rows a table preview shows
DAYS_SHOWN = 14             # the most days the bars of page 5 show
TITLE = "Diseño del tablero de Power BI: qué promociones venden de verdad, con la demanda que esconden los quiebres"
SECTIONS = (
    ("armado", "Cómo armarlo en Power BI Desktop"),
    ("modelo", "El modelo en estrella"),
    ("relaciones", "Relaciones"),
    ("consultas", "Power Query: una consulta por tabla"),
    ("medidas", "Medidas DAX"),
    ("paginas", "Las cinco páginas"),
    ("fuente", "Fuente y licencia"),
)
KIND_ES = {"slicer": "Segmentador", "card": "Tarjeta", "lineChart": "Gráfico de líneas", "barChart": "Gráfico de barras", "table": "Tabla", "scatter": "Dispersión"}
SCOPE_ES = {"valid_v1": "V1", "valid_v2": "V2", "test": "Prueba", "valid": "Validación", "launch": "Lanzamiento", "valid_replication": "Réplica en la validación"}
DASH = "—"
CSS = """
:root{color-scheme:light;--surface:#fcfcfb;--panel:#f3f2ef;--text:#0b0b0b;--text-2:#52514e;--muted:#6f6e69;--line:#d9d8d3;--accent:#256abf;
--series-1:#2a78d6;--series-2:#eb6834;--series-3:#1baf7a;--series-4:#eda100;--series-5:#e87ba4;--series-6:#008300;--series-7:#6250d6;--series-8:#e34948}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])){color-scheme:dark;--surface:#1a1a19;--panel:#242422;--text:#f0efec;--text-2:#c3c2b7;--muted:#a3a299;--line:#3a3a37;--accent:#6da7ec;
--series-1:#3987e5;--series-2:#d95926;--series-3:#199e70;--series-4:#c98500;--series-5:#d55181;--series-6:#008300;--series-7:#9085e9;--series-8:#e66767}}
:root[data-theme="dark"]{color-scheme:dark;--surface:#1a1a19;--panel:#242422;--text:#f0efec;--text-2:#c3c2b7;--muted:#a3a299;--line:#3a3a37;--accent:#6da7ec;
--series-1:#3987e5;--series-2:#d95926;--series-3:#199e70;--series-4:#c98500;--series-5:#d55181;--series-6:#008300;--series-7:#9085e9;--series-8:#e66767}
*{box-sizing:border-box}
body{margin:0;background:var(--surface);color:var(--text);font:16px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1180px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:1.6rem;line-height:1.25;margin:0 0 4px}h2{font-size:1.3rem;margin:48px 0 8px;padding-top:8px;border-top:1px solid var(--line)}
h3{font-size:1.05rem;margin:28px 0 8px}p,li{max-width:78ch}a{color:var(--accent)}
.lead{color:var(--text-2);margin:0 0 16px}.meta{display:flex;flex-wrap:wrap;gap:8px 24px;color:var(--text-2);font-size:.9rem;margin:12px 0}
nav ul{display:flex;flex-wrap:wrap;gap:4px 16px;padding:0;list-style:none;margin:16px 0}
code,pre{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:.85rem}
pre{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:10px 12px;overflow-x:auto;margin:6px 0;white-space:pre}
table{border-collapse:collapse;width:100%;font-size:.88rem}th,td{border-bottom:1px solid var(--line);padding:5px 8px;text-align:left;vertical-align:top}
th{color:var(--text-2);font-weight:600;background:var(--surface)}td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
.scroll{overflow-x:auto}.warn{border-left:3px solid var(--series-4);padding:4px 12px;background:var(--panel);margin:12px 0}
.model-svg{width:100%;height:auto;display:block}.model-svg .box{fill:var(--panel);stroke:var(--line)}.model-svg .dim{stroke:var(--series-1)}
.model-svg .fact{stroke:var(--series-2)}.model-svg text{fill:var(--text);font-size:12px}.model-svg .small{fill:var(--text-2);font-size:10px}
.model-svg .rel{stroke:var(--muted);stroke-width:1;fill:none;opacity:.55}.model-svg .card{font-weight:700;fill:var(--accent)}
.canvas-wrap{overflow-x:auto;border:1px solid var(--line);border-radius:8px;background:var(--panel);padding:8px}
.canvas{display:grid;grid-template-columns:repeat(12,1fr);grid-template-rows:repeat(9,1fr);gap:6px;aspect-ratio:16/9;min-width:960px;max-width:1280px}
.visual{background:var(--surface);border:1px solid var(--line);border-radius:6px;overflow:hidden;display:flex;flex-direction:column;min-width:0;min-height:0}
.visual header{display:flex;justify-content:space-between;gap:6px;padding:2px 8px;font-size:.75rem;color:var(--text-2);height:26px;align-items:center}
.visual header b{color:var(--text);font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.visual header span{white-space:nowrap;color:var(--muted)}
.visual .body{flex:1;min-height:0;padding:0 8px 3px;overflow:hidden;font-size:.75rem}.visual .body svg{max-width:100%;height:auto;display:block}
.big{font-size:1.2rem;font-weight:700;line-height:1.15;font-variant-numeric:tabular-nums;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.sub{color:var(--muted);font-size:.65rem;line-height:1.1}
.chips{display:flex;flex-wrap:nowrap;gap:3px;overflow:hidden}.chip{white-space:nowrap;border:1px solid var(--line);border-radius:10px;padding:0 6px;font-size:.7rem;color:var(--text-2)}
.visual table{font-size:.7rem}.visual th,.visual td{padding:1px 5px}.rows p{margin:1px 0;font-size:.75rem}
.multiples{display:grid;grid-template-columns:repeat(4,1fr);gap:2px 6px}.multiples figure{margin:0;min-width:0}.multiples figcaption{font-size:.6rem;color:var(--text-2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
svg .svg-grid{stroke:var(--line);stroke-width:1}svg .svg-axis{stroke:var(--muted);stroke-width:1}
svg .svg-tick,svg .svg-legend,svg .svg-note,svg .svg-value{fill:var(--text-2);font-size:10px}svg .svg-value{fill:var(--text)}
svg .svg-hit{fill:transparent}svg .svg-hit:hover{fill:var(--text);fill-opacity:.15}
.placement td:first-child{white-space:nowrap}
@media print{.canvas-wrap{break-inside:avoid}body{font-size:12px}}
"""




# --- data ---------------------------------------------------------------------------------------------------------------------


class _Data:
    """The exported tables the previews are drawn from (a missing file is an empty table with its columns) and what their files say about the run."""

    def __init__(self, parquet_dir: Path, model: SemanticModel) -> None:
        self.t: dict[str, pd.DataFrame] = {}
        for table in model.tables:
            path = Path(parquet_dir) / f"{table.name}.parquet"
            self.t[table.name] = pd.read_parquet(path) if path.is_file() else pd.DataFrame(columns=list(table.column_names))
        path = Path(parquet_dir) / "dim_pipeline_run.parquet"
        metadata = pq.read_schema(path).metadata or {} if path.is_file() else {}
        self.train_sha256 = metadata.get(b"promolift.train_sha256", DASH.encode()).decode("utf-8", "replace")
        self.method_es = dict(zip(self.t["dim_method"]["method_key"], self.t["dim_method"]["label_es"], strict=True))
        self.cell_es = dict(zip(self.t["dim_cell"]["cell_key"], self.t["dim_cell"]["label_es"], strict=True))
        self.group_es = dict(zip(self.t["dim_group"]["group_key"], self.t["dim_group"]["label_es"], strict=True))
        self.band_es = dict(zip(self.t["dim_band"]["band_key"], self.t["dim_band"]["depth_label_es"], strict=True))
        self.version_es = dict(zip(self.t["dim_version"]["version_key"], self.t["dim_version"]["label_es"], strict=True))

    def sealed(self, name: str) -> pd.DataFrame:
        """The sealed rows of a fact, or all of them if none is sealed."""
        frame = self.t[name]
        return frame[frame["seal_state"] == "sealed"] if "seal_state" in frame.columns and (frame["seal_state"] == "sealed").any() else frame

    def test_or_validation(self, name: str) -> tuple[pd.DataFrame, str]:
        """The sealed rows of the test week when there are any, and else those of the validation, with what is shown in Spanish (never the test unless it is)."""
        frame = self.sealed(name)
        for scope, label in (("test", "prueba"), ("valid_v2", "validación (V2), no es la prueba"), ("valid", "validación, no es la prueba")):
            part = frame[frame["scope"] == scope]
            if len(part):
                return part, label
        return frame.iloc[0:0], "sin evaluar"


def _missing(value) -> bool:
    return value is None or bool(pd.isna(value))


def _fmt(value, digits: int = 3) -> str:
    return DASH if _missing(value) else f"{float(value):.{digits}f}".replace(".", ",")


def _int(value) -> str:
    return DASH if _missing(value) else f"{int(value):,}".replace(",", ".")


def _pct(value, digits: int = 1) -> str:
    return DASH if _missing(value) else f"{float(value) * 100:.{digits}f} %".replace(".", ",")


def _when(value) -> str:
    return DASH if _missing(value) else pd.Timestamp(value).strftime("%Y-%m-%d %H:%M")


def _table_html(headers: list[str], rows: list[list[str]], numeric: set[int] = frozenset()) -> str:
    """A table; every cell is escaped."""
    head = "".join(f'<th{" class=num" if i in numeric else ""}>{escape(h)}</th>' for i, h in enumerate(headers))
    body = "".join("<tr>" + "".join(f'<td{" class=num" if i in numeric else ""}>{escape(str(c))}</td>' for i, c in enumerate(row)) + "</tr>" for row in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body or '<tr><td>Sin datos</td></tr>'}</tbody></table>"


def _size(v: Visual) -> tuple[int, int]:
    return max(int(v.w * CELL_W - 22), 60), max(int(v.h * CELL_H - HEADER_PX - 12), 40)


def _card(big: str, sub: str = "") -> str:
    return f'<div class="big">{escape(big)}</div><div class="sub">{escape(sub)}</div>'


def _note(text: str) -> str:
    return f'<div class="rows"><p>{escape(text)}</p></div>'


def _caption(text: str) -> str:
    return f'<div class="sub">{escape(text)}</div>'


# --- previews ---------------------------------------------------------------------------------------------------------------------


def _slicer(data: _Data, field: str) -> str:
    table, column = field.split("[")[0], field.split("[")[1].rstrip("]")
    values = data.t[table][column].dropna() if column in data.t[table].columns else pd.Series(dtype=object)
    shown = sorted({str(x) for x in values})
    if column == "date" and shown:
        chips = f'<span class="chip">{escape(shown[0])}</span><span class="chip">a</span><span class="chip">{escape(shown[-1])}</span><span class="chip">{len(shown)} días</span>'
        return f'<div class="chips">{chips}</div>'
    chips = "".join(f'<span class="chip">{escape(x)}</span>' for x in shown[:4])
    more = f'<span class="chip">+{len(shown) - 4}</span>' if len(shown) > 4 else ""
    return f'<div class="chips">{chips or "Sin datos"}{more}</div>'


def _overall(data: _Data, version: str, estimator: str = "counterfactual", control: str = "regular"):
    part = data.sealed("fact_overall_effect")
    part = part[(part["scope"] == "launch") & (part["version_key"] == version) & (part["estimator"] == estimator) & (part["control"] == control)]
    return part.iloc[0] if len(part) else None


def _cards(data: _Data) -> dict:
    cells = data.sealed("fact_cell_effect")
    cells = cells[(cells["scope"] == "launch") & (cells["version_key"] == "recovered")]
    recovered, raw, naive = _overall(data, "recovered"), _overall(data, "raw"), _overall(data, "raw", "naive_pooled")
    replication = data.sealed("fact_replication")
    comparable = replication[replication["consistent"].notna()]
    quality, rules, runs = data.t["fact_data_quality"], data.t["fact_validation"], data.t["dim_pipeline_run"]
    ok = runs[runs["status"] == "ok"]
    return {
        "[Aumento total recuperado]": lambda: _card(_pct(None if recovered is None else recovered["lift"]),
                                                   "—" if recovered is None else f"intervalo {_pct(recovered['ci_low'])} a {_pct(recovered['ci_high'])}"),
        "[Lo que esconden los quiebres]": lambda: _card(DASH if recovered is None or raw is None else f"{(recovered['lift'] - raw['lift']) * 100:.1f} puntos".replace(".", ","), "recuperado menos crudo"),
        "[Aumento de la cuenta ingenua]": lambda: _card(_pct(None if naive is None else naive["lift"]), "mezcla productos"),
        "[Celdas ordenadas]": lambda: _card(_int(cells["ranked"].astype(bool).sum()), f"de {len(cells)} celdas"),
        "[Grupos indistinguibles]": lambda: _card(_int(cells[cells["ranked"].astype(bool)]["tier"].nunique()), "los intervalos que se pisan no se distinguen"),
        "[Celdas que mantienen su nivel (%)]": lambda: _card(_pct(comparable["consistent"].mean() if len(comparable) else None), f"de {len(comparable)} celdas comparables"),
        "[Series-días con promoción (%)]": lambda: _card(_pct(quality["promo"].sum() / quality["series_days"].sum() if quality["series_days"].sum() else None), f"de {_int(quality['series_days'].sum())} series-días"),
        "[Reglas bloqueantes fallidas]": lambda: _card(_int((rules["status"] == "falla").sum()), "en las corridas cargadas"),
        "[Última fecha de cálculo]": lambda: _card(_when(ok["as_of"].max()) if len(ok) else DASH, "última corrida terminada bien"),
    }


def _cell_intervals(data: _Data, v: Visual) -> str:
    cells = data.sealed("fact_cell_effect")
    cells = cells[(cells["scope"] == "launch") & (cells["version_key"] == "recovered") & cells["ranked"].astype(bool)].sort_values("rank")
    width, height = _size(v)
    shown = cells.head(max(height // 11, 1))
    items = [(row.cell_key, row.ci_low, row.lift, row.ci_high, row.tier) for row in shown.itertuples()]
    return svg.interval_chart(items, width, height - 14, v.title_es) + _caption(f"Las celdas del mismo color no se distinguen entre sí; {len(shown)} de {len(cells)} celdas ordenadas.")


def _unranked(data: _Data) -> str:
    cells = data.sealed("fact_cell_effect")
    cells = cells[(cells["scope"] == "launch") & (cells["version_key"] == "recovered") & ~cells["ranked"].astype(bool)].sort_values("series")
    rows = [[data.cell_es.get(r.cell_key, r.cell_key), _int(r.series), "no", _pct(r.lift)] for r in cells.head(TABLE_ROWS).itertuples()]
    return _table_html(["Celda", "Series", "Ordenada", "Aumento"], rows, {1, 3}) + _caption("Con pocas series: se muestran, no se ordenan.")


def _hour_lines(data: _Data, v: Visual) -> str:
    profile = data.t["fact_hour_profile"]
    width, height = _size(v)
    if profile.empty:
        return svg.line_chart({}, width, height, v.title_es)
    weighted = profile.assign(out=profile["stockout_rate"] * profile["series_days"], sold=profile["mean_sales"] * profile["series_days"]).groupby("hour")[["out", "sold", "series_days"]].sum()
    rate = (weighted["out"] / weighted["series_days"]).to_dict()
    sales = (weighted["sold"] / weighted["series_days"])
    scale = float(sales.max()) or 1.0
    lines = {"Tasa de quiebre": [(float(h), float(r)) for h, r in rate.items()], "Venta media (relativa a su máximo)": [(float(h), float(x / scale)) for h, x in sales.items()]}
    return svg.line_chart(lines, width, height - 14, v.title_es, x_ticks=[(0.0, "0"), (6.0, "6"), (12.0, "12"), (21.0, "21")]) + _caption("Las horas de 06 a 21 son las que analiza el proyecto.")


def _example_day(data: _Data, v: Visual) -> str:
    day = data.t["fact_example_day"]
    width, height = _size(v)
    lines = {"Venta observada": [(float(r.hour), float(r.observed)) for r in day.itertuples()], "Demanda recuperada": [(float(r.hour), float(r.recovered)) for r in day.itertuples()]}
    return svg.line_chart(lines, width, height - 14, v.title_es, dashed=["Demanda recuperada"]) + _caption("Una serie-día que se quedó sin stock: lo observado cae a cero, lo recuperado no.")


def _recovery_table(data: _Data) -> str:
    check = data.sealed("fact_recovery_check")
    check = check[check["mask"] == "tail"].sort_values(["scope", "method_key"])
    rows = [[SCOPE_ES.get(r.scope, r.scope), data.method_es.get(r.method_key, r.method_key) + (" (elegido)" if r.chosen else ""), _pct(r.wape_series), _pct(r.bias), r.fit_blocks]
            for r in check.head(TABLE_ROWS * 2).itertuples()]
    return _table_html(["Bloque", "Método", "WAPE por serie", "Sesgo", "Ajustado con"], rows, {2, 3})


def _recovered_by_group(data: _Data, v: Visual) -> str:
    daily = data.t["fact_stockout_daily"]
    totals = daily.groupby("group_key")[["raw_mass", "recovered_mass"]].sum()
    values = [(data.group_es.get(g, str(g)), float(r["recovered_mass"] / r["raw_mass"] - 1) * 100) for g, r in totals.iterrows() if r["raw_mass"]]
    width, height = _size(v)
    return svg.bar_chart(values, width, height, v.title_es, unit="%")


def _band_bars(data: _Data, v: Visual) -> str:
    bands = data.sealed("fact_band_effect")
    bands = bands[(bands["scope"] == "launch") & (bands["control"] == "regular") & (bands["day_state"] == "promo")]
    groups = [(data.band_es.get(k, str(k)), {data.version_es.get(r.version_key, r.version_key): float(r.lift) * 100 for r in bands[bands["band_key"] == k].itertuples()}) for k in sorted(bands["band_key"].unique())]
    width, height = _size(v)
    return svg.grouped_bar_chart(groups, width, height, v.title_es)


def _unflagged_bars(data: _Data, v: Visual) -> str:
    bands = data.sealed("fact_band_effect")
    bands = bands[(bands["scope"] == "launch") & (bands["day_state"] == "unflagged_cut") & (bands["version_key"] == "recovered")]
    width, height = _size(v)
    return svg.bar_chart([(data.band_es.get(r.band_key, str(r.band_key)), float(r.lift) * 100) for r in bands.sort_values("band_key").itertuples()], width, height, v.title_es, unit="%")


def _group_bars(data: _Data, v: Visual) -> str:
    groups = data.sealed("fact_group_effect")
    groups = groups[(groups["scope"] == "launch") & (groups["version_key"] == "recovered")]
    width, height = _size(v)
    return svg.bar_chart([(data.group_es.get(r.group_key, str(r.group_key)), float(r.lift) * 100) for r in groups.sort_values("group_key").itertuples()], width, height, v.title_es, unit="%")


def _overall_table(data: _Data) -> str:
    overall = data.sealed("fact_overall_effect")
    overall = overall[overall["scope"].isin(["launch", "test"])].sort_values(["scope", "estimator", "control", "version_key"])
    rows = [[SCOPE_ES.get(r.scope, r.scope), {"naive_pooled": "Cuenta ingenua", "counterfactual": "Contrafactual"}.get(r.estimator, r.estimator),
             {"regular": "días regulares", "any_flag0": "cualquier día sin marca"}.get(r.control, r.control), data.version_es.get(r.version_key, r.version_key), _pct(r.lift)]
            for r in overall.head(TABLE_ROWS + 3).itertuples()]
    return _table_html(["Alcance", "Estimador", "Control", "Versión", "Aumento"], rows, {4})


def _criteria(data: _Data) -> str:
    summary = data.sealed("fact_evaluation_summary").sort_values("criterion_id")
    if summary.empty:
        return _note("La prueba se evalúa con el cierre: los criterios quedan pendientes hasta entonces.")
    rows = [[r.criterion_id, r.name_es, _fmt(r.value), r.threshold_es, r.seen_by_research, r.seen_by_planner, "informativo" if _missing(r.passed) else ("sí" if r.passed else "no"), r.verdict_es]
            for r in summary.itertuples()]
    return _table_html(["Criterio", "Nombre", "Valor", "Umbral", "Investigación", "Plan", "Cumple", "Veredicto"], rows, {2})


def _replication_scatter(data: _Data, v: Visual) -> str:
    rep = data.sealed("fact_replication")
    width, height = _size(v)
    points = [(data.cell_es.get(r.cell_key, r.cell_key), float(r.lift_launch), float(r.lift_test)) for r in rep.itertuples() if not _missing(r.lift_launch) and not _missing(r.lift_test)]
    return svg.scatter_chart(points, width, height - 14, v.title_es, x_label="aumento sellado", y_label="semana de prueba") + _caption("Sobre la diagonal, el aumento se repitió.")


def _forecast_bars(data: _Data, v: Visual) -> str:
    part, label = data.test_or_validation("fact_forecast")
    width, height = _size(v)
    chart = svg.bar_chart([(data.method_es.get(r.method_key, r.method_key), float(r.wape) * 100) for r in part.sort_values("method_key").itertuples()], width, height - 14, v.title_es, unit="%")
    return chart + _caption(f"WAPE de lo que se muestra: {label}.")


def _day_by_band(data: _Data) -> str:
    daily, cells = data.t["fact_daily_cell"], data.t["dim_cell"]
    daily = daily[daily["version_key"] == "recovered"].merge(cells[["cell_key", "band_key"]], on="cell_key")
    if daily.empty:
        return _table_html(["Fecha"], [])
    sums = daily.groupby(["date_key", "band_key"])[["observed", "counterfactual"]].sum()
    lift = (sums["observed"] / sums["counterfactual"] - 1).unstack("band_key")
    bands = list(lift.columns)
    rows = [[str(key), *[_pct(lift.loc[key, b]) for b in bands]] for key in lift.index[:TABLE_ROWS]]
    return _table_html(["Fecha", *[data.band_es.get(b, str(b)) for b in bands]], rows, set(range(1, len(bands) + 1)))


def _state_bars(data: _Data, v: Visual) -> str:
    quality = data.t["fact_data_quality"].sort_values("date_key").tail(DAYS_SHOWN)
    groups = [(str(r.date_key)[4:], {"promo": float(r.promo), "regular": float(r.regular), "con rebaja y sin marca": float(r.unflagged_cut), "anómalos": float(r.anomalous)}) for r in quality.itertuples()]
    width, height = _size(v)
    return svg.grouped_bar_chart(groups, width, height, v.title_es) + _caption(f"Los últimos {len(groups)} días con datos.")


def _leakage(data: _Data) -> str:
    rows = [[r.check_es, _pct(r.value, 2), r.note_es] for r in data.t["fact_leakage"].itertuples()]
    return _table_html(["Qué se hizo", "WAPE por serie", "Lo que enseña"], rows, {1})


def _rules(data: _Data) -> str:
    rules = data.t["fact_validation"].sort_values(["run_key", "rule_id"])
    return _table_html(["Corrida", "Regla", "Nombre", "Severidad", "Series-días", "Estado"],
                       [[r.run_key, r.rule_id, r.name_es, r.severity, _int(r.series_days_affected), r.status] for r in rules.head(TABLE_ROWS).itertuples()], {4})


def _runs(data: _Data) -> str:
    runs = data.t["dim_pipeline_run"].sort_values("as_of", ascending=False)
    return _table_html(["Corrida", "Entrega", "Instante de cálculo", "Estado", "Filas emitidas", "Mensaje"],
                       [[r.run_key, r.delivery_id or DASH, _when(r.as_of), r.status, _int(r.rows_issued), r.message or ""] for r in runs.head(TABLE_ROWS).itertuples()], {4})


NOT_FILTERED_MARK = " (no lo"


def _bare_title(title: str) -> str:
    """A visual's title without the note that says what its slicers do not filter (``semantic_model.NOT_FILTERED``): the key of its preview."""
    return title.split(NOT_FILTERED_MARK, 1)[0]


def _makers(data: _Data, v: Visual) -> dict[str, Callable[[], str]]:
    """The drawing of each visual that is not a slicer or a card, by its title without the not-filtered note."""
    return {
        "Celdas ordenadas por aumento, con su intervalo y su grupo indistinguible": lambda: _cell_intervals(data, v),
        "Celdas con pocas series, sin ordenar": lambda: _unranked(data),
        "Tasa de quiebre y venta media por hora": lambda: _hour_lines(data, v),
        "Un día de ejemplo: venta observada y recuperada por hora": lambda: _example_day(data, v),
        "Comprobación de la recuperación en V1, V2 y la prueba": lambda: _recovery_table(data),
        "Demanda recuperada (%) por grupo": lambda: _recovered_by_group(data, v),
        "Aumento por banda de descuento, en las dos versiones": lambda: _band_bars(data, v),
        "Descuento sin marca: el aumento de los días con rebaja y sin promoción": lambda: _unflagged_bars(data, v),
        "Aumento por grupo de gestión": lambda: _group_bars(data, v),
        "La cuenta ingenua, el contrafactual y el control con cualquier día sin marca": lambda: _overall_table(data),
        "Criterios C01-C10": lambda: _criteria(data),
        "Aumento sellado contra el de la prueba, por celda (con la diagonal)": lambda: _replication_scatter(data, v),
        "WAPE de F0, F1, F2a y F2 en la prueba": lambda: _forecast_bars(data, v),
        "Aumento del día por banda en cada día de la prueba": lambda: _day_by_band(data),
        "Series-días de cada día según su estado": lambda: _state_bars(data, v),
        "Demostración de la fuga: una recuperación que lee el total diario": lambda: _leakage(data),
        "Reglas de validación": lambda: _rules(data),
        "Corridas": lambda: _runs(data),
    }


def _preview(data: _Data, v: Visual) -> str:
    """The body of a visual: its drawing or figure from the exported tables."""
    if v.kind == "slicer":
        return _slicer(data, v.fields[0])
    if v.kind == "card":
        maker = _cards(data).get(v.fields[0])
        return maker() if maker else _note("Se calcula en Power BI.")
    maker = _makers(data, v).get(_bare_title(v.title_es))
    return maker() if maker else _note("Se calcula en Power BI.")


# --- sections -----------------------------------------------------------------------------------------------------------------


def _steps(model: SemanticModel) -> str:
    steps = [
        "Instale Power BI Desktop (gratuito, solo para Windows) y abra un informe en blanco.",
        "Cree un parámetro de texto llamado <code>CarpetaSalidas</code> con la ruta de <code>outputs\\powerbi</code>.",
        f"Cree una consulta por tabla ({len(model.tables)}) con el código de la sección «Power Query»; deje el nombre de la consulta igual al de la tabla.",
        f"En la vista de modelo, cree las {len(model.relationships)} relaciones de la tabla «Relaciones»: uno a varios (1:*), filtro único de la dimensión al hecho, todas activas. "
        "Los hechos sin clave compartida (<code>fact_evaluation_summary</code>, <code>fact_example_day</code>, <code>fact_leakage</code>) no tienen relación: alimentan sus propios visuales.",
        "Marque <code>dim_date</code> como tabla de fechas con la columna <code>date</code>; ordene <code>dim_band[depth_label_es]</code> por <code>band_key</code> y <code>dim_date[weekday_es]</code> por <code>date</code>.",
        "Cree una tabla vacía llamada <code>_Medidas</code> y agregue en ella las medidas de la sección «Medidas DAX», con su formato.",
        f"Cree las {len(model.pages)} páginas a 1280 × 720 px y ubique cada visual según la grilla de {PAGE_COLUMNS} columnas por {PAGE_ROWS} filas.",
        "Guarde el informe como <code>.pbix</code>. Cuando corra el flujo, «Actualizar» vuelve a leer los mismos archivos.",
    ]
    return "<ol>" + "".join(f"<li>{s}</li>" for s in steps) + "</ol>"


def _diagram(model: SemanticModel) -> str:
    """Related dimensions above, the facts with relationships in the middle, the run table below, and the tables without relationships last."""
    width, height = 1500, 700
    related = {r.dim_table for r in model.relationships} | {r.fact_table for r in model.relationships}
    top = [t.name for t in model.tables if t.kind == "dimension" and t.name in related and t.name != "dim_pipeline_run"]
    bottom = [t.name for t in model.tables if t.name == "dim_pipeline_run" and t.name in related]
    facts = [t.name for t in model.tables if t.kind == "fact" and t.name in related]
    alone = [t.name for t in model.tables if t.name not in related]
    boxes: dict[str, tuple[float, float, float, float]] = {}
    for names, y, w, h in ((top, 24, 150, 46), (facts, 250, 150, 56), (bottom, 420, 170, 46), (alone, 590, 150, 46)):
        w = min(w, (width - 16 * (len(names) + 1)) / max(len(names), 1))
        gap = (width - w * len(names)) / (len(names) + 1) if names else 0
        for i, name in enumerate(names):
            boxes[name] = (gap + i * (w + gap), y, w, h)
    dims = sum(1 for t in model.tables if t.kind == "dimension")
    nfacts = sum(1 for t in model.tables if t.kind == "fact")
    out = [f'<svg class="model-svg" viewBox="0 0 {width} {height}" role="img" aria-label="Diagrama del modelo en estrella: {dims} dimensiones y {nfacts} hechos">',
           '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="var(--muted)"/></marker></defs>']
    for r in model.relationships:
        dx, dy, dw, dh = boxes[r.dim_table]
        fx, fy, fw, fh = boxes[r.fact_table]
        up = r.dim_table in top
        x1, y1 = dx + dw / 2, (dy + dh if up else dy)
        x2, y2 = fx + fw / 2, (fy if up else fy + fh)
        out.append(f'<line class="rel" x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" marker-end="url(#arrow)">'
                   f'<title>{escape(r.rel_id)}: {escape(r.dim_table)}[{escape(r.dim_column)}] 1 → * {escape(r.fact_table)}[{escape(r.fact_column)}]</title></line>')
        sign = 1 if up else -1
        out.append(f'<text class="card" x="{x1 + 3:.1f}" y="{y1 + sign * 13:.1f}">1</text><text class="card" x="{x2 + 3:.1f}" y="{y2 - sign * 6:.1f}">*</text>')
    for name, (x, y, w, h) in boxes.items():
        table = model.table(name)
        size = ' font-size="9"' if len(name) > 15 else ""
        key = ", ".join(table.key) if table.kind == "dimension" else f"{len(table.columns)} columnas"
        out.append(f'<rect class="box {"dim" if table.kind == "dimension" else "fact"}" x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h}" rx="6"/>'
                   f'<text x="{x + w / 2:.1f}" y="{y + h / 2 - 2:.1f}" text-anchor="middle"{size}>{escape(name)}</text>'
                   f'<text class="small" x="{x + w / 2:.1f}" y="{y + h / 2 + 12:.1f}" text-anchor="middle">{escape(key)}</text>')
    out.append('<text class="small" x="8" y="570">Sin relaciones: alimentan sus propios visuales.</text>')
    out.append(f'<text class="small" x="8" y="{height - 6}">Cada línea va de la dimensión («1») al hecho («*»); la flecha es la dirección del filtro, única y activa.</text></svg>')
    return "".join(out)


def _relationships(model: SemanticModel) -> str:
    rows = [[r.rel_id, f"{r.dim_table}[{r.dim_column}]", "1", f"{r.fact_table}[{r.fact_column}]", "*", "Uno a varios (1:*)",
             "Única: de la dimensión al hecho" if r.cross_filter == "single" else r.cross_filter, "Sí" if r.active else "No"] for r in model.relationships]
    return _table_html(["ID", "Dimensión", "", "Hecho", "", "Cardinalidad", "Dirección del filtro", "Activa"], rows)


def _queries(model: SemanticModel) -> str:
    parts = []
    for t in model.tables:
        steps = f'    Origen = Parquet.Document(File.Contents(CarpetaSalidas & "\\{t.name}.parquet"))'
        last = "Origen"
        dates = [c.name for c in t.columns if c.dtype == "date"]
        if dates:
            casts = ", ".join(f'{{"{d}", type date}}' for d in dates)
            steps += f",\n    Tipos = Table.TransformColumnTypes(Origen, {{{casts}}})"
            last = "Tipos"
        parts.append(f"<h3>{escape(t.name)}</h3><p>{escape(t.description_es)}</p><pre><code>{escape(f'let{chr(10)}{steps}{chr(10)}in{chr(10)}    {last}')}</code></pre>")
    return "".join(parts)


def _measures(model: SemanticModel) -> str:
    parts = []
    for m in model.measures:
        uses = sorted(dax_measure_refs(m.dax))
        used = f" Usa: {', '.join('[' + u + ']' for u in uses)}." if uses else ""
        parts.append(f"<h3>{escape(m.name_es)}</h3><p>{escape(m.description_es)}{escape(used)} Formato: <code>{escape(m.format_string)}</code>.</p>"
                     f"<pre><code>{escape(m.name_es)} =\n{escape(m.dax)}</code></pre>")
    return "".join(parts)


def _page_section(data: _Data, page: Page, number: int) -> str:
    visuals = []
    for v in page.visuals:
        style = f"grid-column:{v.x + 1} / span {v.w};grid-row:{v.y + 1} / span {v.h}"
        visuals.append(f'<section class="visual" style="{style}" aria-label="{escape(v.title_es)}"><header><b>{escape(v.title_es)}</b>'
                       f'<span>{escape(KIND_ES.get(v.kind, v.kind))}</span></header><div class="body">{_preview(data, v)}</div></section>')
    rows = [[KIND_ES.get(v.kind, v.kind), v.title_es, ", ".join(v.fields), f"x {v.x}, y {v.y}, ancho {v.w}, alto {v.h}"] for v in page.visuals]
    return (f'<h3 id="pagina-{number}">Página {number}: {escape(page.name_es)}</h3>'
            f'<div class="canvas-wrap"><div class="canvas" role="group" aria-label="Página {escape(page.name_es)}">{"".join(visuals)}</div></div>'
            f'<details><summary>Posición, tipo y campos de cada visual</summary><div class="scroll placement">'
            f'{_table_html(["Visual", "Título", "Campos", "Posición (celdas)"], rows)}</div></details>')


def _page_html(model: SemanticModel, data: _Data, run: RunMeta) -> str:
    nav = "".join(f'<li><a href="#{key}">{escape(title)}</a></li>' for key, title in SECTIONS)
    pages = "".join(_page_section(data, p, i) for i, p in enumerate(model.pages, start=1))
    dims = sum(1 for t in model.tables if t.kind == "dimension")
    facts = sum(1 for t in model.tables if t.kind == "fact")
    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(TITLE)}</title>
<style>{CSS}</style>
</head>
<body>
<main>
<h1>{escape(TITLE)}</h1>
<p class="lead">Guía para armar el informe en Power BI Desktop a partir de los archivos Parquet de <code>outputs/powerbi</code>: modelo, relaciones, consultas, medidas y las cinco páginas con una vista previa de cada visual dibujada con las cifras exportadas.</p>
<div class="meta"><span>Fecha de cálculo <b>{escape(run.as_of.isoformat(sep=" "))}</b></span><span>Corrida <code>{escape(run.run_key)}</code></span><span>SHA-256 de train.parquet <code>{escape(data.train_sha256[:12])}</code></span></div>
<nav aria-label="Secciones"><ul>{nav}</ul></nav>
<h2 id="armado">{escape(SECTIONS[0][1])}</h2>
{_steps(model)}
<div class="warn"><b>Qué se probó y qué no.</b> Las pruebas del proyecto comprueban que los archivos cumplen el modelo (claves únicas, claves foráneas en su dimensión, relaciones de uno a varios con filtro único) y que cada tabla, columna, medida y función que nombra el DAX existe, que las medidas de la prueba leen solo filas selladas, que cada segmentador llega, por las relaciones, a los visuales de su página (o el título dice que no los filtra) y que todo texto de los datos está escapado. <b>Ninguna medida se ejecutó</b>: no hay Power BI en el proyecto, así que ninguna expresión DAX se evaluó. Las vistas previas se calculan con pandas sobre los mismos archivos, sin segmentadores; al armar el informe, compare cada tarjeta con su vista previa.</div>
<div class="warn"><b>Un aumento es una asociación dentro de la serie, no una causa.</b> Es lo que se vendió sobre lo que la misma serie habría vendido a esa hora sin promoción; no dice por qué se lanzó la promoción. Las celdas cuyos intervalos se pisan no se distinguen entre sí, y el tablero las muestra en el mismo color. El nivel de un aumento describe el período; el orden de las celdas es lo que se repite (C05 y C06).</div>
<h2 id="modelo">{escape(SECTIONS[1][1])}</h2>
<p>{dims} dimensiones y {facts} hechos. <code>dim_cell</code> lleva el grupo y la banda como columnas, así que no hay copo de nieve. Los hechos de la evaluación, del día de ejemplo y de la fuga no comparten claves con las dimensiones y alimentan sus propios visuales.</p>
{_diagram(model)}
<h2 id="relaciones">{escape(SECTIONS[2][1])}</h2>
<div class="scroll">{_relationships(model)}</div>
<h2 id="consultas">{escape(SECTIONS[3][1])}</h2>
{_queries(model)}
<h2 id="medidas">{escape(SECTIONS[4][1])}</h2>
<p>Todas van en la tabla <code>_Medidas</code>. Los nombres de las medidas y los textos están en español; las tablas y las columnas, en inglés. Las medidas que leen una tabla con <code>seal_state</code> piden solo las filas selladas: si no, una fila posterior al sello dejaría la cifra vacía. Las medidas que fijan una versión (recuperada o cruda) no cambian con el segmentador de versión.</p>
{_measures(model)}
<h2 id="paginas">{escape(SECTIONS[5][1])}</h2>
<p>Cada página es un lienzo de 1280 × 720 px (16:9) sobre una grilla de {PAGE_COLUMNS} columnas por {PAGE_ROWS} filas; la posición de cada visual está en celdas. Las vistas previas de la evaluación muestran la prueba sellada si existe y, si no, la validación, y lo dicen. Un visual que un segmentador no filtra lo dice en su título.</p>
{pages}
<h2 id="fuente">{escape(SECTIONS[6][1])}</h2>
<p>{escape(ATTRIBUTION)}</p>
<p>Datos de la corrida <code>{escape(run.run_key)}</code>, con fecha de cálculo {escape(run.as_of.isoformat(sep=" "))}. Este documento se genera desde <code>dashboard/semantic_model.py</code>; no se edita a mano.</p>
</main>
</body>
</html>
"""


def render_design(model: SemanticModel, parquet_dir: Path, html_path: Path, run_meta: RunMeta) -> Path:
    """Write the HTML design of the report to `html_path` (atomically, through ``files.write_atomic``) from the Parquet files of `parquet_dir` and return the path. The model is checked
    first: an incoherent one writes nothing."""
    problems = validate_model(model)
    if problems:
        raise ValueError(f"el modelo semántico es incoherente: {problems[0]}")
    html = _page_html(model, _Data(Path(parquet_dir), model), run_meta)
    path = write_atomic(Path(html_path), html)
    logger.info("dashboard design written to %s (%d bytes)", path.name, len(html.encode("utf-8")))
    return path
