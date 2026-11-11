"""Cancellation netting known on a date (U06, AC05; RF06, D04): last in, first out by customer and product, with only the cancellations
dated on or before the date; a day of purchase is a day with at least one net purchase."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from churnrisk.netting import (
    MATCH_COLUMNS,
    NET_COLUMNS,
    UNMATCHED_COLUMNS,
    NettingResult,
    cancellation_outcomes,
    customer_days,
    net_cancellations,
    netting_inputs,
)
from tests.fixtures import hand_cases
from tests.fixtures.hand_cases import event, split

END = date(2011, 12, 9)


def run(*events, as_of: date = END) -> NettingResult:
    purchases, cancellations = split(*events)
    return net_cancellations(purchases, cancellations, as_of)


def net(result: NettingResult) -> dict[int, int]:
    return dict(zip(result.net_lines["line_id"].tolist(), result.net_lines["net_quantity"].tolist(), strict=True))


def unmatched(result: NettingResult) -> dict[int, int]:
    return dict(zip(result.unmatched["cancel_line_id"].tolist(), result.unmatched["quantity"].tolist(), strict=True))


# --- the RED of U06 ---------------------------------------------------------------------------------------------------


def test_lifo_hand_case():
    """hand_cases.netting_case: the latest purchase first, a remainder unmatched, never an earlier cancellation, the same minute purchase
    first, and a cancellation that is not yet known on the earlier date."""
    case = hand_cases.netting_case()
    for as_of, expected in case.net_quantity.items():
        result = net_cancellations(case.purchases, case.cancellations, as_of)
        assert net(result) == expected, as_of
        known = {line: units for line, units in case.unmatched[as_of].items() if units}
        assert unmatched(result) == known, as_of
    late = net_cancellations(case.purchases, case.cancellations, date(2011, 1, 20))
    pairs = sorted(zip(late.matches["cancel_line_id"], late.matches["purchase_line_id"], late.matches["quantity"], strict=True))
    assert pairs == [(3, 1, 2), (3, 2, 6), (5, 4, 5), (9, 8, 3), (11, 10, 7)], "line 3 takes line 2's 6 units first, then 2 of line 1"
    lines = late.net_lines.set_index("line_id")
    assert lines.loc[1, "allocated_quantity"] == 2 and lines.loc[1, "net_revenue"] == pytest.approx(8.0), "a purchase keeps its own price"


def test_a_cancellation_after_the_date_changes_nothing():
    """Known on a date means dated on or before it (RNF06 b): a later cancellation changes neither the purchases nor the unmatched list, and
    from its own date on it nets."""
    purchase, later = event(1, 7, "71008", "2011-05-20 10:00", 4, 7.0), event(2, 7, "71008", "2011-06-15 11:00", -4, 7.0)
    before = run(purchase, later, as_of=date(2011, 6, 14))
    without = run(purchase, as_of=date(2011, 6, 14))
    pd.testing.assert_frame_equal(before.net_lines, without.net_lines)
    assert before.matches.empty and before.unmatched.empty, "not even reported as unmatched"
    assert net(run(purchase, later, as_of=date(2011, 6, 15))) == {1: 0}, "the day itself counts"
    # a purchase after the date is not in the result either
    assert list(run(purchase, event(3, 7, "71008", "2011-06-02 10:00", 3), as_of=date(2011, 5, 31)).net_lines["line_id"]) == [1]


# --- the other properties of AC05 -----------------------------------------------------------------------------------------


def test_the_result_does_not_depend_on_the_order_of_the_rows():
    case = hand_cases.netting_case()
    expected = net_cancellations(case.purchases, case.cancellations, END)
    shuffled = net_cancellations(case.purchases.sample(frac=1.0, random_state=3), case.cancellations.sample(frac=1.0, random_state=4), END)
    for a, b in zip((expected.net_lines, expected.matches, expected.unmatched), (shuffled.net_lines, shuffled.matches, shuffled.unmatched), strict=True):
        pd.testing.assert_frame_equal(a, b)
    # the same minute: the purchase before its cancellation, whatever their line numbers
    flipped = run(event(5, 7, "71007", "2011-03-28 14:00", 3, 6.2), event(4, 7, "71007", "2011-03-28 14:00", -3, 6.2))
    assert net(flipped) == {5: 0}


def test_identical_purchases_of_the_same_instant_are_taken_in_line_order_whatever_the_row_order():
    """The rows repeated inside a sheet are kept (D03; 11,812 in the real file): two identical purchases of the same instant are told apart by
    their line id, so the latest line is cancelled first in any order of the input."""
    events = (event(1, 7, "10001", "2011-03-01 10:00", 3, 2.0), event(2, 7, "10001", "2011-03-01 10:00", 3, 2.0),
              event(3, 7, "10001", "2011-03-04 10:00", -3, 2.0))
    assert net(run(*events)) == {1: 3, 2: 0}
    assert net(run(*reversed(events))) == {1: 3, 2: 0}


def test_several_cancellations_see_what_the_earlier_ones_left_and_other_customers_are_never_touched():
    result = run(
        event(1, 7, "10001", "2011-03-01 10:00", 10), event(2, 7, "10001", "2011-03-02 10:00", 4), event(6, 8, "10001", "2011-03-02 11:00", 9),
        event(3, 7, "10001", "2011-03-03 10:00", -3), event(4, 7, "10001", "2011-03-04 10:00", -3), event(5, 7, "10001", "2011-03-05 10:00", -3),
    )
    pairs = sorted(zip(result.matches["cancel_line_id"], result.matches["purchase_line_id"], result.matches["quantity"], strict=True))
    assert pairs == [(3, 2, 3), (4, 1, 2), (4, 2, 1), (5, 1, 3)]
    assert net(result) == {1: 5, 2: 0, 6: 9}


def test_the_value_of_a_match_is_the_purchase_price_and_of_a_remainder_the_cancellation_price():
    result = run(event(1, 7, "10001", "2011-03-01 10:00", 2, 2.0), event(2, 7, "10001", "2011-03-02 10:00", -3, 2.5))
    assert result.matches["value_gbp"].tolist() == [4.0]
    assert result.unmatched[["cancel_line_id", "quantity", "value_gbp"]].values.tolist() == [[2, 1, 2.5]]


def test_the_shapes_of_the_result_and_the_input_are_kept():
    purchases, cancellations = split(event(9, 7, "10001", "2011-03-01 10:00", 5, 2.0), event(3, 8, "10002", "2011-03-02 10:00", 4, 1.0),
                                     event(11, 7, "10001", "2011-03-03 10:00", -2, 2.0))
    before = purchases.copy(), cancellations.copy()
    result = net_cancellations(purchases, cancellations, END)
    pd.testing.assert_frame_equal(purchases, before[0])
    pd.testing.assert_frame_equal(cancellations, before[1])
    assert list(result.net_lines.columns) == NET_COLUMNS and list(result.matches.columns) == MATCH_COLUMNS
    assert list(result.unmatched.columns) == UNMATCHED_COLUMNS and result.net_lines["line_id"].tolist() == [3, 9]
    empty = net_cancellations(purchases.iloc[:0], cancellations.iloc[:0], END)
    assert empty.net_lines.empty and list(empty.net_lines.columns) == NET_COLUMNS and empty.matches.empty and empty.unmatched.empty


@pytest.mark.parametrize(("which", "quantity", "message"), [("purchases", 0, "positiva"), ("cancellations", 2, "negativa")])
def test_a_quantity_of_the_wrong_sign_or_a_missing_column_is_refused(which, quantity, message):
    purchases, cancellations = split(event(1, 7, "10001", "2011-03-01 10:00", 2), event(2, 7, "10001", "2011-03-02 10:00", -1))
    frames = {"purchases": purchases, "cancellations": cancellations}
    frames[which] = frames[which].assign(quantity=quantity)
    with pytest.raises(ValueError, match=message):
        net_cancellations(frames["purchases"], frames["cancellations"], END)
    with pytest.raises(ValueError, match="faltan las columnas price"):
        net_cancellations(purchases.drop(columns="price"), cancellations, END)


def test_a_day_of_purchase_is_a_day_with_a_net_purchase():
    result = run(
        event(1, 7, "A", "2011-03-01 10:00", 2, 1.5), event(2, 7, "B", "2011-03-01 12:00", 1, 4.0), event(3, 7, "A", "2011-03-02 10:00", 5),
        event(4, 7, "A", "2011-03-03 10:00", -5), event(5, 8, "C", "2011-03-01 10:00", 3, 2.0),
    )
    days = customer_days(result.net_lines)
    assert list(days.columns) == ["customer_id", "day", "net_revenue", "units", "lines"]
    assert days.values.tolist() == [
        [7, pd.Timestamp("2011-03-01"), 7.0, 3, 2], [8, pd.Timestamp("2011-03-01"), 6.0, 3, 1],
    ], "the 2nd of March was cancelled down to zero: it is not a day of purchase"


def test_each_cancellation_is_complete_partial_or_without_a_purchase():
    """The unit of project 02's D04 (per cancellation line, not per pair): the reconciliation of U06 counts with it."""
    case = hand_cases.netting_case()
    result = net_cancellations(case.purchases, case.cancellations, date(2011, 1, 20))
    outcomes = cancellation_outcomes(case.cancellations, result, date(2011, 1, 20))
    assert outcomes.set_index("cancel_line_id")["outcome"].to_dict() == {3: "complete", 5: "partial", 6: "unmatched", 9: "complete", 11: "complete"}
    assert outcomes.set_index("cancel_line_id").loc[5, ["cancelled", "matched", "unmatched"]].tolist() == [8, 5, 3]
    early = cancellation_outcomes(case.cancellations, net_cancellations(case.purchases, case.cancellations, date(2011, 1, 10)), date(2011, 1, 10))
    assert 11 not in set(early["cancel_line_id"]), "a cancellation not yet known has no outcome"


def test_the_inputs_of_the_netting_are_the_purchases_and_cancellations_of_the_roles():
    frame = pd.DataFrame({
        "line_id": [1, 2, 3, 4], "invoice": ["500", "C501", "502", "C503"], "stock_code": ["10001", "10001", "POST", "10001"],
        "quantity": [3, -1, 1, -2], "price": [2.0, 2.0, 18.0, 0.0], "customer_id": pd.array([90001, 90001, 90001, 90001], dtype="Int64"),
        "code_kind": ["product", "product", "service", "product"], "invoice_ts": pd.to_datetime(["2011-01-01"] * 4),
        "invoice_date": pd.to_datetime(["2011-01-01"] * 4),
    })
    purchases, cancellations = netting_inputs(frame)
    assert purchases["line_id"].tolist() == [1] and cancellations["line_id"].tolist() == [2], "the service line and the «C» line with no price are set aside"
    assert purchases["customer_id"].dtype == "int64"


def test_outcomes_of_a_result_netted_on_another_date_or_with_other_cancellations_are_refused():
    """R3-cancellation-outcomes-consistency-check-untested: the outcomes read a netting result against the cancellations known on a date; a
    result netted on another date, or with other cancellations, does not add up (assigned plus unassigned is not what was cancelled) and is a
    ValueError, never a silent count."""
    case = hand_cases.netting_case()
    late, early = date(2011, 1, 20), date(2011, 1, 10)
    message = "lo asignado más lo no asignado no es lo anulado"
    with pytest.raises(ValueError, match=message):
        cancellation_outcomes(case.cancellations, net_cancellations(case.purchases, case.cancellations, early), late)
    fewer = case.cancellations[case.cancellations["line_id"] != 5]
    with pytest.raises(ValueError, match=message):
        cancellation_outcomes(case.cancellations, net_cancellations(case.purchases, fewer, late), late)
    assert len(cancellation_outcomes(case.cancellations, net_cancellations(case.purchases, case.cancellations, late), late)) == 5, "the pair that agrees"
