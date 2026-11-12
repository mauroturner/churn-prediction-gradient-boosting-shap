"""Scoring a cut with the frozen model, with the three reasons of each risk (RF21, AC24; M02, M04, M06; D15; plan, section 15). Adapted from
project 03's ``scoring.py``.

``score_cut`` is the function an API would wrap (D43): it reads the population of the cut with its features (``features.read_features``, what is
known before the cut), builds the matrix with ``features.build_matrix`` and the country groups of the launch, asks the frozen model for the
calibrated risk of each customer (``model.predict_risk``: M02 and M04), explains the uncalibrated log-odds with SHAP and checks additivity in
every row (``explain.explain``: M06), and inserts one row per customer into ``model_scores`` and its ``shap_top_reasons`` reasons into
``score_reasons``, both insert only: a score never changes. The contact is ``risk >= threshold``. A repetition scores only the customers that have
no score yet, and what is already scored is read again inside the transaction that inserts (project 03, D63). If any check fails, nothing is
inserted. It never reads a table of labels (a static test reads this file).
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import date

import numpy as np

from churnrisk.config import SealedConfig
from churnrisk.explain import explain, top_reasons
from churnrisk.features import build_matrix, read_features
from churnrisk.model import predict_risk
from churnrisk.warehouse import apply_schema

logger = logging.getLogger(__name__)


class ScoreError(RuntimeError):
    """The scores of a cut cannot be produced; nothing was inserted."""


@dataclass(frozen=True)
class RunMeta:
    """What a run adds to every score it writes: its key, its calculation date, the version of the model and the sealed threshold."""

    run_key: str
    as_of: date
    model_version: str
    threshold: float


@dataclass(frozen=True)
class ScoreResult:
    cut: date
    scored: int              # customers scored by this call
    already_scored: int      # customers of the cut that had a score from an earlier call
    contacts: int            # of the customers scored by this call
    max_additivity_error: float
    threshold: float
    model_version: str
    as_of: date


def _scored(conn: sqlite3.Connection, cut: date) -> set[int]:
    return {r[0] for r in conn.execute("SELECT customer_id FROM model_scores WHERE cut_date = ?", (cut.isoformat(),))}


def score_cut(conn: sqlite3.Connection, cut: date, bundle, run_meta: RunMeta, view: SealedConfig) -> ScoreResult:
    """Score once each active customer of `cut` with the model of `bundle` (``registry.ModelBundle``) and insert its risk, its contact and its
    reasons. All or nothing: a matrix that is not the model's (M02), a probability out of [0, 1] (M04) or a row whose SHAP values do not add up
    to its log-odds (M06) inserts no row."""
    threshold = run_meta.threshold
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not 0 <= threshold <= 1:   # True is not the threshold 1.0
        raise ScoreError(f"el umbral debe ser un número entre 0 y 1, se recibió {threshold!r}")
    if bundle.model_version != run_meta.model_version:
        raise ScoreError(f"el artefacto es de la versión {bundle.model_version} y la corrida puntúa con la {run_meta.model_version}")
    apply_schema(conn)
    population = read_features(conn, [cut])
    if population.empty:
        raise ScoreError(f"el corte {cut} no tiene población en el almacén: se construyen sus cortes (build_cuts) antes de puntuarlo")
    done = _scored(conn, cut)
    todo = population[~population.index.get_level_values("customer_id").isin(sorted(done))]
    if todo.empty:
        return ScoreResult(cut, 0, len(done), 0, 0.0, float(threshold), run_meta.model_version, run_meta.as_of)
    model = bundle.model
    matrix = build_matrix(todo, model.feature_set, model.country_groups)
    risk = predict_risk(model, matrix)                                           # M02 and M04
    explanation = explain(model.pipeline, matrix, view.criteria.shap_additivity_tol)   # M06, every row
    reasons = top_reasons(explanation, view.evaluation.shap_top_reasons)
    contact = risk >= threshold
    scores = [(cut.isoformat(), int(customer), run_meta.as_of.isoformat(), run_meta.run_key, run_meta.model_version, float(p), float(lo), float(threshold), int(c))
              for (_cut, customer), p, lo, c in zip(matrix.index, risk, explanation.log_odds, contact, strict=True)]
    reason_rows = [(cut.isoformat(), int(r.customer_id), int(r.rank), r.feature, float(r.shap_value), r.direction) for r in reasons.itertuples(index=False)]
    conn.execute("BEGIN IMMEDIATE")
    try:
        # read again inside the transaction: a call that overlapped this one and committed first keeps its own scores, and this one inserts the rest
        meanwhile = _scored(conn, cut) - done
        scores = [row for row in scores if row[1] not in meanwhile]
        reason_rows = [row for row in reason_rows if row[1] not in meanwhile]
        conn.executemany("INSERT INTO model_scores (cut_date, customer_id, as_of_date, run_key, model_version, risk, log_odds, threshold, is_contact) "
                         "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", scores)
        conn.executemany("INSERT INTO score_reasons (cut_date, customer_id, rank, feature, shap_value, direction) VALUES (?, ?, ?, ?, ?, ?)", reason_rows)
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        logger.warning("score %s of cut %s rolled back: nothing was inserted", run_meta.run_key, cut)
        raise
    contacts = int(sum(row[8] for row in scores))
    logger.info("score %s: cut=%s scored=%d already=%d contacts=%d threshold=%s max_error=%.3g", run_meta.run_key, cut, len(scores),
                len(done) + len(meanwhile), contacts, threshold, explanation.max_error)
    return ScoreResult(cut, len(scores), len(done) + len(meanwhile), contacts, float(np.float64(explanation.max_error)), float(threshold),
                       run_meta.model_version, run_meta.as_of)
