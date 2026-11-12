"""The evaluation of the frozen model against the baselines, the bootstrap by customer and the criteria C01-C10 (RF23, RF24, AC25; D18, D21;
requirements, section 8.1; plan, section 16). Adapted from project 03's ``evaluation.py``.

``evaluate_frame`` measures, on one block (V2 at the launch, the test once its windows have closed), the model and the baselines B0-B5 and B*:
AUC (ties by halves), PR-AUC, Brier, ECE, bias, the threshold (the model's sealed one; each baseline's chosen on V2 with its own calibrated
probability), the contacted share, precision, recall, the net benefit in total and per 1,000 customers, the capture and the lift at the top
shares of each cut, the ROC curve, the calibration by bin and the gain curve; the same by cut; the bootstrap of AUC(model) - AUC(B2) and
AUC(model) - AUC(B*) resampling **whole customers** (D21); and the sensitivity of the net benefit to the break-even (C09). A block with one
class is ``BlockLabelError`` before anything is measured (M07).

``evaluate_criteria`` and ``criteria_from_seal`` share ``_criteria_of``: the criteria are a function of the sealed numbers only, so the summary
after the seal rebuilds them from the seal (D20). A criterion that cannot be computed is ``passed = False`` with its reason; a tie never passes.
This module receives the sealed view, never the whole configuration (D19).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import rankdata
from sklearn.metrics import average_precision_score, roc_auc_score

from churnrisk.config import SealedConfig
from churnrisk.split import require_both_classes
from churnrisk.threshold import Costs, choose_on_v2, cost_sensitivity, gain_curve, net_benefit, threshold_grid, top_share_capture

MODEL = "model"
B_STAR = "b_star"
METHODS = ("model", "b0_all", "b1_recency", "b2_rfm", "b3_bgnbd", "b4_frequency", "b5_alive")
PROBABILISTIC = ("model", "b1_recency", "b2_rfm", "b3_bgnbd", "b4_frequency", "b5_alive")   # B0 contacts everyone: it has no probability
COMPARISONS = ("b2_rfm", B_STAR)
SEAL_DECIMALS = 6


class EvaluationError(RuntimeError):
    """The block cannot be evaluated as asked."""


# --- metrics --------------------------------------------------------------------------------------------------------------


def auc_score(y, score) -> float:
    """``roc_auc_score``: the ties counted by halves (the rules have few distinct values)."""
    return float(roc_auc_score(np.asarray(y), np.asarray(score, dtype="float64")))


def _bin_of(p: np.ndarray, bins: int) -> np.ndarray:
    return np.clip(np.floor(np.round(p * bins, 9)).astype("int64"), 0, bins - 1)


def calibration_table(p, y, bins: int) -> pd.DataFrame:
    """``bin`` (from 1), ``p_mean``, ``observed`` and ``rows`` of `bins` intervals of equal width in [0, 1]; an empty bin has no means."""
    p, y = np.asarray(p, dtype="float64"), np.asarray(y, dtype="float64")
    which = _bin_of(p, bins)
    rows = []
    for b in range(bins):
        mask = which == b
        n = int(mask.sum())
        rows.append((b + 1, float(p[mask].mean()) if n else None, float(y[mask].mean()) if n else None, n))
    return pd.DataFrame(rows, columns=["bin", "p_mean", "observed", "rows"])


def expected_calibration_error(p, y, bins: int) -> float:
    """``sum over the bins (n_b / N) x |mean p - observed rate|``, with `bins` intervals of equal width."""
    table = calibration_table(p, y, bins)
    filled = table[table["rows"] > 0]
    return float((filled["rows"] / filled["rows"].sum() * (filled["p_mean"] - filled["observed"]).abs()).sum())


def roc_table(y, score, points: int) -> pd.DataFrame:
    """The ROC curve at `points` false positive rates from 0 to 1: the largest true positive rate the curve reaches at each (a run of equal
    scores is a straight segment; a vertical one counts at its top)."""
    y, score = np.asarray(y), np.asarray(score, dtype="float64")
    order = np.argsort(-score, kind="stable")
    ys, ss = y[order], score[order]
    last = np.r_[np.flatnonzero(np.diff(ss)), len(ss) - 1]      # the end of each run of equal scores: a tie moves both rates at once
    tp, fp = np.cumsum(ys)[last], np.cumsum(1 - ys)[last]
    tpr, fpr = np.r_[0.0, tp / max(int(ys.sum()), 1)], np.r_[0.0, fp / max(int((1 - ys).sum()), 1)]
    grid = np.linspace(0.0, 1.0, points)
    # between two rates the curve is the segment of its neighbours; at a rate it reaches more than once (a vertical step), np.interp takes
    # the last point with that rate, the top of the step
    return pd.DataFrame({"point": np.arange(1, points + 1), "fpr": grid, "tpr": np.interp(grid, fpr, tpr)})


def method_metrics(y, score, probability, contacted, costs: Costs, cut_ids, *, threshold: float | None, bins: int,
                   shares: Sequence[float]) -> dict[str, float | None]:
    """The metrics of one method on one block. `score` orders the customers (AUC, PR-AUC, capture, lift); `probability` (None for B0) gives
    Brier, ECE and the bias; `contacted` says whom the method contacts at its threshold."""
    y = np.asarray(y).astype("int64")
    contacted = np.asarray(contacted, dtype=bool)
    n, churners = len(y), int(y.sum())
    out: dict[str, float | None] = {"rows": float(n), "churn_rate": float(y.mean()), "auc": auc_score(y, score),
                                    "pr_auc": float(average_precision_score(y, np.asarray(score, dtype="float64")))}
    if probability is None:
        out.update(brier=None, ece=None, mean_p=None, bias=None)
    else:
        p = np.asarray(probability, dtype="float64")
        out.update(brier=float(np.mean((p - y) ** 2)), ece=expected_calibration_error(p, y, bins), mean_p=float(p.mean()), bias=float(p.mean() - y.mean()))
    hits = int(y[contacted].sum())
    benefit = net_benefit(y, contacted, costs)
    out.update(threshold=threshold, contact_share=float(contacted.mean()), precision=float(hits / contacted.sum()) if contacted.any() else None,
               recall=float(hits / churners) if churners else None, nb_total=benefit, nb_per_1000=benefit / n * 1000)
    for share in shares:
        captured, k = top_share_capture(np.asarray(score, dtype="float64"), y, np.asarray(cut_ids), share)
        tag = f"{round(share * 100):d}"
        out[f"capture_{tag}"] = captured / churners if churners else None
        out[f"captured_{tag}"] = float(captured)
        out[f"lift_{tag}"] = (captured / churners) / (k / n) if churners else None
    return out


# --- the bootstrap by customer (D21) ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Bootstrap:
    """``AUC(a) - AUC(b)`` on the rows given and its 95 % interval over the resamples kept; a resample with one class is discarded and counted."""

    diff: float
    ci_low: float | None
    ci_high: float | None
    kept: int
    discarded: int


def _fast_auc(y: np.ndarray, score: np.ndarray) -> float:
    ranks = rankdata(score)
    positives = y == 1
    n1, n0 = int(positives.sum()), int((~positives).sum())
    return float((ranks[positives].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def cluster_bootstrap(y, s_a, s_b, customer_ids, n: int, seed: int) -> Bootstrap:
    """Resample whole customers with replacement `n` times (``numpy.random.default_rng(seed)``): each customer drawn brings all its rows, the
    same customers for both scores; the interval is the 2.5 and 97.5 percentiles of ``AUC(s_a) - AUC(s_b)`` (D21)."""
    y, s_a, s_b, customers = np.asarray(y).astype("int64"), np.asarray(s_a, dtype="float64"), np.asarray(s_b, dtype="float64"), np.asarray(customer_ids)
    if not (len(y) == len(s_a) == len(s_b) == len(customers)):
        raise EvaluationError("las etiquetas, los puntajes y los clientes deben tener el mismo largo")
    require_both_classes(y, "del remuestreo")
    unique, inverse = np.unique(customers, return_inverse=True)
    groups = [np.flatnonzero(inverse == g) for g in range(len(unique))]
    rng = np.random.default_rng(seed)
    diffs, discarded = [], 0
    for _ in range(n):
        rows = np.concatenate([groups[g] for g in rng.integers(0, len(groups), len(groups))])
        yy = y[rows]
        if yy.min() == yy.max():
            discarded += 1
            continue
        diffs.append(_fast_auc(yy, s_a[rows]) - _fast_auc(yy, s_b[rows]))
    diff = auc_score(y, s_a) - auc_score(y, s_b)
    if not diffs:
        return Bootstrap(diff, None, None, 0, discarded)
    low, high = np.percentile(diffs, [2.5, 97.5])
    return Bootstrap(diff, float(low), float(high), len(diffs), discarded)


# --- one block --------------------------------------------------------------------------------------------------------------


def block_data(conn, scope: str, bundle, view: SealedConfig) -> "BlockData":
    """The labelled rows of `scope` (``valid_v2`` or ``test``) with the model's risk and each baseline's score and calibrated probability. The
    labels come from ``split.labelled_rows``, the only reader of labels; on the test the model's risk is the one ``model_scores`` holds (each
    customer was scored once, at its cut), on V2 the frozen artifact predicts it."""
    from churnrisk.baselines import SCORED, baseline_scores, probabilities
    from churnrisk.features import build_matrix
    from churnrisk.model import predict_risk
    from churnrisk.schema import FEATURE_COLUMNS
    from churnrisk.split import labelled_rows

    if scope not in ("valid_v2", "test"):
        raise EvaluationError(f"alcance desconocido: {scope!r}; se evalúa valid_v2 o test")
    rows = labelled_rows(conn, [scope])
    if rows.empty:
        raise EvaluationError(f"el bloque {scope} no tiene filas con etiqueta: sus ventanas no cerraron")
    features = rows[list(FEATURE_COLUMNS)]
    frame = rows[["churned"]].copy()
    if scope == "test":
        stored = pd.read_sql_query("SELECT cut_date, customer_id, risk FROM model_scores", conn)
        stored["cut_date"] = [date.fromisoformat(v) for v in stored["cut_date"]]
        risk = stored.set_index(["cut_date", "customer_id"])["risk"].reindex(frame.index)
        if risk.isna().any():
            raise EvaluationError(f"{int(risk.isna().sum())} filas de la prueba no tienen puntaje: cada corte de prueba se puntúa en su corrida")
        frame[MODEL] = risk.to_numpy(float)
    else:
        model = bundle.model
        frame[MODEL] = predict_risk(model, build_matrix(features, model.feature_set, model.country_groups))
    scores = baseline_scores(features, bundle.bgnbd, view.label.horizon_days)
    probs = probabilities(bundle.baseline_calibrators, scores)
    for m in scores.columns:
        frame[f"score_{m}"] = scores[m].to_numpy(float)
    for m in SCORED:
        frame[f"p_{m}"] = probs[m].to_numpy(float)
    return BlockData(scope, frame, bundle.b_star)


@dataclass(frozen=True)
class BlockData:
    """The rows of one block (index ``(cut_date, customer_id)``): ``churned``, the model's risk (``model``), each baseline's score
    (``score_<method>``) and calibrated probability (``p_<method>``)."""

    scope: str
    frame: pd.DataFrame
    b_star: str


@dataclass
class EvaluationResult:
    scope: str
    b_star: str
    rows: int
    metrics: dict[str, dict[str, float | None]]
    per_cut: list[dict[str, Any]]
    bootstrap: dict[str, Bootstrap]
    gain: dict[str, pd.DataFrame]
    roc: dict[str, pd.DataFrame]
    calibration: dict[str, pd.DataFrame]
    sensitivity: pd.DataFrame
    thresholds: dict[str, float]
    extra: dict[str, Any] = field(default_factory=dict)


def _contacts(frame: pd.DataFrame, method: str, threshold: float | None) -> np.ndarray:
    if method == "b0_all":
        return np.ones(len(frame), dtype=bool)
    column = MODEL if method == MODEL else f"p_{method}"
    return frame[column].to_numpy() >= threshold


def baseline_thresholds(v2: BlockData, view: SealedConfig) -> dict[str, float]:
    """Each probabilistic baseline's threshold, chosen on V2 with its own calibrated probability by the model's procedure (C05, C09)."""
    costs, grid = Costs.from_view(view), threshold_grid(view.costs)
    frame = v2.frame.assign(block="valid_v2")
    return {m: choose_on_v2(frame, costs, grid, score=f"p_{m}").threshold for m in PROBABILISTIC if m != MODEL}


def evaluate_frame(block: BlockData, v2: BlockData, model_threshold: float, view: SealedConfig, n_resamples: int | None = None) -> EvaluationResult:
    """Every measure of the evaluation on `block`, with the thresholds chosen on `v2` (the model's is the sealed `model_threshold`)."""
    frame = block.frame
    y = frame["churned"].to_numpy().astype("int64")
    require_both_classes(y, block.scope)                    # M07: before anything is measured
    costs, ev = Costs.from_view(view), view.evaluation
    cut_ids = np.asarray([c.isoformat() for c in frame.index.get_level_values("cut_date")])
    customers = frame.index.get_level_values("customer_id").to_numpy()
    thresholds = {MODEL: float(model_threshold), **baseline_thresholds(v2, view)}
    metrics, gain, roc, calibration = {}, {}, {}, {}
    for m in METHODS:
        score = frame[MODEL if m == MODEL else f"score_{m}"].to_numpy(float)
        p = None if m not in PROBABILISTIC else frame[MODEL if m == MODEL else f"p_{m}"].to_numpy(float)
        t = thresholds.get(m)
        metrics[m] = method_metrics(y, score, p, _contacts(frame, m, t), costs, cut_ids, threshold=t, bins=ev.calibration_bins, shares=ev.top_shares)
        gain[m] = gain_curve(score, y, ev.gain_points)
        roc[m] = roc_table(y, score, ev.roc_points)
        if p is not None:
            calibration[m] = calibration_table(p, y, ev.calibration_bins)
    metrics[B_STAR] = dict(metrics[block.b_star])
    resamples = ev.bootstrap_resamples if n_resamples is None else n_resamples
    bootstrap = {other: cluster_bootstrap(y, frame[MODEL], frame[f"score_{block.b_star if other == B_STAR else other}"], customers, resamples,
                                          ev.bootstrap_seed) for other in COMPARISONS}
    per_cut = []
    for cut, rows in frame.groupby(level="cut_date", sort=True):
        yc = rows["churned"].to_numpy().astype("int64")
        entry: dict[str, Any] = {"cut": cut.isoformat(), "rows": len(rows), "churn_rate": float(yc.mean())}
        if yc.min() != yc.max():
            entry.update(auc_model=auc_score(yc, rows[MODEL]), auc_b2_rfm=auc_score(yc, rows["score_b2_rfm"]),
                         auc_b_star=auc_score(yc, rows[f"score_{block.b_star}"]))
            entry.update(diff_b2_rfm=entry["auc_model"] - entry["auc_b2_rfm"], diff_b_star=entry["auc_model"] - entry["auc_b_star"])
        else:
            entry.update(auc_model=None, auc_b2_rfm=None, auc_b_star=None, diff_b2_rfm=None, diff_b_star=None)
        per_cut.append(entry)
    v2y = v2.frame["churned"].to_numpy()
    p_v2 = {MODEL: v2.frame[MODEL].to_numpy(float), B_STAR: v2.frame[f"p_{block.b_star}"].to_numpy(float)}
    p_here = {MODEL: frame[MODEL].to_numpy(float), B_STAR: frame[f"p_{block.b_star}"].to_numpy(float)}
    same = block.scope == v2.scope
    sensitivity = cost_sensitivity(p_v2, v2y, None if same else p_here, None if same else y, view)
    return EvaluationResult(block.scope, block.b_star, len(frame), metrics, per_cut, bootstrap, gain, roc, calibration, sensitivity, thresholds)


# --- the criteria (requirements, section 8.1) ----------------------------------------------------------------------------

CRITERIA: dict[str, tuple[str, str, str, str]] = {   # id: name, threshold, seen by the research, seen by the planner
    "C01": ("Discriminación frente a RFM", "AUC(modelo) > AUC(B2)", "sí", "en parte"),
    "C02": ("Mejora fuera del ruido frente a RFM", "límite inferior del intervalo del 95 % de AUC(modelo) − AUC(B2) > 0", "sí", "no"),
    "C03": ("Mejora fuera del ruido frente a la base más fuerte", "límite inferior del intervalo del 95 % de AUC(modelo) − AUC(B*) > 0", "en parte", "en parte"),
    "C04": ("Captura en el 10 % superior", "bajas en el 10 % de mayor riesgo del modelo > las del 10 % de B*", "en parte", "no"),
    "C05": ("Beneficio neto frente a la base más fuerte", "BN(modelo, t*) > BN(B*, t*_B*)", "no", "no"),
    "C06": ("Conviene actuar con el modelo", "BN(modelo, t*) > máx(BN(contactar a todos), 0)", "no", "no"),
    "C07": ("Calibración en la prueba", "ECE ≤ {ece} y |sesgo| ≤ {bias}", "no", "no"),
    "C08": ("Brier frente a la base más fuerte", "Brier(modelo) < Brier(B*)", "no", "no"),
    "C09": ("Sensibilidad a los costos", "BN(modelo) ≥ BN(B*) en cada punto de equilibrio de {low} a {high}", "no", "no"),
    "C10": ("Por corte y sensibilidades (informativo)", "sin umbral: que esté escrito y sea consistente", "no", "solo las tasas de entrenamiento"),
}


def es(value: float | None, digits: int = 3) -> str:
    """A number as the Spanish text shows it: a comma for the decimals and a point for the thousands."""
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return "sin dato"
    text = f"{value:,.{digits}f}"
    return text.replace(",", "§").replace(".", ",").replace("§", ".").replace("-", "−")


@dataclass(frozen=True)
class Criterion:
    criterion_id: str
    name_es: str
    value: float | None
    baseline_value: float | None
    ci_low: float | None
    ci_high: float | None
    threshold_es: str
    passed: bool | None
    seen_by_research: str
    seen_by_planner: str
    verdict_es: str

    def seal_entry(self) -> dict[str, Any]:
        return {"id": self.criterion_id, "value": self.value, "baseline_value": self.baseline_value, "ci_low": self.ci_low, "ci_high": self.ci_high,
                "passed": self.passed, "verdict_es": self.verdict_es}


def _criterion(cid: str, value, baseline, passed: bool | None, verdict: str, threshold_es: str, ci=(None, None)) -> Criterion:
    name, _threshold, research, planner = CRITERIA[cid]
    return Criterion(cid, name, value, baseline, ci[0], ci[1], threshold_es, passed, research, planner, verdict)


def _beats(a: float | None, b: float | None, *, lower_is_better: bool = False) -> bool:
    if a is None or b is None:
        return False
    return a < b if lower_is_better else a > b             # a tie never passes


def _criteria_of(metrics: Mapping[str, Mapping[str, Any]], per_cut: Sequence[Mapping[str, Any]], costs_document: Mapping[str, Any],
                 criteria_document: Mapping[str, Any]) -> list[Criterion]:
    """C01-C10 from the sealed numbers only: ``metrics`` (by method, plus ``bootstrap`` and ``cost_sensitivity``), the per-cut figures and the
    sealed ``[costs]`` and ``[criteria]`` (the range of C09 comes from the sealed view, not from a constant)."""
    model, b2, b_star = metrics[MODEL], metrics["b2_rfm"], metrics[B_STAR]
    boot = metrics["bootstrap"]
    sens = metrics["cost_sensitivity"]
    out: list[Criterion] = []
    a, b = model["auc"], b2["auc"]
    ok = _beats(a, b)
    out.append(_criterion("C01", a, b, ok, f"El modelo {'supera' if ok else 'no supera'} a RFM en AUC: {es(a)} frente a {es(b)}.", CRITERIA["C01"][1]))
    for cid, key, who in (("C02", "b2_rfm", "a RFM"), ("C03", "b_star", "a la base más fuerte")):
        diff, low, high = boot[f"{key}.diff"], boot[f"{key}.ci_low"], boot[f"{key}.ci_high"]
        ok = low is not None and low > 0
        verdict = (f"El modelo {'supera' if ok else 'no supera'} {who} fuera del ruido: la diferencia de AUC es {es(diff, 2)}, con un intervalo del "
                   f"95 % de {es(low, 2)} a {es(high, 2)}.")
        out.append(_criterion(cid, diff, None, ok, verdict, CRITERIA[cid][1], (low, high)))
    a, b = model.get("captured_10"), b_star.get("captured_10")
    ok = _beats(a, b)
    out.append(_criterion("C04", a, b, ok, f"En el 10 % de mayor riesgo, el modelo {'capta más' if ok else 'no capta más'} bajas que la base más "
                                          f"fuerte: {es(a, 0)} frente a {es(b, 0)}.", CRITERIA["C04"][1]))
    a, b = model["nb_per_1000"], b_star["nb_per_1000"]
    ok = _beats(a, b)
    out.append(_criterion("C05", a, b, ok, f"Con los costos supuestos, el modelo {'deja más' if ok else 'no deja más'} beneficio neto que la base más "
                                          f"fuerte con su propio umbral: {es(a, 1)} u. frente a {es(b, 1)} u. por cada 1.000 clientes.", CRITERIA["C05"][1]))
    contact_all = metrics["b0_all"]["nb_per_1000"]
    floor = max(contact_all, 0.0)
    ok = _beats(a, floor)
    out.append(_criterion("C06", a, floor, ok, f"El modelo {'supera' if ok else 'no supera'} a contactar a todos y a no contactar a nadie: {es(a, 1)} u. por "
                                               f"cada 1.000 clientes frente a {es(floor, 1)}.", CRITERIA["C06"][1]))
    max_ece, max_bias = criteria_document["c07_max_ece"], criteria_document["c07_max_bias"]
    ece, bias = model["ece"], model["bias"]
    ok = ece is not None and bias is not None and ece <= max_ece and abs(bias) <= max_bias
    out.append(_criterion("C07", ece, bias, ok, f"La calibración en la prueba {'cumple' if ok else 'no cumple'}: ECE {es(ece)} y sesgo {es(bias)}.",
                          CRITERIA["C07"][1].format(ece=es(max_ece, 2), bias=es(max_bias, 2))))
    a, b = model["brier"], b_star["brier"]
    ok = _beats(a, b, lower_is_better=True)
    out.append(_criterion("C08", a, b, ok, f"El Brier del modelo {'es menor' if ok else 'no es menor'} que el de la base más fuerte: {es(a, 4)} frente a "
                                          f"{es(b, 4)}.", CRITERIA["C08"][1]))
    low, high, step = costs_document["sensitivity_min"], costs_document["sensitivity_max"], costs_document["sensitivity_step"]
    count = int(np.floor((high - low) / step + 1e-9)) + 1
    points = [f"{round(low + step * i, 10):.2f}" for i in range(count)]
    missing = [b for b in points if f"{b}.model" not in sens or f"{b}.b_star" not in sens]
    if missing:
        out.append(_criterion("C09", None, None, False, f"No se puede calcular: faltan los puntos de equilibrio {', '.join(missing)}.", CRITERIA["C09"][1]))
    else:
        kept = sum(sens[f"{b}.model"] >= sens[f"{b}.b_star"] - 1e-9 for b in points)
        ok = kept == len(points)
        out.append(_criterion("C09", float(kept), float(len(points)), ok, f"El modelo {'deja' if ok else 'no deja'} al menos el beneficio de la base "
                              f"más fuerte en cada punto de equilibrio: en {kept} de los {len(points)} de {es(low, 2)} a {es(high, 2)}.",
                              CRITERIA["C09"][1].format(low=es(low, 2), high=es(high, 2))))
    cuts = "; ".join(f"{c['cut']}: AUC {es(c.get('auc_model'))}, tasa de bajas {es(c['churn_rate'])}, diferencia con B2 {es(c.get('diff_b2_rfm'), 2)} y con "
                     f"B* {es(c.get('diff_b_star'), 2)}" for c in per_cut)
    out.append(_criterion("C10", None, None, None, f"Por corte de prueba: {cuts}.", CRITERIA["C10"][1]))
    return out


def seal_metrics(result: EvaluationResult) -> dict[str, dict[str, float | None]]:
    """The numbers the criteria are made of, as the seal stores them: the metrics by method, the bootstrap and the cost sensitivity of the
    test (net benefit per 1,000 customers, by break-even and method)."""
    out = {m: dict(values) for m, values in result.metrics.items()}
    out["bootstrap"] = {f"{k}.{f}": getattr(b, f) for k, b in result.bootstrap.items() for f in ("diff", "ci_low", "ci_high", "kept", "discarded")}
    out["bootstrap"] = {k: (float(v) if v is not None else None) for k, v in out["bootstrap"].items()}
    test = result.sensitivity[result.sensitivity["scope"] == result.scope]
    out["cost_sensitivity"] = {f"{b:.2f}.{m}": float(v) for b, m, v in zip(test["break_even"], test["method"], test["net_benefit_per_1000"], strict=True)}
    return out


def evaluate_criteria(result: EvaluationResult, view: SealedConfig) -> list[Criterion]:
    from churnrisk.registry import sealed_document

    document = sealed_document(view)
    return _criteria_of(seal_metrics(result), result.per_cut, document["costs"], document["criteria"])


def _rounded(value):
    if isinstance(value, float):
        return round(value, SEAL_DECIMALS)
    if isinstance(value, dict):
        return {k: _rounded(v) for k, v in value.items()}
    return value


def criteria_from_seal(seal: Mapping[str, Any]) -> list[Criterion]:
    """C01-C10 rebuilt from the test part of the seal with ``_criteria_of``; each must give back its own entry of the seal to 6 decimals, or the
    seal is not taken (``SealError``): a seal the code no longer knows how to rebuild is never published (D20)."""
    from churnrisk.registry import SealError

    test, launch = seal.get("test"), seal.get("launch")
    if not test or not launch:
        raise SealError("el sello no tiene la parte de la prueba: no hay criterios sellados")
    rebuilt = _criteria_of(test["metrics"], test["per_cut"], launch["sealed_config"]["costs"], launch["sealed_config"]["criteria"])
    sealed = {entry["id"]: entry for entry in test["criteria"]}
    for criterion in rebuilt:
        if _rounded(criterion.seal_entry()) != _rounded(sealed.get(criterion.criterion_id)):
            raise SealError(f"el criterio {criterion.criterion_id} del sello no se reconstruye desde sus cifras: lo sellado no se toma (docs/runbook.md, R7)")
    return rebuilt

