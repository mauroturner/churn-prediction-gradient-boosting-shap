"""The contact threshold chosen by cost, the gain curve and the sensitivity to the break-even (RF19, AC19; D22; plan, section 14). Adapted from
project 03's ``threshold.py``.

The net benefit of contacting a customer is ``churned x rescue_rate x retained_value - offer_cost``; of not contacting him, 0. With the
default costs, ``sum over the contacted (10 x churned - 5)``. The threshold is the value of the grid (``threshold_min`` to ``threshold_max``,
every ``threshold_step``) whose ``p >= t`` gives the largest net benefit **on V2**; on a tie, the largest (fewer contacts). The costs are
declared assumptions in generic units (D22): what decides the threshold is their quotient, the break-even ``offer_cost / (rescue_rate x
retained_value)``. F1 is never used: neither this module nor ``model.py`` imports it (a test reads their source).

The **gain curve** orders the customers by score, highest first (ties keep the internal order of the rows, which is never published), and
says which share of the churners the top share of the customers holds, at ``gain_points`` points, and its lift. ``top_share_capture`` takes
the top ``ceil(share x n)`` of each cut. ``cost_sensitivity`` repeats the choice on V2 at each break-even of the declared range, rescaling
``offer_cost`` to ``b x rescue_rate x retained_value``, for each method, and applies that threshold to the test when the test is given: the
test never chooses anything.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
import pandas as pd

from churnrisk.config import CostsConfig, SealedConfig

VALID_V2 = "valid_v2"
TEST = "test"
TIE_TOLERANCE = 1e-9
SENSITIVITY_COLUMNS = ("break_even", "method", "scope", "threshold", "net_benefit", "net_benefit_per_1000", "contacted_share", "rows")
GAIN_COLUMNS = ("point", "contacted", "captured", "share_contacted", "share_captured", "lift")


@dataclass(frozen=True)
class Costs:
    """The assumed costs, in generic units: what an offer costs, the share of the churners it rescues and the value of a retained customer."""

    offer_cost: float
    rescue_rate: float
    retained_value: float

    def __post_init__(self) -> None:
        for name in ("offer_cost", "retained_value"):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name}: se esperaba un número positivo, se recibió {value!r}")
        if not math.isfinite(self.rescue_rate) or not 0 < self.rescue_rate <= 1:
            raise ValueError(f"rescue_rate: se esperaba un número en (0, 1], se recibió {self.rescue_rate!r}")

    @classmethod
    def from_view(cls, view: SealedConfig) -> Costs:
        c = view.costs
        return cls(c.offer_cost, c.rescue_rate, c.retained_value)

    def break_even(self) -> float:
        """The probability of churn above which an offer pays: ``offer_cost / (rescue_rate x retained_value)``."""
        return self.offer_cost / (self.rescue_rate * self.retained_value)

    def at_break_even(self, break_even: float) -> Costs:
        """The same rescue rate and retained value with the offer cost that gives `break_even`."""
        return Costs(break_even * self.rescue_rate * self.retained_value, self.rescue_rate, self.retained_value)


def _steps(low: float, high: float, step: float) -> np.ndarray:
    count = int(np.floor((high - low) / step + 1e-9)) + 1
    return np.round(low + step * np.arange(count), 10)


def threshold_grid(costs: CostsConfig) -> np.ndarray:
    """The thresholds tried: ``threshold_min`` to ``threshold_max`` in steps of ``threshold_step`` (99 by default)."""
    return _steps(costs.threshold_min, costs.threshold_max, costs.threshold_step)


def break_even_grid(costs: CostsConfig) -> np.ndarray:
    """The break-evens of the sensitivity: ``sensitivity_min`` to ``sensitivity_max`` in steps of ``sensitivity_step`` (17 by default)."""
    return _steps(costs.sensitivity_min, costs.sensitivity_max, costs.sensitivity_step)


def _check(p, y) -> tuple[np.ndarray, np.ndarray]:
    p, y = np.asarray(p, dtype="float64"), np.asarray(y)
    if p.ndim != 1 or p.shape != y.shape:
        raise ValueError(f"los puntajes y las etiquetas deben ser vectores del mismo largo; se recibió {p.shape} y {y.shape}")
    if len(p) == 0:
        raise ValueError("no hay clientes para elegir el umbral")
    if not np.isfinite(p).all():
        raise ValueError("hay puntajes que no son finitos")
    if not np.isin(y, (0, 1)).all():
        raise ValueError("las etiquetas deben ser 0 o 1")
    return p, y.astype("int64")


def net_benefit(y: np.ndarray, contacted: np.ndarray, costs: Costs) -> float:
    """The total net benefit of contacting the customers in `contacted`: ``sum over the contacted (churned x r x V - offer_cost)``."""
    y, contacted = np.asarray(y), np.asarray(contacted, dtype=bool)
    if y.shape != contacted.shape or y.ndim != 1:
        raise ValueError(f"las etiquetas y los contactos deben ser vectores del mismo largo; se recibió {y.shape} y {contacted.shape}")
    if not np.isin(y, (0, 1)).all():
        raise ValueError("las etiquetas deben ser 0 o 1")
    return float(y[contacted].sum() * costs.rescue_rate * costs.retained_value - contacted.sum() * costs.offer_cost)


def choose_threshold(p: np.ndarray, y: np.ndarray, costs: Costs, grid: np.ndarray) -> float:
    """The value of `grid` that maximizes the net benefit of contacting ``p >= t`` for the labels `y`; on a tie, the largest."""
    p, y = _check(p, y)
    grid = np.asarray(grid, dtype="float64")
    if grid.ndim != 1 or len(grid) == 0:
        raise ValueError("la grilla de umbrales no puede estar vacía")
    contacts = p[:, None] >= grid[None, :]
    benefit = (contacts & (y[:, None] == 1)).sum(axis=0) * costs.rescue_rate * costs.retained_value - contacts.sum(axis=0) * costs.offer_cost
    return float(grid[np.flatnonzero(benefit >= benefit.max() - TIE_TOLERANCE)].max())


@dataclass(frozen=True)
class ThresholdChoice:
    """The threshold chosen on V2 with the figures that go with it."""

    threshold: float
    break_even: float
    net_benefit: float
    net_benefit_per_1000: float
    contacted_share: float
    rows: int


def choose_on_v2(rows: pd.DataFrame, costs: Costs, grid: np.ndarray, score: str = "risk") -> ThresholdChoice:
    """Choose the threshold from the V2 rows of `rows` (columns ``block``, ``churned`` and the probability `score`); the rows of any other
    block are never read."""
    for column in ("block", "churned", score):
        if column not in rows.columns:
            raise ValueError(f"las filas necesitan la columna {column}")
    v2 = rows.loc[rows["block"] == VALID_V2]
    if v2.empty:
        raise ValueError("no hay clientes de V2 para elegir el umbral")
    p, y = _check(v2[score], v2["churned"])
    t = choose_threshold(p, y, costs, grid)
    contacted = p >= t
    benefit = net_benefit(y, contacted, costs)
    return ThresholdChoice(t, costs.break_even(), benefit, benefit / len(y) * 1000, float(contacted.mean()), len(y))


def v2_threshold(valid_v2: pd.DataFrame, view: SealedConfig) -> ThresholdChoice:
    """The threshold of the model the launch trained: chosen on its calibrated V2 risks (``model.TrainedModel.valid_v2``, columns
    ``churned`` and ``risk``) with the costs and the grid of ``[costs]``."""
    return choose_on_v2(valid_v2.assign(block=VALID_V2), Costs.from_view(view), threshold_grid(view.costs))


def _ranking(score: np.ndarray) -> np.ndarray:
    """The rows by score, highest first; a tie keeps the internal order of the rows."""
    return np.argsort(-np.asarray(score, dtype="float64"), kind="stable")


def gain_curve(score: np.ndarray, y: np.ndarray, points: int) -> pd.DataFrame:
    """The share of the churners held by the top ``ceil(i / points x n)`` customers by score, for i = 1 .. `points`, and its lift.

    Every point holds at least one customer: with more points than customers the points repeat, and a `points` so large that the first point
    would hold none (``n / points`` rounds to 0 at 9 decimals) is refused before any point is computed, since that point would read the last
    customer and divide its lift by a share of 0."""
    score, y = _check(score, y)
    if points < 1:
        raise ValueError("la curva de ganancia necesita al menos un punto")
    if math.ceil(round(1 / points * len(y), 9)) < 1:      # the first point, computed as the loop computes it
        raise ValueError(f"la curva de ganancia con {points} puntos y {len(y)} clientes deja puntos sin clientes: cada punto necesita al menos un cliente")
    churners = int(y.sum())
    if churners == 0:
        raise ValueError("la curva de ganancia necesita al menos una baja")
    captured = np.cumsum(y[_ranking(score)])
    n = len(y)
    rows = []
    for i in range(1, points + 1):
        k = math.ceil(round(i / points * n, 9))
        share = k / n
        rows.append((i, k, int(captured[k - 1]), share, captured[k - 1] / churners, (captured[k - 1] / churners) / share))
    return pd.DataFrame(rows, columns=list(GAIN_COLUMNS))


def top_share_capture(score: np.ndarray, y: np.ndarray, cut_ids: np.ndarray, share: float) -> tuple[int, int]:
    """``(churners captured, customers contacted)`` by the top ``ceil(share x n)`` of each cut by score, added over the cuts."""
    score, y = _check(score, y)
    cut_ids = np.asarray(cut_ids)
    if cut_ids.shape != y.shape:
        raise ValueError("cada fila necesita su corte")
    if not 0 < share <= 1:
        raise ValueError(f"la proporción debe estar en (0, 1], se recibió {share!r}")
    captured = contacted = 0
    for cut in pd.unique(cut_ids):
        rows = np.flatnonzero(cut_ids == cut)
        k = math.ceil(round(share * len(rows), 9))
        top = rows[_ranking(score[rows])[:k]]
        captured, contacted = captured + int(y[top].sum()), contacted + k
    return captured, contacted


def cost_sensitivity(p_v2: Mapping[str, np.ndarray], y_v2: np.ndarray, p_test: Mapping[str, np.ndarray] | None, y_test: np.ndarray | None,
                     view: SealedConfig) -> pd.DataFrame:
    """The net benefit of each method at each break-even of the declared range, one row per break-even, method and scope.

    For every ``b`` of ``break_even_grid`` the offer cost becomes ``b x rescue_rate x retained_value`` and, for each method of `p_v2` (the
    model and B*), the threshold is chosen on V2 (scope ``valid_v2``). When `p_test` is given, that threshold is applied to the test
    probabilities of the same method (scope ``test``), with its figures per 1,000 customers of the test. The test never chooses anything.
    """
    if (p_test is None) != (y_test is None):
        raise ValueError("los puntajes y las etiquetas de la prueba van juntos")
    if p_test is not None and set(p_test) != set(p_v2):
        raise ValueError("la prueba y V2 deben tener los mismos métodos")
    base = Costs.from_view(view)
    grid = threshold_grid(view.costs)
    rows = []
    for b in break_even_grid(view.costs):
        costs = base.at_break_even(float(b))
        for method, scores in p_v2.items():
            p, y = _check(scores, y_v2)
            t = choose_threshold(p, y, costs, grid)
            scopes = [(VALID_V2, p, y)] + ([(TEST, *_check(p_test[method], y_test))] if p_test is not None else [])
            for scope, p_scope, y_scope in scopes:
                contacted = p_scope >= t
                benefit = net_benefit(y_scope, contacted, costs)
                rows.append((float(b), method, scope, t, benefit, benefit / len(y_scope) * 1000, float(contacted.mean()), len(y_scope)))
    return pd.DataFrame(rows, columns=list(SENSITIVITY_COLUMNS))
