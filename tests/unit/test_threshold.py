"""The contact threshold chosen by cost on V2, the gain curve, the capture of the top share of each cut and the sensitivity to the
break-even (U15, AC19; RF19; D22): every key of ``[costs]`` changes the result as the formula says, and F1 is never used."""

from __future__ import annotations

import ast
import dataclasses
from datetime import date

import numpy as np
import pandas as pd
import pytest
from sklearn.metrics import f1_score

from churnrisk import model, threshold
from churnrisk.config import SealedConfig
from churnrisk.threshold import (
    Costs,
    break_even_grid,
    choose_on_v2,
    choose_threshold,
    cost_sensitivity,
    gain_curve,
    net_benefit,
    threshold_grid,
    top_share_capture,
    v2_threshold,
)
from tests.fixtures.hand_cases import GAIN_CAPTURED, THRESHOLD_EXPECTED, THRESHOLD_P, THRESHOLD_Y

SHA = "a" * 64
P, Y = np.array(THRESHOLD_P), np.array(THRESHOLD_Y)


def with_costs(view: SealedConfig, **changes) -> SealedConfig:
    return dataclasses.replace(view, costs=dataclasses.replace(view.costs, **changes))


def chosen(view: SealedConfig, p=P, y=Y) -> tuple[float, float]:
    """(threshold, net benefit) of the hand case under the costs and the grid of `view`."""
    costs = Costs.from_view(view)
    t = choose_threshold(p, y, costs, threshold_grid(view.costs))
    return t, net_benefit(y, p >= t, costs)


def blocks_frame() -> pd.DataFrame:
    """The hand case as the V2 rows, between training and test rows that a choice on V2 must never read."""
    rng = np.random.default_rng(1)
    parts = [pd.DataFrame({"block": "train", "risk": rng.random(30), "churned": rng.integers(0, 2, 30)}),
             pd.DataFrame({"block": "valid_v2", "risk": P, "churned": Y}),
             pd.DataFrame({"block": "test", "risk": rng.random(30), "churned": rng.integers(0, 2, 30)})]
    return pd.concat(parts, ignore_index=True)


# --- the RED of U15 -------------------------------------------------------------------------------------------------------


def test_net_benefit_hand_case_and_threshold_from_v2_only(cfg):
    """hand_cases: with the default costs a contacted customer is worth 10 x churned - 5; the best is 15, from 0.31 to 0.40, and a tie goes
    to the largest threshold. Only the rows of V2 are read."""
    view = SealedConfig.of(cfg, SHA)
    costs = Costs.from_view(view)
    assert costs.break_even() == 0.5
    assert [net_benefit(Y[i:i + 1], np.array([True]), costs) for i in range(8)] == [5.0, 5.0, -5.0, 5.0, 5.0, -5.0, -5.0, -5.0]
    assert net_benefit(Y, np.zeros(8, dtype=bool), costs) == 0.0 and net_benefit(Y, P >= 0.40, costs) == THRESHOLD_EXPECTED["net_benefit"]
    assert chosen(view) == (THRESHOLD_EXPECTED["threshold"], THRESHOLD_EXPECTED["net_benefit"])
    rows = blocks_frame()
    choice = choose_on_v2(rows, costs, threshold_grid(view.costs))
    assert (choice.threshold, choice.net_benefit, choice.net_benefit_per_1000, choice.contacted_share, choice.rows, choice.break_even) == (
        THRESHOLD_EXPECTED["threshold"], THRESHOLD_EXPECTED["net_benefit"], THRESHOLD_EXPECTED["net_benefit_per_1000"],
        THRESHOLD_EXPECTED["contacted"] / 8, 8, 0.5)
    others = rows["block"] != "valid_v2"
    shuffled = rows.assign(risk=np.where(others, 1 - rows["risk"], rows["risk"]), churned=np.where(others, 1 - rows["churned"], rows["churned"]))
    assert choose_on_v2(shuffled, costs, threshold_grid(view.costs)) == choice, "the training and the test never choose the threshold"
    moved = rows.assign(churned=np.where(others, rows["churned"], 1 - rows["churned"]))
    assert choose_on_v2(moved, costs, threshold_grid(view.costs)).threshold != choice.threshold, "control: V2 does"


def test_every_cost_key_changes_the_result(cfg):
    """Each key of [costs] on the hand case, with what the formula gives (AC19); the three of the sensitivity change its break-evens."""
    view = SealedConfig.of(cfg, SHA)
    assert chosen(view) == (0.40, 15.0)
    # offer_cost 7 (break-even 0.7): +3, +3, -7, +3, +3, -7, -7, -7 -> the best is 6, contacting the top two: t in (0.6, 0.8]
    assert chosen(with_costs(view, offer_cost=7.0)) == (0.80, 6.0)
    # rescue_rate 0.1 (break-even 1.0): 0, 0, -5, 0, 0, -5, -5, -5 -> the best is 0, and the largest threshold
    assert chosen(with_costs(view, rescue_rate=0.1)) == (0.99, 0.0)
    # retained_value 100 (break-even 0.25): +15, +15, -5, +15, +15, -5, -5, -5 -> the same five customers, worth 55
    assert chosen(with_costs(view, retained_value=100.0)) == (0.40, 55.0)
    # threshold_min 0.45: 0.40 is out of reach; the best left is 10, from 0.45 to 0.55 and from 0.61 to 0.80, and a tie goes to the largest
    assert chosen(with_costs(view, threshold_min=0.45)) == (0.80, 10.0)
    # threshold_max 0.35: the best stays 15, now at most at 0.35
    assert chosen(with_costs(view, threshold_max=0.35)) == (0.35, 15.0)
    # threshold_step 0.07: 0.01, 0.08, ..., 0.36, 0.43, ...: 0.36 is the only point in (0.3, 0.4]
    assert chosen(with_costs(view, threshold_step=0.07)) == (0.36, 15.0)
    p_v2 = {"model": P, "b4_frequency": P[::-1].copy()}
    for key, value, grid in (("sensitivity_min", 0.20, np.round(np.arange(0.20, 0.901, 0.05), 10)),
                             ("sensitivity_max", 0.50, np.round(np.arange(0.10, 0.501, 0.05), 10)),
                             ("sensitivity_step", 0.10, np.round(np.arange(0.10, 0.901, 0.10), 10))):
        changed = with_costs(view, **{key: value})
        np.testing.assert_allclose(break_even_grid(changed.costs), grid, atol=1e-12, err_msg=key)
        table = cost_sensitivity(p_v2, Y, None, None, changed)
        np.testing.assert_allclose(sorted(set(table["break_even"])), grid, atol=1e-12, err_msg=key)
    default = cost_sensitivity(p_v2, Y, None, None, view)
    assert len(default) == 17 * 2 and sorted(set(default["break_even"]))[0] == 0.1 and max(default["break_even"]) == pytest.approx(0.9)
    at = default[(default["method"] == "model") & (np.isclose(default["break_even"], 0.7))].iloc[0]
    # a break-even of 0.7 is an offer cost of 0.7 x 0.2 x 50 = 7 (6.999999999999999 in floating point)
    assert at["threshold"] == 0.80 and at["net_benefit"] == pytest.approx(6.0, abs=1e-9)


def test_neither_the_threshold_nor_the_model_imports_f1():
    for module in (threshold, model):
        tree = ast.parse(open(module.__file__, encoding="utf-8").read())
        names = {alias.name for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom)) for alias in node.names}
        assert not {name for name in names if "f1" in name.lower() or "fbeta" in name.lower()}, module.__name__
        assert "f1_score" not in open(module.__file__, encoding="utf-8").read()


def test_where_f1_would_contact_almost_everyone_the_cost_threshold_does_not(cfg):
    """800 customers who churn 80 % of the time, scored 0.8, and 200 who churn 45 %, scored 0.2: the best F1 contacts all of them (F1 0.844
    against 0.837), while the cost contacts only the first 800, because each of the others is worth 10 x 0.45 - 5 < 0 (AC19)."""
    view = SealedConfig.of(cfg, SHA)
    p = np.r_[np.full(800, 0.8), np.full(200, 0.2)]
    y = np.r_[np.ones(640), np.zeros(160), np.ones(90), np.zeros(110)].astype(int)
    grid = threshold_grid(view.costs)
    f1 = [f1_score(y, p >= t) for t in grid]
    best_f1 = grid[int(np.argmax(f1))]
    assert (p >= best_f1).mean() >= 0.95
    t = choose_threshold(p, y, Costs.from_view(view), grid)
    assert (p >= t).mean() == 0.80 and t == 0.80


# --- the gain curve and the capture ----------------------------------------------------------------------------------------


def test_the_gain_curve_and_the_capture_of_each_cut_hand_case():
    curve = gain_curve(P, Y, 8)
    assert list(curve.columns) == ["point", "contacted", "captured", "share_contacted", "share_captured", "lift"]
    assert tuple(curve["captured"]) == GAIN_CAPTURED and tuple(curve["contacted"]) == tuple(range(1, 9))
    np.testing.assert_allclose(curve["share_captured"], np.array(GAIN_CAPTURED) / 4)
    np.testing.assert_allclose(curve["lift"], (np.array(GAIN_CAPTURED) / 4) / (np.arange(1, 9) / 8))
    assert tuple(gain_curve(P, Y, 4)["captured"]) == (2, 3, 4, 4), "ceil(i / points x n) customers at each point"
    assert tuple(gain_curve(P, Y, 3)["contacted"]) == (3, 6, 8), "8 / 3 and 16 / 3 customers round up"
    tied = gain_curve(np.array([0.5, 0.5, 0.5, 0.1]), np.array([0, 1, 1, 0]), 4)
    assert tuple(tied["captured"]) == (0, 1, 2, 2), "a tie keeps the internal order of the rows"
    cuts = np.array([date(2011, 8, 1)] * 4 + [date(2011, 9, 1)] * 4)
    assert top_share_capture(P, Y, cuts, 0.10) == (2, 2), "ceil(0.1 x 4) = 1 customer of each cut: 0.9 and 0.4, both churners"
    assert top_share_capture(P, Y, cuts, 0.50) == (3, 4)
    with pytest.raises(ValueError, match="baja"):
        gain_curve(P, np.zeros(8, dtype=int), 4)


def test_the_sensitivity_chooses_on_v2_and_only_applies_the_threshold_to_the_test(cfg):
    view = SealedConfig.of(cfg, SHA)
    rng = np.random.default_rng(3)
    p_v2, y_v2 = {"model": P, "b4_frequency": P[::-1].copy()}, Y
    p_test = {"model": rng.random(50), "b4_frequency": rng.random(50)}
    y_test = rng.integers(0, 2, 50)
    table = cost_sensitivity(p_v2, y_v2, p_test, y_test, view)
    assert len(table) == 17 * 2 * 2 and set(table["scope"]) == {"valid_v2", "test"}
    for (b, method), rows in table.groupby(["break_even", "method"]):
        costs = Costs.from_view(view).at_break_even(b)
        assert set(rows["threshold"]) == {choose_threshold(p_v2[method], y_v2, costs, threshold_grid(view.costs))}, (b, method)
        test = rows[rows["scope"] == "test"].iloc[0]
        contacted = p_test[method] >= test["threshold"]
        assert test["net_benefit"] == net_benefit(y_test, contacted, costs) and test["contacted_share"] == contacted.mean() and test["rows"] == 50
    flipped = cost_sensitivity(p_v2, y_v2, p_test, 1 - y_test, view)
    assert flipped["threshold"].tolist() == table["threshold"].tolist(), "the test never chooses"
    with pytest.raises(ValueError, match="mismos métodos"):
        cost_sensitivity(p_v2, y_v2, {"model": p_test["model"]}, y_test, view)


def test_the_threshold_of_the_launch_comes_from_its_v2_risks(cfg, launch_model):
    view = SealedConfig.of(cfg, SHA)
    _labelled, trained = launch_model("irregular_gaps")
    choice = v2_threshold(trained.valid_v2, view)
    assert choice.threshold == choose_threshold(trained.valid_v2["risk"], trained.valid_v2["churned"], Costs.from_view(view), threshold_grid(view.costs))
    assert choice.rows == len(trained.valid_v2) and 0.01 <= choice.threshold <= 0.99 and choice.break_even == 0.5
    with pytest.raises(ValueError, match="positivo"):
        Costs(0.0, 0.2, 50.0)
    with pytest.raises(ValueError, match=r"\(0, 1\]"):
        Costs(5.0, 1.5, 50.0)


def test_a_gain_curve_whose_first_point_would_hold_no_customer_is_refused_before_any_point():
    """R3-gain-curve-zero-share: ``ceil(round(i / points x n, 9))`` is 0 only when ``n / points`` rounds to 0 at 9 decimals; that point would
    read ``captured[-1]`` (the last customer) and divide the lift by a share of 0, so it is refused before any point is computed. With more points
    than customers each point still holds at least one customer (points repeat)."""
    with pytest.raises(ValueError, match="al menos un cliente"):
        gain_curve(np.array([0.9]), np.array([1]), 3_000_000_000)
    small = gain_curve(np.array([0.9, 0.1, 0.5]), np.array([1, 0, 1]), 10)
    assert small["contacted"].min() == 1 and len(small) == 10 and small["lift"].notna().all()
