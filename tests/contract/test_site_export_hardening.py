"""The site export against the three ways project 03's review of U20 found a published file could point at someone or mix two exports (D77 of
project 03; plan 24.2; U23, AC29): an example detail kept only while enough customers share it, no hidden cell given back by subtraction, and a
failure in the middle of the writes leaving a set that is refused."""

from __future__ import annotations

import json
import shutil
import sqlite3

import pandas as pd
import pytest

from churnrisk import site_export
from churnrisk.dashboard.semantic_model import FEATURES_ES
from churnrisk.site_export import SITE_FILES, SiteSetError, export_site, read_site, verify_site
from churnrisk.warehouse import connect
from tests.contract.test_site_export import export_to


@pytest.fixture(scope="module")
def site(star_files, tmp_path_factory):
    return export_to(star_files, tmp_path_factory.mktemp("site_hardening"))


def last_test_cut(warehouse) -> pd.DataFrame:
    """Every scored customer of the last test cut with what an example can say about it, as ``site_export`` computes it."""
    conn = sqlite3.connect(warehouse)
    try:
        last = conn.execute("SELECT MAX(cut_date) FROM cut_blocks WHERE block = 'test'").fetchone()[0]
        rows = pd.read_sql_query("SELECT s.customer_id, s.risk, s.is_contact, l.churned, f.rec_days, f.freq_365, f.mon_365 FROM model_scores AS s "
                                 "JOIN cut_labels AS l ON l.cut_date = s.cut_date AND l.customer_id = s.customer_id "
                                 "JOIN cut_features AS f ON f.cut_date = s.cut_date AND f.customer_id = s.customer_id WHERE s.cut_date = ? ORDER BY s.rowid", conn, params=(last,))
        reasons = pd.read_sql_query("SELECT customer_id, rank, feature FROM score_reasons WHERE cut_date = ?", conn, params=(last,))
    finally:
        conn.close()
    names = {f: FEATURES_ES[f][0] for f in FEATURES_ES}
    by_rank = reasons.pivot(index="customer_id", columns="rank", values="feature")
    for rank in (1, 2, 3):
        rows[f"reason_{rank}_es"] = rows["customer_id"].map(by_rank[rank]).map(names) if rank in by_rank.columns else None
    rows["risk_quintile"] = pd.qcut(rows["risk"].rank(method="first"), 5, labels=False) + 1
    for column, word, key in (("rec_days", "recencia", "recency_band_es"), ("freq_365", "frecuencia", "frequency_band_es"), ("mon_365", "gasto", "spend_band_es")):
        band = pd.qcut(rows[column].rank(method="first"), 5, labels=False) + 1
        rows[key] = [f"quintil {int(b)} de 5 de {word} en el corte" for b in band]
    rows["risk_raw"], rows["risk"] = rows["risk"], rows["risk"].round(2)
    rows["outcome"] = rows["churned"].map({1: "se fue", 0: "volvió"})
    rows["contacted"] = rows["is_contact"].astype(bool)
    return rows


def test_an_example_detail_is_published_only_while_enough_customers_share_it(site, star_files):
    """D27: every published example is shared, in everything it says, by at least the minimum of customers of the last test cut; a detail
    left ``null`` would have left fewer; and there is one example per quintile that has enough customers (here all five)."""
    minimum = site.cfg.site.min_cell_customers
    rows = last_test_cut(site.warehouse)
    examples = site.docs["algorithms.json"]["examples"]
    assert [e["risk_quintile"] for e in examples] == [1, 2, 3, 4, 5] and [e["label"] for e in examples] == ["Cliente A", "Cliente B", "Cliente C", "Cliente D", "Cliente E"]
    details = ("risk", "reason_1_es", "reason_2_es", "reason_3_es", "recency_band_es", "frequency_band_es", "spend_band_es")
    for example in examples:
        quintile = rows[rows["risk_quintile"] == example["risk_quintile"]].sort_values("risk_raw", kind="stable")
        chosen = quintile.iloc[(len(quintile) - 1) // 2]           # the lower median of its quintile
        assert (chosen["outcome"], bool(chosen["contacted"])) == (example["outcome"], example["contacted"])
        same = (rows["risk_quintile"] == example["risk_quintile"]) & (rows["outcome"] == example["outcome"]) & (rows["contacted"] == example["contacted"])
        assert int(same.sum()) >= minimum, example["label"]
        for name in details:
            narrower = same & (rows[name] == chosen[name])
            if example[name] is not None:
                assert example[name] == chosen[name] and int(narrower.sum()) >= minimum, (example["label"], name)
                same = narrower
            else:
                assert pd.isna(chosen[name]) or int(narrower.sum()) < minimum, (example["label"], name)
        assert int(same.sum()) >= minimum, example["label"]
    assert any(e[name] is None for e in examples for name in details), "some detail is withheld: the rule is exercised"


def test_no_hidden_cell_is_a_published_total_minus_the_shown_cells(site):
    """A breakdown whose total is published never hides exactly one cell: the follow-up of each cut (who returned and who churned of the
    scored once the window closed, and the same of the contacted) and the calibration bins of the test."""
    for cut in site.docs["retention.json"]["cuts"]:
        for row in cut["by_as_of"]:
            if row["window_closed"]:
                assert [row["returned"], row["churned"]].count(None) != 1, (cut["cut"], row["as_of"])
                assert [row["contacted_returned"], row["contacted_churned"]].count(None) != 1, (cut["cut"], row["as_of"])
    calibration = site.docs["algorithms.json"]["calibration"]
    assert sum(c["suppressed"] for c in calibration) != 1
    bands = site.docs["retention.json"]["by_country"]
    assert sum(c["suppressed"] for c in bands) != 1, "the marts' secondary suppression, taken as it is"


def test_a_failure_in_the_middle_of_the_writes_leaves_a_set_that_is_refused(site, star_files, tmp_path, monkeypatch):
    """The five files are replaced one by one and the manifest last: a failure after two of them leaves a folder whose new files do not match
    the old manifest, which ``verify_site`` names and ``read_site`` refuses; the next complete export makes it one set again."""
    cfg, _out, _private, _paths, meta, _w = star_files
    folder = tmp_path / "site"
    shutil.copytree(site.folder, folder)
    real = site_export.write_atomic
    written = []

    def failing(path, data):
        if len(written) == 2:
            raise OSError("disk full, by the test")
        written.append(path.name)
        return real(path, data)

    warehouse = tmp_path / "warehouse.sqlite"
    shutil.copy2(site.warehouse, warehouse)
    conn = connect(warehouse)
    try:
        conn.execute("UPDATE star_dim_model SET threshold = 0.61")        # another export: other bytes for the files that carry the threshold
        monkeypatch.setattr(site_export, "write_atomic", failing)
        with pytest.raises(OSError, match="disk full"):
            export_site(conn, folder, meta, cfg)
        assert written == list(SITE_FILES[:2])
        problems = verify_site(folder)
        assert any("summary.json" in p for p in problems)
        with pytest.raises(SiteSetError):
            read_site(folder)
        monkeypatch.setattr(site_export, "write_atomic", real)
        export_site(conn, folder, meta, cfg)
    finally:
        conn.close()
    assert verify_site(folder) == [] and json.loads(read_site(folder)["retention.json"])["threshold"] == 0.61
