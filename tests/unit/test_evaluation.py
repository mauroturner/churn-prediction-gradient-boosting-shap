"""The evaluation's measures, the bootstrap by customer and the criteria (U17, AC25; D18, D21; requirements, section 8.1)."""

from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd
import pytest
from sklearn.metrics import roc_auc_score

from churnrisk.evaluation import (
    BlockData,
    _criteria_of,
    calibration_table,
    cluster_bootstrap,
    evaluate_frame,
    method_metrics,
    roc_table,
)
from churnrisk.registry import sealed_document, sealed_view
from churnrisk.split import BlockLabelError
from churnrisk.threshold import Costs
from tests.fixtures.hand_cases import METRICS_EXPECTED, METRICS_P, METRICS_Y, bootstrap_case, losing_metrics

SHA = "a" * 64


# --- the RED of U17 ------------------------------------------------------------------------------------------------------


def test_ten_row_hand_case():
    """hand_cases: AUC with ties by halves, PR-AUC, Brier, ECE of ten equal bins, bias, capture and lift of the top 10 % and 20 % and the net
    benefit of contacting p >= 0.5 with the default costs, each written by hand."""
    y, p = np.asarray(METRICS_Y), np.asarray(METRICS_P)
    got = method_metrics(y, p, p, p >= 0.5, Costs(5.0, 0.2, 50.0), np.asarray(["2011-08-01"] * 10), threshold=0.5, bins=10, shares=(0.10, 0.20))
    e = METRICS_EXPECTED
    for key in ("auc", "pr_auc", "brier", "bias", "ece"):
        assert got[key] == pytest.approx(e[key], abs=1e-12), key
    assert (got["mean_p"], got["churn_rate"]) == (pytest.approx(e["mean_p"]), pytest.approx(e["rate"]))
    assert (got["captured_10"], got["lift_10"], got["captured_20"], got["lift_20"]) == (e["captured_10"], e["lift_10"], e["captured_20"], e["lift_20"])
    assert got["capture_10"] == pytest.approx(0.25)
    assert got["nb_total"] == pytest.approx(e["net_benefit_at_0_5"]) and got["nb_per_1000"] == pytest.approx(500.0)
    assert (got["contact_share"], got["precision"], got["recall"], got["threshold"], got["rows"]) == (0.5, 0.6, 0.75, 0.5, 10.0)
    table = calibration_table(p, y, 10)
    assert table["rows"].tolist() == [0, 1, 2, 1, 1, 1, 1, 1, 1, 1] and table.loc[2, "observed"] == 0.0 and pd.isna(table.loc[0, "p_mean"])
    roc = roc_table(y, p, 5)
    # the churner with the top score comes before any other customer: at a false positive rate of 0 a quarter of the churners is found
    assert roc["fpr"].tolist() == [0.0, 0.25, 0.5, 0.75, 1.0] and roc["tpr"].tolist()[0] == 0.25 and roc["tpr"].iloc[-1] == 1.0
    fine = roc_table(y, p, 6001)
    assert np.trapezoid(fine["tpr"], fine["fpr"]) == pytest.approx(19 / 24, abs=1e-3), "the area under the curve is the AUC"


def by_hand(case: pd.DataFrame, n: int, seed: int, unit: str) -> tuple[list[float], int]:
    """The resamples drawn with numpy's generator, by whole customers (``unit="customer"``) or by rows: the reference of the test."""
    rng = np.random.default_rng(seed)
    y, a, b = case["churned"].to_numpy(), case["score_a"].to_numpy(), case["score_b"].to_numpy()
    if unit == "customer":
        ids = np.unique(case["customer_id"])
        groups = [np.flatnonzero(case["customer_id"].to_numpy() == c) for c in ids]
    else:
        groups = [np.array([i]) for i in range(len(case))]
    diffs, discarded = [], 0
    for _ in range(n):
        rows = np.concatenate([groups[g] for g in rng.integers(0, len(groups), len(groups))])
        if y[rows].min() == y[rows].max():
            discarded += 1
            continue
        diffs.append(roc_auc_score(y[rows], a[rows]) - roc_auc_score(y[rows], b[rows]))
    return diffs, discarded


def test_bootstrap_resamples_whole_customers_and_is_seeded():
    """D21: each draw takes a customer with all its rows (the three customers in both test cuts bring both), the same customers for both
    scores; a draw with one class is discarded and counted; the same seed gives the same interval and another seed another one."""
    case = bootstrap_case()
    args = (case["churned"], case["score_a"], case["score_b"], case["customer_id"])
    got = cluster_bootstrap(*args, 300, 0)
    diffs, discarded = by_hand(case, 300, 0, "customer")
    assert (got.kept, got.discarded) == (len(diffs), discarded) and discarded > 0
    assert (got.ci_low, got.ci_high) == tuple(np.percentile(diffs, [2.5, 97.5]))
    assert got.diff == pytest.approx(roc_auc_score(case["churned"], case["score_a"]) - roc_auc_score(case["churned"], case["score_b"]))
    assert cluster_bootstrap(*args, 300, 0) == got, "the same seed, the same interval"
    assert cluster_bootstrap(*args, 300, 1) != got
    by_rows, _ = by_hand(case, 300, 0, "rows")
    assert (got.ci_low, got.ci_high) != tuple(np.percentile(by_rows, [2.5, 97.5])), "resampling rows is another interval"


def test_a_block_with_one_class_is_its_own_error_before_any_fit(cfg):
    """M07 (project 03, D65): a block whose labels are of one class gives no AUC; the evaluation refuses it by name before measuring anything."""
    view = sealed_view(cfg, SHA)
    index = pd.MultiIndex.from_tuples([(pd.Timestamp("2011-08-01").date(), c) for c in range(1, 5)], names=["cut_date", "customer_id"])
    frame = pd.DataFrame({"churned": [1, 1, 1, 1], "model": [0.9, 0.8, 0.7, 0.6]}, index=index)
    with pytest.raises(BlockLabelError, match="M07: el bloque test tiene una sola clase"):
        evaluate_frame(BlockData("test", frame, "b2_rfm"), BlockData("valid_v2", frame, "b2_rfm"), 0.5, view)
    with pytest.raises(BlockLabelError, match="M07"):
        cluster_bootstrap([0, 0, 0], [0.1, 0.2, 0.3], [0.3, 0.2, 0.1], [1, 2, 3], 10, 0)


# --- the criteria and their verdicts ---------------------------------------------------------------------------------------


def test_each_verdict_says_its_number_and_a_tie_never_passes(cfg):
    document = sealed_document(sealed_view(cfg, SHA))
    per_cut = [{"cut": "2011-08-01", "rows": 900, "churn_rate": 0.3, "auc_model": 0.77, "diff_b2_rfm": -0.01, "diff_b_star": -0.01}]
    criteria = {c.criterion_id: c for c in _criteria_of(losing_metrics(), per_cut, document["costs"], document["criteria"])}
    assert list(criteria) == [f"C{i:02d}" for i in range(1, 11)]
    assert [cid for cid, c in criteria.items() if c.passed] == ["C06"], "it only beats contacting everyone and nobody"
    assert criteria["C01"].verdict_es == "El modelo no supera a RFM en AUC: 0,769 frente a 0,784."
    assert criteria["C02"].verdict_es == "El modelo no supera a RFM fuera del ruido: la diferencia de AUC es −0,01, con un intervalo del 95 % de −0,03 a 0,01."
    assert (criteria["C02"].value, criteria["C02"].ci_low, criteria["C02"].ci_high) == (-0.015, -0.033, 0.005)
    assert "900,0 u. frente a 950,0 u." in criteria["C05"].verdict_es and "900,0 u. por cada 1.000 clientes frente a 0,0" in criteria["C06"].verdict_es
    assert criteria["C07"].verdict_es == "La calibración en la prueba no cumple: ECE 0,050 y sesgo 0,030." and criteria["C07"].threshold_es == "ECE ≤ 0,03 y |sesgo| ≤ 0,02"
    assert criteria["C09"].verdict_es.endswith("en 1 de los 17 de 0,10 a 0,90.") and criteria["C09"].passed is False
    assert criteria["C10"].passed is None and "2011-08-01: AUC 0,770" in criteria["C10"].verdict_es
    tied = losing_metrics()
    tied["model"]["auc"] = tied["b2_rfm"]["auc"]
    assert not {c.criterion_id: c for c in _criteria_of(tied, per_cut, document["costs"], document["criteria"])}["C01"].passed
    wider = dict(document["costs"], sensitivity_max=0.95)
    c09 = {c.criterion_id: c for c in _criteria_of(losing_metrics(), per_cut, wider, document["criteria"])}["C09"]
    assert c09.passed is False and "faltan los puntos de equilibrio 0.95" in c09.verdict_es, "the range of C09 comes from the sealed view"
    biased = losing_metrics()
    biased["model"].update(ece=0.02, bias=-0.03)            # calibrated by bins, but the mean risk is 3 points below the observed rate
    assert {c.criterion_id: c.passed for c in _criteria_of(biased, per_cut, document["costs"], document["criteria"])}["C07"] is False
    biased["model"].update(bias=-0.02)
    assert {c.criterion_id: c.passed for c in _criteria_of(biased, per_cut, document["costs"], document["criteria"])}["C07"] is True, "the limits are included"
    winning = losing_metrics()
    winning["bootstrap"] = {k: (0.02 if k.endswith("ci_low") else v) for k, v in winning["bootstrap"].items()}
    assert {c.criterion_id: c.passed for c in _criteria_of(winning, per_cut, document["costs"], document["criteria"])}["C02"] is True


def test_the_baselines_thresholds_come_from_v2_and_b_star_is_a_copy_of_its_method(cfg):
    """C05 and C09 compare the model with B* at the threshold B* chooses on V2 with its own calibrated probability."""
    view = dataclasses.replace(sealed_view(cfg, SHA), evaluation=dataclasses.replace(sealed_view(cfg, SHA).evaluation, bootstrap_resamples=20))
    rng = np.random.default_rng(3)
    n = 200
    index = pd.MultiIndex.from_tuples([(pd.Timestamp("2011-08-01").date(), c) for c in range(n)], names=["cut_date", "customer_id"])
    y = rng.integers(0, 2, n)
    frame = pd.DataFrame({"churned": y, "model": np.clip(y * 0.3 + rng.random(n) * 0.7, 0, 1)}, index=index)
    for m in ("b0_all", "b1_recency", "b2_rfm", "b3_bgnbd", "b4_frequency", "b5_alive"):
        frame[f"score_{m}"] = rng.random(n)
        if m != "b0_all":
            frame[f"p_{m}"] = np.clip(y * 0.2 + rng.random(n) * 0.8, 0, 1)
    v2 = BlockData("valid_v2", frame, "b4_frequency")
    result = evaluate_frame(BlockData("test", frame, "b4_frequency"), v2, 0.5, view)
    from churnrisk.threshold import choose_on_v2, threshold_grid

    assert result.thresholds["b4_frequency"] == choose_on_v2(frame.assign(block="valid_v2"), Costs.from_view(view), threshold_grid(view.costs),
                                                              score="p_b4_frequency").threshold
    assert result.metrics["b_star"] == result.metrics["b4_frequency"] and result.metrics["model"]["threshold"] == 0.5
    assert set(result.sensitivity["scope"]) == {"valid_v2", "test"} and len(result.sensitivity) == 17 * 2 * 2


def test_the_leakage_demo_never_writes_the_registry_or_the_scores():
    """D41 (project 03, D31): the module that adds the control past the guards on purpose writes nothing anywhere; the task stores its table."""
    from pathlib import Path

    text = (Path(__file__).resolve().parents[2] / "src" / "churnrisk" / "leakage_demo.py").read_text(encoding="utf-8")
    for word in ("model_registry", "model_scores", "score_reasons", "INSERT", "UPDATE", "DELETE", "write_atomic", "save_artifact"):
        assert word not in text, word

