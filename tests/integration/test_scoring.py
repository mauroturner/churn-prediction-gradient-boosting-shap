"""The scores of each run (U16, AC24; RF21; M02, M04, M06): every active customer of the run's cut gets exactly one calibrated risk, its contact
and its three reasons, written once to insert-only tables; no later run changes a score."""

from __future__ import annotations

import sqlite3
from datetime import date

import numpy as np
import pytest

from churnrisk.explain import ExplanationError, explain, top_reasons
from churnrisk.features import COUNTRY, FEATURE_SETS, build_matrix, read_features
from churnrisk.launch import load_registered
from churnrisk.model import log_odds, predict_risk
from churnrisk.schema import FEATURE_COLUMNS
from churnrisk.scoring import RunMeta, ScoreError, score_cut
from churnrisk.warehouse import connect


def rows_of(table: list[tuple], cut: date) -> list[tuple]:
    return [row for row in table if row[0] == cut.isoformat()]


# --- the RED of U16 ------------------------------------------------------------------------------------------------------


def test_scores_never_change_in_later_runs(quick_history, copy_of):
    """Each run scores its cut (the day after its calculation date) and only it; the scores and reasons of every earlier cut are byte for byte
    those its own run wrote, after every later run; scoring a cut again adds nothing."""
    runs = quick_history.runs
    assert [r.spec.cut for r in runs] == [date(2011, 8, 1), date(2011, 9, 1), date(2011, 10, 1), date(2011, 11, 1), date(2011, 12, 1), None]
    for index, run in enumerate(runs):
        if run.spec.cut is None:
            assert run.score is None and run.scores == runs[index - 1].scores, "the close scores nothing"
            continue
        mine = rows_of(run.scores, run.spec.cut)
        assert run.score.scored == len(mine) > 0 and run.score.already_scored == 0
        assert {row[3] for row in mine} == {run.run_key} and {row[2] for row in mine} == {run.spec.as_of.isoformat()}
        assert len(run.scores) == sum(len(rows_of(run.scores, r.spec.cut)) for r in runs[: index + 1] if r.spec.cut), "only its own cut is added"
        for later in runs[index + 1:]:
            assert rows_of(later.scores, run.spec.cut) == mine, f"the scores of {run.spec.cut} changed in {later.run_key}"
            assert rows_of(later.reasons, run.spec.cut) == rows_of(run.reasons, run.spec.cut)
    conn = connect(copy_of(quick_history.warehouse))
    try:
        registered = load_registered(conn, quick_history.cfg)
        meta = RunMeta("r9", date(2011, 12, 9), registered.model_version, registered.threshold)
        again = score_cut(conn, date(2011, 8, 1), registered.bundle, meta, quick_history.view)
        assert (again.scored, again.already_scored) == (0, runs[0].score.scored)
        assert conn.execute("SELECT * FROM model_scores ORDER BY 1, 2, 3").fetchall() == runs[-1].scores
    finally:
        conn.close()


# --- one score per active customer with its three reasons -------------------------------------------------------------------


def test_each_active_customer_gets_one_calibrated_risk_its_contact_and_its_three_reasons(quick_history):
    """AC24: the scored customers are the cut's population; the risk is the frozen model's calibrated probability (M04), the log-odds the one
    SHAP explains, the contact ``risk >= threshold`` and the three reasons the largest contributions towards the risk, each with its sign."""
    run = quick_history.runs[0]
    conn = sqlite3.connect(quick_history.warehouse)
    try:
        population = read_features(conn, [run.spec.cut])
        registered = load_registered(conn, quick_history.cfg)
    finally:
        conn.close()
    scores = rows_of(run.scores, run.spec.cut)
    assert [row[1] for row in scores] == list(population.index.get_level_values("customer_id")), "one score per active customer, in order"
    model = registered.bundle.model
    matrix = build_matrix(population[list(FEATURE_COLUMNS)], model.feature_set, model.country_groups)
    risk, lo = predict_risk(model, matrix), log_odds(model.pipeline, matrix)
    np.testing.assert_array_equal([row[5] for row in scores], risk)
    np.testing.assert_array_equal([row[6] for row in scores], lo)
    assert all(row[7] == registered.threshold and row[8] == int(row[5] >= registered.threshold) for row in scores)
    assert {row[4] for row in scores} == {registered.model_version} == {quick_history.cfg.model.model_version}
    assert 0 < sum(row[8] for row in scores) < len(scores), "some customers are contacted, not all"
    expected = top_reasons(explain(model.pipeline, matrix, quick_history.view.criteria.shap_additivity_tol), quick_history.view.evaluation.shap_top_reasons)
    reasons = rows_of(run.reasons, run.spec.cut)
    features = {COUNTRY if name.startswith(f"{COUNTRY}_") else name for name in model.pipeline.named_steps["prep"].get_feature_names_out()}
    k = min(quick_history.view.evaluation.shap_top_reasons, len(features))      # three, or every feature of a smaller set (F0 has two; D64)
    assert len(reasons) == k * len(scores) and k == min(3, len(FEATURE_SETS[model.feature_set]))
    assert reasons == sorted((c.isoformat(), int(customer), int(rank), f, float(v), d) for c, customer, rank, f, v, d in expected.itertuples(index=False))
    assert all(r[5] == ("sube" if r[4] > 0 else "baja") and r[3] in FEATURE_COLUMNS for r in reasons)
    by_customer: dict[int, list[float]] = {}
    for r in reasons:
        by_customer.setdefault(r[1], []).append(r[4])
    assert all(values == sorted(values, reverse=True) for values in by_customer.values()), "rank 1 is the largest contribution"


@pytest.mark.parametrize("table", ["model_scores", "score_reasons"])
def test_the_scores_and_their_reasons_are_insert_only(quick_history, copy_of, table):
    conn = connect(copy_of(quick_history.warehouse))
    try:
        row = conn.execute(f"SELECT * FROM {table} LIMIT 1").fetchone()
        for statement in (f"UPDATE {table} SET cut_date = cut_date WHERE customer_id = ?", f"DELETE FROM {table} WHERE customer_id = ?"):
            with pytest.raises(sqlite3.DatabaseError, match="solo inserción"):
                conn.execute(statement, (row[1],))
        with pytest.raises(sqlite3.DatabaseError, match="solo inserción"):
            conn.execute(f"INSERT OR REPLACE INTO {table} VALUES ({', '.join('?' for _ in row)})", row)
    finally:
        conn.close()


def test_a_check_that_fails_inserts_no_score_and_a_cut_without_population_or_a_bad_threshold_is_refused(quick_history, copy_of, monkeypatch):
    """M06 (a row whose SHAP values do not add up), found after the risks are computed: nothing of the cut is inserted. A cut that has no
    population yet, a threshold out of [0, 1] (or a boolean) and an artifact of another version are refused before anything is read."""
    import churnrisk.scoring as scoring

    conn = connect(copy_of(quick_history.warehouse))
    try:
        registered = load_registered(conn, quick_history.cfg)
        meta = RunMeta("r9", date(2011, 12, 9), registered.model_version, registered.threshold)
        unscored = date(2011, 7, 1)          # a cut with its population and no scores: no run scores the purge before the test
        assert not read_features(conn, [unscored]).empty
        real_explain = scoring.explain

        def failing(*args, **kwargs):
            real_explain(*args, **kwargs)
            raise ExplanationError("M06: SHAP no suma el log-odds en 1 filas (tolerancia 1e-06)")

        monkeypatch.setattr(scoring, "explain", failing)
        with pytest.raises(ExplanationError, match="M06"):
            score_cut(conn, unscored, registered.bundle, meta, quick_history.view)
        assert conn.execute("SELECT * FROM model_scores ORDER BY 1, 2, 3").fetchall() == quick_history.runs[-1].scores
        assert conn.execute("SELECT * FROM score_reasons ORDER BY 1, 2, 3").fetchall() == quick_history.runs[-1].reasons
        monkeypatch.setattr(scoring, "explain", real_explain)
        with pytest.raises(ScoreError, match="no tiene población"):
            score_cut(conn, date(2012, 1, 1), registered.bundle, meta, quick_history.view)
        for bad in (1.5, -0.1, True):
            with pytest.raises(ScoreError, match="el umbral"):
                score_cut(conn, unscored, registered.bundle, RunMeta("r9", meta.as_of, meta.model_version, bad), quick_history.view)
        with pytest.raises(ScoreError, match="versión"):
            score_cut(conn, unscored, registered.bundle, RunMeta("r9", meta.as_of, "v9", meta.threshold), quick_history.view)
        assert conn.execute("SELECT COUNT(*) FROM model_scores WHERE cut_date = ?", (unscored.isoformat(),)).fetchone()[0] == 0
        # a risk equal to the threshold is a contact: the threshold is the first risk that pays (``p >= t``, plan, section 14)
        population = read_features(conn, [unscored])
        model = registered.bundle.model
        risk = predict_risk(model, build_matrix(population[list(FEATURE_COLUMNS)], model.feature_set, model.country_groups))
        at = float(np.median(risk))
        result = score_cut(conn, unscored, registered.bundle, RunMeta("r9", meta.as_of, meta.model_version, at), quick_history.view)
        rows = conn.execute("SELECT risk, is_contact FROM model_scores WHERE cut_date = ?", (unscored.isoformat(),)).fetchall()
        assert any(r == at for r, _c in rows) and all(c == int(r >= at) for r, c in rows) and result.contacts == sum(c for _r, c in rows)
    finally:
        conn.close()
