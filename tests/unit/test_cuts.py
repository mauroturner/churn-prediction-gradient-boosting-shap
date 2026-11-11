"""The cuts, the population and the label (U10, AC10; RF11, RF12, D06, D07): a cut is day 1 of a month; its population are the customers
with a net purchase day in [c - M, c - 1], netted with what is known on c - 1; its label is no net purchase day in [c, c + N - 1], netted
with what is known on c + N - 1."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from churnrisk.config import SealedConfig
from churnrisk.cuts import cut_dates, label, label_end, population
from churnrisk.netting import customer_days, net_cancellations
from tests.fixtures import hand_cases


def days_known(case, as_of: date) -> pd.DataFrame:
    return customer_days(net_cancellations(case.purchases, case.cancellations, as_of).net_lines)


def test_population_and_label_hand_case():
    """hand_cases.cuts_case: five customers at two cuts, with cancellations known before, inside and after the windows."""
    case = hand_cases.cuts_case()
    for cut, expected in case.population.items():
        members = population(days_known(case, cut - timedelta(days=1)), cut, case.active_days)
        assert tuple(members) == expected, cut
        end = label_end(cut, case.horizon_days)
        churned = label(days_known(case, end), cut, case.horizon_days, members)
        assert churned.to_dict() == case.labels[cut], cut
        assert churned.dtype == "int64" and churned.index.name == "customer_id"


def test_a_window_is_n_days_from_the_cut_and_the_population_m_days_before_it():
    case = hand_cases.cuts_case()
    assert label_end(date(2011, 3, 1), 90) == date(2011, 5, 29) and label_end(date(2011, 4, 1), 90) == date(2011, 6, 29)
    days = pd.DataFrame({"customer_id": [1, 2, 3, 4], "day": pd.to_datetime(["2010-12-01", "2010-11-30", "2011-02-28", "2011-03-01"])})
    assert list(population(days, date(2011, 3, 1), 90)) == [1, 3], "[2010-12-01, 2011-02-28]: the first day is in, the cut itself is not"
    after = pd.DataFrame({"customer_id": [1, 3], "day": pd.to_datetime(["2011-05-29", "2011-05-30"])})
    assert label(after, date(2011, 3, 1), 90, pd.Index([1, 3], name="customer_id")).to_dict() == {1: 0, 3: 1}, "the last day of the window counts"
    assert len(population(days_known(case, date(2009, 12, 31)), date(2010, 1, 1), 90)) == 0


def test_the_cuts_are_the_first_days_from_first_cut_to_last_cut(cfg):
    cuts = cut_dates(SealedConfig.of(cfg, "c" * 64))
    assert cuts[0] == date(2010, 6, 1) and cuts[-1] == date(2011, 12, 1) and len(cuts) == 19
    assert all(c.day == 1 for c in cuts) and cuts == sorted(set(cuts))
