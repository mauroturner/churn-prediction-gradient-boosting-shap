"""The command line (U26, AC33; RF28; plan, section 22): every documented option changes the result (one case per option), an incompatible
combination exits with 2 before anything is written, and the exit codes 0, 1, 2 and 3. The commands run in this process (``cli.main``) on
quick projects laid out from the session's pipeline states (``tests/fixtures/cli_helpers.py``), from another working directory; one smoke
test runs ``python -m churnrisk --help`` in another process from another directory (the ``-m`` entry, plan 24.1)."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from churnrisk import pipeline
from churnrisk.lock import sole_writer
from churnrisk.pipeline import TASK_IDS
from tests.fixtures.cli_helpers import PROJECT_ROOT, QUICK_CONFIG, cli, fingerprint, quick_project

Q = ("--config", QUICK_CONFIG)


@pytest.fixture
def project(pipeline_states, small_zip, tmp_path, monkeypatch):
    """``project(state)``: a quick project with a copy of that pipeline state (or none), ``CHURNRISK_HOME`` on it and another working
    directory."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.delenv("CHURNRISK_CONFIG", raising=False)
    monkeypatch.chdir(elsewhere)

    def make(state: str | None = None, name: str = "clone") -> Path:
        home = quick_project(tmp_path / name, small_zip, pipeline_states[state] if state else None)
        monkeypatch.setenv("CHURNRISK_HOME", str(home))
        return home

    return make


def quick(home: Path) -> Path:
    return home / "data" / "quick"


def tasks_of(home: Path, run_key: str) -> list[str]:
    return list(json.loads((quick(home) / "interim" / "runs" / f"{run_key}.json").read_text(encoding="utf-8"))["tasks"])


def runs_of(home: Path) -> set[str]:
    return {p.stem for p in (quick(home) / "interim" / "runs").glob("*.json")}


def manifest_of(home: Path) -> dict[str, str]:
    entries = json.loads((quick(home) / "raw" / "deliveries" / "manifest.json").read_text(encoding="utf-8"))["entries"]
    return {e["delivery_id"]: e["status"] for e in entries}


def ok(result) -> None:
    assert result.code == 0, (result.code, result.out, result.err)


# --- the RED of U26 -----------------------------------------------------------------------------------------------------------------


def only(project):
    home = project("launch")
    ok(cli("run", *Q, "--only", "fetch_source", "--run-key", "A1"))
    ok(cli("run", *Q, "--only", "fetch_source", "deliver", "--run-key", "A2"))
    assert tasks_of(home, "A1") == ["fetch_source"] and tasks_of(home, "A2") == ["fetch_source", "deliver"]
    assert manifest_of(home)["M2011-08"] == "published", "only the second selection delivered"


def start(project):
    home = project("cut")
    before = json.loads((quick(home) / "interim" / "runs" / "M1.json").read_text(encoding="utf-8"))["tasks"]
    result = cli("run", *Q, "--from", "fit_model", "--run-key", "M1")
    ok(result)
    after = json.loads((quick(home) / "interim" / "runs" / "M1.json").read_text(encoding="utf-8"))
    assert list(after["tasks"]) == list(TASK_IDS) and after["status"] == "ok"
    assert {t: after["tasks"][t] for t in before} == before, "the tasks before --from were not run again"
    assert [line.split()[0] for line in result.out.splitlines() if line.split() and line.split()[0] in TASK_IDS] == list(TASK_IDS[TASK_IDS.index("fit_model"):])


def run_key(project):
    home = project("launch")
    ok(cli("run", *Q, "--only", "fetch_source", "--run-key", "K7"))
    assert runs_of(home) == {"L1", "K7"}
    ok(cli("run", *Q, "--only", "fetch_source"))
    new = runs_of(home) - {"L1", "K7"}
    assert len(new) == 1 and next(iter(new)).endswith("Z"), "without --run-key a new run takes its key from the clock"


def config(project):
    home = project("launch")
    (home / "config" / "elsewhere.toml").write_text(
        'extends = "pipeline.quick.toml"\n\n[paths]\n' + "".join(f'{k} = "data/elsewhere/{v}"\n' for k, v in (
            ("raw_dir", "raw"), ("interim_dir", "interim"), ("warehouse", "churnrisk.sqlite"), ("models_dir", "models"), ("outputs_dir", "outputs/powerbi"),
            ("private_dir", "outputs/private"), ("site_dir", "outputs/site"), ("reports_dir", "reports"), ("seal", "reports/model_seal.json"),
            ("dashboard_html", "dashboard/powerbi-design.html"), ("readme", "README.md"), ("figures_dir", "figures"))), encoding="utf-8")
    ok(cli("run", "--config", "config/elsewhere.toml", "--only", "fetch_source", "--run-key", "C1"))
    assert (home / "data" / "elsewhere" / "interim" / "runs" / "C1.json").is_file() and "C1" not in runs_of(home)


def verbose(project):
    project("launch")
    quiet = cli("run", *Q, "--only", "fetch_source", "--run-key", "V1")
    loud = cli("run", *Q, "--only", "fetch_source", "--run-key", "V2", "-v")
    ok(quiet), ok(loud)
    assert " INFO " not in quiet.err and " INFO churnrisk." in loud.err, (quiet.err, loud.err)


def until(quick_replay):
    """``replay --until M2011-08`` (the session's ``quick_replay``) stopped there: M2011-09, pending, was not run."""
    ok(quick_replay.result)
    home = Path(quick_replay.home)
    assert manifest_of(home) == {"L2011-07": "loaded", "M2011-08": "loaded"}
    assert quick_replay.result.out.rstrip().endswith("1 corrida")


def task(project):
    home = project("launch")
    ok(cli("task", "fetch_source", *Q, "--run-key", "T1"))
    assert tasks_of(home, "T1") == ["fetch_source"]
    ok(cli("task", "deliver", *Q, "--run-key", "T1"))
    assert tasks_of(home, "T1") == ["fetch_source", "deliver"]


def task_run_key(project):
    home = project("launch")
    ok(cli("task", "fetch_source", *Q, "--run-key", "T2"))
    ok(cli("task", "fetch_source", *Q))
    assert "T2" in runs_of(home) and len(runs_of(home) - {"L1", "T2"}) == 1


def make_fixture_output(project):
    home = project()
    result = cli("make-fixture", "data/quick/made.zip", "--customers", "40")
    ok(result)
    assert (quick(home) / "made.zip").is_file() and not (Path.cwd() / "data").exists(), "resolved against the project, not the working directory"
    assert "40 clientes" in result.out


def make_fixture_customers(project):
    home = project()
    ok(cli("make-fixture", "data/quick/a.zip", "--customers", "40"))
    ok(cli("make-fixture", "data/quick/b.zip", "--customers", "41"))
    assert (quick(home) / "a.zip").read_bytes() != (quick(home) / "b.zip").read_bytes()


def make_fixture_seed(project):
    home = project()
    ok(cli("make-fixture", "data/quick/a.zip", "--customers", "40", "--seed", "0"))
    ok(cli("make-fixture", "data/quick/b.zip", "--customers", "40", "--seed", "1"))
    assert (quick(home) / "a.zip").read_bytes() != (quick(home) / "b.zip").read_bytes()


def make_fixture_signal(project):
    home = project()
    ok(cli("make-fixture", "data/quick/a.zip", "--customers", "40"))
    result = cli("make-fixture", "data/quick/b.zip", "--customers", "40", "--signal", "rfm_only")
    ok(result)
    assert (quick(home) / "a.zip").read_bytes() != (quick(home) / "b.zip").read_bytes() and "señal rfm_only" in result.out


def docs_sync(project):
    home = project("launch")
    readme = quick(home) / "README.md"
    readme.write_text("# Proyecto\n\n<!-- results:start -->\nviejo\n<!-- results:end -->\n\nFin.\n", encoding="utf-8")
    result = cli("docs-sync", *Q)
    ok(result)
    text = readme.read_text(encoding="utf-8")
    summary = (quick(home) / "reports" / "evaluation_summary.md").read_text(encoding="utf-8").strip()
    assert "viejo" not in text and summary in text and text.endswith("<!-- results:end -->\n\nFin.\n")
    again = cli("docs-sync", *Q)
    ok(again)
    assert "ya estaba al día" in again.out


OPTIONS = {
    "run --only": only, "run --from": start, "run --run-key": run_key, "--config": config, "-v": verbose, "replay --until": until,
    "task TAREA": task, "task --run-key": task_run_key, "make-fixture SALIDA": make_fixture_output, "make-fixture --customers": make_fixture_customers,
    "make-fixture --seed": make_fixture_seed, "make-fixture --signal": make_fixture_signal, "docs-sync": docs_sync,
}


@pytest.mark.parametrize("option", list(OPTIONS))
def test_every_documented_option_changes_the_result(option, request):
    """AC33 (project 01, B2; project 02, B1): no option is ignored in silence; each one, given, changes what the command does."""
    case = OPTIONS[option]
    fixture = "quick_replay" if case is until else "project"
    case(request.getfixturevalue(fixture))


# --- refusals before writing and the exit codes -----------------------------------------------------------------------------------------


@pytest.mark.parametrize(("args", "says"), [
    (("run", *Q, "--only", "load", "--from", "load"), "--only y --from no se combinan"),
    (("run", *Q, "--run-key", "X1"), "--run-key necesita --only o --from"),
    (("run", *Q, "--only", "load"), "una corrida nueva empieza por fetch_source"),
    (("run", *Q, "--from", "validate"), "una corrida nueva empieza por fetch_source"),
    (("run", *Q, "--only", "nope"), "invalid choice"),
    (("task", "nope", *Q), "invalid choice"),
    (("replay", *Q, "--until", "Z2099-01"), "no es una entrega del plan"),
    (("replay", *Q, "--until", "L2011-07"), "es anterior a la siguiente entrega pendiente, M2011-08"),
    (("docs-sync", *Q), "el modo rápido no tiene README"),
    (("run", "--config", "config/missing.toml", "--only", "fetch_source", "--run-key", "X2"), "missing.toml"),
])
def test_incompatible_options_exit_2_before_writing(project, args, says):
    home = project("launch")
    before = fingerprint(home)
    result = cli(*args)
    assert result.code == 2 and says in result.err, (result.code, result.err)
    assert fingerprint(home) == before and list(Path.cwd().iterdir()) == []


def test_a_task_that_fails_exits_1_and_says_why(project, monkeypatch):
    project("cut")
    monkeypatch.setattr(pipeline, "track_cuts", lambda *a, **k: (_ for _ in ()).throw(ValueError("the task's own error")))
    result = cli("run", *Q, "--only", "fit_model", "score", "track", "--run-key", "M1")
    assert result.code == 1 and "falló: ValueError: the task's own error" in result.err and "Traceback" not in result.err
    verbose = cli("task", "track", *Q, "--run-key", "M1", "-v")
    assert verbose.code == 1 and "Traceback" in verbose.err, "-v adds the traceback"


def test_a_rejected_source_exits_3_and_a_closed_run_or_a_held_lock_exits_2(project, tiny_zip):
    home = project("launch")
    (quick(home) / "online_retail_fixture.zip").write_bytes(tiny_zip.read_bytes())       # another zip than the registered one: V01
    before = (quick(home) / "churnrisk.sqlite").read_bytes()
    rejected = cli("run", *Q)
    assert rejected.code == 3 and "rechazada" in rejected.err and "V01" in rejected.err
    assert (quick(home) / "churnrisk.sqlite").read_bytes() == before, "nothing written to the warehouse"
    closed = cli("task", "report", *Q, "--run-key", "L1")
    assert closed.code == 2 and "está cerrada" in closed.err
    taken, done = threading.Event(), threading.Event()

    def holder():
        with sole_writer(quick(home) / "interim", "run", "other"):
            taken.set()
            done.wait(timeout=60)

    thread = threading.Thread(target=holder)
    thread.start()
    try:
        assert taken.wait(timeout=60)
        locked = cli("run", *Q, "--only", "fetch_source", "--run-key", "Z1")
    finally:
        done.set()
        thread.join(timeout=60)
    assert locked.code == 2 and "escribe esta carpeta de datos" in locked.err and "Z1" not in runs_of(home), locked.err


def test_a_replay_with_nothing_pending_exits_0_without_the_lock(project, monkeypatch):
    home = project("launch")
    monkeypatch.setattr(pipeline, "next_pending", lambda *a, **k: None)
    taken = []
    monkeypatch.setattr(pipeline, "sole_writer", lambda *a, **k: taken.append(a) or (_ for _ in ()).throw(AssertionError("the lock was taken")))
    before = fingerprint(home)
    result = cli("replay", *Q)
    assert result.code == 0 and "No hay entregas pendientes" in result.out and taken == [] and fingerprint(home) == before


def test_figures_draws_the_site_files_of_the_configuration_into_its_figures_folder(project):
    """``figures`` reads the site files of the configuration's run (verified against their manifest) and writes the seven figures to its
    ``figures_dir``; over a folder that is not one export it exits 2 and writes nothing (U28)."""
    from churnrisk.figures import FIGURE_NAMES

    home = project("launch")
    result = cli("figures", *Q)
    ok(result)
    assert sorted(p.name for p in (quick(home) / "figures").iterdir()) == sorted(FIGURE_NAMES) and result.out.count("escribí") == len(FIGURE_NAMES)
    shutil.rmtree(quick(home) / "figures")
    (quick(home) / "outputs" / "site" / "label.json").write_text("{}\n", encoding="utf-8")
    refused = cli("figures", *Q)
    assert refused.code == 2 and "label.json" in refused.err and not (quick(home) / "figures").exists()


def test_python_m_churnrisk_help_runs_from_another_directory(tmp_path):
    """The ``-m`` entry, in another process from another directory: the help lists every command."""
    env = {**os.environ, "PYTHONPATH": str(PROJECT_ROOT / "src"), "PYTHONIOENCODING": "utf-8"}
    env.pop("CHURNRISK_CONFIG", None)
    env.pop("CHURNRISK_HOME", None)
    done = subprocess.run([sys.executable, "-m", "churnrisk", "--help"], cwd=tmp_path, env=env, capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert done.returncode == 0, done.stderr
    for command in ("run", "replay", "task", "make-fixture", "docs-sync"):
        assert command in done.stdout, command
    assert list(tmp_path.iterdir()) == []


def test_the_logging_of_a_second_call_replaces_the_first(project):
    """Two calls in one process (as the tests make): ``-v`` takes effect each time and a handler is not added twice."""
    project("launch")
    cli("run", *Q, "--only", "fetch_source", "--run-key", "H1", "-v")
    cli("run", *Q, "--only", "fetch_source", "--run-key", "H2")
    handlers = [h for h in logging.getLogger("churnrisk").handlers if getattr(h, "_churnrisk_cli", False)]
    assert len(handlers) == 1 and logging.getLogger("churnrisk").level == logging.WARNING
