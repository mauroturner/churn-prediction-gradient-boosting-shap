"""The quick run of the whole plan on the standard fixture, composed from the functions of the tasks (U16 onwards): for each delivery in order,
its load and its cuts, ``fit_model`` (the launch trains and seals; every later run reuses the frozen model), the scores of its cut and
``evaluate`` (V2 at the launch; the test once, in the run whose date closes its windows). It is the sealed run of the tests: the test cuts are
touched once, here. ``pipeline.py`` (U25) runs the same steps as tasks; until then this helper is
what composes them, and the session fixture ``quick_history`` builds it once (D34).

The configuration is the quick one (``config/pipeline.quick.toml``: one candidate, 50 iterations, 200 resamples) with every path inside the
history's own folder.
"""

from __future__ import annotations

import dataclasses
import shutil
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from churnrisk.config import PipelineConfig, SealedConfig, load_config
from churnrisk.cuts import build_cuts
from churnrisk.deliveries import DeliverySpec, delivery_plan, delivery_rows
from churnrisk.launch import fit_model, load_registered
from churnrisk.registry import sealed_view
from churnrisk.reporting import evaluate
from churnrisk.scoring import RunMeta, ScoreResult, score_cut
from churnrisk.warehouse import connect, load_delivery

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def quick_config(folder: Path, **sections) -> PipelineConfig:
    """The quick configuration with every path under `folder`; `sections` replace whole sections (``costs=...``)."""
    base = load_config(PROJECT_ROOT / "config" / "pipeline.quick.toml")
    folder = Path(folder)
    paths = dataclasses.replace(
        base.paths, raw_dir=folder / "raw", interim_dir=folder / "interim", warehouse=folder / "churnrisk.sqlite", models_dir=folder / "models",
        outputs_dir=folder / "outputs" / "powerbi", private_dir=folder / "outputs" / "private", site_dir=folder / "outputs" / "site",
        reports_dir=folder / "reports", seal=folder / "reports" / "model_seal.json", dashboard_html=folder / "dashboard" / "powerbi-design.html",
        readme=folder / "README.md", figures_dir=folder / "figures",
    )
    return dataclasses.replace(base, paths=paths, **sections)


@dataclass
class RunRecord:
    """What one run of the history did and what the warehouse and the seal held after it."""

    spec: DeliverySpec
    run_key: str
    fit: dict
    score: ScoreResult | None
    evaluation: dict
    scores: list[tuple]
    reasons: list[tuple]
    seal: bytes
    warehouse: Path          # a copy of the warehouse as the run left it (read it; a test that writes copies it again)


@dataclass
class History:
    cfg: PipelineConfig
    view: SealedConfig
    folder: Path
    runs: list[RunRecord] = field(default_factory=list)

    @property
    def warehouse(self) -> Path:
        return self.cfg.paths.warehouse


def _table(conn: sqlite3.Connection, table: str) -> list[tuple]:
    return conn.execute(f"SELECT * FROM {table} ORDER BY 1, 2, 3").fetchall()


def run_one(conn: sqlite3.Connection, cfg: PipelineConfig, view: SealedConfig, spec: DeliverySpec, run_key: str) -> tuple[dict, ScoreResult | None, dict]:
    """``fit_model``, the scores of the run's cut and ``evaluate``, on a warehouse where the run's delivery is loaded and its cuts are built."""
    fit = fit_model(conn, cfg, run_key=run_key, as_of=spec.as_of, source_sha256=view.source_sha256)
    score = None
    if spec.cut is not None:
        registered = load_registered(conn, cfg)
        score = score_cut(conn, spec.cut, registered.bundle, RunMeta(run_key, spec.as_of, registered.model_version, registered.threshold), view)
    evaluation = evaluate(conn, cfg, run_key=run_key, as_of=spec.as_of, source_sha256=view.source_sha256)
    return fit, score, evaluation


def build_history(folder: Path, cfg: PipelineConfig, source_sha256: str, launch_warehouse: Path, frame: pd.DataFrame, entries: dict,
                  until: str | None = None) -> History:
    """Run the plan in order on a copy of `launch_warehouse` (the launch loaded and its cuts built by run ``r1``), up to the delivery `until`
    (all of them by default). Each later delivery is loaded by its own run ``r2``, ``r3``... with the SHA-256 of its published file."""
    view = sealed_view(cfg, source_sha256)
    history = History(cfg, view, Path(folder))
    cfg.paths.warehouse.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(launch_warehouse, cfg.paths.warehouse)
    for index, spec in enumerate(delivery_plan(cfg)):
        run_key = f"r{index + 1}"
        conn = connect(cfg.paths.warehouse)
        try:
            if index:
                load_delivery(conn, delivery_rows(spec, frame), spec, run_key, sha256=entries[spec.delivery_id].sha256)
                build_cuts(conn, spec.as_of, view, run_key)
            fit, score, evaluation = run_one(conn, cfg, view, spec, run_key)
            scores, reasons = _table(conn, "model_scores"), _table(conn, "score_reasons")
        finally:
            conn.close()
        kept = history.folder / "after" / f"{run_key}.sqlite"
        kept.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(cfg.paths.warehouse, kept)
        history.runs.append(RunRecord(spec, run_key, fit, score, evaluation, scores, reasons, cfg.paths.seal.read_bytes(), kept))
        if spec.delivery_id == until:
            break
    return history


SCOPED_TABLES = ("eval_metrics", "eval_per_cut", "eval_bootstrap", "eval_cost_sensitivity", "eval_gain", "eval_roc", "eval_calibration",
                 "feature_importance")
TEST_TABLES = ("eval_criteria", "eval_variants")      # written only with the test


def without_sealed_rows(history: History, folder: Path, **sections) -> PipelineConfig:
    """A copy of the history's last warehouse and of its seal with the sealed rows of the test gone, as a rebuild from scratch leaves them by
    the run that closes the test windows (the rows of V2 are written again by its own launch), and the quick configuration with `sections`
    replaced."""
    cfg = quick_config(folder, **sections)
    cfg.paths.seal.parent.mkdir(parents=True)
    shutil.copy2(history.cfg.paths.seal, cfg.paths.seal)
    shutil.copy2(history.warehouse, cfg.paths.warehouse)
    conn = connect(cfg.paths.warehouse)
    try:
        for table in SCOPED_TABLES:
            conn.execute(f"DELETE FROM {table} WHERE seal_state = 'sealed' AND scope = 'test'")
        for table in TEST_TABLES:
            conn.execute(f"DELETE FROM {table} WHERE seal_state = 'sealed'")
    finally:
        conn.close()
    return cfg
