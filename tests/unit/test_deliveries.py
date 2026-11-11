"""The deliveries (U07, AC06; RF07, D11): the launch L2011-07, four monthly deliveries and the close C2011-12, each line in the delivery of
its invoice date, a manifest with the period, the rows and the SHA-256 of each one, and the next pending delivery always the contiguous one."""

from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta

import pandas as pd
import pyarrow.parquet as pq
import pytest

from churnrisk.deliveries import (
    MANIFEST_NAME,
    DeliverySpec,
    assert_covered,
    delivery_plan,
    delivery_rows,
    mark_delivery,
    next_pending,
    publish,
    read_delivery,
    read_manifest,
)
from churnrisk.schema import CANONICAL_SCHEMA

D = date
FIXED_PLAN = [
    DeliverySpec("L2011-07", "launch", D(2009, 12, 1), D(2011, 7, 31), D(2011, 7, 31), D(2011, 8, 1)),
    DeliverySpec("M2011-08", "monthly", D(2011, 8, 1), D(2011, 8, 31), D(2011, 8, 31), D(2011, 9, 1)),
    DeliverySpec("M2011-09", "monthly", D(2011, 9, 1), D(2011, 9, 30), D(2011, 9, 30), D(2011, 10, 1)),
    DeliverySpec("M2011-10", "monthly", D(2011, 10, 1), D(2011, 10, 31), D(2011, 10, 31), D(2011, 11, 1)),
    DeliverySpec("M2011-11", "monthly", D(2011, 11, 1), D(2011, 11, 30), D(2011, 11, 30), D(2011, 12, 1)),
    DeliverySpec("C2011-12", "close", D(2011, 12, 1), D(2011, 12, 9), D(2011, 12, 9), None),
]


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def lines_at(*stamps: str, invoices: tuple[str, ...] | None = None) -> pd.DataFrame:
    """Canonical lines at the given times; lines that share an invoice take its first date, as the canonical reading does."""
    ts = pd.to_datetime(list(stamps))
    frame = pd.DataFrame({
        "line_id": range(1, len(ts) + 1), "sheet": 1, "source_row": range(1, len(ts) + 1),
        "invoice": list(invoices or [str(500000 + i) for i in range(len(ts))]), "stock_code": "85123A", "description": "HEART",
        "quantity": 2, "invoice_ts": ts, "price": 2.5, "customer_id": pd.array([90001] * len(ts), dtype="Int64"), "country": "United Kingdom",
        "code_kind": "product", "is_repeated_line": False,
    })
    frame["invoice_date"] = frame.groupby("invoice")["invoice_ts"].transform("min").dt.normalize()
    return frame[CANONICAL_SCHEMA.names]


# --- the RED of U07 ---------------------------------------------------------------------------------------------------


def test_each_line_goes_to_the_delivery_of_its_invoice_date_and_the_plan_is_fixed(cfg, canonical):
    plan = delivery_plan(cfg)
    assert plan == FIXED_PLAN
    for before, after in zip(plan, plan[1:], strict=False):
        assert after.lines_from == before.lines_to + timedelta(days=1), "each delivery starts the day after the previous one ends"
    frame, _report = canonical
    assert_covered(frame, plan)
    delivered = [delivery_rows(spec, frame) for spec in plan]
    assert sum(len(rows) for rows in delivered) == len(frame), "every line in exactly one delivery"
    assert sorted(pd.concat([rows["line_id"] for rows in delivered])) == sorted(frame["line_id"])
    for spec, rows in zip(plan, delivered, strict=True):
        assert rows["invoice_date"].between(pd.Timestamp(spec.lines_from), pd.Timestamp(spec.lines_to)).all(), spec.delivery_id
        assert len(rows) > 0, f"the fixture covers the calendar of the source: {spec.delivery_id} has lines"
    # an invoice that starts on the last minutes of the launch and goes on after midnight goes whole to the launch: its invoice date
    across = lines_at("2011-07-31 23:58", "2011-08-01 00:03", "2011-08-01 09:00", invoices=("600001", "600001", "600002"))
    assert delivery_rows(FIXED_PLAN[0], across)["line_id"].tolist() == [1, 2]
    assert delivery_rows(FIXED_PLAN[1], across)["line_id"].tolist() == [3]


def test_the_plan_follows_the_configured_dates(cfg):
    """A month-end last date leaves no close; the cut of a delivery is the day after its calculation date while it is a cut of [label]."""
    import dataclasses

    shorter = dataclasses.replace(cfg, deliveries=dataclasses.replace(cfg.deliveries, last_date=D(2011, 11, 30)),
                                  label=dataclasses.replace(cfg.label, last_cut=D(2011, 11, 1)))
    plan = delivery_plan(shorter)
    assert [s.delivery_id for s in plan] == ["L2011-07", "M2011-08", "M2011-09", "M2011-10", "M2011-11"]
    assert [s.cut for s in plan] == [D(2011, 8, 1), D(2011, 9, 1), D(2011, 10, 1), D(2011, 11, 1), None], "2011-12-01 is after last_cut"


# --- publishing and the manifest ------------------------------------------------------------------------------------------


def test_publishing_writes_the_rows_and_the_manifest_and_publishing_again_changes_nothing(cfg, canonical, tmp_path):
    frame, _report = canonical
    out = tmp_path / "deliveries"
    entry = publish(FIXED_PLAN[0], frame, out)
    path = out / "L2011-07.parquet"
    assert (entry.delivery_id, entry.kind, entry.lines_from, entry.lines_to, entry.as_of, entry.cut) == (
        "L2011-07", "launch", D(2009, 12, 1), D(2011, 7, 31), D(2011, 7, 31), D(2011, 8, 1))
    assert entry.rows == len(delivery_rows(FIXED_PLAN[0], frame)) and entry.sha256 == sha(path.read_bytes()) and entry.status == "published"
    assert entry.file == "L2011-07.parquet" and entry.run_key is None
    table = pq.read_table(path)
    assert table.schema.remove_metadata() == CANONICAL_SCHEMA
    assert table.schema.metadata[b"churnrisk.delivery_id"] == b"L2011-07" and b"churnrisk.attribution" in table.schema.metadata
    pd.testing.assert_frame_equal(read_delivery(path), delivery_rows(FIXED_PLAN[0], frame).reset_index(drop=True), check_dtype=False)
    manifest = (out / MANIFEST_NAME).read_bytes()
    document = json.loads(manifest)
    assert document["version"] == 1 and [e["delivery_id"] for e in document["entries"]] == ["L2011-07"]
    assert document["entries"][0]["cut"] == "2011-08-01"
    again = publish(FIXED_PLAN[0], frame, out)
    assert again == entry and (out / MANIFEST_NAME).read_bytes() == manifest, "republishing the same rows does not duplicate or touch anything"
    # the bytes depend only on the rows: another folder gets the same file, and a damaged file is repaired from the same rows
    assert publish(FIXED_PLAN[0], frame, tmp_path / "other").sha256 == entry.sha256
    path.write_bytes(b"damaged")
    assert publish(FIXED_PLAN[0], frame, out) == entry and sha(path.read_bytes()) == entry.sha256
    second = publish(FIXED_PLAN[1], frame, out)
    assert [e.delivery_id for e in read_manifest(out / MANIFEST_NAME)] == ["L2011-07", "M2011-08"] and second.cut == D(2011, 9, 1)
    # a loaded delivery with the same rows is left as it is: same entry, same status, same manifest bytes
    mark_delivery(out / MANIFEST_NAME, "L2011-07", "loaded", run_key="r1")
    loaded = (out / MANIFEST_NAME).read_bytes()
    assert publish(FIXED_PLAN[0], frame, out).status == "loaded" and (out / MANIFEST_NAME).read_bytes() == loaded


def test_the_next_pending_delivery_is_always_the_contiguous_one(canonical, tmp_path):
    frame, _report = canonical
    out = tmp_path / "deliveries"
    manifest = out / MANIFEST_NAME
    assert next_pending(manifest, FIXED_PLAN) == FIXED_PLAN[0], "without a manifest, the launch"
    for spec in FIXED_PLAN[:2]:
        publish(spec, frame, out)
    assert next_pending(manifest, FIXED_PLAN) == FIXED_PLAN[0], "published is not loaded"
    mark_delivery(manifest, "L2011-07", "loaded", run_key="r1")
    assert next_pending(manifest, FIXED_PLAN) == FIXED_PLAN[1]
    mark_delivery(manifest, "M2011-08", "rejected", run_key="r2")
    assert next_pending(manifest, FIXED_PLAN) == FIXED_PLAN[1], "a rejected delivery stays the pending one"
    entries = {e.delivery_id: e for e in read_manifest(manifest)}
    assert (entries["L2011-07"].status, entries["L2011-07"].run_key, entries["M2011-08"].status) == ("loaded", "r1", "rejected")
    for spec in FIXED_PLAN[1:]:
        publish(spec, frame, out)
        mark_delivery(manifest, spec.delivery_id, "loaded", run_key="r3")
    assert next_pending(manifest, FIXED_PLAN) is None, "no delivery pending: the run ends as no_delivery"


def test_a_manifest_that_skips_the_plan_or_changes_a_period_is_refused(canonical, tmp_path):
    frame, _report = canonical
    out = tmp_path / "deliveries"
    manifest = out / MANIFEST_NAME
    for spec in FIXED_PLAN[:2]:
        publish(spec, frame, out)
    mark_delivery(manifest, "M2011-08", "loaded")
    with pytest.raises(ValueError, match="M2011-08 está cargada pero la anterior, L2011-07, no lo está"):
        next_pending(manifest, FIXED_PLAN)
    with pytest.raises(ValueError, match="no está en el plan"):
        next_pending(manifest, FIXED_PLAN[1:])
    other = [DeliverySpec("L2011-07", "launch", D(2009, 12, 1), D(2011, 6, 30), D(2011, 6, 30), D(2011, 7, 1)), *FIXED_PLAN[1:]]
    with pytest.raises(ValueError, match="otro período"):
        next_pending(manifest, other)
    with pytest.raises(ValueError, match="no hay una entrega M2011-09"):
        mark_delivery(manifest, "M2011-09", "loaded")
    with pytest.raises(ValueError, match="status"):
        mark_delivery(manifest, "L2011-07", "done")


def test_a_loaded_delivery_whose_rows_changed_is_not_published_again_and_an_unloaded_one_is_replaced(canonical, tmp_path):
    frame, _report = canonical
    out = tmp_path / "deliveries"
    first = publish(FIXED_PLAN[1], frame, out)
    changed = frame.assign(price=frame["price"] + 0.01)
    replaced = publish(FIXED_PLAN[1], changed, out)
    assert replaced.sha256 != first.sha256 and replaced.status == "published" and len(read_manifest(out / MANIFEST_NAME)) == 1
    mark_delivery(out / MANIFEST_NAME, "M2011-08", "loaded")
    before = {p.name: p.read_bytes() for p in out.iterdir()}
    with pytest.raises(ValueError, match="ya está cargada"):
        publish(FIXED_PLAN[1], frame, out)
    assert {p.name: p.read_bytes() for p in out.iterdir()} == before


def test_a_line_outside_every_delivery_is_refused_and_the_manifest_reads_only_its_own_format(cfg, tmp_path):
    with pytest.raises(ValueError, match="1 líneas tienen una fecha de factura fuera de todas las entregas"):
        assert_covered(lines_at("2009-11-30 10:00", "2010-01-04 10:00"), delivery_plan(cfg))
    path = tmp_path / MANIFEST_NAME
    assert read_manifest(path) == []
    for broken in ("not json", "[]", '{"version": 2, "entries": []}', '{"version": 1, "entries": [{"delivery_id": "L2011-07"}]}'):
        path.write_text(broken, encoding="utf-8")
        with pytest.raises(ValueError, match="no es un manifiesto de entregas válido"):
            read_manifest(path)
