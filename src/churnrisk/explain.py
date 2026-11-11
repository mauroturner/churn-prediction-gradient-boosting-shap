"""The reasons of each customer: SHAP on the uncalibrated log-odds, checked in every explained row (RF18, AC18; D15; M06; plan, section 13).

``shap.TreeExplainer`` with ``feature_perturbation="tree_path_dependent"`` explains the classifier of the model's pipeline on the matrix its
``ColumnTransformer`` produces (the numeric features and, in F2, one indicator per country group). research.md measured, with ``shap``
0.51.0 and scikit-learn 1.9.1, an error of 8.4e-15 with the country one-hot and of 3.6 with native categorical splits, so:

- ``refuse_native_categorical`` refuses, before anything is explained, a classifier with native categorical splits;
- ``explain`` checks **every** row: ``|base value + sum of the values - log-odds| <= shap_additivity_tol``, or ``ExplanationError`` (M06)
  names how many rows fail, the first by its position (never by its customer) and the largest error, and the task fails. No reason is
  published without additivity.

SHAP explains the log-odds of the uncalibrated model (``model.log_odds``), not the calibrated probability: the isotonic map is monotone and
does not reorder the customers, but the reasons do not add up to the calibrated risk (D15). The country's indicators are added into one
``country_group`` contribution, which keeps the sum, so the reasons and the importance name the 16 features and the country. The reasons of a
row are its ``shap_top_reasons`` largest contributions (towards the risk first), ties by the order of ``schema.FEATURE_COLUMNS``, each with
its direction: ``sube`` when it is above 0 and ``baja`` otherwise. The explainer is never saved: it is rebuilt from the model (D40).

This module never reads a table of labels (a static test reads this file).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import shap
from sklearn.pipeline import Pipeline

from churnrisk.features import COUNTRY, NUMERIC_FEATURES
from churnrisk.model import log_odds
from churnrisk.schema import FEATURE_COLUMNS

REASON_COLUMNS = ("cut_date", "customer_id", "rank", "feature", "shap_value", "direction")
UP, DOWN = "sube", "baja"


class ExplanationError(RuntimeError):
    """M06: the SHAP values of some row do not add up to its log-odds, or the pipeline has native categorical splits, whose SHAP values never
    do (D15). The task fails; no reason is published."""


@dataclass(frozen=True)
class Explanation:
    """The SHAP values of each explained row (index of the matrix, columns of the transformed matrix), the base value, the log-odds of
    each row and the largest additivity error."""

    values: pd.DataFrame
    base_value: float
    log_odds: np.ndarray
    max_error: float


def _classifier(pipeline: Pipeline):
    return pipeline.named_steps["classifier"]


def _designates_columns(categorical_features) -> bool:
    if categorical_features is None or isinstance(categorical_features, str):   # None, or "from_dtype", which the fitted mask then decides
        return False
    values = np.asarray(categorical_features)
    return bool(values.any()) if values.dtype == bool else values.size > 0


def refuse_native_categorical(pipeline: Pipeline) -> None:
    """``ExplanationError`` if the classifier of `pipeline` splits any column as a native category: SHAP is not additive then (D15)."""
    classifier = _classifier(pipeline)
    fitted = getattr(classifier, "is_categorical_", None)
    if _designates_columns(getattr(classifier, "categorical_features", None)) or (fitted is not None and np.any(fitted)):
        raise ExplanationError("el clasificador tiene divisiones categóricas nativas: SHAP no suma su log-odds (research.md: error 3,6); "
                               "el país entra como indicadores one-hot (D13, D15)")


def explainer_for(pipeline: Pipeline) -> shap.TreeExplainer:
    """The tree explainer of the pipeline's classifier, built only after ``refuse_native_categorical``."""
    refuse_native_categorical(pipeline)
    return shap.TreeExplainer(_classifier(pipeline), feature_perturbation="tree_path_dependent")


def explain(pipeline: Pipeline, x: pd.DataFrame, tol: float) -> Explanation:
    """The SHAP values of every row of the matrix `x`, checked against the log-odds of the uncalibrated `pipeline` row by row (M06)."""
    explainer = explainer_for(pipeline)
    prep = pipeline.named_steps["prep"]
    values = np.asarray(explainer.shap_values(prep.transform(x), check_additivity=False), dtype="float64")
    base = float(np.ravel(explainer.expected_value)[0])
    expected = log_odds(pipeline, x)
    if values.shape != (len(x), len(prep.get_feature_names_out())):
        raise ExplanationError(f"M06: SHAP devolvió una matriz de {values.shape} y se esperaba {(len(x), len(prep.get_feature_names_out()))}")
    error = np.abs(base + values.sum(axis=1) - expected)
    failing = np.flatnonzero(~(error <= tol))          # a NaN never passes
    if failing.size:
        raise ExplanationError(f"M06: SHAP no suma el log-odds en {failing.size} filas (tolerancia {tol}); la primera en la posición "
                               f"{int(failing[0])}, con un error máximo de {float(np.nanmax(error)) if np.isfinite(error).any() else float('nan'):.3g}")
    return Explanation(pd.DataFrame(values, index=x.index, columns=list(prep.get_feature_names_out())), base, expected, float(error.max(initial=0.0)))


def _feature_of(column: str) -> str:
    if column in NUMERIC_FEATURES:
        return column
    if column.startswith(f"{COUNTRY}_"):
        return COUNTRY
    raise ExplanationError(f"la columna explicada {column!r} no es una variable permitida ni un indicador del país")


def by_feature(expl: Explanation) -> pd.DataFrame:
    """The SHAP values added by feature (the country's indicators into ``country_group``), columns in the order of ``FEATURE_COLUMNS``."""
    features = [_feature_of(c) for c in expl.values.columns]
    summed = expl.values.T.groupby(features, sort=False).sum().T
    return summed[[name for name in FEATURE_COLUMNS if name in summed.columns]]


def top_reasons(expl: Explanation, k: int) -> pd.DataFrame:
    """The `k` largest contributions of each row (index ``(cut_date, customer_id)``), ``REASON_COLUMNS``, ranked from 1."""
    values = by_feature(expl)
    names = np.asarray(values.columns)
    data = values.to_numpy()
    order = np.argsort(-data, axis=1, kind="stable")[:, :k]          # stable: a tie keeps the order of the features
    rows = []
    for (cut, customer), picks, row in zip(values.index, order, data, strict=True):
        for rank, j in enumerate(picks, start=1):
            rows.append((cut, int(customer), rank, str(names[j]), float(row[j]), UP if row[j] > 0 else DOWN))
    return pd.DataFrame(rows, columns=list(REASON_COLUMNS))


def global_importance(expl: Explanation) -> pd.DataFrame:
    """The mean absolute SHAP value of each feature over the explained rows, the country summed, largest first (ties in feature order)."""
    mean = by_feature(expl).abs().mean(axis=0)
    table = pd.DataFrame({"feature": mean.index, "mean_abs_shap": mean.to_numpy()})
    return table.iloc[np.argsort(-table["mean_abs_shap"].to_numpy(), kind="stable")].reset_index(drop=True)
