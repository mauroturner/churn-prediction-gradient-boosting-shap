"""The cuts in the warehouse (U10, AC10 and AC11; RF11, RF12, RF14, D24): the population of every cut up to the day after the calculation
date and the label of every cut whose window has closed, written once to insert-only tables, with the blocks and the controls of the cuts."""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import date, timedelta

import pytest

from churnrisk.config import SealedConfig
from churnrisk.cuts import build_cuts, cut_dates, label_end
from churnrisk.deliveries import delivery_plan, delivery_rows
from churnrisk.split import PurgeError, blocks, is_censored
from churnrisk.warehouse import CheckFailedError, connect, load_delivery
from tests.fixtures.make_fixture import WINDOW_END

SHA = "d" * 64


def file_sha(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stored(conn: sqlite3.Connection, table: str) -> dict[date, dict[int, int]]:
    column = "churned" if table == "cut_labels" else "1"
    out: dict[date, dict[int, int]] = {}
    for cut, customer, value in conn.execute(f"SELECT cut_date, customer_id, {column} FROM {table} ORDER BY cut_date, customer_id"):
        out.setdefault(date.fromisoformat(cut), {})[customer] = value
    return out


# --- the RED of U10 -----------------------------------------------------------------------------------------------------


def test_a_label_exists_only_once_its_window_has_closed(cfg, canonical, loaded_masters, copy_of, fixture_truth):
    """The launch and every monthly run in order: after each, the warehouse holds the population of every cut up to the day after its
    calculation date and the label of exactly the cuts whose window closed by then, known on that date; both are the fixture's truth."""
    frame, _report = canonical
    view = SealedConfig.of(cfg, SHA)
    plan = delivery_plan(cfg)
    n = timedelta(days=view.label.horizon_days)
    conn = connect(copy_of(loaded_masters(1)[0]))
    for index, spec in enumerate(plan):
        if index:
            load_delivery(conn, delivery_rows(spec, frame), spec, f"r{index + 1}", sha256=loaded_masters.entries[spec.delivery_id].sha256)
        result = build_cuts(conn, spec.as_of, view, f"r{index + 1}")
        with_population = [c for c in cut_dates(view) if c <= spec.as_of + timedelta(days=1)]
        with_label = [c for c in cut_dates(view) if c + n - timedelta(days=1) <= spec.as_of]
        assert sorted(stored(conn, "cut_features")) == with_population, spec.delivery_id
        assert sorted(stored(conn, "cut_labels")) == with_label, spec.delivery_id
        assert conn.execute("SELECT COUNT(*) FROM cut_labels WHERE label_end > ? OR known_as_of < label_end", (spec.as_of.isoformat(),)).fetchone()[0] == 0
        newly = conn.execute("SELECT DISTINCT cut_date FROM cut_labels WHERE known_as_of = ? ORDER BY 1", (spec.as_of.isoformat(),)).fetchall()
        assert [date.fromisoformat(r[0]) for r in newly] == result.labelled_cuts, "each label is known on the date of the run that wrote it"
        assert all(c.violations == 0 for c in result.checks)
    assert result.populated_cuts == [] and result.labelled_cuts == [], "the close (2011-12-09) has no new cut and no window that closes"
    # the populations and the labels are the fixture's truth, computed by its own netting
    assert stored(conn, "cut_features") == {cut: dict.fromkeys(customers, 1) for cut, customers in fixture_truth.population.items()}
    assert stored(conn, "cut_labels") == {cut: labels for cut, labels in fixture_truth.labels.items() if labels}
    assert max(fixture_truth.labels) + n - timedelta(days=1) <= WINDOW_END and len(stored(conn, "cut_labels")) == 16
    # the blocks of every cut, its window and whether it is censored
    rows = conn.execute("SELECT cut_date, block, label_end, is_censored FROM cut_blocks ORDER BY cut_date").fetchall()
    assert rows == [(c.isoformat(), b, label_end(c, view.label.horizon_days).isoformat(), int(is_censored(c, view))) for c, b in blocks(view).items()]
    # repeating the last run's cuts adds nothing and changes nothing
    before = (stored(conn, "cut_features"), stored(conn, "cut_labels"))
    again = build_cuts(conn, plan[-1].as_of, view, "r9")
    assert (again.populated_cuts, again.labelled_cuts) == ([], []) and (stored(conn, "cut_features"), stored(conn, "cut_labels")) == before
    conn.close()


# --- insert only, the controls and the purges -----------------------------------------------------------------------------


@pytest.fixture
def launched(cfg, loaded_masters, copy_of):
    path = copy_of(loaded_masters(1)[0])
    conn = connect(path)
    build_cuts(conn, date(2011, 7, 31), SealedConfig.of(cfg, SHA), "r1")
    yield path, conn
    conn.close()


@pytest.mark.parametrize("table", ["cut_features", "cut_labels"])
def test_the_features_and_the_labels_of_a_cut_are_insert_only(launched, table):
    _path, conn = launched
    cut, customer = conn.execute(f"SELECT cut_date, customer_id FROM {table} LIMIT 1").fetchone()
    for statement in (f"UPDATE {table} SET run_key = 'x' WHERE cut_date = ?", f"DELETE FROM {table} WHERE cut_date = ?"):
        with pytest.raises(sqlite3.DatabaseError, match="solo inserción"):
            conn.execute(statement, (cut,))
    row = conn.execute(f"SELECT * FROM {table} WHERE cut_date = ? AND customer_id = ?", (cut, customer)).fetchone()
    with pytest.raises(sqlite3.DatabaseError, match="solo inserción"):
        conn.execute(f"INSERT OR REPLACE INTO {table} VALUES ({', '.join('?' for _ in row)})", row)


def test_a_failing_control_of_the_cuts_rolls_the_build_back(cfg, loaded_masters, copy_of):
    """A label written by hand before its window closed (known_as_of < label_end): the next build fails its control and writes nothing."""
    path = copy_of(loaded_masters(2)[0])
    conn = connect(path)
    build_cuts(conn, date(2011, 7, 31), SealedConfig.of(cfg, SHA), "r1")
    conn.execute("INSERT INTO cut_labels VALUES ('2011-06-01', 99999, 1, '2011-08-29', '2011-07-31', 'by hand')")
    conn.close()
    before = file_sha(path)
    conn = connect(path)
    with pytest.raises(CheckFailedError, match="chk_label_known_after_window") as error:
        build_cuts(conn, date(2011, 8, 31), SealedConfig.of(cfg, SHA), "r2")
    assert {c.check_id for c in error.value.checks if c.violations} >= {"chk_label_known_after_window", "chk_label_has_features"}
    assert "99999" not in str(error.value), "a control names a cut and counts customers: it never shows a customer number"
    conn.close()
    assert file_sha(path) == before


def test_a_split_without_its_purge_is_refused_before_anything_is_written(cfg, loaded_masters, copy_of):
    import dataclasses

    path = copy_of(loaded_masters(1)[0])
    before = file_sha(path)
    sealed = SealedConfig.of(cfg, SHA)
    broken = dataclasses.replace(sealed, split=dataclasses.replace(sealed.split, train_last=date(2011, 1, 1)))
    conn = connect(path)
    with pytest.raises(PurgeError, match="train → valid_v1"):
        build_cuts(conn, date(2011, 7, 31), broken, "r1")
    conn.close()
    assert file_sha(path) == before
