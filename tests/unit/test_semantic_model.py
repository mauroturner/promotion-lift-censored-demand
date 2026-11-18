"""The measures and the pages of the report (U13; RF21, AC24, AC25; D35; plan, section 20): no measure runs anywhere in the project, so what stands in for running them is that
every table, column, measure and function a DAX expression names exists, that a measure of the test week reads only sealed rows, and that each slicer reaches the visuals of its
page through a relationship or the title of the visual says it does not filter it."""

from __future__ import annotations

import dataclasses
import re

from promolift.dashboard.semantic_model import (
    DAX_FUNCTIONS,
    MEASURES,
    MODEL,
    PAGE_COLUMNS,
    PAGE_ROWS,
    PAGES,
    Page,
    SemanticModel,
    Visual,
    dax_column_refs,
    dax_measure_refs,
    validate_model,
    visual_tables,
)

PAGE_NAMES = ("Qué promociones venden", "Las horas sin stock y la demanda que esconden", "Por descuento y por grupo", "La semana de prueba", "Calidad de datos y corridas")
MEASURE_NAMES = (
    "Aumento", "Aumento sellado", "Límite inferior", "Límite superior", "Celdas ordenadas", "Grupos indistinguibles", "Aumento total recuperado", "Aumento total crudo",
    "Lo que esconden los quiebres", "Aumento de la cuenta ingenua", "Aumento del día", "Tasa de quiebre", "Venta media por hora", "Demanda recuperada (%)", "WAPE del pronóstico",
    "WAPE de la recuperación", "Celdas que mantienen su nivel (%)", "Veredicto", "Series-días con promoción (%)", "Última fecha de cálculo", "Reglas bloqueantes fallidas")
SEALED_FACTS = [t.name for t in MODEL.tables if "seal_state" in t.column_names]


def test_the_21_measures_of_the_plan_exist_with_their_names_formats_and_descriptions():
    assert tuple(m.name_es for m in MEASURES) == MEASURE_NAMES and len(MODEL.measures) == 21
    assert all(m.format_string and m.description_es and m.dax.count("(") == m.dax.count(")") for m in MEASURES)
    assert MODEL.measure("Veredicto").format_string == "@" and MODEL.measure("Última fecha de cálculo").format_string == "yyyy-mm-dd hh:mm"
    assert validate_model(MODEL) == []


def test_every_dax_reference_exists():
    columns = {t.name: {c.name: c for c in t.columns} for t in MODEL.tables}
    names = {m.name_es for m in MODEL.measures}
    for m in MODEL.measures:
        for table, column in dax_column_refs(m.dax):
            assert column in columns.get(table, {}), (m.name_es, table, column)
        for ref in dax_measure_refs(m.dax):
            assert ref in names and ref != m.name_es, (m.name_es, ref)
        for table in re.findall(r"\b(?:dim|fact)_\w+", m.dax):
            assert table in columns, (m.name_es, table)
        for function in re.findall(r"\b([A-Z][A-Z0-9.]*)(?=\s*\()", m.dax):
            assert function in DAX_FUNCTIONS, (m.name_es, function)
        for table, column, literal in re.findall(r'\b([a-z_]\w*)\[(\w+)\]\s*=\s*"([^"]*)"', m.dax):
            assert literal in columns[table][column].description_es, (m.name_es, table, column, literal)       # the text a column is compared with is one the column takes
        assert not re.search(r"\b(ALL|ALLEXCEPT|ALLSELECTED|REMOVEFILTERS|CROSSFILTER|USERELATIONSHIP|KEEPFILTERS)\b", m.dax), m.name_es       # no measure removes the slicers' filters
    for page in PAGES:
        for v in page.visuals:
            for field in v.fields:
                if field.startswith("["):
                    assert field[1:-1] in names, (page.name_es, v.title_es, field)
                else:
                    table, column = field.split("[")[0], field.split("[")[1].rstrip("]")
                    assert column in columns[table], (page.name_es, v.title_es, field)


def test_a_test_figure_reads_the_sealed_rows_only_so_a_post_seal_row_cannot_hide_it():
    """A measure that picks one value (SELECTEDVALUE) from a table with a seal state would be blank if a sealed and a post-seal row of the same key were both there (project 04's D71): it
    asks for the sealed rows, and so does one that counts rows of such a table."""
    for m in MEASURES:
        tables = {t for t, _ in dax_column_refs(m.dax) if t in SEALED_FACTS} | {t for t in re.findall(r"\b(?:dim|fact)_\w+", m.dax) if t in SEALED_FACTS}
        reads_by_pick = "SELECTEDVALUE" in m.dax or "COUNTROWS" in m.dax or "DISTINCTCOUNT" in m.dax
        for table in tables:
            if reads_by_pick:
                assert f'{table}[seal_state] = "sealed"' in m.dax, (m.name_es, table)
    for m in MODEL.measures:
        if "fact_forecast" in m.dax or "fact_recovery_check" in m.dax or "fact_replication" in m.dax or "fact_evaluation_summary" in m.dax:
            assert '[seal_state] = "sealed"' in m.dax, m.name_es
    assert "fact_forecast[scope] = \"test\"" in MODEL.measure("WAPE del pronóstico").dax and "fact_recovery_check[mask] = \"tail\"" in MODEL.measure("WAPE de la recuperación").dax
    assert "fact_daily_cell[version_key] = \"recovered\"" in MODEL.measure("Aumento del día").dax            # both versions are rows of the fact: summing them would count the day twice


def test_the_measures_that_fix_a_version_or_a_scope_say_so_in_their_description():
    for name in ("Aumento total recuperado", "Aumento total crudo"):
        assert "fija la versión" in MODEL.measure(name).description_es
    assert MODEL.measure("Aumento sellado").dax.count('fact_cell_effect[scope] = "launch"') == 1 and "lanzamiento" in MODEL.measure("Aumento sellado").description_es


def page(name: str) -> Page:
    return next(p for p in PAGES if p.name_es == name)


def visual(name: str, title: str) -> Visual:
    return next(v for v in page(name).visuals if v.title_es == title)


def test_there_are_five_pages_in_the_order_of_the_plan_inside_the_grid_without_overlaps():
    assert tuple(p.name_es for p in PAGES) == PAGE_NAMES and (PAGE_COLUMNS, PAGE_ROWS) == (12, 9)
    for p in PAGES:
        taken: set[tuple[int, int]] = set()
        for v in p.visuals:
            assert 0 <= v.x and v.x + v.w <= PAGE_COLUMNS and 0 <= v.y and v.y + v.h <= PAGE_ROWS and v.w >= 1 and v.h >= 1, (p.name_es, v.title_es)
            cells = {(x, y) for x in range(v.x, v.x + v.w) for y in range(v.y, v.y + v.h)}
            assert not cells & taken, (p.name_es, v.title_es)
            taken |= cells


def test_each_page_has_the_visuals_of_the_plan():
    first, second, third, fourth, fifth = PAGES
    assert [v.title_es for v in first.visuals if v.kind == "slicer"] == ["Versión", "Grupo"]
    assert [v.fields[0] for v in first.visuals if v.kind == "card"] == ["[Aumento total recuperado]", "[Lo que esconden los quiebres]", "[Aumento de la cuenta ingenua]", "[Celdas ordenadas]",
                                                                         "[Grupos indistinguibles]"]
    assert [v.title_es for v in second.visuals if v.kind == "slicer"] == ["Fecha", "Grupo", "Estado del día"]
    assert any(v.title_es.startswith("Un día de ejemplo") for v in second.visuals) and any(v.title_es.startswith("Comprobación de la recuperación") for v in second.visuals)
    assert not [v for v in third.visuals if v.kind in ("slicer", "card")] and len(third.visuals) == 4
    assert [v.title_es for v in fourth.visuals][:1] == ["Criterios C01-C10"] and any(v.kind == "scatter" for v in fourth.visuals) and any("Aumento del día por banda" in v.title_es for v in fourth.visuals)
    assert [v.fields[0] for v in fifth.visuals if v.kind == "card"] == ["[Series-días con promoción (%)]", "[Reglas bloqueantes fallidas]", "[Última fecha de cálculo]"]


def _filtered_by(table: str) -> set[str]:
    """The tables a slicer on `table` filters: itself and, if it is a dimension, the facts it has a relationship with."""
    return {table} | {r.fact_table for r in MODEL.relationships if r.dim_table == table}


def _says_it_is_not_filtered_by(v: Visual, slicer: Visual) -> bool:
    match = re.search(r"\(no lo filtran? (.*)\)", v.title_es)
    return bool(match) and slicer.title_es.lower() in match.group(1).lower()


def test_every_slicer_reaches_the_visuals_of_its_page_through_a_relationship():
    """A slicer on a table with no path to a visual selects without filtering it, in silence (the correction A10 of project 04). Every slicer of every page reaches every visual of its page
    through the relationships of the model, or the visual's title says that this slicer does not filter it, and a title says so only when it is true."""
    slicers = 0
    for p in PAGES:
        for slicer in (v for v in p.visuals if v.kind == "slicer"):
            slicers += 1
            reached = _filtered_by(slicer.fields[0].split("[")[0])
            assert len(slicer.fields) == 1 and not slicer.fields[0].startswith("["), slicer.title_es
            for v in (v for v in p.visuals if v.kind != "slicer"):
                filtered = bool(reached & visual_tables(MODEL, v))
                assert filtered != _says_it_is_not_filtered_by(v, slicer), (p.name_es, slicer.title_es, v.title_es, filtered)
    assert slicers == 5
    # the two ways it can fail are seen: a slicer that reaches nothing of the page, and a title that says what is not so
    date = visual(PAGE_NAMES[1], "Fecha")
    example = next(v for v in page(PAGE_NAMES[1]).visuals if v.title_es.startswith("Un día de ejemplo"))
    assert not _filtered_by("dim_date") & visual_tables(MODEL, example) and _says_it_is_not_filtered_by(example, date)
    assert not _says_it_is_not_filtered_by(dataclasses.replace(example, title_es="Un día de ejemplo"), date)


def test_a_visual_reads_only_tables_that_the_relationships_join():
    """A column of a dimension next to a measure of a fact it has no relationship with would show the same number in every row; two facts need a dimension that joins them."""
    kinds = {t.name: t.kind for t in MODEL.tables}
    for p in PAGES:
        for v in p.visuals:
            tables = visual_tables(MODEL, v)
            dims, facts = [t for t in tables if kinds[t] == "dimension"], [t for t in tables if kinds[t] == "fact"]
            assert not (len(facts) >= 2 and not dims) and not (len(dims) >= 2 and not facts), (p.name_es, v.title_es)
            for d in dims:
                for f in facts:
                    assert f in _filtered_by(d), (p.name_es, v.title_es, d, f)


def test_the_model_check_names_every_way_a_measure_or_a_page_can_be_wrong():
    assert validate_model(MODEL) == []
    good = MEASURES[2]

    def with_(**changes) -> SemanticModel:
        return dataclasses.replace(MODEL, **changes)

    def measure(dax: str, **changes) -> SemanticModel:
        return with_(measures=(*MEASURES, dataclasses.replace(good, name_es="Nueva", dax=dax, **changes)))

    first = PAGES[0].visuals[0]
    cases = [
        (measure("SUM ( fact_data_quality[promoo] )"), "fact_data_quality[promoo]"), (measure("SUM ( fact_data_qualit[promo] )"), "fact_data_qualit"),
        (measure("COUNTROWS ( fact_data_qualit )"), "fact_data_qualit"), (measure("[No existe] + 1"), "[No existe]"), (measure("[Nueva] + 1"), "[Nueva]"),
        (measure("SUM ( fact_data_quality[promo] "), "paréntesis"), (measure('CALCULATE ( COUNTROWS ( fact_validation ), fact_validation[status] = "falla )'), "comillas"),
        (measure("MEDIAN ( fact_data_quality[promo] )"), "MEDIAN"), (measure('CALCULATE ( COUNTROWS ( fact_validation ), fact_validation[status] = "bien" )'), "'bien'"),
        (measure("CALCULATE ( COUNTROWS ( fact_validation ), ALL ( fact_validation ) )"), "ALL"), (measure("SUM ( fact_data_quality[promo] )", format_string=""), "formato"),
        (measure("SUM ( fact_data_quality[promo] )", description_es=""), "descripción"), (with_(measures=(*MEASURES, MEASURES[0])), "repetida"),
        (with_(measures=(*MEASURES[:8], dataclasses.replace(MEASURES[8], dax="[Lo que esconden los quiebres]"), *MEASURES[9:])), "no existe o es ella misma"),
        (with_(measures=(*MEASURES, dataclasses.replace(good, name_es="A", dax="[B] + 1"), dataclasses.replace(good, name_es="B", dax="[A] + 1"))), "en círculo"),
        (with_(pages=(*PAGES, PAGES[0])), "repetida"), (with_(pages=(*PAGES, Page("Vacía", ()))), "sin visuales"),
        (with_(pages=(Page("P", (dataclasses.replace(first, fields=("dim_version[nope]",)),)),)), "dim_version[nope]"),
        (with_(pages=(Page("P", (dataclasses.replace(first, fields=("dim_version[label_es]", "dim_cell[group_key]")),)),)), "un segmentador usa una sola columna"),
        (with_(pages=(Page("P", (dataclasses.replace(first, x=10, w=4),)),)), "sale de la grilla"), (with_(pages=(Page("P", (first, dataclasses.replace(first, title_es="Otro"))),)), "se superpone"),
        (with_(pages=(Page("P", (Visual("table", "Dos hechos", ("fact_daily_cell[lift]", "fact_forecast[wape]"), 0, 0, 4, 2),)),)), "dos hechos sin una dimensión"),
        (with_(pages=(Page("P", (Visual("table", "Dos dimensiones", ("dim_date[date]", "dim_band[band_key]"), 0, 0, 4, 2),)),)), "dos dimensiones sin un hecho"),
        (with_(pages=(Page("P", (Visual("table", "Sin relación", ("dim_band[band_key]", "fact_daily_cell[lift]"), 0, 0, 4, 2),)),)), "no se unen por ninguna relación"),
    ]
    for model, text in cases:
        assert any(text in p for p in validate_model(model)), (text, validate_model(model))
    assert validate_model(dataclasses.replace(MODEL, measures=(), pages=())) == []          # a model without measures or pages is still checked as before


def test_no_text_of_the_report_calls_a_lift_a_cause_or_promises_the_next_week():
    forbidden = ("causó", "causa de", "provocó", "gracias a la promoción", "garantiza", "promete")
    texts = [m.description_es for m in MEASURES] + [v.title_es for p in PAGES for v in p.visuals] + [t.description_es for t in MODEL.tables] + [c.description_es for t in MODEL.tables for c in t.columns]
    for text in texts:
        assert not any(word in text.lower() for word in forbidden), text
