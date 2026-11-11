"""The real workbook (U05, mark real_data): the canonical lines and the roles of AC04 and AC05 on UCI's file, read once per session from the
pinned zip copied into data/raw/ (``real_canonical``; never downloaded again). Only descriptive counts of the whole file: no cut, no label and
no metric (D19)."""

from __future__ import annotations

from datetime import date

import pytest

from churnrisk.validate import classify_lines

pytestmark = pytest.mark.real_data

ZIP_SHA256 = "572e36277c2390fbfde10664750731e0a86f55e33470d91919085f0408e67bfb"


def test_the_real_canonical_lines_are_the_base_of_project_02(real_canonical):
    result, frame, report = real_canonical
    assert result["sha256"] == ZIP_SHA256 and result["downloaded"] is False and result["built"] is True
    assert report.rows_by_sheet == {"Year 2009-2010": 525_461, "Year 2010-2011": 541_910}
    assert (report.overlap_start, report.overlap_end) == (date(2010, 12, 1), date(2010, 12, 9))
    assert report.overlap_rows == 22_523 and report.canonical_lines == len(frame) == 1_044_848
    assert report.repeated_lines == 11_812
    assert frame["customer_id"].nunique() == 5_942
    assert (frame["invoice_ts"].min().date(), frame["invoice_ts"].max().date()) == (date(2009, 12, 1), date(2011, 12, 9))
    cancellations = frame[frame["invoice"].str.startswith("C")]
    assert len(cancellations) == 19_165 and cancellations["invoice"].nunique() == 8_292


def test_the_real_roles_follow_the_rules_and_the_adjustment_invoices_have_no_customer(real_canonical):
    _result, frame, _report = real_canonical
    roles = classify_lines(frame)
    reasons = roles["exclusion_reason"].value_counts().to_dict()
    assert reasons["no_customer"] == 235_287
    assert reasons["service_code"] == 3_663
    # D51: the lines set aside by their price are the 70 that research counted with project 02's order, and none is set aside by the sign
    # of its quantity (R3-real-data-price-quantity-counts-unproven)
    assert reasons["non_positive_price"] == 70
    assert reasons.get("non_positive_quantity", 0) == 0
    assert reasons.get("gift_voucher", 0) == 0
    assert roles["role"].value_counts().to_dict() == {"purchase": 788_187, "excluded": 239_020, "cancellation": 17_641}
    adjustments = frame["invoice"].str.startswith("A")
    assert int(adjustments.sum()) == 6
    assert roles.loc[adjustments, "exclusion_reason"].tolist() == ["no_customer"] * 6, "no adjustment line has a customer: V20 sets them aside first"
    assert reasons.get("adjustment_invoice", 0) == 0
