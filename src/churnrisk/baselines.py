"""The baselines B0-B5, their probabilities and the strongest of them, B* (RF15, RF16, AC15, AC17, AC20; D14, D16; plan, section 11).

Each baseline is a **risk score** (higher means more likely to churn) that is a rule of the features of the row, known before its cut, and
of the BG/NBD parameters fitted on the history before ``bgnbd_fit_cut`` (``bgnbd.py``); no score reads a label:

- B0 ``b0_all``: contact everyone (1 for every row);
- B1 ``b1_recency``: ``rec_days``;
- B2 ``b2_rfm``: ``-(R + F + M)``, quintiles inside each cut by average rank (project 02, D09): R of ``-rec_days``, F of ``freq_365`` and M
  of ``mon_365``, a score from 3 to 15;
- B3 ``b3_bgnbd``: ``-(expected purchases in the next N days)``, the window of the label;
- B4 ``b4_frequency``: ``-freq_365``;
- B5 ``b5_alive``: ``1 - P(alive)``, informative: it saturates among active customers.

For the decisions by cost each score becomes a probability with ``IsotonicRegression(out_of_bounds="clip")`` fitted on **V1** only, the
same procedure as the model (D14). **B*** is the one of ``strongest_candidates`` with the largest AUC on the whole validation (V1 and V2); on
a tie to 1e-6, the first of that list, the simplest. A block with one class is ``BlockLabelError`` before anything learns from it (M07).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import roc_auc_score

from churnrisk.bgnbd import BGNBDParams, expected_purchases, p_alive, summary_from_features
from churnrisk.config import SealedConfig
from churnrisk.schema import FEATURE_COLUMNS
from churnrisk.split import require_both_classes

METHODS = ("b0_all", "b1_recency", "b2_rfm", "b3_bgnbd", "b4_frequency", "b5_alive")
SCORED = METHODS[1:]            # the ones whose score becomes a probability; B0 contacts everyone and has none
STRONGEST_TIE = 1e-6
VALIDATION = ("valid_v1", "valid_v2")
SCORES = 5


def quintile_scores(values: pd.Series) -> pd.Series:
    """``ceil(5 x average rank / n)`` of each value, from 1 (lowest) to 5 (highest); ties share the average rank (project 02, D09), done in
    integers so that a rank that is a multiple of n / 5 never falls on the wrong side of a boundary through floating point."""
    n = len(values)
    if n == 0:
        return pd.Series([], index=values.index, dtype="int64")
    doubled = (values.rank(method="average") * 2).round().astype("int64")  # average ranks are multiples of one half
    return ((SCORES * doubled + 2 * n - 1) // (2 * n)).clip(1, SCORES).astype("int64")


def rfm_scores(features: pd.DataFrame) -> pd.DataFrame:
    """``r_score``, ``f_score``, ``m_score`` and ``rfm_score`` of each row, the quintiles cut inside each cut (index level ``cut_date``)."""
    by_cut = features.groupby(level="cut_date", sort=False)
    out = pd.DataFrame(index=features.index)
    for name, column, sign in (("r_score", "rec_days", -1), ("f_score", "freq_365", 1), ("m_score", "mon_365", 1)):
        out[name] = by_cut[column].transform(lambda values, s=sign: quintile_scores(s * values)).astype("int64")
    out["rfm_score"] = out["r_score"] + out["f_score"] + out["m_score"]
    return out


def baseline_scores(features: pd.DataFrame, params: BGNBDParams, horizon_days: int) -> pd.DataFrame:
    """The risk score of each baseline for each row of `features` (index ``(cut_date, customer_id)``): columns ``METHODS``."""
    summary = summary_from_features(features)
    x, t_x, T = (summary[c].to_numpy(float) for c in ("x", "t_x", "T"))
    out = pd.DataFrame(index=features.index)
    out["b0_all"] = 1.0
    out["b1_recency"] = features["rec_days"].astype("float64")
    out["b2_rfm"] = -rfm_scores(features)["rfm_score"].astype("float64")
    out["b3_bgnbd"] = -expected_purchases(params, float(horizon_days), x, t_x, T)
    out["b4_frequency"] = -features["freq_365"].astype("float64")
    out["b5_alive"] = 1.0 - p_alive(params, x, t_x, T)
    return out[list(METHODS)]


def _rows(labelled: pd.DataFrame, blocks: Sequence[str]) -> pd.Index:
    return labelled.index[labelled["block"].isin(blocks).to_numpy()]


def fit_calibrators(scores: pd.DataFrame, labelled: pd.DataFrame) -> dict[str, IsotonicRegression]:
    """One isotonic calibrator per scored baseline, fitted on the rows of V1 only (``labelled``: ``block`` and ``churned``)."""
    rows = _rows(labelled, ("valid_v1",))
    y = labelled.loc[rows, "churned"].to_numpy()
    require_both_classes(y, "valid_v1")
    return {m: IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0, increasing=True).fit(scores.loc[rows, m].to_numpy(), y) for m in SCORED}


def probabilities(calibrators: dict[str, IsotonicRegression], scores: pd.DataFrame) -> pd.DataFrame:
    """The calibrated probability of each scored baseline for each row of `scores`."""
    return pd.DataFrame({m: calibrators[m].predict(scores[m].to_numpy()) for m in SCORED}, index=scores.index)[list(SCORED)]


def strongest(scores: pd.DataFrame, labelled: pd.DataFrame, candidates: Sequence[str]) -> tuple[str, dict[str, float]]:
    """``(B*, AUC of each candidate)``: the candidate with the largest AUC on the rows of V1 and V2 only; within 1e-6 of the best, the first of
    `candidates` (they come in order of simplicity)."""
    unknown = [c for c in candidates if c not in METHODS]
    if unknown or not candidates:
        raise ValueError(f"candidatos a B* desconocidos o ninguno: {list(unknown) or list(candidates)}; se esperaban de {', '.join(METHODS)}")
    rows = _rows(labelled, VALIDATION)
    y = labelled.loc[rows, "churned"].to_numpy()
    require_both_classes(y, "validación (V1 y V2)")
    aucs = {c: float(roc_auc_score(y, scores.loc[rows, c].to_numpy())) for c in candidates}
    best = max(aucs.values())
    return next(c for c in candidates if aucs[c] >= best - STRONGEST_TIE), aucs


@dataclass(frozen=True)
class Baselines:
    """What the launch learns about the baselines: the risk scores of the labelled rows, the calibrators of V1 and B* with its AUCs."""

    scores: pd.DataFrame
    calibrators: dict[str, IsotonicRegression]
    b_star: str
    auc_validation: dict[str, float]
    bgnbd: BGNBDParams


def fit_baselines(labelled: pd.DataFrame, params: BGNBDParams, view: SealedConfig) -> Baselines:
    """The baselines of the launch from the labelled rows (``split.labelled_rows``) and the BG/NBD parameters of the launch."""
    scores = baseline_scores(labelled[list(FEATURE_COLUMNS)], params, view.label.horizon_days)
    if not np.isfinite(scores.to_numpy()).all():               # checked before anything learns from the scores
        raise ValueError("hay puntajes de las líneas base que no son finitos")
    calibrators = fit_calibrators(scores, labelled)
    b_star, aucs = strongest(scores, labelled, view.baselines.strongest_candidates)
    return Baselines(scores, calibrators, b_star, aucs, params)
