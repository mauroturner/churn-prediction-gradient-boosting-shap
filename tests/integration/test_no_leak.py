"""No leakage by time (U11, AC13; RNF06 a and b): the features that the warehouse holds for a cut are the ones the data truncated the day
before gives, whatever the warehouse has loaded since; deleting, changing or adding lines and cancellations from the cut on changes none
of them."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from churnrisk.config import SealedConfig
from churnrisk.cuts import build_cuts, cut_dates, population
from churnrisk.deliveries import delivery_plan, delivery_rows
from churnrisk.features import compute_features, known_before, read_features
from churnrisk.netting import netting_inputs
from churnrisk.schema import FEATURE_COLUMNS
from churnrisk.warehouse import connect, load_delivery
from tests.fixtures.perturb import perturbed

SHA = "d" * 64


def test_features_at_a_cut_equal_those_from_data_truncated_the_day_before(cfg, canonical, loaded_masters, copy_of):
    """Every delivery loaded first, then every cut built at once at the last date: the warehouse holds up to 18 months after a cut, and each
    cut's features are still exactly those computed from the canonical lines dated before it."""
    frame, _report = canonical
    view = SealedConfig.of(cfg, SHA)
    plan = delivery_plan(cfg)
    conn = connect(copy_of(loaded_masters(len(plan))[0]))
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(cut_features)")}
        assert set(FEATURE_COLUMNS) <= columns, f"the warehouse holds the features of each cut; missing {sorted(set(FEATURE_COLUMNS) - columns)}"
        build_cuts(conn, plan[-1].as_of, view, "all")
        stored = read_features(conn)
    finally:
        conn.close()
    assert sorted(set(stored.index.get_level_values("cut_date"))) == cut_dates(view)
    every_purchase, every_cancellation = netting_inputs(frame)   # a line's role depends on that line only, so truncating after it is the same
    for cut in cut_dates(view):
        purchases, cancellations = (lines[lines["invoice_date"] < pd.Timestamp(cut)].reset_index(drop=True) for lines in (every_purchase, every_cancellation))
        days, lines = known_before(purchases, cancellations, cut)
        expected = compute_features(days, lines, cut, population(days, cut, view.label.active_days), view)
        pd.testing.assert_frame_equal(stored.xs(cut, level="cut_date"), expected, check_exact=True, obj=str(cut))


def test_lines_and_cancellations_from_the_cut_on_change_nothing_at_that_date(cfg, canonical, loaded_masters, copy_of, tmp_path):
    frame, _report = canonical
    view = SealedConfig.of(cfg, SHA)
    launch = delivery_plan(cfg)[0]
    cut = date(2011, 3, 1)
    conn = connect(copy_of(loaded_masters(1)[0]))
    try:
        build_cuts(conn, launch.as_of, view, "r1")
        base = read_features(conn)
    finally:
        conn.close()
    customers = sorted(base.xs(cut, level="cut_date").index)[:25]
    lines = perturbed(delivery_rows(launch, frame), cut, customers)
    conn = connect(tmp_path / "perturbed.sqlite")
    try:
        load_delivery(conn, lines, launch, "p1", sha256="f" * 64)
        build_cuts(conn, launch.as_of, view, "p1")
        got = read_features(conn)
    finally:
        conn.close()
    for c in cut_dates(view):
        if c <= cut:
            pd.testing.assert_frame_equal(got.xs(c, level="cut_date"), base.xs(c, level="cut_date"), check_exact=True, obj=str(c))
    later = cut + timedelta(days=31)
    assert not got.xs(later, level="cut_date").equals(base.xs(later, level="cut_date")), "control: the perturbation does change the next cut"
