"""The baselines B0-B5, their probabilities and the strongest of them (U12, AC15, AC17, AC20; RF15, RF16; D14, D16, D17, M07).

Every score is a rule of the features known before the cut, with the BG/NBD parameters fitted on the history before ``bgnbd_fit_cut``:
no score reads a label. The calibrators learn from V1 only; B* is chosen on the validation (V1 and V2) only, with a tie to 1e-6 going to
the simplest of ``strongest_candidates``."""

from __future__ import annotations

import dataclasses
from datetime import date

import numpy as np
import pandas as pd
import pytest

from churnrisk.baselines import (
    METHODS,
    SCORED,
    baseline_scores,
    fit_baselines,
    fit_calibrators,
    probabilities,
    rfm_scores,
    strongest,
)
from churnrisk.bgnbd import BGNBDParams, expected_purchases, fit_at_cut, fit_in_warehouse, p_alive, summary_from_features
from churnrisk.config import SealedConfig
from churnrisk.deliveries import delivery_plan, delivery_rows
from churnrisk.features import FEATURE_COLUMNS, known_before
from churnrisk.netting import netting_inputs
from churnrisk.split import BlockLabelError
from churnrisk.netting import customer_days, net_cancellations
from churnrisk.warehouse import connect, load_delivery
from tests.fixtures import hand_cases
from tests.fixtures.perturb import perturbed

SHA = "e" * 64
PARAMS = BGNBDParams(r=0.9091, alpha=75.83, a=0.1717, b=105.91)   # what the planner fitted on the real training history (requirements, 4)
CUTS = {date(2010, 11, 1): "train", date(2010, 12, 1): "train", date(2011, 3, 1): "valid_v1", date(2011, 4, 1): "valid_v1",
        date(2011, 5, 1): "valid_v2", date(2011, 8, 1): "test"}


def labelled_frame(rows_per_cut: int = 60, seed: int = 0) -> pd.DataFrame:
    """Labelled rows as ``split.labelled_rows`` gives them, with consistent histories and labels that follow the frequency."""
    rng = np.random.default_rng(seed)
    parts = []
    for cut, block in CUTS.items():
        n = rows_per_cut
        freq = rng.integers(1, 15, n)
        rec = rng.integers(1, 90, n)
        tenure = rec + np.where(freq > 1, rng.integers(20, 400, n), 0)
        data = {name: rng.random(n) * 100 for name in FEATURE_COLUMNS if name != "country_group"}
        data.update(rec_days=rec, tenure_days=tenure, freq_total=freq, freq_365=np.minimum(freq, rng.integers(1, 15, n)), country_group="France")
        churned = (rng.random(n) < 1 / (1 + np.exp(0.5 * (freq - 5)))).astype("int64")
        index = pd.MultiIndex.from_arrays([[cut] * n, 90_001 + np.arange(n)], names=["cut_date", "customer_id"])
        parts.append(pd.DataFrame(data, index=index)[list(FEATURE_COLUMNS)].assign(block=block, churned=churned))
    frame = pd.concat(parts)
    return frame[["block", "churned", *FEATURE_COLUMNS]].astype({name: "int64" for name in ("rec_days", "tenure_days", "freq_total", "freq_365")})


def flipped(frame: pd.DataFrame, blocks: tuple[str, ...]) -> pd.DataFrame:
    out = frame.copy()
    rows = out["block"].isin(blocks)
    out.loc[rows, "churned"] = 1 - out.loc[rows, "churned"]
    return out


def predictions(calibrators: dict, grid: np.ndarray) -> dict[str, np.ndarray]:
    return {method: calibrator.predict(grid) for method, calibrator in calibrators.items()}


# --- the RED of U12 -------------------------------------------------------------------------------------------------------


def test_rfm_quintiles_hand_case_and_no_parameter_reads_validation_or_test_labels(cfg):
    """hand_cases.rfm_case: the quintiles by average rank of project 02 (D09), inside each cut. Then, with the labels of the validation
    and of the test turned over, every score of B1-B5 stays the same: they are rules of the features and of the BG/NBD parameters."""
    frame, expected = hand_cases.rfm_case()
    features = frame.set_index(pd.MultiIndex.from_arrays([[date(2011, 3, 1)] * len(frame), frame["customer_id"]], names=["cut_date", "customer_id"]))
    got = rfm_scores(features[["rec_days", "freq_365", "mon_365"]])
    assert got["rfm_score"].droplevel("cut_date").to_dict() == expected
    assert got.loc[(date(2011, 3, 1), 1), ["r_score", "f_score", "m_score"]].tolist() == [5, 5, 5]
    assert got.loc[(date(2011, 3, 1), 3), ["r_score", "f_score", "m_score"]].tolist() == [3, 3, 4]
    # the quintiles are cut inside each cut: the same six customers next to six others in another cut keep their scores
    other = features.rename(index={date(2011, 3, 1): date(2011, 4, 1)}).assign(rec_days=features["rec_days"].to_numpy() * 9)
    both = rfm_scores(pd.concat([features, other])[["rec_days", "freq_365", "mon_365"]])
    assert both.xs(date(2011, 3, 1), level="cut_date")["rfm_score"].to_dict() == expected
    view = SealedConfig.of(cfg, SHA)
    labelled = labelled_frame()
    base = fit_baselines(labelled, PARAMS, view)
    assert base.scores.loc[(date(2011, 3, 1), 90_001), "b2_rfm"] == -rfm_scores(labelled[list(FEATURE_COLUMNS)]).loc[(date(2011, 3, 1), 90_001), "rfm_score"]
    for blocks in (("valid_v1", "valid_v2", "test"), ("valid_v2", "test"), ("test",), ("train",)):
        again = fit_baselines(flipped(labelled, blocks), PARAMS, view)
        pd.testing.assert_frame_equal(again.scores, base.scores, check_exact=True, obj=f"scores with {blocks} turned over")


def test_bgnbd_parameters_equal_with_history_truncated_at_the_fit_cut(cfg, canonical, loaded_masters):
    """Fitted in a warehouse that holds the whole history, BG/NBD sees only the purchase days before bgnbd_fit_cut, netted with what is
    known the day before: the same parameters, to the last bit, as from the canonical lines truncated there (AC13, AC15)."""
    frame, _report = canonical
    view = SealedConfig.of(cfg, SHA)
    conn = connect(loaded_masters(len(delivery_plan(cfg)))[0])
    try:
        everything = fit_in_warehouse(conn, view)
    finally:
        conn.close()
    cut = view.baselines.bgnbd_fit_cut
    purchases, cancellations = netting_inputs(frame[frame["invoice_date"] < pd.Timestamp(cut)].reset_index(drop=True))
    history = known_before(purchases, cancellations, cut)[0]
    truncated = fit_at_cut(history, cut, view.baselines.bgnbd_max_iter)
    assert (everything.params, everything.log_likelihood, everything.n) == (truncated.params, truncated.log_likelihood, truncated.n)
    assert everything.converged and everything.n == history["customer_id"].nunique(), "every customer with a purchase day before the cut"


def test_lines_from_the_fit_cut_on_change_no_bgnbd_parameter(cfg, canonical, loaded_masters, tmp_path):
    """Lines and cancellations deleted, changed or added from bgnbd_fit_cut on, among them a cancellation on that day of everything a
    customer bought of a product before it: the parameters are the same, to the last bit; netted with what is known on the cut itself
    they would not be (the control)."""
    frame, _report = canonical
    view = SealedConfig.of(cfg, SHA)
    cut = view.baselines.bgnbd_fit_cut
    launch = delivery_plan(cfg)[0]
    conn = connect(loaded_masters(1)[0])
    try:
        base = fit_in_warehouse(conn, view)
    finally:
        conn.close()
    lines = delivery_rows(launch, frame)
    buyers = sorted(lines.loc[(lines["invoice_date"] < pd.Timestamp(cut)) & lines["customer_id"].notna(), "customer_id"].astype(int).unique())[:40]
    changed = perturbed(lines, cut, buyers)
    conn = connect(tmp_path / "perturbed.sqlite")
    try:
        load_delivery(conn, changed, launch, "p1", sha256="f" * 64)
        again = fit_in_warehouse(conn, view)
    finally:
        conn.close()
    assert (again.params, again.log_likelihood, again.n) == (base.params, base.log_likelihood, base.n)
    purchases, cancellations = netting_inputs(changed[changed["invoice_date"] <= pd.Timestamp(cut)].reset_index(drop=True))
    days = customer_days(net_cancellations(purchases, cancellations, cut).net_lines)
    leaked = fit_at_cut(days[days["day"] < pd.Timestamp(cut)], cut, view.baselines.bgnbd_max_iter)
    assert leaked.params != base.params, "control: the cancellations of the cut day would change the fit if they were known"


# --- the scores, the calibrators and B* -----------------------------------------------------------------------------------


def test_each_baseline_score_is_its_rule(cfg):
    labelled = labelled_frame()
    features = labelled[list(FEATURE_COLUMNS)]
    scores = baseline_scores(features, PARAMS, 90)
    assert tuple(scores.columns) == METHODS and scores.index.equals(features.index)
    summary = summary_from_features(features)
    x, t_x, T = (summary[c].to_numpy(float) for c in ("x", "t_x", "T"))
    np.testing.assert_array_equal(scores["b0_all"], 1.0)
    np.testing.assert_array_equal(scores["b1_recency"], features["rec_days"].astype(float))
    np.testing.assert_array_equal(scores["b2_rfm"], -rfm_scores(features)["rfm_score"].astype(float))
    np.testing.assert_allclose(scores["b3_bgnbd"], -expected_purchases(PARAMS, 90, x, t_x, T), rtol=0, atol=0)
    np.testing.assert_array_equal(scores["b4_frequency"], -features["freq_365"].astype(float))
    np.testing.assert_allclose(scores["b5_alive"], 1 - p_alive(PARAMS, x, t_x, T), rtol=0, atol=0)
    longer = baseline_scores(features, PARAMS, 120)
    assert (longer["b3_bgnbd"] < scores["b3_bgnbd"]).all(), "B3 counts the purchases expected over the label's N days"


def test_the_calibrators_learn_from_v1_only_and_give_probabilities(cfg):
    labelled = labelled_frame()
    scores = baseline_scores(labelled[list(FEATURE_COLUMNS)], PARAMS, 90)
    grid = np.linspace(-20, 100, 400)
    base = predictions(fit_calibrators(scores, labelled), grid)
    assert set(base) == set(SCORED)
    for blocks in (("valid_v2", "test", "train"),):
        again = predictions(fit_calibrators(scores, flipped(labelled, blocks)), grid)
        assert all(np.array_equal(again[m], base[m]) for m in SCORED), "nothing outside V1 reaches a calibrator"
    other_scores = scores.copy()
    other_scores.loc[labelled["block"] != "valid_v1"] = other_scores.loc[labelled["block"] != "valid_v1"] * 3 + 1
    assert all(np.array_equal(predictions(fit_calibrators(other_scores, labelled), grid)[m], base[m]) for m in SCORED)
    changed = predictions(fit_calibrators(scores, flipped(labelled, ("valid_v1",))), grid)
    assert any(not np.array_equal(changed[m], base[m]) for m in SCORED), "control: V1's labels do reach them"
    p = probabilities(fit_calibrators(scores, labelled), scores)
    assert tuple(p.columns) == SCORED and np.isfinite(p.to_numpy()).all() and ((p >= 0) & (p <= 1)).all().all()
    increasing = probabilities(fit_calibrators(scores, labelled), scores.sort_values("b4_frequency"))["b4_frequency"].to_numpy()
    assert (np.diff(increasing) >= 0).all() and increasing[-1] > increasing[0], "a higher risk score never gets a lower probability"


def test_the_strongest_baseline_is_chosen_on_validation_only_with_ties_to_the_simplest(cfg):
    labelled = labelled_frame()
    scores = baseline_scores(labelled[list(FEATURE_COLUMNS)], PARAMS, 90)
    candidates = SealedConfig.of(cfg, SHA).baselines.strongest_candidates
    name, aucs = strongest(scores, labelled, candidates)
    assert set(aucs) == set(candidates) and aucs[name] == max(aucs.values())
    # the test and the training never decide it (AC20); both validation blocks do
    assert strongest(scores, flipped(labelled, ("test", "train")), candidates) == (name, aucs)
    for block in ("valid_v1", "valid_v2"):
        assert strongest(scores, flipped(labelled, (block,)), candidates)[1] != aucs, f"{block} is part of the validation"
    # a tie to 1e-6 goes to the first of the list: B4 and B2 given the same ranking
    tied = scores.assign(b2_rfm=scores["b4_frequency"] * 2, b3_bgnbd=scores["b4_frequency"] - 1e-3 * (labelled["churned"] == 0))
    assert strongest(tied, labelled, ("b4_frequency", "b2_rfm"))[0] == "b4_frequency"
    assert strongest(tied, labelled, ("b2_rfm", "b4_frequency"))[0] == "b2_rfm"
    assert strongest(tied, labelled, ("b4_frequency", "b2_rfm", "b3_bgnbd"))[0] == "b3_bgnbd", "a better AUC beyond 1e-6 wins over a simpler rule"
    baselines = fit_baselines(labelled, PARAMS, SealedConfig.of(cfg, SHA))
    assert (baselines.b_star, baselines.auc_validation) == (name, aucs)


def test_an_auc_better_by_less_than_1e_6_is_a_tie_that_the_simpler_rule_wins():
    """With 1,500 churners and 1,500 others one pair is worth 1 / 2,250,000 of AUC: B2 ranks one pair better than B4, by 4.4e-7."""
    rng = np.random.default_rng(5)
    y = rng.permutation(np.repeat([0, 1], 1500))
    b4 = np.arange(3000, dtype=float)
    low = next(k for k in range(2999) if y[k] == 1 and y[k + 1] == 0)          # a churner ranked just below a customer who stayed
    b2 = b4.copy()
    b2[[low, low + 1]] = b2[[low + 1, low]]
    index = pd.MultiIndex.from_arrays([[date(2011, 3, 1)] * 3000, np.arange(3000)], names=["cut_date", "customer_id"])
    labelled = pd.DataFrame({"block": "valid_v1", "churned": y}, index=index)
    scores = pd.DataFrame({"b4_frequency": b4, "b2_rfm": b2}, index=index)
    name, aucs = strongest(scores, labelled, ("b4_frequency", "b2_rfm"))
    assert aucs["b2_rfm"] - aucs["b4_frequency"] == pytest.approx(1 / 2_250_000, rel=1e-6) and name == "b4_frequency"
    assert strongest(scores.assign(b2_rfm=b2 + np.where(y == 1, 100.0, 0.0)), labelled, ("b4_frequency", "b2_rfm"))[0] == "b2_rfm"


def test_a_block_with_one_class_is_refused_before_calibrating_or_choosing(cfg):
    labelled = labelled_frame()
    scores = baseline_scores(labelled[list(FEATURE_COLUMNS)], PARAMS, 90)
    one_class = labelled.assign(churned=np.where(labelled["block"] == "valid_v1", 0, labelled["churned"]))
    with pytest.raises(BlockLabelError, match="M07.*valid_v1"):
        fit_calibrators(scores, one_class)
    no_validation = labelled.assign(churned=np.where(labelled["block"].isin(["valid_v1", "valid_v2"]), 1, labelled["churned"]))
    with pytest.raises(BlockLabelError, match="M07"):
        strongest(scores, no_validation, ("b4_frequency",))
    with pytest.raises(BlockLabelError, match="M07"):
        fit_calibrators(scores, labelled[labelled["block"] != "valid_v1"])
    view = SealedConfig.of(cfg, SHA)
    with pytest.raises(ValueError, match="b9"):
        strongest(scores, labelled, ("b9_unknown",))
    assert dataclasses.is_dataclass(fit_baselines(labelled, PARAMS, view))


def test_scores_that_are_not_finite_are_refused_before_any_calibrator_or_b_star(cfg, monkeypatch):
    """R3-fit-baselines-finite-check-ordering: a score that is not finite stops ``fit_baselines`` before anything learns from it."""
    from churnrisk import baselines

    labelled = labelled_frame()
    real = baselines.baseline_scores

    def with_inf(*args, **kwargs):
        scores = real(*args, **kwargs)
        scores.iloc[0, 0] = np.inf
        return scores

    learned = []
    monkeypatch.setattr(baselines, "baseline_scores", with_inf)
    monkeypatch.setattr(baselines, "fit_calibrators", lambda *a, **k: learned.append("calibrators"))
    monkeypatch.setattr(baselines, "strongest", lambda *a, **k: learned.append("strongest"))
    with pytest.raises(ValueError, match="no son finitos"):
        fit_baselines(labelled, PARAMS, SealedConfig.of(cfg, SHA))
    assert learned == []
