"""The documentation is checked like code (AC22, AC37; RF24; RNF14; plan, sections 24.2, 25 and 26).

U20: the README has the headings of plan section 25 in their order, its results block is the sealed summary that ``docs-sync`` copies (never one written by hand), and it
says the unfavourable verdicts («no supera», «no se cumple») in «El problema», «La solución» and «Los resultados»; the model card has the contents the plan lists, every
verdict as the summary writes it, the memory counters and the suite's limit; every interval bound that the documents quote is the summary's, rounded to the decimals the
document writes. These tests read the versioned Markdown and the versioned reports and run nothing.

U21 (AC37; RNF14; plan, sections 24.1, 25 and 30): every decision has its seven fields; the test count the documents give is the one of the session's collection (only when
that session collected the default selection in full); every memory figure names its counter; every test the plan names exists; every unit and every log entry the documents
cite has its entry in the log; the dictionary's tables are the ones ``docs-sync`` writes from the semantic model; the runbook has R1 to R12 and every reference of the code
points to one; the step by step cites commits that exist; the relative links resolve; the advisories of the native reviews have their status; and the root rows of project 06
carry the real verdicts.
"""

from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from promolift.reporting import RESULTS_END, RESULTS_START

README_TITLE = "# Qué promociones venden de verdad"
README_HEADINGS = [   # plan, section 25, in this order (AC37)
    "El problema", "La solución", "Los resultados", "En qué consiste", "Los datos", "Los algoritmos", "El producto", "La documentación",
    "Con IA, de punta a punta", "Para qué sirve", "Cómo correrlo de punta a punta", "Paso a paso", "Fuente y licencia",
]
MODEL_CARD_HEADINGS = [   # what plan section 25 lists for the model card, in this order
    "Uso previsto y no previsto", "Datos", "Estados del día y control", "Recuperación y su validación sintética", "Contrafactual", "Intervalos", "Ranking",
    "Criterios y resultados", "Limitaciones", "Tiempos y memoria", "La suite rápida",
]
FAILED = ["C04", "C06", "C09"]   # what the sealed run says (D16, U19): C06 and C09 as the plan expected, C04 against its expectation
PASSED = ["C01", "C02", "C03", "C05", "C07", "C08"]
RESULTS_HEADING = "## Resultados"   # the first line of the summary, copied as it is
DAILY_TIME_TEST = "tests/e2e/test_real.py::test_every_daily_run_takes_at_most_the_required_seconds"


@pytest.fixture(scope="module")
def readme(project_root: Path) -> str:
    return (project_root / "README.md").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def model_card(project_root: Path) -> str:
    return (project_root / "docs" / "model-card.md").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def summary(project_root: Path) -> dict:
    return json.loads((project_root / "reports" / "evaluation_summary.json").read_text(encoding="utf-8"))


def section(text: str, title: str, end: str | None = None) -> str:
    """The body of the second-level section `title`: up to `end` (its first appearance after the heading) when it is given, otherwise up to the next second-level
    heading or the end of the text."""
    body = text.split(f"\n## {title}\n", 1)[1]
    if end is not None:
        assert end in body, f"{end!r} does not follow the heading {title!r}"
        return body.split(end, 1)[0]
    return re.split(r"^## ", body, flags=re.MULTILINE)[0]


def test_readme_headings_in_order_and_results_block_matches_summary(project_root: Path, readme: str, summary: dict) -> None:
    assert readme.startswith(README_TITLE + "\n")
    assert readme.count(RESULTS_START) == 1 and readme.count(RESULTS_END) == 1
    head, rest = readme.split(RESULTS_START)
    block, tail = rest.split(RESULTS_END)
    block = block.strip("\n")
    # the block carries its own «## Resultados»: the headings of the plan are those outside it, in order
    assert re.findall(r"^## (.+)$", head + tail, flags=re.MULTILINE) == README_HEADINGS
    written = (project_root / "reports" / "evaluation_summary.md").read_text(encoding="utf-8")
    assert block == written.strip("\n")   # what docs-sync copies, byte for byte
    assert block.startswith(RESULTS_HEADING + "\n") and re.findall(r"^## (.+)$", block, flags=re.MULTILINE) == ["Resultados"]
    framing = section(readme, "Los resultados", end=RESULTS_START)   # «Los resultados» frames the block before it and reads it after it
    assert len(framing.strip()) > 400 and "\n## En qué consiste\n" in tail
    # AC22: the sealed summary is unfavourable, and the README says «no supera» outside the block too, in the three sections that tell it
    assert summary["evaluation_status"] == "sealed" and summary["post_seal"] is None
    assert [c["criterion_id"] for c in summary["criteria"] if c["passed"] is False] == FAILED
    assert [c["criterion_id"] for c in summary["criteria"] if c["passed"] is True] == PASSED
    assert [c["criterion_id"] for c in summary["criteria"] if c["passed"] is None] == ["C10"]
    for criterion in summary["criteria"]:
        assert criterion["verdict_es"] in block, criterion["criterion_id"]
    reading = framing + tail.split("\n## En qué consiste\n")[0]
    for title, text in (("El problema", section(readme, "El problema")), ("La solución", section(readme, "La solución")), ("Los resultados", reading)):
        assert "no supera" in text, title
    for criterion in FAILED + PASSED:
        assert re.search(rf"\b{criterion}\b", reading), criterion
    assert "se esperaba" in reading and "F1" in reading and "RNF02" in reading   # the expectation said before measuring, the naive rule and the open requirement
    assert "ajustados con train" in block   # AC22: every validation figure says the blocks its method was fitted on


def test_the_model_card_has_the_contents_of_the_plan_and_says_the_unfavourable_verdicts(model_card: str, summary: dict) -> None:
    assert re.findall(r"^## (.+)$", model_card, flags=re.MULTILINE) == MODEL_CARD_HEADINGS
    for criterion in summary["criteria"]:
        assert criterion["verdict_es"] in model_card, criterion["criterion_id"]   # every verdict as the summary writes it, «no supera» included
    for limit in (
        "un operador", "18 ciudades", "97 días", "venta normalizada", "zona horaria", "censura real", "PeakWorkingSetSize", "PeakPagefileUsage", "180 s", "150 s",
        "asociación", "no es causal", "ajustó con", "no se cumple", "RNF02", "62", "68", DAILY_TIME_TEST,
    ):
        assert limit.lower() in model_card.lower(), limit
    assert re.search(r"suite rápida[^\n]*\d{2,3},\d+ s", model_card)   # AC38: measured and written down


def test_the_readme_says_what_is_pending_and_gives_the_attribution(readme: str, model_card: str) -> None:
    """RNF14: the independent evaluation, the corrections and the ``.pbix`` are not done and the README says so; the credit of the source is complete; nothing local is published."""
    text = readme.lower()
    assert "evaluación independiente" in text and "todavía no" in text and ".pbix" in text and "RNF02" in readme
    tail = section(readme, "Fuente y licencia")
    for piece in (
        "Dingdong-Inc", "FreshRetailNet-50K", "CC BY 4.0", "c374e859", "Wang et al. (2026)", "arXiv:2505.16319",
        "6706832db892bbae4969c19d87e07975d2543d2ba7d7d4756360654785de5a3d", "1b118840664280c6b88bffc84c80ee1f54c05d911e354b7599e5da10995e960e",
    ):
        assert piece in tail, piece
    for document in (readme, model_card):
        assert not re.search(r"[A-Za-z]:[\\/]+(Users|Documents and Settings)", document) and "mauro" not in document.lower() and "@gmail" not in document


# --- the intervals the documents quote (AC37, RNF14; lessons B3 of project 05) ------------------------------------------------------------------------------------------

SIGN = "[+−-]?"
NUMBER = rf"({SIGN}\d+,\d+)"


def quoted_bound(text: str) -> tuple[float, int]:
    """A bound as a document writes it («−4,69», «+4,36»): its value and its number of decimals."""
    sign, digits = (-1.0, text[1:]) if text[0] in "−-" else (1.0, text.lstrip("+"))
    return sign * float(digits.replace(",", ".")), len(digits.split(",")[1])


def read(project_root: Path, name: str) -> str:
    return (project_root / "docs" / name).read_text(encoding="utf-8")


def decision(project_root: Path, number: int) -> str:
    """One entry of the register, from its heading to the next."""
    return read(project_root, "decisions.md").split(f"\n## D{number:02d} ")[1].split("\n## D")[0]


def root_rows(project_root: Path, *, required: bool = True) -> str:
    """The section of project 06 in the root ``SITE-UPDATES.md``, up to the next project or the end (empty when it is not required and there is none)."""
    text = (project_root.parent / "SITE-UPDATES.md").read_text(encoding="utf-8")
    if not required and "\n## 06 " not in text:
        return ""
    assert text.count("\n## 06 ") == 1, "SITE-UPDATES.md has no section for project 06"
    return re.split(r"\n## 0[7-9] ", text.split("\n## 06 ")[1])[0]


def test_every_quoted_interval_bound_equals_the_summary_at_its_decimals(project_root: Path, readme: str, model_card: str, summary: dict) -> None:
    """B3 of project 05: bounds rounded by hand came out wrong in two documents. Every interval of the criteria that have one (C01, C04, C08, C09: differences, in points)
    that D16 and D42, the README, the model card and the root rows quote is the summary's rounded to the decimals the document writes; and every lift of the test week or of
    the sealed 90 days that a document quotes with its interval («+46,5 % [41,0; 52,3]») has the bounds of the sealed files."""
    intervals = {c["criterion_id"]: (100 * c["ci_low"], 100 * c["ci_high"]) for c in summary["criteria"] if c["ci_low"] is not None}
    assert sorted(intervals) == ["C01", "C04", "C08", "C09"]
    named = "|".join(intervals)
    # a criterion named alone (not the end or the start of a range such as «C01-C04»), then, before any other criterion, «de <límite> a <límite>»
    interval = re.compile(rf"(?<![-–])\b({named})\b(?![-–])((?:(?!C\d\d)[^\n]){{0,260}}?)\bde {NUMBER} a {NUMBER}")
    documents = {"D16": decision(project_root, 16), "D42": decision(project_root, 42), "README.md": readme, "docs/model-card.md": model_card, "SITE-UPDATES.md (06)": root_rows(project_root, required=False)}
    wrong, seen = [], {}
    for name, text in documents.items():
        found = interval.findall(text)
        seen[name] = {criterion for criterion, *_rest in found}
        for criterion, _between, low, high in found:
            for written, value in ((low, intervals[criterion][0]), (high, intervals[criterion][1])):
                number, decimals = quoted_bound(written)
                if f"{number:.{decimals}f}" != f"{value:.{decimals}f}":
                    wrong.append(f"{name}: {criterion} writes {written}, the summary rounds to {value:.{decimals}f}")
    assert wrong == []
    assert seen["D16"] == seen["docs/model-card.md"] == set(intervals), seen   # the check is not vacuous
    assert {"C01", "C04", "C09"} <= seen["README.md"], seen
    # the lifts: the value and its interval, from the sealed files
    seal = json.loads((project_root / "reports" / "model_seal.json").read_text(encoding="utf-8"))
    test_effect, launch_effect = summary["test"]["effect"], seal["launch"]["effects"]["overall"]
    known = [(100 * e["lift"], 100 * e["ci_low"], 100 * e["ci_high"]) for e in (test_effect["raw"], test_effect["recovered"])]
    known += [(100 * e["lift"], 100 * e["ci_low"], 100 * e["ci_high"]) for e in (launch_effect["raw"], launch_effect["recovered"])]
    lift = re.compile(rf"({SIGN}\d+,\d+) % \(?\[({SIGN}\d+,\d+); ({SIGN}\d+,\d+)\]")
    off, matched = [], 0
    for name, text in {**documents, "docs/decisions.md": read(project_root, "decisions.md")}.items():
        for value, low, high in lift.findall(text):
            number, decimals = quoted_bound(value)
            for truth, truth_low, truth_high in known:
                if f"{number:.{decimals}f}" == f"{truth:.{decimals}f}":   # it is one of the lifts: its bounds must be that lift's
                    matched += 1
                    for written, expected in ((low, truth_low), (high, truth_high)):
                        bound, bound_decimals = quoted_bound(written)
                        if f"{bound:.{bound_decimals}f}" != f"{expected:.{bound_decimals}f}":
                            off.append(f"{name}: {value} % writes {written}, the sealed files round to {expected:.{bound_decimals}f}")
    assert off == []
    assert matched >= 4   # the documents do quote lifts with their intervals: the check is not vacuous
