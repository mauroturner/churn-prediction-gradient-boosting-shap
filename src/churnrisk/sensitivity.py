"""The sensitivity of N, M and of the December cut, reported and never used to choose (RF23, AC26; D10; plan, section 17), and the tables of
the definition of the label (N x M and the silences that come back, on the training cuts).

Each variant keeps the cut dates of the design and leaves out the cuts whose window or purge does not fit its N: a training cut needs
``c + N <= v1_first`` (V1 calibrates), a V1 cut ``c + N <= test_first``, a test cut ``c + N - 1 <= last_date``; ``no_december`` also leaves
out the December training cut. For each variant, the population (with its M) and the label (with its N) of every kept cut, with what is known
on ``c - 1`` and on ``c + N - 1``; the **same sealed candidate** (feature set and hyperparameters: there is no other selection) fitted again on
its training cuts and calibrated on its V1; BG/NBD with the sealed parameters and its N as the horizon; and on its test the AUC of the model,
of B2 and of the sealed B*, the churn rate, the rows and the interval of the difference with B2 and with B* (resampling whole customers).
There is no threshold and no cost. ``run_variants`` refuses to run before the launch part of the seal exists, and nothing that chooses (the
selection, the calibration, B*, the threshold) reads what it writes (a static test).

This module receives the sealed view, never the whole configuration (D19).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from churnrisk.baselines import baseline_scores
from churnrisk.config import SealedConfig
from churnrisk.cuts import label, label_end, population
from churnrisk.evaluation import auc_score, cluster_bootstrap
from churnrisk.features import build_matrix, compute_features, country_groups, known_before, read_features
from churnrisk.model import Candidate, calibrate, make_pipeline, predict_risk
from churnrisk.netting import customer_days, known_netting_inputs, net_lines_at
from churnrisk.schema import FEATURE_COLUMNS
from churnrisk.split import blocks, require_both_classes

VARIANTS_ES = {"n60": "N = 60 días", "n120": "N = 120 días", "m180": "M = 180 días", "no_december": "sin el corte de diciembre en el entrenamiento"}


@dataclass(frozen=True)
class VariantPlan:
    variant: str
    n: int
    m: int
    train: tuple[date, ...]
    valid_v1: tuple[date, ...]
    test: tuple[date, ...]


def variant_plan(view: SealedConfig, variant: str) -> VariantPlan:
    """The cuts each block of `variant` keeps: those of the design whose window and purge fit its N (and no December for ``no_december``)."""
    s = view.sensitivity
    if variant not in VARIANTS_ES:
        raise ValueError(f"variante de sensibilidad desconocida: {variant!r}; se esperaba una de {', '.join(VARIANTS_ES)}")
    n = {"n60": s.n60_horizon_days, "n120": s.n120_horizon_days}.get(variant, view.label.horizon_days)
    m = s.m180_active_days if variant == "m180" else view.label.active_days
    by_block: dict[str, list[date]] = {}
    for cut, b in blocks(view).items():
        by_block.setdefault(b, []).append(cut)
    span = timedelta(days=n)
    train = [c for c in by_block.get("train", []) if c + span <= view.split.v1_first and not (variant == "no_december" and c.month == 12)]
    v1 = [c for c in by_block.get("valid_v1", []) if c + span <= view.split.test_first]
    test = [c for c in by_block.get("test", []) if label_end(c, n) <= view.deliveries.last_date]
    return VariantPlan(variant, n, m, tuple(train), tuple(v1), tuple(test))


class KnownDays:
    """The net purchase days known on each date, netted once per date from the lines the warehouse holds up to `as_of` (``net_lines_at``)."""

    def __init__(self, conn: sqlite3.Connection, as_of: date) -> None:
        self.conn, self.as_of = conn, as_of
        self.inputs = known_netting_inputs(conn, as_of)
        self._days: dict[date, pd.DataFrame] = {}
        self._features: dict[tuple[date, int], pd.DataFrame] = {}

    def on(self, day: date) -> pd.DataFrame:
        if day > self.as_of:
            raise ValueError(f"lo conocido el {day} no se sabe todavía en la fecha de cálculo {self.as_of}")
        if day not in self._days:
            self._days[day] = customer_days(net_lines_at(self.conn, day, self.inputs))
        return self._days[day]

    def features(self, cut: date, active_days: int, view: SealedConfig) -> pd.DataFrame:
        """The features of the population of `cut` with M = `active_days`, from what is known on ``c - 1`` (computed once per cut and M)."""
        if (cut, active_days) not in self._features:
            days, lines = known_before(*self.inputs, cut)
            self._features[(cut, active_days)] = compute_features(days, lines, cut, population(days, cut, active_days), view)
        return self._features[(cut, active_days)]


def rows_of(known: KnownDays, view: SealedConfig, cuts: tuple[date, ...], n: int, m: int, stored: pd.DataFrame) -> pd.DataFrame:
    """The rows of `cuts` with M = `m` and N = `n`: index ``(cut_date, customer_id)``, ``churned`` and the features. With the design's M the
    population and its features are those the warehouse holds (`stored`); with another M they are computed from what is known on ``c - 1``."""
    parts = []
    for cut in cuts:
        features = stored.xs(cut, level="cut_date") if m == view.label.active_days else known.features(cut, m, view)
        churned = label(known.on(label_end(cut, n)), cut, n, features.index)
        parts.append(features.assign(churned=churned.to_numpy(), cut_date=cut).set_index("cut_date", append=True).swaplevel())
    return pd.concat(parts)[["churned", *FEATURE_COLUMNS]]


def run_variants(conn: sqlite3.Connection, view: SealedConfig, bundle, candidate: Candidate, launch_seal: Mapping[str, Any] | None,
                 as_of: date) -> list[dict[str, Any]]:
    """Every variant of ``[sensitivity] variants`` on the warehouse known on `as_of` (see the module), in their order. Refuses to run unless
    `launch_seal` (the seal document) has its launch part: the sensitivity comes after everything it could have influenced is sealed."""
    from churnrisk.registry import SealError

    if not launch_seal or not launch_seal.get("launch"):
        raise SealError("las sensibilidades corren después de escrita la parte del lanzamiento del sello, y no hay sello")
    known = KnownDays(conn, as_of)
    stored = read_features(conn)
    out = []
    for variant in view.sensitivity.variants:
        plan = variant_plan(view, variant)
        train, v1, test = (rows_of(known, view, cuts, plan.n, plan.m, stored) for cuts in (plan.train, plan.valid_v1, plan.test))
        for name, rows in (("train", train), ("valid_v1", v1), (f"test de {variant}", test)):
            require_both_classes(rows["churned"].to_numpy(), name)
        groups = country_groups(train, view.features.country_min_customers)
        x = {k: build_matrix(r[list(FEATURE_COLUMNS)], candidate.feature_set, groups) for k, r in (("train", train), ("v1", v1), ("test", test))}
        pipeline = make_pipeline(candidate, view, groups).fit(x["train"], train["churned"].to_numpy())
        model = _VariantModel(candidate.feature_set, calibrate(pipeline, x["v1"], v1["churned"].to_numpy(), view.model.calibration))
        risk = predict_risk(model, x["test"])
        scores = baseline_scores(test[list(FEATURE_COLUMNS)], bundle.bgnbd, plan.n)
        y = test["churned"].to_numpy()
        customers = test.index.get_level_values("customer_id").to_numpy()
        ev = view.evaluation
        b2 = cluster_bootstrap(y, risk, scores["b2_rfm"], customers, ev.bootstrap_resamples, ev.bootstrap_seed)
        bs = cluster_bootstrap(y, risk, scores[bundle.b_star], customers, ev.bootstrap_resamples, ev.bootstrap_seed)
        out.append({
            "variant": variant, "label_es": VARIANTS_ES[variant], "n": plan.n, "m": plan.m,
            "train_cuts": [c.isoformat() for c in plan.train], "valid_v1_cuts": [c.isoformat() for c in plan.valid_v1],
            "test_cuts": [c.isoformat() for c in plan.test], "rows": int(len(test)), "churn_rate": float(y.mean()),
            "auc_model": auc_score(y, risk), "auc_b2": auc_score(y, scores["b2_rfm"]), "auc_b_star": auc_score(y, scores[bundle.b_star]),
            "diff_b2_ci_low": b2.ci_low, "diff_b2_ci_high": b2.ci_high, "diff_b_star_ci_low": bs.ci_low, "diff_b_star_ci_high": bs.ci_high,
        })
    return out


@dataclass(frozen=True)
class _VariantModel:
    """What ``model.predict_risk`` needs of a model: its feature set and its calibrated classifier."""

    feature_set: str
    calibrated: Any


# --- the definition of the label on the training cuts (D06, D07) ---------------------------------------------------------------


def definition_tables(conn: sqlite3.Connection, view: SealedConfig, as_of: date) -> tuple[pd.DataFrame, pd.DataFrame]:
    """``(label_definition, silence_return)`` on the design's training cuts: the churn rate and the rows of every N of the sensitivity (and
    the design's) by every M; and for each N, the silences (churned with that N) and the share of them that buys again in the next N days,
    ``[c + N, c + 2N - 1]``, netted with what is known at the end of that window. Informative: nothing chooses with them."""
    known = KnownDays(conn, as_of)
    stored = read_features(conn)
    s = view.sensitivity
    ns = sorted({s.n60_horizon_days, view.label.horizon_days, s.n120_horizon_days})
    ms = sorted({view.label.active_days, s.m180_active_days})
    train = tuple(c for c, b in blocks(view).items() if b == "train")
    definition, silences = [], []
    for m in ms:
        for n in ns:
            rows = rows_of(known, view, train, n, m, stored)
            definition.append((n, m, float(rows["churned"].mean()), int(len(rows))))
    for n in ns:
        rows = rows_of(known, view, train, n, view.label.active_days, stored)
        silent = rows[rows["churned"] == 1]
        back = 0
        for cut, part in silent.groupby(level="cut_date"):
            start, end = pd.Timestamp(cut + timedelta(days=n)), pd.Timestamp(cut + timedelta(days=2 * n - 1))
            days = known.on(cut + timedelta(days=2 * n - 1))
            returned = set(days.loc[(days["day"] >= start) & (days["day"] <= end), "customer_id"])
            back += int(np.isin(part.index.get_level_values("customer_id"), list(returned)).sum())
        silences.append((n, int(len(silent)), back / len(silent) if len(silent) else None))
    return (pd.DataFrame(definition, columns=["n", "m", "churn_rate", "rows"]),
            pd.DataFrame(silences, columns=["n", "silences", "return_share"]))
