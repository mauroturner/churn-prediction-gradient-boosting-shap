"""The sources of the project compile cleanly and the suite collects only its own tests (A14 of the independent evaluation; D92): a function
whose name starts with ``test`` imported into a test module is collected as a test of that module (``reporting.test_delivery`` was, and inflated
the count by one with a ``PytestReturnNotNoneWarning``), and an invalid escape in a string literal is a warning in Python 3.11 and 3.13 (the
image's) and meant to become an error. Static: nothing is imported or run."""

from __future__ import annotations

import ast
import warnings
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
SOURCES = sorted([*(PROJECT / "src").rglob("*.py"), *(PROJECT / "tests").rglob("*.py"), *(PROJECT / "airflow").rglob("*.py")])


def test_no_test_module_imports_a_name_pytest_would_collect():
    imported = []
    for path in sorted((PROJECT / "tests").rglob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if isinstance(node, ast.ImportFrom):
                imported += [f"{path.relative_to(PROJECT).as_posix()}: {a.asname or a.name}" for a in node.names
                             if (a.asname or a.name).lower().startswith("test")]
    assert len(SOURCES) > 100 and imported == []


def test_every_source_compiles_without_an_invalid_escape():
    found = []
    for path in SOURCES:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            compile(path.read_text(encoding="utf-8"), str(path), "exec")
        # Python 3.11 says it with a DeprecationWarning, 3.12 and later with a SyntaxWarning
        found += [f"{path.relative_to(PROJECT).as_posix()}:{w.lineno}: {w.message}" for w in caught
                  if issubclass(w.category, (SyntaxWarning, DeprecationWarning)) and "invalid escape sequence" in str(w.message)]
    assert found == []
