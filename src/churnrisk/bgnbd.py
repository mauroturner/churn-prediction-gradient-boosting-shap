"""BG/NBD with SciPy, copied from project 02's ``clv.py`` and adapted (RF15, D17, M08; plan, section 11).

The model of Fader, Hardie and Lee (2005) for the repeat purchases of a customer, from its published formulas, in days, without
Gamma-Gamma or the value of a customer (V is a declared constant, D22). A customer at a cut is described by ``x`` (purchase days after the
first), ``t_x`` (days from the first purchase day to the last) and ``T`` (days from the first purchase day to the cut): the history before
the cut, the same that the features see (``x = freq_total - 1``, ``t_x = tenure_days - rec_days``, ``T = tenure_days``).

It is fitted **once**, at the launch, with every customer that has a net purchase day before ``bgnbd_fit_cut``, netted with what is known
the day before; the parameters then stay fixed for every cut (D17). The fit maximizes the likelihood over the logarithm of the parameters
with L-BFGS-B and retries once with Nelder-Mead; if neither converges it is ``ConvergenceError`` (M08).

``lifetimes`` is never imported here: it is the oracle of the tests (``tests/unit/test_bgnbd.py``, mark ``oracle``).
"""

from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import asdict, dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import betaln, expit, gammaln, hyp2f1

from churnrisk.config import SealedConfig
from churnrisk.netting import customer_days, net_lines_at

logger = logging.getLogger(__name__)

LOG_BOUND = 20.0  # the optimiser works on log parameters, kept inside [-20, 20] so that exp() cannot overflow
SUMMARY_COLUMNS = ["customer_id", "x", "t_x", "T"]


@dataclass(frozen=True)
class BGNBDParams:
    r: float
    alpha: float
    a: float
    b: float

    def as_dict(self) -> dict[str, float]:
        return {key: float(value) for key, value in asdict(self).items()}


@dataclass(frozen=True)
class FitResult:
    params: BGNBDParams
    log_likelihood: float  # summed over the customers used
    n: int                 # customers used
    converged: bool
    seconds: float


class ConvergenceError(RuntimeError):
    """M08: neither L-BFGS-B nor the Nelder-Mead retry converged."""


def _floats(values) -> np.ndarray:
    return np.asarray(values, dtype=float)


def bgnbd_log_likelihood(params: BGNBDParams, x, t_x, T) -> np.ndarray:
    """ln L(r, alpha, a, b | x, t_x, T) of each customer."""
    x, t_x, T = _floats(x), _floats(t_x), _floats(T)
    r, alpha, a, b = params.r, params.alpha, params.a, params.b
    with np.errstate(divide="ignore", invalid="ignore"):
        first = gammaln(r + x) - gammaln(r) + r * np.log(alpha)
        second = betaln(a, b + x) - betaln(a, b)
        never_dropped = -(r + x) * np.log(alpha + T)
        dropped_after_last = np.log(a) - np.log(b + np.maximum(x, 1) - 1) - (r + x) * np.log(alpha + t_x)
        return first + second + np.logaddexp(never_dropped, np.where(x > 0, dropped_after_last, -np.inf))


def expected_purchases(params: BGNBDParams, t, x, t_x, T) -> np.ndarray:
    """E[repeat purchases in the next `t` days | x, t_x, T] of each customer (`t` is a number or one per customer)."""
    x, t_x, T, t = _floats(x), _floats(t_x), _floats(T), _floats(t)
    r, alpha, a, b = params.r, params.alpha, params.a, params.b
    with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
        hyper = hyp2f1(r + x, b + x, a + b + x - 1, t / (alpha + T + t))
        bracket = 1 - np.exp((r + x) * (np.log(alpha + T) - np.log(alpha + T + t))) * hyper
        dead = np.where(x > 0, a / (b + np.maximum(x, 1) - 1) * np.exp((r + x) * (np.log(alpha + T) - np.log(alpha + t_x))), 0.0)
        return (a + b + x - 1) / (a - 1) * bracket / (1 + dead)


def p_alive(params: BGNBDParams, x, t_x, T) -> np.ndarray:
    """P(the customer is still active at T | x, t_x, T); 1 for a customer with no repeat purchase."""
    x, t_x, T = _floats(x), _floats(t_x), _floats(T)
    r, alpha, a, b = params.r, params.alpha, params.a, params.b
    with np.errstate(divide="ignore", invalid="ignore"):
        log_odds_dead = np.log(a) - np.log(b + np.maximum(x, 1) - 1) + (r + x) * (np.log(alpha + T) - np.log(alpha + t_x))
    return np.where(x > 0, expit(-log_odds_dead), 1.0)


def _optimise(objective, n_params: int, max_iter: int):
    """Minimise `objective` over log parameters from zeros: L-BFGS-B, then one Nelder-Mead retry; ConvergenceError (M08) if both fail."""

    def safe(theta: np.ndarray) -> float:
        value = objective(np.exp(np.clip(theta, -LOG_BOUND, LOG_BOUND)))
        return float(value) if np.isfinite(value) else 1e12

    start = np.zeros(n_params)
    result = minimize(safe, start, method="L-BFGS-B", bounds=[(-LOG_BOUND, LOG_BOUND)] * n_params, options={"maxiter": max_iter})
    if result.success:
        return result
    logger.warning("BG/NBD: L-BFGS-B did not converge (%s); retrying once with Nelder-Mead", result.message)
    retry = minimize(safe, result.x if np.all(np.isfinite(result.x)) else start, method="Nelder-Mead",
                     options={"maxiter": max_iter, "xatol": 1e-8, "fatol": 1e-10})
    if not retry.success:
        raise ConvergenceError(f"M08: el ajuste de BG/NBD no convergió ni con L-BFGS-B ni con Nelder-Mead: {retry.message} (docs/runbook.md, R5)")
    return retry


def fit_bgnbd(x, t_x, T, max_iter: int = 5000) -> FitResult:
    """Maximum-likelihood BG/NBD parameters of the customers described by `x`, `t_x` and `T`."""
    x, t_x, T = _floats(x), _floats(t_x), _floats(T)
    if not len(x):
        raise ValueError("BG/NBD necesita clientes para ajustarse y no hay ninguno")
    began = time.perf_counter()
    result = _optimise(lambda p: -bgnbd_log_likelihood(BGNBDParams(*p), x, t_x, T).sum() / len(x), 4, max_iter)
    params = BGNBDParams(*np.exp(np.clip(result.x, -LOG_BOUND, LOG_BOUND)).tolist())
    fit = FitResult(params, float(bgnbd_log_likelihood(params, x, t_x, T).sum()), len(x), True, time.perf_counter() - began)
    logger.info("BG/NBD fitted on %d customers in %.3f s: %s, ln L = %.4f", fit.n, fit.seconds, params, fit.log_likelihood)
    return fit


def simulate_bgnbd(n: int, params: BGNBDParams, T, seed: int) -> pd.DataFrame:
    """`n` customers drawn from the BG/NBD process: ``x``, ``t_x`` and ``T``; `T` is a number or one value per customer (for the tests).

    A customer buys at rate lambda ~ Gamma(r, rate alpha); after each repeat purchase it drops out with probability p ~ Beta(a, b).
    Deterministic for a given `seed`.
    """
    rng = np.random.default_rng(seed)
    horizon = np.broadcast_to(_floats(T), (n,))
    rate = rng.gamma(params.r, 1.0 / params.alpha, size=n)
    drop = rng.beta(params.a, params.b, size=n)
    xs = np.zeros(n, dtype="int64")
    last = np.zeros(n)
    for i in range(n):
        now = rng.exponential(1.0 / rate[i])
        while now < horizon[i]:
            xs[i] += 1
            last[i] = now
            if rng.random() < drop[i]:
                break
            now += rng.exponential(1.0 / rate[i])
    return pd.DataFrame({"x": xs, "t_x": last, "T": horizon.astype(float)})


# --- the history of a cut ---------------------------------------------------------------------------------------------------


def summary_at_cut(days_before: pd.DataFrame, cut: date) -> pd.DataFrame:
    """``customer_id``, ``x``, ``t_x`` and ``T`` of every customer with a net purchase day before `cut` (`days_before` is
    ``netting.customer_days`` known on ``c - 1``); a day dated on the cut or later is a ``ValueError``, never filtered in silence."""
    cut_ts = pd.Timestamp(cut)
    if (days_before["day"] >= cut_ts).any():
        raise ValueError(f"la historia de BG/NBD al corte {cut} tiene días de compra desde el {cut}: solo se usa lo anterior al corte")
    if days_before.empty:
        return pd.DataFrame({c: pd.Series(dtype="int64") for c in SUMMARY_COLUMNS})
    grouped = days_before.groupby("customer_id")["day"]
    first, last, count = grouped.min(), grouped.max(), grouped.size()
    out = pd.DataFrame({"x": (count - 1).astype("int64"), "t_x": (last - first).dt.days.astype("int64"), "T": (cut_ts - first).dt.days.astype("int64")})
    out.index = out.index.astype("int64")
    return out.rename_axis("customer_id").reset_index()[SUMMARY_COLUMNS]


def summary_from_features(features: pd.DataFrame) -> pd.DataFrame:
    """``x``, ``t_x`` and ``T`` of each row of the features of a cut (same index): the same history that ``summary_at_cut`` reads."""
    return pd.DataFrame({
        "x": (features["freq_total"] - 1).astype("int64"),
        "t_x": (features["tenure_days"] - features["rec_days"]).astype("int64"),
        "T": features["tenure_days"].astype("int64"),
    }, index=features.index)


def fit_at_cut(days_before: pd.DataFrame, cut: date, max_iter: int) -> FitResult:
    """BG/NBD fitted on every customer with a net purchase day before `cut`."""
    summary = summary_at_cut(days_before, cut)
    return fit_bgnbd(summary["x"], summary["t_x"], summary["T"], max_iter)


def fit_in_warehouse(conn: sqlite3.Connection, view: SealedConfig) -> FitResult:
    """The fit of the launch: the purchase days before ``bgnbd_fit_cut`` known on the day before it, whatever the warehouse holds since."""
    cut = view.baselines.bgnbd_fit_cut
    days = customer_days(net_lines_at(conn, cut - timedelta(days=1)))
    return fit_at_cut(days, cut, view.baselines.bgnbd_max_iter)
