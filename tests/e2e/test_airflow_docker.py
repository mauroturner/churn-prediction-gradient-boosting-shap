"""``airflow dags test`` in Docker, twice, in quick mode (U27, AC35, AC36; plan, section 22). Mark ``docker``: not in the default selection,
and skipped unless the Docker engine is running. Adapted from project 03's ``tests/e2e/test_airflow_docker.py``.

Run it with ``pytest -m docker``. It builds the image of ``airflow/`` (several minutes the first time), runs ``pip check`` in it (with SHAP and
numba), starts the database and the initialization service of the compose file, runs the DAG on a small synthetic source twice in a row and
checks that the first run is the launch and the second the delivery ``M2011-08``, that what the launch fixed (the model artifact, its registry
row and the seal) did not change, and that the cut 2011-09-01 has its scores, each with its reasons. It writes only inside ``data/quick/``
(git-ignored), the ``airflow/logs``, ``airflow/config`` and ``airflow/plugins`` folders the containers use and the empty ``outputs``,
``reports`` and ``dashboard`` folders that the writable mounts create when they are missing, with throwaway secrets passed through the
environment (the four of the compose file, the password of the metadata database included), and removes what it created and the database
volume at the end, and the image ``churnrisk-airflow:3.4.0`` when this test built it (an image that was there before the test stays; A13, D92).
"""

from __future__ import annotations

import base64
import os
import secrets
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from tests.fixtures.make_fixture import make_fixture

PROJECT = Path(__file__).resolve().parents[2]
AIRFLOW = PROJECT / "airflow"
QUICK = PROJECT / "data" / "quick"
CREATED = ("logs", "config", "plugins")         # folders of airflow/ that the bind mounts create
MOUNTED = ("outputs", "reports", "dashboard")    # folders of the project that the writable mounts create when they are missing
IMAGE = "churnrisk-airflow:3.4.0"                 # the compose file's image of the Airflow services (tests/unit/test_compose.py checks the name)
BUILD_TIMEOUT_S = 1800
STEP_TIMEOUT_S = 900
TEARDOWN_TIMEOUT_S = 300

pytestmark = pytest.mark.docker

CURRENT: dict[str, str] = {}   # the secrets of the running test, the same for every docker call of it


def throwaway_secrets() -> dict[str, str]:
    """The four secrets of the compose file, new for each test: it has no default for any (AC36)."""
    return {
        "CHURNRISK_DB_PASSWORD": secrets.token_hex(24),
        "CHURNRISK_FERNET_KEY": base64.urlsafe_b64encode(os.urandom(32)).decode(),
        "CHURNRISK_JWT_SECRET": secrets.token_urlsafe(48),
        "CHURNRISK_ADMIN_PASSWORD": secrets.token_urlsafe(16),
    }


def docker(*args: str, timeout: int = STEP_TIMEOUT_S, check: bool = True, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    environment = {**os.environ, **(CURRENT if env is None else env), "ENV_FILE_PATH": str(AIRFLOW / ".env.example"),
                   "CHURNRISK_CONFIG": "/opt/churnrisk/config/pipeline.quick.toml"}
    try:
        return subprocess.run(["docker", *args], cwd=AIRFLOW, env=environment, capture_output=True, text=True, timeout=timeout, check=check, encoding="utf-8")
    except subprocess.TimeoutExpired as error:
        pytest.fail(f"docker {' '.join(args)} did not end in {timeout} s:\n" + str(error.stdout or "")[-1500:] + str(error.stderr or "")[-1500:])


def rows(query: str) -> list[tuple]:
    conn = sqlite3.connect(f"{(QUICK / 'churnrisk.sqlite').as_uri()}?mode=ro", uri=True)
    try:
        return conn.execute(query).fetchall()
    finally:
        conn.close()


def teardown(existing: set[str], existing_mounts: set[str], *, image_existed: bool) -> list[str]:
    """Remove the stack, its database volume, the folders this test created and the image if this test built it (`image_existed` False);
    return what could not be done."""
    problems: list[str] = []
    try:
        down = docker("compose", "down", "--volumes", check=False, timeout=TEARDOWN_TIMEOUT_S)
        if down.returncode != 0:
            problems.append(f"docker compose down --volumes returned {down.returncode}:\n" + (down.stdout + down.stderr)[-2000:])
    except (Exception, pytest.fail.Exception) as error:
        problems.append(f"docker compose down --volumes did not finish: {error}")
    if not image_existed:
        try:
            removed = docker("image", "rm", IMAGE, check=False, timeout=TEARDOWN_TIMEOUT_S)
            if removed.returncode != 0:
                problems.append(f"docker image rm {IMAGE} returned {removed.returncode}:\n" + (removed.stdout + removed.stderr)[-2000:])
        except (Exception, pytest.fail.Exception) as error:
            problems.append(f"docker image rm {IMAGE} did not finish: {error}")
    for folder in [QUICK] + [AIRFLOW / name for name in CREATED if name not in existing]:
        shutil.rmtree(folder, ignore_errors=True)
        if folder.exists():
            problems.append(f"{folder} could not be removed")
    for name in MOUNTED:
        folder = PROJECT / name
        if name not in existing_mounts and folder.exists():
            try:
                folder.rmdir()
            except OSError:
                problems.append(f"{folder} was created by the mounts and is not empty: {sorted(p.name for p in folder.iterdir())[:5]}")
    return problems


def dags_test() -> subprocess.CompletedProcess:
    return docker("compose", "--profile", "debug", "run", "--rm", "airflow-cli", "airflow", "dags", "test", "churnrisk_monthly", check=False)


@pytest.fixture(autouse=True)
def secrets_of_this_test():
    CURRENT.clear()
    CURRENT.update(throwaway_secrets())
    yield
    CURRENT.clear()


@pytest.fixture()
def engine():
    if shutil.which("docker") is None or subprocess.run(["docker", "info"], capture_output=True).returncode != 0:
        pytest.skip("the Docker engine is not running")


def test_the_compose_file_needs_each_secret_and_puts_the_database_password_in_the_connection_string(engine) -> None:
    """Without one secret (or with it empty) the file does not render and names it; with all four, the connection string and the PostgreSQL
    service carry the database password. Nothing is built or started."""
    given = dict(CURRENT)
    rendered = docker("compose", "config", env=given, check=False)
    assert rendered.returncode == 0, rendered.stderr[-2000:]
    assert f"postgresql+psycopg://airflow:{given['CHURNRISK_DB_PASSWORD']}@postgres/airflow" in rendered.stdout
    assert f"POSTGRES_PASSWORD: {given['CHURNRISK_DB_PASSWORD']}" in rendered.stdout
    for name in given:
        missing = docker("compose", "config", env={k: v for k, v in given.items() if k != name}, check=False)
        assert missing.returncode != 0 and name in missing.stderr, (name, missing.stderr[-800:])
        blank = docker("compose", "config", env={**given, name: ""}, check=False)
        assert blank.returncode != 0 and name in blank.stderr, (name, "empty", blank.stderr[-800:])


def test_the_dag_runs_the_launch_and_then_august_in_quick_mode_with_airflow_dags_test(engine) -> None:
    assert not QUICK.exists(), "data/quick is left over from another run (run `docker compose down --volumes` in airflow/ and delete it)"
    existing = {name for name in CREATED if (AIRFLOW / name).exists()}
    existing_mounts = {name for name in MOUNTED if (PROJECT / name).exists()}
    image_existed = docker("image", "inspect", IMAGE, check=False).returncode == 0
    make_fixture(QUICK / "online_retail_fixture.zip", n_customers=300, seed=0)
    try:
        for step in (("compose", "build"), ("compose", "up", "airflow-init")):
            done = docker(*step, check=False, timeout=BUILD_TIMEOUT_S if step[1] == "build" else STEP_TIMEOUT_S)
            assert done.returncode == 0, f"docker {' '.join(step)} failed:\n" + (done.stdout + done.stderr)[-3000:]
        consistent = docker("compose", "--profile", "debug", "run", "--rm", "airflow-cli", "bash", "-c", "pip check && python -c 'import shap, numba'", check=False)
        assert consistent.returncode == 0 and "No broken requirements found" in consistent.stdout, (consistent.stdout + consistent.stderr)[-2000:]

        first = dags_test()
        assert first.returncode == 0, first.stdout[-3000:] + first.stderr[-3000:]
        registry = "SELECT model_version, trained_as_of, artifact_path, artifact_sha256, config_sha256 FROM model_registry"
        launch_model, launch_seal = rows(registry), (QUICK / "reports" / "model_seal.json").read_bytes()
        launch_artifact = {p.relative_to(QUICK).as_posix(): p.read_bytes() for p in (QUICK / "models").rglob("*") if p.is_file()}
        assert [r[0] for r in rows("SELECT delivery_id FROM pipeline_runs ORDER BY as_of_date")] == ["L2011-07"]
        assert len(launch_model) == 1 and launch_seal and launch_artifact

        second = dags_test()
        assert second.returncode == 0, second.stdout[-3000:] + second.stderr[-3000:]
        assert rows("SELECT delivery_id, status, as_of_date FROM pipeline_runs ORDER BY as_of_date") == [("L2011-07", "ok", "2011-07-31"), ("M2011-08", "ok", "2011-08-31")]
        assert rows("SELECT delivery_id, status FROM deliveries ORDER BY as_of_date") == [("L2011-07", "loaded"), ("M2011-08", "loaded")]
        assert rows(registry) == launch_model and (QUICK / "reports" / "model_seal.json").read_bytes() == launch_seal
        assert {p.relative_to(QUICK).as_posix(): p.read_bytes() for p in (QUICK / "models").rglob("*") if p.is_file()} == launch_artifact
        scored, explained, deepest = rows("SELECT (SELECT COUNT(*) FROM model_scores WHERE cut_date = '2011-09-01'), (SELECT COUNT(DISTINCT customer_id) FROM "
                                          "score_reasons WHERE cut_date = '2011-09-01'), (SELECT MAX(rank) FROM score_reasons WHERE cut_date = '2011-09-01')")[0]
        assert scored > 0 and explained == scored and 1 <= deepest <= 3, "the cut of the run has its scores, each with its reasons (at most three)"
        assert (QUICK / "outputs" / "site" / "summary.json").is_file() and (QUICK / "dashboard" / "powerbi-design.html").is_file()
    finally:
        problems = teardown(existing, existing_mounts, image_existed=image_existed)
        if problems:
            sys.stderr.write("TEARDOWN FAILED:\n" + "\n".join(problems) + "\n")
    assert not problems, "the teardown failed, so the next run will find leftovers:\n" + "\n".join(problems)
