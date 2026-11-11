"""The real netting (U06, mark real_data; AC05, D04 [Verificar en U06]): on the canonical base, the counts of project 02 by cancellation line,
and the difference with the counts that its D04 cites, explained (D52). Only descriptive counts of the whole file at its last date: no cut,
no label and no metric (D19)."""

from __future__ import annotations

from datetime import date

import pytest

from churnrisk.netting import cancellation_outcomes, customer_days, net_cancellations, netting_inputs

pytestmark = pytest.mark.real_data

END = date(2011, 12, 9)


def outcomes_of(frame):
    purchases, cancellations = netting_inputs(frame)
    result = net_cancellations(purchases, cancellations, END)
    outcomes = cancellation_outcomes(cancellations, result, END)["outcome"].value_counts().to_dict()
    return purchases, cancellations, result, outcomes


def test_the_real_netting_gives_project_02s_counts_on_the_canonical_base_and_its_d04_counts_without_the_internal_repeats(real_canonical):
    _result, frame, _report = real_canonical
    purchases, cancellations, result, outcomes = outcomes_of(frame)
    assert (len(purchases), len(cancellations)) == (788_187, 17_641)
    # project 02 on the same canonical base (its tests/e2e/test_load_real.py): 16,427 matches and 1,706 lines with units left
    assert len(result.matches) == 16_427 and len(result.unmatched) == 1_706
    assert outcomes == {"complete": 15_935, "partial": 116, "unmatched": 1_590}
    days = customer_days(result.net_lines)
    assert len(days) == 32_703 and days["net_revenue"].sum() == pytest.approx(16_391_525.27, abs=0.01), "project 02's customer days and net revenue"
    assert result.net_lines.loc[result.net_lines["quantity"].isin([80_995, 74_215]), "net_quantity"].tolist() == [0, 0], "the two giant lines net to zero"
    # project 02's D04 counted 15,875 complete, 126 partial and 1,585 without a purchase over 17,586 cancellations: the base without the
    # 11,812 rows repeated inside a sheet, which D03 keeps (55 of them are cancellations). Without them the netting gives exactly those (D52).
    plain = frame[~frame["is_repeated_line"]].reset_index(drop=True)
    _p, plain_cancellations, _r, plain_outcomes = outcomes_of(plain)
    assert len(plain_cancellations) == 17_586 and plain_outcomes == {"complete": 15_875, "partial": 126, "unmatched": 1_585}
