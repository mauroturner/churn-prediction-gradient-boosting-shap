"""The first complete run on the real data (U29, mark real_data; AC04, AC10, AC37; RNF02, RNF03, RNF10; D19, D20).

It reads what ``python -m churnrisk replay`` and the run with no delivery left after it wrote with the full configuration in this project's
own folders: the warehouse, the seal, the evaluation summary, the star model, the site files and the dashboard design (the versioned outputs
other than the seal are those of the same replay of the corrected code in a fresh copy, whose seal reproduced this one; D85, D86). Without those outputs
it fails, so it is the RED of U29 until the real run has been made once. It never runs the pipeline itself: the test cuts are evaluated once,
by that run, under the seal (D19), and a test that ran it again would either repeat the seal or be refused by it.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime

import pytest

from churnrisk.evaluation import criteria_from_seal
from churnrisk.export import verify_star_schema
from churnrisk.registry import config_fingerprint, read_seal, seal_state, sealed_view
from churnrisk.site_export import verify_site
from churnrisk.sysinfo import POSIX_COUNTER, WINDOWS_COUNTER

pytestmark = pytest.mark.real_data

ZIP_SHA256 = "572e36277c2390fbfde10664750731e0a86f55e33470d91919085f0408e67bfb"
DELIVERIES = ("L2011-07", "M2011-08", "M2011-09", "M2011-10", "M2011-11", "C2011-12")
# cut -> (active in the 90 days before, churn rate with N = 90), requirements.md section 4 (AC10)
TRAINING = {
    "2010-06-01": (2_012, 0.443), "2010-07-01": (2_013, 0.429), "2010-08-01": (1_993, 0.359), "2010-09-01": (1_925, 0.312),
    "2010-10-01": (2_018, 0.365), "2010-11-01": (2_477, 0.463), "2010-12-01": (2_859, 0.579),
}
LAUNCH_LIMIT_S, MONTHLY_LIMIT_S, REPLAY_LIMIT_S = 5 * 60, 2 * 60, 15 * 60          # RNF02
WORKING_SET_LIMIT_MB = 2.5 * 1024                                                    # RNF03: 2.5 GB of the peak working set
PARQUET_LIMIT_BYTES = 25 * 1024 * 1024                                               # RNF10, AC37


def _seconds(started: str, finished: str) -> float:
    return (datetime.fromisoformat(finished) - datetime.fromisoformat(started)).total_seconds()


def _rounded(value, decimals: int = 6):
    return round(value, decimals) if isinstance(value, float) else value


@pytest.fixture(scope="module")
def outputs(cfg):
    paths = cfg.paths
    expected = (paths.warehouse, paths.seal, paths.reports_dir / "evaluation_summary.json", paths.reports_dir / "evaluation_summary.md",
                paths.reports_dir / "validation" / "latest.json", paths.outputs_dir / "manifest.json", paths.site_dir / "manifest.json",
                paths.dashboard_html)
    missing = [str(p.relative_to(paths.reports_dir.parent)) for p in expected if not p.is_file()]
    assert not missing, f"the real run has not written {missing}: run `python -m churnrisk replay` and then `python -m churnrisk run` (U29)"
    conn = sqlite3.connect(f"{paths.warehouse.resolve().as_uri()}?mode=ro", uri=True)
    yield conn
    conn.close()


def test_real_counts_seal_and_summary_consistency(cfg, outputs):
    conn, paths = outputs, cfg.paths

    # AC04: the canonical base, in the warehouse and in what the site publishes
    assert conn.execute("SELECT COUNT(*) FROM raw_lines").fetchone()[0] == 1_044_848
    rules = json.loads((paths.site_dir / "validation_rules.json").read_text(encoding="utf-8"))
    totals = rules["totals"]
    assert (totals["lines_raw"], totals["overlap_removed"], totals["lines_base"]) == (1_067_371, 22_523, 1_044_848)
    assert (totals["deliveries_loaded"], totals["deliveries_rejected"]) == (len(DELIVERIES), 0)

    # AC10: the populations and the churn rates of the seven training cuts, as the warehouse holds them and as label.json publishes them
    rows, churned, customers = 0, 0, set()
    for cut, (active, rate) in TRAINING.items():
        members = {r[0] for r in conn.execute("SELECT customer_id FROM cut_features WHERE cut_date = ?", (cut,))}
        labels = [r[0] for r in conn.execute("SELECT churned FROM cut_labels WHERE cut_date = ?", (cut,))]
        assert (len(members), len(labels), round(sum(labels) / len(labels), 3)) == (active, active, rate), cut
        rows, churned, customers = rows + len(labels), churned + sum(labels), customers | members
    assert (rows, len(customers), round(churned / rows, 3)) == (15_297, 3_942, 0.432)
    assert {r[0] for r in conn.execute("SELECT cut_date FROM cut_blocks WHERE block = 'train'")} == set(TRAINING)
    published = {c["cut"]: c for c in json.loads((paths.site_dir / "label.json").read_text(encoding="utf-8"))["rates_by_cut"]}
    for cut, (active, rate) in TRAINING.items():
        assert (published[cut]["customers"], published[cut]["churn_rate"], published[cut]["suppressed"]) == (active, rate, False), cut

    # AC37 with RNF02 and RNF03: six runs, one per delivery and in order, then the run with no delivery left; times and memory with the counter
    runs = conn.execute("SELECT run_key, status, delivery_id, started_at, finished_at, peak_working_set_mb, memory_counter FROM pipeline_runs "
                        "ORDER BY started_at, run_key").fetchall()
    assert [(r[1], r[2]) for r in runs] == [("ok", d) for d in DELIVERIES] + [("no_delivery", None)], runs
    counter = WINDOWS_COUNTER if sys.platform == "win32" else POSIX_COUNTER
    seconds = {}
    for run_key, _status, delivery, started, finished, working_set, memory_counter in runs:
        seconds[delivery] = _seconds(started, finished)
        if delivery is not None:          # a run with no delivery records no peak: it never reaches a task that measures one into its row
            assert memory_counter == counter and 0 < working_set <= WORKING_SET_LIMIT_MB, (run_key, working_set, memory_counter)
    assert seconds["L2011-07"] <= LAUNCH_LIMIT_S, seconds
    assert all(seconds[d] <= MONTHLY_LIMIT_S for d in DELIVERIES[1:]), seconds
    assert seconds[None] <= MONTHLY_LIMIT_S and sum(seconds.values()) <= REPLAY_LIMIT_S, seconds
    sizes = {p.name: p.stat().st_size for p in paths.outputs_dir.glob("*.parquet")}
    assert sizes and all(size <= PARQUET_LIMIT_BYTES for size in sizes.values()), sizes
    assert verify_star_schema(paths.outputs_dir) == []
    assert not any(p.name == "fact_customer_cut.parquet" for p in paths.outputs_dir.iterdir()), "the customer-level fact is kept private (D26)"
    assert verify_site(paths.site_dir) == []
    site_files = [p for p in paths.site_dir.glob("*.json") if p.name != "manifest.json"]
    assert len(site_files) == 5 and sum(p.stat().st_size for p in site_files) <= cfg.site.max_total_bytes

    # the seal: both parts, the sealed configuration is this one, the launch's source is the pinned zip and the test part is of the M2011-11 run
    seal = read_seal(paths.seal)
    assert seal is not None and seal["test"] is not None
    view = sealed_view(cfg, ZIP_SHA256)
    assert seal_state(paths.seal, config_fingerprint(view)) == "match"
    assert seal["launch"]["source_sha256"] == ZIP_SHA256 and seal["launch"]["as_of"] == cfg.deliveries.launch_as_of.isoformat()
    by_delivery = {r[2]: r[0] for r in runs}
    assert (seal["launch"]["run_key"], seal["test"]["run_key"]) == (by_delivery["L2011-07"], by_delivery["M2011-11"])
    assert seal["test"]["config_sha256"] == seal["launch"]["config_sha256"]

    # the summary says what was sealed: evaluated from the warehouse's sealed rows, and each criterion equal to the one the seal rebuilds
    summary = json.loads((paths.reports_dir / "evaluation_summary.json").read_text(encoding="utf-8"))
    assert summary["evaluation_status"] == "sealed" and "sealed_from" not in summary and summary["post_seal"] is None
    # The versioned outputs come from the replay of the corrected code in a fresh copy (D85, D86), whose seal reproduced every sealed value of
    # this one except its two run keys; the seal kept is the first run's, so the summary's seal block names the other run's keys.
    assert {k: v for k, v in summary["seal"].items() if not k.endswith("run_key")} == {"config_sha256": seal["launch"]["config_sha256"],
                                                                                       "test_as_of": seal["test"]["as_of"]}
    assert summary["seal"]["launch_run_key"] < summary["seal"]["test_run_key"]
    rebuilt = {c.criterion_id: c for c in criteria_from_seal(seal)}
    assert [c["criterion_id"] for c in summary["criteria"]] == [f"C{i:02d}" for i in range(1, 11)] == list(rebuilt)
    for entry in summary["criteria"]:
        sealed = rebuilt[entry["criterion_id"]]
        assert {k: _rounded(entry[k]) for k in ("value", "baseline_value", "ci_low", "ci_high")} == \
            {k: _rounded(getattr(sealed, k)) for k in ("value", "baseline_value", "ci_low", "ci_high")}, entry["criterion_id"]
        assert (entry["passed"], entry["verdict_es"]) == (sealed.passed, sealed.verdict_es), entry["criterion_id"]
        assert (entry["passed"] is None) == (entry["criterion_id"] == "C10"), entry["criterion_id"]
    for method in ("model", "b2_rfm", "b_star"):
        assert _rounded(summary["test"][method]["auc"]) == _rounded(seal["test"]["metrics"][method]["auc"]), method

    # what the site publishes is that summary, rounded as the site shows it
    site = json.loads((paths.site_dir / "summary.json").read_text(encoding="utf-8"))
    assert (site["status"], site["evaluation_status"], site["seal"]) == ("ok", "sealed", summary["seal"])
    assert [(c["id"], c["passed"], c["verdict_es"]) for c in site["criteria"]] == [(c["criterion_id"], c["passed"], c["verdict_es"]) for c in summary["criteria"]]
    for shown, entry in zip(site["criteria"], summary["criteria"], strict=True):
        assert all(shown[k] == (None if entry[k] is None else round(entry[k], 4)) for k in ("value", "baseline_value", "ci_low", "ci_high")), entry["criterion_id"]
    headline = site["headline"]
    assert (headline["lines_raw"], headline["lines_base"], headline["train_churn_rate"]) == (1_067_371, 1_044_848, 0.432)
    assert headline["auc"] == {m: round(summary["test"][m]["auc"], 3) for m in ("model", "b2_rfm", "b_star")}
