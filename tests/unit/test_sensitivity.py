"""The sensitivity is reported and never used to choose (U18, AC26; RNF06 e; D10): a static test over the functions that choose, and the rule of
the cuts each variant keeps for any N."""

from __future__ import annotations

import dataclasses
import inspect
from datetime import date
from pathlib import Path

import pytest

from churnrisk import baselines, launch, model, threshold
from churnrisk.registry import sealed_view
from churnrisk.sensitivity import variant_plan

SOURCE_DIR = Path(__file__).resolve().parents[2] / "src" / "churnrisk"
SENSITIVITY_NAMES = ("sensitivity", "eval_variants", "eval_label_definition", "eval_silence_return", "run_variants", "definition_tables")


# --- the RED of U18 ------------------------------------------------------------------------------------------------------


def test_no_choosing_function_reads_a_sensitivity_table():
    """The selection, the calibration, B*, the threshold and the launch that seals them never name the sensitivity or its tables, and their
    modules never import it (plan, section 17)."""
    choosing = (model.select, model.calibrate, model.train_model, model.check_tripwire, baselines.strongest, baselines.fit_calibrators,
                baselines.fit_baselines, threshold.choose_threshold, threshold.choose_on_v2, threshold.v2_threshold, launch.fit_model, launch._launch)
    for function in choosing:
        source = inspect.getsource(function)
        for name in SENSITIVITY_NAMES:
            assert name not in source, f"{function.__module__}.{function.__name__} names {name}"
    for module in ("model", "baselines", "threshold", "launch", "split", "features", "registry"):
        text = (SOURCE_DIR / f"{module}.py").read_text(encoding="utf-8")
        assert "import sensitivity" not in text and "churnrisk.sensitivity" not in text, f"{module}.py imports the sensitivity"


def test_the_sensitivity_has_no_threshold_and_no_cost():
    text = (SOURCE_DIR / "sensitivity.py").read_text(encoding="utf-8")
    for name in ("Costs", "choose_threshold", "choose_on_v2", "v2_threshold", "net_benefit", ".costs"):
        assert name not in text, name


def test_each_variant_keeps_the_cuts_whose_window_and_purge_fit_any_n(cfg):
    """The rule, not a list: with N = 30 every cut fits; with N = 150 the training stops in October (2010-10-01 + 150 days = 2011-02-28) and no
    test window ends inside the data, which the variant then cannot measure, and only 2011-03-01 of V1 is purged before the test (2011-04-01 + 150 days
    = 2011-08-29); an unknown variant is refused."""
    view = sealed_view(cfg, "a" * 64)
    shorter = dataclasses.replace(view, sensitivity=dataclasses.replace(view.sensitivity, n60_horizon_days=30, n120_horizon_days=150))
    short, long = variant_plan(shorter, "n60"), variant_plan(shorter, "n120")
    assert (short.n, len(short.train), len(short.valid_v1), len(short.test)) == (30, 7, 2, 2)
    assert (long.n, long.train[-1], long.valid_v1, long.test) == (150, date(2010, 10, 1), (date(2011, 3, 1),), ())
    assert variant_plan(view, "no_december").train[-1] == date(2010, 11, 1) and variant_plan(view, "m180").m == 180
    with pytest.raises(ValueError, match="variante de sensibilidad desconocida"):
        variant_plan(view, "n45")
