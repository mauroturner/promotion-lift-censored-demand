"""The summary and the results block (U11; RF19, D21; AC22): a criterion that is not met says «no supera» with its number, each verdict names its own comparison, a cell
never breaks its row, and the block that is copied into the README replaces only what is between its markers."""

from __future__ import annotations

import pytest

from promolift.evaluation import criteria_of
from promolift.reporting import check_markers, criterion_dict, replace_block, summary_markdown, sync_block
from tests.unit.test_evaluation import DOC, figures

START, END = "<!-- results:start -->", "<!-- results:end -->"


def summary_of(figs, **extra):
    criteria = [criterion_dict(c) for c in criteria_of(figs, DOC)]
    return {"schema_version": 1, "run_key": "run-close", "as_of": "2024-07-03 00:00:00", "evaluation_status": "sealed", "criteria": criteria, "validation": {}, "post_seal": None, **extra}


def rows_of(markdown: str, cid: str) -> str:
    return next(line for line in markdown.splitlines() if line.startswith(f"| {cid} "))


def test_unfavourable_summary_says_no_supera():
    bad = figures(forecast__f2_minus_f1={"value": 0.07, "ci_low": 0.05, "ci_high": 0.09}, replication__share_consistent=0.425)
    markdown = summary_markdown(summary_of(bad))
    row9, row6 = rows_of(markdown, "C09"), rows_of(markdown, "C06")
    assert "no supera a la regla ingenua" in row9 and "| no |" in row9 and "no supera" not in rows_of(markdown, "C08")
    assert "| no |" in row6 and "no se repite" in row6 and "| sí |" in rows_of(markdown, "C01") and "| informativo |" in rows_of(markdown, "C10")
    assert "C09" in markdown and markdown.startswith("## Resultados")


def test_each_verdict_names_its_own_comparison():
    expected = {"C01": ("media simple (R1)", "WAPE por serie"), "C02": ("sesgo", "masa recuperada"), "C03": ("aumento", "días con promoción", "días regulares"),
                "C04": ("demanda recuperada", "venta cruda"), "C05": ("Spearman", "celdas", "sellado"), "C06": ("nivel", "prueba − sellado"),
                "C07": ("profundidad", "banda"), "C08": ("aumento único (F2a)", "F2"), "C09": ("regla ingenua (F1)", "F2")}
    for variant in (figures(), figures(forecast__f2_minus_f1={"value": 0.07, "ci_low": 0.05, "ci_high": 0.09}, recovery__ci_high=0.01)):
        verdicts = {c.criterion_id: c.verdict_es for c in criteria_of(variant, DOC)}
        for cid, words in expected.items():
            assert all(w in verdicts[cid] for w in words), (cid, verdicts[cid])
        assert "F1" not in verdicts["C08"] and "F2a" not in verdicts["C09"] and "F2a" not in verdicts["C01"]
        assert "recuperada" not in verdicts["C08"] and "Spearman" not in verdicts["C04"]
    good, bad = (criteria_of(f, DOC) for f in (figures(), figures(forecast__f2_minus_f2a={"value": 0.01, "ci_low": 0.0, "ci_high": 0.02})))
    assert "no mejora" in bad[7].verdict_es and "no mejora" not in good[7].verdict_es and "mejora el pronóstico" in good[7].verdict_es
    assert criteria_of(figures(replication__spearman=0.9), DOC)[4].verdict_es.count("0,900") == 1     # the number in the verdict is the figure, formatted from it


def test_criterion_cells_escape_pipes_and_every_row_has_the_header_width():
    criteria = [criterion_dict(c) for c in criteria_of(figures(), DOC)]
    criteria[1] = {**criteria[1], "name_es": "Sesgo |sesgo| de la masa", "verdict_es": "El |sesgo| cumple"}
    markdown = summary_markdown({**summary_of(figures()), "criteria": criteria})
    table = [line for line in markdown.splitlines() if line.startswith("|")]
    widths = {len(line.replace(r"\|", "").split("|")) for line in table}
    assert len(widths) == 1 and r"Sesgo \|sesgo\| de la masa" in markdown and len(table) == 12


def test_a_pending_summary_says_when_the_test_is_evaluated_and_keeps_the_validation_with_its_blocks():
    pending = {"schema_version": 1, "run_key": "run-launch", "as_of": "2024-06-26 00:00:00", "evaluation_status": "pending", "pending_reason_es": "La prueba se evalúa con el cierre del 2024-07-03.",
               "criteria": [], "post_seal": None,
               "validation": {"recovery_v2": {"fit_blocks": "train", "methods": {"r1": {"wape_series": 0.3747, "bias": 0.01}, "r2@0.25": {"wape_series": 0.3157, "bias": -0.0}}}}}
    markdown = summary_markdown(pending)
    assert "La prueba se evalúa con el cierre del 2024-07-03" in markdown and "train" in markdown and "31,6 %" in markdown and "Estado: pending" in markdown


def test_the_results_block_replaces_only_what_is_between_its_markers_and_a_file_without_them_is_not_touched(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text(f"# Title\n\n{START}\nold\n{END}\n\nafter\n", encoding="utf-8")
    assert sync_block(readme, START, END, "new text\n") is True
    assert readme.read_text(encoding="utf-8") == f"# Title\n\n{START}\nnew text\n{END}\n\nafter\n" and sync_block(readme, START, END, "new text") is False
    broken = tmp_path / "broken.md"
    broken.write_text(f"{END}\n{START}\n", encoding="utf-8")
    for text in (f"{START}\nonly start\n", f"{START}{START}{END}", f"{END}{START}"):
        with pytest.raises(ValueError):
            replace_block(text, "x.md", START, END, "c")
    before = broken.read_bytes()
    with pytest.raises(ValueError):
        sync_block(broken, START, END, "c")
    with pytest.raises(ValueError):
        check_markers(broken, START, END)
    assert broken.read_bytes() == before
