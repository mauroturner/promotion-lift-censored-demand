"""The figures of the documentation (U14; RF24): drawn only from the verified files of the site."""

from __future__ import annotations

import ast
import dataclasses
import shutil
from pathlib import Path

import pytest

from promolift import figures
from promolift.figures import FIGURES, figure_data, write_figures
from promolift.site_export import SiteSetError, read_site

SRC = Path(__file__).resolve().parents[2] / "src" / "promolift"


@pytest.fixture(scope="module")
def figures_written(site_files, tmp_path_factory):
    out = tmp_path_factory.mktemp("figures")
    return out, write_figures(site_files.out, out)


def test_figures_are_drawn_only_from_the_verified_site_files(site_files, figures_written, tmp_path):
    out, paths = figures_written
    tree = ast.parse((SRC / "figures.py").read_text(encoding="utf-8"))
    imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imported |= {(node.module or "").split(".")[0] if node.level == 0 else "." for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    from_promolift = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("promolift")}
    assert from_promolift == {"promolift.files", "promolift.site_export"} and not imported & {"sqlite3", "pyarrow", "pandas", "numpy"}          # no warehouse, no Parquet: the site files and nothing else
    assert [p.name for p in paths] == [f"{n}.png" for n in FIGURES] and all(p.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n" and p.stat().st_size > 2_000 for p in paths) and not list(out.glob("*.tmp"))
    # a folder that is not one export draws nothing
    broken = tmp_path / "site"
    shutil.copytree(site_files.out, broken)
    (broken / "data.json").write_text('{"changed": true}\n', encoding="utf-8")
    target = tmp_path / "figures"
    with pytest.raises(SiteSetError):
        write_figures(broken, target)
    assert not target.exists()
    (broken / "manifest.json").unlink()
    with pytest.raises(SiteSetError, match="manifest.json"):
        write_figures(broken, target)


def test_a_figure_plots_the_numbers_of_the_site_and_changes_when_they_change(site_files):
    site = site_files.site
    data = figure_data(site)
    assert set(data) == set(FIGURES) and data["hour_profile"]["hour"] == site.data["hour_profile"]["hour"] and data["first_stockout"]["share"] == site.data["first_stockout"]["share"]
    assert data["first_stockout"]["hour"] == site.data["first_stockout"]["hour"] == list(range(6, 22)) and data["recovery_check"]["methods"] == [r["label_es"] for r in site.algorithms["recovery"] if r["scope"] == "test"]
    assert data["example_day"]["recovered"] == site.algorithms["example_day"]["recovered"] and data["naive_vs_adjusted"]["recovered"] == site.algorithms["naive_vs_adjusted"]["recovered"]
    assert data["band_lift"]["recovered"] == [b["recovered"] for b in site.algorithms["bands"]] and data["cell_ranking"]["cell"] == [c["cell"] for c in sorted(site.algorithms["cells"], key=lambda c: c["rank"] or 999) if c["ranked"]]
    assert data["replication"]["cell"] == [r["cell"] for r in site.operation["replication"]] and data["recovery_check"]["scope"] == "test" and data["forecast_wape"]["scope"] == "test"
    assert data["forecast_wape"]["wape"] == [m["wape"] for m in site.operation["forecast"]]
    other = dataclasses.replace(site, algorithms={**site.algorithms, "naive_vs_adjusted": {**site.algorithms["naive_vs_adjusted"], "recovered": {"value": 0.99, "ci_low": 0.9, "ci_high": 1.1}}})
    changed = figure_data(other)
    assert changed["naive_vs_adjusted"]["recovered"]["value"] == 0.99 and figures._DRAW["naive_vs_adjusted"](changed["naive_vs_adjusted"]) != figures._DRAW["naive_vs_adjusted"](data["naive_vs_adjusted"])
    assert figures._DRAW["hour_profile"](data["hour_profile"]) == figures._DRAW["hour_profile"](data["hour_profile"])          # the same numbers, the same bytes


def test_before_the_seal_the_figures_say_they_show_the_validation_and_not_the_test(site_files):
    site = site_files.site
    operation = {**site.operation, "replication": [], "forecast": [{**m, "wape": None, "bias": None} for m in site.operation["forecast"]]}
    algorithms = {**site.algorithms, "recovery": [r for r in site.algorithms["recovery"] if r["scope"] != "test"]}
    data = figure_data(dataclasses.replace(site, operation=operation, algorithms=algorithms))
    assert data["forecast_wape"]["scope"] == "valid" and data["forecast_wape"]["fit_blocks"] == ["train"] and data["recovery_check"]["scope"] == "valid_v2" and data["recovery_check"]["fit_blocks"] == ["train"]
    assert data["replication"]["cell"] == [] and all(isinstance(figures._DRAW[name](data[name]), bytes) for name in FIGURES)        # an empty figure is drawn, saying why
    assert len(read_site(site_files.out).operation["replication"]) > 0
