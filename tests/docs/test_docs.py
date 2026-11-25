"""The documentation is checked like code (AC25, AC40; RF24, RF29; RNF09, RNF14; plan, sections 25 and 26).

U30: the README has the headings of the portfolio's numbered outline (ESTRUCTURA-PROYECTOS.md, after plan section 25) in their order and its
results block, in an appendix, is the sealed summary that ``docs-sync`` copies, never a block written by hand; the README says the
unfavourable verdicts («no supera») in «1. Resumen ejecutivo» and in «5.1 Evaluación frente a criterios de éxito», and has no section
about how AI built the project;
the model card has the contents the plan lists, every verdict as the summary writes it, the memory counters and the suite's limit. These
tests read the versioned Markdown and the versioned reports (``reports/`` holds the outputs of U29) and run nothing, except the ``docs-sync``
tests, which work on a copy of the configuration in a temporary folder.

U31: every decision has its seven fields; the test count the documents give is the one of the session's collection; every memory figure
names its counter; every test the plan names exists; the results block is the sealed summary; the dictionary covers the 8 source columns
and the 16 features, and its tables are the ones ``docs-sync`` writes from the semantic model; the runbook has R1 to R14; the step by step
names every unit and cites commits that exist; the links resolve; every advisory of the native reviews has its status and the README's open
ones are the review file's; and the root rows of project 04 carry the real figures (plan, sections 25 and 30; D37).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from churnrisk.reporting import RESULTS_END, RESULTS_START

README_TITLE = "# Gradient boosting y SHAP para la predicción de la baja de clientes"
README_HEADINGS = [   # the numbered outline of ESTRUCTURA-PROYECTOS.md, then the appendices, in this order (AC40)
    "1. Resumen ejecutivo", "2. Datasets y preparación", "3. Arquitectura y metodología", "4. Producto final", "5. Conclusión",
    "Resultados completos de la corrida", "Revisiones y evaluación", "Cómo correrlo de punta a punta", "Paso a paso", "Fuente y licencia",
]
README_SUBSECTIONS = [
    "1.1 Problema de negocio y solución", "1.2 Criterios de éxito e impacto",
    "2.1 Fuentes, alcance y granularidad", "2.2 Saneamiento y reglas de calidad",
    "3.1 Fuente e ingesta", "3.2 Orquestación y transformación", "3.3 Almacenamiento y modelado de datos",
    "3.4 Experimentación y Machine Learning", "3.5 Consumo y gobernanza",
    "4.1 Entregables operativos", "4.2 Lectura de resultados actuales",
    "5.1 Evaluación frente a criterios de éxito", "5.2 Limitaciones metodológicas", "5.3 Trabajo futuro",
]
README_ML_SUBSECTIONS = [
    "3.4.1 Ingeniería de características y línea base (baseline)", "3.4.2 Decisiones de modelado y ablación (ADR)",
    "3.4.3 Protocolo de validación (backtesting / cross-validation)",
]
MODEL_CARD_HEADINGS = [   # what plan section 25 lists for the model card, in this order
    "Uso previsto y no previsto", "Datos", "La definición de baja y su ruido", "La población y los invitados", "Cortes y estacionalidad",
    "Variables", "Partición", "Métodos", "Calibración", "SHAP y qué explica", "Umbral y costos supuestos", "Criterios y resultados",
    "Sensibilidades", "Limitaciones", "Tiempos y memoria", "La suite rápida",
]
FAILED = ["C01", "C02", "C03", "C04", "C05", "C07", "C09"]   # D85: what the sealed run says
PASSED = ["C06", "C08"]


def root_document(project_root: Path, name: str) -> str:
    """A document at the portfolio's root. The project is also published on its own repository, where the test that reads it is skipped."""
    path = project_root.parent / name
    if not path.is_file():
        pytest.skip(f"{name} is at the root of the portfolio, which is not here")
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def readme(project_root: Path) -> str:
    return (project_root / "README.es.md").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def model_card(project_root: Path) -> str:
    return (project_root / "docs" / "model-card.md").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def summary(project_root: Path) -> dict:
    return json.loads((project_root / "reports" / "evaluation_summary.json").read_text(encoding="utf-8"))


def section(text: str, title: str) -> str:
    """The body of the second-level section `title`, up to the next second-level heading."""
    return re.split(r"^## ", text.split(f"\n## {title}\n", 1)[1], flags=re.MULTILINE)[0]


def test_readme_headings_in_order_and_results_block_matches_summary(project_root: Path, readme: str, summary: dict) -> None:
    check_the_english_readme(project_root, readme)
    assert readme.startswith(README_TITLE + "\n")
    assert re.findall(r"^## (.+)$", readme, flags=re.MULTILINE) == README_HEADINGS   # the block's own headings sit one level down
    assert re.findall(r"^### (\d.+)$", readme, flags=re.MULTILINE) == README_SUBSECTIONS
    assert re.findall(r"^#### (\d.+)$", readme, flags=re.MULTILINE) == README_ML_SUBSECTIONS
    assert "Con IA, de punta a punta" not in readme and "agente" not in readme.lower()
    assert readme.count(RESULTS_START) == 1 and readme.count(RESULTS_END) == 1
    from churnrisk.docs_sync import readme_block   # the copy docs-sync makes
    block = readme.split(RESULTS_START)[1].split(RESULTS_END)[0].strip("\n")
    written = (project_root / "reports" / "evaluation_summary.md").read_text(encoding="utf-8")
    assert block == readme_block(written).strip("\n")   # what docs-sync copies, byte for byte
    assert re.sub(r"^#(#+ )", r"\1", block, flags=re.MULTILINE) == written.strip("\n")   # the summary itself, only its headings one level down
    appendix = section(readme, "Resultados completos de la corrida")
    assert RESULTS_START in appendix and RESULTS_END in appendix   # the block sits in its appendix, linked from 5.1
    # AC25: the sealed summary is unfavourable, and the README says «no supera» outside the block too, in the two sections that tell it
    assert summary["evaluation_status"] == "sealed" and summary["post_seal"] is None
    assert [c["criterion_id"] for c in summary["criteria"] if c["passed"] is False] == FAILED
    assert [c["criterion_id"] for c in summary["criteria"] if c["passed"] is True] == PASSED
    for criterion in summary["criteria"]:
        assert criterion["verdict_es"] in block, criterion["criterion_id"]
    reading = readme.split("\n### 5.1 Evaluación frente a criterios de éxito\n", 1)[1].split("\n### 5.2 ")[0]
    for title, text in (("1. Resumen ejecutivo", section(readme, "1. Resumen ejecutivo")), ("5.1", reading)):
        assert "no supera" in text, title
    for criterion in FAILED + PASSED:
        assert re.search(rf"\b{criterion}\b", reading), criterion


def test_the_model_card_has_the_contents_of_the_plan_and_says_the_unfavourable_verdicts(model_card: str, summary: dict) -> None:
    assert re.findall(r"^## (.+)$", model_card, flags=re.MULTILINE) == MODEL_CARD_HEADINGS
    for criterion in summary["criteria"]:
        assert criterion["verdict_es"] in model_card, criterion["criterion_id"]   # every verdict as the summary writes it, «no supera» included
    for limit in (
        "2009 a 2011", "una sola tienda", "sin bajas comprobadas", "experimento de retención", "costos supuestos", "censurados", "una sola vez",
        "FastAPI", "log-odds", "PeakWorkingSetSize", "PeakPagefileUsage", "120 s",
    ):
        assert limit.lower() in model_card.lower(), limit
    assert re.search(r"suite rápida[^\n]*\d{2,3},\d+ s", model_card)   # AC41: measured and written down


def test_the_readme_says_what_is_pending_and_gives_the_attribution(readme: str) -> None:
    """RNF14 and RNF09: the independent evaluation and the ``.pbix`` are not done, and the README says so; the citation of the source is
    complete; no private address is published."""
    text = readme.lower()
    assert "evaluación independiente" in text and "todavía no" in text and ".pbix" in text
    tail = section(readme, "Fuente y licencia")
    for piece in ("Chen, D. (2012). Online Retail II [Dataset]. UCI Machine Learning Repository. https://doi.org/10.24432/C5CG6D", "CC BY 4.0",
                  "https://creativecommons.org/licenses/by/4.0/", "10.1016/j.ejor.2011.09.031"):
        assert piece in readme if piece.startswith("10.1016") else piece in tail, piece
    assert "@gmail" not in readme


def test_docs_sync_puts_the_summary_one_level_down_under_the_readme_heading(project_root: Path, tmp_path: Path, capsys) -> None:
    """The summary starts with its own ``## Resultados``; copied as it is, the README would get a second-level heading the plan does not list
    (AC40). ``docs-sync`` copies it with every heading one level down, and a second run changes nothing."""
    from churnrisk import cli

    (tmp_path / "config").mkdir()
    shutil.copyfile(project_root / "config" / "pipeline.toml", tmp_path / "config" / "pipeline.toml")
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "evaluation_summary.md").write_text("## Resultados\n\n| C01 | no supera |\n\n### Análisis posterior al sello\n\n- C05\n",
                                                                 encoding="utf-8")
    readme = tmp_path / "README.es.md"
    readme.write_text(f"# P\n\n## Los resultados\n\n{RESULTS_START}\nviejo\n{RESULTS_END}\n\n## Después\n", encoding="utf-8")
    config = str(tmp_path / "config" / "pipeline.toml")
    assert cli.main(["docs-sync", "--config", config]) == 0
    assert capsys.readouterr().out.splitlines() == ["README.es.md actualizado"]
    assert readme.read_text(encoding="utf-8") == (f"# P\n\n## Los resultados\n\n{RESULTS_START}\n### Resultados\n\n| C01 | no supera |\n\n"
                                                  f"#### Análisis posterior al sello\n\n- C05\n{RESULTS_END}\n\n## Después\n")
    assert cli.main(["docs-sync", "--config", config]) == 0
    assert capsys.readouterr().out.splitlines() == ["README.es.md ya estaba al día"]


# --- U31: the decisions, the stated test count, the memory figures, the tests the plan names, the dictionary, the runbook, the step by step,
# the advisories and the root rows (AC40) ------------------------------------------------------------------------------------------------

NAMED_TEST = re.compile(r"(tests/[\w/]+\.py)?::(test_\w+)")
# Every test the plan names exists: the one gap U31 left (``tests/integration/test_privacy.py::test_no_fixture_customer_id_in_any_versioned_byte_or_run_log``,
# D88) was written by the corrections of the independent evaluation (A11, D92). The test fails if any named test is missing.
KNOWN_MISSING: list[str] = []
DECISION_FIELDS = ("Contexto", "Opciones", "Decisión", "Motivo", "Afecta", "Quién", "Estado")   # AC40: every decision, D01 to the last
COUNTERS = ("PeakWorkingSetSize", "PeakPagefileUsage", "ru_maxrss", "conjunto de trabajo", "memoria comprometida")   # by API name or what it counts
MEMORY_FIGURE = re.compile(r"\d[\d.]*(?:,\d+)?\s?(?:MB|GB|MiB|GiB)\b")
MEMORY_WORDS = re.compile(r"pico|peak_|conjunto de trabajo|comprometid|memoria", re.IGNORECASE)   # a file or a folder's size is not one
SENTENCE_END = re.compile(r"(?<=\.)\s+")
LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)#\s]+)(?:#[^)]*)?\)")
IMAGE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)\)")
UNITS = [f"U{n:02d}" for n in range(1, 32)]
STATUSES = ("corregida", "dejada con evidencia", "abierta")
DOCS = ("data-dictionary.md", "runbook.md", "paso-a-paso.md", "review-advisories.md", "decisions.md")


def read(project_root: Path, name: str) -> str:
    return (project_root / "docs" / name).read_text(encoding="utf-8")


def root_rows(project_root: Path) -> str:
    """The section of project 04 in the root ``SITE-UPDATES.md``, up to the next project or the end."""
    text = root_document(project_root, "SITE-UPDATES.md")
    assert text.count("\n## 04 ") == 1, "SITE-UPDATES.md has no section for project 04"
    return re.split(r"\n## 0\d ", text.split("\n## 04 ")[1])[0]


def fast_suite_count(request: pytest.FixtureRequest, project_root: Path) -> int:
    """The number of tests of the fast suite. When this session is the fast suite itself (the test paths of the configuration, its default
    mark expression and no selection), its own collection; otherwise ``pytest --collect-only`` in another process, which costs a few seconds."""
    from tests.fixtures.suite_budget import is_full_default_selection

    if is_full_default_selection(request.config):
        return len(request.session.items)
    done = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"], cwd=project_root,
                          capture_output=True, text=True, timeout=300, encoding="utf-8")
    found = re.search(r"^(\d+)(?:/\d+)? tests? collected", done.stdout, flags=re.MULTILINE)
    assert found, done.stdout[-500:] + done.stderr[-500:]
    return int(found.group(1))


def named_in_plan(plan: str) -> list[tuple[str, str]]:
    """Every test the plan names, as (file, function): a bare ``::name`` belongs to the file named last before it."""
    found, last = [], None
    for match in NAMED_TEST.finditer(plan):
        last = match.group(1) or last
        assert last is not None, match.group(0)
        found.append((last, match.group(2)))
    return found


def test_every_test_named_in_the_plan_exists(project_root: Path) -> None:
    """AC40: every test plan sections 24 and 27 name (the RED of each unit and the named defect classes) is a test function of that file."""
    import ast

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
    assert sorted(set(missing)) == KNOWN_MISSING


def test_every_decision_has_seven_fields(project_root: Path) -> None:
    text = read(project_root, "decisions.md")
    entries = re.split(r"^## (?=D\d+ )", text, flags=re.MULTILINE)[1:]
    numbers = [int(re.match(r"D(\d+)", e).group(1)) for e in entries]
    assert numbers == list(range(1, len(numbers) + 1)) and len(numbers) >= 88   # no gap and no repeat, up to U31's own
    missing = [f"D{n:02d}: {field}" for n, entry in zip(numbers, entries, strict=True) for field in DECISION_FIELDS if f"- **{field}**: " not in entry]
    assert missing == []
    states = {f"D{n:02d}": re.search(r"^- \*\*Estado\*\*: (.+)$", e, flags=re.MULTILINE).group(1) for n, e in zip(numbers, entries, strict=True)}
    assert [d for d, s in states.items() if not re.match(r"(vigente|pendiente del dueño|reemplazada por D\d+)", s)] == []


def test_stated_test_count_matches_the_session_collection(request: pytest.FixtureRequest, project_root: Path, readme: str, model_card: str) -> None:
    """B3 of project 02 and B5 of project 03 (RNF14): the documents said one test count after a change had moved it. The count is that of the
    collection, in the README, the model card and the root rows; the seconds next to it are measured and written by hand (AC41)."""
    stated = f"{fast_suite_count(request, project_root):,}".replace(",", ".") + " pruebas"
    assert re.findall(r"\b\d{1,3}(?:\.\d{3})* pruebas\b", readme) == [stated]   # the README states one count: this one
    [suite] = re.findall(r"^- \*\*AC41, la suite rápida\*\*.*$", model_card, flags=re.MULTILINE)
    assert f"para {stated}" in suite
    assert stated in root_rows(project_root)


def test_every_memory_figure_names_its_counter(project_root: Path, readme: str, model_card: str) -> None:
    """RNF03 and D39 (lesson A3 of project 02): a memory figure without its counter cannot be compared with another. Every sentence of the
    documents that gives a memory figure in MB or GB names the counter, by its API name or by what it counts."""
    absent = [f"docs/{name}" for name in DOCS if not (project_root / "docs" / name).is_file()]
    assert absent == [], "every document of AC40 exists"
    documents = {"README.md": readme, "docs/model-card.md": model_card, "SITE-UPDATES.md (04)": root_rows(project_root)}
    documents |= {f"docs/{name}": read(project_root, name) for name in DOCS}
    figures, unnamed = 0, []
    for name, text in documents.items():
        for line in text.splitlines():
            for sentence in SENTENCE_END.split(line):
                if MEMORY_FIGURE.search(sentence) and MEMORY_WORDS.search(sentence):
                    figures += 1
                    if not any(counter in sentence for counter in COUNTERS):
                        unnamed.append(f"{name}: {sentence.strip()[:160]}")
    assert unnamed == []
    assert figures >= 10   # the documents do state memory figures: the check is not vacuous


def test_every_criterion_row_of_the_summary_and_of_the_readme_block_has_the_cells_of_its_header(project_root: Path, readme: str) -> None:
    """A4 of the independent evaluation (``U31/resumen-C07-barras``): the versioned summary and the README block, row by row, have as many cells
    as the header of their table; an unescaped pipe inside a cell (C07's «|sesgo|») would split its row."""
    def cells(line: str) -> int:
        return len(re.findall(r"(?<!\\)\|", line)) - 1

    block = readme.split(RESULTS_START)[1].split(RESULTS_END)[0]
    for name, text in (("reports/evaluation_summary.md", (project_root / "reports" / "evaluation_summary.md").read_text(encoding="utf-8")), ("README.md", block)):
        lines = text.splitlines()
        header = next(line for line in lines if line.startswith("| Criterio |"))
        rows = [line for line in lines if re.match(r"\| C\d\d ", line)]
        assert len(rows) == 10 and cells(header) == 5, name
        assert [(row.split(" ")[1], cells(row)) for row in rows if cells(row) != cells(header)] == [], name


def test_results_block_matches_summary(project_root: Path, readme: str, summary: dict) -> None:
    """Plan 24.2, the class «documentación sin sincronizar»: the block is the summary of the sealed run, its run and its date included."""
    from churnrisk.docs_sync import readme_block

    block = readme.split(RESULTS_START)[1].split(RESULTS_END)[0].strip("\n")
    assert block == readme_block((project_root / "reports" / "evaluation_summary.md").read_text(encoding="utf-8")).strip("\n")
    assert f"Corrida {summary['run_key']} del {summary['as_of']}." in block and "Estado: sealed." in block


def test_the_dictionary_covers_the_source_and_the_features_and_its_tables_are_the_generated_ones(project_root: Path) -> None:
    import pyarrow.parquet as pq

    from churnrisk.dashboard.semantic_model import MODEL, arrow_schema
    from churnrisk.docs_sync import COLUMNS_END, COLUMNS_START, render_dictionary_tables
    from churnrisk.schema import FEATURE_COLUMNS, SOURCE_COLUMNS, WORKBOOK_COLUMNS

    text = read(project_root, "data-dictionary.md")
    source = text.split("\n## Archivo de origen\n")[1].split("\n## ")[0]
    rows = re.findall(r"^\| `([^`]+)` \| `([^`]+)` \| ([^|]+?) \| ", source, flags=re.MULTILINE)
    assert [(w, s) for w, s, _use in rows] == list(zip(WORKBOOK_COLUMNS, SOURCE_COLUMNS, strict=True))   # the 8 columns, in order
    assert all(use.strip() for _w, _s, use in rows)
    features = text.split("\n## Variables\n")[1].split("\n## ")[0]
    documented = re.findall(r"^\| `([a-z_0-9]+)` \| [^|]+ \| ([^|]+) \| ", features, flags=re.MULTILINE)
    numeric = [c for c in FEATURE_COLUMNS if c != "country_group"]
    assert [name for name, _unit in documented] == numeric and all(unit.strip() for _name, unit in documented)   # the 16, each with its unit
    assert text.count(COLUMNS_START) == 1 and text.count(COLUMNS_END) == 1
    block = text.split(COLUMNS_START)[1].split(COLUMNS_END)[0]
    assert block.strip() == render_dictionary_tables(MODEL).strip()   # what docs-sync writes
    for table in MODEL.tables:
        section = block.split(f"### `{table.name}`\n")[1].split("\n### ")[0]
        listed = re.findall(r"^\| `([a-z_0-9]+)` \| [^|]+ \| ([^|]+) \| ", section, flags=re.MULTILINE)
        assert tuple(name for name, _unit in listed) == table.column_names and all(unit.strip() for _name, unit in listed), table.name
        if table.private:   # the private fact is in the dictionary too, marked as not versioned; its file is never in the repository
            assert "no se versiona" in section and arrow_schema(table).names == list(table.column_names), table.name
        else:
            assert pq.read_schema(project_root / "outputs" / "powerbi" / f"{table.name}.parquet").names == list(table.column_names), table.name


def _sync_project(project_root: Path, tmp_path: Path, dictionary: bool) -> str:
    (tmp_path / "config").mkdir()
    shutil.copyfile(project_root / "config" / "pipeline.toml", tmp_path / "config" / "pipeline.toml")
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "evaluation_summary.md").write_text("## Resultados\n\n| C01 | no supera |\n", encoding="utf-8")
    (tmp_path / "README.es.md").write_text(f"# P\n\n{RESULTS_START}\nviejo\n{RESULTS_END}\n", encoding="utf-8")
    if dictionary:   # next to the figures folder of the configuration (docs/figures), as docs/ is in the project
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "data-dictionary.md").write_text("# D\n\n<!-- columns:start -->\nviejo\n<!-- columns:end -->\n\nal final\n",
                                                              encoding="utf-8")
    return str(tmp_path / "config" / "pipeline.toml")


def test_docs_sync_writes_the_dictionary_tables_and_a_second_run_changes_nothing(project_root: Path, tmp_path: Path, capsys) -> None:
    from churnrisk import cli
    from churnrisk.dashboard.semantic_model import MODEL

    config = _sync_project(project_root, tmp_path, dictionary=True)
    assert cli.main(["docs-sync", "--config", config]) == 0
    assert capsys.readouterr().out.splitlines() == ["README.es.md actualizado", "data-dictionary.md actualizado"]
    from churnrisk.docs_sync import render_dictionary_tables

    text = (tmp_path / "docs" / "data-dictionary.md").read_text(encoding="utf-8")
    assert render_dictionary_tables(MODEL).strip() in text and "viejo" not in text and text.endswith("al final\n")
    assert "| C01 | no supera |" in (tmp_path / "README.es.md").read_text(encoding="utf-8")
    assert cli.main(["docs-sync", "--config", config]) == 0
    assert capsys.readouterr().out.splitlines() == ["README.es.md ya estaba al día", "data-dictionary.md ya estaba al día"]


def test_docs_sync_without_a_dictionary_still_syncs_only_the_readme(project_root: Path, tmp_path: Path, capsys) -> None:
    """The command as it was before U31: with no dictionary next to the figures folder, it writes the README block and says only that."""
    from churnrisk import cli

    config = _sync_project(project_root, tmp_path, dictionary=False)
    assert cli.main(["docs-sync", "--config", config]) == 0
    assert capsys.readouterr().out.splitlines() == ["README.es.md actualizado"]
    assert not (tmp_path / "docs").exists()


def test_the_runbook_has_r1_to_r14_and_every_reference_of_the_code_points_to_one(project_root: Path) -> None:
    text = read(project_root, "runbook.md")
    entries = re.split(r"^## (?=R\d+ )", text, flags=re.MULTILINE)[1:]
    assert [entry.split()[0] for entry in entries] == [f"R{n}" for n in range(1, 15)]   # plan, section 25
    for entry in entries:
        assert "**Síntoma.**" in entry and "**Qué hacer.**" in entry, entry.splitlines()[0]
    sources = [*sorted((project_root / "src" / "churnrisk").rglob("*.py")), *sorted((project_root / "airflow").rglob("*.py")),
               project_root / "airflow" / "docker-compose.yaml"]
    cited = {int(n) for path in sources for n in re.findall(r"runbook(?:\.md)?,? R(\d+)", path.read_text(encoding="utf-8"))}
    assert cited and cited <= set(range(1, 15)), cited


def test_the_step_by_step_names_every_unit_and_cites_commits_that_exist(project_root: Path) -> None:
    text = read(project_root, "paso-a-paso.md")
    assert [unit for unit in UNITS if not re.search(rf"\b{unit}\b", text)] == []
    hashes = sorted(set(re.findall(r"`([0-9a-f]{7})`", text)))
    assert len(hashes) >= 50
    if shutil.which("git") is None or not (project_root.parent / ".git").exists():
        pytest.skip("there is no Git history to check the commits against")
    done = subprocess.run(["git", "cat-file", "--batch-check"], cwd=project_root, input="".join(f"{h}^{{commit}}\n" for h in hashes),
                          capture_output=True, text=True)
    assert [line for line in done.stdout.splitlines() if line.endswith("missing")] == []


def test_relative_links_and_images_point_to_files_that_exist(project_root: Path) -> None:
    broken = []
    for document in [project_root / "README.md", project_root / "README.es.md", *sorted((project_root / "docs").glob("*.md"))]:
        text = document.read_text(encoding="utf-8")
        for target in [*LINK.findall(text), *IMAGE.findall(text)]:
            if not re.match(r"^(https?:|mailto:)", target) and not (document.parent / target).resolve().exists():
                broken.append(f"{document.name}: {target}")
    assert broken == []


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
    """AC40 and B5 of project 03's evaluation: every advisory of every native review has its status in ``docs/review-advisories.md`` (fixed,
    with its commit; left with evidence; or open), and the advisories the README calls open are the ones that file calls open."""
    text = read(project_root, "review-advisories.md")
    found = advisories(text)
    assert len(found) >= 150 and [key for key, status in found.items() if status not in STATUSES] == []
    fixed = [block for block in re.split(r"^(?=- \*\*)", text, flags=re.MULTILINE) if "Estado: **corregida**" in block]
    assert fixed and all(re.search(r"`[0-9a-f]{7}`", block.split("Estado: **corregida**")[1].splitlines()[0]) for block in fixed)
    opened = sorted(f"{key}/{ident}" for (key, ident), status in found.items() if status == "abierta")
    [stated] = re.findall(r"^Advertencias abiertas: (.+)$", readme, flags=re.MULTILINE)
    assert sorted(re.findall(r"`([^`]+)`", stated)) == opened, stated


def test_the_root_rows_of_project_04_carry_the_real_figures(project_root: Path) -> None:
    rows = root_rows(project_root)
    table = [line for line in rows.split("### ")[0].splitlines() if re.match(r"^\| \d+ \|", line)]
    assert [int(line.split("|")[1]) for line in table] == list(range(1, 17))   # plan, section 30: the sixteen rows
    for figure in ("0,745", "0,746", "0,749", "0,752", "209,7", "238,9", "3.935", "34,4 %", "43,2 %", "31,7 %", "0,55", "312,2 s", "1.868,5 MB",
                   "3.709,2 MB", "1.044.848"):
        assert figure in rows, figure
    assert rows.count("no supera") >= 2 and "C06" in rows and "C08" in rows and "pendiente" in rows and "@gmail" not in rows
    expansion = root_document(project_root, "LANDING-EXPANSION.md")
    marked = {line.split("|")[1].strip() for line in expansion.splitlines() if line.startswith("| ") and "04 Clientes que se van" in line}
    assert marked == {"SciPy", "NumPy", "SQLite", "Apache Parquet con pyarrow", "matplotlib", "pytest", "PostgreSQL", "openpyxl", "lifetimes",
                      "SHAP"}   # D37: the ones this project uses, and SHAP, its one new row


def check_the_english_readme(project_root: Path, readme: str) -> None:
    """README.md is the page of the project in English; README.es.md is the full one, which ``docs-sync`` and the other tests check."""
    english = (project_root / "README.md").read_text(encoding="utf-8")
    assert "**English** · [Español](README.es.md)" in english and "[English](README.md) · **Español**" in readme
    assert english.count("2 of 9 success criteria met") == 2 and "undefined" not in english and "@gmail" not in english
    for target in ("docs/screenshots/dashboard.png", "docs/screenshots/demo.png", "docs/model-card.md", "docs/evaluation.md"):
        assert f"]({target})" in english and (project_root / target).is_file(), target
