"""The reasons of each customer with SHAP (U14, AC18; RF18; D15, M06): the values plus the base value give the log-odds of the uncalibrated
model in every explained row, or the task fails naming the row by its position; a pipeline with native categorical splits is refused before
anything is explained; the reasons are the largest contributions towards the risk, with the country's indicators summed into one."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest
import shap
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OrdinalEncoder

from churnrisk import explain as explain_module
from churnrisk.config import SealedConfig
from churnrisk.explain import Explanation, ExplanationError, explain, global_importance, top_reasons
from churnrisk.features import COUNTRY, NUMERIC_FEATURES, build_matrix
from churnrisk.model import Candidate, log_odds, make_pipeline
from churnrisk.schema import FEATURE_COLUMNS

SHA = "a" * 64


def v2_of(launch_model, signal: str = "irregular_gaps"):
    labelled, trained = launch_model(signal)
    v2 = labelled[labelled["block"] == "valid_v2"]
    return labelled, trained, v2


def f2_pipeline(labelled: pd.DataFrame, trained, view: SealedConfig) -> Pipeline:
    """An F2 candidate of the launch's grid fitted on its training rows: the country one-hot reaches the explanation."""
    train = labelled[labelled["block"] == "train"]
    pipeline = make_pipeline(Candidate("f2", 0.1, 15, 50), view, trained.model.country_groups)
    return pipeline.fit(build_matrix(train[list(FEATURE_COLUMNS)], "f2", trained.model.country_groups), train["churned"].to_numpy())


# --- the RED of U14 -------------------------------------------------------------------------------------------------------


def test_shap_values_add_up_to_the_log_odds_of_every_explained_row(cfg, launch_model):
    """The launch's model on the 626 customers of V2, and an F2 candidate with the country one-hot: in every row, |base value + sum of the
    values - log-odds| <= shap_additivity_tol (M06, AC18)."""
    view = SealedConfig.of(cfg, SHA)
    tol = view.criteria.shap_additivity_tol
    labelled, trained, v2 = v2_of(launch_model)
    for pipeline, feature_set in ((trained.model.pipeline, trained.model.feature_set), (f2_pipeline(labelled, trained, view), "f2")):
        x = build_matrix(v2[list(FEATURE_COLUMNS)], feature_set, trained.model.country_groups)
        got = explain(pipeline, x, tol)
        expected = log_odds(pipeline, x)
        error = np.abs(got.base_value + got.values.sum(axis=1).to_numpy() - expected)
        assert error.max() <= tol and got.max_error == pytest.approx(error.max(), abs=1e-15), feature_set
        np.testing.assert_array_equal(got.log_odds, expected)
        assert list(got.values.columns) == list(pipeline.named_steps["prep"].get_feature_names_out()) and got.values.index.equals(x.index)
        assert np.abs(got.values.to_numpy()).sum(axis=1).min() > 0, "every row is explained by something"


def native_pipeline(labelled: pd.DataFrame) -> tuple[Pipeline, pd.DataFrame]:
    """The country as an ordinal code with HistGradientBoosting's own categorical splits: what research.md found not additive (3.6)."""
    train = labelled[labelled["block"] == "train"]
    x = train[list(FEATURE_COLUMNS)]
    prep = ColumnTransformer([("country", OrdinalEncoder(), [COUNTRY]), ("numeric", "passthrough", list(NUMERIC_FEATURES))], verbose_feature_names_out=False)
    classifier = HistGradientBoostingClassifier(max_iter=100, early_stopping=False, random_state=0, categorical_features=[True] + [False] * len(NUMERIC_FEATURES))
    return Pipeline([("prep", prep), ("classifier", classifier)]).fit(x, train["churned"].to_numpy()), x


def test_a_pipeline_with_native_categorical_splits_is_refused(cfg, launch_model, monkeypatch):
    labelled, _trained, _v2 = v2_of(launch_model)
    pipeline, x = native_pipeline(labelled)
    # why: explained anyway, its values do not add up to its log-odds
    raw = shap.TreeExplainer(pipeline.named_steps["classifier"], feature_perturbation="tree_path_dependent")
    transformed = pipeline.named_steps["prep"].transform(x.head(300))
    gap = np.abs(np.ravel(raw.expected_value)[0] + raw.shap_values(transformed, check_additivity=False).sum(axis=1) - log_odds(pipeline, x.head(300)))
    assert gap.max() > SealedConfig.of(cfg, SHA).criteria.shap_additivity_tol
    built = []
    monkeypatch.setattr(explain_module.shap, "TreeExplainer", lambda *a, **k: built.append(a) or pytest.fail("an explainer was built"))
    with pytest.raises(ExplanationError, match="categóricas nativas"):
        explain(pipeline, x.head(10), 1e-6)
    assert built == []
    unfitted = Pipeline([("prep", pipeline.named_steps["prep"]), ("classifier", HistGradientBoostingClassifier(categorical_features=[0]))])
    with pytest.raises(ExplanationError, match="categóricas nativas"):
        explain_module.refuse_native_categorical(unfitted)


# --- M06 and the reasons ------------------------------------------------------------------------------------------------------


def test_a_row_that_does_not_add_up_fails_the_task_naming_its_position_never_a_customer(cfg, launch_model, monkeypatch):
    labelled, trained, v2 = v2_of(launch_model)
    x = build_matrix(v2[list(FEATURE_COLUMNS)], trained.model.feature_set, trained.model.country_groups)
    real = shap.TreeExplainer

    class OffByOne(real):
        def shap_values(self, X, *args, **kwargs):
            values = np.array(real.shap_values(self, X, *args, **kwargs))
            values[3, 0] += 1e-3
            return values

    monkeypatch.setattr(explain_module.shap, "TreeExplainer", OffByOne)
    with pytest.raises(ExplanationError, match=r"M06.*1 filas.*posición 3.*0\.001") as error:
        explain(trained.model.pipeline, x, SealedConfig.of(cfg, SHA).criteria.shap_additivity_tol)
    assert not any(str(customer) in str(error.value) for customer in x.index.get_level_values("customer_id")), "a row by its position, never by its customer"


def hand_explanation() -> Explanation:
    """Three customers of one cut; the country is two indicators that the reasons and the importance add into one."""
    columns = ["rec_days", "freq_365", "gap_mean", "country_group_France", "country_group_Otros"]
    values = pd.DataFrame([[0.5, -0.2, 0.3, 0.1, 0.05],        # rec_days 0.5, gap_mean 0.3, country 0.15: all towards the risk
                           [-0.1, -0.4, -0.05, 0.0, -0.02],     # nothing towards the risk: the three least against, in order
                           [0.2, 0.2, -0.3, 0.0, 0.0]],         # a tie at 0.2 goes to the earlier feature; the country at 0 is «baja»
                          columns=columns,
                          index=pd.MultiIndex.from_tuples([(date(2011, 8, 1), c) for c in (90001, 90002, 90003)], names=["cut_date", "customer_id"]))
    return Explanation(values, -0.5, -0.5 + values.sum(axis=1).to_numpy(), 0.0)


def test_the_three_reasons_are_the_largest_contributions_towards_the_risk():
    reasons = top_reasons(hand_explanation(), 3)
    assert list(reasons.columns) == ["cut_date", "customer_id", "rank", "feature", "shap_value", "direction"]
    got = {(int(r.customer_id), int(r.rank)): (r.feature, round(r.shap_value, 10), r.direction) for r in reasons.itertuples()}
    assert got == {
        (90001, 1): ("rec_days", 0.5, "sube"), (90001, 2): ("gap_mean", 0.3, "sube"), (90001, 3): ("country_group", 0.15, "sube"),
        (90002, 1): ("country_group", -0.02, "baja"), (90002, 2): ("gap_mean", -0.05, "baja"), (90002, 3): ("rec_days", -0.1, "baja"),
        (90003, 1): ("rec_days", 0.2, "sube"), (90003, 2): ("freq_365", 0.2, "sube"), (90003, 3): ("country_group", 0.0, "baja"),
    }
    assert len(top_reasons(hand_explanation(), 2)) == 6 and set(reasons["feature"]) <= set(FEATURE_COLUMNS)


def test_the_importance_is_the_mean_absolute_shap_with_the_country_summed():
    importance = global_importance(hand_explanation())
    assert list(importance.columns) == ["feature", "mean_abs_shap"]
    assert [(r.feature, round(r.mean_abs_shap, 10)) for r in importance.itertuples()] == [
        ("rec_days", round(0.8 / 3, 10)), ("freq_365", round(0.8 / 3, 10)), ("gap_mean", round(0.65 / 3, 10)), ("country_group", round(0.17 / 3, 10))]
