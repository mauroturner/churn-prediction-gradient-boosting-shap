"""The summary after the seal (U17, AC22; RF24; D20; project 03's B3, D88): a warehouse that does not have the sealed rows of the test (a rebuild
from scratch, here with other costs) takes the criteria and the test figures from the seal, each rebuilt and compared with its entry, and shows
its own analysis below as post-seal; a seal entry that does not rebuild is refused."""

from __future__ import annotations

import dataclasses
import json

import pytest

from churnrisk.registry import SealError, read_seal
from churnrisk.reporting import build_summary, evaluate, summary_markdown
from churnrisk.warehouse import connect
from tests.fixtures.history import quick_config, without_sealed_rows

def sealed_criteria(history) -> list[dict]:
    return [{"id": e["id"], **{k: e[k] for k in ("value", "baseline_value", "ci_low", "ci_high", "passed", "verdict_es")}}
            for e in read_seal(history.cfg.paths.seal)["test"]["criteria"]]


# --- the RED of U17 ------------------------------------------------------------------------------------------------------


def test_a_warehouse_without_sealed_rows_takes_the_sealed_result_from_the_seal(quick_history, tmp_path):
    other = dataclasses.replace(quick_history.cfg.costs, offer_cost=7.0)
    one_variant = dataclasses.replace(quick_history.cfg.sensitivity, variants=("n60",))     # post-seal anyway: one variant is enough here
    cfg = without_sealed_rows(quick_history, tmp_path / "rebuilt", costs=other, sensitivity=one_variant)
    last = quick_history.runs[-1].spec
    conn = connect(cfg.paths.warehouse)
    try:
        outcome = evaluate(conn, cfg, run_key="r9", as_of=last.as_of, source_sha256=quick_history.view.source_sha256)
        summary = build_summary(conn, cfg, run_key="r9", as_of=last.as_of, source_sha256=quick_history.view.source_sha256)
    finally:
        conn.close()
    assert (outcome["seal_state"], outcome["test"]) == ("post_seal", "post_seal")
    assert cfg.paths.seal.read_bytes() == quick_history.cfg.paths.seal.read_bytes(), "the post-seal evaluation leaves the seal as it was"
    assert (summary["evaluation_status"], summary["sealed_from"]) == ("sealed", "seal")
    got = [{"id": c["criterion_id"], **{k: c[k] for k in ("value", "baseline_value", "ci_low", "ci_high", "passed", "verdict_es")}} for c in summary["criteria"]]
    assert got == sealed_criteria(quick_history), "each sealed criterion, rebuilt from the seal, is its entry"
    assert summary["test"] == read_seal(cfg.paths.seal)["test"]["metrics"]
    post = summary["post_seal"]
    assert post["costs"]["offer_cost"] == 7.0 and [c["criterion_id"] for c in post["criteria"]] == [f"C{i:02d}" for i in range(1, 11)]
    assert summary["costs"]["offer_cost"] == quick_history.cfg.costs.offer_cost, "the sealed figures carry the sealed costs (A2)"
    assert post["test"]["model"]["threshold"] == outcome_threshold(cfg)
    text = summary_markdown(summary)
    assert "Criterios fijados antes de construir, evaluados una vez sobre la prueba (tomados del sello)." in text
    assert "### Análisis posterior al sello" in text and "costo de la oferta 7,00" in text
    assert text.index("| C01") < text.index("### Análisis posterior al sello"), "the run's own analysis goes below what was sealed"


def test_a_post_seal_summary_puts_the_sealed_costs_next_to_the_sealed_figures(quick_history, tmp_path):
    """A2 of the independent evaluation (``U17/R3-post-seal-costs-staleness``; D92): a rebuild with another offer cost takes the criteria and
    the test figures from the seal, and its top-level ``costs`` were the run's: 7 next to figures sealed with 5. The top level now carries the
    sealed costs, and only the post-seal block names the run's own."""
    other = dataclasses.replace(quick_history.cfg.costs, offer_cost=7.0)
    cfg = without_sealed_rows(quick_history, tmp_path / "rebuilt", costs=other)
    conn = connect(cfg.paths.warehouse)
    try:
        summary = build_summary(conn, cfg, run_key="r9", as_of=quick_history.runs[-1].spec.as_of, source_sha256=quick_history.view.source_sha256)
    finally:
        conn.close()
    sealed = read_seal(cfg.paths.seal)["launch"]["sealed_config"]["costs"]
    assert (summary["evaluation_status"], summary["sealed_from"]) == ("sealed", "seal")
    assert summary["costs"] == {k: sealed[k] for k in ("offer_cost", "rescue_rate", "retained_value")}
    assert summary["costs"]["offer_cost"] == quick_history.cfg.costs.offer_cost != 7.0


def outcome_threshold(cfg) -> float:
    conn = connect(cfg.paths.warehouse)
    try:
        return conn.execute("SELECT threshold FROM model_registry").fetchone()[0]
    finally:
        conn.close()


def test_a_seal_entry_that_does_not_rebuild_is_refused(quick_history, tmp_path):
    """A seal whose criterion says another value than its own figures give (here C01, edited by hand) is never published: SealError."""
    cfg = without_sealed_rows(quick_history, tmp_path / "edited")
    document = json.loads(cfg.paths.seal.read_text(encoding="utf-8"))
    entry = next(e for e in document["test"]["criteria"] if e["id"] == "C01")
    entry["value"] = round(entry["value"] + 0.01, 6)
    cfg.paths.seal.write_text(json.dumps(document), encoding="utf-8")
    conn = connect(cfg.paths.warehouse)
    try:
        with pytest.raises(SealError, match="el criterio C01 del sello no se reconstruye desde sus cifras"):
            build_summary(conn, cfg, run_key="r9", as_of=quick_history.runs[-1].spec.as_of, source_sha256=quick_history.view.source_sha256)
    finally:
        conn.close()
