"""The environment and its dependencies (U01, item 5): every third-party module the code imports is a pinned direct requirement
documented as such (AC39, project 03 B6), every pin is exact (D38, RNF01) and the generated state stays out of Git (RNF10)."""

from __future__ import annotations

import ast
import importlib.metadata
import re
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[2]
# Top-level names that belong to this project, not to a distribution
LOCAL_TOP_LEVEL = {"churnrisk", "tests"}
# The line that separates the direct pins (above) from the transitive ones (below) in both requirements files
TRANSITIVE_MARKER = "# transitive"
PIN = re.compile(r"([A-Za-z0-9][A-Za-z0-9_.-]*)==([A-Za-z0-9_.+!-]+)")
REQUIREMENT_NAME = re.compile(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def normalize(name: str) -> str:
    """PEP 503 normalization: ``scikit_learn``, ``Scikit-Learn`` and ``scikit-learn`` are one distribution."""
    return re.sub(r"[-_.]+", "-", name).lower()


@dataclass
class Pins:
    direct: dict[str, str] = field(default_factory=dict)
    transitive: dict[str, str] = field(default_factory=dict)
    includes: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def all(self) -> dict[str, str]:
        return {**self.direct, **self.transitive}


def read_pins(path: Path) -> Pins:
    pins = Pins()
    section = pins.direct
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if raw.strip() == TRANSITIVE_MARKER:
            section = pins.transitive
            continue
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("-r "):
            pins.includes.append(line[3:].strip())
            continue
        match = PIN.fullmatch(line)
        if not match:
            pins.problems.append(f"{path.name}:{number}: {line!r} is not an exact == pin")
            continue
        name = normalize(match.group(1))
        if name in pins.all:
            pins.problems.append(f"{path.name}:{number}: {name} is pinned twice")
            continue
        section[name] = match.group(2)
    return pins


def third_party_imports(root: Path, project: Path) -> dict[str, set[str]]:
    """Top-level module -> the files (relative to the project) that import it, for every absolute import of a module outside the
    standard library and outside this project."""
    found: dict[str, set[str]] = {}
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            else:
                continue
            for name in names:
                top = name.split(".", 1)[0]
                if top in sys.stdlib_module_names or top == "__future__" or top in LOCAL_TOP_LEVEL:
                    continue
                found.setdefault(top, set()).add(path.relative_to(project).as_posix())
    return found


def distribution_of(module: str) -> str:
    """The distribution that provides an importable top-level module (``sklearn`` -> ``scikit-learn``); the module's own name when
    nothing installed provides it, so a missing package is still reported by a recognisable name."""
    providers = importlib.metadata.packages_distributions().get(module)
    return normalize(providers[0] if providers else module)


def dependency_problems(project: Path) -> list[str]:
    """Every third-party import of ``src/`` must be a direct pin of requirements.txt, and every one of ``tests/`` a direct pin of
    requirements.txt or of requirements-dev.txt; a module pinned only in a transitive section is documented as what it is not, and a direct
    pin of requirements-dev.txt imported by ``src/`` is a development tool that an installation of the runtime alone does not have."""
    runtime = read_pins(project / "requirements.txt")
    dev = read_pins(project / "requirements-dev.txt")
    problems: list[str] = []
    transitive = runtime.transitive | dev.transitive
    # (folder, the pins it may import, the direct pins it may not: only the development tools have them)
    scopes = (("src", runtime.direct, dev.direct), ("tests", runtime.direct | dev.direct, {}))
    for folder, direct, development_only in scopes:
        if not (project / folder).is_dir():
            continue
        for module, files in sorted(third_party_imports(project / folder, project).items()):
            dist = distribution_of(module)
            where = ", ".join(sorted(files))
            if dist in direct:
                continue
            if dist in development_only:
                problems.append(f"{module} ({dist}) is imported by {where} but is a development-only dependency (a direct pin of requirements-dev.txt), "
                                "which runtime code cannot import")
            elif dist in transitive:
                problems.append(f"{module} ({dist}) is imported by {where} but is pinned only as a transitive dependency")
            else:
                problems.append(f"{module} ({dist}) is imported by {where} but is not pinned as a direct requirement")
    return problems


def never_applies(marker: str) -> bool:
    """A requirement only an extra asks for, or only a Python older than the project's 3.11 (pyproject's requires-python): ``< "3.N"`` for
    N up to 11 and ``<= "3.N"`` for N up to 10, in single or double quotes."""
    if "extra" in marker:
        return True
    older = re.search(r"""python_version\s*(<=|<)\s*(['"])3\.(\d+)\2""", marker)
    if older is None:
        return False
    minor = int(older.group(3))
    return minor <= 11 if older.group(1) == "<" else minor <= 10


def required_names(dist: str) -> set[str]:
    """The distributions a pinned distribution requires on some supported platform and Python."""
    names = set()
    for requirement in importlib.metadata.requires(dist) or []:
        if ";" in requirement and never_applies(requirement.split(";", 1)[1]):
            continue
        match = REQUIREMENT_NAME.match(requirement)
        if match:
            names.add(normalize(match.group(1)))
    return names


# --- AC39: the imports and the pins ------------------------------------------------------------------------------------


def test_every_direct_import_is_a_pinned_requirement_and_documented(tmp_path):
    # the check itself, on a copy of the project whose code imports shap with its pin removed, or with shap filed as transitive
    probe = tmp_path / "probe"
    (probe / "src" / "churnrisk").mkdir(parents=True)
    (probe / "src" / "churnrisk" / "explain_probe.py").write_text("import numpy as np\nimport shap\nfrom sklearn import metrics\n", encoding="utf-8")
    shutil.copy(PROJECT / "requirements-dev.txt", probe / "requirements-dev.txt")
    lines = (PROJECT / "requirements.txt").read_text(encoding="utf-8").splitlines()
    without_shap = [line for line in lines if not line.startswith("shap==")]
    (probe / "requirements.txt").write_text("\n".join(without_shap) + "\n", encoding="utf-8")
    assert dependency_problems(probe) == [
        "shap (shap) is imported by src/churnrisk/explain_probe.py but is not pinned as a direct requirement"
    ]
    (probe / "requirements.txt").write_text("\n".join(without_shap + ["shap==0.51.0"]) + "\n", encoding="utf-8")
    assert dependency_problems(probe) == [
        "shap (shap) is imported by src/churnrisk/explain_probe.py but is pinned only as a transitive dependency"
    ]
    # and on the project as it is
    assert dependency_problems(PROJECT) == []


def probe_project(tmp_path: Path, files: dict[str, str]) -> Path:
    """A copy of the project's two requirements files next to the given source files (path relative to the probe -> text)."""
    probe = tmp_path / "probe"
    probe.mkdir()
    for name in ("requirements.txt", "requirements-dev.txt"):
        shutil.copy(PROJECT / name, probe / name)
    for relative, text in files.items():
        (probe / relative).parent.mkdir(parents=True, exist_ok=True)
        (probe / relative).write_text(text, encoding="utf-8")
    return probe


def test_a_development_only_direct_dependency_imported_by_src_is_reported_as_such(tmp_path):
    """pytest is a direct pin of requirements-dev.txt: runtime code that imports it is not wrongly told it is pinned as transitive (R3-dep-problems-mislabel)."""
    probe = probe_project(tmp_path, {"src/churnrisk/uses_pytest.py": "import pytest\nimport numpy\n"})
    assert dependency_problems(probe) == [
        "pytest (pytest) is imported by src/churnrisk/uses_pytest.py but is a development-only dependency (a direct pin of "
        "requirements-dev.txt), which runtime code cannot import"
    ]


def test_the_tests_scope_takes_direct_pins_of_both_files_and_names_the_rest(tmp_path):
    """The tests scope (R3-missing-coverage-tests-scope): a direct pin of either file passes, a transitive one is named as such and a module
    no installed distribution provides is reported by its own name (the fallback of distribution_of)."""
    probe = probe_project(tmp_path, {
        "tests/test_probe.py": "import numpy\nimport lifetimes\nimport pluggy\nimport no_such_module_xyz\nfrom sklearn import metrics\n",
    })
    assert dependency_problems(probe) == [
        "no_such_module_xyz (no-such-module-xyz) is imported by tests/test_probe.py but is not pinned as a direct requirement",
        "pluggy (pluggy) is imported by tests/test_probe.py but is pinned only as a transitive dependency",
    ]
    assert distribution_of("no_such_module_xyz") == "no-such-module-xyz" and distribution_of("sklearn") == "scikit-learn"


@pytest.mark.parametrize(("marker", "never"), [
    ('python_version < "3.8"', True), ("python_version < '3.8'", True), ('python_version < "3.11"', True), ('python_version < "3.12"', False),
    ('python_version <= "3.10"', True), ("python_version <= '3.10'", True), ('python_version <= "3.11"', False), ("python_version<='3.12'", False),
    ('extra == "test"', True), ('platform_system == "Windows"', False),
])
def test_a_marker_never_applies_only_to_extras_and_to_pythons_older_than_3_11(marker, never):
    """Single or double quotes and a strict or inclusive bound (R3-never-applies-brittle): ``<= "3.11"`` still applies to 3.11."""
    assert never_applies(marker) is never


def test_every_pin_is_exact_and_python_dateutil_is_below_3():
    runtime = read_pins(PROJECT / "requirements.txt")
    dev = read_pins(PROJECT / "requirements-dev.txt")
    assert runtime.problems + dev.problems == []
    assert runtime.includes == [] and dev.includes == ["requirements.txt"]
    assert not set(runtime.all) & set(dev.all), "requirements-dev.txt pins again what requirements.txt already pins"
    # project 01 D44 and project 02 D55: version 4.x of python-dateutil conflicts with Airflow's own dependencies; six comes with 2.9
    assert int(runtime.all["python-dateutil"].split(".", 1)[0]) < 3
    assert runtime.all["six"] == "1.17.0"


def test_shap_and_numba_are_the_versions_research_measured_additivity_with():
    """D38: shap 0.51.0 with numba 0.68.1 is what research.md ran (additivity 8e-15 with the country one-hot); the rest is project 02's set."""
    runtime = read_pins(PROJECT / "requirements.txt")
    assert runtime.direct["shap"] == "0.51.0" and runtime.all["numba"] == "0.68.1"
    project_02 = {"numpy": "2.4.6", "pandas": "2.3.3", "scipy": "1.17.1", "scikit-learn": "1.9.1", "pyarrow": "26.0.1", "matplotlib": "3.11.2", "openpyxl": "3.1.5"}
    assert {name: runtime.direct[name] for name in project_02} == project_02
    dev = read_pins(PROJECT / "requirements-dev.txt")
    assert dev.direct == {"pytest": "9.2.0", "lifetimes": "0.11.3"}


def test_every_transitive_pin_is_required_by_another_pin():
    runtime = read_pins(PROJECT / "requirements.txt")
    dev = read_pins(PROJECT / "requirements-dev.txt")
    pinned = runtime.all | dev.all
    required = set().union(*(required_names(name) for name in pinned))
    orphans = sorted((set(runtime.transitive) | set(dev.transitive)) - required)
    assert orphans == [], f"pinned as transitive but required by no other pin: {orphans}"


def test_each_requirements_file_pins_everything_its_pins_require():
    """requirements.txt alone installs a complete runtime (the image installs only it, D38): colorama is there because tqdm needs it on
    Windows, not only because pytest does; requirements-dev.txt adds what the test tools need on top of it."""
    runtime = read_pins(PROJECT / "requirements.txt")
    dev = read_pins(PROJECT / "requirements-dev.txt")
    for pinned, available in ((runtime.all, set(runtime.all)), (dev.all, set(runtime.all) | set(dev.all))):
        missing = {name: sorted(required_names(name) - available) for name in pinned}
        assert {name: needs for name, needs in missing.items() if needs} == {}


def test_no_dependency_outside_the_declared_set_is_pinned():
    """D13 (scikit-learn, not LightGBM), D35 (no pytest-xdist) and research.md (psutil only measured the research)."""
    pinned = set(read_pins(PROJECT / "requirements.txt").all) | set(read_pins(PROJECT / "requirements-dev.txt").all)
    assert not ({"lightgbm", "xgboost", "pytest-xdist", "execnet", "psutil", "requests", "httpx"} & pinned)


def test_installed_versions_match_the_pins():
    pinned = read_pins(PROJECT / "requirements.txt").all | read_pins(PROJECT / "requirements-dev.txt").all
    wrong = {}
    for name, version in pinned.items():
        try:
            installed = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            installed = None
        if installed != version:
            wrong[name] = (version, installed)
    assert not wrong, f"installed versions differ from the pins (pinned, installed): {wrong}"


def test_pip_check_reports_no_broken_requirements():
    result = subprocess.run([sys.executable, "-m", "pip", "check", "--disable-pip-version-check"], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "No broken requirements found" in result.stdout


# --- the project files ----------------------------------------------------------------------------------------------------


def test_pyproject_declares_the_package_the_pythons_and_the_marks():
    document = tomllib.loads((PROJECT / "pyproject.toml").read_text(encoding="utf-8"))
    assert document["project"]["name"] == "churnrisk"
    assert document["project"]["requires-python"] == ">=3.11,<3.14"
    options = document["tool"]["pytest"]["ini_options"]
    assert "-m 'not real_data and not docker'" in options["addopts"] and "--strict-markers" in options["addopts"]
    assert {mark.split(":", 1)[0] for mark in options["markers"]} == {"real_data", "docker", "oracle"}
    assert options["pythonpath"] == ["src", "."]


@pytest.mark.parametrize("entry", [
    "data/raw/", "data/interim/", "data/warehouse/", "data/models/", "data/quick/", "outputs/private/", "airflow/logs/", "airflow/config/",
    "airflow/plugins/", "airflow/.env", "reports/validation/history/", ".venv/", "__pycache__/", ".pytest_cache/",
])
def test_gitignore_keeps_generated_state_and_the_environment_out_of_git(entry):
    assert entry in (PROJECT / ".gitignore").read_text(encoding="utf-8").splitlines()


def test_the_seal_the_reports_and_the_published_outputs_are_not_ignored():
    """RNF10: the seal, the reports, the Parquet of outputs/powerbi/, the site files and the dashboard are versioned; outputs/private/ is not (D26)."""
    ignored = set((PROJECT / ".gitignore").read_text(encoding="utf-8").splitlines())
    assert not ({"reports/", "outputs/", "outputs/powerbi/", "outputs/site/", "reports/model_seal.json", "dashboard/", "docs/"} & ignored)


def test_the_docker_build_context_holds_only_requirements_txt():
    lines = [line for line in (PROJECT / ".dockerignore").read_text(encoding="utf-8").splitlines() if line and not line.startswith("#")]
    assert lines == ["*", "!requirements.txt"]


def test_the_package_imports_from_the_source_folder():
    import churnrisk

    assert Path(churnrisk.__file__).resolve().parent == PROJECT / "src" / "churnrisk"
    assert churnrisk.__version__ == "0.1.0"
