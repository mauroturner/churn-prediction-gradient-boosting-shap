"""BG/NBD and the baselines on the real training cuts (U12, mark real_data; AC15): the figures of requirements.md, section 4, which the
planner measured with project 02's functions and `lifetimes` on the lines before 2011-03-01, come out of the project's own code. Only the
session fixture ``real_training`` is read, so no line of a validation or test window is used (D19)."""

from __future__ import annotations

import warnings
from datetime import date

import numpy as np
import pytest
from scipy.stats import spearmanr
from sklearn.metrics import roc_auc_score

from churnrisk.baselines import baseline_scores, rfm_scores
from churnrisk.bgnbd import BGNBDParams, expected_purchases, fit_at_cut, p_alive, summary_at_cut, summary_from_features
from churnrisk.config import SealedConfig
from churnrisk.features import known_before

pytestmark = pytest.mark.real_data


@pytest.fixture(scope="module")
def fitted(real_training, cfg):
    purchases, cancellations, rows = real_training
    view = SealedConfig.of(cfg, cfg.source.accepted_sha256)
    cut = view.baselines.bgnbd_fit_cut
    history = known_before(purchases, cancellations, cut)[0]
    return view, history, fit_at_cut(history, cut, view.baselines.bgnbd_max_iter), rows


def actives(rows, cut: date):
    december = rows.xs(cut, level="cut_date")
    summary = summary_from_features(december)
    return december, tuple(summary[c].to_numpy(float) for c in ("x", "t_x", "T"))


def test_the_real_bgnbd_fit_is_the_one_of_the_requirements(fitted):
    view, _history, fit, rows = fitted
    p = fit.params
    assert fit.converged and fit.n == 4_229
    assert (round(p.r, 4), round(p.alpha, 2), round(p.a, 4), round(p.b, 2), round(fit.log_likelihood, 4)) == (0.9091, 75.83, 0.1717, 105.91, -59_505.3611)
    december, (x, t_x, T) = actives(rows, view.baselines.bgnbd_fit_cut)
    expected = expected_purchases(p, view.label.horizon_days, x, t_x, T)
    assert len(december) == 2_859 and round(float(expected.mean()), 4) == 1.3536, "the means are 1.3536 (ours) and 1.3537 (lifetimes)"
    alive = p_alive(p, x, t_x, T)
    assert (round(float(alive.min()), 3), round(float(np.quantile(alive, 0.01)), 3), round(float(np.median(alive)), 3)) == (0.866, 0.992, 0.998)
    assert (round(float((alive >= 0.996).mean()), 3), round(float((x == 0).mean()), 3)) == (0.934, 0.239), "P(alive) saturates (D16)"


@pytest.mark.oracle
def test_the_real_bgnbd_fit_against_lifetimes(fitted):
    lifetimes = pytest.importorskip("lifetimes")
    view, history, fit, rows = fitted
    summary = summary_at_cut(history, view.baselines.bgnbd_fit_cut)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        theirs = lifetimes.BetaGeoFitter().fit(summary["x"], summary["t_x"], summary["T"])
    q = BGNBDParams(*(float(theirs.params_[k]) for k in ("r", "alpha", "a", "b")))
    assert (round(q.r, 4), round(q.alpha, 2), round(q.a, 4), round(q.b, 2)) == (0.9084, 75.76, 0.1737, 108.27)
    log_q = np.log([q.r, q.alpha, q.a, q.b])
    x0, tx0, T0 = (summary[c].to_numpy(float) for c in ("x", "t_x", "T"))
    their_ll = -len(x0) * float(lifetimes.BetaGeoFitter._negative_log_likelihood(log_q, x0, tx0, T0, np.ones(len(x0)), 0.0))
    assert round(their_ll, 4) == -59_505.3607
    _december, (x, t_x, T) = actives(rows, view.baselines.bgnbd_fit_cut)
    ours = expected_purchases(fit.params, view.label.horizon_days, x, t_x, T)
    reference = np.asarray(theirs.conditional_expected_number_of_purchases_up_to_time(view.label.horizon_days, x, t_x, T))
    assert round(float(np.abs(ours - reference).max()), 4) == 0.0045 and round(float(reference.mean()), 4) == 1.3537
    assert round(float(spearmanr(ours, reference).statistic), 7) == 0.9999996


def test_the_real_baselines_rank_the_training_cuts_as_the_requirements_measured(fitted):
    """AUC of each rule in each of the seven training cuts, ties counted by halves: mean, minimum and maximum (requirements.md, section 4).
    The one figure that differs is the minimum of B5, 0.326 (0.326452 in 2010-06-01) where the requirements say 0.327 (D58)."""
    view, _history, fit, rows = fitted
    scores = baseline_scores(rows, fit.params, view.label.horizon_days).assign(spend=-rows["mon_365"])
    by_cut = {}
    for method in ("b4_frequency", "b2_rfm", "b3_bgnbd", "spend", "b1_recency", "b5_alive"):
        aucs = [roc_auc_score(rows.xs(c, level="cut_date")["churned"], scores.xs(c, level="cut_date")[method])
                for c in sorted(set(rows.index.get_level_values("cut_date")))]
        by_cut[method] = (round(float(np.mean(aucs)), 3), round(float(np.min(aucs)), 3), round(float(np.max(aucs)), 3))
    assert by_cut == {"b4_frequency": (0.746, 0.728, 0.761), "b2_rfm": (0.737, 0.711, 0.760), "b3_bgnbd": (0.732, 0.706, 0.753),
                      "spend": (0.731, 0.713, 0.758), "b1_recency": (0.594, 0.550, 0.623), "b5_alive": (0.362, 0.326, 0.392)}
    # RFM orders well: the churn rate falls with every point of the score, from 71.5 % (3) to 4.3 % (15), without an inversion
    rates = rows.assign(score=rfm_scores(rows)["rfm_score"]).groupby("score")["churned"].agg(["mean", "size"])
    assert list(rates.index) == list(range(3, 16)) and rates["mean"].is_monotonic_decreasing
    assert (round(float(rates.loc[3, "mean"]), 3), int(rates.loc[3, "size"]), round(float(rates.loc[15, "mean"]), 3), int(rates.loc[15, "size"])) == (
        0.715, 716, 0.043, 853)
