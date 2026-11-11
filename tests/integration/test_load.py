"""The warehouse (U09, AC08 and AC09; RF10, D24): a delivery is added to SQLite in one transaction with the staging table rebuilt for its
calculation date and the controls of the load; a control with rows undoes everything, down to the bytes of the file."""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from churnrisk.deliveries import delivery_plan, delivery_rows
from churnrisk.validate import classify_lines
from churnrisk.schema import CANONICAL_SCHEMA
from churnrisk.warehouse import (
    CheckFailedError,
    DeliveryAlreadyLoadedError,
    EmptyDeliveryError,
    SchemaDriftError,
    apply_schema,
    connect,
    load_delivery,
    rebuild_staging,
    run_checks,
)

LAUNCH_SHA = "a" * 64


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest() if Path(path).exists() else ""


def content(path: Path) -> dict[str, list[tuple]]:
    """Every row of every table, in key order: what a reload from scratch must give again."""
    conn = sqlite3.connect(path)
    try:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return {t: conn.execute(f'SELECT * FROM "{t}" ORDER BY 1, 2').fetchall() for t in tables}
    finally:
        conn.close()


def two_countries_launch() -> pd.DataFrame:
    """A launch of three lines whose first invoice says two countries: V13 rejects it before any load, and the control of the load is the
    second line of defence (D24)."""
    frame = pd.DataFrame({
        "line_id": [10_000_001, 10_000_002, 10_000_003], "sheet": 1, "source_row": [1, 2, 3], "invoice": ["500001", "500001", "500002"],
        "stock_code": ["85123A", "22423", "85123A"], "description": "X", "quantity": [2, 3, 1],
        "invoice_ts": pd.to_datetime(["2011-03-03 10:00", "2011-03-03 10:00", "2011-03-04 11:00"]), "price": [2.5, 4.0, 2.5],
        "customer_id": pd.array([90001, 90001, 90002], dtype="Int64"), "country": ["United Kingdom", "France", "United Kingdom"],
        "code_kind": "product", "is_repeated_line": False,
    })
    frame["invoice_date"] = frame["invoice_ts"].dt.normalize()
    return frame[CANONICAL_SCHEMA.names]


# --- the RED of U09 ---------------------------------------------------------------------------------------------------


def test_failed_check_rolls_back_a_first_load(cfg, tmp_path):
    path = tmp_path / "warehouse.sqlite"
    conn = connect(path)
    before = sha(path)
    spec = delivery_plan(cfg)[0]
    with pytest.raises(CheckFailedError) as error:
        load_delivery(conn, two_countries_launch(), spec, "r1", sha256=LAUNCH_SHA)
    assert [c.check_id for c in error.value.checks if c.violations] == ["chk_one_country_per_invoice"]
    failing = next(c for c in error.value.checks if c.violations)
    assert failing.sample == [(10_000_001, 2)], "the first line of the invoice and its two countries: never the invoice number"
    assert "500001" not in str(error.value) and "90001" not in str(error.value)
    assert not conn.in_transaction
    conn.close()
    assert sha(path) == before, "the warehouse keeps exactly what it had: here, nothing"
    assert content(path) == {}


# --- AC09: the load -------------------------------------------------------------------------------------------------------


def test_loaded_rows_equal_the_delivery_rows_every_check_is_zero_and_the_staging_has_the_roles_of_the_lines(cfg, canonical, loaded_masters, copy_of):
    frame, _report = canonical
    path, result = loaded_masters(len(delivery_plan(cfg)))
    conn = connect(copy_of(path))
    plan = delivery_plan(cfg)
    loaded = dict(conn.execute("SELECT delivery_id, COUNT(*) FROM raw_lines GROUP BY delivery_id").fetchall())
    assert loaded == {spec.delivery_id: len(delivery_rows(spec, frame)) for spec in plan}
    assert sum(loaded.values()) == len(frame)
    assert (result.delivery_id, result.as_of, result.lines) == ("C2011-12", date(2011, 12, 9), len(delivery_rows(plan[-1], frame)))
    assert result.staged == len(frame) and all(c.violations == 0 for c in result.checks)
    assert [c.check_id for c in result.checks] == ["chk_delivery_period", "chk_one_country_per_invoice", "chk_one_customer_per_invoice",
                                                   "chk_raw_unique_line", "chk_stg_one_per_raw"]
    statuses = conn.execute("SELECT delivery_id, kind, lines_from, lines_to, as_of_date, status, run_key FROM deliveries ORDER BY lines_from").fetchall()
    assert statuses == [(s.delivery_id, s.kind, s.lines_from.isoformat(), s.lines_to.isoformat(), s.as_of.isoformat(), "loaded", f"r{i}")
                        for i, s in enumerate(plan, start=1)]
    # the staging's roles are those of validate.classify_lines, line by line (the same order of the rules in SQL and in Python)
    staged = pd.read_sql_query("SELECT line_id, role, exclusion_reason, quality_flags FROM stg_lines ORDER BY line_id", conn)
    expected = classify_lines(frame).assign(line_id=frame["line_id"]).sort_values("line_id").reset_index(drop=True)
    assert staged["line_id"].tolist() == expected["line_id"].tolist()
    assert staged["role"].tolist() == expected["role"].tolist()
    assert staged["exclusion_reason"].where(staged["exclusion_reason"].notna(), None).tolist() == expected["exclusion_reason"].tolist()
    flagged = staged.dropna(subset=["quality_flags"])
    assert flagged["quality_flags"].str.contains("repeated_line").sum() == int(frame["is_repeated_line"].sum())
    assert flagged["quality_flags"].str.contains("unspecified_country").sum() == int((frame["country"] == "Unspecified").sum())
    # what a line holds comes back as it went in
    raw = pd.read_sql_query("SELECT * FROM raw_lines ORDER BY line_id", conn)
    ordered = frame.sort_values("line_id").reset_index(drop=True)
    for column in ("invoice", "stock_code", "quantity", "price", "country", "code_kind"):
        assert raw[column].tolist() == ordered[column].tolist(), column
    assert raw["customer_id"].astype("Int64").equals(ordered["customer_id"].astype("Int64"))
    assert raw["invoice_ts"].tolist() == ordered["invoice_ts"].dt.strftime("%Y-%m-%d %H:%M:%S").tolist()
    conn.close()


def test_loading_from_scratch_again_gives_the_same_content(cfg, canonical, loaded_masters, tmp_path):
    frame, _report = canonical
    path, _result = loaded_masters(2)
    fresh = tmp_path / "fresh.sqlite"
    conn = connect(fresh)
    for i, spec in enumerate(delivery_plan(cfg)[:2], start=1):
        load_delivery(conn, delivery_rows(spec, frame), spec, f"r{i}", sha256=loaded_masters.entries[spec.delivery_id].sha256)
    conn.close()
    assert content(fresh) == content(path)


def test_a_failed_control_after_an_earlier_load_leaves_the_warehouse_byte_for_byte_as_it_was(cfg, canonical, loaded_masters, copy_of):
    frame, _report = canonical
    path = copy_of(loaded_masters(1)[0])
    before = sha(path)
    spec = delivery_plan(cfg)[1]
    rows = delivery_rows(spec, frame).copy()
    first = rows.index[0]
    rows.loc[first, "invoice_date"] = pd.Timestamp("2011-09-15")    # a line dated outside the period of its delivery: chk_delivery_period
    conn = connect(path)
    with pytest.raises(CheckFailedError, match="chk_delivery_period"):
        load_delivery(conn, rows, spec, "r2", sha256="b" * 64)
    conn.close()
    assert sha(path) == before


def test_a_delivery_already_loaded_or_empty_is_refused_and_writes_nothing(cfg, canonical, loaded_masters, copy_of):
    frame, _report = canonical
    path = copy_of(loaded_masters(1)[0])
    before = sha(path)
    conn = connect(path)
    spec = delivery_plan(cfg)[0]
    with pytest.raises(DeliveryAlreadyLoadedError, match="L2011-07 ya está cargada"):
        load_delivery(conn, delivery_rows(spec, frame), spec, "r9", sha256=LAUNCH_SHA)
    with pytest.raises(EmptyDeliveryError, match="no tiene líneas"):
        load_delivery(conn, frame.iloc[:0], delivery_plan(cfg)[1], "r9", sha256="b" * 64)
    conn.close()
    assert sha(path) == before


def test_the_staging_holds_only_what_is_known_on_the_date_it_is_built_for(cfg, canonical, loaded_masters, copy_of):
    frame, _report = canonical
    conn = connect(copy_of(loaded_masters(2)[0]))
    for as_of in (date(2011, 8, 31), date(2011, 3, 1), date(2009, 11, 30)):
        checks = rebuild_staging(conn, as_of)
        known = frame[(frame["invoice_date"] <= pd.Timestamp(as_of))]
        assert conn.execute("SELECT COUNT(*) FROM stg_lines").fetchone()[0] == len(known), as_of
        assert conn.execute("SELECT MAX(invoice_date) FROM stg_lines").fetchone()[0] == (known["invoice_date"].max().date().isoformat() if len(known) else None)
        assert all(c.violations == 0 for c in checks)
    conn.close()


def test_a_table_with_other_columns_is_refused_naming_it_and_an_unknown_group_of_controls_too(tmp_path):
    conn = connect(tmp_path / "old.sqlite")
    conn.execute("CREATE TABLE deliveries (delivery_id TEXT PRIMARY KEY, status TEXT)")
    with pytest.raises(SchemaDriftError, match=r"deliveries.*faltan las columnas \['kind'"):
        apply_schema(conn)
    with pytest.raises(ValueError, match="grupo de controles desconocido"):
        run_checks(conn, "nonsense")
    conn.close()
