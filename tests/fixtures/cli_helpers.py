"""Helpers of the command-line tests (U26): a command of the CLI run in this process, a quick project laid out from a state of the pipeline,
and a fingerprint of a folder.

A quick project is a folder with a copy of ``config/`` (a clean clone of what the commands read; the SQL comes with the package) and, under
``data/quick/``, a copy of a state of ``pipeline_states`` and the small zip as ``online_retail_fixture.zip``: the paths of
``config/pipeline.quick.toml`` are those of the state (``history.local_quick_config``), so with ``CHURNRISK_HOME`` on the project the command
line works on that state.
"""

from __future__ import annotations

import contextlib
import io
import os
import shutil
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[2]
QUICK_CONFIG = "config/pipeline.quick.toml"
FIXTURE_NAME = "online_retail_fixture.zip"
SKIPPED = {".venv", ".git", "__pycache__", ".pytest_cache"}


def cli(*args: str) -> SimpleNamespace:
    """``python -m churnrisk <args>`` in this process (``cli.main``): its exit code and what it wrote to stdout and stderr."""
    from churnrisk.cli import main

    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(list(args))
    return SimpleNamespace(code=code, out=out.getvalue(), err=err.getvalue())


def quick_project(dest: Path, zip_path: Path, state: Path | None = None) -> Path:
    """A quick project at `dest`: ``config/``, and ``data/quick/`` with a copy of `state` (if any) and the zip."""
    dest = Path(dest)
    shutil.copytree(PROJECT_ROOT / "config", dest / "config")
    quick = dest / "data" / "quick"
    if state is not None:
        shutil.copytree(state, quick)
    quick.mkdir(parents=True, exist_ok=True)
    shutil.copy2(zip_path, quick / FIXTURE_NAME)
    return dest


def fingerprint(root: Path, skipped: set[str] = SKIPPED) -> dict[str, tuple[int, int]]:
    """Size and modification time of every file under `root` (the environment and the caches left out)."""
    found = {}
    for folder, names, files in os.walk(root):
        names[:] = [n for n in names if n not in skipped]
        for name in files:
            path = Path(folder) / name
            stat = path.stat()
            found[path.relative_to(root).as_posix()] = (stat.st_size, stat.st_mtime_ns)
    return found


@contextlib.contextmanager
def at_home(home: Path, cwd: Path):
    """``CHURNRISK_HOME`` on `home`, no ``CHURNRISK_CONFIG`` and `cwd` as the working directory, all restored afterwards (for a session
    fixture, where ``monkeypatch`` is not available)."""
    saved = {k: os.environ.get(k) for k in ("CHURNRISK_HOME", "CHURNRISK_CONFIG")}
    before = Path.cwd()
    os.environ["CHURNRISK_HOME"] = str(home)
    os.environ.pop("CHURNRISK_CONFIG", None)
    os.chdir(cwd)
    try:
        yield
    finally:
        os.chdir(before)
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
