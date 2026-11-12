"""The monthly tracking (U19, AC24; RF22; D44): who bought again, whether the window closed, who churned and what the contacts did, with a
censored cut whose label never completes."""

from __future__ import annotations

from datetime import timedelta

import pandas as pd
import pytest

from churnrisk.tracking import track_counts
from tests.fixtures.hand_cases import tracking_case


def labels_of(case) -> pd.Series:
    """The labels of the closed window of 2011-08-01 (no net purchase day in [c, c + 89]): B and D churned, A and C did not."""
    august = min(case.expected)
    return pd.Series([0, 1, 0, 1], index=pd.MultiIndex.from_tuples([(august, c) for c in (1, 2, 3, 4)]), name="churned")


# --- the RED of U19 ------------------------------------------------------------------------------------------------------


def test_returned_and_churned_counts_hand_case_with_a_censored_cut():
    case = tracking_case()
    table = track_counts(case.scores, case.purchase_days, labels_of(case), case.as_of, 90, case.last_date)
    assert table["cut_date"].tolist() == sorted(case.expected)
    for row in table.itertuples(index=False):
        expected = case.expected[row.cut_date]
        got = {k: getattr(row, k) for k in expected}
        got = {k: (None if v is None or v is pd.NA or (isinstance(v, float) and pd.isna(v)) else v) for k, v in got.items()}
        assert got == {**expected, "expected_churners": pytest.approx(expected["expected_churners"])}, row.cut_date
        assert row.as_of_date == case.as_of


def test_a_closed_window_needs_its_labels_and_a_later_date_closes_the_censored_one_never():
    case = tracking_case()
    with pytest.raises(ValueError, match="faltan etiquetas"):
        track_counts(case.scores, case.purchase_days, None, case.as_of, 90, case.last_date)
    # on the last day of the data the window of 2011-10-01 is still open: it is censored and never gets a label
    last = track_counts(case.scores, case.purchase_days, labels_of(case), case.last_date, 90, case.last_date).set_index("cut_date")
    october = max(case.expected)
    assert (bool(last.loc[october, "window_closed"]), bool(last.loc[october, "is_censored"]), pd.isna(last.loc[october, "churned"])) == (False, True, True)
    # before the window of 2011-08-01 closes, nobody has churned yet and a purchase seen so far counts only up to the calculation date
    early = track_counts(case.scores, case.purchase_days, labels_of(case), min(case.expected) + timedelta(days=30), 90, case.last_date).set_index("cut_date")
    august = min(case.expected)
    assert (bool(early.loc[august, "window_closed"]), pd.isna(early.loc[august, "churned"]), int(early.loc[august, "returned"])) == (False, True, 1)


def test_the_label_and_not_the_purchases_seen_later_says_who_churned():
    """C bought on the last day of its window and that purchase was cancelled after the window closed: netted on the calculation date it is
    gone, so C has not come back; its label, netted when the window closed, says it did not churn, and the label is what counts (D06)."""
    case = tracking_case()
    days = case.purchase_days[case.purchase_days["customer_id"] != 3]          # C's purchase of 2011-10-29, cancelled later
    august = track_counts(case.scores, days, labels_of(case), case.as_of, 90, case.last_date).set_index("cut_date").loc[min(case.expected)]
    assert (int(august["returned"]), int(august["churned"]), int(august["scored"])) == (1, 2, 4), "1 came back, 2 churned, 1 neither by now"
