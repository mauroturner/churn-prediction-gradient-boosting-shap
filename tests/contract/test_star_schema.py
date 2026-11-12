"""The star model that Power BI reads (U20, AC27, AC42 in part; RF25; D25, D26): unique keys, every foreign key in its dimension, relationships one
to many of single direction and active, each Parquet with the specification's schema and the run's metadata, and the customer-level fact
written outside the versioned folder."""

from __future__ import annotations

import shutil
import sqlite3
from datetime import date

import pyarrow.parquet as pq
import pytest

from churnrisk.dashboard.semantic_model import MODEL, arrow_schema
from churnrisk.export import METADATA_KEYS, ExportMeta, build_powerbi_marts, export_star_schema
from churnrisk.warehouse import CheckFailedError, connect


@pytest.fixture(scope="module")
def star_export(quick_history, tmp_path_factory):
    """The star model of the quick history's last run, exported once for this module: ``(cfg, out_dir, private_dir, paths, meta)``."""
    folder = tmp_path_factory.mktemp("star")
    warehouse = folder / "warehouse.sqlite"
    shutil.copy2(quick_history.warehouse, warehouse)
    out_dir, private_dir = folder / "outputs" / "powerbi", folder / "outputs" / "private"
    last = quick_history.runs[-1]
    meta = ExportMeta(last.run_key, last.spec.as_of, quick_history.view.source_sha256)
    conn = connect(warehouse)
    try:
        paths = export_star_schema(conn, out_dir, private_dir, MODEL, meta, quick_history.cfg)
    finally:
        conn.close()
    return quick_history.cfg, out_dir, private_dir, paths, meta, warehouse


def read(star_export, name: str):
    _cfg, out_dir, private_dir, _paths, _meta, _w = star_export
    table = MODEL.table(name)
    return pq.read_table((private_dir if table.private else out_dir) / f"{name}.parquet")


# --- the RED of U20 ------------------------------------------------------------------------------------------------------


def test_every_relationship_is_one_to_many_single_and_keys_exist(star_export):
    """AC27: for each of the 18 relationships the dimension's key is unique and never empty, every key of the fact is in the dimension, and the
    relationship is one to many, single direction and active; every table's key is unique; each file has the schema of the specification and the
    run, the date, the source and the attribution as metadata."""
    _cfg, _out, _private, paths, meta, _w = star_export
    assert len(MODEL.relationships) == 18 and [r.rel_id for r in MODEL.relationships] == [f"R{i:02d}" for i in range(1, 19)]
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
    assert sorted(p.name for p in private_dir.glob("*")) == ["fact_customer_cut.parquet"]
    assert sorted(p.stem for p in out_dir.glob("*")) == sorted(t.name for t in MODEL.tables if not t.private)
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
