"""The task ``evaluate``, the evaluation tables and the summary (RF23, RF24, AC22, AC25; D19, D20; plan, sections 3 and 16).

``evaluate`` runs in every run after the launch's ``fit_model``. While the validation of the launch is not stored for this configuration it
evaluates V2 (the threshold and the comparisons the site shows before the seal), the SHAP importance on V2 and the leakage demonstration. Once
the calculation date reaches the end of the window of the last test cut it evaluates the test **once**: C01-C10, written to the seal's test part
(``registry.write_test_seal``) and to the sealed rows of the warehouse, which are never rewritten. With another configuration than the sealed one,
everything is stored as ``post_seal`` and the seal is left as it is (M05).

``build_summary`` says what is known: the test pending (with the reason and the figures of V2, labelled as validation), the sealed criteria from
the warehouse, or, when the warehouse has no sealed rows but the seal has its test part (a rebuild from scratch with other costs), the criteria
rebuilt from the seal, each checked against its entry (D20), with the run's own analysis below as post-seal. The top-level ``costs`` are those of
the figures next to them: the sealed ones when the criteria are sealed, the run's own in the post-seal block (D92). ``write_summary`` writes
``evaluation_summary.json`` and ``.md``; ``sync_block`` copies the Markdown between two markers of the README.

This module receives the whole configuration (the paths of the seal and of the reports); the calculations it calls receive the sealed view.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from churnrisk.config import PipelineConfig
from churnrisk.deliveries import delivery_plan
from churnrisk.evaluation import (
    CRITERIA,
    Criterion,
    EvaluationResult,
    block_data,
    criteria_from_seal,
    es,
    evaluate_criteria,
    evaluate_frame,
    seal_metrics,
)
from churnrisk.explain import explain, global_importance
from churnrisk.features import build_matrix
from churnrisk.files import write_atomic
from churnrisk.launch import load_registered
from churnrisk.leakage_demo import leakage_table
from churnrisk.model import Candidate
from churnrisk.registry import SealError, config_fingerprint, read_seal, seal_state, sealed_view, write_test_seal
from churnrisk.schema import FEATURE_COLUMNS
from churnrisk.sensitivity import definition_tables, run_variants
from churnrisk.split import labelled_rows
from churnrisk.warehouse import apply_schema

logger = logging.getLogger(__name__)

SUMMARY_VERSION = 1
RESULTS_START, RESULTS_END = "<!-- results:start -->", "<!-- results:end -->"
COST_KEYS = ("offer_cost", "rescue_rate", "retained_value")      # the costs the summary names, next to the figures computed with them
METHODS_ES = {"model": "Modelo", "b0_all": "Contactar a todos", "b1_recency": "Recencia", "b2_rfm": "RFM", "b3_bgnbd": "BG/NBD",
              "b4_frequency": "Frecuencia", "b5_alive": "1 − P(vivo)", "b_star": "Base más fuerte (B*)"}


def test_ready_date(cfg: PipelineConfig) -> date:
    """The first calculation date on which every test window has closed: ``test_last + N - 1``."""
    return cfg.split.test_last + timedelta(days=cfg.label.horizon_days - 1)


def test_delivery(cfg: PipelineConfig) -> str:
    """The delivery of the plan whose run evaluates the test (``M2011-11`` by default)."""
    ready = test_ready_date(cfg)
    return next(spec.delivery_id for spec in delivery_plan(cfg) if spec.as_of >= ready)


# --- storing a result --------------------------------------------------------------------------------------------------------


def _db(value: Any) -> Any:
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, bool):
        return int(value)
    return float(value)


def _has(conn: sqlite3.Connection, table: str, where: str, args: tuple) -> bool:
    return conn.execute(f"SELECT 1 FROM {table} WHERE {where} LIMIT 1", args).fetchone() is not None


def store_result(conn: sqlite3.Connection, result: EvaluationResult, criteria: list[Criterion] | None, state: str, run_key: str, as_of: date) -> None:
    """Write every measure of `result` (and its criteria) with `state`, in one transaction. The sealed rows of the test are written once; any
    other group of rows of the same scope and state is replaced."""
    scope = result.scope
    once = scope == "test" and state == "sealed"
    if once and _has(conn, "eval_metrics", "scope = ? AND seal_state = ?", (scope, state)):
        return
    groups = {
        "eval_metrics": [(scope, m, k, state, _db(v), run_key, as_of.isoformat()) for m, values in result.metrics.items() for k, v in values.items()],
        "eval_per_cut": [(scope, entry["cut"], k, state, _db(v), run_key) for entry in result.per_cut for k, v in entry.items() if k != "cut"],
        "eval_bootstrap": [(scope, f"model_vs_{k}", state, b.diff, b.ci_low, b.ci_high, b.kept, b.discarded, run_key) for k, b in result.bootstrap.items()],
        "eval_cost_sensitivity": [(r.scope, r.break_even, r.method, state, r.threshold, r.net_benefit, r.net_benefit_per_1000, r.contacted_share, int(r.rows),
                                   run_key) for r in result.sensitivity.itertuples() if r.scope == scope],
        "eval_gain": [(scope, m, int(g.point), state, int(g.contacted), int(g.captured), g.share_contacted, g.share_captured, g.lift)
                      for m, table in result.gain.items() for g in table.itertuples()],
        "eval_roc": [(scope, m, int(r.point), state, r.fpr, r.tpr) for m, table in result.roc.items() for r in table.itertuples()],
        "eval_calibration": [(scope, m, int(c.bin), state, _db(c.p_mean), _db(c.observed), int(c.rows)) for m, table in result.calibration.items()
                             for c in table.itertuples()],
    }
    conn.execute("BEGIN IMMEDIATE")
    try:
        for table, rows in groups.items():
            conn.execute(f"DELETE FROM {table} WHERE scope = ? AND seal_state = ?", (scope, state))
            if rows:
                conn.executemany(f"INSERT INTO {table} VALUES ({', '.join('?' for _ in rows[0])})", rows)
        if criteria is not None:
            conn.execute("DELETE FROM eval_criteria WHERE seal_state = ?", (state,))
            conn.executemany("INSERT INTO eval_criteria VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [
                (c.criterion_id, state, c.name_es, _db(c.value), _db(c.baseline_value), _db(c.ci_low), _db(c.ci_high), c.threshold_es,
                 None if c.passed is None else int(c.passed), c.seen_by_research, c.seen_by_planner, c.verdict_es, run_key) for c in criteria])
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise


def _store_rows(conn: sqlite3.Connection, table: str, where: str, args: tuple, rows: list[tuple]) -> None:
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(f"DELETE FROM {table} WHERE {where}", args)
        if rows:
            conn.executemany(f"INSERT INTO {table} VALUES ({', '.join('?' for _ in rows[0])})", rows)
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise


def _importance(conn: sqlite3.Connection, bundle, scope: str, view, state: str, run_key: str) -> None:
    rows = labelled_rows(conn, [scope])
    model = bundle.model
    matrix = build_matrix(rows[list(FEATURE_COLUMNS)], model.feature_set, model.country_groups)
    table = global_importance(explain(model.pipeline, matrix, view.criteria.shap_additivity_tol))
    if scope == "test" and state == "sealed" and _has(conn, "feature_importance", "scope = ? AND seal_state = ?", (scope, state)):
        return
    _store_rows(conn, "feature_importance", "scope = ? AND seal_state = ?", (scope, state),
                [(scope, f, state, float(v), run_key) for f, v in zip(table["feature"], table["mean_abs_shap"], strict=True)])


def variant_rows(variants: list[dict[str, Any]], state: str, run_key: str) -> list[tuple]:
    """The variants as rows of ``eval_variants``: (variant, method, metric, seal_state, value, run_key)."""
    rows = []
    for v in variants:
        for method, metric, key in (("all", "n", "n"), ("all", "m", "m"), ("all", "rows", "rows"), ("all", "churn_rate", "churn_rate"),
                                    ("model", "auc", "auc_model"), ("b2_rfm", "auc", "auc_b2"), ("b_star", "auc", "auc_b_star"),
                                    ("b2_rfm", "diff_ci_low", "diff_b2_ci_low"), ("b2_rfm", "diff_ci_high", "diff_b2_ci_high"),
                                    ("b_star", "diff_ci_low", "diff_b_star_ci_low"), ("b_star", "diff_ci_high", "diff_b_star_ci_high")):
            rows.append((v["variant"], method, metric, state, _db(v[key]), run_key))
    return rows


# --- the task ----------------------------------------------------------------------------------------------------------------


def evaluate(conn: sqlite3.Connection, cfg: PipelineConfig, *, run_key: str, as_of: date, source_sha256: str) -> dict[str, Any]:
    """Evaluate what the calculation date allows (see the module). Returns what the run records (JSON-ready)."""
    apply_schema(conn)
    view = sealed_view(cfg, source_sha256)
    config_sha256 = config_fingerprint(view)
    state = seal_state(cfg.paths.seal, config_sha256)
    if state == "none":
        raise SealError("no hay sello: el lanzamiento escribe su parte antes de que se evalúe nada (docs/runbook.md, R7)")
    rows_state = "sealed" if state == "match" else "post_seal"
    registered = load_registered(conn, cfg)                       # M03
    bundle, threshold = registered.bundle, registered.threshold
    out: dict[str, Any] = {"seal_state": rows_state, "valid_v2": "kept", "test": "pending", "test_ready": test_ready_date(cfg).isoformat()}
    v2 = block_data(conn, "valid_v2", bundle, view)
    if not _has(conn, "eval_metrics", "scope = 'valid_v2' AND seal_state = ?", (rows_state,)):
        result = evaluate_frame(v2, v2, threshold, view)
        store_result(conn, result, None, rows_state, run_key, as_of)
        _importance(conn, bundle, "valid_v2", view, rows_state, run_key)
        leak = leakage_table(conn, view, json.loads(conn.execute("SELECT params_json FROM model_registry WHERE model_version = ?",
                                                                 (registered.model_version,)).fetchone()[0]), cfg.deliveries.launch_as_of)
        _store_rows(conn, "eval_leakage", "1 = 1", (), [(r.variable, r.variable_es, r.auc_valid_v2, r.note_es, run_key) for r in leak.itertuples()])
        definition, silences = definition_tables(conn, view, as_of)
        _store_rows(conn, "eval_label_definition", "1 = 1", (), [(int(r.n), int(r.m), float(r.churn_rate), int(r.rows), run_key) for r in definition.itertuples()])
        _store_rows(conn, "eval_silence_return", "1 = 1", (), [(int(r.n), int(r.silences), _db(r.return_share), run_key) for r in silences.itertuples()])
        out["valid_v2"] = "evaluated"
    if as_of < test_ready_date(cfg):
        return out
    if rows_state == "sealed" and _has(conn, "eval_criteria", "seal_state = 'sealed'", ()):
        out["test"] = "sealed_before"
        return out
    result = evaluate_frame(block_data(conn, "test", bundle, view), v2, threshold, view)
    params = json.loads(conn.execute("SELECT params_json FROM model_registry WHERE model_version = ?", (registered.model_version,)).fetchone()[0])
    candidate = Candidate(registered.feature_set, params["learning_rate"], params["max_leaf_nodes"], params["min_samples_leaf"])
    variants = run_variants(conn, view, bundle, candidate, read_seal(cfg.paths.seal), as_of)     # after the launch part of the seal
    criteria = evaluate_criteria(result, view, variants)
    part = {"run_key": run_key, "as_of": as_of.isoformat(), "config_sha256": config_sha256, "criteria": [c.seal_entry() for c in criteria],
            "metrics": seal_metrics(result), "per_cut": result.per_cut, "variants": variants}
    outcome = write_test_seal(cfg.paths.seal, part) if rows_state == "sealed" else "post_seal"
    store_result(conn, result, criteria, rows_state, run_key, as_of)
    _store_rows(conn, "eval_variants", "seal_state = ?", (rows_state,), variant_rows(variants, rows_state, run_key))
    _importance(conn, bundle, "test", view, rows_state, run_key)
    out.update(test=outcome, criteria={c.criterion_id: c.passed for c in criteria})
    logger.info("evaluate %s: test %s (%s), criteria passed %s", run_key, outcome, rows_state, [c.criterion_id for c in criteria if c.passed])
    return out


# --- the summary ---------------------------------------------------------------------------------------------------------


def _criteria_rows(conn: sqlite3.Connection, state: str) -> list[dict[str, Any]]:
    columns = ("criterion_id", "name_es", "value", "baseline_value", "ci_low", "ci_high", "threshold_es", "passed", "seen_by_research",
               "seen_by_planner", "verdict_es")
    rows = conn.execute(f"SELECT {', '.join(columns)} FROM eval_criteria WHERE seal_state = ? ORDER BY criterion_id", (state,)).fetchall()
    out = []
    for row in rows:
        entry = dict(zip(columns, row, strict=True))
        entry["passed"] = None if entry["passed"] is None else bool(entry["passed"])
        out.append(entry)
    return out


def _criterion_dict(c: Criterion) -> dict[str, Any]:
    return {"criterion_id": c.criterion_id, "name_es": c.name_es, "value": c.value, "baseline_value": c.baseline_value, "ci_low": c.ci_low,
            "ci_high": c.ci_high, "threshold_es": c.threshold_es, "passed": c.passed, "seen_by_research": c.seen_by_research,
            "seen_by_planner": c.seen_by_planner, "verdict_es": c.verdict_es}


def _metrics(conn: sqlite3.Connection, scope: str, state: str) -> dict[str, dict[str, float | None]]:
    out: dict[str, dict[str, float | None]] = {}
    for method, metric, value in conn.execute("SELECT method, metric, value FROM eval_metrics WHERE scope = ? AND seal_state = ? ORDER BY 1, 2", (scope, state)):
        out.setdefault(method, {})[metric] = value
    return out


def build_summary(conn: sqlite3.Connection, cfg: PipelineConfig, *, run_key: str, as_of: date, source_sha256: str) -> dict[str, Any]:
    """What the summary says (see the module): ``evaluation_status`` is ``pending``, ``sealed`` or ``post_seal`` (this run's configuration is
    not the sealed one), ``sealed_from`` is ``seal`` when the criteria come from the seal."""
    apply_schema(conn)
    view = sealed_view(cfg, source_sha256)
    state = seal_state(cfg.paths.seal, config_fingerprint(view))
    rows_state = "sealed" if state == "match" else "post_seal"
    seal = read_seal(cfg.paths.seal)
    run_costs = {key: getattr(view.costs, key) for key in COST_KEYS}
    summary: dict[str, Any] = {
        "schema_version": SUMMARY_VERSION, "run_key": run_key, "as_of": as_of.isoformat(), "source_sha256": source_sha256, "costs": run_costs,
        "validation_v2": _metrics(conn, "valid_v2", rows_state), "test": None, "post_seal": None, "pending_reason_es": None,
    }
    sealed_rows = _criteria_rows(conn, "sealed")
    post_rows = _criteria_rows(conn, "post_seal") if rows_state == "post_seal" else []
    if sealed_rows:
        summary.update(evaluation_status="sealed", criteria=sealed_rows, test=_metrics(conn, "test", "sealed"))
    elif seal is not None and seal.get("test") is not None:
        summary.update(evaluation_status="sealed", criteria=[_criterion_dict(c) for c in criteria_from_seal(seal)], test=seal["test"]["metrics"],
                       sealed_from="seal")
    elif post_rows:          # no sealed test result anywhere, and this run evaluated the test with another configuration
        summary.update(evaluation_status="post_seal", criteria=post_rows, test=_metrics(conn, "test", "post_seal"))
    else:
        reason = (f"La prueba se evalúa con la entrega de {test_delivery(cfg)[1:]}: las ventanas de sus cortes cierran el "
                  f"{test_ready_date(cfg).isoformat()} y esta corrida es la del {as_of.isoformat()}. Las cifras que se muestran son de la "
                  "validación (V2), no de la prueba.")
        summary.update(evaluation_status="pending", pending_reason_es=reason, criteria=[
            {"criterion_id": cid, "name_es": name, "value": None, "baseline_value": None, "ci_low": None, "ci_high": None, "threshold_es": threshold,
             "passed": None, "seen_by_research": research, "seen_by_planner": planner, "verdict_es": "Pendiente: " + reason}
            for cid, (name, threshold, research, planner) in CRITERIA.items()])
    if summary["evaluation_status"] == "sealed" and seal is not None:   # the sealed figures carry the sealed costs (A2, D92)
        summary["costs"] = {key: seal["launch"]["sealed_config"]["costs"][key] for key in COST_KEYS}
    if post_rows and summary["evaluation_status"] == "sealed":       # the run's own analysis, below what was sealed, with its own costs
        summary["post_seal"] = {"criteria": post_rows, "test": _metrics(conn, "test", "post_seal") or None, "costs": run_costs}
    if seal is not None:
        summary["seal"] = {"config_sha256": seal["launch"]["config_sha256"], "launch_run_key": seal["launch"]["run_key"],
                           "test_run_key": (seal.get("test") or {}).get("run_key"), "test_as_of": (seal.get("test") or {}).get("as_of")}
    return summary


def _cell(text: Any) -> str:
    """A cell of a Markdown table: its pipes escaped, so «|sesgo|» stays inside its cell (A4 of the independent evaluation, D91)."""
    return str(text).replace("|", r"\|")


def _verdict(c: dict[str, Any]) -> str:
    """The verdict of a criterion as the summary says it: the sealed ``verdict_es`` and, for C09, the same sealed numbers said plainly, at how
    many break-even points the model keeps at least the benefit of B* and at how many it does not (A5, D91). The data keep the sealed text."""
    text = c["verdict_es"]
    if c["criterion_id"] == "C09" and c.get("value") is not None and c.get("baseline_value") is not None:
        kept, points = int(c["value"]), int(c["baseline_value"])
        text += f" Es decir: lo deja en {kept} de los {points} puntos de equilibrio y no lo deja en {points - kept}."
    return text


def summary_markdown(summary: dict[str, Any]) -> str:
    """The Markdown of the summary, in Spanish: the state, each criterion with its number and its verdict (also «no supera»), and below, the
    post-seal analysis when there is one."""
    lines = ["## Resultados", ""]
    status = summary["evaluation_status"]
    if summary.get("pending_reason_es") and not any(c.get("value") is not None for c in summary["criteria"]):
        lines += [f"**Prueba pendiente.** {summary['pending_reason_es']}", ""]
        v2 = summary.get("validation_v2") or {}
        if v2:
            lines += ["| Método (validación V2) | AUC | Beneficio neto por 1.000 clientes |", "| --- | ---: | ---: |"]
            lines += [f"| {METHODS_ES.get(m, m)} | {es(v.get('auc'))} | {es(v.get('nb_per_1000'), 1)} |" for m, v in v2.items()]
            lines.append("")
    else:
        origin = " (tomados del sello)" if summary.get("sealed_from") == "seal" else ""
        lines += [f"Criterios fijados antes de construir, evaluados una vez sobre la prueba{origin}.", "",
                  "| Criterio | Umbral | Valor | Cumple | Veredicto |", "| --- | --- | ---: | --- | --- |"]
        for c in summary["criteria"]:
            passed = "informativo" if c["passed"] is None else ("sí" if c["passed"] else "no")
            lines.append(f"| {c['criterion_id']} {_cell(c['name_es'])} | {_cell(c['threshold_es'])} | {es(c['value'])} | {passed} | {_cell(_verdict(c))} |")
        lines.append("")
    post = summary.get("post_seal")
    if post and post.get("criteria"):
        costs = post["costs"]
        lines += ["### Análisis posterior al sello", "",
                  f"Con otra configuración que la sellada (costo de la oferta {es(costs['offer_cost'], 2)}, tasa de rescate {es(costs['rescue_rate'], 2)}, "
                  f"valor del cliente retenido {es(costs['retained_value'], 2)}): no reemplaza lo sellado.", ""]
        lines += [f"- {c['criterion_id']}: {_verdict(c)}" for c in post["criteria"]]
        lines.append("")
    lines.append(f"Estado: {status}. Corrida {summary['run_key']} del {summary['as_of']}.")
    return "\n".join(lines) + "\n"


def write_summary(summary: dict[str, Any], reports_dir: Path) -> tuple[Path, Path]:
    """``evaluation_summary.json`` and ``evaluation_summary.md`` in `reports_dir`, each written atomically."""
    reports_dir = Path(reports_dir)
    json_path, md_path = reports_dir / "evaluation_summary.json", reports_dir / "evaluation_summary.md"
    write_atomic(json_path, json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=1, allow_nan=False) + "\n")
    write_atomic(md_path, summary_markdown(summary))
    return json_path, md_path


def sync_block(path: Path, start_marker: str, end_marker: str, content: str) -> bool:
    """Replace what is between the two markers of `path` with `content` (the markers stay). True if the file changed. A file without both
    markers, in order and once each, is a ``ValueError`` and is not touched."""
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    if text.count(start_marker) != 1 or text.count(end_marker) != 1 or text.index(start_marker) > text.index(end_marker):
        raise ValueError(f"{path.name} debe tener una vez {start_marker} y después una vez {end_marker}")
    head, rest = text.split(start_marker)
    _old, tail = rest.split(end_marker)
    new = f"{head}{start_marker}\n{content.strip()}\n{end_marker}{tail}"
    if new == text:
        return False
    write_atomic(path, new)
    return True
