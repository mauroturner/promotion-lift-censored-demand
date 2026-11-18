"""What ``python -m promolift docs-sync`` writes into ``docs/data-dictionary.md`` (RF24, AC37; plan, section 25; D44). Adapted from project 05's ``docs.py``.

The README's results block is the summary the ``report`` task writes, copied between the ``results`` markers by ``reporting.replace_block``; that part of ``docs-sync`` stays in
``cli.py``. The tables of the data dictionary come from the semantic model (``dashboard.semantic_model.MODEL``), the specification the export checks every Parquet file against:
one section per table, in the order of the model, with every column, its type, its unit and its meaning, between the ``columns`` markers of the dictionary, written with the
same ``replace_block`` so that a second run changes nothing. The 19 source columns, the day states and the bands are written by hand and checked against ``schema.py`` and
``days.py`` by a test (``tests/docs/test_docs.py``).
"""

from __future__ import annotations

from pathlib import Path

from promolift.dashboard.semantic_model import SemanticModel

COLUMNS_START = "<!-- columns:start -->"
COLUMNS_END = "<!-- columns:end -->"
DICTIONARY_NAME = "data-dictionary.md"
KIND_ES = {"dimension": "Dimensión", "fact": "Hecho"}
KEY_ES = {"dimension": "Clave", "fact": "Grano"}
DTYPE_ES = {"int8": "entero 8", "int16": "entero 16", "int32": "entero 32", "int64": "entero 64", "float64": "decimal", "string": "texto", "bool": "verdadero/falso", "date": "fecha",
            "datetime": "fecha y hora"}
NO_UNIT = "—"
VERSIONED_ES = "Se versiona en `outputs/powerbi/{name}.parquet`."


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _dtype_es(table: str, column: str, dtype: str) -> str:
    """The name the dictionary gives a type; one ``DTYPE_ES`` does not name is a ``ValueError`` that names the column, which ``docs-sync`` turns into exit 2."""
    try:
        return DTYPE_ES[dtype]
    except KeyError:
        raise ValueError(f"el tipo {dtype!r} de la columna {table}.{column} no tiene nombre en el diccionario (docs_sync.DTYPE_ES)") from None


def render_dictionary_tables(model: SemanticModel) -> str:
    """One section per table of the model, in its order: what it is, where it is written, its key or grain, and every column with its type, unit and meaning."""
    lines: list[str] = []
    for table in model.tables:
        keys = ", ".join(f"`{k}`" for k in table.key)
        lines += [f"### `{table.name}`", "", f"{KIND_ES[table.kind]}. {_cell(table.description_es)} {VERSIONED_ES.format(name=table.name)} {KEY_ES[table.kind]}: {keys}.", ""]
        lines += ["| Columna | Tipo | Unidad | Significado |", "| --- | --- | --- | --- |"]
        lines += [f"| `{c.name}` | {_dtype_es(table.name, c.name, c.dtype)} | {_cell(c.unit or NO_UNIT)} | {_cell(c.description_es)} |" for c in table.columns]
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def dictionary_path(figures_dir: Path) -> Path:
    """Where the dictionary lives: next to the figures folder (``docs/`` in the project; the quick mode has none)."""
    return Path(figures_dir).parent / DICTIONARY_NAME


__all__ = ["COLUMNS_END", "COLUMNS_START", "DTYPE_ES", "dictionary_path", "render_dictionary_tables"]
