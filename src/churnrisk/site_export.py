"""The five small JSON files that the personal site copies (RF27, AC29, AC42; plan, section 21; D27, D73). Adapted from project 03's
``site_export.py`` (its D77 and D94).

``export_site`` writes ``summary.json``, ``validation_rules.json``, ``label.json``, ``algorithms.json`` and ``retention.json`` to the site folder
from the star model (the ``star_*`` tables that ``export.build_powerbi_marts`` built, the very rows the Parquet files hold, so a figure on the
site is the figure in the report), from the summary of the run (``reporting.build_summary``, which takes the sealed criteria from the seal when
the warehouse has none) and from the validation of each run. Nothing identifies a customer: no file has a customer number, an invoice number
or a key that names either, and the examples follow the rule of D27.

The files are a contract that another repository consumes (item 3 of the risk list): a change of shape is a change of
``tests/contract/test_site_export.py``. Floats are rounded to what the site shows; every file is ``json.dumps(obj, ensure_ascii=False,
sort_keys=True, indent=1)`` with a final newline, and the five together stay under ``[site] max_total_bytes``.

Small cells. The breakdowns by cut and band and by cut and country come from U20's marts with their primary and secondary suppression as they
are (the site never decides them again). The two breakdowns the marts leave whole, the follow-up of each cut (D68 leaves it to the site) and
the calibration bins of the test, go through ``protect``: a cell of fewer than ``min_cell_customers`` customers has its values ``null`` and
``"suppressed": true``, and a breakdown whose total is published that would hide exactly one cell hides its smallest shown cell too (the rule
of the marts, project 03 D77; a test checks that it gives the marts' ``suppressed`` on their own counts).

The five files are one export: each is replaced atomically and ``manifest.json``, written last, names each with its size and SHA-256. A failure
between two replacements leaves a folder that ``verify_site`` refuses; a reader takes the files through ``read_site``. Until the test is sealed
with this configuration, every result of the test is empty or ``null``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd

from churnrisk.config import PipelineConfig
from churnrisk.dashboard.semantic_model import FEATURES_ES, METHODS_ES
from churnrisk.export import ExportMeta, prefer_sealed
from churnrisk.files import write_atomic
from churnrisk.reporting import build_summary
from churnrisk.sensitivity import VARIANTS_ES
from churnrisk.split import BLOCKS_ES
from churnrisk.validate import RULES, Aggregation

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
SITE_FILES = ("summary.json", "validation_rules.json", "label.json", "algorithms.json", "retention.json")
MANIFEST_FILE = "manifest.json"
STATUS_EN = {"pasa": "pass", "falla": "fail", "advierte": "warn"}
WORST_STATUS_FIRST = ("falla", "advierte", "pasa")
EXAMPLE_LABELS = ("Cliente A", "Cliente B", "Cliente C", "Cliente D", "Cliente E")
BAND_ES = {"rec_days": "recencia", "freq_365": "frecuencia", "mon_365": "gasto"}
# Every table of the star model the export reads: the one list ``_require_star`` checks before anything is built (a test compares it with
# the tables the queries of this module name).
REQUIRED_STAR = (
    "star_dim_country", "star_dim_cut", "star_dim_model", "star_fact_calibration", "star_fact_cost_sensitivity", "star_fact_cut_country",
    "star_fact_gain_curve", "star_fact_importance", "star_fact_label_definition", "star_fact_leakage", "star_fact_method_metrics",
    "star_fact_reason_summary", "star_fact_selection", "star_fact_sensitivity", "star_fact_silence_return", "star_fact_tracking",
)


class SiteExportError(RuntimeError):
    """The site files cannot be written from this warehouse; nothing was replaced."""


class SiteSetError(FileNotFoundError):
    """The files of a site folder are not one export: one is missing or is not the file ``manifest.json`` names, or the manifest is."""


# --- values ---------------------------------------------------------------------------------------------------------------------


def _num(value: Any, decimals: int) -> float | None:
    if value is None or (isinstance(value, float) and math.isnan(value)) or pd.isna(value):
        return None
    return round(float(value), decimals)


def _int(value: Any) -> int | None:
    return None if value is None or pd.isna(value) else int(value)


def _day(key: Any) -> str:
    text = str(int(key))
    return f"{text[:4]}-{text[4:6]}-{text[6:]}"


def _query(conn: sqlite3.Connection, sql: str, params: tuple | dict = ()) -> pd.DataFrame:
    return pd.read_sql_query(sql, conn, params=params)


def _hidden(count: Any, minimum: int) -> bool:
    """A cell of fewer customers than the minimum, or with no count, is hidden."""
    return count is None or pd.isna(count) or int(count) < max(int(minimum), 1)


def protect(cells: list[dict[str, Any]], counts: list[Any], labels: tuple[str, ...], minimum: int, *, total_published: bool = True) -> list[dict[str, Any]]:
    """The cells of one breakdown with the hidden ones emptied (only `labels` stay) and ``"suppressed": true``: the primary rule (fewer than
    `minimum` customers) and, when the breakdown's total is published, the secondary one (one hidden cell hides the smallest shown cell too,
    the first on a tie), so that no hidden cell is the total minus the shown ones. It is the rule of the marts of U20 (D68, project 03 D77)."""
    hidden = [_hidden(n, minimum) for n in counts]
    if total_published and sum(hidden) == 1:
        shown = [(int(n), i) for i, (n, h) in enumerate(zip(counts, hidden, strict=True)) if not h]
        if shown:
            hidden[min(shown)[1]] = True
    return [{**{k: (v if k in labels else None) for k, v in cell.items()}, "suppressed": True} if h else {**cell, "suppressed": False}
            for cell, h in zip(cells, hidden, strict=True)]


def _require_star(conn: sqlite3.Connection) -> None:
    present = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    missing = [t for t in REQUIRED_STAR if t not in present]
    if missing:
        raise SiteExportError(f"faltan las tablas del modelo estrella {missing}: la tarea export las construye antes de escribir el sitio")


def _header(meta: ExportMeta) -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "run_key": meta.run_key, "as_of": meta.as_of.isoformat(), "source_sha256": meta.source_sha256,
            "attribution": meta.attribution}


# --- summary.json -------------------------------------------------------------------------------------------------------------------


def _loaded_rule_rows(conn: sqlite3.Connection) -> pd.DataFrame:
    """The rule results of the runs whose delivery is loaded, with each run's calculation date."""
    return _query(conn, "SELECT v.rule_id, v.passed, v.severity, v.rows_affected, v.customers_affected, v.value_gbp, d.as_of_date FROM validation_results AS v "
                        "JOIN deliveries AS d ON d.run_key = v.run_key AND d.status = 'loaded' ORDER BY d.as_of_date, v.rule_id")


def _aggregated(rows: pd.DataFrame, rule_id: str) -> pd.DataFrame:
    """The rows of `rule_id` that its ``aggregation`` counts (plan, section 6): ``source`` and ``latest`` read once, from the latest loaded run
    (a cumulative count summed over runs would count the earlier months again; project 03, D94), ``per_run`` every loaded run."""
    mine = rows[rows["rule_id"] == rule_id]
    if RULES[rule_id].aggregation in (Aggregation.SOURCE, Aggregation.LATEST) and len(mine):
        mine = mine[mine["as_of_date"] == mine["as_of_date"].max()]
    return mine


def _overlap_removed(rows: pd.DataFrame) -> int | None:
    """The overlap copies that rule I03 recorded, aggregated as I03 says; None if no loaded run recorded it. ``summary.json`` and
    ``validation_rules.json`` both publish ``lines_raw`` from this one figure."""
    mine = _aggregated(rows, "I03")
    return None if mine.empty else int(mine["rows_affected"].sum())


def _headline_counts(conn: sqlite3.Connection) -> dict[str, Any]:
    base, customers, countries, start, end = conn.execute(
        "SELECT COUNT(*), COUNT(DISTINCT customer_id), COUNT(DISTINCT CASE WHEN customer_id IS NOT NULL THEN country END), MIN(invoice_date), "
        "MAX(invoice_date) FROM raw_lines").fetchone()
    positive, guest_lines, guest_positive, cancelled = conn.execute(
        "SELECT COALESCE(SUM(CASE WHEN quantity * price > 0 THEN quantity * price END), 0), COALESCE(SUM(customer_id IS NULL), 0), "
        "COALESCE(SUM(CASE WHEN customer_id IS NULL AND quantity * price > 0 THEN quantity * price END), 0), "
        "COALESCE(SUM(CASE WHEN customer_id IS NOT NULL AND invoice LIKE 'C%' THEN -quantity * price END), 0) FROM raw_lines").fetchone()
    overlap = _overlap_removed(_loaded_rule_rows(conn))
    return {
        "lines_raw": None if overlap is None else int(base) + overlap, "lines_base": int(base), "customers_with_purchase": int(customers),
        "countries_with_customers": int(countries), "guest_lines_share": _num(guest_lines / base, 3) if base else None,
        "guest_value_share": _num(guest_positive / positive, 3) if positive else None, "cancelled_value_share": _num(cancelled / positive, 3) if positive else None,
        "period_start": start, "period_end": end,
    }


def _model_row(conn: sqlite3.Connection) -> pd.Series:
    rows = _query(conn, "SELECT * FROM star_dim_model")
    if rows.empty:
        raise SiteExportError("no hay un modelo en el modelo estrella: el sitio se escribe después del lanzamiento")
    return rows.iloc[0]


def _summary(conn: sqlite3.Connection, cfg: PipelineConfig, meta: ExportMeta) -> dict[str, Any]:
    summary = build_summary(conn, cfg, run_key=meta.run_key, as_of=meta.as_of, source_sha256=meta.source_sha256)
    model = _model_row(conn)
    cuts = _query(conn, "SELECT block, active_customers, churn_rate FROM star_dim_cut")
    count = {b: int((cuts["block"] == b).sum()) for b in ("train", "valid_v1", "valid_v2", "test")}
    sealed = summary["evaluation_status"] == "sealed"
    test = summary.get("test") or {}

    def metric(method: str, name: str, decimals: int) -> float | None:
        return _num(test.get(method, {}).get(name), decimals) if sealed else None

    train = _query(conn, "SELECT AVG(l.churned) AS rate FROM cut_labels AS l JOIN cut_blocks AS b ON b.cut_date = l.cut_date WHERE b.block = 'train'")
    status = conn.execute("SELECT status FROM pipeline_runs WHERE run_key = ?", (meta.run_key,)).fetchone()
    headline = {
        **_headline_counts(conn), "n_days": cfg.label.horizon_days, "m_days": cfg.label.active_days, "train_cuts": count["train"],
        "valid_cuts": count["valid_v1"] + count["valid_v2"], "test_cuts": count["test"], "test_rows": int(cuts.loc[cuts["block"] == "test", "active_customers"].sum()),
        "train_churn_rate": _num(train["rate"].iloc[0], 3), "test_churn_rate": metric("model", "churn_rate", 3),
        "threshold": _num(model["threshold"], 2), "break_even": _num(model["break_even"], 3), "offer_cost": _num(model["offer_cost"], 2),
        "rescue_rate": _num(model["rescue_rate"], 2), "retained_value": _num(model["retained_value"], 2), "b_star": str(model["b_star"]),
        "auc": {"model": metric("model", "auc", 3), "b2_rfm": metric("b2_rfm", "auc", 3), "b_star": metric("b_star", "auc", 3)},
        "capture_10": {"model": metric("model", "capture_10", 3), "b_star": metric("b_star", "capture_10", 3)},
        "net_benefit_per_1000": {"model": metric("model", "nb_per_1000", 1), "b_star": metric("b_star", "nb_per_1000", 1), "contact_all": metric("b0_all", "nb_per_1000", 1)},
    }
    criteria = [{"id": c["criterion_id"], "name_es": c["name_es"], "passed": c["passed"], "value": _num(c["value"], 4), "baseline_value": _num(c["baseline_value"], 4),
                 "ci_low": _num(c["ci_low"], 4), "ci_high": _num(c["ci_high"], 4), "threshold_es": c["threshold_es"], "seen_by_research": c["seen_by_research"],
                 "seen_by_planner": c["seen_by_planner"], "verdict_es": c["verdict_es"]} for c in summary["criteria"]]
    out = {"status": "running" if status is None else status[0], "evaluation_status": summary["evaluation_status"], "headline": headline, "criteria": criteria,
           "seal": summary.get("seal")}
    if summary.get("sealed_from"):
        out["sealed_from"] = summary["sealed_from"]
    return out


# --- validation_rules.json -----------------------------------------------------------------------------------------------------------


def _validation(conn: sqlite3.Connection) -> dict[str, Any]:
    """The rules in the order of the report, each aggregated over the loaded runs as its ``aggregation`` says (plan, section 6): ``source`` and
    ``latest`` read once, from the latest loaded run (a cumulative count summed over runs would count the earlier months again; project 03,
    D94), ``per_run`` summed over the loaded runs. A rule no loaded run recorded is ``not_evaluated``."""
    rows = _loaded_rule_rows(conn)
    rules = []
    for rule_id, rule in RULES.items():
        mine = _aggregated(rows, rule_id)
        status_es = ["pasa" if bool(p) else ("falla" if s == "blocking" else "advierte") for p, s in zip(mine["passed"], mine["severity"], strict=True)]
        status = "not_evaluated" if mine.empty else STATUS_EN[next(s for s in WORST_STATUS_FIRST if s in status_es)]
        rules.append({"rule_id": rule_id, "name_es": rule.name_es, "severity": rule.severity.value, "scope": rule.scope, "aggregation": rule.aggregation.value,
                      "status": status, "rows": int(mine["rows_affected"].sum()), "customers": int(mine["customers_affected"].sum()),
                      "value_gbp": _num(mine["value_gbp"].sum(), 2) if len(mine) else 0.0})
    by_id = {r["rule_id"]: r for r in rules}
    base = int(conn.execute("SELECT COUNT(*) FROM raw_lines").fetchone()[0])
    loaded, rejected = conn.execute("SELECT COALESCE(SUM(status = 'loaded'), 0), COALESCE(SUM(status = 'rejected'), 0) FROM deliveries").fetchone()
    overlap = _overlap_removed(rows)
    totals = {"lines_raw": None if overlap is None else base + overlap, "lines_base": base, "overlap_removed": overlap, "guest_lines": by_id["V20"]["rows"],
              "cancellation_lines": by_id["V21"]["rows"], "deliveries_loaded": int(loaded), "deliveries_rejected": int(rejected)}
    return {"rules": rules, "totals": totals}


# --- label.json --------------------------------------------------------------------------------------------------------------------


def _label(conn: sqlite3.Connection, cfg: PipelineConfig, headline: dict[str, Any]) -> dict[str, Any]:
    minimum = cfg.site.min_cell_customers
    cuts = _query(conn, "SELECT cut_key, block, is_censored, active_customers, churn_rate FROM star_dim_cut ORDER BY cut_key")
    rates = []
    for r in cuts.itertuples():
        hidden = _hidden(r.active_customers, minimum)
        rates.append({"cut": _day(r.cut_key), "block": r.block, "customers": None if hidden else int(r.active_customers),
                      "churn_rate": None if hidden or bool(r.is_censored) else _num(r.churn_rate, 3), "suppressed": hidden})
    n_by_m = [{"n": int(r.n), "m": int(r.m), "churn_rate": _num(r.churn_rate, 3)} for r in _query(conn, "SELECT * FROM star_fact_label_definition ORDER BY n, m").itertuples()]
    silence = [{"n": int(r.n), "silences": int(r.silences), "return_share": _num(r.return_share, 3)}
               for r in _query(conn, "SELECT * FROM star_fact_silence_return ORDER BY n").itertuples()]
    leakage = _query(conn, "SELECT variable, variable_es, auc_valid_v2, note_es FROM star_fact_leakage ORDER BY variable")
    control = leakage[leakage["variable"] != "f1"]
    f1 = leakage[leakage["variable"] == "f1"]
    n, m = cfg.label.horizon_days, cfg.label.active_days
    return {
        "rule": {"n_days": n, "m_days": m, "text_es": f"Un cliente activo en los {m} días anteriores al corte se fue si no tiene ninguna compra neta en los {n} días "
                                                  "desde el corte. La baja no está en los datos: se define así."},
        "rates_by_cut": rates, "n_by_m": n_by_m, "silence_return": silence,
        "leakage": {"control_es": None if control.empty else str(control["variable_es"].iloc[0]), "auc_control_v2": None if control.empty else _num(control["auc_valid_v2"].iloc[0], 3),
                    "auc_f1_v2": None if f1.empty else _num(f1["auc_valid_v2"].iloc[0], 3)},
        "guests": {"lines_share": headline["guest_lines_share"], "value_share": headline["guest_value_share"]},
    }


# --- algorithms.json ----------------------------------------------------------------------------------------------------------------


def _metrics_of(conn: sqlite3.Connection, scope: str, sealed: bool) -> pd.DataFrame:
    frame = prefer_sealed(_query(conn, "SELECT * FROM star_fact_method_metrics WHERE scope = ?", (scope,)))
    return frame if scope != "test" or sealed else frame.iloc[0:0]


def _examples(conn: sqlite3.Connection, cfg: PipelineConfig, sealed: bool) -> list[dict[str, Any]]:
    """The rule of D27: in the last test cut, after the seal, for each quintile of the model's risk (lowest first), the customer with the
    lower-median risk (ties by the internal order of the rows, never published). It exists only if at least ``min_cell_customers`` customers
    of the cut share its quintile, its outcome and whether it was contacted; then each detail, in the order of the table, is published only
    while the customers sharing it and everything published before it are still that many, and is ``null`` otherwise. Never its number, its
    country, its exact values or its SHAP values."""
    if not sealed:
        return []
    last = conn.execute("SELECT MAX(cut_date) FROM cut_blocks WHERE block = 'test'").fetchone()[0]
    rows = _query(conn, "SELECT s.customer_id, s.risk, s.is_contact, l.churned, f.rec_days, f.freq_365, f.mon_365 FROM model_scores AS s "
                        "JOIN cut_labels AS l ON l.cut_date = s.cut_date AND l.customer_id = s.customer_id "
                        "JOIN cut_features AS f ON f.cut_date = s.cut_date AND f.customer_id = s.customer_id WHERE s.cut_date = ? ORDER BY s.rowid", (last,))
    if rows.empty:
        return []
    reasons = _query(conn, "SELECT customer_id, rank, feature FROM score_reasons WHERE cut_date = ?", (last,)).pivot(index="customer_id", columns="rank", values="feature")
    for rank in (1, 2, 3):
        rows[f"reason_{rank}"] = rows["customer_id"].map(reasons[rank]) if rank in reasons.columns else None
    minimum = max(cfg.site.min_cell_customers, 1)
    rows["quintile"] = pd.qcut(rows["risk"].rank(method="first"), 5, labels=False) + 1
    for column in BAND_ES:
        rows[f"{column}_band"] = pd.qcut(rows[column].rank(method="first"), 5, labels=False) + 1
    rows["risk_shown"] = rows["risk"].round(2)
    rows["outcome"] = rows["churned"].map({1: "se fue", 0: "volvió"})
    out = []
    for quintile in range(1, 6):
        cell = rows[rows["quintile"] == quintile].sort_values("risk", kind="stable")
        if cell.empty:
            continue
        r = cell.iloc[(len(cell) - 1) // 2]
        same = (rows["quintile"] == quintile) & (rows["outcome"] == r["outcome"]) & (rows["is_contact"] == r["is_contact"])
        if int(same.sum()) < minimum:
            continue
        details: dict[str, Any] = {}
        for name in ("risk_shown", "reason_1", "reason_2", "reason_3", "rec_days_band", "freq_365_band", "mon_365_band"):
            narrower = same & (rows[name] == r[name])
            if pd.notna(r[name]) and int(narrower.sum()) >= minimum:
                same, details[name] = narrower, r[name]
            else:
                details[name] = None
        band = {c: (None if details[f"{c}_band"] is None else f"quintil {int(details[f'{c}_band'])} de 5 de {BAND_ES[c]} en el corte") for c in BAND_ES}
        out.append({
            "label": EXAMPLE_LABELS[len(out)], "risk_quintile": quintile, "outcome": r["outcome"], "contacted": bool(r["is_contact"]),
            "risk": None if details["risk_shown"] is None else _num(details["risk_shown"], 2),
            **{f"reason_{k}_es": None if details[f"reason_{k}"] is None else FEATURES_ES[details[f"reason_{k}"]][0] for k in (1, 2, 3)},
            "recency_band_es": band["rec_days"], "frequency_band_es": band["freq_365"], "spend_band_es": band["mon_365"],
        })
    return out


def _calibration(conn: sqlite3.Connection, cfg: PipelineConfig, sealed: bool) -> list[dict[str, Any]]:
    if not sealed:
        return []
    frame = prefer_sealed(_query(conn, "SELECT * FROM star_fact_calibration WHERE scope = 'test' AND method_key = 'model' ORDER BY point"))
    cells = [{"bin": int(r.point), "p_mean": _num(r.p_mean, 3), "observed": _num(r.observed, 3), "rows": _int(r.rows)} for r in frame.itertuples()]
    return protect(cells, [c["rows"] for c in cells], ("bin",), cfg.site.min_cell_customers)


def _algorithms(conn: sqlite3.Connection, cfg: PipelineConfig, sealed: bool, seal_variants: dict[str, dict]) -> dict[str, Any]:
    model = _model_row(conn)
    b_star = str(model["b_star"])
    cuts = _query(conn, "SELECT cut_key, block, block_es, active_customers, churn_rate FROM star_dim_cut ORDER BY cut_key")
    split = []
    for block in [b for b in ("train", "valid_v1", "valid_v2", "test") if b in set(cuts["block"])]:
        part = cuts[cuts["block"] == block]
        known = part[part["churn_rate"].notna()]
        rate = None if known.empty else float((known["churn_rate"] * known["active_customers"]).sum() / known["active_customers"].sum())
        split.append({"block": block, "label_es": BLOCKS_ES[block], "cuts": [_day(k) for k in part["cut_key"]], "rows": int(part["active_customers"].sum()),
                      "churn_rate": _num(rate, 3)})
    selection = [{"feature_set": r.feature_set, "learning_rate": float(r.learning_rate), "max_leaf_nodes": int(r.max_leaf_nodes), "min_samples_leaf": int(r.min_samples_leaf),
                  "log_loss_v1": _num(r.log_loss_v1, 4), "chosen": bool(r.chosen)} for r in _query(conn, "SELECT * FROM star_fact_selection").itertuples()]
    v2 = _metrics_of(conn, "valid_v2", sealed)
    b_star_v2 = v2[v2["method_key"] == b_star]
    methods = []
    for scope in ("valid_v2", "test"):
        for r in _metrics_of(conn, scope, sealed).sort_values("method_key").itertuples():
            methods.append({"method": r.method_key, "label_es": METHODS_ES.get(r.method_key, r.method_key), "scope": scope, "auc": _num(r.auc, 3), "pr_auc": _num(r.pr_auc, 3),
                            "brier": _num(r.brier, 4), "capture_10": _num(r.capture_10, 3), "lift_10": _num(r.lift_10, 3), "capture_20": _num(r.capture_20, 3),
                            "lift_20": _num(r.lift_20, 3), "net_benefit_per_1000": _num(r.nb_per_1000, 1)})
    gain = []
    if sealed:
        curves = prefer_sealed(_query(conn, "SELECT * FROM star_fact_gain_curve WHERE scope = 'test' ORDER BY method_key, point"))
        for method in dict.fromkeys(("model", "b2_rfm", b_star)):
            for r in curves[curves["method_key"] == method].head(cfg.evaluation.gain_points).itertuples():
                gain.append({"method": method, "share_contacted": _num(r.share_contacted, 3), "share_captured": _num(r.share_captured, 3)})
    costs = prefer_sealed(_query(conn, "SELECT * FROM star_fact_cost_sensitivity WHERE scope = 'valid_v2' ORDER BY break_even"))
    cost_curve = []
    for be in sorted(set(costs["break_even"])):
        at = costs[costs["break_even"] == be].set_index("method_key")
        cost_curve.append({"break_even": _num(be, 2), "threshold_model": _num(at["threshold"].get("model"), 2), "nb_model": _num(at["nb_per_1000"].get("model"), 1),
                           "nb_b_star": _num(at["nb_per_1000"].get(b_star), 1), "contact_share_model": _num(at["contact_share"].get("model"), 3)})
    importance_scope = "test" if sealed else "valid_v2"
    importance = prefer_sealed(_query(conn, "SELECT * FROM star_fact_importance WHERE scope = ? ORDER BY mean_abs_shap DESC, reason_key", (importance_scope,))).head(10)
    variants = prefer_sealed(_query(conn, "SELECT * FROM star_fact_sensitivity")) if sealed else pd.DataFrame(columns=["variant"])
    out_variants = []
    for variant in [v for v in VARIANTS_ES if v in set(variants["variant"])]:
        at = variants[variants["variant"] == variant].set_index("method_key")
        out_variants.append({"variant": variant, "label_es": VARIANTS_ES[variant], "n": int(at["n"].iloc[0]), "m": int(at["m"].iloc[0]),
                             "test_cuts": len((seal_variants.get(variant) or {}).get("test_cuts", [])), "auc_model": _num(at["auc"].get("model"), 3), "auc_b2": _num(at["auc"].get("b2_rfm"), 3),
                             "auc_b_star": _num(at["auc"].get("b_star"), 3), "diff_b_star_ci_low": _num(at["diff_ci_low"].get("b_star"), 3),
                             "diff_b_star_ci_high": _num(at["diff_ci_high"].get("b_star"), 3)})
    return {
        "split": split, "selection": selection,
        "b_star": {"method": b_star, "auc_valid": None if b_star_v2.empty else _num(b_star_v2["auc"].iloc[0], 3), "chosen_on": "valid"},
        "methods": methods, "gain": gain, "calibration": _calibration(conn, cfg, sealed), "cost_curve": cost_curve,
        "threshold": {"value": _num(model["threshold"], 2), "break_even": _num(model["break_even"], 3), "offer_cost": _num(model["offer_cost"], 2),
                      "rescue_rate": _num(model["rescue_rate"], 2), "retained_value": _num(model["retained_value"], 2), "chosen_on": "valid_v2"},
        "importance": [{"feature": r.reason_key, "feature_es": FEATURES_ES[r.reason_key][0], "mean_abs_shap": _num(r.mean_abs_shap, 3)} for r in importance.itertuples()],
        "examples": _examples(conn, cfg, sealed), "variants": out_variants,
    }


# --- retention.json -----------------------------------------------------------------------------------------------------------------


def _pair(first: int | None, second: int | None, minimum: int) -> tuple[int | None, int | None]:
    """Two counts that add up to a published total once the window closes (who returned and who churned of the scored; the same of the
    contacted): both go through ``protect``. While the window is open the second is unknown (None) and the first is a cell of its own."""
    if second is None:
        return (None if _hidden(first, minimum) else first), None
    a, b = protect([{"v": first}, {"v": second}], [first, second], (), minimum)
    return a["v"], b["v"]


def _retention(conn: sqlite3.Connection, cfg: PipelineConfig) -> dict[str, Any]:
    minimum = cfg.site.min_cell_customers
    model = _model_row(conn)
    tracking = _query(conn, "SELECT * FROM star_fact_tracking ORDER BY cut_key, as_of_key")
    blocks = _query(conn, "SELECT cut_key, block FROM star_dim_cut").set_index("cut_key")["block"]
    cuts = []
    for cut_key, part in tracking.groupby("cut_key", sort=True):
        first = part.iloc[0]
        by_as_of = []
        for r in part.itertuples():
            returned, churned = _pair(_int(r.returned), _int(r.churned), minimum)                       # of the scored, published
            contacted_returned, contacted_churned = _pair(_int(r.contacted_returned), _int(r.contacted_churned), minimum)   # of the contacted
            by_as_of.append({"as_of": _day(r.as_of_key), "window_closed": bool(r.window_closed), "returned": returned, "churned": churned,
                             "contacted_churned": contacted_churned, "contacted_returned": contacted_returned, "expected_churners": _num(r.expected_churners, 1)})
        scored, contacted_n = int(first["scored"]), int(first["contacted"])
        small = _hidden(scored, minimum) or _hidden(contacted_n, minimum)      # the scored are a count of customers, like label.json's customers
        cuts.append({"cut": _day(cut_key), "block": str(blocks.get(cut_key)), "is_censored": bool(first["is_censored"]),
                     "scored": None if _hidden(scored, minimum) else scored, "contacted": None if small else contacted_n,
                     "contact_share": None if small else _num(contacted_n / scored, 3), "by_as_of": by_as_of})
    country = _query(conn, "SELECT c.cut_key, d.country_es, c.customers, c.contacted, c.churned, c.suppressed FROM star_fact_cut_country AS c "
                           "JOIN star_dim_country AS d ON d.country_key = c.country_key ORDER BY c.cut_key, d.country_key")
    closed = [k for k in sorted(set(country["cut_key"])) if country.loc[country["cut_key"] == k, "churned"].notna().any()]
    latest = closed[-1] if closed else (country["cut_key"].max() if len(country) else None)
    part = country[country["cut_key"] == latest]
    by_country = [{"country_es": r.country_es, "customers": _int(r.customers), "contacted": _int(r.contacted),
                   "churn_rate_observed": None if bool(r.suppressed) or pd.isna(r.churned) else _num(r.churned / r.customers, 3), "suppressed": bool(r.suppressed)}
                  for r in part.itertuples()]
    reasons = _query(conn, "SELECT r.reason_key, r.contacted_top3 FROM star_fact_reason_summary AS r WHERE r.cut_key = ? ORDER BY r.contacted_top3 DESC, r.reason_key",
                     (int(latest) if latest is not None else 0,))
    contacted_cut = tracking.loc[tracking["cut_key"] == latest, "contacted"].max() if latest is not None and len(tracking) else None
    shown = [] if not contacted_cut else [{"feature_es": FEATURES_ES[r.reason_key][0], "share_of_contacted_top3": _num(r.contacted_top3 / contacted_cut, 3)}
                                          for r in reasons.itertuples() if not _hidden(r.contacted_top3, minimum)][:10]
    return {"threshold": _num(model["threshold"], 2), "model_version": str(model["model_version"]), "cuts": cuts, "by_country": by_country,
            "by_country_cut": None if latest is None else _day(latest), "reasons": shown}


# --- writing ------------------------------------------------------------------------------------------------------------------------


def _text(document: dict) -> str:
    return json.dumps(document, ensure_ascii=False, sort_keys=True, indent=1, allow_nan=False) + "\n"


def _read_checked(out_dir: Path) -> tuple[dict[str, bytes], list[str]]:
    out_dir = Path(out_dir)
    try:
        files = json.loads((out_dir / MANIFEST_FILE).read_text(encoding="utf-8"))["files"]
        if not isinstance(files, dict) or not all(isinstance(e, dict) for e in files.values()):
            raise TypeError(MANIFEST_FILE)
    except FileNotFoundError:
        return {}, [f"falta {MANIFEST_FILE} en {out_dir}"]
    except (ValueError, KeyError, TypeError):
        return {}, [f"{MANIFEST_FILE} de {out_dir} no se puede leer"]
    problems = [] if sorted(files) == sorted(SITE_FILES) else [f"{MANIFEST_FILE} nombra {sorted(files)} y no los cinco archivos del sitio"]
    out: dict[str, bytes] = {}
    for name in SITE_FILES:
        path = out_dir / name
        if not path.is_file():
            problems.append(f"falta {name} en {out_dir}")
            continue
        data = path.read_bytes()
        entry = files.get(name, {})
        if len(data) != entry.get("bytes") or hashlib.sha256(data).hexdigest() != entry.get("sha256"):
            problems.append(f"{name} no es el que nombra {MANIFEST_FILE} (otro tamaño o SHA-256): los archivos no son de una misma exportación")
        out[name] = data
    return out, problems


def read_site(out_dir: Path) -> dict[str, bytes]:
    """The bytes of the five files, each read once and checked against ``manifest.json``; ``SiteSetError`` if they are not one export."""
    data, problems = _read_checked(out_dir)
    if problems:
        raise SiteSetError("; ".join(problems))
    return data


def verify_site(out_dir: Path) -> list[str]:
    """What keeps the files of `out_dir` from being one export (``[]`` when the manifest names the five with their size and SHA-256)."""
    return _read_checked(out_dir)[1]


def _write(texts: dict[str, str], out_dir: Path, cap: int, header: dict[str, Any]) -> list[Path]:
    out_dir = Path(out_dir)
    payloads = {name: texts[name].encode("utf-8") if name in texts else (out_dir / name).read_bytes() for name in SITE_FILES}
    total = sum(len(p) for p in payloads.values())
    if total > cap:
        raise SiteExportError(f"los archivos del sitio pesan {total} bytes y el tope es {cap}: no se escribió ninguno")
    manifest = _text({**header, "files": {n: {"bytes": len(p), "sha256": hashlib.sha256(p).hexdigest()} for n, p in payloads.items()}})
    paths = [write_atomic(out_dir / name, texts[name]) for name in SITE_FILES if name in texts]
    write_atomic(out_dir / MANIFEST_FILE, manifest)
    logger.info("site export %s: %d files, %d bytes", header["run_key"], len(paths), total)
    return paths


def export_site(conn: sqlite3.Connection, out_dir: Path, meta: ExportMeta, cfg: PipelineConfig) -> list[Path]:
    """Write the five site files from the star model of `conn`, then ``manifest.json``; returns the five paths (``SITE_FILES`` order). Every
    document is built before the first file is replaced, and nothing is written if together they would pass ``[site] max_total_bytes``."""
    from churnrisk.registry import read_seal

    _require_star(conn)
    seal = read_seal(cfg.paths.seal) or {}
    seal_variants = {v["variant"]: v for v in (seal.get("test") or {}).get("variants") or []}
    header = _header(meta)
    summary = _summary(conn, cfg, meta)
    sealed = summary["evaluation_status"] == "sealed"
    documents = {"summary.json": summary, "validation_rules.json": _validation(conn), "label.json": _label(conn, cfg, summary["headline"]),
                 "algorithms.json": _algorithms(conn, cfg, sealed, seal_variants), "retention.json": _retention(conn, cfg)}
    return _write({name: _text({**header, **documents[name]}) for name in SITE_FILES}, out_dir, cfg.site.max_total_bytes, header)


def export_summary(conn: sqlite3.Connection, out_dir: Path, meta: ExportMeta, cfg: PipelineConfig) -> Path:
    """Rewrite only ``summary.json`` (what closing a run changes) and the manifest with it. The other four must be one export with the
    summary there now: over a folder that is not one export nothing is written (``SiteExportError``)."""
    _require_star(conn)
    problems = verify_site(out_dir)
    if problems:
        raise SiteExportError(f"no se reescribe el resumen: {'; '.join(problems)}; la tarea export escribe los cinco archivos de nuevo")
    header = _header(meta)
    [path] = _write({"summary.json": _text({**header, **_summary(conn, cfg, meta)})}, out_dir, cfg.site.max_total_bytes, header)
    return path


__all__ = ["MANIFEST_FILE", "SITE_FILES", "SiteExportError", "SiteSetError", "export_site", "export_summary", "protect", "read_site", "verify_site"]
