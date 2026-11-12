"""The tasks of a monthly run, their state, the ordered close and the refusals (RF28, AC08, AC30, AC31, AC38; plan, sections 3 and 22; D30,
D77). Adapted from project 03's ``pipeline.py`` (its D72, D79, D86 and D93, with the corrections of its evaluation), from the design.

``TASKS`` is the one list the command line and the Airflow DAG run, in this order, with these functions. Every task of a run works on the state
file ``<interim>/runs/<run_key>.json`` (the start, the delivery, the status and the result of each task with its seconds and its memory peaks
with their counter, or the whole traceback if it failed) and, from ``load`` on, on the run's row of ``pipeline_runs``.

- **One writer.** ``run_task``, ``run_all`` and ``replay`` hold ``lock.sole_writer`` from before the state file is touched until they return
  (D31, D76): a second writer is ``RunLockedError`` (exit 2) and writes nothing; ``fit_model`` runs inside it like every task.
- **Refusals before writing** (``RunRefusedError``, exit 2, no retry), in this order: any task of a run that ended (``ok`` or ``no_delivery``);
  ``deliver`` in a run that already holds another delivery; ``load`` when another run loaded the delivery, and every task after ``load`` unless
  this run loaded its own delivery (project 03, D86); ``load`` without this run's validation report in ``reports/validation/history`` or with a
  blocking rule failing in it (D93); and the model tasks (``fit_model``, ``score``, ``track``, ``evaluate``) when the run's delivery is not the
  latest loaded one.
- **The close.** The run stays ``running`` until ``report`` closes it in this order: SQLite ``ok``, ``dim_pipeline_run.parquet`` alone,
  ``summary.json`` and the site manifest, the HTML, and only then the delivery ``loaded`` in the delivery manifest (project 03, D72). Closing
  never creates a run's row: it is ``load``'s.
- **A failure** after ``load`` marks the run ``failed`` in SQLite and rewrites the run table, the summary and the HTML if they exist; each of
  those writes is tried on its own and logged if it fails, and the task's error is raised again (project 03, D79). A run with no delivery
  records ``no_delivery`` and rewrites the run table and the HTML.

The frozen model's body stays in ``launch.py`` (``launch.fit_model``), the one place it is written; the task here calls it (D77).
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from churnrisk import ingest
from churnrisk.config import PipelineConfig, load_config
from churnrisk.cuts import build_cuts as build_cut_tables
from churnrisk.dashboard.render import render_design
from churnrisk.dashboard.semantic_model import MODEL
from churnrisk.deliveries import MANIFEST_NAME, DeliverySpec, assert_covered, delivery_plan, mark_delivery, next_pending, publish, read_delivery, read_manifest
from churnrisk.export import ExportMeta, export_run_table, export_star_schema, verify_star_schema
from churnrisk.files import write_atomic
from churnrisk.launch import fit_model as fit_frozen_model
from churnrisk.launch import load_registered
from churnrisk.lock import RunLockedError, RunRefusedError, RunStateError, sole_writer
from churnrisk.registry import sealed_view
from churnrisk.reporting import build_summary, write_summary
from churnrisk.reporting import evaluate as evaluate_model
from churnrisk.schema import SourceError
from churnrisk.scoring import RunMeta, score_cut
from churnrisk.site_export import export_site, export_summary, verify_site
from churnrisk.sysinfo import MemoryPeaks, peak_memory
from churnrisk.tracking import track as track_cuts
from churnrisk.validate import (
    Severity,
    ValidationError,
    ValidationReport,
    add_results,
    combine_reports,
    model_result,
    read_report,
    validate_delivery,
    validate_source,
    write_report,
)
from churnrisk.warehouse import apply_schema, connect, load_delivery

logger = logging.getLogger(__name__)

__all__ = ["TASKS", "TASK_IDS", "RunContext", "RunLockedError", "RunRefusedError", "RunStateError", "TaskSpec", "UsageError", "replay", "run_all", "run_task"]

CLOSED_STATUSES = ("ok", "no_delivery")
MODEL_TASK_IDS = ("fit_model", "score", "track", "evaluate")
CLOSING_STEPS = ("sqlite", "run_table", "summary", "html", "manifest")
RUN_COLUMNS = ("run_key", "started_at", "finished_at", "status", "delivery_id", "as_of_date", "cut_date", "source_sha256", "lines_delivery",
               "customers_scored", "contacts", "peak_working_set_mb", "peak_commit_mb", "memory_counter", "message")


class UsageError(ValueError):
    """A command asked for something the flow does not do (an unknown task, two selections together): nothing was written."""


class ExportError(RuntimeError):
    """The exported files do not keep their contract (their manifest, the site's set)."""


@dataclass(frozen=True)
class RunContext:
    cfg: PipelineConfig
    run_key: str
    started_at: datetime
    state_path: Path


@dataclass(frozen=True)
class TaskSpec:
    """One task: its id, its function and the limits the Airflow DAG gives it (retries, minutes between them, timeout in minutes; Airflow
    enforces them, ``run_task`` runs a task once). ``short_circuit`` marks ``deliver``: with no delivery left the run ends there."""

    task_id: str
    func: Callable[[RunContext], dict]
    retries: int
    retry_delay_min: int
    timeout_min: int
    short_circuit: bool = False


# --- state ------------------------------------------------------------------------------------------------------------------


def make_run_key(source: str | datetime) -> str:
    if isinstance(source, datetime):
        return source.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    key = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in str(source)).strip("_")
    if not key:
        raise UsageError("una clave de corrida no puede estar vacía")
    return key


def _state_path(cfg: PipelineConfig, run_key: str) -> Path:
    return Path(cfg.paths.interim_dir) / "runs" / f"{run_key}.json"


def _read_state(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _write_state(path: Path, state: dict) -> None:
    write_atomic(path, json.dumps(state, indent=2, ensure_ascii=False, default=str) + "\n")


def _context(cfg: PipelineConfig, run_id: str | None, when: datetime) -> RunContext:
    run_key = make_run_key(run_id if run_id is not None else when)
    path = _state_path(cfg, run_key)
    state = _read_state(path)
    if not state:
        state = {"run_key": run_key, "started_at": when.isoformat(timespec="seconds"), "status": "running", "tasks": {}}
        _write_state(path, state)
    return RunContext(cfg, run_key, datetime.fromisoformat(state["started_at"]), path)


def _task_result(ctx: RunContext, task_id: str) -> dict:
    result = _read_state(ctx.state_path).get("tasks", {}).get(task_id)
    if result is None or result.get("status") in ("failed", "rejected"):
        raise RunStateError(f"la corrida {ctx.run_key} no tiene el resultado de la tarea {task_id}: corra esa tarea antes "
                            f"(python -m churnrisk task {task_id} --run-key {ctx.run_key})")
    return result


def _save_task(ctx: RunContext, task_id: str, result: dict, status: str | None = None) -> None:
    state = _read_state(ctx.state_path)
    state.setdefault("tasks", {})[task_id] = result
    if status:
        state["status"] = status
    _write_state(ctx.state_path, state)


def _mark_rejected(ctx: RunContext, task_id: str, report: ValidationReport) -> None:
    state = _read_state(ctx.state_path)
    state["status"] = "rejected"
    state.setdefault("tasks", {})[task_id] = {"status": "rejected", "rules": [r.rule_id for r in report.results if not r.passed and r.severity is Severity.BLOCKING]}
    _write_state(ctx.state_path, state)


def _now_text() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _peak() -> MemoryPeaks | None:
    """The process's memory peaks, or None: telemetry never discards the result of a task that finished."""
    try:
        return peak_memory()
    except Exception:
        logger.warning("could not measure the peak memory", exc_info=True)
        return None


# --- the warehouse, as the tasks need it ----------------------------------------------------------------------------------------


def _read_only(cfg: PipelineConfig) -> sqlite3.Connection:
    """The warehouse for reading; before the first load there is none, and asking must not create it (AC08)."""
    path = Path(cfg.paths.warehouse)
    return sqlite3.connect(":memory:") if not path.exists() else sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)).fetchone() is not None


def _has_record(ctx: RunContext) -> bool:
    conn = _read_only(ctx.cfg)
    try:
        return _has_table(conn, "pipeline_runs") and conn.execute("SELECT 1 FROM pipeline_runs WHERE run_key = ?", (ctx.run_key,)).fetchone() is not None
    finally:
        conn.close()


def record_run(conn: sqlite3.Connection, fields: dict) -> None:
    """Create or update the run's row of ``pipeline_runs`` with `fields` (only the columns given change)."""
    unknown = set(fields) - set(RUN_COLUMNS)
    if unknown:
        raise ValueError(f"columnas desconocidas de pipeline_runs: {sorted(unknown)}")
    columns = [c for c in fields if c != "run_key"]
    updated = conn.execute(f"UPDATE pipeline_runs SET {', '.join(f'{c} = ?' for c in columns)} WHERE run_key = ?",
                           [*(fields[c] for c in columns), fields["run_key"]]).rowcount if columns else 0
    if not updated:
        names = list(fields)
        conn.execute(f"INSERT INTO pipeline_runs ({', '.join(names)}) VALUES ({', '.join('?' for _ in names)})", [fields[c] for c in names])


def _record(ctx: RunContext, **fields) -> None:
    conn = connect(ctx.cfg.paths.warehouse)
    try:
        apply_schema(conn)
        record_run(conn, {"run_key": ctx.run_key, **fields})
    finally:
        conn.close()


def _store_validation(conn: sqlite3.Connection, report: ValidationReport) -> None:
    """The run's rule results in ``validation_results`` (examples hold line ids and columns that identify nobody, D26)."""
    conn.execute("DELETE FROM validation_results WHERE run_key = ?", (report.run_key,))
    conn.executemany(
        "INSERT INTO validation_results (run_key, rule_id, name_es, severity, scope, aggregation, passed, rows_affected, customers_affected, value_gbp, "
        "examples_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [(report.run_key, r.rule_id, r.name_es, r.severity.value, r.scope, r.aggregation.value, int(r.passed), int(r.rows_affected), int(r.customers_affected),
          float(r.value_gbp), json.dumps(r.examples, ensure_ascii=False, default=str)) for r in report.results])


def _loaded_by(conn: sqlite3.Connection, delivery_id: str) -> str | None:
    if not _has_table(conn, "deliveries"):
        return None
    row = conn.execute("SELECT run_key FROM deliveries WHERE delivery_id = ? AND status = 'loaded'", (delivery_id,)).fetchone()
    return None if row is None else row[0]


def _latest_loaded_as_of(conn: sqlite3.Connection) -> str | None:
    if not _has_table(conn, "deliveries"):
        return None
    return conn.execute("SELECT MAX(as_of_date) FROM deliveries WHERE status = 'loaded'").fetchone()[0]


def _deliveries_dir(cfg: PipelineConfig) -> Path:
    return Path(cfg.paths.raw_dir) / "deliveries"


def _manifest_path(cfg: PipelineConfig) -> Path:
    return _deliveries_dir(cfg) / MANIFEST_NAME


def _validation_dir(cfg: PipelineConfig) -> Path:
    return Path(cfg.paths.reports_dir) / "validation"


def _validation_report_path(cfg: PipelineConfig, run_key: str) -> Path:
    return _validation_dir(cfg) / "history" / f"{run_key}.json"


def _spec_of(cfg: PipelineConfig, delivery_id: str) -> DeliverySpec:
    [spec] = [s for s in delivery_plan(cfg) if s.delivery_id == delivery_id]
    return spec


def _entry_of(cfg: PipelineConfig, delivery_id: str):
    [entry] = [e for e in read_manifest(_manifest_path(cfg)) if e.delivery_id == delivery_id]
    return entry


def _meta(ctx: RunContext) -> ExportMeta:
    return ExportMeta(ctx.run_key, date.fromisoformat(_task_result(ctx, "deliver")["as_of"]), _task_result(ctx, "fetch_source")["sha256"])


def _add_rules(ctx: RunContext, results: list) -> None:
    """Add rule results of the model steps to this run's report (its files and ``validation_results``)."""
    report = add_results(read_report(_validation_report_path(ctx.cfg, ctx.run_key)), [r for r in results if r is not None])
    write_report(report, _validation_dir(ctx.cfg))
    conn = connect(ctx.cfg.paths.warehouse)
    try:
        _store_validation(conn, report)
    finally:
        conn.close()


# --- tasks --------------------------------------------------------------------------------------------------------------------------


def fetch_source(ctx: RunContext) -> dict:
    """The pinned zip and its canonical lines (RF01-RF05); a source rule that fails rejects the run and writes nothing to SQLite."""
    try:
        return ingest.fetch_source(ctx)
    except SourceError as error:
        report = validate_source(error, run_key=ctx.run_key)
        write_report(report, _validation_dir(ctx.cfg))
        _mark_rejected(ctx, "fetch_source", report)
        raise ValidationError(report) from error


def deliver(ctx: RunContext) -> dict:
    """Publish the next pending delivery; with none left the run ends as ``no_delivery`` (RF06)."""
    cfg = ctx.cfg
    fetched = _task_result(ctx, "fetch_source")
    frame, _report = ingest.read_canonical(cfg.paths.interim_dir)
    plan = delivery_plan(cfg)
    assert_covered(frame, plan)
    spec = next_pending(_manifest_path(cfg), plan)
    if spec is None:
        message = f"no hay entregas pendientes: las {len(plan)} del plan ya están cargadas"
        _record(ctx, started_at=ctx.started_at.isoformat(timespec="seconds"), finished_at=_now_text(), status="no_delivery", source_sha256=fetched["sha256"],
                message=message)
        conn = _read_only(cfg)
        try:
            as_of = _latest_loaded_as_of(conn)      # the data the exports describe: the last loaded delivery's
        finally:
            conn.close()
        result = {"delivered": False, "run_status": "no_delivery", "message": message, "as_of": as_of}
        _save_task(ctx, "deliver", result, status="no_delivery")     # the refresh below reads this task's own result (``_meta``)
        _refresh_exports(ctx, summary=False, html=True, when="after a run with no delivery")
        return result
    conn = _read_only(cfg)
    try:
        owner = _loaded_by(conn, spec.delivery_id)
    finally:
        conn.close()
    if owner is not None and owner != ctx.run_key:
        raise RunStateError(f"la entrega {spec.delivery_id} ya está cargada por la corrida {owner} y el manifiesto no la marca cargada: retome esa corrida "
                            f"(python -m churnrisk run --run-key {owner} --from <tarea>; docs/runbook.md, R4)")
    entry = publish(spec, frame, _deliveries_dir(cfg))
    return {"delivered": True, "delivery_id": spec.delivery_id, "kind": spec.kind, "as_of": spec.as_of.isoformat(),
            "cut": None if spec.cut is None else spec.cut.isoformat(), "rows": entry.rows, "sha256": entry.sha256}


def validate(ctx: RunContext) -> dict:
    """Validate the delivery; a blocking rule rejects the run, writing nothing to SQLite (RF07, AC08)."""
    cfg = ctx.cfg
    delivered, fetched = _task_result(ctx, "deliver"), _task_result(ctx, "fetch_source")
    spec, entry = _spec_of(cfg, delivered["delivery_id"]), _entry_of(cfg, delivered["delivery_id"])
    path = _deliveries_dir(cfg) / entry.file
    conn = _read_only(cfg)
    try:
        by_delivery = validate_delivery(read_delivery(path), spec, conn, cfg, entry=entry, delivery_path=path, run_key=ctx.run_key)
    finally:
        conn.close()
    state = ingest.canonical_state(cfg.paths.interim_dir)
    if state is None:
        raise RunStateError(f"faltan las líneas canónicas en {cfg.paths.interim_dir}: corra fetch_source (python -m churnrisk task fetch_source --run-key {ctx.run_key})")
    report = combine_reports(validate_source(state[1], run_key=ctx.run_key, source_sha256=fetched["sha256"]), by_delivery)
    write_report(report, _validation_dir(cfg))
    if report.blocking_failed:
        mark_delivery(_manifest_path(cfg), spec.delivery_id, "rejected", ctx.run_key)
        _mark_rejected(ctx, "validate", report)
        raise ValidationError(report)
    return {"delivery_id": spec.delivery_id, "rows": entry.rows,
            "warnings": [r.rule_id for r in report.results if not r.passed and r.severity is Severity.WARNING]}


def load(ctx: RunContext) -> dict:
    """Load the delivery in one transaction with its controls and open the run's row as ``running`` (RF08); a load that committed and is
    repeated by the same run records the run only."""
    cfg = ctx.cfg
    delivered, fetched = _task_result(ctx, "deliver"), _task_result(ctx, "fetch_source")
    spec, entry = _spec_of(cfg, delivered["delivery_id"]), _entry_of(cfg, delivered["delivery_id"])
    lines = read_delivery(_deliveries_dir(cfg) / entry.file)
    conn = connect(cfg.paths.warehouse)
    try:
        resumed = _loaded_by(conn, spec.delivery_id) == ctx.run_key
        controls = None if resumed else len(load_delivery(conn, lines, spec, ctx.run_key, sha256=entry.sha256).checks)
        record_run(conn, {"run_key": ctx.run_key, "started_at": ctx.started_at.isoformat(timespec="seconds"), "finished_at": None, "status": "running",
                          "delivery_id": spec.delivery_id, "as_of_date": spec.as_of.isoformat(), "cut_date": None if spec.cut is None else spec.cut.isoformat(),
                          "source_sha256": fetched["sha256"], "lines_delivery": len(lines), "message": ""})
        _store_validation(conn, read_report(_validation_report_path(cfg, ctx.run_key)))
    finally:
        conn.close()
    return {"lines": len(lines), "as_of": spec.as_of.isoformat(), "controls": controls, "resumed": resumed}


def build_cuts(ctx: RunContext) -> dict:
    """The cuts, their populations, features and the labels whose window closed, with what is known at each date (RF09-RF12)."""
    cfg = ctx.cfg
    delivered, fetched = _task_result(ctx, "deliver"), _task_result(ctx, "fetch_source")
    conn = connect(cfg.paths.warehouse)
    try:
        result = build_cut_tables(conn, date.fromisoformat(delivered["as_of"]), sealed_view(cfg, fetched["sha256"]), ctx.run_key)
    finally:
        conn.close()
    return {"as_of": delivered["as_of"], "rows": result.rows if hasattr(result, "rows") else None}


def fit_model(ctx: RunContext) -> dict:
    """Train and freeze the model at the launch, or check the frozen one (M03, M05); the body is ``launch.fit_model`` (D77)."""
    cfg = ctx.cfg
    delivered, fetched = _task_result(ctx, "deliver"), _task_result(ctx, "fetch_source")
    conn = connect(cfg.paths.warehouse)
    try:
        result = fit_frozen_model(conn, cfg, run_key=ctx.run_key, as_of=date.fromisoformat(delivered["as_of"]), source_sha256=fetched["sha256"])
    finally:
        conn.close()
    m05 = None if result["m05_passed"] is None else model_result("M05", passed=bool(result["m05_passed"]))
    rules = [model_result("M03", passed=True), m05, model_result("M07", passed=True), model_result("M08", passed=True)]
    if result["mode"] == "launch":
        rules.insert(0, model_result("M01", passed=True))
    _add_rules(ctx, rules)
    return result


def score(ctx: RunContext) -> dict:
    """Score once each active customer of the run's cut with the frozen model (RF20, M02, M04, M06); the close scores nothing."""
    cfg = ctx.cfg
    delivered, fetched = _task_result(ctx, "deliver"), _task_result(ctx, "fetch_source")
    if delivered.get("cut") is None:
        return {"cut": None, "scored": 0, "skipped": "the close scores no cut"}
    conn = connect(cfg.paths.warehouse)
    try:
        registered = load_registered(conn, cfg)
        as_of = date.fromisoformat(delivered["as_of"])
        scored = score_cut(conn, date.fromisoformat(delivered["cut"]), registered.bundle, RunMeta(ctx.run_key, as_of, registered.model_version, registered.threshold),
                           sealed_view(cfg, fetched["sha256"]))
        totals = conn.execute("SELECT COUNT(*), COALESCE(SUM(is_contact), 0) FROM model_scores WHERE cut_date = ?", (delivered["cut"],)).fetchone()
        record_run(conn, {"run_key": ctx.run_key, "customers_scored": int(totals[0]), "contacts": int(totals[1])})
    finally:
        conn.close()
    _add_rules(ctx, [model_result("M02", passed=True), model_result("M04", passed=True), model_result("M06", passed=True),
                     model_result("I04", passed=True, rows=int(totals[0]), customers=int(totals[0])), model_result("I05", passed=True, rows=int(totals[1]), customers=int(totals[1]))])
    return {"cut": delivered["cut"], "scored": scored.scored, "already_scored": scored.already_scored, "contacts": scored.contacts, "threshold": scored.threshold}


def track(ctx: RunContext) -> dict:
    """The follow-up of every scored cut with what is known on the calculation date (RF22)."""
    cfg = ctx.cfg
    delivered, fetched = _task_result(ctx, "deliver"), _task_result(ctx, "fetch_source")
    conn = connect(cfg.paths.warehouse)
    try:
        frame = track_cuts(conn, date.fromisoformat(delivered["as_of"]), sealed_view(cfg, fetched["sha256"]), ctx.run_key)
    finally:
        conn.close()
    return {"cuts": int(len(frame))}


def evaluate(ctx: RunContext) -> dict:
    """V2 the first time, the test once when its windows close, and its seal (RF23, RF24)."""
    cfg = ctx.cfg
    delivered, fetched = _task_result(ctx, "deliver"), _task_result(ctx, "fetch_source")
    conn = connect(cfg.paths.warehouse)
    try:
        outcome = evaluate_model(conn, cfg, run_key=ctx.run_key, as_of=date.fromisoformat(delivered["as_of"]), source_sha256=fetched["sha256"])
    finally:
        conn.close()
    return {k: v for k, v in outcome.items() if isinstance(v, (str, int, float, bool)) or v is None}


def export(ctx: RunContext) -> dict:
    """The star model for Power BI and the five site files, each set read back against its manifest (RF25, RF27). The run stays ``running``."""
    cfg, meta = ctx.cfg, _meta(ctx)
    conn = connect(cfg.paths.warehouse)
    try:
        paths = export_star_schema(conn, cfg.paths.outputs_dir, cfg.paths.private_dir, MODEL, meta, cfg)
        site = export_site(conn, cfg.paths.site_dir, meta, cfg)
    finally:
        conn.close()
    problems = verify_star_schema(cfg.paths.outputs_dir) + verify_site(cfg.paths.site_dir)
    if problems:
        raise ExportError(f"lo exportado no es una misma exportación: {problems[0]} ({len(problems)} problemas)")
    return {"files": len(paths), "site_files": len(site)}


def render_dashboard(ctx: RunContext) -> dict:
    cfg = ctx.cfg
    path = render_design(MODEL, cfg.paths.outputs_dir, cfg.paths.private_dir, cfg.paths.dashboard_html, _meta(ctx), min_cell_customers=cfg.site.min_cell_customers)
    return {"html": path.name, "bytes": path.stat().st_size}


# --- the close of a run -------------------------------------------------------------------------------------------------------------


def _run_peaks(ctx: RunContext) -> tuple[float | None, float | None, str | None]:
    tasks = _read_state(ctx.state_path).get("tasks", {}).values()
    now = _peak()
    working = [t.get("peak_working_set_mb") for t in tasks] + [now.working_set_mb if now else None]
    commit = [t.get("peak_commit_mb") for t in tasks] + [now.commit_mb if now else None]
    working, commit = [p for p in working if p is not None], [p for p in commit if p is not None]
    return (max(working) if working else None, max(commit) if commit else None, now.counter if now else None)


def _close_sqlite(ctx: RunContext) -> None:
    """Close the run's row as ``ok``; the row is ``load``'s, so a run without one is an error and never gets a row here."""
    working, commit, counter = _run_peaks(ctx)
    conn = connect(ctx.cfg.paths.warehouse)
    try:
        apply_schema(conn)
        if conn.execute("SELECT 1 FROM pipeline_runs WHERE run_key = ?", (ctx.run_key,)).fetchone() is None:
            raise RunStateError(f"la corrida {ctx.run_key} no tiene su fila en pipeline_runs: no cargó su entrega, así que no se cierra "
                                f"(python -m churnrisk run --run-key {ctx.run_key} --from validate)")
        record_run(conn, {"run_key": ctx.run_key, "status": "ok", "finished_at": _now_text(), "message": "ok",
                          "peak_working_set_mb": None if working is None else round(working, 1), "peak_commit_mb": None if commit is None else round(commit, 1),
                          "memory_counter": counter})
    finally:
        conn.close()


def _close_run_table(ctx: RunContext) -> None:
    conn = connect(ctx.cfg.paths.warehouse)
    try:
        export_run_table(conn, ctx.cfg.paths.outputs_dir, MODEL, _meta(ctx))
    finally:
        conn.close()


def _close_summary(ctx: RunContext) -> None:
    conn = connect(ctx.cfg.paths.warehouse)
    try:
        export_summary(conn, ctx.cfg.paths.site_dir, _meta(ctx), ctx.cfg)
    finally:
        conn.close()


def _close_html(ctx: RunContext) -> None:
    render_dashboard(ctx)


def _close_manifest(ctx: RunContext) -> None:
    mark_delivery(_manifest_path(ctx.cfg), _task_result(ctx, "deliver")["delivery_id"], "loaded", ctx.run_key)


_CLOSERS = {"sqlite": _close_sqlite, "run_table": _close_run_table, "summary": _close_summary, "html": _close_html, "manifest": _close_manifest}


def report(ctx: RunContext) -> dict:
    """Write the evaluation summary and close the run in ``CLOSING_STEPS`` order (plan, section 3; project 03, D72)."""
    cfg, meta = ctx.cfg, _meta(ctx)
    conn = connect(cfg.paths.warehouse)
    try:
        summary = build_summary(conn, cfg, run_key=ctx.run_key, as_of=meta.as_of, source_sha256=meta.source_sha256)
    finally:
        conn.close()
    json_path, _md = write_summary(summary, cfg.paths.reports_dir)
    for step in CLOSING_STEPS:
        _CLOSERS[step](ctx)
    return {"summary": json_path.name, "evaluation_status": summary["evaluation_status"], "run_status": "ok"}


def _refresh_exports(ctx: RunContext, *, summary: bool, html: bool, when: str) -> None:
    """Rewrite what was exported before so it says what SQLite says now: the run table, this run's summary and the HTML; nothing is created.
    Each write is tried on its own and logged if it fails (the caller's outcome stands)."""
    cfg = ctx.cfg
    try:
        meta = _meta(ctx)
    except (RunStateError, KeyError, TypeError, ValueError) as error:
        logger.warning("could not read the metadata of run %s %s, so no exported file was rewritten: %s", ctx.run_key, when, error)
        meta = None
    steps = []
    if meta is not None:
        steps.append(("run table", _close_run_table))
        if summary and (Path(cfg.paths.site_dir) / "summary.json").exists():
            steps.append(("summary", _close_summary))
        if html and Path(cfg.paths.dashboard_html).exists():
            steps.append(("html", _close_html))
    for name, step in steps:
        try:
            step(ctx)
        except Exception as error:
            logger.warning("could not rewrite the %s %s (run %s): %s", name, when, ctx.run_key, error, exc_info=error)


# --- running tasks -----------------------------------------------------------------------------------------------------------------


TASKS: tuple[TaskSpec, ...] = (
    TaskSpec("fetch_source", fetch_source, 3, 10, 20),
    TaskSpec("deliver", deliver, 0, 0, 5, short_circuit=True),
    TaskSpec("validate", validate, 0, 0, 10),
    TaskSpec("load", load, 1, 5, 30),
    TaskSpec("build_cuts", build_cuts, 1, 5, 20),
    TaskSpec("fit_model", fit_model, 1, 5, 30),
    TaskSpec("score", score, 1, 5, 10),
    TaskSpec("track", track, 1, 5, 10),
    TaskSpec("evaluate", evaluate, 1, 5, 30),
    TaskSpec("export", export, 1, 5, 10),
    TaskSpec("render_dashboard", render_dashboard, 1, 5, 10),
    TaskSpec("report", report, 1, 5, 5),
)
TASK_IDS = tuple(t.task_id for t in TASKS)


def _spec(task_id: str) -> TaskSpec:
    for spec in TASKS:
        if spec.task_id == task_id:
            return spec
    raise UsageError(f"tarea desconocida {task_id!r}; las tareas son {', '.join(TASK_IDS)}")


def _held_delivery(ctx: RunContext) -> dict:
    return _read_state(ctx.state_path).get("tasks", {}).get("deliver", {})


def _refuse_a_closed_run(spec: TaskSpec, ctx: RunContext) -> None:
    status = _read_state(ctx.state_path).get("status")
    if status in CLOSED_STATUSES:
        raise RunRefusedError(f"la corrida {ctx.run_key} está cerrada (estado {status}): no se vuelve a abrir para correr {spec.task_id}; "
                              "otra entrega es otra corrida (python -m churnrisk run)")


def _refuse_a_second_delivery(spec: TaskSpec, ctx: RunContext) -> None:
    held = _held_delivery(ctx)
    if spec.task_id != "deliver" or not held.get("delivered"):
        return
    pending = next_pending(_manifest_path(ctx.cfg), delivery_plan(ctx.cfg))
    if pending is None or pending.delivery_id != held["delivery_id"]:
        raise RunRefusedError(f"la corrida {ctx.run_key} ya tiene la entrega {held['delivery_id']} y la siguiente pendiente es "
                              f"{'ninguna' if pending is None else pending.delivery_id}: una corrida no cambia de entrega (python -m churnrisk run)")


def _refuse_a_delivery_this_run_did_not_load(spec: TaskSpec, ctx: RunContext) -> None:
    if TASK_IDS.index(spec.task_id) < TASK_IDS.index("load"):
        return
    held = _held_delivery(ctx)
    if not held.get("delivered"):
        return
    conn = _read_only(ctx.cfg)
    try:
        owner = _loaded_by(conn, held["delivery_id"])
    finally:
        conn.close()
    if owner == ctx.run_key or (owner is None and spec.task_id == "load"):
        return
    if owner is None:
        raise RunRefusedError(f"la corrida {ctx.run_key} tiene la entrega {held['delivery_id']} pero no la cargó: {spec.task_id} trabaja sobre la entrega que cargó "
                              f"su corrida (python -m churnrisk run --run-key {ctx.run_key} --from validate)")
    raise RunRefusedError(f"la entrega {held['delivery_id']} la cargó la corrida {owner}: {spec.task_id} no corre en la corrida {ctx.run_key} "
                          f"(python -m churnrisk run --run-key {owner} --from <tarea>)")


def _refuse_a_load_its_validation_did_not_pass(spec: TaskSpec, ctx: RunContext) -> None:
    if spec.task_id != "load" or not _held_delivery(ctx).get("delivered"):
        return
    path = _validation_report_path(ctx.cfg, ctx.run_key)
    if not path.is_file():
        raise RunRefusedError(f"la corrida {ctx.run_key} no validó su entrega: load carga solo una entrega que la validación de su corrida aprobó "
                              f"(python -m churnrisk run --run-key {ctx.run_key} --from validate)")
    report = read_report(path)
    if report.blocking_failed:
        failing = ", ".join(r.rule_id for r in report.results if not r.passed and r.severity is Severity.BLOCKING)
        raise RunRefusedError(f"la validación de la corrida {ctx.run_key} rechazó su entrega ({failing}): load no carga una entrega rechazada "
                              f"(docs/runbook.md, R3)")


def _refuse_an_older_date(spec: TaskSpec, ctx: RunContext) -> None:
    held = _held_delivery(ctx)
    if spec.task_id not in MODEL_TASK_IDS or not held.get("delivered"):
        return
    conn = _read_only(ctx.cfg)
    try:
        latest = _latest_loaded_as_of(conn)
    finally:
        conn.close()
    if latest is not None and latest != held["as_of"]:
        raise RunRefusedError(f"la corrida {ctx.run_key} es de la entrega {held['delivery_id']} (cálculo al {held['as_of']}) y la última cargada es la del "
                              f"{latest}: {spec.task_id} calcula la última fecha y no corre en esta corrida")


def _reopen(ctx: RunContext) -> None:
    state = _read_state(ctx.state_path)
    if state.get("status") != "failed":
        return
    state["status"] = "running"
    _write_state(ctx.state_path, state)
    if _has_record(ctx):
        _record(ctx, status="running", finished_at=None, message="")


def _record_failure(ctx: RunContext, spec: TaskSpec, error: BaseException) -> None:
    """The state file, the run's row and the exported files say the task failed; each write on its own, logged if it fails, so the task's
    error is what the caller sees (project 03, D79)."""
    message = f"{spec.task_id}: {type(error).__name__}: {error}"[:500]
    try:
        state = _read_state(ctx.state_path)
        state["status"] = "failed"
        state.setdefault("tasks", {})[spec.task_id] = {"status": "failed", "error": message, "traceback": "".join(traceback.format_exception(error))}
        _write_state(ctx.state_path, state)
    except Exception as failure:
        logger.warning("could not record the failure of %s in %s", spec.task_id, ctx.state_path, exc_info=failure)
    try:
        if _has_record(ctx):
            _record(ctx, status="failed", finished_at=_now_text(), message=message)
    except Exception as failure:
        logger.warning("could not record the failure of %s in the warehouse of run %s", spec.task_id, ctx.run_key, exc_info=failure)
    try:
        if _has_record(ctx):
            _refresh_exports(ctx, summary=True, html=True, when=f"after {spec.task_id} failed")
    except Exception as failure:
        logger.warning("could not rewrite the exported files of run %s after %s failed", ctx.run_key, spec.task_id, exc_info=failure)


def _run_spec(spec: TaskSpec, ctx: RunContext) -> dict:
    """The refusals (nothing written), the task, and its result saved with its seconds and its memory peaks; a failure is recorded and raised."""
    _refuse_a_closed_run(spec, ctx)
    _refuse_a_second_delivery(spec, ctx)
    _refuse_a_delivery_this_run_did_not_load(spec, ctx)
    _refuse_a_load_its_validation_did_not_pass(spec, ctx)
    _refuse_an_older_date(spec, ctx)
    started = time.perf_counter()
    _reopen(ctx)
    try:
        result = spec.func(ctx)
    except ValidationError:
        raise
    except BaseException as error:
        _record_failure(ctx, spec, error)
        logger.error("task %s of run %s failed after %.1f s: %s", spec.task_id, ctx.run_key, time.perf_counter() - started, error)
        raise
    peaks = _peak()
    result = {**result, "seconds": round(time.perf_counter() - started, 2), "peak_working_set_mb": None if peaks is None else round(peaks.working_set_mb, 1),
              "peak_commit_mb": None if peaks is None or peaks.commit_mb is None else round(peaks.commit_mb, 1), "memory_counter": None if peaks is None else peaks.counter}
    try:
        _save_task(ctx, spec.task_id, result, status=result.get("run_status"))
    except BaseException as error:
        if result.get("run_status") in CLOSED_STATUSES:
            logger.error("task %s closed run %s as %s but its result could not be saved: run it again", spec.task_id, ctx.run_key, result["run_status"], exc_info=error)
            raise
        _record_failure(ctx, spec, error)
        raise
    logger.info("task %s of run %s: %.1f s", spec.task_id, ctx.run_key, result["seconds"])
    return result


def run_task(task_id: str, run_id: str | None = None, cfg: PipelineConfig | None = None, *, now: datetime | None = None) -> dict:
    """Run one task of the run `run_id` (a new run if None) holding the writer lock: what the Airflow DAG calls."""
    spec = _spec(task_id)
    cfg = cfg or load_config()
    when = (now or datetime.now(UTC)).astimezone(UTC)
    with sole_writer(cfg.paths.interim_dir, f"task {task_id}", make_run_key(run_id if run_id is not None else when)):
        return _run_spec(spec, _context(cfg, run_id, when))


def _select(only: list[str] | None, start: str | None) -> list[str]:
    if only is not None and not only:
        raise UsageError("`only` está vacío: indique al menos una tarea")
    if only and start is not None:
        raise UsageError("`only` y `start` no se combinan")
    ids = list(TASK_IDS)
    if start is not None:
        _spec(start)
        ids = ids[ids.index(start):]
    if only:
        for task_id in only:
            _spec(task_id)
        ids = [i for i in ids if i in only]
    return ids


def run_all(cfg: PipelineConfig, only: list[str] | None = None, start: str | None = None, run_key: str | None = None, *, now: datetime | None = None) -> list[dict]:
    """Run the tasks in order (all, the listed ones or from `start` on) holding the writer lock from before the first to after the last; a run
    with no delivery stops after ``deliver``."""
    ids = _select(only, start)
    when = (now or datetime.now(UTC)).astimezone(UTC)
    outcome = []
    with sole_writer(cfg.paths.interim_dir, "run", make_run_key(run_key if run_key is not None else when)):
        ctx = _context(cfg, run_key, when)
        for task_id in ids:
            spec = _spec(task_id)
            result = _run_spec(spec, ctx)
            outcome.append({"task": task_id, "result": result})
            if spec.short_circuit and not result.get("delivered", True):
                break
    return outcome


def replay(cfg: PipelineConfig, until: str | None = None) -> list[list[dict]]:
    """Run the pending deliveries one run after another up to `until`; with nothing pending nothing runs and the lock is not taken."""
    plan = delivery_plan(cfg)
    ids = [s.delivery_id for s in plan]
    if until is not None and until not in ids:
        raise UsageError(f"--until {until}: no es una entrega del plan ({', '.join(ids)})")
    last = len(plan) - 1 if until is None else ids.index(until)
    runs: list[list[dict]] = []
    pending = next_pending(_manifest_path(cfg), plan)
    if pending is None:
        return runs
    if plan.index(pending) > last:   # nothing up to `until` is pending: the option would be ignored in silence (AC33), so it is refused
        raise UsageError(f"--until {until}: es anterior a la siguiente entrega pendiente, {pending.delivery_id}; no hay nada que correr hasta ella. "
                         "No se escribió nada.")
    with sole_writer(cfg.paths.interim_dir, "replay", None):
        while (pending := next_pending(_manifest_path(cfg), plan)) is not None and plan.index(pending) <= last:
            runs.append(run_all(cfg))
            if next_pending(_manifest_path(cfg), plan) == pending:
                raise RunStateError(f"la corrida de {pending.delivery_id} terminó sin cargar la entrega: el replay se detiene")
    return runs
