"""The real training cuts (U10, mark real_data; AC10): the populations and the churn rates of requirements.md, section 4, from the real
canonical lines with the cuts' own functions. Only lines dated before 2011-03-01 are netted, so no line of a validation or test window
is used, as in the planner's check (D19)."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from churnrisk.cuts import label, label_end, population
from churnrisk.netting import customer_days, net_cancellations, netting_inputs

pytestmark = pytest.mark.real_data

# cut -> (active in the 90 days before, churn rate with N = 90), requirements.md section 4
TRAINING = {
    date(2010, 6, 1): (2_012, 0.443), date(2010, 7, 1): (2_013, 0.429), date(2010, 8, 1): (1_993, 0.359), date(2010, 9, 1): (1_925, 0.312),
    date(2010, 10, 1): (2_018, 0.365), date(2010, 11, 1): (2_477, 0.463), date(2010, 12, 1): (2_859, 0.579),
}


def test_the_real_training_cuts_have_the_populations_and_the_rates_of_the_requirements(real_canonical):
    _result, frame, _report = real_canonical
    before = frame[frame["invoice_date"] < pd.Timestamp(2011, 3, 1)]
    purchases, cancellations = netting_inputs(before)
    rows, churned, customers = 0, 0, set()
    for cut, (active, rate) in TRAINING.items():
        end = label_end(cut, 90)
        assert end < date(2011, 3, 1), "the window of a training cut closes before the first validation cut"
        members = population(customer_days(net_cancellations(purchases, cancellations, cut - timedelta(days=1)).net_lines), cut, 90)
        labels = label(customer_days(net_cancellations(purchases, cancellations, end).net_lines), cut, 90, members)
        assert (len(members), round(float(labels.mean()), 3)) == (active, rate), cut
        rows, churned, customers = rows + len(labels), churned + int(labels.sum()), customers | set(members)
    assert (rows, len(customers), round(churned / rows, 3)) == (15_297, 3_942, 0.432)
