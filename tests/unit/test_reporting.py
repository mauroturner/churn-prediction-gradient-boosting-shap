"""The summary of the evaluation and the block of the README (U17, AC22, AC25; RF24; D20)."""

from __future__ import annotations

import dataclasses
import json
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
