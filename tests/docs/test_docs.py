"""The documentation is checked like code (AC25, AC40; RF24, RF29; RNF09, RNF14; plan, sections 25 and 26).

U30: the README has the headings of plan section 25 in their order and its results block is the sealed summary that ``docs-sync`` copies,
never a block written by hand; the README says the unfavourable verdicts («no supera») in «El problema», «La solución» and «Los resultados»;
the model card has the contents the plan lists, every verdict as the summary writes it, the memory counters and the suite's limit. These
tests read the versioned Markdown and the versioned reports (``reports/`` holds the outputs of U29) and run nothing, except the ``docs-sync``
tests, which work on a copy of the configuration in a temporary folder.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from churnrisk.reporting import RESULTS_END, RESULTS_START

README_TITLE = "# Clientes que están por irse, antes de que se vayan"
README_HEADINGS = [   # plan, section 25, in this order (AC40)
    "El problema", "La solución", "Los resultados", "En qué consiste", "Los datos", "Los algoritmos", "El producto", "La documentación",
    "Con IA, de punta a punta", "Para qué sirve", "Cómo correrlo de punta a punta", "Paso a paso", "Fuente y licencia",
]
MODEL_CARD_HEADINGS = [   # what plan section 25 lists for the model card, in this order
    "Uso previsto y no previsto", "Datos", "La definición de baja y su ruido", "La población y los invitados", "Cortes y estacionalidad",
    "Variables", "Partición", "Métodos", "Calibración", "SHAP y qué explica", "Umbral y costos supuestos", "Criterios y resultados",
    "Sensibilidades", "Limitaciones", "Tiempos y memoria", "La suite rápida",
]
FAILED = ["C01", "C02", "C03", "C04", "C05", "C07", "C09"]   # D85: what the sealed run says
PASSED = ["C06", "C08"]


@pytest.fixture(scope="module")
def readme(project_root: Path) -> str:
    return (project_root / "README.md").read_text(encoding="utf-8")


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
    assert readme.startswith(README_TITLE + "\n")
    assert re.findall(r"^## (.+)$", readme, flags=re.MULTILINE) == README_HEADINGS   # the block's own headings sit one level down
    assert readme.count(RESULTS_START) == 1 and readme.count(RESULTS_END) == 1
    from churnrisk.docs_sync import readme_block   # the copy docs-sync makes
    block = readme.split(RESULTS_START)[1].split(RESULTS_END)[0].strip("\n")
    written = (project_root / "reports" / "evaluation_summary.md").read_text(encoding="utf-8")
    assert block == readme_block(written).strip("\n")   # what docs-sync copies, byte for byte
    assert re.sub(r"^#(#+ )", r"\1", block, flags=re.MULTILINE) == written.strip("\n")   # the summary itself, only its headings one level down
    assert readme.index(RESULTS_START) > readme.index("\n## Los resultados\n") and readme.index(RESULTS_END) < readme.index("\n## En qué consiste\n")
    # AC25: the sealed summary is unfavourable, and the README says «no supera» outside the block too, in the three sections that tell it
    assert summary["evaluation_status"] == "sealed" and summary["post_seal"] is None
    assert [c["criterion_id"] for c in summary["criteria"] if c["passed"] is False] == FAILED
    assert [c["criterion_id"] for c in summary["criteria"] if c["passed"] is True] == PASSED
    for criterion in summary["criteria"]:
        assert criterion["verdict_es"] in block, criterion["criterion_id"]
    reading = readme.split(RESULTS_END)[1].split("\n## En qué consiste\n")[0]
    for title, text in (("El problema", section(readme, "El problema")), ("La solución", section(readme, "La solución")), ("Los resultados", reading)):
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
    readme = tmp_path / "README.md"
    readme.write_text(f"# P\n\n## Los resultados\n\n{RESULTS_START}\nviejo\n{RESULTS_END}\n\n## Después\n", encoding="utf-8")
    config = str(tmp_path / "config" / "pipeline.toml")
    assert cli.main(["docs-sync", "--config", config]) == 0
    assert capsys.readouterr().out.splitlines() == ["README.md actualizado"]
    assert readme.read_text(encoding="utf-8") == (f"# P\n\n## Los resultados\n\n{RESULTS_START}\n### Resultados\n\n| C01 | no supera |\n\n"
                                                  f"#### Análisis posterior al sello\n\n- C05\n{RESULTS_END}\n\n## Después\n")
    assert cli.main(["docs-sync", "--config", config]) == 0
    assert capsys.readouterr().out.splitlines() == ["README.md ya estaba al día"]
