"""The tasks of a run, its state, its ordered close and the refusals (U25, AC08, AC30, AC31; RF28; plan, section 22; D30, D77), on the small
fixture with the quick configuration: the launch ``L1`` runs whole and closes, and the next delivery is taken by runs whose tasks the tests
run one by one. A refusal writes nothing: the bytes of every file of the data folder are the same before and after."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import os
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from churnrisk import lock, pipeline
from churnrisk.lock import RunRefusedError, RunStateError
from churnrisk.pipeline import CLOSING_STEPS, TASK_IDS, run_all, run_task
from churnrisk.validate import read_report, write_report
from tests.fixtures.history import quick_config

LAUNCH, NEXT = "L1", "M1"


@dataclass(frozen=True)
class Folder:
    root: Path
    cfg: object


def config_for(root: Path, zip_path: Path):
    cfg = quick_config(root)
    return dataclasses.replace(cfg, source=dataclasses.replace(cfg.source, mode="local", url="", accepted_sha256="", member_sha256="", local_path=zip_path))


@pytest.fixture(scope="session")
def pipeline_states(tmp_path_factory, small_zip):
    """``{name: folder}`` built once per session: ``launch`` (the launch run ``L1``, run whole and closed), ``validated`` (then run ``M1``
    with the next delivery fetched, delivered and validated) and ``cut`` (``M1`` loaded and its cuts built). A test copies one (``copy_state``)."""
    states = {}
    base = tmp_path_factory.mktemp("pipeline")
    for name, tasks in (("launch", None), ("validated", ["fetch_source", "deliver", "validate"]), ("cut", ["load", "build_cuts"])):
        root = base / name
        if states:
            shutil.copytree(list(states.values())[-1], root)
        cfg = config_for(root, small_zip)
        if tasks is None:
            run_all(cfg, run_key=LAUNCH)
        else:
            run_all(cfg, only=tasks, run_key=NEXT)
        states[name] = root
    return states


@pytest.fixture
def copy_state(pipeline_states, small_zip, tmp_path):
    def copy(name: str) -> Folder:
        root = tmp_path / name
        shutil.copytree(pipeline_states[name], root)
        return Folder(root, config_for(root, small_zip))

    return copy


def fingerprint(root: Path) -> dict[str, str]:
    """The SHA-256 of every file of the data folder (the lock file is never there between two commands)."""
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*")) if p.is_file()}


def state_of(folder: Folder, run_key: str) -> dict:
    return json.loads((Path(folder.cfg.paths.interim_dir) / "runs" / f"{run_key}.json").read_text(encoding="utf-8"))


def run_row(folder: Folder, run_key: str):
    conn = sqlite3.connect(folder.cfg.paths.warehouse)
    try:
        return conn.execute("SELECT status, delivery_id, message FROM pipeline_runs WHERE run_key = ?", (run_key,)).fetchone()
    finally:
        conn.close()


# --- the RED of U25 --------------------------------------------------------------------------------------------------------------


def test_closed_run_refuses_every_task_and_keeps_its_records(copy_state):
    """AC31 (project 02, B1): every task of a run that ended ``ok`` is refused with exit 2 before anything is written, and its records stay
    byte for byte the same."""
    folder = copy_state("launch")
    assert state_of(folder, LAUNCH)["status"] == "ok" and run_row(folder, LAUNCH)[0] == "ok"
    before = fingerprint(folder.root)
    for task_id in TASK_IDS:
        with pytest.raises(RunRefusedError, match=f"la corrida {LAUNCH} está cerrada") as error:
            run_task(task_id, LAUNCH, folder.cfg)
        assert error.value.exit_code == 2
    with pytest.raises(RunRefusedError, match="está cerrada"):
        run_all(folder.cfg, start="deliver", run_key=LAUNCH)
    assert fingerprint(folder.root) == before


def test_a_task_of_a_run_that_did_not_load_its_own_delivery_is_refused_and_writes_nothing(copy_state):
    """Project 03, D86: the tasks after ``load`` of a run that validated its delivery but did not load it are refused; once another run loads
    that delivery, the first run's ``load`` is refused too, naming the run that loaded it."""
    folder = copy_state("validated")
    before = fingerprint(folder.root)
    for task_id in TASK_IDS[TASK_IDS.index("build_cuts"):]:
        with pytest.raises(RunRefusedError, match="no la cargó"):
            run_task(task_id, NEXT, folder.cfg)
    assert fingerprint(folder.root) == before
    run_all(folder.cfg, only=["fetch_source", "deliver", "validate", "load"], run_key="M2")     # the same pending delivery, loaded by another run
    after_other = fingerprint(folder.root)
    for task_id in ("load", "build_cuts", "report"):
        with pytest.raises(RunRefusedError, match="la cargó la corrida M2"):
            run_task(task_id, NEXT, folder.cfg)
    assert fingerprint(folder.root) == after_other and run_row(folder, NEXT) is None


def test_load_is_refused_without_a_passed_validation_of_this_run(copy_state):
    """Project 03, D93: ``load`` needs this run's validation report, with no blocking rule failing; otherwise it is refused and writes nothing."""
    folder = copy_state("validated")
    run_all(folder.cfg, only=["fetch_source", "deliver"], run_key="M3")
    before = fingerprint(folder.root)
    with pytest.raises(RunRefusedError, match="no validó su entrega"):
        run_task("load", "M3", folder.cfg)
    assert fingerprint(folder.root) == before
    history = Path(folder.cfg.paths.reports_dir) / "validation" / "history" / f"{NEXT}.json"
    report = read_report(history)
    failed = dataclasses.replace(report, results=[dataclasses.replace(r, passed=False) if r.rule_id == "V14" else r for r in report.results])
    write_report(failed, Path(folder.cfg.paths.reports_dir) / "validation")
    before = fingerprint(folder.root)
    with pytest.raises(RunRefusedError, match=r"rechazó su entrega \(V14\)"):
        run_task("load", NEXT, folder.cfg)
    assert fingerprint(folder.root) == before and run_row(folder, NEXT) is None


def test_failure_handler_write_errors_do_not_mask_the_task_error(copy_state, monkeypatch, caplog):
    """AC30 (project 02, A5; project 03, H7): when the task fails and every write of the failure handler fails too, the caller sees the task's
    error; each failed write is logged."""
    folder = copy_state("cut")
    monkeypatch.setattr(pipeline, "track_cuts", lambda *a, **k: (_ for _ in ()).throw(ValueError("the task's own error")))
    real_write = pipeline._write_state

    def write_state(path, state):
        if state.get("status") == "failed":
            raise OSError(28, "No space left on device")
        real_write(path, state)

    monkeypatch.setattr(pipeline, "_write_state", write_state)
    monkeypatch.setattr(pipeline, "_record", lambda ctx, **fields: (_ for _ in ()).throw(sqlite3.OperationalError("database is locked")))
    monkeypatch.setattr(pipeline, "_refresh_exports", lambda ctx, **kw: (_ for _ in ()).throw(OSError(13, "Permission denied")))
    run_all(folder.cfg, only=["fit_model", "score"], run_key=NEXT)
    with caplog.at_level(logging.WARNING, logger="churnrisk.pipeline"), pytest.raises(ValueError, match="the task's own error"):
        run_task("track", NEXT, folder.cfg)
    messages = [r.getMessage() for r in caplog.records if r.name == "churnrisk.pipeline" and r.levelno == logging.WARNING]
    assert sum("could not record the failure" in m or "could not rewrite" in m for m in messages) == 3, messages


def test_a_failure_after_load_marks_the_run_failed_and_rewrites_what_was_exported(copy_state, monkeypatch):
    """AC30: the state file, the run's row and the exported run table say ``failed``; resuming the run takes it back to ``running``."""
    folder = copy_state("cut")
    monkeypatch.setattr(pipeline, "track_cuts", lambda *a, **k: (_ for _ in ()).throw(ValueError("boom")))
    run_all(folder.cfg, only=["fit_model", "score"], run_key=NEXT)
    with pytest.raises(ValueError, match="boom"):
        run_task("track", NEXT, folder.cfg)
    state = state_of(folder, NEXT)
    assert state["status"] == "failed" and "ValueError: boom" in state["tasks"]["track"]["error"] and "Traceback" in state["tasks"]["track"]["traceback"]
    assert run_row(folder, NEXT)[0] == "failed"
    runs = pq.read_table(Path(folder.cfg.paths.outputs_dir) / "dim_pipeline_run.parquet").to_pandas().set_index("run_key")
    assert runs.loc[NEXT, "status"] == "failed" and runs.loc[LAUNCH, "status"] == "ok"
    monkeypatch.undo()
    run_task("track", NEXT, folder.cfg)
    assert state_of(folder, NEXT)["status"] == "running" and run_row(folder, NEXT)[0] == "running"


def test_closing_never_creates_a_run_row(copy_state):
    """Project 03, D86: the close of a run whose delivery was never loaded is an error and creates no row of ``pipeline_runs``."""
    folder = copy_state("validated")
    ctx = pipeline._context(folder.cfg, NEXT, pipeline.datetime.now(pipeline.UTC))
    with pytest.raises(RunStateError, match="no tiene su fila en pipeline_runs"):
        pipeline._close_sqlite(ctx)
    assert run_row(folder, NEXT) is None


# --- the launch, closed in order -------------------------------------------------------------------------------------------------


def test_the_launch_closes_in_order_and_every_task_records_its_seconds_and_memory_with_its_counter(copy_state, pipeline_states):
    folder = copy_state("launch")
    state = state_of(folder, LAUNCH)
    assert list(state["tasks"]) == list(TASK_IDS) and state["status"] == "ok"
    for task_id, result in state["tasks"].items():
        assert result["seconds"] >= 0 and result["peak_working_set_mb"] > 0 and result["memory_counter"] in ("PeakWorkingSetSize", "ru_maxrss"), task_id
    assert run_row(folder, LAUNCH)[:2] == ("ok", "L2011-07")
    manifest = json.loads((Path(folder.cfg.paths.raw_dir) / "deliveries" / "manifest.json").read_text(encoding="utf-8"))
    assert [(e["delivery_id"], e["status"], e["run_key"]) for e in manifest["entries"]] == [("L2011-07", "loaded", LAUNCH)]
    runs = pq.read_table(Path(folder.cfg.paths.outputs_dir) / "dim_pipeline_run.parquet").to_pandas()
    assert list(runs["status"]) == ["ok"], "the run table was rewritten by the close, after the export saw the run running"
    summary = json.loads((Path(folder.cfg.paths.site_dir) / "summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "ok" and summary["run_key"] == LAUNCH
    assert CLOSING_STEPS == ("sqlite", "run_table", "summary", "html", "manifest")


def test_the_close_writes_in_its_order_and_a_close_cut_short_leaves_the_delivery_unloaded(copy_state, monkeypatch):
    """Project 03, D72: SQLite, the run table, the summary, the HTML and last the delivery manifest; a failure between two steps leaves the
    delivery ``published`` (the run is resumed, never replaced)."""
    folder = copy_state("cut")
    for task_id in ("fit_model", "score", "track", "evaluate", "export", "render_dashboard"):
        run_task(task_id, NEXT, folder.cfg)
    order = []
    for step, closer in list(pipeline._CLOSERS.items()):
        monkeypatch.setitem(pipeline._CLOSERS, step, lambda ctx, step=step, closer=closer: (order.append(step), closer(ctx))[1])
    real_html = pipeline._CLOSERS["html"]
    monkeypatch.setitem(pipeline._CLOSERS, "html", lambda ctx: (order.append("html"), (_ for _ in ()).throw(OSError("disk full")))[1])
    with pytest.raises(OSError, match="disk full"):
        run_task("report", NEXT, folder.cfg)
    assert order == ["sqlite", "run_table", "summary", "html"]
    manifest = json.loads((Path(folder.cfg.paths.raw_dir) / "deliveries" / "manifest.json").read_text(encoding="utf-8"))
    assert {e["delivery_id"]: e["status"] for e in manifest["entries"]}["M2011-08"] == "published"
    monkeypatch.setitem(pipeline._CLOSERS, "html", real_html)
    run_task("report", NEXT, folder.cfg)
    manifest = json.loads((Path(folder.cfg.paths.raw_dir) / "deliveries" / "manifest.json").read_text(encoding="utf-8"))
    assert {e["delivery_id"]: e["status"] for e in manifest["entries"]}["M2011-08"] == "loaded" and state_of(folder, NEXT)["status"] == "ok"


def test_the_frozen_model_task_runs_holding_the_writer_lock(copy_state, monkeypatch):
    """R4-launch-race (U16): ``fit_model`` runs inside the single writer, so no second process can train or register a model meanwhile."""
    folder = copy_state("cut")
    seen = []
    real = pipeline.fit_frozen_model

    def watched(conn, cfg, **kwargs):
        seen.append(lock.read_holder(cfg.paths.interim_dir))
        return real(conn, cfg, **kwargs)

    monkeypatch.setattr(pipeline, "fit_frozen_model", watched)
    run_task("fit_model", NEXT, folder.cfg)
    assert len(seen) == 1 and seen[0]["pid"] == os.getpid() and (seen[0]["command"], seen[0]["run_key"]) == ("task fit_model", NEXT)
    assert lock.read_holder(folder.cfg.paths.interim_dir) is None


def test_a_model_task_of_an_older_delivery_is_refused(copy_state):
    folder = copy_state("cut")
    for task_id in ("fit_model", "score", "track", "evaluate"):
        with pytest.raises(RunRefusedError, match="está cerrada"):
            run_task(task_id, LAUNCH, folder.cfg)
    state = json.loads((Path(folder.cfg.paths.interim_dir) / "runs" / f"{LAUNCH}.json").read_text(encoding="utf-8"))
    state["status"] = "running"                       # a launch run left open: its model tasks would calculate M1's date
    (Path(folder.cfg.paths.interim_dir) / "runs" / f"{LAUNCH}.json").write_text(json.dumps(state), encoding="utf-8")
    before = fingerprint(folder.root)
    with pytest.raises(RunRefusedError, match="la última cargada es la del 2011-08-31"):
        run_task("score", LAUNCH, folder.cfg)
    assert fingerprint(folder.root) == before


def test_a_second_delivery_in_the_same_run_is_refused(copy_state):
    """A run keeps the delivery it took: once another run loaded and closed that delivery, ``deliver`` again in the first run would take the
    next one, and is refused."""
    folder = copy_state("validated")
    run_all(folder.cfg, run_key="M2")                 # the same pending delivery, taken, loaded and closed by another run
    before = fingerprint(folder.root)
    with pytest.raises(RunRefusedError, match="ya tiene la entrega M2011-08 y la siguiente pendiente es M2011-09"):
        run_task("deliver", NEXT, folder.cfg)
    assert fingerprint(folder.root) == before


def test_unknown_tasks_and_incompatible_selections_are_usage_errors_before_writing(copy_state):
    folder = copy_state("launch")
    before = fingerprint(folder.root)
    for call in (lambda: run_task("nope", "X1", folder.cfg), lambda: run_all(folder.cfg, only=["deliver"], start="load"), lambda: run_all(folder.cfg, only=[]),
                 lambda: pipeline.replay(folder.cfg, until="Z2099-01")):
        with pytest.raises(pipeline.UsageError):
            call()
    assert fingerprint(folder.root) == before


# --- the review corrections of U25 (R3-001, R4-001) ----------------------------------------------------------------------------------


def run_table_of(folder: Folder):
    return pq.read_table(Path(folder.cfg.paths.outputs_dir) / "dim_pipeline_run.parquet").to_pandas().set_index("run_key")


def test_a_run_with_no_delivery_rewrites_the_run_table_and_the_html(copy_state, monkeypatch):
    """R3-001 (D77): ``deliver`` with nothing pending ends the run ``no_delivery`` and the exported run table and the HTML say so."""
    folder = copy_state("launch")
    html_path = Path(folder.cfg.paths.dashboard_html)
    assert "N1" not in html_path.read_text(encoding="utf-8")
    monkeypatch.setattr(pipeline, "next_pending", lambda *a, **k: None)
    result = run_all(folder.cfg, only=["fetch_source", "deliver"], run_key="N1")[-1]["result"]
    assert result["run_status"] == "no_delivery" and state_of(folder, "N1")["status"] == "no_delivery" and run_row(folder, "N1")[0] == "no_delivery"
    assert run_table_of(folder).loc["N1", "status"] == "no_delivery" and run_table_of(folder).loc[LAUNCH, "status"] == "ok"
    html = html_path.read_text(encoding="utf-8")
    assert "N1" in html and "no_delivery" in html


@pytest.mark.parametrize("damage", ["mismatch", "missing"])
def test_a_run_table_rewrite_that_cannot_happen_is_logged_and_overwrites_nothing(copy_state, caplog, damage):
    """R4-001: a missing or mismatched manifest means no rewrite; the close says so (WARNING, the run and the reason) and keeps every file."""
    folder = copy_state("launch")
    manifest = Path(folder.cfg.paths.outputs_dir) / "manifest.json"
    if damage == "missing":
        manifest.unlink()
    else:
        document = json.loads(manifest.read_text(encoding="utf-8"))
        document["files"][0]["sha256"] = "0" * 64
        manifest.write_text(json.dumps(document), encoding="utf-8")
    before = fingerprint(folder.root)
    ctx = pipeline._context(folder.cfg, LAUNCH, pipeline.datetime.now(pipeline.UTC))
    conn = pipeline.connect(folder.cfg.paths.warehouse)
    try:
        assert pipeline.export_run_table(conn, folder.cfg.paths.outputs_dir, pipeline.MODEL, pipeline._meta(ctx)) is None
    finally:
        conn.close()
    with caplog.at_level(logging.WARNING):
        pipeline._close_run_table(ctx)
    messages = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any(LAUNCH in m and "not rewritten" in m and "manifest" in m for m in messages), messages
    assert fingerprint(folder.root) == before


def test_refreshing_the_exports_logs_when_the_run_metadata_cannot_be_read(copy_state, caplog):
    """R3-001: a refresh that cannot read the run's metadata says so instead of skipping every step without a trace."""
    folder = copy_state("launch")
    ctx = pipeline._context(folder.cfg, "Z9", pipeline.datetime.now(pipeline.UTC))
    before = fingerprint(folder.root)
    with caplog.at_level(logging.WARNING, logger="churnrisk.pipeline"):
        pipeline._refresh_exports(ctx, summary=True, html=True, when="after a test")
    assert any("Z9" in r.getMessage() and "metadata" in r.getMessage() for r in caplog.records if r.levelno == logging.WARNING), caplog.records
    assert {k: v for k, v in fingerprint(folder.root).items() if not k.startswith("interim/runs/")} == {k: v for k, v in before.items() if not k.startswith("interim/runs/")}
