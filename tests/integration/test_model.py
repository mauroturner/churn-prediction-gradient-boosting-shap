"""The model of the launch on the synthetic fixture (U13, AC14, AC16; RF17; D12-D14, D41, D42, D49, M01).

The controls of D42 are compared on **V2**, the validation cut that neither fits, selects nor calibrates the model (it only chooses the
threshold): with a signal that RFM does not see (``irregular_gaps``), the lower end of the 95 % interval of AUC(model) - AUC(B2) is above
0; with churn that depends only on what RFM sees (``rfm_only``), the interval holds 0. The interval resamples customers (D21); V2 is one cut,
so each customer has one row. A variable that looks at the label window, forced past the guards under an allowed name, trips M01 and stops
the launch."""

from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd
import pytest
from scipy.stats import rankdata

from churnrisk.baselines import rfm_scores
from churnrisk.config import SealedConfig
from churnrisk.features import LeakageError, build_matrix
from churnrisk.model import predict_risk, train_model
from churnrisk.netting import customer_days, known_netting_inputs, net_cancellations
from churnrisk.schema import FEATURE_COLUMNS
from churnrisk.warehouse import connect

SHA = "a" * 64


def auc(y: np.ndarray, score: np.ndarray) -> float:
    """The AUC by ranks, ties counted by halves (the Mann-Whitney statistic)."""
    ranks = rankdata(score)
    positives = y == 1
    n1, n0 = int(positives.sum()), int((~positives).sum())
    return float((ranks[positives].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def paired_customer_bootstrap(y, a, b, customers, resamples: int = 1000, seed: int = 0) -> tuple[float, float, float]:
    """``(low, high, difference)`` of AUC(a) - AUC(b): 2.5 and 97.5 percentiles over `resamples` draws of whole customers with replacement,
    the same customers for both scores; a draw with one class is discarded (D21). The evaluation's own bootstrap is U17's."""
    y, a, b, customers = (np.asarray(v) for v in (y, a, b, customers))
    groups = [np.flatnonzero(customers == c) for c in np.unique(customers)]
    rng = np.random.default_rng(seed)
    diffs = []
    for _ in range(resamples):
        rows = np.concatenate([groups[i] for i in rng.integers(0, len(groups), len(groups))])
        if y[rows].min() == y[rows].max():
            continue
        diffs.append(auc(y[rows], a[rows]) - auc(y[rows], b[rows]))
    low, high = np.percentile(diffs, [2.5, 97.5])
    return float(low), float(high), auc(y, a) - auc(y, b)


def against_rfm_on_v2(labelled: pd.DataFrame, trained) -> tuple[float, float, float]:
    v2 = labelled[labelled["block"] == "valid_v2"]
    features = v2[list(FEATURE_COLUMNS)]
    risk = predict_risk(trained.model, build_matrix(features, trained.model.feature_set, trained.model.country_groups))
    rfm = -rfm_scores(features)["rfm_score"].to_numpy(float)
    return paired_customer_bootstrap(v2["churned"].to_numpy(), risk, rfm, v2.index.get_level_values("customer_id"))


# --- the RED of U13 -------------------------------------------------------------------------------------------------------


def test_positive_control_beats_rfm_and_negative_control_does_not(cfg, launch_model):
    low, high, diff = against_rfm_on_v2(*launch_model("irregular_gaps"))
    assert low > 0, f"positive control: AUC(model) - AUC(RFM) = {diff:.4f}, 95 % interval {low:.4f} to {high:.4f}"
    labelled, trained = launch_model("rfm_only")
    low, high, diff = against_rfm_on_v2(labelled, trained)
    assert low <= 0 <= high, f"negative control: AUC(model) - AUC(RFM) = {diff:.4f}, 95 % interval {low:.4f} to {high:.4f}"


def test_two_runs_choose_the_same_candidate_and_give_identical_probabilities(cfg, launch_model):
    """AC16. A grid of 12 candidates with 50 iterations: the fit is seeded and never stops early, so determinism does not depend on the size
    of the grid, and the default one (24 candidates, 300 iterations) costs about 7 s a run (D59)."""
    view = SealedConfig.of(cfg, SHA)
    grid = dataclasses.replace(view, model=dataclasses.replace(view.model, learning_rate=(0.05, 0.1), max_leaf_nodes=(15,), min_samples_leaf=(20, 200), max_iter=50))
    labelled, _trained = launch_model("rfm_only")
    first, again = train_model(labelled, grid), train_model(labelled, grid)
    assert len(first.selection.losses) == 12 and len({loss for _c, loss in first.selection.losses}) > 1, "a real choice among twelve"
    assert again.selection.chosen == first.selection.chosen and again.selection.losses == first.selection.losses
    x = build_matrix(labelled[list(FEATURE_COLUMNS)], first.model.feature_set, first.model.country_groups)
    np.testing.assert_array_equal(predict_risk(again.model, x), predict_risk(first.model, x))
    pd.testing.assert_frame_equal(again.valid_v2, first.valid_v2, check_exact=True)


# --- the tripwire -----------------------------------------------------------------------------------------------------------


def days_to_next_purchase(conn, labelled: pd.DataFrame, as_of) -> np.ndarray:
    """For each labelled row, the days from its cut to the customer's next net purchase day (the window and after: what the label is made
    of), or 400 if none by `as_of`. It is ``days_to_next_purchase`` of ``schema.LABEL_COLUMNS``."""
    purchases, cancellations = known_netting_inputs(conn, as_of)
    days = customer_days(net_cancellations(purchases, cancellations, as_of).net_lines)
    by_customer = {c: g["day"].to_numpy() for c, g in days.groupby("customer_id")}
    out = []
    for cut, customer in labelled.index:
        later = by_customer.get(customer, np.array([], dtype="datetime64[ns]"))
        later = later[later >= np.datetime64(cut)]
        out.append(int((later.min() - np.datetime64(cut)) / np.timedelta64(1, "D")) if len(later) else 400)
    return np.asarray(out)


def test_a_future_looking_control_feature_trips_m01_and_stops_the_launch(cfg, launch_model, signal_launch):
    """By its name the control is refused by the guards (AC12); hidden under an allowed name it reaches the matrix, and the AUC of the
    selected candidate on V1 (1.0 or close: churned is «no purchase in 90 days») stops the launch (M01, AC14). The grid is the quick one:
    the tripwire does not depend on how many candidates there are."""
    view = SealedConfig.of(cfg, SHA)
    quick = dataclasses.replace(view, model=dataclasses.replace(view.model, learning_rate=(0.1,), max_leaf_nodes=(15,), min_samples_leaf=(20,), max_iter=50))
    labelled, _trained = launch_model("rfm_only")
    conn = connect(signal_launch("rfm_only"))
    try:
        control = days_to_next_purchase(conn, labelled, view.deliveries.launch_as_of)
    finally:
        conn.close()
    churned = labelled["churned"].to_numpy()
    # netted with what is known at the launch rather than at each window's end, it gives the label away for almost every row
    assert ((control < view.label.horizon_days) == (churned == 0)).mean() > 0.99
    with pytest.raises(LeakageError, match="days_to_next_purchase"):
        build_matrix(labelled[list(FEATURE_COLUMNS)].assign(days_to_next_purchase=control), "f1", ("Otros",))
    hidden = labelled.assign(freq_365=-control)
    with pytest.raises(LeakageError, match=r"M01.*0\.9[5-9]|M01.*1\.0") as error:
        train_model(hidden, quick)
    assert "posible fuga" in str(error.value)
    assert train_model(labelled, quick).selection.auc_v1 < view.criteria.leak_tripwire_auc, "control: without the leak the launch goes on"
