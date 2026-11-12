"""The summary of the evaluation and the block of the README (U17, AC22, AC25; RF24; D20)."""

from __future__ import annotations

import dataclasses
import json
import re
import sqlite3

import pytest

from churnrisk.evaluation import _criteria_of
from churnrisk.registry import sealed_document, sealed_view
from churnrisk.reporting import RESULTS_END, RESULTS_START, build_summary, summary_markdown, sync_block, write_summary
from tests.fixtures.hand_cases import losing_metrics

SHA = "a" * 64


def sealed_summary(cfg, metrics: dict) -> dict:
    document = sealed_document(sealed_view(cfg, SHA))
    per_cut = [{"cut": "2011-08-01", "rows": 900, "churn_rate": 0.3, "auc_model": 0.77, "diff_b2_rfm": -0.01, "diff_b_star": -0.01}]
    criteria = _criteria_of(metrics, per_cut, document["costs"], document["criteria"])
    return {"evaluation_status": "sealed", "run_key": "r5", "as_of": "2011-11-30", "pending_reason_es": None, "post_seal": None,
            "criteria": [{"criterion_id": c.criterion_id, "name_es": c.name_es, "value": c.value, "baseline_value": c.baseline_value,
                          "ci_low": c.ci_low, "ci_high": c.ci_high, "threshold_es": c.threshold_es, "passed": c.passed,
                          "seen_by_research": c.seen_by_research, "seen_by_planner": c.seen_by_planner, "verdict_es": c.verdict_es} for c in criteria]}


# --- the RED of U17 ------------------------------------------------------------------------------------------------------


def test_unfavourable_summary_says_no_supera(cfg, tmp_path):
    """A model that loses to RFM: the summary says «no supera» with its numbers, criterion by criterion, and says which criteria it meets."""
    summary = sealed_summary(cfg, losing_metrics())
    text = summary_markdown(summary)
    assert "El modelo no supera a RFM en AUC: 0,769 frente a 0,784." in text
    assert "El modelo no supera a RFM fuera del ruido: la diferencia de AUC es −0,01, con un intervalo del 95 % de −0,03 a 0,01." in text
    rows = {line.split(" ")[1]: line for line in text.splitlines() if line[:3] == "| C" and line[3:5].isdigit()}
    assert sorted(rows) == [f"C{i:02d}" for i in range(1, 11)]
    assert "| no |" in rows["C01"] and "| sí |" in rows["C06"] and "| informativo |" in rows["C10"]
    assert "supera a RFM en AUC" not in text.replace("no supera a RFM en AUC", "")
    json_path, md_path = write_summary(summary, tmp_path / "reports")
    assert json.loads(json_path.read_text(encoding="utf-8")) == summary and md_path.read_text(encoding="utf-8") == text


def _cells(line: str) -> int:
    """The cells of a Markdown table row: its pipes that are not escaped, minus one."""
    return len(re.findall(r"(?<!\\)\|", line)) - 1


def criterion_rows(text: str) -> list[str]:
    return [line for line in text.splitlines() if re.match(r"\| C\d\d ", line)]


def test_every_criterion_row_of_the_summary_has_the_cells_of_its_header(cfg):
    """A4 of the independent evaluation (``U31/resumen-C07-barras``): C07's threshold says «|sesgo|», and its unescaped pipes split the row into
    more cells than the header has, in the summary and in the README block copied from it. Every pipe inside a cell is escaped, so every
    criterion row has the five cells of the header; the data keep the text as it is."""
    from churnrisk.docs_sync import readme_block

    summary = sealed_summary(cfg, losing_metrics())
    assert "|sesgo|" in next(c["threshold_es"] for c in summary["criteria"] if c["criterion_id"] == "C07")
    for text in (summary_markdown(summary), readme_block(summary_markdown(summary))):
        header = next(line for line in text.splitlines() if line.startswith("| Criterio |"))
        rows = criterion_rows(text)
        assert [r.split(" ")[1] for r in rows] == [f"C{i:02d}" for i in range(1, 11)]
        assert _cells(header) == 5 and [_cells(r) for r in rows] == [5] * 10, [r for r in rows if _cells(r) != 5]
        assert r"\|sesgo\|" in next(r for r in rows if r.startswith("| C07 "))


def test_the_c09_verdict_says_at_how_many_break_even_points_the_model_keeps_the_benefit_and_at_how_many_it_does_not(cfg):
    """A5: «no deja al menos el beneficio … en 9 de los 17» reads as 9 failures, and 9 is where the model keeps the benefit of B*. The row of the
    summary adds, from the same sealed numbers, where it keeps it and where it does not; the sealed verdict, its number and «no» stay."""
    metrics = losing_metrics()
    metrics["cost_sensitivity"] = {k: (100.0 if k.endswith(".b_star") or i < 9 * 2 else 99.0) for i, k in enumerate(metrics["cost_sensitivity"])}
    summary = sealed_summary(cfg, metrics)
    c09 = next(c for c in summary["criteria"] if c["criterion_id"] == "C09")
    assert (c09["value"], c09["baseline_value"], c09["passed"]) == (9.0, 17.0, False)
    sealed = "El modelo no deja al menos el beneficio de la base más fuerte en cada punto de equilibrio: en 9 de los 17 de 0,10 a 0,90."
    assert c09["verdict_es"] == sealed, "the verdict that is sealed does not change"
    rows = criterion_rows(summary_markdown(summary))
    assert [r.split(" ")[1] for r in rows if "Es decir" in r] == ["C09"], "only C09 counts its points; every other verdict is the sealed one"
    [row] = [r for r in rows if r.startswith("| C09 ")]
    assert row.endswith(f"| 9,000 | no | {sealed} Es decir: lo deja en 9 de los 17 puntos de equilibrio y no lo deja en 8. |")
    one = next(r for r in criterion_rows(summary_markdown(sealed_summary(cfg, losing_metrics()))) if r.startswith("| C09 "))
    assert "Es decir: lo deja en 1 de los 17 puntos de equilibrio y no lo deja en 16." in one


def test_the_pending_summary_says_why_the_test_is_not_evaluated(quick_history, tmp_path):
    """Before the run of 2011-11 the test is pending: the summary says with which delivery it is evaluated and why (its windows have not
    closed), every criterion is pending with that reason, and the figures it shows are those of V2, labelled as validation (project 03's
    R3-pending-why-branch-untested)."""
    launch = quick_history.runs[0]
    seal = tmp_path / "launch_seal.json"                 # the seal as the launch left it: its launch part only
    seal.write_bytes(launch.seal)
    cfg = dataclasses.replace(quick_history.cfg, paths=dataclasses.replace(quick_history.cfg.paths, seal=seal))
    conn = sqlite3.connect(launch.warehouse)
    try:
        summary = build_summary(conn, cfg, run_key="r1", as_of=launch.spec.as_of, source_sha256=quick_history.view.source_sha256)
    finally:
        conn.close()
    assert summary["evaluation_status"] == "pending" and summary["test"] is None and "sealed_from" not in summary
    reason = summary["pending_reason_es"]
    assert reason.startswith("La prueba se evalúa con la entrega de 2011-11: las ventanas de sus cortes cierran el 2011-11-29")
    assert all(c["passed"] is None and c["value"] is None and c["verdict_es"] == "Pendiente: " + reason for c in summary["criteria"])
    assert [c["criterion_id"] for c in summary["criteria"]] == [f"C{i:02d}" for i in range(1, 11)]
    assert set(summary["validation_v2"]) >= {"model", "b2_rfm", "b_star"} and summary["validation_v2"]["model"]["auc"] > 0.5
    text = summary_markdown(summary)
    assert text.startswith("## Resultados\n\n**Prueba pendiente.** La prueba se evalúa con la entrega de 2011-11")
    assert "| Método (validación V2) | AUC |" in text and "| C01" not in text


# --- the block of the README -------------------------------------------------------------------------------------------------


def test_the_results_block_is_replaced_between_its_markers_only(tmp_path):
    path = tmp_path / "README.md"
    path.write_text(f"# Título\n\nantes\n{RESULTS_START}\nviejo\n{RESULTS_END}\ndespués\n", encoding="utf-8")
    assert sync_block(path, RESULTS_START, RESULTS_END, "## Resultados\n\nnuevo\n") is True
    assert path.read_text(encoding="utf-8") == f"# Título\n\nantes\n{RESULTS_START}\n## Resultados\n\nnuevo\n{RESULTS_END}\ndespués\n"
    assert sync_block(path, RESULTS_START, RESULTS_END, "## Resultados\n\nnuevo") is False, "the same content changes nothing"
    for broken in (f"{RESULTS_END}\n{RESULTS_START}\n", f"{RESULTS_START}\n", f"{RESULTS_START}{RESULTS_START}{RESULTS_END}"):
        path.write_text(broken, encoding="utf-8")
        with pytest.raises(ValueError, match="debe tener una vez"):
            sync_block(path, RESULTS_START, RESULTS_END, "x")
        assert path.read_text(encoding="utf-8") == broken
