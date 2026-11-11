"""Shared fixtures, the automatic skipping of the real_data and docker marks and the fast suite's time limit (plan, section 24.1).

Every expensive state is built once per session and reused (D34): the synthetic fixture in its standard (1,500 customers), small
(300) and tiny (40) sizes, each malformed variant and each signal variant. A test that writes works on its own copy (``copy_of``).
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from tests.fixtures.suite_budget import pytest_addoption, pytest_sessionfinish, pytest_sessionstart  # noqa: F401  (the time limit, D34)

pytest_plugins = ["pytester"]

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REAL_ZIP = PROJECT_ROOT / "data" / "raw" / "online_retail_ii.zip"
STANDARD_CUSTOMERS = 1500
SMALL_CUSTOMERS = 300
TINY_CUSTOMERS = 40


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip, instead of failing, the tests whose external requirement is missing."""
    skips = {
        "real_data": (not REAL_ZIP.exists(), "the real zip is not in data/raw/"),
        "docker": (shutil.which("docker") is None, "docker is not installed"),
    }
    for item in items:
        for mark, (missing, reason) in skips.items():
            if mark in item.keywords and missing:
                item.add_marker(pytest.mark.skip(reason=reason))


@pytest.fixture(scope="session")
def project_root() -> Path:
    return PROJECT_ROOT


@pytest.fixture(scope="session")
def cfg():
    """The default configuration, loaded once (it is immutable)."""
    from churnrisk.config import load_config

    return load_config(PROJECT_ROOT / "config" / "pipeline.toml")


# --- the synthetic fixture, its sizes and its variants ---------------------------------------------------------------


@pytest.fixture(scope="session")
def fixture_truth(tmp_path_factory: pytest.TempPathFactory):
    """The standard synthetic zip (1,500 customers, seed 0, no planted signal) and what it holds."""
    from tests.fixtures.make_fixture import make_fixture

    return make_fixture(tmp_path_factory.mktemp("fixture") / "online_retail_fixture.zip", n_customers=STANDARD_CUSTOMERS, seed=0)


@pytest.fixture(scope="session")
def fixture_zip(fixture_truth) -> Path:
    return fixture_truth.path


@pytest.fixture(scope="session")
def small_truth(tmp_path_factory: pytest.TempPathFactory):
    """A synthetic zip of 300 customers (seed 0) for the tests whose subject is one row, one cell, the download or an error: a defect in
    one row is found by the same code whatever the size of the rest, and the standard file costs five times as much to write and read."""
    from tests.fixtures.make_fixture import make_fixture

    return make_fixture(tmp_path_factory.mktemp("small_fixture") / "small_fixture.zip", n_customers=SMALL_CUSTOMERS, seed=0)


@pytest.fixture(scope="session")
def small_zip(small_truth) -> Path:
    return small_truth.path


@pytest.fixture(scope="session")
def tiny_zip(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A synthetic zip of 40 customers with every dedicated case: the base of the malformed variants, which are opened and saved
    whole with openpyxl (about 1.5 s each from the small zip, a tenth of that from this one)."""
    from tests.fixtures.make_fixture import make_fixture

    return make_fixture(tmp_path_factory.mktemp("tiny_fixture") / "tiny_fixture.zip", n_customers=TINY_CUSTOMERS, seed=0).path


@pytest.fixture(scope="session")
def malformed(tmp_path_factory: pytest.TempPathFactory, tiny_zip: Path) -> Callable[[str], Path]:
    """``malformed(kind)``: the tiny zip damaged in one documented way, each kind built once per session."""
    from tests.fixtures.make_fixture import make_malformed

    folder = tmp_path_factory.mktemp("malformed")
    built: dict[str, Path] = {}

    def build(kind: str) -> Path:
        if kind not in built:
            built[kind] = make_malformed(tiny_zip, kind, folder / f"{kind}.zip")
        return built[kind]

    return build


@pytest.fixture(scope="session")
def rejection(tmp_path_factory: pytest.TempPathFactory, malformed: Callable[[str], Path], tiny_zip: Path, cfg) -> Callable[[str], object]:
    """``rejection(kind)``: the ``SourceError`` of the first task on a malformed variant in local mode, each read once per session, for the
    tests that only look at the error (plan 24.1; project 03, D76). The tests that check that a rejection writes nothing run their own."""
    import dataclasses
    import hashlib
    import types

    from churnrisk.ingest import MANIFEST_NAME, SourceManifest, fetch_source, write_source_manifest
    from churnrisk.schema import SourceError

    folder = tmp_path_factory.mktemp("rejections")
    seen: dict[str, object] = {}

    def read(kind: str):
        if kind not in seen:
            run = folder / kind
            paths = dataclasses.replace(cfg.paths, raw_dir=run / "raw", interim_dir=run / "interim")
            source = dataclasses.replace(cfg.source, mode="local", url="", accepted_sha256="", member_sha256="", local_path=malformed(kind))
            if kind == "wrong_hash":   # a local source whose first hash was registered: another one is V01
                registered = SourceManifest("local", str(tiny_zip), hashlib.sha256(tiny_zip.read_bytes()).hexdigest(), tiny_zip.stat().st_size,
                                            "2026-11-11T10:00:00+00:00", str(tiny_zip))
                write_source_manifest(run / "raw" / MANIFEST_NAME, registered)
            try:
                fetch_source(types.SimpleNamespace(cfg=dataclasses.replace(cfg, paths=paths, source=source)))
            except SourceError as error:
                seen[kind] = error
            else:  # pragma: no cover - every source variant is rejected
                raise AssertionError(f"the variant {kind} was not rejected")
        return seen[kind]

    return read


@pytest.fixture(scope="session")
def signal_truth(tmp_path_factory: pytest.TempPathFactory) -> Callable[[str], object]:
    """``signal_truth(signal)``: the standard zip with a planted signal (``irregular_gaps`` or ``rfm_only``), each built once per session."""
    from tests.fixtures.make_fixture import make_fixture

    folder = tmp_path_factory.mktemp("signals")
    built: dict[str, object] = {}

    def build(signal: str):
        if signal not in built:
            built[signal] = make_fixture(folder / f"{signal}.zip", n_customers=STANDARD_CUSTOMERS, seed=0, signal=signal)
        return built[signal]

    return build


@pytest.fixture
def copy_of(tmp_path: Path) -> Callable[[Path], Path]:
    """``copy_of(path)``: a copy of a file or a folder inside this test's ``tmp_path``, for a test that writes."""

    def copy(path: Path) -> Path:
        target = tmp_path / "copies" / Path(path).name
        target.parent.mkdir(parents=True, exist_ok=True)
        if Path(path).is_dir():
            shutil.copytree(path, target)
        else:
            shutil.copy2(path, target)
        return target

    return copy


@pytest.fixture(scope="session")
def canonical(tmp_path_factory: pytest.TempPathFactory, fixture_zip: Path, cfg):
    """``(frame, report)``: the standard fixture's workbook read once into its canonical lines (reading an .xlsx is the slowest step, D34)."""
    from churnrisk.ingest import extract_member, read_source

    xlsx = extract_member(fixture_zip, cfg.source.member, cfg.source.max_member_bytes, "", out_dir=tmp_path_factory.mktemp("canonical"))
    return read_source(xlsx, cfg)


@pytest.fixture(scope="session")
def real_canonical(cfg, tmp_path_factory: pytest.TempPathFactory):
    """``(fetch result, frame, report)``: the real canonical lines, built once per session from a copy of the pinned zip in a folder of the
    session's own (mark real_data only; the zip is never downloaded again). Reading the real workbook takes about 40 s, so every real_data
    test shares this one read."""
    import dataclasses
    import types

    from churnrisk.ingest import fetch_source, read_canonical

    folder = tmp_path_factory.mktemp("real")
    (folder / "raw").mkdir()
    shutil.copyfile(REAL_ZIP, folder / "raw" / REAL_ZIP.name)
    paths = dataclasses.replace(cfg.paths, raw_dir=folder / "raw", interim_dir=folder / "interim")
    result = fetch_source(types.SimpleNamespace(cfg=dataclasses.replace(cfg, paths=paths)))
    frame, report = read_canonical(folder / "interim")
    return result, frame, report

