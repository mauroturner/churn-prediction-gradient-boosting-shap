"""The guards of the model's tables (sql/schema/003_model.sql; review of U16, R3-3 and R3-4): ``baseline_calibrators`` is insert only like its
sibling tables, and a score's threshold is a probability like the registry's."""

from __future__ import annotations

import sqlite3

import pytest

from churnrisk.warehouse import apply_schema, connect

REGISTRY_ROW = ("v1", "2011-07-31", "models/v1.pkl", "a" * 64, "f0", "[]", "[]", "{}", "isotonic", 0.5, "b2_rfm", "{}", "{}", "b" * 64, "[]", "c" * 64)


@pytest.fixture
def warehouse(tmp_path):
    conn = connect(tmp_path / "w.sqlite")
    apply_schema(conn)
    conn.execute(f"INSERT INTO model_registry VALUES ({', '.join('?' for _ in REGISTRY_ROW)})", REGISTRY_ROW)
    conn.execute("INSERT INTO baseline_calibrators VALUES ('b2_rfm', 'v1', ?)", ("d" * 64,))
    yield conn
    conn.close()


@pytest.mark.parametrize("statement", [
    "UPDATE baseline_calibrators SET calibrator_sha256 = 'x'",
    "DELETE FROM baseline_calibrators",
    "INSERT OR REPLACE INTO baseline_calibrators VALUES ('b2_rfm', 'v1', 'x')",
])
def test_baseline_calibrators_are_insert_only(warehouse, statement):
    with pytest.raises(sqlite3.IntegrityError, match="baseline_calibrators es de solo inserción"):
        warehouse.execute(statement)
    assert warehouse.execute("SELECT * FROM baseline_calibrators").fetchall() == [("b2_rfm", "v1", "d" * 64)]


def test_a_new_model_version_registers_its_own_calibrators_for_the_same_methods(warehouse):
    warehouse.execute(f"INSERT INTO model_registry VALUES ({', '.join('?' for _ in REGISTRY_ROW)})", ("v2", *REGISTRY_ROW[1:]))
    warehouse.execute("INSERT INTO baseline_calibrators VALUES ('b2_rfm', 'v2', ?)", ("e" * 64,))
    with pytest.raises(sqlite3.IntegrityError, match="baseline_calibrators es de solo inserción: ese calibrador ya está registrado"):
        warehouse.execute("INSERT OR REPLACE INTO baseline_calibrators VALUES ('b2_rfm', 'v2', 'x')")
    assert warehouse.execute("SELECT * FROM baseline_calibrators ORDER BY model_version").fetchall() == [("b2_rfm", "v1", "d" * 64), ("b2_rfm", "v2", "e" * 64)]


@pytest.mark.parametrize("threshold", [-0.01, 1.01])
def test_a_score_whose_threshold_is_not_a_probability_is_refused(warehouse, threshold):
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        warehouse.execute("INSERT INTO model_scores VALUES ('2011-08-01', 90001, '2011-07-31', 'r1', 'v1', 0.5, 0.0, ?, 0)", (threshold,))
    warehouse.execute("INSERT INTO model_scores VALUES ('2011-08-01', 90001, '2011-07-31', 'r1', 'v1', 0.5, 0.0, 1.0, 0)")
