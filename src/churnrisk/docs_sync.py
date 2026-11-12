"""What ``python -m churnrisk docs-sync`` writes into the documentation (RF24, RF29, AC25, AC40; plan, section 25; D82, D87, D88).

The results block of the README is the summary the ``report`` task writes (``reports/evaluation_summary.md``), copied between the
``results`` markers with the same ``sync_block`` the tests of U17 pin. The summary starts with its own ``## Resultados``: the README already
has the plan's ``## Los resultados`` above the block, so every heading of the summary goes one level down inside it and the README keeps
exactly the second-level headings of the plan. Nothing else of the summary changes, so a test can rebuild the summary from the block.

The tables of the data dictionary come from the semantic model (``dashboard.semantic_model.MODEL``), the specification the export checks
every Parquet file against: one section per table, in the order of the model, with every column, its type, its unit and its meaning,
between the ``columns`` markers of ``docs/data-dictionary.md``. The customer-level fact is there too, marked as not versioned. Adapted from
project 03's ``docs.py``.
"""

from __future__ import annotations

import re
from pathlib import Path

from churnrisk.dashboard.semantic_model import SemanticModel
from churnrisk.reporting import RESULTS_END, RESULTS_START, sync_block

_HEADING = re.compile(r"^(#+ )", flags=re.MULTILINE)
COLUMNS_START = "<!-- columns:start -->"
COLUMNS_END = "<!-- columns:end -->"
DICTIONARY_NAME = "data-dictionary.md"
KIND_ES = {"dimension": "Dimensión", "fact": "Hecho"}
KEY_ES = {"dimension": "Clave", "fact": "Grano"}
DTYPE_ES = {"int32": "entero 32", "int64": "entero 64", "float64": "decimal", "string": "texto", "bool": "verdadero/falso", "date": "fecha"}
NO_UNIT = "—"
PRIVATE_ES = ("Se escribe en `outputs/private/`, que no se versiona: es la única tabla con el número de cliente, para el `.pbix` armado en "
              "el equipo del dueño (D26).")
VERSIONED_ES = "Se versiona en `outputs/powerbi/{name}.parquet`."


def readme_block(summary_md: str) -> str:
    """The summary as the README holds it: every Markdown heading one level down, the rest byte for byte."""
    return _HEADING.sub(r"#\1", summary_md)


def sync_readme(readme: Path, summary_md: Path) -> bool:
    """Copy `summary_md` into the results block of `readme`; True if the README changed (a second run changes nothing)."""
    return sync_block(Path(readme), RESULTS_START, RESULTS_END, readme_block(Path(summary_md).read_text(encoding="utf-8")))


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def render_dictionary_tables(model: SemanticModel) -> str:
    """One section per table of the model, in its order: what it is, where it is written, its key or grain, and every column with its
    type, unit and meaning."""
    lines: list[str] = []
    for table in model.tables:
        keys = ", ".join(f"`{k}`" for k in table.key)
        where = PRIVATE_ES if table.private else VERSIONED_ES.format(name=table.name)
        lines += [f"### `{table.name}`", "", f"{KIND_ES[table.kind]}. {_cell(table.description_es)} {where} {KEY_ES[table.kind]}: {keys}.", ""]
        lines += ["| Columna | Tipo | Unidad | Significado |", "| --- | --- | --- | --- |"]
        lines += [f"| `{c.name}` | {DTYPE_ES[c.dtype]} | {_cell(c.unit or NO_UNIT)} | {_cell(c.description_es)} |" for c in table.columns]
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def dictionary_path(figures_dir: Path) -> Path:
    """Where the dictionary lives: next to the figures folder (``docs/`` in the project; the quick mode has none)."""
    return Path(figures_dir).parent / DICTIONARY_NAME


def sync_dictionary(dictionary: Path, model: SemanticModel) -> bool:
    """Write the tables between the ``columns`` markers of the dictionary; True if the file changed (a second run changes nothing)."""
    return sync_block(Path(dictionary), COLUMNS_START, COLUMNS_END, render_dictionary_tables(model))


__all__ = ["COLUMNS_END", "COLUMNS_START", "dictionary_path", "readme_block", "render_dictionary_tables", "sync_dictionary", "sync_readme"]
