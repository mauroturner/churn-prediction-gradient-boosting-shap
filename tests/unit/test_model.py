"""The model's rules (U13, AC16, AC17; RF17; D13, D14, D15; M02, M04, M07): the grid, the pipeline with the country one-hot and no native
categorical splits, the selection on V1 with its tie to the simplest, the calibration on V1 only and the refusals before anything is fitted.
The trainings here use a quick grid (3 candidates, 50 iterations): what they prove does not depend on its size."""

from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd
import pytest

from churnrisk import model as model_module
from churnrisk.config import SealedConfig
from churnrisk.features import OTHERS, LeakageError, build_matrix, country_groups
from churnrisk.model import Candidate, candidates, make_pipeline, predict_risk, select, train_model
from churnrisk.schema import FEATURE_COLUMNS
from churnrisk.split import BlockLabelError

SHA = "a" * 64


@pytest.fixture(scope="module")
def quick(cfg) -> SealedConfig:
    view = SealedConfig.of(cfg, SHA)
    return dataclasses.replace(view, model=dataclasses.replace(view.model, learning_rate=(0.1,), max_leaf_nodes=(15,), min_samples_leaf=(20,), max_iter=50))


def flipped(frame: pd.DataFrame, blocks: tuple[str, ...]) -> pd.DataFrame:
    out = frame.copy()
    rows = out["block"].isin(blocks)
    out.loc[rows, "churned"] = 1 - out.loc[rows, "churned"]
    return out


def test_the_grid_is_three_sets_by_eight_configurations_in_a_fixed_order(cfg):
    grid = candidates(SealedConfig.of(cfg, SHA))
    assert len(grid) == 24 and len(set(grid)) == 24
    assert grid[0] == Candidate("f0", 0.05, 15, 50) and grid[1] == Candidate("f0", 0.05, 15, 200) and grid[-1] == Candidate("f2", 0.1, 31, 200)
    assert [c.feature_set for c in grid] == ["f0"] * 8 + ["f1"] * 8 + ["f2"] * 8
    assert sorted(grid, key=Candidate.simplicity)[0] == Candidate("f0", 0.05, 15, 200), "fewer leaves, then more samples per leaf, then the lower rate"


def test_the_pipeline_one_hots_the_launch_groups_without_native_categorical_splits(cfg, launch_model):
    """[Verificar en U13]: a country outside the launch's groups is mapped to «Otros» by build_matrix; one that reaches the encoder unmapped
    is an error, never a row of zeros."""
    labelled, _trained = launch_model("rfm_only")
    view = SealedConfig.of(cfg, SHA)
    train = labelled[labelled["block"] == "train"]
    groups = country_groups(train, view.features.country_min_customers)
    x = build_matrix(train[list(FEATURE_COLUMNS)], "f2", groups)
    pipeline = make_pipeline(Candidate("f2", 0.1, 15, 20), dataclasses.replace(view, model=dataclasses.replace(view.model, max_iter=20)), groups)
    pipeline.fit(x, train["churned"].to_numpy())
    classifier = pipeline.named_steps["classifier"]
    assert classifier.categorical_features is None and not np.any(classifier.is_categorical_ if classifier.is_categorical_ is not None else False)
    names = list(pipeline.named_steps["prep"].get_feature_names_out())
    assert names == [*FEATURE_COLUMNS[:-1], *(f"country_group_{g}" for g in groups)] and OTHERS in groups
    new_country = train[list(FEATURE_COLUMNS)].head(3).assign(country_group=["Atlantis", "Unspecified", groups[0]])
    mapped = build_matrix(new_country, "f2", groups)
    assert mapped["country_group"].tolist() == [OTHERS, OTHERS, groups[0]]
    assert np.isfinite(pipeline.predict_proba(mapped)[:, 1]).all()
    with pytest.raises(ValueError, match="unknown categor"):
        pipeline.predict_proba(new_country)
    without = make_pipeline(Candidate("f1", 0.1, 15, 20), view, groups)
    assert [name for name, _t, _c in without.named_steps["prep"].transformers] == ["numeric"]


class Fixed:
    """A fitted candidate that answers a given probability: the selection only reads ``predict_proba`` on V1."""

    def __init__(self, p) -> None:
        self.p = np.asarray(p, dtype=float)

    def predict_proba(self, _x):
        return np.column_stack([1 - self.p, self.p])


def test_select_takes_the_lowest_v1_log_loss_and_a_tie_to_1e_6_goes_to_the_simplest():
    y = np.array([0, 1, 0, 1, 1, 0])
    good, better = [0.3, 0.7, 0.3, 0.7, 0.7, 0.3], [0.2, 0.8, 0.2, 0.8, 0.8, 0.2]
    x = {"f0": pd.DataFrame(index=range(6)), "f1": pd.DataFrame(index=range(6)), "f2": pd.DataFrame(index=range(6))}
    a, b, c = Candidate("f2", 0.1, 31, 50), Candidate("f1", 0.05, 15, 200), Candidate("f0", 0.1, 15, 50)
    assert select([(a, Fixed(better)), (b, Fixed(good))], x, y).chosen == a, "a lower loss wins over a simpler candidate"
    tie = select([(a, Fixed(better)), (c, Fixed(np.asarray(better) + 1e-9)), (b, Fixed(better))], x, y)
    assert tie.chosen == c and len(tie.losses) == 3, "within 1e-6, the smaller set"
    assert select([(Candidate("f1", 0.1, 31, 50), Fixed(good)), (Candidate("f1", 0.1, 15, 200), Fixed(good))], x, y).chosen == Candidate("f1", 0.1, 15, 200)
    assert tie.log_loss_v1 == dict(tie.losses)[c] and 0 < tie.auc_v1 <= 1
    with pytest.raises(BlockLabelError, match="M07"):
        select([(a, Fixed(better))], x, np.zeros(6, dtype=int))


@pytest.mark.parametrize("block", ["train", "valid_v1", "valid_v2"])
def test_m07_a_block_of_one_class_stops_the_launch_before_anything_is_fitted(block, launch_model, quick, monkeypatch):
    labelled, _trained = launch_model("rfm_only")
    one_class = labelled.assign(churned=np.where(labelled["block"] == block, 1, labelled["churned"]))

    def never(*_args, **_kwargs):
        raise AssertionError("a candidate was fitted")

    monkeypatch.setattr(model_module, "fit_candidates", never)
    monkeypatch.setattr(model_module, "build_matrix", never)
    with pytest.raises(BlockLabelError, match=f"M07.*{block}"):
        train_model(one_class, quick)


def test_the_calibration_and_the_choice_learn_from_training_and_v1_only(launch_model, quick):
    """AC17: V2's labels (and any other block's) never reach the model, its calibration or its country groups; V1's do (the control).
    Every probability is finite and in [0, 1] (M04)."""
    labelled, _trained = launch_model("rfm_only")
    base = train_model(labelled, quick)
    x = build_matrix(labelled[list(FEATURE_COLUMNS)], base.model.feature_set, base.model.country_groups)
    risk = predict_risk(base.model, x)
    assert np.isfinite(risk).all() and ((risk >= 0) & (risk <= 1)).all()
    v1 = (labelled["block"] == "valid_v1").to_numpy()
    assert risk[v1].mean() == pytest.approx(labelled.loc[v1, "churned"].mean(), abs=1e-9), "isotonic regression keeps the mean of the block it is fitted on: V1"
    others = flipped(labelled, ("valid_v2", "purge_1")).assign(country_group=lambda f: np.where(f["block"] == "valid_v2", "Atlantis", f["country_group"]))
    again = train_model(others, quick)
    assert again.selection.losses == base.selection.losses and again.model.country_groups == base.model.country_groups
    np.testing.assert_array_equal(predict_risk(again.model, x), risk)
    assert (again.valid_v2["churned"] == 1 - base.valid_v2["churned"]).all(), "V2 is only measured"
    changed = train_model(flipped(labelled, ("valid_v1",)), quick)
    x_changed = build_matrix(labelled[list(FEATURE_COLUMNS)], changed.model.feature_set, changed.model.country_groups)
    assert not np.array_equal(predict_risk(changed.model, x_changed), risk), "control: V1 does reach the choice and the calibration"
    assert base.model.country_groups == country_groups(labelled[labelled["block"] == "train"], quick.features.country_min_customers)
    assert base.rows == {name: int((labelled["block"] == name).sum()) for name in ("train", "valid_v1", "valid_v2")}


def test_m02_and_m04_refuse_a_wrong_matrix_and_a_probability_out_of_range(launch_model, quick, monkeypatch):
    labelled, _trained = launch_model("rfm_only")
    trained = train_model(labelled, quick)
    x = build_matrix(labelled[list(FEATURE_COLUMNS)], trained.model.feature_set, trained.model.country_groups).head(5)
    with pytest.raises(LeakageError, match="M02"):
        predict_risk(trained.model, x[list(reversed(x.columns))])
    for bad in (np.nan, 1.5, -0.1):
        monkeypatch.setattr(type(trained.model.calibrated), "predict_proba", lambda self, _x, v=bad: np.column_stack([np.full(5, 0.5), np.r_[0.2, v, 0.2, 0.2, 0.2]]))
        with pytest.raises(ValueError, match="M04.*posición 1"):
            predict_risk(trained.model, x)
