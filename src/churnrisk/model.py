"""The model: a fixed grid of gradient-boosting candidates, selection and isotonic calibration on V1, and the leak tripwire (RF17, AC14,
AC16, AC17; D12-D15, D41; M01, M02, M04, M07; plan, section 12). Adapted from project 03's ``model.py``.

Everything here learns from the labelled rows of the launch (``split.labelled_rows``) and nothing else:

- M07 first: the training block, V1 and V2 must each have both classes, or ``BlockLabelError`` before any matrix is built or fitted;
- the **country groups** are fixed from the training rows (``features.country_groups``) and every matrix is built by
  ``features.build_matrix``, with its guards;
- the candidates (the sets of ``candidate_sets`` times the grid of ``[model]``, 24 by default, in a fixed order) are fitted on the
  **training** block: an explicit one-hot of the country with the launch's groups (``handle_unknown="error"``: an unmapped country is an
  error, never a row of zeros) and the numeric features as they are, then ``HistGradientBoostingClassifier`` **without**
  ``categorical_features`` (SHAP is additive only so, D15), without early stopping and seeded;
- the one with the lowest uncalibrated log loss on **V1** is selected; within 1e-6 of the best, the simplest (F0 < F1 < F2, then fewer
  leaves, more samples per leaf and a lower learning rate); every loss is kept;
- M01: if the AUC of the selected candidate on V1 reaches ``leak_tripwire_auc``, ``LeakageError`` stops the launch (D41);
- it is calibrated with isotonic regression on **V1** (``CalibratedClassifierCV(FrozenEstimator(pipeline))``). V2 only gets the calibrated
  risks, for the threshold of U15; the test is never read.

``predict_risk`` gives the calibrated risk and refuses a matrix whose columns are not exactly the model's set (M02) and any probability that
is not finite or not in [0, 1] (M04). ``log_odds`` gives the uncalibrated log-odds, the one SHAP explains: the isotonic map is monotone and
does not reorder it (D15). No F1 or F-beta score is used to choose anything here: neither this module nor ``threshold.py`` imports one or
names scikit-learn's F1 scorer (``tests/unit/test_threshold.py::test_neither_the_threshold_nor_the_model_imports_f1`` reads both sources); the only F1 of
the project is the one D61's test computes to show what the cost threshold avoids.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.frozen import FrozenEstimator
from sklearn.metrics import log_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from churnrisk.config import SealedConfig
from churnrisk.features import COUNTRY, FEATURE_SETS, LeakageError, build_matrix, check_matrix, country_groups
from churnrisk.schema import FEATURE_COLUMNS
from churnrisk.split import require_both_classes

logger = logging.getLogger(__name__)

TIE_TOLERANCE = 1e-6          # candidates within this log loss of the best are a tie, and the simplest of them is selected
SET_RANK: dict[str, int] = {name: rank for rank, name in enumerate(FEATURE_SETS)}   # f0 < f1 < f2
CALIBRATION_METHODS = ("isotonic",)
LAUNCH_BLOCKS = ("train", "valid_v1", "valid_v2")


@dataclass(frozen=True)
class Candidate:
    """One point of the grid: a feature set and a configuration of the classifier."""

    feature_set: str
    learning_rate: float
    max_leaf_nodes: int
    min_samples_leaf: int

    def simplicity(self) -> tuple:
        """Sorts the simplest first: the smaller set, then fewer leaves, then more samples per leaf, then the lower learning rate."""
        return (SET_RANK[self.feature_set], self.max_leaf_nodes, -self.min_samples_leaf, self.learning_rate)

    def params(self) -> dict[str, float | int]:
        return {"learning_rate": self.learning_rate, "max_leaf_nodes": self.max_leaf_nodes, "min_samples_leaf": self.min_samples_leaf}


def candidates(view: SealedConfig) -> list[Candidate]:
    """The grid in a fixed order: by set (as ``candidate_sets`` lists them), then learning rate, leaves and samples per leaf in the order of
    ``[model]`` (3 x 8 = 24 by default)."""
    m = view.model
    return [Candidate(s, lr, leaves, msl) for s in view.features.candidate_sets
            for lr in m.learning_rate for leaves in m.max_leaf_nodes for msl in m.min_samples_leaf]


def make_pipeline(c: Candidate, view: SealedConfig, country_groups: Sequence[str]) -> Pipeline:
    """The unfitted pipeline of a candidate: the numeric features of its set as they are and, in F2, the country one-hot with the launch's
    groups (an unknown value is an error), then the classifier, without native categorical splits."""
    columns = FEATURE_SETS[c.feature_set]
    numeric = [name for name in columns if name != COUNTRY]
    transformers: list[tuple] = [("numeric", "passthrough", numeric)]
    if COUNTRY in columns:
        transformers.append(("country", OneHotEncoder(categories=[list(country_groups)], handle_unknown="error", sparse_output=False, dtype=np.float64), [COUNTRY]))
    prep = ColumnTransformer(transformers, remainder="drop", verbose_feature_names_out=False)
    classifier = HistGradientBoostingClassifier(
        learning_rate=c.learning_rate, max_leaf_nodes=c.max_leaf_nodes, min_samples_leaf=c.min_samples_leaf,
        l2_regularization=view.model.l2_regularization, max_iter=view.model.max_iter, early_stopping=False, random_state=view.model.random_state,
        categorical_features=None,
    )
    return Pipeline([("prep", prep), ("classifier", classifier)])


def fit_candidates(cands: Sequence[Candidate], view: SealedConfig, x_train: Mapping[str, pd.DataFrame], y_train, groups: Sequence[str]) -> list[tuple[Candidate, Pipeline]]:
    """Fit every candidate on the training matrix of its feature set (`x_train` maps a set to its matrix)."""
    fitted = []
    for c in cands:
        if c.feature_set not in x_train:
            raise ValueError(f"falta la matriz de entrenamiento del conjunto {c.feature_set}")
        pipeline = make_pipeline(c, view, groups)
        pipeline.fit(x_train[c.feature_set], np.asarray(y_train))
        fitted.append((c, pipeline))
    return fitted


@dataclass(frozen=True)
class Selection:
    """The candidate with the lowest uncalibrated log loss on V1, the loss of every candidate and the AUC of the chosen one on V1."""

    chosen: Candidate
    pipeline: Pipeline
    losses: tuple[tuple[Candidate, float], ...]
    auc_v1: float

    @property
    def log_loss_v1(self) -> float:
        return dict(self.losses)[self.chosen]


def select(fitted: Sequence[tuple[Candidate, Pipeline]], x_v1: Mapping[str, pd.DataFrame], y_v1) -> Selection:
    """The candidate with the lowest uncalibrated log loss on V1; within ``TIE_TOLERANCE`` of the best, the simplest."""
    if not fitted:
        raise ValueError("no hay candidatos para elegir")
    y = np.asarray(y_v1)
    require_both_classes(y, "valid_v1")
    scored = []
    for c, pipeline in fitted:
        if c.feature_set not in x_v1:
            raise ValueError(f"falta la matriz de V1 del conjunto {c.feature_set}")
        scored.append((c, pipeline, float(log_loss(y, pipeline.predict_proba(x_v1[c.feature_set])[:, 1], labels=[0, 1]))))
    best = min(loss for _c, _p, loss in scored)
    chosen, pipeline, _loss = min((s for s in scored if s[2] <= best + TIE_TOLERANCE), key=lambda s: s[0].simplicity())
    auc = float(roc_auc_score(y, pipeline.predict_proba(x_v1[chosen.feature_set])[:, 1]))
    return Selection(chosen, pipeline, tuple((c, loss) for c, _p, loss in scored), auc)


def check_tripwire(selection: Selection, view: SealedConfig) -> None:
    """M01: stop the launch if the AUC of the selected candidate on V1 reaches ``leak_tripwire_auc`` (D41). Raises ``LeakageError``."""
    limit = view.criteria.leak_tripwire_auc
    if not selection.auc_v1 < limit:              # a NaN AUC is not below the limit either: it stops the launch too (D59)
        logger.error("M01: the AUC on V1 of the selected candidate (set %s) is %.4f, not below the tripwire %s: the launch stops",
                     selection.chosen.feature_set, selection.auc_v1, limit)
        raise LeakageError(
            f"M01: el AUC del candidato elegido en V1 es {selection.auc_v1:.4f}, igual o mayor que el umbral de {limit}: posible fuga de información "
            f"(el conjunto {selection.chosen.feature_set}). El lanzamiento se detiene (docs/runbook.md, R5)"
        )


def calibrate(pipeline: Pipeline, x_v1: pd.DataFrame, y_v1, method: str = "isotonic") -> CalibratedClassifierCV:
    """Calibrate an already fitted pipeline with `x_v1` and `y_v1` only: ``CalibratedClassifierCV(FrozenEstimator(pipeline), method=...)``."""
    if method not in CALIBRATION_METHODS:
        raise ValueError(f"método de calibración desconocido: {method!r}; el único implementado es {', '.join(CALIBRATION_METHODS)}")
    y = np.asarray(y_v1)
    require_both_classes(y, "valid_v1")
    return CalibratedClassifierCV(FrozenEstimator(pipeline), method=method).fit(x_v1, y)


@dataclass(frozen=True)
class RiskModel:
    """The model in use: the selected pipeline (fitted on the training block), its isotonic calibrator (fitted on V1), the feature set both
    expect and the country groups fixed at the launch."""

    feature_set: str
    candidate: Candidate
    pipeline: Pipeline
    calibrated: CalibratedClassifierCV
    country_groups: tuple[str, ...]
    calibration: str


def _check_probabilities(p: np.ndarray) -> np.ndarray:
    """M04: one finite probability in [0, 1] per row."""
    p = np.asarray(p, dtype="float64")
    bad = ~np.isfinite(p) | (p < 0) | (p > 1)
    if bad.any():
        raise ValueError(f"M04: {int(bad.sum())} probabilidades no son finitas o están fuera de [0, 1] (la primera en la posición {int(np.flatnonzero(bad)[0])})")
    return p


def predict_risk(model: RiskModel, x: pd.DataFrame) -> np.ndarray:
    """The calibrated probability of churn of each row of `x`, whose columns must be exactly the model's set, in order (M02); every
    probability is finite and in [0, 1] (M04)."""
    check_matrix(x, model.feature_set)
    return _check_probabilities(model.calibrated.predict_proba(x)[:, 1])


def log_odds(pipeline: Pipeline, x: pd.DataFrame) -> np.ndarray:
    """The uncalibrated log-odds of the pipeline (``decision_function``): what SHAP explains (D15)."""
    return np.asarray(pipeline.decision_function(x), dtype="float64")


@dataclass(frozen=True)
class TrainedModel:
    """What the launch learns: the model in use, how it was selected, the rows of each block and the calibrated risks of V2 (index
    ``(cut_date, customer_id)``, columns ``churned`` and ``risk``), from which U15 chooses the threshold."""

    model: RiskModel
    selection: Selection
    rows: dict[str, int]
    valid_v2: pd.DataFrame


def train_model(labelled: pd.DataFrame, view: SealedConfig) -> TrainedModel:
    """Fit, select, check and calibrate the model of the launch from its labelled rows (``split.labelled_rows``: ``block``, ``churned`` and
    the features). Only the training block, V1 and V2 are read; anything else in `labelled` is ignored."""
    parts = {name: labelled[labelled["block"] == name] for name in LAUNCH_BLOCKS}
    for name, rows in parts.items():
        require_both_classes(rows["churned"].to_numpy(), name)        # M07, before anything is built or fitted
    groups = country_groups(parts["train"], view.features.country_min_customers)
    sets = list(view.features.candidate_sets)
    x = {name: {s: build_matrix(rows[list(FEATURE_COLUMNS)], s, groups) for s in sets} for name, rows in parts.items()}
    y = {name: rows["churned"].to_numpy() for name, rows in parts.items()}
    fitted = fit_candidates(candidates(view), view, x["train"], y["train"], groups)
    selection = select(fitted, x["valid_v1"], y["valid_v1"])
    check_tripwire(selection, view)
    chosen = selection.chosen.feature_set
    calibrated = calibrate(selection.pipeline, x["valid_v1"][chosen], y["valid_v1"], view.model.calibration)
    model = RiskModel(chosen, selection.chosen, selection.pipeline, calibrated, groups, view.model.calibration)
    valid_v2 = pd.DataFrame({"churned": y["valid_v2"], "risk": predict_risk(model, x["valid_v2"][chosen])}, index=parts["valid_v2"].index)
    return TrainedModel(model, selection, {name: len(rows) for name, rows in parts.items()}, valid_v2)
