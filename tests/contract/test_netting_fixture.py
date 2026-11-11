"""The netting on the synthetic fixture (U06, AC05): the product's netting agrees with the fixture's own oracle (a LIFO written apart, in
tests/fixtures/make_fixture.py) on the net purchase days of every customer known on the day before every cut and at the end of the data, and
its properties hold on every line."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from churnrisk.netting import cancellation_outcomes, customer_days, net_cancellations, netting_inputs
from churnrisk.validate import classify_lines
from tests.fixtures.make_fixture import WINDOW_END, _event_order, _unmatched_cancellations, cut_dates, net_purchase_days


def oracle_lines(frame: pd.DataFrame) -> list[dict]:
    roles = classify_lines(frame)["role"]
    lines = [
        {"order": i, "customer": None if pd.isna(c) else int(c), "code": code, "qty": int(q), "ts": ts, "invoice_date": day.date(), "role": role}
        for i, (c, code, q, ts, day, role) in enumerate(zip(frame["customer_id"], frame["stock_code"], frame["quantity"], frame["invoice_ts"],
                                                             frame["invoice_date"], roles, strict=True))
    ]
    return sorted(lines, key=_event_order)


def test_the_net_purchase_days_agree_with_the_fixture_oracle_before_every_cut_and_at_the_end(canonical, fixture_truth):
    frame, _report = canonical
    lines = oracle_lines(frame)
    purchases, cancellations = netting_inputs(frame)
    for as_of in [cut - timedelta(days=1) for cut in cut_dates()] + [WINDOW_END]:
        days = customer_days(net_cancellations(purchases, cancellations, as_of).net_lines)
        mine = {customer: set(group.dt.date) for customer, group in days.groupby("customer_id")["day"]}
        assert mine == net_purchase_days(lines, as_of), as_of
    result = net_cancellations(purchases, cancellations, WINDOW_END)
    assert len(result.unmatched) == _unmatched_cancellations(lines, WINDOW_END) == fixture_truth.unmatched_cancellations_at_end


def test_the_properties_of_the_netting_hold_on_every_line_of_the_fixture(canonical):
    frame, _report = canonical
    purchases, cancellations = netting_inputs(frame)
    result = net_cancellations(purchases, cancellations, WINDOW_END)
    net = result.net_lines
    assert len(net) == len(purchases) and ((net["net_quantity"] >= 0) & (net["net_quantity"] <= net["quantity"])).all()
    outcomes = cancellation_outcomes(cancellations, result, WINDOW_END)
    assert (outcomes["matched"] + outcomes["unmatched"] == outcomes["cancelled"]).all() and len(outcomes) == len(cancellations)
    assert int(net["allocated_quantity"].sum()) == int(result.matches["quantity"].sum()) == int(outcomes["matched"].sum())
    # a purchase never takes a cancellation that came before it, and never one of another customer or product
    pairs = result.matches.merge(cancellations.add_prefix("c_"), left_on="cancel_line_id", right_on="c_line_id").merge(
        purchases.add_prefix("p_"), left_on="purchase_line_id", right_on="p_line_id")
    assert (pairs["p_invoice_ts"] <= pairs["c_invoice_ts"]).all()
    assert (pairs["p_customer_id"] == pairs["c_customer_id"]).all() and (pairs["p_stock_code"] == pairs["c_stock_code"]).all()
    # the order of the rows changes nothing, and a cut netted with what is known the day before ignores every later cancellation
    shuffled = net_cancellations(purchases.sample(frac=1.0, random_state=7), cancellations.sample(frac=1.0, random_state=8), WINDOW_END)
    pd.testing.assert_frame_equal(shuffled.net_lines, net)
    pd.testing.assert_frame_equal(shuffled.matches, result.matches)
    pd.testing.assert_frame_equal(shuffled.unmatched, result.unmatched)
    cut = date(2011, 3, 1)
    later_removed = cancellations[cancellations["invoice_date"] < pd.Timestamp(cut)]
    pd.testing.assert_frame_equal(net_cancellations(purchases, cancellations, cut - timedelta(days=1)).net_lines,
                                  net_cancellations(purchases, later_removed, cut - timedelta(days=1)).net_lines)
