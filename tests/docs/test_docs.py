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
import getpass
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from promolift.reporting import RESULTS_END, RESULTS_START

README_TITLE = "# Qué promociones venden de verdad"
USER_NAMES = {name.lower() for name in (getpass.getuser(), Path.home().name) if name}   # this machine's user, read here and never written in a test (A8)
EMAIL = re.compile(r"\S+@\S+")                                                         # a public contact address may carry a name: it is not a local path
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
    """RNF14: the independent evaluation is done (L85) and the check of its corrections and the ``.pbix`` are not, and the README says so; the credit of the source is
    complete; nothing local is published."""
    text = readme.lower()
    assert "evaluación independiente" in text and "comprobación" in text and "todavía no" in text and ".pbix" in text and "RNF02" in readme
    tail = section(readme, "Fuente y licencia")
    for piece in (
        "Dingdong-Inc", "FreshRetailNet-50K", "CC BY 4.0", "c374e859", "Wang et al. (2026)", "arXiv:2505.16319",
        "6706832db892bbae4969c19d87e07975d2543d2ba7d7d4756360654785de5a3d", "1b118840664280c6b88bffc84c80ee1f54c05d911e354b7599e5da10995e960e",
    ):
        assert piece in tail, piece
    for document in (readme, model_card):
        assert not re.search(r"[A-Za-z]:[\\/]+(Users|Documents and Settings)", document) and not any(name in EMAIL.sub("", document).lower() for name in USER_NAMES) and "@gmail" not in document


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


# --- U21: the decisions, the stated test count, the memory figures, the tests the plan names, the log, the dictionary, the runbook, the step by step, the advisories, the
# links and the root rows (AC37) ---------------------------------------------------------------------------------------------------------------------------------

NAMED_TEST = re.compile(r"(tests/[\w/]+\.py)?::(test_\w+)")
DECISION_FIELDS = ("Contexto", "Opciones", "Decisión", "Motivo", "Afecta", "Quién", "Estado")   # AC37: every decision, D01 to the last
COUNTERS = ("PeakWorkingSetSize", "PeakPagefileUsage", "ru_maxrss", "conjunto de trabajo", "memoria comprometida")   # by API name or by what it counts
MEMORY_FIGURE = re.compile(r"\d[\d.]*(?:,\d+)?\s?(?:MB|GB|MiB|GiB)\b")
MEMORY_WORDS = re.compile(r"pico|peak_|conjunto de trabajo|comprometid|memoria", re.IGNORECASE)   # the size of a file or a folder is not a memory figure
SENTENCE_END = re.compile(r"(?<=\.)\s+")
LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)#\s]+)(?:#[^)]*)?\)")
IMAGE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)\)")
UNITS_DONE = [f"U{n:02d}" for n in range(1, 22)]   # U01 to U21 have their entry in the log (U20 and U21 in L83)
STATUSES = ("corregida", "refutada", "dejada con evidencia", "abierta")
DOCS = ("data-dictionary.md", "runbook.md", "paso-a-paso.md", "review-advisories.md", "decisions.md", "evaluation.md")   # the independent evaluation, with its check, is in the tuple since L88
LOCAL_PATH = re.compile(r"[A-Za-z]:[\\/]+(?:Users|Documents and Settings)|/c/Users|Users\\|/home/\w+/")


def memory_documents(project_root: Path, readme: str, model_card: str) -> dict[str, str]:
    documents = {"README.md": readme, "docs/model-card.md": model_card, "SITE-UPDATES.md (06)": root_rows(project_root)}
    documents |= {f"docs/{name}": read(project_root, name) for name in DOCS}
    if (project_root / "docs" / "evaluation.md").is_file():
        documents["docs/evaluation.md"] = read(project_root, "evaluation.md")
    return documents


def stated_count(request: pytest.FixtureRequest) -> str:
    """The test count as the documents write it, from the collection of this session; skipped when the session did not collect the default selection in full
    (a count taken from a part of the suite would be another number, and collecting the rest in another process costs seconds: plan, section 24.1)."""
    from tests.fixtures.suite_budget import is_full_default_selection

    if not is_full_default_selection(request.config):
        pytest.skip("the session did not collect the default selection in full: its collection is not the suite's count")
    return f"{len(request.session.items):,}".replace(",", ".") + " pruebas"


def named_in_plan(plan: str) -> list[tuple[str, str]]:
    """Every test the plan names, as (file, function): a bare ``::name`` belongs to the file named last before it."""
    found, last = [], None
    for match in NAMED_TEST.finditer(plan):
        last = match.group(1) or last
        assert last is not None, match.group(0)
        found.append((last, match.group(2)))
    return found


def test_every_test_named_in_the_plan_exists(project_root: Path) -> None:
    """AC37: every test plan sections 24 and 27 name (the RED of each unit and the named defect classes) is a test function of that file."""
    named = named_in_plan((project_root / "docs" / "plan.md").read_text(encoding="utf-8"))
    assert len(named) >= 100   # the plan does name its tests: the check is not vacuous
    defined: dict[str, set[str]] = {}
    missing = []
    for path, name in named:
        if path not in defined:
            file = project_root / path
            tree = ast.parse(file.read_text(encoding="utf-8")) if file.is_file() else ast.Module(body=[], type_ignores=[])
            defined[path] = {node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        if name not in defined[path]:
            missing.append(f"{path}::{name}")
    assert sorted(set(missing)) == []


def test_every_decision_has_seven_fields(project_root: Path) -> None:
    text = read(project_root, "decisions.md")
    entries = re.split(r"^## (?=D\d+ )", text, flags=re.MULTILINE)[1:]
    numbers = [int(re.match(r"D(\d+)", e).group(1)) for e in entries]
    assert numbers == list(range(1, len(numbers) + 1)) and len(numbers) >= 44   # no gap and no repeat, up to this documentation's own
    missing = [f"D{n:02d}: {field}" for n, entry in zip(numbers, entries, strict=True) for field in DECISION_FIELDS if f"- **{field}**: " not in entry]
    assert missing == []
    states = {f"D{n:02d}": re.search(r"^- \*\*Estado\*\*: (.+)$", e, flags=re.MULTILINE).group(1) for n, e in zip(numbers, entries, strict=True)}
    assert [d for d, s in states.items() if not re.match(r"(vigente|pendiente del dueño|reemplazada por D\d+)", s)] == []


def test_stated_test_count_matches_the_session_collection(request: pytest.FixtureRequest, readme: str, model_card: str) -> None:
    """B3 of project 02, B5 of project 03 and B1 of project 04 (RNF14): the documents said one test count after a change had moved it. The count is that of the
    collection, in the README and the model card; the seconds next to it are measured and written by hand (AC38)."""
    stated = stated_count(request)
    assert re.findall(r"\b\d{1,3}(?:\.\d{3})* pruebas\b", readme) == [stated]   # the README states one count: this one
    assert re.findall(r"\b\d{1,3}(?:\.\d{3})* pruebas\b", section(model_card, "La suite rápida")) == [stated]


def test_every_memory_figure_names_its_counter(project_root: Path, readme: str, model_card: str) -> None:
    """RNF03 and D39 (lesson A3 of project 02): a memory figure without its counter cannot be compared with another. Every sentence of the documents that gives a
    memory figure in MB or GB names the counter, by its API name or by what it counts."""
    absent = [f"docs/{name}" for name in DOCS if not (project_root / "docs" / name).is_file()]
    assert absent == [], "every document of AC37 exists"
    figures, unnamed = 0, []
    for name, text in memory_documents(project_root, readme, model_card).items():
        for line in text.splitlines():
            for sentence in SENTENCE_END.split(line):
                if MEMORY_FIGURE.search(sentence) and MEMORY_WORDS.search(sentence):
                    figures += 1
                    if not any(counter in sentence for counter in COUNTERS):
                        unnamed.append(f"{name}: {sentence.strip()[:160]}")
    assert unnamed == []
    assert figures >= 6   # the documents do state memory figures: the check is not vacuous


def test_results_block_matches_summary(project_root: Path, readme: str, summary: dict) -> None:
    """Plan 24.2, the class «documentación sin sincronizar»: the block is the summary of the sealed run, its run and its date included."""
    block = readme.split(RESULTS_START)[1].split(RESULTS_END)[0].strip("\n")
    assert block == (project_root / "reports" / "evaluation_summary.md").read_text(encoding="utf-8").strip("\n")
    assert f"Corrida {summary['run_key']} del {summary['as_of']}." in block and "Estado: sealed." in block


LOG = "odd/tasks/portfolio-projects.md"
FIRST_LOG_ENTRY = 70   # L70 starts project 06


def log_entries(project_root: Path) -> dict[int, str]:
    """The entries L70 and later of the tracking document at the root of the repository, by number (skipped when the repository has no such document)."""
    path = project_root.parent / LOG
    if not path.is_file():
        pytest.skip("the tracking document is not next to the project")
    parts = re.split(r"^- \*\*L(\d+) ", path.read_text(encoding="utf-8"), flags=re.MULTILINE)[1:]
    return {int(number): body for number, body in zip(parts[::2], parts[1::2], strict=True) if int(number) >= FIRST_LOG_ENTRY}


def test_every_unit_the_docs_tell_has_its_log_entry(project_root: Path, readme: str) -> None:
    """B4 and N2 of project 05 (RNF14): the documents told units and corrections that the log did not have yet. Every unit (U01...) and every entry (L70...) that the README, the step
    by step and the advisories name is in the log, and the step by step names every unit the log has; the two units of documentation are named after their own entry exists."""
    entries = log_entries(project_root)
    assert max(entries) >= 81 and sorted(entries) == list(range(FIRST_LOG_ENTRY, max(entries) + 1))   # the log of project 06 is there, with no gap
    logged_units = {unit for body in entries.values() for unit in re.findall(r"\bU\d{2}\b", body)}
    assert set(UNITS_DONE) <= logged_units
    documents = {"README.md": readme, "docs/paso-a-paso.md": read(project_root, "paso-a-paso.md"), "docs/review-advisories.md": read(project_root, "review-advisories.md")}
    if (project_root / "docs" / "evaluation.md").is_file():
        documents["docs/evaluation.md"] = read(project_root, "evaluation.md")
    told = {name: set(re.findall(r"\bU\d{2}\b", text)) for name, text in documents.items()}
    assert [(name, sorted(units - logged_units)) for name, units in told.items() if units - logged_units] == []   # no unit that the log does not have
    cited = {name: {int(n) for n in re.findall(r"\bL(\d{2,3})\b", text)} for name, text in documents.items()}
    assert [(name, sorted(numbers - set(entries))) for name, numbers in cited.items() if numbers - set(entries)] == []   # no entry that the log does not have
    assert set(UNITS_DONE) <= told["docs/paso-a-paso.md"]   # the step by step names every unit the log has
    assert set(range(70, 89)) <= cited["docs/paso-a-paso.md"]   # and every entry of the project so far: the evaluation (L85), the corrections and their reviews (L86, L87) and the check (L88)


def test_the_dictionary_covers_the_source_and_its_tables_are_the_generated_ones(project_root: Path) -> None:
    import pyarrow.parquet as pq

    from promolift.dashboard.semantic_model import MODEL, arrow_schema
    from promolift.days import STATE_NAMES
    from promolift.docs_sync import COLUMNS_END, COLUMNS_START, render_dictionary_tables
    from promolift.schema import DAILY_KEPT, FORBIDDEN_COLUMNS, SOURCE_COLUMNS

    text = read(project_root, "data-dictionary.md")
    source = text.split("\n## Archivo de origen\n")[1].split("\n## ")[0]
    rows = re.findall(r"^\| `([^`]+)` \| `([^`]+)` \| ([^|]+?) \| ([^|]+?) \|$", source, flags=re.MULTILINE)
    assert [name for name, *_rest in rows] == list(SOURCE_COLUMNS) and len(rows) == 19   # the 19 columns of both files, in file order
    assert all(cell.strip() for row in rows for cell in row)
    use = {name: how for name, _type, how, _meaning in rows}
    assert {name for name, how in use.items() if how == "prohibido"} == set(FORBIDDEN_COLUMNS)   # the six that never pass the reader
    assert set(DAILY_KEPT) <= {name for name, how in use.items() if how == "se usa"} and set(use.values()) <= {"identificador", "se usa", "prohibido"}
    states = text.split("\n## Estados del día\n")[1].split("\n## ")[0]
    assert re.findall(r"^\| `([a-z_]+)` \|", states, flags=re.MULTILINE) == list(STATE_NAMES)
    assert len(re.findall(r"^\| \d \|", text.split("\n## Bandas de descuento\n")[1].split("\n## ")[0], flags=re.MULTILINE)) == 7
    assert text.count(COLUMNS_START) == 1 and text.count(COLUMNS_END) == 1
    block = text.split(COLUMNS_START)[1].split(COLUMNS_END)[0]
    assert block.strip() == render_dictionary_tables(MODEL).strip()   # what docs-sync writes
    assert re.findall(r"^### `([a-z_]+)`$", block, flags=re.MULTILINE) == [t.name for t in MODEL.tables] and len(MODEL.tables) == 25
    for table in MODEL.tables:
        part = block.split(f"### `{table.name}`\n")[1].split("\n### ")[0]
        listed = re.findall(r"^\| `([a-z_0-9]+)` \| [^|]+ \| ([^|]+) \| ", part, flags=re.MULTILINE)
        assert tuple(name for name, _unit in listed) == table.column_names and all(unit.strip() for _name, unit in listed), table.name
        assert pq.read_schema(project_root / "outputs" / "powerbi" / f"{table.name}.parquet").names == list(table.column_names) == arrow_schema(table).names, table.name


def _sync_project(project_root: Path, tmp_path: Path, dictionary: str | None) -> str:
    (tmp_path / "config").mkdir()
    shutil.copyfile(project_root / "config" / "pipeline.toml", tmp_path / "config" / "pipeline.toml")
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "evaluation_summary.md").write_text("## Resultados\n\n| C01 | no supera |\n", encoding="utf-8", newline="\n")
    (tmp_path / "README.md").write_text(f"# P\n\n{RESULTS_START}\nviejo\n{RESULTS_END}\n", encoding="utf-8", newline="\n")
    if dictionary is not None:   # next to the figures folder of the configuration (docs/figures), as docs/ is in the project
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "data-dictionary.md").write_text(dictionary, encoding="utf-8", newline="\n")
    return str(tmp_path / "config" / "pipeline.toml")


def test_docs_sync_writes_the_dictionary_tables_and_a_second_run_changes_nothing(project_root: Path, tmp_path: Path, capsys) -> None:
    from promolift import cli
    from promolift.dashboard.semantic_model import MODEL
    from promolift.docs_sync import COLUMNS_END, COLUMNS_START, render_dictionary_tables

    config = _sync_project(project_root, tmp_path, f"# D\n\n{COLUMNS_START}\nviejo\n{COLUMNS_END}\n\nal final\n")
    assert cli.main(["docs-sync", "--config", config]) == 0
    assert capsys.readouterr().out.splitlines() == ["README.md actualizado", "data-dictionary.md actualizado"]
    text = (tmp_path / "docs" / "data-dictionary.md").read_text(encoding="utf-8")
    assert text == f"# D\n\n{COLUMNS_START}\n{render_dictionary_tables(MODEL).strip()}\n{COLUMNS_END}\n\nal final\n" and "viejo" not in text
    assert "| C01 | no supera |" in (tmp_path / "README.md").read_text(encoding="utf-8")
    assert cli.main(["docs-sync", "--config", config]) == 0
    assert capsys.readouterr().out.splitlines() == ["README.md ya estaba al día", "data-dictionary.md ya estaba al día"]


def test_docs_sync_without_a_dictionary_still_syncs_only_the_readme(project_root: Path, tmp_path: Path, capsys) -> None:
    """The command as it was before this unit: with no dictionary next to the figures folder, it writes the README block and says only that."""
    from promolift import cli

    config = _sync_project(project_root, tmp_path, None)
    assert cli.main(["docs-sync", "--config", config]) == 0
    assert capsys.readouterr().out.splitlines() == ["README.md actualizado"]
    assert not (tmp_path / "docs").exists()


def test_docs_sync_with_a_dictionary_without_its_markers_exits_2_and_writes_nothing(project_root: Path, tmp_path: Path, capsys) -> None:
    from promolift import cli

    config = _sync_project(project_root, tmp_path, "# D\n\nsin marcadores\n")
    before = {path: path.read_bytes() for path in sorted(tmp_path.rglob("*")) if path.is_file()}
    assert cli.main(["docs-sync", "--config", config]) == 2
    captured = capsys.readouterr()
    assert captured.out == "" and "data-dictionary.md" in captured.err and "columns:start" in captured.err and "No se escribió nada" in captured.err
    assert {path: path.read_bytes() for path in sorted(tmp_path.rglob("*")) if path.is_file()} == before   # the README was not written either


def test_docs_sync_with_a_column_type_the_dictionary_cannot_name_exits_2_and_writes_nothing(project_root: Path, tmp_path: Path, capsys, monkeypatch) -> None:
    """A type of the semantic model that ``DTYPE_ES`` does not name is a ``ValueError`` that names the column, which ``docs-sync`` turns into exit 2; the tables are rendered
    before any file is written, so neither the README nor the dictionary changes."""
    from promolift import cli, docs_sync

    monkeypatch.setattr(docs_sync, "DTYPE_ES", {k: v for k, v in docs_sync.DTYPE_ES.items() if k != "date"})
    config = _sync_project(project_root, tmp_path, f"# D\n\n{docs_sync.COLUMNS_START}\nviejo\n{docs_sync.COLUMNS_END}\n")
    before = {path: path.read_bytes() for path in sorted(tmp_path.rglob("*")) if path.is_file()}
    assert cli.main(["docs-sync", "--config", config]) == 2
    captured = capsys.readouterr()
    assert captured.out == "" and "'date'" in captured.err and "DTYPE_ES" in captured.err and "No se escribió nada" in captured.err, captured.err
    assert {path: path.read_bytes() for path in sorted(tmp_path.rglob("*")) if path.is_file()} == before


def test_the_help_of_docs_sync_names_both_blocks(capsys) -> None:
    from promolift import cli

    assert cli.main(["docs-sync", "--help"]) == 0
    help_text = " ".join(capsys.readouterr().out.split())
    assert "README" in help_text and "diccionario de datos" in help_text and "tablas" in help_text


RUNBOOK_TOPICS = {   # what each entry the code cites has to be about (the refusal messages and the compose header point here)
    1: ("s00_download.py", "106.436.287"), 2: ("V02",), 3: ("load", "validación"), 4: ("entrega", "orden"), 5: ("M01", "fuga"), 6: ("huella", "r3.pkl"),
    7: ("sello", "post_seal"), 8: ("bloqueo", "database is locked"), 9: ("análisis nuevo", "sello"), 10: ("12 GB", "Docker", "PeakWorkingSetSize"), 11: ("desde cero", "manifest"),
    12: ("cubo", "manifiesto"),
}


def test_the_runbook_has_r1_to_r12_and_every_reference_of_the_code_points_to_one(project_root: Path) -> None:
    text = read(project_root, "runbook.md")
    entries = re.split(r"^## (?=R\d+ )", text, flags=re.MULTILINE)[1:]
    assert [entry.split()[0] for entry in entries] == [f"R{n}" for n in range(1, 13)]   # plan, section 25
    for entry in entries:
        assert "**Síntoma.**" in entry and "**Qué hacer.**" in entry, entry.splitlines()[0]
    for number, words in RUNBOOK_TOPICS.items():
        entry = entries[number - 1]
        assert [word for word in words if word.lower() not in entry.lower()] == [], f"R{number}"
    sources = [*sorted((project_root / "src" / "promolift").rglob("*.py")), *sorted((project_root / "airflow").rglob("*.py")), project_root / "airflow" / "docker-compose.yaml"]
    cited = {int(n) for path in sources for n in re.findall(r"runbook(?:\.md)?,? R(\d+)", path.read_text(encoding="utf-8"))}
    assert {1, 2, 3, 4, 5, 6, 7, 8, 10, 11, 12} <= cited <= set(range(1, 13)), cited   # R4, R7, R8 and R10 among them: every entry the code points to exists and is about that


def test_the_step_by_step_names_every_unit_and_cites_commits_that_exist(project_root: Path) -> None:
    text = read(project_root, "paso-a-paso.md")
    assert [unit for unit in UNITS_DONE if not re.search(rf"\b{unit}\b", text)] == []
    hashes = sorted(set(re.findall(r"`([0-9a-f]{7})`", text)))
    assert len(hashes) >= 27   # the 27 commits of the project up to the real run, and more
    if shutil.which("git") is None or not (project_root.parent / ".git").exists():
        pytest.skip("there is no Git history to check the commits against")
    done = subprocess.run(["git", "cat-file", "--batch-check"], cwd=project_root, input="".join(f"{h}^{{commit}}\n" for h in hashes), capture_output=True, text=True)
    assert [line for line in done.stdout.splitlines() if line.endswith("missing")] == []
    # the chronology is whole: every commit of the project up to the real run (U19) is in it
    history = subprocess.run(["git", "log", "--abbrev=7", "--format=%h", "6253c31", "--", "."], cwd=project_root, capture_output=True, text=True)
    assert history.returncode == 0 and [h for h in history.stdout.split() if h not in hashes and h != "1d5d1e3"] == []   # 1d5d1e3 is the scaffold of the portfolio


def test_relative_links_and_images_point_to_files_that_exist(project_root: Path, readme: str) -> None:
    """Every relative link and image of the README and of the documents resolves, and the README links to every document of ``docs/`` that exists."""
    broken = []
    for document in [project_root / "README.md", *sorted((project_root / "docs").glob("*.md"))]:
        text = document.read_text(encoding="utf-8")
        for target in [*LINK.findall(text), *IMAGE.findall(text)]:
            if not re.match(r"^(https?:|mailto:)", target) and not (document.parent / target).resolve().exists():
                broken.append(f"{document.name}: {target}")
    assert broken == []
    unlinked = [f"docs/{name}" for name in ("research.md", "requirements.md", "plan.md", "decisions.md", "model-card.md", *DOCS) if f"](docs/{name})" not in readme]
    assert unlinked == []


def advisories(text: str) -> dict[tuple[str, str], str]:
    """Every advisory of the review file by (section key, id), with its status: the bold words after «Estado:», or an empty string."""
    found: dict[tuple[str, str], str] = {}
    for part in re.split(r"^## ", text, flags=re.MULTILINE)[1:]:
        key = part.split()[0]
        for block in re.split(r"^(?=- \*\*)", part, flags=re.MULTILINE)[1:]:
            ident = re.match(r"- \*\*([^*]+)\*\*", block).group(1)
            status = re.search(r"^  - Estado: \*\*([^*]+)\*\*", block, flags=re.MULTILINE)
            assert (key, ident) not in found, (key, ident)
            found[(key, ident)] = status.group(1) if status else ""
    return found


def test_open_advisories_match_review_file(project_root: Path, readme: str) -> None:
    """AC37 and B5 of project 03's evaluation: every advisory of every native review (L74, L76, L78, L80, L82, L84 and L87: 33 in all) and N1 of the check (L88), 34 in all, has its location and its status in
    ``docs/review-advisories.md`` (corrected, with its commit; refuted or left with evidence, with the reason; or open), and the advisories the README calls open are the ones
    that file calls open. After the corrections that followed the evaluation (plan, section 28), none is open."""
    text = read(project_root, "review-advisories.md")
    found = advisories(text)
    assert len(found) == 34 and [key for key, status in found.items() if status not in STATUSES] == []
    blocks = [block for block in re.split(r"^(?=- \*\*)", text, flags=re.MULTILINE) if block.startswith("- **")]
    assert all(re.search(r"^  - Ubicación: .+", block, flags=re.MULTILINE) for block in blocks)   # where each one is
    fixed = [block for block in blocks if "Estado: **corregida**" in block]
    assert len(fixed) == 17 and all(re.search(r"`[0-9a-f]{7}`", block.split("Estado: **corregida**")[1].splitlines()[0]) for block in fixed)   # each with its commit
    left = [block for block in blocks if re.search(r"Estado: \*\*(dejada con evidencia|refutada)\*\*\. \S", block)]
    assert len(left) == 17, "every finding left as it is or refuted says why"
    opened = sorted(f"{key}/{ident}" for (key, ident), status in found.items() if status == "abierta")
    [stated] = re.findall(r"^Advertencias abiertas: (.+)$", readme, flags=re.MULTILINE)
    assert sorted(re.findall(r"`([^`]+)`", stated)) == opened == [] and stated == "ninguna.", stated
    assert "todavía no consta" not in text and "20 en total" not in text and "L82" in text and "lens_context_budget_exceeded" in text   # B3 of the evaluation


STALE_PENDING = re.compile(
    r"pendiente de la (?:evaluaci|comprobaci)|comprobaci[oó]n pendiente|comprobaci[oó]n de (?:esas |sus |las )?correcciones[^.\n]{0,80}(?:todav[ií]a no|pendiente|a[uú]n no)"
    r"|sin la comprobaci[oó]n|escribe quien compruebe|\*\*Pendiente\.\*\*",
    flags=re.IGNORECASE,
)


def test_the_evaluation_and_its_check_are_recorded_as_done_and_no_document_says_otherwise(project_root: Path, readme: str, model_card: str) -> None:
    """Plan, section 28.4, and B4 and N1 of project 05 (RNF14): after the evaluation (L85), its corrections (L86) and the check (L88), ``docs/evaluation.md`` has the check written
    (no section left pending), each blocker is corrected in the evaluation and again in the check, and no document or root row still says the evaluation or the check is pending.
    N1 of the check: D49 carries a dated note that counts the review findings as the file of advisories does (24)."""
    text = read(project_root, "evaluation.md")
    blockers = [f"B{n}" for n in range(1, 5)]
    for title in ("Los bloqueantes", "Comprobación"):
        parts = {m.group(1): m.group(2) for m in re.finditer(r"^### (B\d)\. (.*?)(?=^### |\Z)", section(text, title), flags=re.MULTILINE | re.DOTALL)}
        assert sorted(parts) == blockers, title
        assert [b for b in blockers if not re.search(r"\*\*Estado: corregida", parts[b])] == [], title   # each blocker says it is corrected, in the evaluation and in the check
    assert [a for a in (f"A{n}" for n in range(1, 10)) if not re.search(rf"^- \*\*{a}\.\*\*.*\*\*Estado[.:]", text, flags=re.MULTILINE)] == []   # and each advisory says its state
    assert "Otro agente con Opus, que no escribió las correcciones" in section(text, "Comprobación") and "L88" in text
    documents = {"README.md": readme, "docs/model-card.md": model_card, "SITE-UPDATES.md (06)": root_rows(project_root)} | {f"docs/{name}": read(project_root, name) for name in DOCS}
    stale = [f"{name}: {match.group(0)}" for name, document in documents.items() for match in STALE_PENDING.finditer(document)]
    assert stale == []
    assert "no se hicieron todavía" not in read(project_root, "paso-a-paso.md").split("\n## ")[0]   # L87's warning: the introduction says what its own sections tell
    d49 = decision(project_root, 49)
    estado = re.search(r"^- \*\*Estado\*\*: (.+)$", d49, flags=re.MULTILINE).group(1)
    assert re.search(r"\*\*Nota del 2026-11-18 \(comprobación, N1, L88\)\*\*: .*24 hallazgos", estado)   # N1 of the check (L88): the entry keeps its words and a dated note says the count is 24


def test_the_root_rows_of_project_06_carry_the_real_figures(project_root: Path) -> None:
    rows = root_rows(project_root)
    table = [line for line in rows.split("### ")[0].splitlines() if re.match(r"^\| \d+ \|", line)]
    assert [int(line.split("|")[1]) for line in table] == list(range(1, 19))   # plan, section 30: the eighteen rows
    for figure in ("46,5", "47,9", "52,0", "52,9", "0,897", "58,3", "40,3", "35,0", "43,9", "−1,81", "+4,36", "103.629", "183", "903", "876", "62", "68", "4.077,9", "5.808,7"):
        assert figure in rows, figure
    assert rows.count("no supera") >= 1 and rows.count("no cumple") >= 2 and all(f"C{n:02d}" in rows for n in range(1, 10)) and "PeakWorkingSetSize" in rows
    assert "RNF02" in rows and "Aplicado en el sitio el 2026-11-18" in rows and "No aplicado" not in rows and "@gmail" not in rows   # the page is applied (marca-personal L131)
    assert not re.search(r"[A-Za-z]:[\\/]+(Users|Documents and Settings)", rows) and "Users" not in rows


def test_the_landing_expansion_names_project_06_in_the_rows_it_uses_and_adds_no_library(project_root: Path) -> None:
    """D32: project 06 is added to the rows of pyarrow, NumPy, SQLite, matplotlib, pytest and PostgreSQL; it adds none (statsmodels is not used)."""
    text = (project_root.parent / "LANDING-EXPANSION.md").read_text(encoding="utf-8")
    rows = {line.split("|")[1].strip(): line for line in text.splitlines() if re.match(r"^\| [^|]+ \|", line)}
    for technology in ("NumPy", "SQLite", "Apache Parquet con pyarrow", "matplotlib", "pytest", "PostgreSQL"):
        assert "06 Qué promociones" in rows[technology], technology
    assert [name for name in rows if "06 Qué promociones" in rows[name]] == ["NumPy", "SQLite", "Apache Parquet con pyarrow", "matplotlib", "pytest", "PostgreSQL"]
    assert "statsmodels" not in text.lower() or "no se usa" in text.lower()


def test_no_document_publishes_a_local_path_or_a_user_name(project_root: Path, readme: str) -> None:
    """The README, every document of ``docs/`` and the root rows name no path of the machine and no user name."""
    documents = {"README.md": readme, "SITE-UPDATES.md (06)": root_rows(project_root)}
    documents |= {f"docs/{path.name}": path.read_text(encoding="utf-8") for path in sorted((project_root / "docs").glob("*.md"))}
    found = [name for name, text in documents.items() if LOCAL_PATH.search(text) or any(name in EMAIL.sub("", text).lower() for name in USER_NAMES)]
    assert found == []


def test_no_test_and_no_source_file_carries_this_machine_s_user_name(project_root: Path) -> None:
    """A8 (L85): two tests wrote the user's name as a literal to check that nothing published carries it; they read it from the machine now, and no versioned code does."""
    texts = {path.relative_to(project_root).as_posix(): path.read_text(encoding="utf-8") for folder in ("tests", "src") for path in sorted((project_root / folder).rglob("*.py"))}
    assert [name for name, text in texts.items() if any(user in EMAIL.sub("", text).lower() for user in USER_NAMES)] == []


def _pct(value: float | None) -> str:
    return f"{value * 100:,.1f} %".replace(",", "§").replace(".", ",").replace("§", ".").replace("-", "−")


def _thousands(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def test_the_band_and_day_tables_of_the_model_card_are_the_site_files(project_root: Path, model_card: str) -> None:
    """L84's suggestion on U20: the per-band and per-day tables of the model card were generated by a script that is not versioned, and no test pinned them. Each row is
    the one of ``algorithms.json`` (bands) and ``operation.json`` (days), at the decimals the card writes."""
    algorithms = json.loads((project_root / "outputs" / "site" / "algorithms.json").read_text(encoding="utf-8"))
    operation = json.loads((project_root / "outputs" / "site" / "operation.json").read_text(encoding="utf-8"))
    bands = [f"| {b['label_es']} | {_thousands(b['series'])} | {_pct(b['raw'])} | {_pct(b['recovered'])} | [{_pct(b['ci_low'])}; {_pct(b['ci_high'])}] |" for b in algorithms["bands"]]
    days = [f"| {d['date']} | {_thousands(d['promo_series_days'])} | {_pct(d['lift_raw'])} | {_pct(d['lift_recovered'])} | {_pct(d['stockout_rate'])} |" for d in operation["days"]]
    lines = model_card.splitlines()
    for row in bands + days:
        assert row in lines, row
    assert len(bands) == 7 and len(days) == 7


TABLE_DELIMITER = re.compile(r"^\|(?:\s*:?-{3,}:?\s*\|)+\s*$")


def _cells(line: str) -> int:
    return len(re.split(r"(?<!\\)\|", line.strip().removeprefix("|").removesuffix("|")))


def test_every_markdown_table_has_as_many_cells_in_its_delimiter_and_its_rows_as_in_its_header(project_root: Path, readme: str) -> None:
    """L84's finding on U21 said the dictionary's generated tables had a delimiter row of three cells under a header of four, so GitHub would not render them. They have
    four (the finding did not reproduce); this keeps every table of the README and of ``docs/`` well formed, generated or written by hand."""
    documents = {"README.md": readme} | {f"docs/{p.name}": p.read_text(encoding="utf-8") for p in sorted((project_root / "docs").glob("*.md"))}
    broken, tables = [], 0
    for name, text in documents.items():
        lines, fenced = text.splitlines(), False
        for at, line in enumerate(lines):
            fenced = fenced != line.startswith("```")
            if fenced or not TABLE_DELIMITER.match(line):
                continue
            tables += 1
            width = _cells(lines[at - 1])
            rows = lines[at:]
            body = rows[: next((k for k, row in enumerate(rows) if not row.startswith("|")), len(rows))]   # the delimiter and the rows under it, up to the first line that is not a table row
            broken += [f"{name}:{at + 1 + k}" for k, row in enumerate(body) if _cells(row) != width]
    assert broken == [] and tables >= 40
