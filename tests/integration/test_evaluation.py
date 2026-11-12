"""The evaluation in the quick history (U17, AC21, AC25; RF23; D19): V2 at the launch, the test once, in the run whose date closes its
windows, written to the seal and to sealed rows that are never rewritten; a repetition with the sealed configuration reproduces it."""

from __future__ import annotations

import json
import sqlite3

from churnrisk.registry import read_seal
from churnrisk.reporting import evaluate, test_delivery
from churnrisk.warehouse import connect
from tests.fixtures.history import without_sealed_rows


def test_the_test_is_evaluated_once_by_the_run_that_closes_its_windows_and_sealed(quick_history):
    runs = {r.spec.delivery_id: r for r in quick_history.runs}
    assert test_delivery(quick_history.cfg) == "M2011-11"
    assert [(r.spec.delivery_id, r.evaluation["valid_v2"], r.evaluation["test"]) for r in quick_history.runs] == [
        ("L2011-07", "evaluated", "pending"), ("M2011-08", "kept", "pending"), ("M2011-09", "kept", "pending"), ("M2011-10", "kept", "pending"),
        ("M2011-11", "kept", "written"), ("C2011-12", "kept", "sealed_before")]
    assert "test" not in json.loads(runs["M2011-10"].seal) and "test" in json.loads(runs["M2011-11"].seal)
    assert runs["C2011-12"].seal == runs["M2011-11"].seal, "nothing rewrites the seal after the test is sealed"
    seal = read_seal(quick_history.cfg.paths.seal)
    assert (seal["test"]["run_key"], seal["test"]["as_of"], seal["test"]["config_sha256"]) == ("r5", "2011-11-30", seal["launch"]["config_sha256"])
    conn = sqlite3.connect(quick_history.warehouse)
    try:
        stored = {row[0]: row[1:] for row in conn.execute("SELECT criterion_id, value, passed, verdict_es FROM eval_criteria WHERE seal_state = 'sealed'")}
        scopes = {row for row in conn.execute("SELECT DISTINCT scope, seal_state FROM eval_metrics")}
        leak = dict(conn.execute("SELECT variable, auc_valid_v2 FROM eval_leakage").fetchall())
        rows = conn.execute("SELECT value FROM eval_metrics WHERE scope = 'test' AND method = 'model' AND metric = 'rows'").fetchone()[0]
    finally:
        conn.close()
    assert {e["id"]: (e["value"], None if e["passed"] is None else int(e["passed"]), e["verdict_es"]) for e in seal["test"]["criteria"]} == stored
    assert scopes == {("valid_v2", "sealed"), ("test", "sealed")}
    assert rows == len([s for s in quick_history.runs[-1].scores if s[0] in ("2011-08-01", "2011-09-01")]), "the test rows are the scored test cuts"
    assert leak["f1_days_to_next_purchase"] >= 0.95 > leak["f1"], "the control that looks at the window gives the label away"


def test_a_repetition_with_the_sealed_configuration_reproduces_the_sealed_test(quick_history, tmp_path):
    """A rebuild with the sealed configuration and no sealed rows evaluates the test again: write_test_seal finds the same values to 6
    decimals and leaves the seal byte for byte; the warehouse gets its sealed rows back."""
    cfg = without_sealed_rows(quick_history, tmp_path / "again")
    conn = connect(cfg.paths.warehouse)
    try:
        outcome = evaluate(conn, cfg, run_key="r9", as_of=quick_history.runs[-1].spec.as_of, source_sha256=quick_history.view.source_sha256)
        restored = conn.execute("SELECT COUNT(*) FROM eval_criteria WHERE seal_state = 'sealed'").fetchone()[0]
        again = evaluate(conn, cfg, run_key="r10", as_of=quick_history.runs[-1].spec.as_of, source_sha256=quick_history.view.source_sha256)
    finally:
        conn.close()
    assert (outcome["seal_state"], outcome["test"], restored) == ("sealed", "unchanged", 10)
    assert again["test"] == "sealed_before", "the sealed rows are written once"
    assert cfg.paths.seal.read_bytes() == quick_history.cfg.paths.seal.read_bytes()


# --- review coverage (L50: R3-block-data-error-paths, R3-evaluate-no-seal-error) -----------------------------------------------------


def test_a_block_is_refused_when_its_scope_is_unknown_its_windows_are_open_or_a_test_row_has_no_score(quick_history, cut_history):
    import pytest

    from churnrisk.evaluation import EvaluationError, block_data
    from churnrisk.launch import load_registered

    conn = connect(quick_history.warehouse)
    try:
        bundle = load_registered(conn, quick_history.cfg).bundle
        with pytest.raises(EvaluationError, match="alcance desconocido: 'train'"):
            block_data(conn, "train", bundle, quick_history.view)
    finally:
        conn.close()
    launch = connect(cut_history[0].path)                  # the launch's warehouse: the test windows have not closed
    try:
        with pytest.raises(EvaluationError, match="el bloque test no tiene filas con etiqueta"):
            block_data(launch, "test", bundle, quick_history.view)
    finally:
        launch.close()
    unscored = connect(cut_history[-1].path)               # the loads and cuts of every run, with the test labels but no score
    try:
        with pytest.raises(EvaluationError, match="filas de la prueba no tienen puntaje"):
            block_data(unscored, "test", bundle, quick_history.view)
    finally:
        unscored.close()


def test_evaluate_without_a_seal_is_refused_before_it_writes(quick_history, tmp_path):
    import hashlib
    import shutil

    import pytest

    from churnrisk.registry import SealError
    from tests.fixtures.history import quick_config

    cfg = quick_config(tmp_path / "no_seal")
    cfg.paths.warehouse.parent.mkdir(parents=True)
    shutil.copy2(quick_history.warehouse, cfg.paths.warehouse)
    before = hashlib.sha256(cfg.paths.warehouse.read_bytes()).hexdigest()
    conn = connect(cfg.paths.warehouse)
    try:
        with pytest.raises(SealError, match="no hay sello"):
            evaluate(conn, cfg, run_key="r9", as_of=quick_history.runs[-1].spec.as_of, source_sha256=quick_history.view.source_sha256)
    finally:
        conn.close()
    assert hashlib.sha256(cfg.paths.warehouse.read_bytes()).hexdigest() == before and not cfg.paths.seal.exists()
