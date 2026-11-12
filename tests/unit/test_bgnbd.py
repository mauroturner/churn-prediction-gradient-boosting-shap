"""BG/NBD with SciPy, copied from project 02 and checked against `lifetimes` (U12, AC15; D17, M08).

`lifetimes` is a development dependency only (D17): the pipeline never imports it. The tests that compare with it carry the mark ``oracle``
(they run in the default suite) and are skipped, with a reason, if it is not installed."""

from __future__ import annotations

import warnings
from datetime import date

import numpy as np
import pandas as pd
import pytest

from churnrisk import bgnbd
from churnrisk.bgnbd import (
    BGNBDParams,
    ConvergenceError,
    bgnbd_log_likelihood,
    expected_purchases,
    fit_bgnbd,
    p_alive,
    simulate_bgnbd,
    summary_at_cut,
    summary_from_features,
)
from churnrisk.config import SealedConfig
from churnrisk.features import compute_features, known_before
from tests.fixtures import hand_cases

# close to what the planner fitted on the training history, in days (requirements.md, section 4)
SIMULATED = BGNBDParams(r=0.9, alpha=75.0, a=0.6, b=4.0)


@pytest.fixture(scope="module")
def lifetimes():
    return pytest.importorskip("lifetimes", reason="lifetimes is the oracle of these tests (requirements-dev.txt)")


@pytest.fixture(scope="module")
def cdnow(lifetimes):
    """The 2,357 customers of Fader, Hardie and Lee (2005): frequency, recency and T in weeks."""
    from lifetimes.datasets import load_cdnow_summary

    frame = load_cdnow_summary(index_col=[0])
    return tuple(frame[c].to_numpy(float) for c in ("frequency", "recency", "T"))


@pytest.fixture(scope="module")
def simulated():
    """3,000 customers of the BG/NBD process, observed from 60 to 720 days, in days."""
    T = np.random.default_rng(7).uniform(60, 720, 3000).round()
    frame = simulate_bgnbd(3000, SIMULATED, T, seed=11)
    return tuple(frame[c].to_numpy(float) for c in ("x", "t_x", "T"))


def their_fit(lifetimes, x, t_x, T):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return lifetimes.BetaGeoFitter().fit(x, t_x, T)


def params_of(theirs) -> BGNBDParams:
    return BGNBDParams(*(float(theirs.params_[k]) for k in ("r", "alpha", "a", "b")))


def their_log_likelihood(lifetimes, params: BGNBDParams, x, t_x, T) -> float:
    """The total log-likelihood of `params` by lifetimes' own formula, in the units of the data (its fit rescales the time)."""
    log_params = np.log([params.r, params.alpha, params.a, params.b])
    return -len(x) * float(lifetimes.BetaGeoFitter._negative_log_likelihood(log_params, x, t_x, T, np.ones(len(x)), 0.0))


# --- the RED of U12 -------------------------------------------------------------------------------------------------------


@pytest.mark.oracle
@pytest.mark.parametrize(("data", "horizon"), [("cdnow", 13.0), ("simulated", 90.0)])
def test_fit_matches_lifetimes_oracle(request, lifetimes, data, horizon):
    """On CDNOW (weeks) and on a simulated set (days): lifetimes' log-likelihood is the same to 1e-3 at our optimum and at its own, our
    formula of the log-likelihood is theirs, and the expected purchases over the horizon agree to 1e-2 relative, each with its own
    parameters."""
    x, t_x, T = request.getfixturevalue(data)
    ours = fit_bgnbd(x, t_x, T)
    theirs = their_fit(lifetimes, x, t_x, T)
    best = their_log_likelihood(lifetimes, params_of(theirs), x, t_x, T)
    assert abs(their_log_likelihood(lifetimes, ours.params, x, t_x, T) - best) <= 1e-3, (ours.params, params_of(theirs))
    assert ours.converged and ours.n == len(x)
    assert float(bgnbd_log_likelihood(params_of(theirs), x, t_x, T).sum()) == pytest.approx(best, rel=1e-12), "our log-likelihood is lifetimes' one"
    assert abs(ours.log_likelihood - best) <= 1e-3
    mine = expected_purchases(ours.params, horizon, x, t_x, T)
    reference = np.asarray(theirs.conditional_expected_number_of_purchases_up_to_time(horizon, x, t_x, T))
    assert np.max(np.abs(mine - reference) / np.maximum(reference, 1e-12)) <= 1e-2


@pytest.mark.oracle
def test_cdnow_published_parameters(cdnow):
    # Fader, Hardie and Lee (2005): r = 0.243, alpha = 4.414, a = 0.793, b = 2.426 and a log-likelihood of -9,582.4.
    fit = fit_bgnbd(*cdnow)
    assert (round(fit.params.r, 3), round(fit.params.alpha, 3), round(fit.params.a, 3), round(fit.params.b, 3)) == (0.243, 4.414, 0.793, 2.426)
    assert round(fit.log_likelihood, 1) == -9582.4 and fit.n == 2357


@pytest.mark.oracle
def test_the_formulas_are_lifetimes_given_the_same_parameters(lifetimes, cdnow):
    x, t_x, T = cdnow
    theirs = their_fit(lifetimes, x, t_x, T)
    params = params_of(theirs)
    for horizon in (1.0, 13.0, 39.0, 52.0):
        mine = expected_purchases(params, horizon, x, t_x, T)
        reference = np.asarray(theirs.conditional_expected_number_of_purchases_up_to_time(horizon, x, t_x, T))
        assert np.max(np.abs(mine - reference) / np.maximum(np.abs(reference), 1e-12)) < 1e-9, horizon
    assert np.max(np.abs(p_alive(params, x, t_x, T) - np.asarray(theirs.conditional_probability_alive(x, t_x, T)))) < 1e-12


# --- the summary of a cut and the fit ---------------------------------------------------------------------------------------


def test_the_summary_of_a_cut_is_the_history_before_it_measured_to_the_cut(cfg):
    """x is the purchase days after the first, t_x the days from the first to the last and T from the first to the cut; from the stored
    features it is the same (x = freq_total - 1, t_x = tenure_days - rec_days, T = tenure_days)."""
    days = pd.DataFrame({"customer_id": [1, 1, 1, 2], "day": pd.to_datetime(["2010-10-01", "2010-10-11", "2010-11-30", "2010-11-01"]),
                         "net_revenue": [1.0, 2.0, 3.0, 4.0]})
    got = summary_at_cut(days, date(2010, 12, 1)).set_index("customer_id")
    assert got.loc[1, ["x", "t_x", "T"]].tolist() == [2, 60, 61] and got.loc[2, ["x", "t_x", "T"]].tolist() == [0, 0, 30]
    with pytest.raises(ValueError, match="2010-12-01"):
        summary_at_cut(pd.concat([days, days.head(1).assign(day=pd.Timestamp(2010, 12, 1))]), date(2010, 12, 1))
    case = hand_cases.features_case()
    history, lines = known_before(case.purchases, case.cancellations, case.cut)
    features = compute_features(history, lines, case.cut, pd.Index(case.customers), SealedConfig.of(cfg, "e" * 64))
    from_days = summary_at_cut(history, case.cut).set_index("customer_id")[["x", "t_x", "T"]]
    assert summary_from_features(features)[["x", "t_x", "T"]].equals(from_days.loc[list(case.customers)])


def test_m08_two_failed_optimisations_are_a_convergence_error(monkeypatch):
    from scipy.optimize import OptimizeResult

    calls = []

    def failing(fun, x0, method, **kwargs):
        calls.append(method)
        return OptimizeResult(x=np.zeros(4), success=False, message="forced to fail")

    monkeypatch.setattr(bgnbd, "minimize", failing)
    with pytest.raises(ConvergenceError, match="M08"):
        fit_bgnbd([0, 1, 2], [0, 5, 9], [10, 10, 10])
    assert calls == ["L-BFGS-B", "Nelder-Mead"], "one retry with Nelder-Mead, then the error"


def test_the_simulation_is_seeded_and_a_customer_without_repeats_is_alive():
    T = np.full(50, 300.0)
    assert simulate_bgnbd(50, SIMULATED, T, seed=3).equals(simulate_bgnbd(50, SIMULATED, T, seed=3))
    assert not simulate_bgnbd(50, SIMULATED, T, seed=3).equals(simulate_bgnbd(50, SIMULATED, T, seed=4))
    assert p_alive(SIMULATED, [0], [0], [300])[0] == 1.0
    with pytest.raises(ValueError, match="clientes"):
        fit_bgnbd([], [], [])


@pytest.mark.parametrize(("lbfgs_x", "start_is_zero"), [(np.array([0.5, -0.2, 0.1, 0.3]), False), (np.array([np.nan, 0.0, 0.0, 0.0]), True)])
def test_the_nelder_mead_retry_starts_where_l_bfgs_b_stopped_or_from_zeros_if_that_is_not_finite(monkeypatch, lbfgs_x, start_is_zero):
    """R3-nelder-mead-retry-start-fallback-unproved: the retry continues from L-BFGS-B's last point when it is finite, and from the zeros
    otherwise; its result is the fit's."""
    from scipy.optimize import OptimizeResult

    starts = []

    def scripted(fun, x0, method, **kwargs):
        starts.append((method, np.array(x0, dtype="float64")))
        if method == "L-BFGS-B":
            return OptimizeResult(x=lbfgs_x, success=False, message="forced to fail")
        return OptimizeResult(x=np.log([0.9, 75.0, 0.2, 100.0]), success=True, fun=1.0, message="ok", nit=3)

    monkeypatch.setattr(bgnbd, "minimize", scripted)
    fit = fit_bgnbd([0, 1, 2], [0, 5, 9], [10, 10, 10])
    assert [m for m, _x in starts] == ["L-BFGS-B", "Nelder-Mead"]
    np.testing.assert_allclose([fit.params.r, fit.params.alpha, fit.params.a, fit.params.b], [0.9, 75.0, 0.2, 100.0], rtol=1e-12)
    expected = np.zeros(4) if start_is_zero else lbfgs_x
    np.testing.assert_array_equal(starts[1][1], expected)
