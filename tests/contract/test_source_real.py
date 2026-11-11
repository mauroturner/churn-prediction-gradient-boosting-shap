"""The real workbook (U05, mark real_data): the canonical lines and the roles of AC04 and AC05 on UCI's file, read from the pinned zip copied
into data/raw/ (never downloaded again). Only descriptive counts of the whole file: no cut, no label and no metric (D19)."""

from __future__ import annotations

import dataclasses
import shutil
import types
from datetime import date

import pytest

from churnrisk.ingest import fetch_source, read_canonical
from churnrisk.validate import classify_lines

pytestmark = pytest.mark.real_data

ZIP_SHA256 = "572e36277c2390fbfde10664750731e0a86f55e33470d91919085f0408e67bfb"


@pytest.fixture(scope="module")
def real(cfg, project_root, tmp_path_factory):
    """The real canonical lines, built once from a copy of the pinned zip in a folder of the test's own."""
    folder = tmp_path_factory.mktemp("real")
    (folder / "raw").mkdir()
    shutil.copyfile(project_root / "data" / "raw" / "online_retail_ii.zip", folder / "raw" / "online_retail_ii.zip")
    paths = dataclasses.replace(cfg.paths, raw_dir=folder / "raw", interim_dir=folder / "interim")
    result = fetch_source(types.SimpleNamespace(cfg=dataclasses.replace(cfg, paths=paths)))
    frame, report = read_canonical(folder / "interim")
    return result, frame, report


def test_the_real_canonical_lines_are_the_base_of_project_02(real):
    result, frame, report = real
    assert result["sha256"] == ZIP_SHA256 and result["downloaded"] is False and result["built"] is True
    assert report.rows_by_sheet == {"Year 2009-2010": 525_461, "Year 2010-2011": 541_910}
    assert (report.overlap_start, report.overlap_end) == (date(2010, 12, 1), date(2010, 12, 9))
    assert report.overlap_rows == 22_523 and report.canonical_lines == len(frame) == 1_044_848
    assert report.repeated_lines == 11_812
    assert frame["customer_id"].nunique() == 5_942
    assert (frame["invoice_ts"].min().date(), frame["invoice_ts"].max().date()) == (date(2009, 12, 1), date(2011, 12, 9))
    cancellations = frame[frame["invoice"].str.startswith("C")]
    assert len(cancellations) == 19_165 and cancellations["invoice"].nunique() == 8_292


def test_the_real_roles_follow_the_rules_and_the_adjustment_invoices_have_no_customer(real):
    _result, frame, _report = real
    roles = classify_lines(frame)
    reasons = roles["exclusion_reason"].value_counts().to_dict()
    assert reasons["no_customer"] == 235_287
    assert reasons["service_code"] == 3_663
    assert reasons.get("gift_voucher", 0) == 0
    adjustments = frame["invoice"].str.startswith("A")
    assert int(adjustments.sum()) == 6
    assert roles.loc[adjustments, "exclusion_reason"].tolist() == ["no_customer"] * 6, "no adjustment line has a customer: V20 sets them aside first"
    assert reasons.get("adjustment_invoice", 0) == 0
    print("REAL ROLES", roles["role"].value_counts().to_dict(), reasons)
