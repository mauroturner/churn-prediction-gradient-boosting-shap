"""The fast suite's time limit (U03, AC41; D34): a full default session over the limit fails and says by how much; a part of the suite
never fails for its time. Run in this process with ``pytester`` on a toy suite whose limit is 0 s."""

from __future__ import annotations

TOY_PYPROJECT = """
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-m 'not real_data and not docker'"
markers = ["real_data: x", "docker: x"]
fast_suite_limit_s = "{limit}"
"""
TOY_CONFTEST = "from tests.fixtures.suite_budget import pytest_addoption, pytest_sessionfinish, pytest_sessionstart  # noqa: F401\n"


def toy_suite(pytester, limit: str) -> None:
    pytester.makepyprojecttoml(TOY_PYPROJECT.format(limit=limit))
    pytester.makeconftest(TOY_CONFTEST)
    (pytester.path / "tests").mkdir(exist_ok=True)
    (pytester.path / "tests" / "test_toy.py").write_text("def test_one():\n    assert True\n\ndef test_two():\n    assert True\n", encoding="utf-8")


def test_a_full_default_session_over_the_limit_fails_and_says_by_how_much(pytester):
    toy_suite(pytester, "0")
    result = pytester.runpytest_inprocess()
    result.assert_outcomes(passed=2)
    assert result.ret == 1
    result.stdout.re_match_lines([r"La suite rápida tardó \d+\.\d\d s, \d+\.\d\d s por encima del límite de 0 s"])


def test_a_part_of_the_suite_or_a_session_under_the_limit_passes(pytester):
    toy_suite(pytester, "0")
    for args in (["-k", "one"], ["tests/test_toy.py"], ["-m", "not docker"], ["--deselect", "tests/test_toy.py::test_two"]):
        result = pytester.runpytest_inprocess(*args)
        assert result.ret == 0, args
        assert "La suite rápida tardó" not in result.stdout.str(), args
    toy_suite(pytester, "120")
    result = pytester.runpytest_inprocess()
    assert result.ret == 0 and "La suite rápida tardó" not in result.stdout.str()


def test_the_guards_mark_expression_is_the_default_one_of_pyproject():
    """R3-suite-budget-markexpr-drift: the guard recognises the default selection by its mark expression, so it must be the one that
    pyproject.toml passes to every session; if they drifted apart, no session would ever be failed for its time."""
    import shlex
    import tomllib
    from pathlib import Path

    from tests.fixtures.suite_budget import DEFAULT_MARKEXPR

    pyproject = tomllib.loads((Path(__file__).resolve().parents[2] / "pyproject.toml").read_text(encoding="utf-8"))
    tokens = shlex.split(pyproject["tool"]["pytest"]["ini_options"]["addopts"])
    assert tokens.count("-m") == 1 and tokens[tokens.index("-m") + 1] == DEFAULT_MARKEXPR


def test_the_project_limit_is_120_seconds(pytestconfig):
    from tests.fixtures.suite_budget import FAST_SUITE_LIMIT_S

    assert FAST_SUITE_LIMIT_S == 120.0 and float(pytestconfig.getini("fast_suite_limit_s")) == 120.0
