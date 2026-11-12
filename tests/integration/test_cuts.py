"""The cuts in the warehouse (U10, AC10 and AC11; RF11, RF12, RF14, D24): the population of every cut up to the day after the calculation
date and the label of every cut whose window has closed, written once to insert-only tables, with the blocks and the controls of the cuts."""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import date, timedelta

import pandas as pd
import pytest

from churnrisk.config import SealedConfig
from churnrisk.cuts import build_cuts, cut_dates, label_end
from churnrisk.deliveries import delivery_plan
from churnrisk.split import PurgeError, blocks, is_censored
from churnrisk.warehouse import CheckFailedError, connect
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


def test_a_label_exists_only_once_its_window_has_closed(cfg, cut_history, copy_of, fixture_truth):
    """The launch and every monthly run in order (``cut_history``: each run loads its delivery and builds its cuts): after each, the warehouse
    holds the population of every cut up to the day after its calculation date and the label of exactly the cuts whose window closed by then,
    known on that date; both are the fixture's truth."""
    view = SealedConfig.of(cfg, SHA)
    n = timedelta(days=view.label.horizon_days)
    assert [run.spec.delivery_id for run in cut_history] == [spec.delivery_id for spec in delivery_plan(cfg)]
    for run in cut_history:
        spec, result = run.spec, run.result
        conn = sqlite3.connect(run.path)
        try:
            with_population = [c for c in cut_dates(view) if c <= spec.as_of + timedelta(days=1)]
            with_label = [c for c in cut_dates(view) if c + n - timedelta(days=1) <= spec.as_of]
            assert sorted(stored(conn, "cut_features")) == with_population, spec.delivery_id
            assert sorted(stored(conn, "cut_labels")) == with_label, spec.delivery_id
            assert conn.execute("SELECT COUNT(*) FROM cut_labels WHERE label_end > ? OR known_as_of < label_end", (spec.as_of.isoformat(),)).fetchone()[0] == 0
            newly = conn.execute("SELECT DISTINCT cut_date FROM cut_labels WHERE known_as_of = ? ORDER BY 1", (spec.as_of.isoformat(),)).fetchall()
            assert [date.fromisoformat(r[0]) for r in newly] == result.labelled_cuts, "each label is known on the date of the run that wrote it"
            assert all(c.violations == 0 for c in result.checks) and result.as_of == spec.as_of
        finally:
            conn.close()
    assert result.populated_cuts == [] and result.labelled_cuts == [], "the close (2011-12-09) has no new cut and no window that closes"
    conn = connect(copy_of(cut_history[-1].path))
    try:
        # the populations and the labels are the fixture's truth, computed by its own netting
        assert stored(conn, "cut_features") == {cut: dict.fromkeys(customers, 1) for cut, customers in fixture_truth.population.items()}
        assert stored(conn, "cut_labels") == {cut: labels for cut, labels in fixture_truth.labels.items() if labels}
        assert max(fixture_truth.labels) + n - timedelta(days=1) <= WINDOW_END and len(stored(conn, "cut_labels")) == 16
        # the blocks of every cut, its window and whether it is censored
        rows = conn.execute("SELECT cut_date, block, label_end, is_censored FROM cut_blocks ORDER BY cut_date").fetchall()
        assert rows == [(c.isoformat(), b, label_end(c, view.label.horizon_days).isoformat(), int(is_censored(c, view))) for c, b in blocks(view).items()]
        # repeating the last run's cuts adds nothing and changes nothing
        before = (stored(conn, "cut_features"), stored(conn, "cut_labels"))
        again = build_cuts(conn, cut_history[-1].spec.as_of, view, "r9")
        assert (again.populated_cuts, again.labelled_cuts) == ([], []) and (stored(conn, "cut_features"), stored(conn, "cut_labels")) == before
    finally:
        conn.close()


# --- insert only, the controls and the purges -----------------------------------------------------------------------------


@pytest.fixture
def launched(launch_cuts, copy_of):
    """A copy of the session's launch warehouse with its cuts built at 2011-07-31 (``launch_cuts``, the same view as SHA)."""
    path = copy_of(launch_cuts)
    conn = connect(path)
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
    assert str(error.value).startswith("La construcción de los cortes se deshizo"), "the error names the step that was undone, not the load"
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


def test_the_labelled_rows_are_the_features_of_the_closed_windows_with_their_block_and_label(cfg, launched, fixture_truth):
    """split.labelled_rows, the only reader of labels of the baselines and the model, gives the features of every cut whose window closed by
    the launch, with its block and its label (the fixture's truth); a block filter keeps only those blocks."""
    from churnrisk.features import read_features
    from churnrisk.schema import FEATURE_COLUMNS
    from churnrisk.split import labelled_rows

    _path, conn = launched
    view = SealedConfig.of(cfg, SHA)
    rows = labelled_rows(conn)
    closed = [c for c in cut_dates(view) if label_end(c, view.label.horizon_days) <= date(2011, 7, 31)]
    assert sorted(set(rows.index.get_level_values("cut_date"))) == closed
    assert {c: dict(rows.xs(c, level="cut_date")["churned"]) for c in closed} == {c: fixture_truth.labels[c] for c in closed}
    assert (rows["block"] == [blocks(view)[c] for c in rows.index.get_level_values("cut_date")]).all()
    pd.testing.assert_frame_equal(rows[list(FEATURE_COLUMNS)], read_features(conn, closed), check_exact=True)
    validation = labelled_rows(conn, ["valid_v1", "valid_v2"])
    assert set(validation["block"]) == {"valid_v1", "valid_v2"} and validation.equals(rows[rows["block"].isin(["valid_v1", "valid_v2"])])
    with pytest.raises(ValueError, match="bloque desconocido"):
        labelled_rows(conn, ["validation"])


# --- the advisories of the reviews of U06-U10 (L47) -------------------------------------------------------------------------


def test_build_cuts_nets_each_label_with_the_one_helper_and_counts_the_rows_it_wrote(cfg, loaded_masters, copy_of, monkeypatch, fixture_truth):
    """R3-001: the label of each cut is netted with what is known at the end of its window by ``netting.net_lines_at``, the one helper for
    the net lines known on a date, never by a composition of its own. R3-002: ``CutsResult.rows`` counts the rows the build wrote to each
    table, and a build that writes nothing counts zero."""
    import churnrisk.cuts as cuts
    from churnrisk.netting import net_lines_at

    calls: list[date] = []

    def spy(conn, as_of, *args, **kwargs):
        calls.append(as_of)
        return net_lines_at(conn, as_of, *args, **kwargs)

    monkeypatch.setattr(cuts, "net_lines_at", spy, raising=False)
    view = SealedConfig.of(cfg, SHA)
    conn = connect(copy_of(loaded_masters(1)[0]))
    result = build_cuts(conn, date(2011, 7, 31), view, "r1")
    assert calls == [label_end(c, view.label.horizon_days) for c in result.labelled_cuts] and len(calls) == 12
    expected_rows = {"cut_features": sum(len(fixture_truth.population[c]) for c in result.populated_cuts),
                     "cut_labels": sum(len(fixture_truth.labels[c]) for c in result.labelled_cuts)}
    assert result.rows == expected_rows and min(expected_rows.values()) > 0
    assert result.rows == {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("cut_features", "cut_labels")}
    again = build_cuts(conn, date(2011, 7, 31), view, "r2")
    assert again.rows == {"cut_features": 0, "cut_labels": 0} and len(calls) == 12
    conn.close()
