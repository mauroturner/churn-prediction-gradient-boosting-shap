"""Shared fixtures, the automatic skipping of the real_data and docker marks and the fast suite's time limit (plan, section 24.1).

Every expensive state is built once per session and reused (D34): the synthetic fixture in its standard (1,500 customers), small
(300) and tiny (40) sizes, each malformed variant and each signal variant. A test that writes works on its own copy (``copy_of``).
"""

from __future__ import annotations

import os

# OpenMP threads of the fits in this test process (scikit-learn's gradient boosting), set before scikit-learn is imported: on this machine's
# 32 logical processors the default takes 8.0 s to train the 24 candidates of a launch and 8 threads 6.7 s, with the same risks to the last
# bit (D75). A value the person running the suite set is kept. The product never reads it.
os.environ.setdefault("OMP_NUM_THREADS", "8")

import shutil  # noqa: E402
import types  # noqa: E402
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


@pytest.fixture(scope="session")
def signal_launch(tmp_path_factory: pytest.TempPathFactory, signal_truth: Callable[[str], object], cfg) -> Callable[[str], Path]:
    """``signal_launch(signal)``: a warehouse with the launch delivery of the signal fixture loaded and its cuts built at the launch's
    calculation date, each built once per session. A test that writes works on ``copy_of(path)``."""
    from churnrisk.config import SealedConfig
    from churnrisk.cuts import build_cuts
    from churnrisk.deliveries import delivery_plan, delivery_rows, publish
    from churnrisk.ingest import extract_member, read_source
    from churnrisk.warehouse import connect, load_delivery

    folder = tmp_path_factory.mktemp("signal_launch")
    built: dict[str, Path] = {}

    def build(signal: str) -> Path:
        if signal not in built:
            zip_path = signal_truth(signal).path
            xlsx = extract_member(zip_path, cfg.source.member, cfg.source.max_member_bytes, "", out_dir=folder / f"{signal}_xlsx")
            frame, _report = read_source(xlsx, cfg)
            launch = delivery_plan(cfg)[0]
            entry = publish(launch, frame, folder / f"{signal}_deliveries")
            path = folder / f"{signal}.sqlite"
            conn = connect(path)
            try:
                load_delivery(conn, delivery_rows(launch, frame), launch, "r1", sha256=entry.sha256)
                build_cuts(conn, launch.as_of, SealedConfig.of(cfg, "a" * 64), "r1")
            finally:
                conn.close()
            built[signal] = path
        return built[signal]

    return build


@pytest.fixture(scope="session")
def launch_model(signal_launch: Callable[[str], Path], cfg) -> Callable[[str], tuple[object, object]]:
    """``launch_model(signal)``: ``(labelled rows, TrainedModel)`` of the launch on the signal fixture with the default configuration (the
    24 candidates), each trained once per session: the model's tests and the explanations share it."""
    from churnrisk.config import SealedConfig
    from churnrisk.model import train_model
    from churnrisk.split import labelled_rows
    from churnrisk.warehouse import connect

    trained: dict[str, tuple[object, object]] = {}

    def train(signal: str) -> tuple[object, object]:
        if signal not in trained:
            conn = connect(signal_launch(signal))
            try:
                labelled = labelled_rows(conn)
            finally:
                conn.close()
            trained[signal] = (labelled, train_model(labelled, SealedConfig.of(cfg, "a" * 64)))
        return trained[signal]

    return train


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
def loaded_masters(tmp_path_factory: pytest.TempPathFactory, canonical, cfg) -> Callable[[int], tuple[Path, object]]:
    """``loaded_masters(upto)``: ``(path, LoadResult of its last load)`` of a warehouse with the standard fixture's first `upto` deliveries,
    loaded by runs ``r1``, ``r2``... with the SHA-256 of their published file. Each is a copy of the largest one already built below it with
    the missing deliveries loaded (project 03, D76). A test that writes works on ``copy_of(path)``. ``loaded_masters.entries`` holds the
    manifest entry of each delivery."""
    from churnrisk.deliveries import delivery_plan, delivery_rows, publish
    from churnrisk.warehouse import connect, load_delivery

    frame, _report = canonical
    plan = delivery_plan(cfg)
    folder = tmp_path_factory.mktemp("masters")
    entries = {spec.delivery_id: publish(spec, frame, folder / "deliveries") for spec in plan}
    built: dict[int, tuple[Path, object]] = {}

    def build(upto: int) -> tuple[Path, object]:
        if not 1 <= upto <= len(plan):
            raise ValueError(f"upto: from 1 to {len(plan)}, got {upto}")
        if upto not in built:
            below = max((k for k in built if k < upto), default=0)
            path = folder / f"master_{upto}.sqlite"
            if below:
                shutil.copy2(built[below][0], path)
            conn = connect(path)
            try:
                for index in range(below, upto):
                    spec = plan[index]
                    result = load_delivery(conn, delivery_rows(spec, frame), spec, f"r{index + 1}", sha256=entries[spec.delivery_id].sha256)
            finally:
                conn.close()
            built[upto] = (path, result)
        return built[upto]

    build.entries = entries
    return build


LAUNCH_RUN_SHA = "d" * 64   # the source hash of the sealed view of the cuts built by launch_cuts


@pytest.fixture(scope="session")
def launch_build(tmp_path_factory: pytest.TempPathFactory, loaded_masters, cfg) -> tuple[Path, object]:
    """``(path, CutsResult)``: the warehouse of ``loaded_masters(1)`` (the launch L2011-07 loaded by run ``r1``) with its cuts built at the
    launch's calculation date by the same run, built once per session (D63)."""
    from churnrisk.config import SealedConfig
    from churnrisk.cuts import build_cuts
    from churnrisk.deliveries import delivery_plan
    from churnrisk.warehouse import connect

    path = tmp_path_factory.mktemp("launch_cuts") / "launch_cuts.sqlite"
    shutil.copy2(loaded_masters(1)[0], path)
    conn = connect(path)
    try:
        result = build_cuts(conn, delivery_plan(cfg)[0].as_of, SealedConfig.of(cfg, LAUNCH_RUN_SHA), "r1")
    finally:
        conn.close()
    return path, result


@pytest.fixture(scope="session")
def launch_cuts(launch_build) -> Path:
    """The launch warehouse with its cuts (``launch_build``): the tests of the cuts and every later state of the launch start from a copy."""
    return launch_build[0]


@pytest.fixture(scope="session")
def cut_history(tmp_path_factory: pytest.TempPathFactory, launch_build, canonical, loaded_masters, cfg) -> list:
    """The loads and the cuts of the whole plan, run by run (``r1`` to ``r6``) from ``launch_build``: each run's warehouse and the
    ``CutsResult`` of its build, built once per session (D67). The tests of the cuts read it, and ``quick_history`` runs its model steps on a
    copy of each run's warehouse."""
    from churnrisk.config import SealedConfig
    from tests.fixtures.history import build_cut_history

    frame, _report = canonical
    return build_cut_history(tmp_path_factory.mktemp("cut_history"), frame, loaded_masters.entries, *launch_build, cfg, SealedConfig.of(cfg, LAUNCH_RUN_SHA))


@pytest.fixture(scope="session")
def quick_history(tmp_path_factory: pytest.TempPathFactory, cut_history, fixture_truth):
    """The quick run of the whole plan on the standard fixture (``tests/fixtures/history.py``), on the loads and cuts of ``cut_history``: the
    launch trains and seals, every later run reuses the frozen model, scores its cut, tracks and evaluates. Built once per session; a test that
    writes works on copies of its warehouse, its artifact and its seal."""
    from tests.fixtures.history import build_history, quick_config

    folder = tmp_path_factory.mktemp("quick_history")
    return build_history(folder, quick_config(folder), fixture_truth.zip_sha256, cut_history)


@pytest.fixture(scope="session")
def pipeline_states(tmp_path_factory: pytest.TempPathFactory, small_zip: Path) -> dict[str, Path]:
    """``{name: folder}`` of the pipeline (U25) on the small zip with the quick configuration, built once per session: ``launch`` (the launch
    run ``L1``, run whole and closed), ``validated`` (then run ``M1`` with the next delivery fetched, delivered and validated) and ``cut``
    (``M1`` loaded and its cuts built). A test copies one. The tests of the pipeline and of the command line share them."""
    from churnrisk.pipeline import run_all
    from tests.fixtures.history import local_quick_config

    states: dict[str, Path] = {}
    base = tmp_path_factory.mktemp("pipeline")
    for name, tasks in (("launch", None), ("validated", ["fetch_source", "deliver", "validate"]), ("cut", ["load", "build_cuts"])):
        root = base / name
        if states:
            shutil.copytree(list(states.values())[-1], root)
        cfg = local_quick_config(root, small_zip)
        if tasks is None:
            run_all(cfg, run_key="L1")
        else:
            run_all(cfg, only=tasks, run_key="M1")
        states[name] = root
    return states


@pytest.fixture(scope="session")
def quick_replay(tmp_path_factory: pytest.TempPathFactory, pipeline_states: dict[str, Path], small_zip: Path):
    """The documented quick replay, once per session: ``python -m churnrisk replay --config config/pipeline.quick.toml --until M2011-08`` (in
    this process) from an empty folder that is not the project, with ``CHURNRISK_HOME`` on a quick project whose ``data/quick`` holds the
    ``validated`` state of ``pipeline_states`` (the launch closed, and run ``M1`` holding ``M2011-08``, fetched, delivered and validated): one
    monthly run, which takes, loads and closes ``M2011-08``. It records the fingerprints of the project, of the working directory and of this
    repository's project before and after (U26, AC34), and who held the writer lock while the run tracked its cuts (R4-002 of U25). The tests
    of the command line, of the quick mode and of the pipeline share this one run (D82)."""
    from churnrisk import lock, pipeline
    from tests.fixtures.cli_helpers import PROJECT_ROOT as REAL, QUICK_CONFIG, at_home, cli, fingerprint, quick_project

    home = quick_project(tmp_path_factory.mktemp("quick_project") / "clone", small_zip, pipeline_states["validated"])
    elsewhere = tmp_path_factory.mktemp("elsewhere")
    before, real_before = fingerprint(home), fingerprint(REAL)
    holders, real_track = [], pipeline.track_cuts

    def watched(*args, **kwargs):
        holders.append((lock.read_holder(home / "data" / "quick" / "interim"), [len(e.records) for e in lock._HELD.values()]))
        return real_track(*args, **kwargs)

    pipeline.track_cuts = watched
    try:
        with at_home(home, elsewhere):
            result = cli("replay", "--config", QUICK_CONFIG, "--until", "M2011-08")
    finally:
        pipeline.track_cuts = real_track
    return types.SimpleNamespace(home=home, elsewhere=elsewhere, result=result, before=before, after=fingerprint(home), real_before=real_before,
                                 real_after=fingerprint(REAL), holders=holders)


@pytest.fixture(scope="session")
def star_files(tmp_path_factory: pytest.TempPathFactory, quick_history):
    """``(cfg, out_dir, private_dir, paths, meta, warehouse)``: the star model of the quick history's last run, exported once per session on a
    copy of its warehouse (D72). The star model's contract, the HTML design and the site export read it; a test that writes copies it."""
    from churnrisk.dashboard.semantic_model import MODEL
    from churnrisk.export import ExportMeta, export_star_schema
    from churnrisk.warehouse import connect

    folder = tmp_path_factory.mktemp("star")
    warehouse = folder / "warehouse.sqlite"
    shutil.copy2(quick_history.warehouse, warehouse)
    out_dir, private_dir = folder / "outputs" / "powerbi", folder / "outputs" / "private"
    last = quick_history.runs[-1]
    meta = ExportMeta(last.run_key, last.spec.as_of, quick_history.view.source_sha256)
    conn = connect(warehouse)
    try:
        paths = export_star_schema(conn, out_dir, private_dir, MODEL, meta, quick_history.cfg)
    finally:
        conn.close()
    return quick_history.cfg, out_dir, private_dir, paths, meta, warehouse


@pytest.fixture(scope="session")
def site_files(tmp_path_factory: pytest.TempPathFactory, star_files) -> Path:
    """The five site files of the quick history's last run and their manifest, exported once per session (plan 24.1): the figures read them."""
    from churnrisk.site_export import export_site
    from churnrisk.warehouse import connect

    cfg, _out, _private, _paths, meta, warehouse = star_files
    folder = tmp_path_factory.mktemp("site_files") / "site"
    conn = connect(warehouse)
    try:
        export_site(conn, folder, meta, cfg)
    finally:
        conn.close()
    return folder


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


REAL_TRAINING_END = "2011-03-01"   # the first validation cut: no line from it on is read by a real_data test before U29 (D19)


@pytest.fixture(scope="session")
def real_training(real_canonical, cfg):
    """``(purchases, cancellations, rows)``: the real netting inputs dated before 2011-03-01, so that no line of a validation or test window
    is used (D19), and the rows of the seven training cuts with their features (index ``(cut_date, customer_id)``) and their label, built
    once per session with the project's own functions (mark real_data only)."""
    from datetime import date

    import pandas as pd

    from churnrisk.config import SealedConfig
    from churnrisk.cuts import label, label_end, population
    from churnrisk.features import compute_features, known_before
    from churnrisk.netting import customer_days, net_cancellations, netting_inputs
    from churnrisk.split import blocks

    _result, frame, _report = real_canonical
    view = SealedConfig.of(cfg, cfg.source.accepted_sha256)
    purchases, cancellations = netting_inputs(frame[frame["invoice_date"] < pd.Timestamp(REAL_TRAINING_END)].reset_index(drop=True))
    n = view.label.horizon_days
    parts = []
    for cut in [c for c, b in blocks(view).items() if b == "train"]:
        assert label_end(cut, n) < date.fromisoformat(REAL_TRAINING_END), "the window of a training cut closes before the first validation cut"
        days, lines = known_before(purchases, cancellations, cut)
        members = population(days, cut, view.label.active_days)
        features = compute_features(days, lines, cut, members, view)
        churned = label(customer_days(net_cancellations(purchases, cancellations, label_end(cut, n)).net_lines), cut, n, members)
        parts.append(features.assign(churned=churned, cut_date=cut).set_index("cut_date", append=True).swaplevel())
    return purchases, cancellations, pd.concat(parts)

