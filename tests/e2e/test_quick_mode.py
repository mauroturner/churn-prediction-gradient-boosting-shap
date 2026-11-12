"""The quick mode, isolated (U26, AC34; RNF04, RNF10; D32): from another working directory, with ``CHURNRISK_HOME`` on a clean clone of the
project's configuration, the documented commands write only under ``data/quick/``: not a byte and not a modification time anywhere else of
the clone, nothing in the working directory, and nothing in this repository's project.

Project 01 wrote its quick run over the versioned outputs and resolved a relative path against the directory of the command. The replay is
the session's ``quick_replay`` (the monthly run after the launch of ``pipeline_states``, laid out as ``data/quick``); a clean clone with no
state makes its fixture and runs the first tasks of a run here (D82).
"""

from __future__ import annotations

from pathlib import Path

from churnrisk.pipeline import TASK_IDS
from tests.fixtures.cli_helpers import PROJECT_ROOT, QUICK_CONFIG, cli, fingerprint

QUICK = "data/quick/"


def changed(before: dict, after: dict) -> set[str]:
    return {name for name in set(before) | set(after) if before.get(name) != after.get(name)}


def test_quick_replay_from_other_cwd_touches_only_data_quick(quick_replay):
    """AC34: the replay ends with 0, every file it created or changed is under ``data/quick/`` of the clone, the working directory stays empty
    and this repository's project is as it was."""
    result = quick_replay.result
    assert result.code == 0, result.err
    touched = changed(quick_replay.before, quick_replay.after)
    assert touched and all(name.startswith(QUICK) for name in touched), sorted(n for n in touched if not n.startswith(QUICK))
    assert list(Path(quick_replay.elsewhere).iterdir()) == [], "nothing in the directory the command was started from"
    assert changed(quick_replay.real_before, quick_replay.real_after) == set(), "the repository's project was not touched"
    home = Path(quick_replay.home) / "data" / "quick"
    for name in ("churnrisk.sqlite", "outputs/powerbi/manifest.json", "outputs/site/manifest.json", "dashboard/powerbi-design.html",
                 "reports/evaluation_summary.json", "reports/model_seal.json"):
        assert (home / name).is_file(), name
    assert {"churnrisk.sqlite", "dashboard/powerbi-design.html", "outputs/site/summary.json"} <= {n[len(QUICK):] for n in touched}, "the run wrote its outputs"


def test_the_quick_replay_ran_every_task_of_its_one_run(quick_replay):
    lines = [line.split()[0] for line in quick_replay.result.out.splitlines() if line.strip() and line.split()[0] in TASK_IDS]
    assert lines == list(TASK_IDS), quick_replay.result.out
    assert "entrega M2011-08" in quick_replay.result.out and quick_replay.result.out.rstrip().endswith("1 corrida")


def test_a_clean_clone_makes_its_fixture_and_its_first_tasks_write_only_under_data_quick(tmp_path, monkeypatch):
    """From a clone with only ``config/``: ``make-fixture`` with a relative path writes into the clone (not into the working directory), and
    the first tasks of a run of the quick configuration write only under ``data/quick/``."""
    home = tmp_path / "clone"
    (home / "config").mkdir(parents=True)
    for path in (PROJECT_ROOT / "config").iterdir():
        (home / "config" / path.name).write_bytes(path.read_bytes())
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.setenv("CHURNRISK_HOME", str(home))
    monkeypatch.delenv("CHURNRISK_CONFIG", raising=False)
    monkeypatch.chdir(elsewhere)
    before, real_before = fingerprint(home), fingerprint(PROJECT_ROOT)
    made = cli("make-fixture", "data/quick/online_retail_fixture.zip", "--customers", "40")
    assert made.code == 0, made.err
    ran = cli("run", "--config", QUICK_CONFIG, "--only", "fetch_source", "deliver", "validate", "--run-key", "C1")
    assert ran.code == 0, ran.err
    touched = changed(before, fingerprint(home))
    assert "data/quick/online_retail_fixture.zip" in touched and "data/quick/interim/runs/C1.json" in touched
    assert all(name.startswith(QUICK) for name in touched), sorted(touched)
    assert list(elsewhere.iterdir()) == [] and changed(real_before, fingerprint(PROJECT_ROOT)) == set()


def test_every_path_of_the_quick_configuration_is_under_data_quick(monkeypatch, tmp_path):
    from churnrisk.config import load_config

    monkeypatch.delenv("CHURNRISK_HOME", raising=False)
    cfg = load_config(Path(QUICK_CONFIG))
    quick = (PROJECT_ROOT / "data" / "quick").resolve()
    paths = [cfg.source.local_path, *vars(cfg.paths).values()]
    assert all(Path(p).resolve().is_relative_to(quick) for p in paths), [str(p) for p in paths]
    assert cfg.source.mode == "local" and not cfg.source.url
