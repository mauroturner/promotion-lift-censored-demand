"""The HTML design of the report (U13; RF21, AC25; plan, section 20): every page and measure of the model, no external resource, every text of the data escaped, the figures of the
previews the ones of the exported files, and an incoherent model that writes nothing."""

from __future__ import annotations

import dataclasses
import re
import shutil

import pandas as pd
import pytest

from promolift.dashboard.render import render_design
from promolift.dashboard.semantic_model import MODEL, PAGES
from promolift.registry import RunMeta
from tests.unit.test_semantic_model import MEASURE_NAMES, PAGE_NAMES


def test_html_has_every_page_and_escapes_data_text(star_export, rendered_html, tmp_path):
    html = rendered_html.html
    assert html.startswith("<!doctype html>") and '<html lang="es">' in html and len(html.encode("utf-8")) < 2 * 1024 * 1024
    for number, name in enumerate(PAGE_NAMES, start=1):
        assert f'id="pagina-{number}">Página {number}: {name}</h3>' in html
    for page in PAGES:
        for v in page.visuals:
            assert f'aria-label="{v.title_es}"' in html.replace("&quot;", '"') or v.title_es.split(" (no lo")[0] in html, v.title_es
    for name in MEASURE_NAMES:
        assert f"<h3>{name}</h3>" in html.replace("&amp;", "&") or name in html, name
    assert html.count('class="visual"') == sum(len(p.visuals) for p in PAGES) and "<h2 id=\"relaciones\">" in html and html.count("<tr><td>R") >= 21
    assert all(f"<h3>{t.name}</h3>" in html for t in MODEL.tables) and "Ninguna medida se ejecutó" in html and "una asociación dentro de la serie, no una causa" in html
    # text that comes from the data is escaped wherever it is shown
    tainted = tmp_path / "powerbi"
    shutil.copytree(star_export.out, tainted)
    cells = pd.read_parquet(tainted / "dim_cell.parquet")
    cells["label_es"] = '<script>alert("x")</script> & más'
    cells.to_parquet(tainted / "dim_cell.parquet")
    runs = pd.read_parquet(tainted / "dim_pipeline_run.parquet")
    runs["message"] = "<img src=x onerror=alert(1)>"
    runs.to_parquet(tainted / "dim_pipeline_run.parquet")
    other = render_design(MODEL, tainted, tmp_path / "other.html", star_export.run).read_text(encoding="utf-8")
    assert "<script>alert" not in other and "<img src=x" not in other and "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt; &amp; más" in other and "&lt;img src=x onerror=alert(1)&gt;" in other


def test_the_page_loads_nothing_from_outside_and_has_no_script(rendered_html):
    html = rendered_html.html
    assert "<script" not in html.lower() and "<iframe" not in html.lower() and "@import" not in html and not re.findall(r"url\((?!#)", html)
    assert not re.findall(r'(?:src|href)=["\'](?!#)', html) and "http://" not in html and "https://" not in html
    assert str(rendered_html.path.parent) not in html and "C:\\" not in html and "/Users/" not in html


def test_the_previews_are_the_figures_of_the_exported_files(star_export, rendered_html):
    html = rendered_html.html
    overall = pd.read_parquet(star_export.out / "fact_overall_effect.parquet")
    recovered = overall[(overall["scope"] == "launch") & (overall["version_key"] == "recovered") & (overall["estimator"] == "counterfactual") & (overall["control"] == "regular")].iloc[0]
    raw = overall[(overall["scope"] == "launch") & (overall["version_key"] == "raw") & (overall["estimator"] == "counterfactual") & (overall["control"] == "regular")].iloc[0]
    shown = f"{recovered['lift'] * 100:.1f} %".replace(".", ",")
    assert f'<div class="big">{shown}</div>' in html
    assert f'<div class="big">{(recovered["lift"] - raw["lift"]) * 100:.1f} puntos</div>'.replace(".", ",", 1) in html
    cells = pd.read_parquet(star_export.out / "fact_cell_effect.parquet")
    launch = cells[(cells["scope"] == "launch") & (cells["version_key"] == "recovered")]
    assert f'<div class="big">{int(launch["ranked"].sum())}</div><div class="sub">de {len(launch)} celdas</div>' in html
    criteria = pd.read_parquet(star_export.out / "fact_evaluation_summary.parquet")
    assert all(verdict.replace("&", "&amp;").replace("<", "&lt;") in html for verdict in criteria[criteria["seal_state"] == "sealed"]["verdict_es"])
    assert "Las celdas del mismo color no se distinguen entre sí" in html and "La prueba se evalúa" not in html


def test_without_the_exported_files_every_preview_says_there_is_no_data_and_the_criteria_are_pending(star_export, tmp_path):
    out = render_design(MODEL, tmp_path / "nothing", tmp_path / "empty.html", RunMeta("run-x", star_export.run.as_of)).read_text(encoding="utf-8")
    assert "Sin datos" in out and "pendientes" in out and out.count('class="visual"') == sum(len(p.visuals) for p in PAGES) and "<script" not in out


def test_an_incoherent_model_writes_nothing_and_the_file_is_written_whole(star_export, tmp_path):
    broken = dataclasses.replace(MODEL, relationships=MODEL.relationships[1:] + (dataclasses.replace(MODEL.relationships[0], cardinality="many_to_many"),))
    target = tmp_path / "design.html"
    with pytest.raises(ValueError, match="incoherente"):
        render_design(broken, star_export.out, target, star_export.run)
    assert not target.exists() and not list(tmp_path.glob("*.tmp"))
    render_design(MODEL, star_export.out, target, star_export.run)
    before = target.read_bytes()
    render_design(MODEL, star_export.out, target, star_export.run)
    assert target.read_bytes() == before and not list(tmp_path.glob("*.tmp"))
