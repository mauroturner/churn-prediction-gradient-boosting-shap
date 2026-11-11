"""The source as a contract (U05, item 2: the zip and the workbook are untrusted): extraction, reading, the canonical lines and the roles
(AC03, AC04 and AC05 for the roles; RF03-RF05; V01-V06)."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
import types
import zipfile
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import pytest

from churnrisk.ingest import (
    ATTRIBUTION,
    CANONICAL_NAME,
    INTERIM_MANIFEST,
    MANIFEST_NAME,
    SourceManifest,
    extract_member,
    fetch_source,
    read_canonical,
    read_source,
    write_source_manifest,
)
from churnrisk.schema import CANONICAL_SCHEMA, FEATURE_COLUMNS, IDENTIFIER_COLUMNS, LABEL_COLUMNS, SourceError, code_kind
from churnrisk.validate import EXCLUSION_RULES, classify_lines
from tests.fixtures.http_server import FileServer
from tests.fixtures.make_fixture import CASE_BASE, MEMBER, OVERLAP_END, OVERLAP_START

LOCAL = frozenset({"127.0.0.1"})
# each blocking rule of the source and the variants that must fail it (two_customers_one_invoice is a rule of the delivery, V13, in U08)
KIND_RULE = {
    "wrong_hash": "V01", "oversize": "V02", "extra_member": "V03", "member_with_path": "V03", "inflated_member": "V03",
    "missing_sheet": "V04", "renamed_sheet": "V04", "extra_column": "V04", "missing_column": "V04", "renamed_column": "V04",
    "bad_date": "V05", "bad_quantity": "V05", "six_digit_customer": "V05", "overlap_mismatch": "V06",
}
FIXTURE_ID = re.compile(r"\b9\d{4}\b")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def snapshot(folder: Path) -> dict[str, str]:
    if not folder.exists():
        return {}
    return {p.relative_to(folder).as_posix(): sha(p.read_bytes()) for p in sorted(folder.rglob("*")) if p.is_file()}


def ctx_for(cfg, tmp_path: Path, **source):
    paths = dataclasses.replace(cfg.paths, raw_dir=tmp_path / "raw", interim_dir=tmp_path / "interim")
    return types.SimpleNamespace(cfg=dataclasses.replace(cfg, paths=paths, source=dataclasses.replace(cfg.source, **source)))


def local_ctx(cfg, tmp_path: Path, zip_path: Path):
    return ctx_for(cfg, tmp_path, mode="local", url="", accepted_sha256="", member_sha256="", local_path=zip_path)


def member_hash(zip_path: Path) -> str:
    with zipfile.ZipFile(zip_path) as archive:
        return sha(archive.read(MEMBER))


# --- AC03: every malformed variant fails its rule and writes nothing ---------------------------------------------------


@pytest.mark.parametrize("kind", sorted(KIND_RULE))
def test_each_malformed_variant_fails_its_rule_and_writes_nothing(cfg, tmp_path, malformed, tiny_zip, kind):
    ctx = local_ctx(cfg, tmp_path, malformed(kind))
    if kind == "wrong_hash":   # a local source whose first hash was registered: another one is V01
        registered = SourceManifest("local", str(tiny_zip), sha(tiny_zip.read_bytes()), tiny_zip.stat().st_size, "2026-11-11T10:00:00+00:00", str(tiny_zip))
        write_source_manifest(tmp_path / "raw" / MANIFEST_NAME, registered)
    before = snapshot(tmp_path)
    with pytest.raises(SourceError) as error:
        fetch_source(ctx)
    assert error.value.rule_id == KIND_RULE[kind], str(error.value)
    assert error.value.problems and all(p["rule_id"] == KIND_RULE[kind] for p in error.value.problems)
    assert snapshot(tmp_path) == before, "no canonical lines, no manifest, no extracted member"
    assert not (tmp_path / "interim").exists()
    shown = str(error.value) + json.dumps(error.value.problems, default=str)
    assert not FIXTURE_ID.search(shown) and "123456" not in shown, "a message never carries a customer number"
    # the check that refuses each variant is the one that reads what the variant damaged
    expected_words = {
        "inflated_member": "declara", "extra_column": "exactamente las columnas", "missing_column": "exactamente las columnas",
        "renamed_column": "exactamente las columnas", "missing_sheet": "no tiene la hoja", "renamed_sheet": "no tiene la hoja",
    }
    if kind in expected_words:
        assert expected_words[kind] in str(error.value), str(error.value)


def test_the_member_hash_is_checked_in_http_mode_and_a_refused_member_leaves_nothing(cfg, tmp_path, tiny_zip):
    good = member_hash(tiny_zip)
    out = tmp_path / "out"
    path = extract_member(tiny_zip, MEMBER, cfg.source.max_member_bytes, good, out_dir=out)
    assert path.parent == out and sha(path.read_bytes()) == good
    path.unlink()
    with pytest.raises(SourceError, match=r"^V03:.*huella") as error:
        extract_member(tiny_zip, MEMBER, cfg.source.max_member_bytes, "0" * 64, out_dir=out)
    assert error.value.problems[0]["actual"] == good
    with pytest.raises(SourceError, match=r"^V03:.*límite"):
        extract_member(tiny_zip, MEMBER, 1000, "", out_dir=out)
    assert snapshot(out) == {}


def workbook_with(tmp_path: Path, cells: dict[tuple[int, int], object]) -> Path:
    """A minimal two-sheet workbook with three valid rows in sheet 1, one in sheet 2, and the given cells (row from 2, column from 1) replaced."""
    import openpyxl
    from datetime import datetime

    book = openpyxl.Workbook()
    first = book.active
    first.title = "Year 2009-2010"
    second = book.create_sheet("Year 2010-2011")
    header = ["Invoice", "StockCode", "Description", "Quantity", "InvoiceDate", "Price", "Customer ID", "Country"]
    for sheet in (first, second):
        sheet.append(header)
    for day in (1, 2, 3):
        first.append([489433 + day, "85123A", "HEART", 6, datetime(2010, 1, day, 10, 0), 2.55, 90001.0, "United Kingdom"])
    second.append([500000, "85123A", "HEART", 6, datetime(2011, 1, 5, 10, 0), 2.55, 90001.0, "United Kingdom"])
    for (row, column), value in cells.items():
        first.cell(row, column).value = value
    path = tmp_path / "book.xlsx"
    book.save(path)
    return path


@pytest.mark.parametrize(("cells", "columns"), [
    ({(2, 1): None}, ["Invoice"]),
    ({(2, 2): "   "}, ["StockCode"]),
    ({(2, 4): 2.5, (3, 4): "6"}, ["Quantity"]),
    ({(2, 5): "2010-01-01"}, ["InvoiceDate"]),
    ({(2, 6): "2.55"}, ["Price"]),
    ({(2, 7): 9001.0, (3, 7): 90001.5, (4, 7): "ABC"}, ["Customer ID"]),
    ({(2, 1): "", (2, 6): None}, ["Invoice", "Price"]),
])
def test_every_type_rule_of_v05_names_its_column_and_counts_its_values(cfg, tmp_path, cells, columns):
    with pytest.raises(SourceError, match="^V05:") as error:
        read_source(workbook_with(tmp_path, cells), cfg)
    assert [p["column"] for p in error.value.problems] == columns
    assert sum(p["count"] for p in error.value.problems) == len(cells)


def test_a_valid_minimal_workbook_gives_text_invoices_and_codes_and_whole_customer_numbers(cfg, tmp_path):
    frame, report = read_source(workbook_with(tmp_path, {(3, 7): None}), cfg)
    assert report.canonical_lines == 4 and report.overlap_rows == 0 and (report.overlap_start, report.overlap_end) == (None, None)
    assert frame["invoice"].map(type).eq(str).all() and frame["stock_code"].map(type).eq(str).all()
    assert frame["customer_id"].isna().tolist() == [False, True, False, False] and frame["customer_id"].dropna().tolist() == [90001] * 3


# --- AC04: the canonical lines -------------------------------------------------------------------------------------


def test_overlap_copies_are_removed_and_internal_repeats_kept(canonical, fixture_truth):
    frame, report = canonical
    truth = fixture_truth
    assert report.rows_by_sheet == truth.rows_by_sheet
    assert (report.overlap_start, report.overlap_end) == (OVERLAP_START, OVERLAP_END)
    assert report.overlap_rows == truth.overlap_rows > 0, "sheet 2's copies of the shared days are dropped"
    assert len(frame) == report.canonical_lines == truth.canonical_lines == sum(truth.rows_by_sheet.values()) - truth.overlap_rows
    second = frame[frame["sheet"] == 2]
    assert second["invoice_ts"].min().date() > OVERLAP_END and frame[frame["sheet"] == 1]["invoice_ts"].max().date() == OVERLAP_END
    assert int(frame["is_repeated_line"].sum()) == report.repeated_lines == truth.repeated_lines == 9, "repeats inside a sheet are kept and flagged"
    repeated = frame[frame["is_repeated_line"]]
    columns = ["invoice", "stock_code", "description", "quantity", "invoice_ts", "price", "customer_id", "country"]
    for _index, row in repeated.iterrows():
        twins = frame[(frame["sheet"] == row["sheet"]) & (frame[columns].fillna(-1) == row[columns].fillna(-1)).all(axis=1)]
        assert len(twins) >= 2 and not twins.iloc[0]["is_repeated_line"]
    assert frame["line_id"].is_unique and (frame["line_id"] == frame["sheet"] * 10_000_000 + frame["source_row"]).all()
    assert set(frame["customer_id"].dropna().astype(int)) == set(truth.customer_ids)
    assert (frame["invoice_date"] == frame.groupby("invoice")["invoice_ts"].transform("min").dt.normalize()).all()
    two_dates = frame[frame["invoice_ts"].dt.normalize() != frame["invoice_date"]]
    assert len(two_dates) == 1 and int(two_dates["customer_id"].iloc[0]) == CASE_BASE + 10, "the invoice across midnight takes its first date"
    assert list(frame.columns) == CANONICAL_SCHEMA.names
    assert frame["code_kind"].tolist() == [code_kind(c) for c in frame["stock_code"]]


def test_the_canonical_lines_are_written_with_their_manifest_last_and_a_second_run_changes_nothing(cfg, tmp_path, tiny_zip):
    ctx = local_ctx(cfg, tmp_path, tiny_zip)
    first = fetch_source(ctx)
    assert first["built"] is True and first["sha256"] == sha(tiny_zip.read_bytes()) and first["downloaded"] is False
    interim, raw = tmp_path / "interim", tmp_path / "raw"
    assert sorted(p.name for p in interim.iterdir()) == [INTERIM_MANIFEST, CANONICAL_NAME]
    assert sorted(p.name for p in raw.iterdir()) == [MANIFEST_NAME], "the extracted member is not kept"
    manifest = json.loads((interim / INTERIM_MANIFEST).read_text(encoding="utf-8"))
    assert manifest == {"version": 1, "source_sha256": first["sha256"], "files": {CANONICAL_NAME: sha((interim / CANONICAL_NAME).read_bytes())}}
    table = pq.read_table(interim / CANONICAL_NAME)
    assert table.schema.remove_metadata() == CANONICAL_SCHEMA and table.num_rows == first["lines"]
    metadata = table.schema.metadata
    assert metadata[b"churnrisk.source_sha256"] == first["sha256"].encode() and metadata[b"churnrisk.attribution"] == ATTRIBUTION.encode()
    assert "Chen, D. (2012). Online Retail II [Dataset]. UCI Machine Learning Repository. https://doi.org/10.24432/C5CG6D" in ATTRIBUTION
    frame, report = read_canonical(interim)
    assert len(frame) == first["lines"] and report.canonical_lines == first["lines"]
    before = snapshot(tmp_path)
    second = fetch_source(ctx)
    assert second["built"] is False and second["lines"] == first["lines"]
    assert snapshot(tmp_path) == before
    for key in ("zip_path", "sha256", "size", "downloaded", "built", "lines"):
        assert key in second
    assert not FIXTURE_ID.search(json.dumps(first, default=str)), "the task's result is part of the run's state: no customer number"


def test_canonical_lines_that_do_not_match_their_manifest_are_rebuilt(cfg, tmp_path, tiny_zip):
    ctx = local_ctx(cfg, tmp_path, tiny_zip)
    fetch_source(ctx)
    canonical = tmp_path / "interim" / CANONICAL_NAME
    good = canonical.read_bytes()
    canonical.write_bytes(good[:-10] + b"0123456789")
    with pytest.raises(ValueError, match="manifiesto"):
        read_canonical(tmp_path / "interim")
    assert fetch_source(ctx)["built"] is True and canonical.read_bytes() == good
    (tmp_path / "interim" / INTERIM_MANIFEST).unlink()
    assert fetch_source(ctx)["built"] is True


def test_local_mode_registers_the_first_hash_only_after_a_clean_read(cfg, tmp_path, tiny_zip, malformed):
    bad = local_ctx(cfg, tmp_path, malformed("bad_quantity"))
    with pytest.raises(SourceError, match="V05"):
        fetch_source(bad)
    assert not (tmp_path / "raw" / MANIFEST_NAME).exists(), "an unreadable first zip registers nothing"
    fetch_source(local_ctx(cfg, tmp_path, tiny_zip))
    registered = json.loads((tmp_path / "raw" / MANIFEST_NAME).read_text(encoding="utf-8"))["source"]
    assert registered["sha256"] == sha(tiny_zip.read_bytes()) and registered["mode"] == "local"


def test_http_mode_downloads_once_checks_both_hashes_and_refuses_another_zip_in_raw(cfg, tmp_path, tiny_zip):
    body = tiny_zip.read_bytes()
    with FileServer(body) as server:
        ctx = ctx_for(cfg, tmp_path, mode="http", url=server.url("/file.zip"), allowed_hosts=("127.0.0.1",), accepted_sha256=sha(body),
                      member_sha256=member_hash(tiny_zip), local_path=None)
        first = fetch_source(ctx, insecure_hosts=LOCAL)
        assert first["downloaded"] is True and first["built"] is True and server.paths() == ["/file.zip"]
        assert fetch_source(ctx, insecure_hosts=LOCAL)["downloaded"] is False and server.paths() == ["/file.zip"], "the zip in raw is not downloaded again"
        wrong_member = ctx_for(cfg, tmp_path / "other", mode="http", url=server.url("/file.zip"), allowed_hosts=("127.0.0.1",),
                               accepted_sha256=sha(body), member_sha256="0" * 64, local_path=None)
        with pytest.raises(SourceError, match="V03"):
            fetch_source(wrong_member, insecure_hosts=LOCAL)
        assert not (tmp_path / "other" / "interim").exists()
    (tmp_path / "raw" / "online_retail_ii.zip").write_bytes(body + b"tampered")
    before = snapshot(tmp_path / "raw")
    with pytest.raises(SourceError, match=r"^V01:.*aceptada"):
        fetch_source(ctx, insecure_hosts=LOCAL)
    assert snapshot(tmp_path / "raw") == before


def test_an_unknown_mode_is_refused_by_the_task(cfg, tmp_path, tiny_zip):
    with pytest.raises(ValueError, match="mode"):
        fetch_source(ctx_for(cfg, tmp_path, mode="ftp", local_path=tiny_zip))


# --- AC05 (roles): every line in one rule, in the order of the table -----------------------------------------------------


def test_the_roles_follow_the_order_of_the_rules_and_match_the_fixture_truth(canonical, fixture_truth):
    frame, _report = canonical
    roles = classify_lines(frame)
    counts = roles["role"].where(roles["role"] != "excluded", roles["exclusion_reason"]).value_counts().to_dict()
    assert counts == {k: v for k, v in fixture_truth.roles.items() if v}
    assert set(roles["exclusion_reason"].dropna()) <= set(EXCLUSION_RULES)
    by = lambda customer: roles.loc[frame["customer_id"] == customer, "exclusion_reason"].tolist()  # noqa: E731
    assert "adjustment_invoice" in by(CASE_BASE + 13) and set(by(CASE_BASE + 14)) == {"non_positive_price", "non_positive_quantity", "service_code", None}
    pads = frame["stock_code"] == "PADS"
    assert pads.any() and (roles.loc[pads, "exclusion_reason"] == "service_code").all()
    shuffled = frame.sample(frac=1.0, random_state=1)
    assert classify_lines(shuffled).loc[frame.index].equals(roles), "a line's role does not depend on the order of the rows"


@pytest.mark.parametrize(("invoice", "quantity", "price", "customer", "code", "expected"), [
    ("489434", 2, 1.5, None, "service", "no_customer"),              # no customer comes first, whatever else the line is
    ("489434", 0, 0.0, 90001, "product", "non_positive_quantity"),   # the quantity before the price
    ("C489434", 3, 1.5, 90001, "product", "non_positive_quantity"),  # a positive quantity in a «C» invoice is the wrong sign
    ("489434", 2, 0.0, 90001, "service", "non_positive_price"),      # the price before the code
    ("C489434", -2, 0.0, 90001, "product", "non_positive_price"),    # a «C» line with no price is set aside, not netted
    ("A489434", 1, 10.0, 90001, "service", "service_code"),          # the code before the «A» invoice
    ("A489434", 1, 10.0, 90001, "gift_voucher", "gift_voucher"),
    ("A489434", 1, 10.0, 90001, "product", "adjustment_invoice"),
    ("C489434", -2, 1.5, 90001, "product", None),                    # a cancellation
    ("489434", 2, 1.5, 90001, "product", None),                      # a purchase
])
def test_each_line_is_set_aside_by_the_first_rule_that_applies(invoice, quantity, price, customer, code, expected):
    frame = pd.DataFrame({"invoice": [invoice], "quantity": [quantity], "price": [price], "customer_id": pd.array([customer], dtype="Int64"), "code_kind": [code]})
    result = classify_lines(frame).iloc[0]
    assert result["exclusion_reason"] == expected
    assert result["role"] == ("excluded" if expected else ("cancellation" if invoice.startswith("C") else "purchase"))


def test_the_lists_of_columns_never_share_a_name():
    assert not set(FEATURE_COLUMNS) & set(LABEL_COLUMNS) and not set(FEATURE_COLUMNS) & set(IDENTIFIER_COLUMNS)
    assert not set(LABEL_COLUMNS) & set(IDENTIFIER_COLUMNS) and len(FEATURE_COLUMNS) == 17
    assert [code_kind(c) for c in ("85123A", "22423", "DCGS0076", "PADS", "POST", "gift_0001_20", "M", "BANK CHARGES")] == [
        "product", "product", "product", "service", "service", "gift_voucher", "service", "service"]
