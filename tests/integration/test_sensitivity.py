"""The sensitivity of N, M and of the December cut in the quick history (U18, AC11, AC26; D10; plan, section 17): each variant keeps only the
cuts that fit its N, runs after the launch part of the seal, enters the test part of the seal and C10, and is never read to choose."""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta

import pandas as pd
import pytest

from churnrisk.config import SealedConfig
from churnrisk.cuts import label_end
from churnrisk.model import Candidate
from churnrisk.netting import customer_days, net_cancellations, netting_inputs
from churnrisk.registry import SealError, read_seal
from churnrisk.sensitivity import run_variants, variant_plan
from churnrisk.split import labelled_rows
from churnrisk.warehouse import connect

D = date
TRAIN = tuple(D(2010, month, 1) for month in range(6, 13))
V1 = (D(2011, 3, 1), D(2011, 4, 1))
TEST = (D(2011, 8, 1), D(2011, 9, 1))


# --- the RED of U18 ------------------------------------------------------------------------------------------------------


def test_each_variant_keeps_only_cuts_that_fit_and_runs_after_the_launch_seal(quick_history, canonical, copy_of):
    view: SealedConfig = quick_history.view
    plans = {v: variant_plan(view, v) for v in view.sensitivity.variants}
    assert {v: (p.n, p.m, p.train, p.valid_v1, p.test) for v, p in plans.items()} == {
        "n60": (60, 90, TRAIN, V1, TEST),
        "n120": (120, 90, TRAIN[:-1], V1, TEST[:1]),            # 2010-12-01 + 120 days > 2011-03-01; the window of 2011-09-01 ends 2011-12-29
        "m180": (90, 180, TRAIN, V1, TEST),
        "no_december": (90, 90, TRAIN[:-1], V1, TEST),
    }
    for plan in plans.values():
        assert all(c + timedelta(days=plan.n) <= view.split.v1_first for c in plan.train)
        assert all(c + timedelta(days=plan.n) <= view.split.test_first for c in plan.valid_v1)
        assert all(label_end(c, plan.n) <= view.deliveries.last_date for c in plan.test)
    # the variants are in the test part of the seal, in their order, each on its own cuts
    seal = read_seal(quick_history.cfg.paths.seal)
    variants = {v["variant"]: v for v in seal["test"]["variants"]}
    assert list(variants) == list(view.sensitivity.variants)
    for name, plan in plans.items():
        v = variants[name]
        assert (v["n"], v["m"], v["train_cuts"], v["valid_v1_cuts"], v["test_cuts"]) == (
            plan.n, plan.m, [c.isoformat() for c in plan.train], [c.isoformat() for c in plan.valid_v1], [c.isoformat() for c in plan.test])
        assert all(0.0 <= v[k] <= 1.0 for k in ("auc_model", "auc_b2", "auc_b_star", "churn_rate"))
        assert v["diff_b_star_ci_low"] <= v["auc_model"] - v["auc_b_star"] <= v["diff_b_star_ci_high"]
    design = seal["test"]["metrics"]["model"]
    assert variants["n60"]["rows"] == variants["no_december"]["rows"] == design["rows"], "with the design's M, the design's population"
    assert variants["m180"]["rows"] > design["rows"] and variants["n120"]["rows"] < design["rows"]
    assert variants["n60"]["churn_rate"] > design["churn_rate"] > variants["n120"]["churn_rate"], "a shorter window, more churners"
    # the label of N = 60, computed apart from the warehouse: no net purchase day in [c, c + 59] with what is known on c + 59
    frame, _report = canonical
    purchases, cancellations = netting_inputs(frame)
    conn = sqlite3.connect(quick_history.warehouse)
    try:
        test_rows = labelled_rows(conn, ["test"])
    finally:
        conn.close()
    churned = []
    for cut in TEST:
        days = customer_days(net_cancellations(purchases, cancellations, cut + timedelta(days=59)).net_lines)
        back = set(days.loc[(days["day"] >= pd.Timestamp(cut)) & (days["day"] <= pd.Timestamp(cut + timedelta(days=59))), "customer_id"])
        churned += [int(c not in back) for c in test_rows.xs(cut, level="cut_date").index]
    assert variants["n60"]["churn_rate"] == pytest.approx(sum(churned) / len(churned), abs=1e-12)
    # C10 says them, and the sensitivity refuses to run before the launch part of the seal exists
    c10 = next(e for e in seal["test"]["criteria"] if e["id"] == "C10")
    assert "Sensibilidades: N = 60 días (2011-08-01, 2011-09-01): AUC del modelo" in c10["verdict_es"] and "M = 180 días" in c10["verdict_es"]
    conn = connect(copy_of(quick_history.warehouse))
    try:
        from churnrisk.launch import load_registered

        registered = load_registered(conn, quick_history.cfg)
        candidate = Candidate(registered.feature_set, **seal["launch"]["params"])
        for missing in (None, {}, {"version": 1}):
            with pytest.raises(SealError, match="después de escrita la parte del lanzamiento del sello"):
                run_variants(conn, view, registered.bundle, candidate, missing, quick_history.runs[-1].spec.as_of)
    finally:
        conn.close()


def test_the_definition_of_the_label_on_the_training_cuts_is_stored_with_the_validation(quick_history):
    """The churn rate of every N by every M and the silences that come back on the training cuts, written by the launch's evaluation: with the
    design's N and M, the rate is the one of the training labels."""
    conn = sqlite3.connect(quick_history.runs[0].warehouse)
    try:
        definition = conn.execute("SELECT n, m, churn_rate, rows FROM eval_label_definition ORDER BY m, n").fetchall()
        silences = conn.execute("SELECT n, silences, return_share FROM eval_silence_return ORDER BY n").fetchall()
        train = labelled_rows(conn, ["train"])
    finally:
        conn.close()
    assert [(n, m) for n, m, _r, _rows in definition] == [(60, 90), (90, 90), (120, 90), (60, 180), (90, 180), (120, 180)]
    by = {(n, m): (rate, rows) for n, m, rate, rows in definition}
    assert by[(90, 90)] == (pytest.approx(train["churned"].mean(), abs=1e-12), len(train))
    assert {rows for (_n, m), (_r, rows) in by.items() if m == 90} == {len(train)} and by[(90, 180)][1] > len(train)
    assert by[(60, 90)][0] > by[(90, 90)][0] > by[(120, 90)][0], "a longer window, fewer churners"
    assert [n for n, _s, _r in silences] == [60, 90, 120]
    assert dict((n, s) for n, s, _r in silences)[90] == int(train["churned"].sum()), "the silences of N = 90 are the churners of the training"
    assert all(0 < share < 1 for _n, _s, share in silences)


def test_a_variant_whose_block_keeps_no_cut_is_refused_naming_the_variant_and_rows_of_no_cut_is_empty(quick_history, monkeypatch):
    """R3-rows-of-empty-cuts: ``rows_of`` of no cut is an empty frame with the columns of the rows (``pd.concat`` of nothing raised), and
    ``run_variants`` refuses a variant whose plan leaves a block without cuts with a message that names the variant and the block."""
    import dataclasses

    from churnrisk import sensitivity
    from churnrisk.features import read_features
    from churnrisk.schema import FEATURE_COLUMNS
    from churnrisk.sensitivity import KnownDays, rows_of

    view = quick_history.view
    as_of = quick_history.runs[-1].spec.as_of
    conn = connect(quick_history.runs[-1].warehouse)
    try:
        empty = rows_of(KnownDays(conn, as_of), view, (), view.label.horizon_days, view.label.active_days, read_features(conn))
        assert empty.empty and list(empty.columns) == ["churned", *FEATURE_COLUMNS] and list(empty.index.names) == ["cut_date", "customer_id"]
        real_plan = sensitivity.variant_plan
        monkeypatch.setattr(sensitivity, "variant_plan", lambda v, name: dataclasses.replace(real_plan(v, name), test=()))
        registered = sensitivity_bundle(conn, quick_history)
        with pytest.raises(ValueError, match=r"n60.*test"):
            run_variants(conn, view, registered.bundle, registered.bundle.model.candidate, read_seal(quick_history.cfg.paths.seal), as_of)
    finally:
        conn.close()


def sensitivity_bundle(conn, history):
    from churnrisk.launch import load_registered

    return load_registered(conn, history.cfg)


def test_evaluate_persists_every_variant_of_the_seal_in_eval_variants(quick_history):
    """R3-eval-variants-persistence-untested: after the run that seals the test, ``eval_variants`` holds, sealed, each variant's N, M, rows,
    churn rate, the three AUCs and the four interval limits, with the values the seal holds (6 decimals) and that run's key."""
    seal = read_seal(quick_history.cfg.paths.seal)
    sealed = seal["test"]["variants"]
    conn = connect(quick_history.warehouse)
    try:
        stored = {(v, m, k): (value, run) for v, m, k, value, run in
                  conn.execute("SELECT variant, method, metric, value, run_key FROM eval_variants WHERE seal_state = 'sealed'")}
    finally:
        conn.close()
    assert len(stored) == 11 * len(sealed) == 11 * len(quick_history.view.sensitivity.variants)
    keys = (("all", "n", "n"), ("all", "m", "m"), ("all", "rows", "rows"), ("all", "churn_rate", "churn_rate"), ("model", "auc", "auc_model"),
            ("b2_rfm", "auc", "auc_b2"), ("b_star", "auc", "auc_b_star"), ("b2_rfm", "diff_ci_low", "diff_b2_ci_low"),
            ("b2_rfm", "diff_ci_high", "diff_b2_ci_high"), ("b_star", "diff_ci_low", "diff_b_star_ci_low"), ("b_star", "diff_ci_high", "diff_b_star_ci_high"))
    for variant in sealed:
        for method, metric, key in keys:
            value, run = stored[(variant["variant"], method, metric)]
            assert run == seal["test"]["run_key"]
            assert (value is None and variant[key] is None) or round(value, 6) == round(float(variant[key]), 6), (variant["variant"], metric)
