"""The star model that Power BI reads (U20, AC27, AC42 in part; RF25; D25, D26): unique keys, every foreign key in its dimension, relationships one
to many of single direction and active, each Parquet with the specification's schema and the run's metadata, and the customer-level fact
written outside the versioned folder."""

from __future__ import annotations

import shutil
from pathlib import Path
import sqlite3
from datetime import date

import pyarrow.parquet as pq
import pytest

from churnrisk.dashboard.semantic_model import MODEL, arrow_schema
from churnrisk.export import METADATA_KEYS, ExportMeta, build_powerbi_marts, export_star_schema
from churnrisk.warehouse import CheckFailedError, connect


@pytest.fixture(scope="module")
def star_export(star_files):
    """The star model of the quick history's last run, exported once per session (``star_files``): ``(cfg, out_dir, private_dir, paths, meta,
    warehouse)``."""
    return star_files


def read(star_export, name: str):
    _cfg, out_dir, private_dir, _paths, _meta, _w = star_export
    table = MODEL.table(name)
    return pq.read_table((private_dir if table.private else out_dir) / f"{name}.parquet")


# --- the RED of U20 ------------------------------------------------------------------------------------------------------


def test_every_relationship_is_one_to_many_single_and_keys_exist(star_export):
    """AC27: for each of the 19 relationships the dimension's key is unique and never empty, every key of the fact is in the dimension, and the
    relationship is one to many, single direction and active; every table's key is unique; each file has the schema of the specification and the
    run, the date, the source and the attribution as metadata."""
    _cfg, _out, _private, paths, meta, _w = star_export
    assert len(MODEL.relationships) == 19 and [r.rel_id for r in MODEL.relationships] == [f"R{i:02d}" for i in range(1, 20)]
    for r in MODEL.relationships:
        assert (r.cardinality, r.cross_filter, r.active) == ("one_to_many", "single", True), r.rel_id
        keys = read(star_export, r.dim_table).column(r.dim_column).to_pylist()
        assert None not in keys and len(set(keys)) == len(keys), f"{r.rel_id}: {r.dim_table}[{r.dim_column}] is not a unique key"
        values = read(star_export, r.fact_table).column(r.fact_column).to_pylist()
        assert None not in values and set(values) <= set(keys), f"{r.rel_id}: {r.fact_table}[{r.fact_column}] outside {r.dim_table}"
    assert [p.stem for p in paths] == [t.name for t in MODEL.tables]
    for table in MODEL.tables:
        data = read(star_export, table.name)
        assert data.schema.remove_metadata() == arrow_schema(table), table.name
        meta_got = {k.decode(): v.decode("utf-8") for k, v in data.schema.metadata.items() if k.decode() in METADATA_KEYS}
        assert meta_got == meta.metadata(), table.name
        rows = list(zip(*(data.column(k).to_pylist() for k in table.key))) if data.num_rows else []
        assert len(set(rows)) == len(rows) and all(None not in row for row in rows), f"{table.name}: its key is not unique"


def test_the_customer_level_fact_is_written_outside_the_versioned_folder(star_export, fixture_truth, tmp_path, quick_history):
    """D26, AC42 in part: the customer number is only in the private fact, under outputs/private/; no versioned file has a column that names a
    customer or an invoice, and no value of a versioned file is a customer number of the fixture; the two folders cannot be one."""
    cfg, out_dir, private_dir, _paths, meta, warehouse = star_export
    assert sorted(p.name for p in private_dir.glob("*")) == ["fact_customer_cut.parquet", "manifest.json"]
    assert sorted(p.stem for p in out_dir.glob("*.parquet")) == sorted(t.name for t in MODEL.tables if not t.private)
    assert sorted(p.name for p in out_dir.glob("*") if p.suffix != ".parquet") == ["manifest.json"]
    customers = set(fixture_truth.customer_ids)
    for table in (t for t in MODEL.tables if not t.private):
        data = read(star_export, table.name)
        assert not any("customer_id" in c or "invoice" in c for c in data.column_names), table.name     # a count of customers is no identifier
        for name in data.column_names:
            values = {v for v in data.column(name).to_pylist() if isinstance(v, int) and not isinstance(v, bool)}
            assert not values & customers, f"{table.name}[{name}] holds a customer number"
    private = read(star_export, "fact_customer_cut")
    assert set(private.column("customer_id").to_pylist()) <= customers and private.num_rows == len(quick_history.runs[-1].scores)
    conn = connect(warehouse)
    try:
        with pytest.raises(ValueError, match="la carpeta privada no puede ser la versionada"):
            export_star_schema(conn, tmp_path / "same", tmp_path / "same", MODEL, meta, cfg)
    finally:
        conn.close()
    assert not (tmp_path / "same").exists()


# --- what the tables hold -------------------------------------------------------------------------------------------------


def test_the_tables_hold_the_warehouse_and_the_small_cells_never_come_back_by_subtraction(star_export, quick_history):
    cfg, *_rest = star_export
    conn = sqlite3.connect(quick_history.warehouse)
    try:
        scores = conn.execute("SELECT COUNT(*), SUM(is_contact) FROM model_scores").fetchone()
        tracking = conn.execute("SELECT COUNT(*) FROM tracking").fetchone()[0]
        groups = len(conn.execute("SELECT country_groups_json FROM model_registry").fetchone()[0].split(","))
    finally:
        conn.close()
    counts = {t.name: read(star_export, t.name).num_rows for t in MODEL.tables}
    assert counts["dim_cut"] == 19 and counts["dim_risk_band"] == 10 and counts["dim_reason"] == 17 and counts["dim_method"] == 7
    assert counts["dim_date"] == (date(2011, 12, 9) - date(2009, 12, 1)).days + 1 and counts["dim_country"] == groups and counts["dim_model"] == 1
    assert counts["fact_customer_cut"] == scores[0] and counts["fact_tracking"] == tracking and counts["fact_selection"] == 3
    assert counts["fact_label_definition"] == 6 and counts["fact_silence_return"] == 3 and counts["fact_sensitivity"] == 4 * 3
    assert counts["dim_pipeline_run"] == counts["fact_validation"] == 0, "the runs and their rules arrive with the tasks (U25)"
    cuts = read(star_export, "dim_cut").to_pandas().set_index("cut_key")
    assert cuts["churn_rate"].notna().sum() == 16 and cuts.loc[cuts["block"] == "post_test", "churn_rate"].isna().all()
    for name, by in (("fact_cut_band", "band_key"), ("fact_cut_country", "country_key")):
        frame = read(star_export, name).to_pandas()
        hidden = frame.groupby("cut_key")["suppressed"].sum()
        assert (hidden != 1).all(), f"{name}: a cut with one hidden cell gives it away by subtraction"
        assert frame.loc[frame["suppressed"], ["customers", "contacted"]].isna().all().all()
        shown = frame.loc[~frame["suppressed"], "customers"]
        assert (shown >= cfg.site.min_cell_customers).all() and frame[by].notna().all()
        if name == "fact_cut_band":
            assert frame["suppressed"].any(), "the fixture has bands with fewer than ten customers: the rule is exercised"
    private = read(star_export, "fact_customer_cut").to_pandas()
    assert (private["is_contact"] == (private["risk"] >= read(star_export, "dim_model").column("threshold")[0].as_py())).all()
    assert int(private["is_contact"].sum()) == scores[1]
    # the reasons in Spanish are those of score_reasons by rank, and who came back is what the tracking of the last date counts
    names = dict(zip(read(star_export, "dim_reason").column("reason_key").to_pylist(), read(star_export, "dim_reason").column("feature_es").to_pylist()))
    conn = sqlite3.connect(quick_history.warehouse)
    try:
        firsts = dict(((date.fromisoformat(c), k), f) for c, k, f in conn.execute("SELECT cut_date, customer_id, feature FROM score_reasons WHERE rank = 1"))
        returned = dict(conn.execute("SELECT cut_date, returned FROM tracking WHERE as_of_date = '2011-12-09'").fetchall())
    finally:
        conn.close()
    by_key = {(date(k // 10000, k // 100 % 100, k % 100), c): r for k, c, r in zip(private["cut_key"], private["customer_id"], private["reason_1_es"], strict=True)}
    assert by_key == {key: names[f] for key, f in firsts.items()}
    # a purchase in the window was known when the window closed: a customer its label calls churned has not come back in it
    assert not (private["returned"] & (private["churned"] == 1)).any()
    got = private.groupby("cut_key")["returned"].sum()
    assert {f"{k // 10000}-{k // 100 % 100:02d}-{k % 100:02d}": int(v) for k, v in got.items()} == returned


def test_a_control_that_fails_rolls_the_star_model_back(star_export, tmp_path):
    """A tracking row that does not count its scores (chk_tracking_totals) and a stray table of the star model with a customer column
    (chk_no_customer_column_in_versioned_marts): the build is undone and the marts keep what they had."""
    cfg, _out, _private, _paths, meta, warehouse = star_export
    path = tmp_path / "warehouse.sqlite"
    shutil.copy2(warehouse, path)
    conn = connect(path)
    try:
        before = conn.execute("SELECT COUNT(*) FROM star_fact_tracking").fetchone()[0]
        conn.execute("UPDATE tracking SET scored = scored + 1 WHERE cut_date = '2011-08-01'")
        conn.execute("CREATE TABLE star_fact_stray (customer_id INTEGER)")
        with pytest.raises(CheckFailedError) as error:
            build_powerbi_marts(conn, cfg, meta.source_sha256, meta.as_of)
        failing = {c.check_id for c in error.value.checks if c.violations}
        assert failing == {"chk_tracking_totals", "chk_no_customer_column_in_versioned_marts"}
        assert conn.execute("SELECT COUNT(*) FROM star_fact_tracking").fetchone()[0] == before and not conn.in_transaction
    finally:
        conn.close()


# --- the manifest of the set (RNF05; D69) -----------------------------------------------------------------------------------


def test_each_folder_gets_a_manifest_of_its_files_written_last_and_a_changed_byte_is_found(star_export, tmp_path, monkeypatch):
    """Open point of L49: the Parquet set has a manifest, as the deliveries do. Each folder's ``manifest.json`` says the run, the date, the
    source and the attribution and, for each of its files in the model's order, its name, bytes and SHA-256; it is written after every file of
    its folder, and ``verify_star_schema`` finds a file whose bytes differ, one missing and one the manifest does not list."""
    import hashlib
    import json

    from churnrisk import export
    from churnrisk.export import STAR_MANIFEST, verify_star_schema

    cfg, out_dir, private_dir, paths, meta, warehouse = star_export
    for folder, private in ((out_dir, False), (private_dir, True)):
        manifest = json.loads((folder / STAR_MANIFEST).read_text(encoding="utf-8"))
        names = [f"{t.name}.parquet" for t in MODEL.tables if t.private == private]
        assert [f["name"] for f in manifest["files"]] == names
        for entry in manifest["files"]:
            data = (folder / entry["name"]).read_bytes()
            assert (entry["bytes"], entry["sha256"]) == (len(data), hashlib.sha256(data).hexdigest())
        assert {k: manifest[k] for k in ("run_key", "as_of", "source_sha256", "attribution")} == dict(zip(("run_key", "as_of", "source_sha256", "attribution"), meta.metadata().values(), strict=True))
        assert verify_star_schema(folder) == []
    order = []
    real = export.write_atomic
    monkeypatch.setattr(export, "write_atomic", lambda path, data: (order.append(Path(path).name), real(path, data))[1])
    copy = tmp_path / "w.sqlite"
    shutil.copy2(warehouse, copy)
    conn = connect(copy)
    try:
        export_star_schema(conn, tmp_path / "powerbi", tmp_path / "private", MODEL, meta, cfg)
    finally:
        conn.close()
    versioned = [n for n in order if n.endswith(".parquet") and not MODEL.table(n[:-8]).private]
    assert order.index(STAR_MANIFEST) > max(order.index(n) for n in versioned)
    target = tmp_path / "powerbi"
    data = bytearray((target / "fact_roc.parquet").read_bytes())
    data[10] ^= 0xFF
    (target / "fact_roc.parquet").write_bytes(bytes(data))
    (target / "dim_date.parquet").unlink()
    (target / "stray.parquet").write_bytes(b"x")
    problems = verify_star_schema(target)
    assert any("fact_roc.parquet" in p for p in problems) and any("dim_date.parquet" in p for p in problems) and any("stray.parquet" in p for p in problems)


def test_a_failed_control_says_the_star_model_was_undone_not_the_load(star_export, tmp_path):
    """Open point of L49: ``CheckFailedError`` names the step whose transaction was undone."""
    cfg, _out, _private, _paths, meta, warehouse = star_export
    path = tmp_path / "warehouse.sqlite"
    shutil.copy2(warehouse, path)
    conn = connect(path)
    try:
        conn.execute("UPDATE tracking SET scored = scored + 1 WHERE cut_date = '2011-08-01'")
        with pytest.raises(CheckFailedError) as error:
            build_powerbi_marts(conn, cfg, meta.source_sha256, meta.as_of)
    finally:
        conn.close()
    assert str(error.value).startswith("La exportación del modelo estrella se deshizo; controles con filas que los violan: chk_tracking_totals")


# --- review coverage of U20 (L50: R3-coverage-*) --------------------------------------------------------------------------------------


def model_check_params(cfg, conn) -> dict:
    from churnrisk.features import FEATURE_SETS
    from churnrisk.registry import sealed_view

    view = sealed_view(cfg, "a" * 64)
    feature_set = conn.execute("SELECT feature_set FROM model_registry").fetchone()[0]
    return {"first_date": view.deliveries.first_date.isoformat(), "last_date": view.deliveries.last_date.isoformat(),
            "min_cell_customers": cfg.site.min_cell_customers, "reasons_per_score": min(view.evaluation.shap_top_reasons, len(set(FEATURE_SETS[feature_set])))}


def violations(conn, params) -> dict[str, int]:
    from churnrisk.warehouse import run_checks

    return {c.check_id: c.violations for c in run_checks(conn, "model", params)}


@pytest.fixture(scope="module")
def checks_db(star_export, tmp_path_factory):
    """One copy of the star model's warehouse for the tests that break a mart and run the controls: each breaks it inside a transaction and
    rolls it back, so every test starts from the exported marts (a copy per case cost a second for nothing)."""
    cfg, _out, _private, _paths, _meta, warehouse = star_export
    path = tmp_path_factory.mktemp("checks") / "w.sqlite"
    shutil.copy2(warehouse, path)
    conn = connect(path)
    params = model_check_params(cfg, conn)
    yield conn, params
    conn.close()


@pytest.mark.parametrize("relationship", MODEL.relationships, ids=lambda r: r.rel_id)
def test_every_foreign_key_check_catches_one_orphan_of_its_relationship(checks_db, relationship):
    """R3-coverage-fk-checks: one row of the fact whose key is not in its dimension makes that relationship's control fail, and among the
    foreign keys only it and the controls of the other relationships on the same column of the fact (R17 and R19 both filter
    ``fact_tracking[as_of_key]``, D90)."""
    conn, params = checks_db
    assert {k: v for k, v in violations(conn, params).items() if v} == {}
    dtype = next(c.dtype for c in MODEL.table(relationship.fact_table).columns if c.name == relationship.fact_column)
    orphan = -7 if dtype.startswith("int") else "orphan"
    fact = f"star_{relationship.fact_table}"
    conn.execute("BEGIN")
    try:
        if conn.execute(f"SELECT COUNT(*) FROM {fact}").fetchone()[0]:      # a real row with only its key changed: its other keys stay valid
            conn.execute(f"CREATE TEMP TABLE orphan AS SELECT * FROM {fact} LIMIT 1")
            conn.execute(f"UPDATE orphan SET {relationship.fact_column} = ?", (orphan,))
            conn.execute(f"INSERT INTO {fact} SELECT * FROM orphan")
        else:
            conn.execute(f"INSERT INTO {fact} ({relationship.fact_column}) VALUES (?)", (orphan,))
        failing = {k for k, v in violations(conn, params).items() if v and k.startswith("chk_fk_")}
    finally:
        conn.execute("ROLLBACK")
    same_column = [r for r in MODEL.relationships if (r.fact_table, r.fact_column) == (relationship.fact_table, relationship.fact_column)]
    assert failing == {f"chk_fk_{r.rel_id.lower()}_{r.fact_table}_{r.dim_table}" for r in same_column}


def test_the_key_check_catches_a_repeated_key_in_every_table_that_has_rows(checks_db):
    """R3-coverage-star-keys: a copy of one row of any table of the star model repeats its key and fails ``chk_star_keys_unique``, naming the
    table."""
    from churnrisk.warehouse import run_checks

    conn, params = checks_db
    tested = []
    for table in MODEL.tables:
        if conn.execute(f"SELECT COUNT(*) FROM star_{table.name}").fetchone()[0] == 0:
            continue
        conn.execute("BEGIN")
        try:
            conn.execute(f"INSERT INTO star_{table.name} SELECT * FROM star_{table.name} LIMIT 1")
            check = next(c for c in run_checks(conn, "model", params) if c.check_id == "chk_star_keys_unique")
        finally:
            conn.execute("ROLLBACK")
        assert check.violations >= 1 and table.name in {row[0] for row in check.sample}, table.name
        tested.append(table.name)
    assert len(tested) >= len(MODEL.tables) - 2, f"only {tested} have rows"


def test_a_versioned_file_over_the_limit_writes_nothing(star_export, tmp_path, monkeypatch):
    """R3-coverage-parquet-size: every file is serialized and measured before any is written; one over the limit writes none."""
    from churnrisk import export

    cfg, _out, _private, _paths, meta, warehouse = star_export
    monkeypatch.setattr(export, "MAX_PARQUET_BYTES", 4_000)
    path = tmp_path / "w.sqlite"
    shutil.copy2(warehouse, path)
    conn = connect(path)
    try:
        with pytest.raises(ValueError, match=r"pesa \d+ bytes, más de 4000: no se escribe nada"):
            export_star_schema(conn, tmp_path / "powerbi", tmp_path / "private", MODEL, meta, cfg)
    finally:
        conn.close()
    assert not (tmp_path / "powerbi").exists() and not (tmp_path / "private").exists()


def test_the_star_model_needs_a_registered_model(star_export, cut_history, tmp_path):
    """R3-coverage-unregistered-model: before the launch registers its model there is nothing to export, and the marts are not touched."""
    cfg, _out, _private, _paths, meta, _w = star_export
    path = tmp_path / "w.sqlite"
    shutil.copy2(cut_history[0].path, path)
    conn = connect(path)
    try:
        with pytest.raises(RuntimeError, match="no hay un modelo registrado con la versión v1"):
            build_powerbi_marts(conn, cfg, meta.source_sha256, meta.as_of)
        assert not conn.in_transaction
        assert conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name LIKE 'star_%' OR name LIKE 'ref_%'").fetchone()[0] == 0
    finally:
        conn.close()


def _broken(change: str):
    import dataclasses

    from churnrisk.dashboard.semantic_model import Column, Relationship, SemanticModel

    tables, rels = list(MODEL.tables), list(MODEL.relationships)
    dim_cut = MODEL.table("dim_cut")
    if change == "repeated_table":
        tables.append(dim_cut)
    elif change == "repeated_column":
        tables[tables.index(dim_cut)] = dataclasses.replace(dim_cut, columns=(*dim_cut.columns, dim_cut.columns[0]))
    elif change == "unknown_type":
        tables[tables.index(dim_cut)] = dataclasses.replace(dim_cut, columns=(*dim_cut.columns, Column("extra", "decimal", "x")))
    elif change == "key_not_a_column":
        tables[tables.index(dim_cut)] = dataclasses.replace(dim_cut, key=("missing_key",))
    elif change == "customer_column":
        tables[tables.index(dim_cut)] = dataclasses.replace(dim_cut, columns=(*dim_cut.columns, Column("customer_id", "int64", "x")))
    elif change == "fact_to_fact":
        rels.append(Relationship("R99", "fact_cut_band", "cut_key", "fact_tracking", "cut_key"))
    elif change == "not_the_whole_key":
        rels.append(Relationship("R99", "dim_cut", "cut_date", "fact_tracking", "cut_key"))
    elif change == "other_type":
        rels.append(Relationship("R99", "dim_reason", "reason_key", "fact_tracking", "cut_key"))
    elif change == "both_directions":
        rels[0] = dataclasses.replace(rels[0], cross_filter="both")
    return SemanticModel(tuple(tables), tuple(rels))


@pytest.mark.parametrize(("change", "message"), [
    ("repeated_table", "hay tablas repetidas"), ("repeated_column", "dim_cut repite una columna"), ("unknown_type", "tipo desconocido decimal"),
    ("key_not_a_column", "la clave missing_key de dim_cut no es una columna"), ("customer_column", "dim_cut es versionada y tiene una columna de cliente"),
    ("fact_to_fact", "R99 no une una dimensión con un hecho"), ("not_the_whole_key", "R99 no usa la clave entera de dim_cut"),
    ("other_type", "R99: fact_tracking\[cut_key\] no es una columna del tipo"), ("both_directions", "R01 no es uno a varios, de filtro unidireccional"),
])
def test_the_model_check_names_every_way_the_specification_can_be_wrong(change, message):
    """R3-coverage-validate-model-negative: each branch of ``validate_model``, and the export refuses an incoherent model before writing."""
    import re

    from churnrisk.dashboard.semantic_model import validate_model

    assert validate_model(MODEL) == []
    problems = validate_model(_broken(change))
    assert any(re.search(message, p) for p in problems), problems
