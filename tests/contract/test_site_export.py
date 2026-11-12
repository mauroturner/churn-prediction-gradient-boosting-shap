"""The five JSON files the personal site copies (U23, AC29, AC42; RF27; plan, section 21; D27, D73): their schema, nothing that names a
customer, small cells hidden and never given back by subtraction, the cumulative rules read once, the manifest written last, and every figure
the one of the Parquet files or of the summary of the same run. Changing their shape after publication is item 3 of the risk list."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
import shutil
import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from churnrisk.site_export import MANIFEST_FILE, SITE_FILES, SiteExportError, SiteSetError, export_site, export_summary, protect, read_site, verify_site
from churnrisk.validate import RULES
from churnrisk.warehouse import connect

ENVELOPE = {"schema_version": int, "run_key": str, "as_of": str, "source_sha256": str, "attribution": str}
SCHEMA: dict[str, dict[str, Any]] = {
    "summary.json": {"status": str, "evaluation_status": str, "headline": dict, "criteria": list, "seal": dict},
    "validation_rules.json": {"rules": list, "totals": dict},
    "label.json": {"rule": dict, "rates_by_cut": list, "n_by_m": list, "silence_return": list, "leakage": dict, "guests": dict},
    "algorithms.json": {"split": list, "selection": list, "b_star": dict, "methods": list, "gain": list, "calibration": list, "cost_curve": list,
                        "threshold": dict, "importance": list, "examples": list, "variants": list},
    "retention.json": {"threshold": float, "model_version": str, "cuts": list, "by_country": list, "by_country_cut": str, "reasons": list},
}
HEADLINE = ("lines_raw", "lines_base", "customers_with_purchase", "countries_with_customers", "guest_lines_share", "guest_value_share", "cancelled_value_share",
            "period_start", "period_end", "n_days", "m_days", "train_cuts", "valid_cuts", "test_cuts", "test_rows", "train_churn_rate", "test_churn_rate",
            "threshold", "break_even", "offer_cost", "rescue_rate", "retained_value", "b_star", "auc", "capture_10", "net_benefit_per_1000")
CRITERION = ("id", "name_es", "passed", "value", "baseline_value", "ci_low", "ci_high", "threshold_es", "seen_by_research", "seen_by_planner", "verdict_es")
EXAMPLE = ("label", "risk_quintile", "outcome", "contacted", "risk", "reason_1_es", "reason_2_es", "reason_3_es", "recency_band_es", "frequency_band_es", "spend_band_es")


@dataclasses.dataclass(frozen=True)
class Site:
    cfg: Any
    folder: Path
    warehouse: Path
    docs: dict[str, dict]
    out_dir: Path
    meta: Any


def export_to(star_files, folder: Path) -> Site:
    cfg, out_dir, _private, _paths, meta, warehouse = star_files
    copy = folder / "warehouse.sqlite"
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copy2(warehouse, copy)
    conn = connect(copy)
    try:
        export_site(conn, folder / "site", meta, cfg)
    finally:
        conn.close()
    docs = {name: json.loads(data) for name, data in read_site(folder / "site").items()}
    return Site(cfg, folder / "site", copy, docs, out_dir, meta)


@pytest.fixture(scope="module")
def site(star_files, tmp_path_factory) -> Site:
    """The site files of the quick history's last run, exported once for this module (``site_files``, plan 24.1)."""
    return export_to(star_files, tmp_path_factory.mktemp("site"))


def every_key(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [k for k in value] + [k for v in value.values() for k in every_key(v)]
    if isinstance(value, list):
        return [k for v in value for k in every_key(v)]
    return []


# --- the RED of U23 -------------------------------------------------------------------------------------------------------------


def test_no_identifier_or_sentinel_and_small_cells_suppressed(site, fixture_truth):
    """AC29, AC42: no key names a customer or an invoice, no customer number of the fixture appears in any byte, every published count of
    customers is at least the minimum, and every hidden cell has its values null and says so."""
    minimum = site.cfg.site.min_cell_customers
    raw = b"".join((site.folder / name).read_bytes() for name in SITE_FILES)
    for name, doc in site.docs.items():
        keys = every_key(doc)
        assert not [k for k in keys if "customer_id" in k.lower() or "invoice" in k.lower()], name
    found = {int(n) for n in re.findall(rb"(?<![\d.])(\d{5})(?![\d.])", raw)} & set(fixture_truth.customer_ids)
    assert not found, f"customer numbers in the site files: {sorted(found)[:5]}"
    retention, label = site.docs["retention.json"], site.docs["label.json"]
    for cut in retention["cuts"]:
        for row in cut["by_as_of"]:
            for key in ("returned", "churned", "contacted_churned", "contacted_returned"):
                assert row[key] is None or row[key] >= minimum, (cut["cut"], row["as_of"], key, row[key])
        assert cut["contacted"] is None or cut["contacted"] >= minimum
        assert cut["scored"] is None or cut["scored"] >= minimum
    for cell in retention["by_country"]:
        if cell["suppressed"]:
            assert (cell["customers"], cell["contacted"], cell["churn_rate_observed"]) == (None, None, None) and cell["country_es"]
        else:
            assert cell["customers"] >= minimum
    for cell in site.docs["algorithms.json"]["calibration"]:
        assert (cell["rows"] is None) == cell["suppressed"] and (cell["suppressed"] or cell["rows"] >= minimum)
    for cell in label["rates_by_cut"]:
        assert cell["suppressed"] == (cell["customers"] is None) and (cell["suppressed"] or cell["customers"] >= minimum)
    assert any(c["suppressed"] for c in retention["by_country"]), "the quick history has small country cells: the rule is exercised"


def test_cumulative_rules_are_read_once_from_the_latest_loaded_run(star_files, tmp_path):
    """Project 03, D94: a rule whose aggregation is ``latest`` (or ``source``) is read once, from the latest loaded run; a ``per_run`` rule is
    summed over the loaded runs; a rule no loaded run recorded is ``not_evaluated``; a run whose delivery is not loaded does not count."""
    cfg, _out, _private, _paths, meta, warehouse = star_files
    copy = tmp_path / "warehouse.sqlite"
    shutil.copy2(warehouse, copy)
    conn = connect(copy)
    try:
        runs = [r[0] for r in conn.execute("SELECT run_key FROM deliveries WHERE status = 'loaded' ORDER BY as_of_date")][:3]
        assert len(runs) == 3
        conn.execute("INSERT INTO deliveries (delivery_id, kind, lines_from, lines_to, as_of_date, lines, sha256, status, run_key) "
                     "VALUES ('M2099-01', 'monthly', '2099-01-01', '2099-01-31', '2099-01-31', 1, 'x', 'rejected', 'r99')")
        rows = []
        for i, run in enumerate([*runs, "r99"], start=1):
            for rule_id, count in (("I07", 100 * i), ("V20", i), ("V01", 7), ("I03", 1000 + i)):
                rule = RULES[rule_id]
                rows.append((run, rule_id, rule.name_es, rule.severity.value, rule.scope, rule.aggregation.value, 1, count, count, 0.0, "[]"))
        conn.executemany("INSERT INTO validation_results (run_key, rule_id, name_es, severity, scope, aggregation, passed, rows_affected, customers_affected, "
                         "value_gbp, examples_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
        export_site(conn, tmp_path / "site", meta, cfg)
    finally:
        conn.close()
    doc = json.loads((tmp_path / "site" / "validation_rules.json").read_text(encoding="utf-8"))
    by_id = {r["rule_id"]: r for r in doc["rules"]}
    assert [r["rule_id"] for r in doc["rules"]] == list(RULES)
    assert (by_id["I07"]["aggregation"], by_id["I07"]["rows"]) == ("latest", 300), "the latest loaded run's count, read once"
    assert (by_id["V20"]["aggregation"], by_id["V20"]["rows"]) == ("per_run", 1 + 2 + 3), "summed over the loaded runs only"
    assert (by_id["V01"]["aggregation"], by_id["V01"]["rows"]) == ("source", 7)
    assert by_id["V10"]["status"] == "not_evaluated" and by_id["I07"]["status"] == "pass"
    assert doc["totals"]["overlap_removed"] == 1003 and doc["totals"]["guest_lines"] == 6 and doc["totals"]["deliveries_rejected"] == 1
    summary = json.loads((tmp_path / "site" / "summary.json").read_text(encoding="utf-8"))
    assert summary["headline"]["lines_raw"] == summary["headline"]["lines_base"] + 1003


# --- the schema -------------------------------------------------------------------------------------------------------------------


def test_each_file_has_the_envelope_and_the_schema_of_the_plan_and_all_five_fit_in_200_kb(site):
    total = 0
    for name in SITE_FILES:
        data = (site.folder / name).read_bytes()
        total += len(data)
        assert data.endswith(b"\n") and data.decode("utf-8") == json.dumps(json.loads(data), ensure_ascii=False, sort_keys=True, indent=1) + "\n", name
        doc = site.docs[name]
        for key, kind in {**ENVELOPE, **SCHEMA[name]}.items():
            assert isinstance(doc[key], kind), (name, key, type(doc[key]))
        assert doc["attribution"].startswith("Chen, D. (2012). Online Retail II") and "CC BY 4.0" in doc["attribution"]
        assert (doc["run_key"], doc["as_of"], doc["source_sha256"]) == (site.meta.run_key, site.meta.as_of.isoformat(), site.meta.source_sha256)
    assert total <= site.cfg.site.max_total_bytes == 204800
    summary = site.docs["summary.json"]
    assert tuple(summary["headline"]) == HEADLINE or set(summary["headline"]) == set(HEADLINE)
    assert [c["id"] for c in summary["criteria"]] == [f"C{i:02d}" for i in range(1, 11)] and all(set(c) == set(CRITERION) for c in summary["criteria"])
    assert set(summary["seal"]) == {"config_sha256", "launch_run_key", "test_run_key", "test_as_of"}
    algorithms = site.docs["algorithms.json"]
    assert len(algorithms["selection"]) == len(site.cfg.model.learning_rate) * len(site.cfg.model.max_leaf_nodes) * len(site.cfg.model.min_samples_leaf) * len(site.cfg.features.candidate_sets)
    assert len(algorithms["cost_curve"]) == 17 and len(algorithms["calibration"]) == 10 and len(algorithms["variants"]) == 4
    assert all(set(e) == set(EXAMPLE) for e in algorithms["examples"]) and len(algorithms["examples"]) <= 5
    assert {(m["method"], m["scope"]) for m in algorithms["methods"]} >= {("model", "test"), ("model", "valid_v2"), ("b2_rfm", "test")}


def test_every_figure_is_the_one_of_the_parquet_files_and_of_the_summary_of_the_same_run(site, star_files):
    _cfg, out_dir, _private, _paths, _meta, _w = star_files
    metrics = pd.read_parquet(out_dir / "fact_method_metrics.parquet")
    test = metrics[(metrics["scope"] == "test") & (metrics["seal_state"] == "sealed")].set_index("method_key")
    headline = site.docs["summary.json"]["headline"]
    assert site.docs["summary.json"]["evaluation_status"] == "sealed"
    assert headline["auc"]["model"] == round(test.loc["model", "auc"], 3) and headline["auc"]["b2_rfm"] == round(test.loc["b2_rfm", "auc"], 3)
    assert headline["net_benefit_per_1000"]["contact_all"] == round(test.loc["b0_all", "nb_per_1000"], 1)
    model = pd.read_parquet(out_dir / "dim_model.parquet").iloc[0]
    assert headline["threshold"] == round(model["threshold"], 2) == site.docs["retention.json"]["threshold"] and headline["b_star"] == model["b_star"]
    cuts = pd.read_parquet(out_dir / "dim_cut.parquet")
    for cell in site.docs["label.json"]["rates_by_cut"]:
        row = cuts[cuts["cut_date"].astype(str) == cell["cut"]].iloc[0]
        assert cell["customers"] == row["active_customers"] and cell["block"] == row["block"]
        if cell["churn_rate"] is not None:
            assert cell["churn_rate"] == round(row["churn_rate"], 3) and not row["is_censored"]
    tracking = pd.read_parquet(out_dir / "fact_tracking.parquet")
    for cut in site.docs["retention.json"]["cuts"]:
        part = tracking[tracking["cut_key"] == int(cut["cut"].replace("-", ""))]
        assert cut["scored"] == int(part["scored"].iloc[0]) and len(cut["by_as_of"]) == len(part)
    country = pd.read_parquet(out_dir / "fact_cut_country.parquet")
    part = country[country["cut_key"] == int(site.docs["retention.json"]["by_country_cut"].replace("-", ""))]
    assert sorted(c["suppressed"] for c in site.docs["retention.json"]["by_country"]) == sorted(bool(s) for s in part["suppressed"])
    assert sorted(c["customers"] for c in site.docs["retention.json"]["by_country"] if c["customers"] is not None) == sorted(int(n) for n in part["customers"].dropna())


# --- the manifest -------------------------------------------------------------------------------------------------------------------


def test_the_manifest_names_the_five_files_with_their_bytes_and_sha256(site):
    manifest = json.loads((site.folder / MANIFEST_FILE).read_text(encoding="utf-8"))
    assert sorted(manifest["files"]) == sorted(SITE_FILES) and verify_site(site.folder) == []
    for name, entry in manifest["files"].items():
        data = (site.folder / name).read_bytes()
        assert entry == {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    assert manifest["run_key"] == site.meta.run_key


def test_rewriting_the_summary_keeps_one_export_and_is_refused_over_a_mixed_folder(site, star_files, tmp_path):
    cfg, _out, _private, _paths, meta, _w = star_files
    folder = tmp_path / "site"
    shutil.copytree(site.folder, folder)
    conn = connect(site.warehouse)
    try:
        export_summary(conn, folder, meta, cfg)
        assert verify_site(folder) == []
        (folder / "label.json").write_text("{}\n", encoding="utf-8")
        with pytest.raises(SiteExportError, match="no se reescribe el resumen"):
            export_summary(conn, folder, meta, cfg)
    finally:
        conn.close()
    with pytest.raises(SiteSetError, match="label.json"):
        read_site(folder)


def test_a_set_over_the_size_cap_writes_nothing(star_files, tmp_path):
    cfg, _out, _private, _paths, meta, warehouse = star_files
    small = dataclasses.replace(cfg, site=dataclasses.replace(cfg.site, max_total_bytes=10_000))
    conn = connect(warehouse)
    try:
        with pytest.raises(SiteExportError, match="el tope es 10000: no se escribió ninguno"):
            export_site(conn, tmp_path / "site", meta, small)
    finally:
        conn.close()
    assert not (tmp_path / "site").exists()


def test_before_the_seal_no_result_of_the_test_is_published(star_files, tmp_path):
    """Until the test is sealed with this configuration, every figure of the test is null or empty (D17); V2 is published, labelled."""
    cfg, _out, _private, _paths, meta, warehouse = star_files
    copy = tmp_path / "w.sqlite"
    shutil.copy2(warehouse, copy)
    conn = connect(copy)
    try:
        conn.execute("DELETE FROM eval_criteria")
        conn.execute("UPDATE star_fact_method_metrics SET seal_state = 'post_seal' WHERE scope = 'test'")
        shutil.copy2(cfg.paths.seal, tmp_path / "launch_only.json")
        seal = json.loads((tmp_path / "launch_only.json").read_text(encoding="utf-8"))
        seal.pop("test", None)
        (tmp_path / "launch_only.json").write_text(json.dumps(seal), encoding="utf-8")
        launch_only = dataclasses.replace(cfg, paths=dataclasses.replace(cfg.paths, seal=tmp_path / "launch_only.json"))
        export_site(conn, tmp_path / "site", meta, launch_only)
    finally:
        conn.close()
    docs = {name: json.loads((tmp_path / "site" / name).read_text(encoding="utf-8")) for name in SITE_FILES}
    headline = docs["summary.json"]["headline"]
    assert docs["summary.json"]["evaluation_status"] == "pending"
    assert headline["test_churn_rate"] is None and set(headline["auc"].values()) == {None} and set(headline["capture_10"].values()) == {None}
    assert all(c["value"] is None and c["passed"] is None for c in docs["summary.json"]["criteria"])
    algorithms = docs["algorithms.json"]
    assert algorithms["gain"] == [] and algorithms["calibration"] == [] and algorithms["examples"] == [] and algorithms["variants"] == []
    assert {m["scope"] for m in algorithms["methods"]} == {"valid_v2"}


# --- protect: the rule of the marts ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("counts", "hidden"), [
    ([50, 30, 4], [False, True, True]),            # one hidden: the smallest shown is hidden too
    ([50, 30, 4, 3], [False, False, True, True]),  # two hidden: nothing more
    ([50, 30, 20], [False, False, False]),
    ([50, 30, 30, 4], [False, True, False, True]),  # a tie goes to the first
    ([4], [True]),
    ([None, 40, 30], [True, False, True]),
])
def test_protect_hides_small_cells_and_never_leaves_one_hidden_cell_of_a_published_total(counts, hidden):
    cells = [{"label": i, "n": n} for i, n in enumerate(counts)]
    out = protect(cells, counts, ("label",), 10)
    assert [c["suppressed"] for c in out] == hidden
    assert all(c["n"] is None and c["label"] == i for i, c in enumerate(out) if c["suppressed"])
    assert [c["suppressed"] for c in protect(cells, counts, ("label",), 10, total_published=False)] == [n is None or n < 10 for n in counts]


def test_protect_gives_the_suppression_of_the_marts_on_their_own_counts(star_files):
    """The site's rule is the marts' rule (U20): on the raw counts of each cut by band, ``protect`` hides exactly the cells the mart hides."""
    cfg, out_dir, _private, _paths, _meta, warehouse = star_files
    conn = sqlite3.connect(warehouse)
    try:
        raw = pd.read_sql_query("SELECT s.cut_date, (SELECT b.band_key FROM ref_band AS b WHERE s.risk >= b.p_low AND (s.risk < b.p_high OR b.band_key = 10)) AS band_key, "
                                "COUNT(*) AS n FROM model_scores AS s GROUP BY s.cut_date, band_key ORDER BY s.cut_date, band_key", conn)
    finally:
        conn.close()
    mart = pd.read_parquet(out_dir / "fact_cut_band.parquet")
    checked = 0
    for cut, part in raw.groupby("cut_date"):
        key = int(cut.replace("-", ""))
        mine = protect([{"band": b} for b in part["band_key"]], list(part["n"]), ("band",), cfg.site.min_cell_customers)
        theirs = mart[mart["cut_key"] == key].set_index("band_key")["suppressed"]
        assert [c["suppressed"] for c in mine] == [bool(theirs[b]) for b in part["band_key"]], cut
        checked += sum(c["suppressed"] for c in mine)
    assert checked > 0, "the quick history hides cells: the comparison is not vacuous"


def test_a_test_evaluated_with_another_configuration_is_not_published_as_the_result(star_files, tmp_path):
    """With a launch-only seal and the test evaluated with other costs (``post_seal``), the summary says so and the headline publishes no
    figure of the test: only the sealed configuration's test is a result (D17)."""
    cfg, _out, _private, _paths, meta, warehouse = star_files
    copy = tmp_path / "w.sqlite"
    shutil.copy2(warehouse, copy)
    seal = json.loads(cfg.paths.seal.read_text(encoding="utf-8"))
    seal.pop("test", None)
    (tmp_path / "launch_only.json").write_text(json.dumps(seal), encoding="utf-8")
    other = dataclasses.replace(cfg, costs=dataclasses.replace(cfg.costs, offer_cost=6.0),
                                paths=dataclasses.replace(cfg.paths, seal=tmp_path / "launch_only.json"))
    conn = connect(copy)
    try:
        for table in ("eval_criteria", "eval_metrics"):
            conn.execute(f"UPDATE {table} SET seal_state = 'post_seal' WHERE seal_state = 'sealed'" + (" AND scope = 'test'" if table == "eval_metrics" else ""))
        export_site(conn, tmp_path / "site", meta, other)
    finally:
        conn.close()
    summary = json.loads((tmp_path / "site" / "summary.json").read_text(encoding="utf-8"))
    assert summary["evaluation_status"] == "post_seal"
    assert set(summary["headline"]["auc"].values()) == {None} and summary["headline"]["test_churn_rate"] is None
    assert set(summary["headline"]["net_benefit_per_1000"].values()) == {None}


# --- the review advisories of U23 ------------------------------------------------------------------------------------------------


def star_tables_read() -> list[str]:
    """The ``star_*`` tables that the queries of ``site_export.py`` name (every string of the module but the ``REQUIRED_STAR`` list itself)."""
    import ast

    from churnrisk import site_export

    tree = ast.parse(Path(site_export.__file__).read_text(encoding="utf-8"))
    skipped = {id(node) for assign in ast.walk(tree) if isinstance(assign, ast.Assign) and any(getattr(t, "id", None) == "REQUIRED_STAR" for t in assign.targets)
               for node in ast.walk(assign.value)}
    texts = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in skipped]
    return sorted({name for text in texts for name in re.findall(r"\bstar_(?:dim|fact)_[a-z0-9_]+", text)})


def test_the_export_checks_every_star_table_its_queries_read_from_one_list():
    """R2-require-star-incomplete: ``_require_star`` checks the one list of the star tables the export reads, all of them."""
    from churnrisk.site_export import REQUIRED_STAR

    read = star_tables_read()
    assert len(read) >= 16 and sorted(REQUIRED_STAR) == read, sorted(set(read) ^ set(REQUIRED_STAR))


@pytest.mark.parametrize("table", star_tables_read())
def test_a_missing_star_table_is_refused_by_name_before_any_file_is_written(site, star_files, tmp_path, table):
    """R2-require-star-incomplete, R3-require-star-untested: a star model missing any table the export reads is ``SiteExportError`` naming
    that table, raised before anything is built or written (not a database error from deep inside a builder)."""
    cfg, _out, _private, _paths, meta, _w = star_files
    conn = connect(site.warehouse)
    try:
        conn.execute("BEGIN")
        conn.execute(f"DROP TABLE {table}")
        with pytest.raises(SiteExportError, match=re.escape(f"faltan las tablas del modelo estrella ['{table}']")):
            export_site(conn, tmp_path / "site", meta, cfg)
        conn.execute("ROLLBACK")
    finally:
        conn.close()
    assert not (tmp_path / "site").exists()


def test_a_cut_scored_below_the_minimum_publishes_neither_its_count_nor_its_contacts(site, star_files, tmp_path):
    """R3-scored-not-suppressed: the customers scored at a cut are a count of customers, hidden under the minimum like ``label.json``'s
    customers of a cut; its contacts and its share go with it. The other cuts keep their counts."""
    cfg, _out, _private, _paths, meta, _w = star_files
    minimum = cfg.site.min_cell_customers
    conn = connect(site.warehouse)
    try:
        first = conn.execute("SELECT MIN(cut_key) FROM star_fact_tracking").fetchone()[0]
        conn.execute("BEGIN")
        conn.execute("UPDATE star_fact_tracking SET scored = ?, contacted = 0 WHERE cut_key = ?", (minimum - 1, first))
        export_site(conn, tmp_path / "site", meta, cfg)
        conn.execute("ROLLBACK")
    finally:
        conn.close()
    cuts = {c["cut"]: c for c in json.loads((tmp_path / "site" / "retention.json").read_text(encoding="utf-8"))["cuts"]}
    small = cuts[f"{str(first)[:4]}-{str(first)[4:6]}-{str(first)[6:]}"]
    assert (small["scored"], small["contacted"], small["contact_share"]) == (None, None, None)
    shown = {c["cut"]: c["scored"] for c in site.docs["retention.json"]["cuts"]}
    assert all(cuts[k]["scored"] == v for k, v in shown.items() if k != small["cut"]) and all(v >= minimum for v in shown.values())


def test_lines_raw_is_the_same_figure_in_the_summary_and_the_validation_totals_whatever_i03_aggregates(site, star_files, tmp_path, monkeypatch):
    """R2-lines-raw-duplicated-aggregation: ``summary.json`` and ``validation_rules.json`` take the overlap of I03 from one aggregation, the
    rule's own: if I03 were summed per run, both files would say so."""
    from churnrisk.validate import Aggregation

    cfg, _out, _private, _paths, meta, _w = star_files
    monkeypatch.setitem(RULES, "I03", dataclasses.replace(RULES["I03"], aggregation=Aggregation.PER_RUN))
    rule = RULES["I03"]
    conn = connect(site.warehouse)
    try:
        runs = [r[0] for r in conn.execute("SELECT run_key FROM deliveries WHERE status = 'loaded' ORDER BY as_of_date")][:3]
        conn.execute("BEGIN")
        conn.execute("DELETE FROM validation_results WHERE rule_id = 'I03'")
        conn.executemany("INSERT INTO validation_results (run_key, rule_id, name_es, severity, scope, aggregation, passed, rows_affected, customers_affected, "
                         "value_gbp, examples_json) VALUES (?, 'I03', ?, ?, ?, ?, 1, ?, 0, 0.0, '[]')",
                         [(run, rule.name_es, rule.severity.value, rule.scope, rule.aggregation.value, 1000 + i) for i, run in enumerate(runs, start=1)])
        export_site(conn, tmp_path / "site", meta, cfg)
        conn.execute("ROLLBACK")
    finally:
        conn.close()
    totals = json.loads((tmp_path / "site" / "validation_rules.json").read_text(encoding="utf-8"))["totals"]
    headline = json.loads((tmp_path / "site" / "summary.json").read_text(encoding="utf-8"))["headline"]
    assert totals["overlap_removed"] == 1001 + 1002 + 1003
    assert headline["lines_raw"] == totals["lines_raw"] == headline["lines_base"] + 3006


def test_an_export_before_the_launch_has_no_model_row_and_writes_nothing(site, star_files, tmp_path):
    """R3-model-row-untested: a star model with no model (an export before the launch) is ``SiteExportError`` and no file is written."""
    cfg, _out, _private, _paths, meta, _w = star_files
    conn = connect(site.warehouse)
    try:
        conn.execute("BEGIN")
        conn.execute("DELETE FROM star_dim_model")
        with pytest.raises(SiteExportError, match="no hay un modelo en el modelo estrella: el sitio se escribe después del lanzamiento"):
            export_site(conn, tmp_path / "site", meta, cfg)
        conn.execute("ROLLBACK")
    finally:
        conn.close()
    assert not (tmp_path / "site").exists()


def test_an_open_window_publishes_who_returned_under_the_primary_rule_and_no_churned_count(site, star_files, tmp_path):
    """R3-open-window-pair-untested: while a cut's window is open, who churned is unknown (``null``) and who returned is a cell of its own,
    shown only from the minimum on; once the window closes the two go through ``protect`` together."""
    from churnrisk.site_export import _pair

    cfg, out_dir, _private, _paths, meta, _w = star_files
    minimum = cfg.site.min_cell_customers
    tracking = pd.read_parquet(out_dir / "fact_tracking.parquet")
    opened = 0
    for cut in site.docs["retention.json"]["cuts"]:
        for row in cut["by_as_of"]:
            if row["window_closed"]:
                continue
            opened += 1
            fact = tracking[(tracking["cut_key"] == int(cut["cut"].replace("-", ""))) & (tracking["as_of_key"] == int(row["as_of"].replace("-", "")))].iloc[0]
            assert row["churned"] is None and row["contacted_churned"] is None, (cut["cut"], row["as_of"])
            for key in ("returned", "contacted_returned"):
                expected = None if pd.isna(fact[key]) or fact[key] < minimum else int(fact[key])
                assert row[key] == expected, (cut["cut"], row["as_of"], key)
    assert opened > 0, "the quick history has cuts whose window is still open"
    assert _pair(minimum - 1, None, minimum) == (None, None) and _pair(minimum, None, minimum) == (minimum, None) and _pair(None, None, minimum) == (None, None)
    conn = connect(site.warehouse)
    try:
        key, as_of = conn.execute("SELECT cut_key, as_of_key FROM star_fact_tracking WHERE window_closed = 0 ORDER BY cut_key, as_of_key LIMIT 1").fetchone()
        conn.execute("BEGIN")
        conn.execute("UPDATE star_fact_tracking SET returned = ? WHERE cut_key = ? AND as_of_key = ?", (minimum - 1, key, as_of))
        export_site(conn, tmp_path / "site", meta, cfg)
        conn.execute("ROLLBACK")
    finally:
        conn.close()
    cuts = json.loads((tmp_path / "site" / "retention.json").read_text(encoding="utf-8"))["cuts"]
    [row] = [r for c in cuts if c["cut"].replace("-", "") == str(key) for r in c["by_as_of"] if r["as_of"].replace("-", "") == str(as_of)]
    assert (row["returned"], row["churned"], row["window_closed"]) == (None, None, False)
