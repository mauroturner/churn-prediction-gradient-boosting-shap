"""Validation of the source, of every delivery and of its lines, the roles of the lines and the validation report (RF05, RF08, D03, D23).

The rules are the table of the plan, section 6, in its order (``RULES``). Each declares its severity, its scope (``source``, ``delivery``,
``lines`` or ``model``) and how it is published over runs (``aggregation``: ``source`` once, from the report of the source; ``per_run`` summed
over the loaded runs; ``latest`` read once from the last loaded run, because it already holds the earlier ones: project 03's D94).

- The rules of the source (V01-V06, I03) are not evaluated again here: the first task ran them while it fetched and read the workbook, so
  ``validate_source`` turns its outcome (a ``SourceError`` naming the failing rule, or the ``SourceReport`` of a clean read) into results.
- The rules of the delivery and of its lines (V10-V14, V20-V31, I01, I02) read the delivery, the plan, its manifest entry and what the
  warehouse already holds (``deliveries`` and ``raw_lines``, plan section 5), which they only read. V22 nets every line known on the
  delivery's calculation date (D04), so it already holds the earlier runs; V30 counts a customer in the delivery where it first shows a
  second country, so the runs add up to the customers with more than one.
- The rules of the model (M01-M08, I04-I08) are evaluated by their tasks, which add them with ``model_result`` and ``add_results``.

A rule that cannot be evaluated because an earlier blocking rule failed is listed in ``not_evaluated``; it is never reported as passed.
``rows_affected`` counts lines, ``customers_affected`` the distinct customers of those lines and ``value_gbp`` their gross value,
``|quantity x price|``. An example names a line by its ``line_id`` and never shows a customer or an invoice number (D26).
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from churnrisk.deliveries import DeliverySpec, ManifestEntry, delivery_plan
from churnrisk.files import sha256_file, write_atomic
from churnrisk.netting import net_cancellations, netting_inputs
from churnrisk.schema import CANONICAL_SCHEMA, SourceError

logger = logging.getLogger(__name__)

EXAMPLE_LIMIT = 5
LARGE_QUANTITY_UNITS = 5000          # V29: a line of 5,000 units or more is kept and flagged (43 in the real file, research.md)
UNSPECIFIED_COUNTRY = "Unspecified"   # V31
_SAFE_RUN_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_PATH_KEYS = ("zip", "kept")          # keys of a SourceError problem that hold a path of this machine


class Severity(StrEnum):
    BLOCKING = "blocking"
    WARNING = "warning"
    INFO = "info"


class Aggregation(StrEnum):
    SOURCE = "source"
    PER_RUN = "per_run"
    LATEST = "latest"


SEVERITY_ES = {Severity.BLOCKING: "bloqueante", Severity.WARNING: "advertencia", Severity.INFO: "informativa"}
STATUS_ES = {"pass": "pasa", "fail": "falla", "warn": "advierte", "not_evaluated": "no evaluada"}


@dataclass(frozen=True)
class Rule:
    name_es: str
    severity: Severity
    scope: str               # "source", "delivery", "lines" or "model"
    aggregation: Aggregation


_B, _W, _I = Severity.BLOCKING, Severity.WARNING, Severity.INFO
_S, _P, _L = Aggregation.SOURCE, Aggregation.PER_RUN, Aggregation.LATEST

# rule id -> rule, in the order of the table of the plan (section 6): the report's order
RULES: dict[str, Rule] = {
    "V01": Rule("El zip tiene la huella aceptada (o la registrada, en modo local)", _B, "source", _S),
    "V02": Rule("Descarga segura: HTTPS en cada salto, host permitido y topes de redirecciones, bytes y segundos", _B, "source", _S),
    "V03": Rule("El zip tiene exactamente el miembro esperado, sin rutas, dentro del tope y con su huella", _B, "source", _S),
    "V04": Rule("El libro tiene las hojas configuradas y en cada una las 8 columnas exactas, en orden", _B, "source", _S),
    "V05": Rule("Cada columna tiene su tipo: cantidad entera, precio numérico, fecha y hora, factura y código no vacíos, cliente de 5 cifras o vacío", _B, "source", _S),
    "V06": Rule("El solapamiento entre las hojas es el mismo conjunto de filas", _B, "source", _S),
    "V10": Rule("La entrega es la siguiente del plan y su período empieza el día siguiente al fin de la anterior", _B, "delivery", _P),
    "V11": Rule("La fecha de cada factura está dentro del período de la entrega", _B, "delivery", _P),
    "V12": Rule("Ninguna línea de la entrega está ya en el almacén ni repetida dentro de ella", _B, "delivery", _P),
    "V13": Rule("Cada factura tiene un solo cliente y un solo país, también contra lo ya cargado", _B, "delivery", _P),
    "V14": Rule("La entrega no está vacía y sus filas y su SHA-256 son los del manifiesto", _B, "delivery", _P),
    "V20": Rule("Línea sin cliente (se aparta)", _W, "lines", _P),
    "V21": Rule("Anulación con cliente y producto (se descuenta de la compra que anula)", _W, "lines", _P),
    "V22": Rule("Anulación, o resto de una, sin compra que anular con lo conocido en la fecha (se descarta y se cuenta)", _W, "lines", _L),
    "V23": Rule("Cantidad con el signo contrario al de su factura: cero o negativa sin «C», positiva con «C» (se aparta)", _W, "lines", _P),
    "V24": Rule("Precio cero o negativo (se aparta)", _W, "lines", _P),
    "V25": Rule("Código de servicio: envío, comisiones, ajustes, muestras, pruebas, PADS (se aparta)", _W, "lines", _P),
    "V26": Rule("Vale de regalo (se aparta)", _W, "lines", _P),
    "V27": Rule("Factura «A» de ajuste de deuda incobrable (se aparta)", _W, "lines", _P),
    "V28": Rule("Línea idéntica a otra anterior de su hoja (se conserva y se marca)", _W, "lines", _P),
    "V29": Rule("Cantidad de 5.000 unidades o más en una línea (se conserva y se marca)", _W, "lines", _P),
    "V30": Rule("Cliente con más de un país (se usa el de su última línea anterior al corte y se marca)", _W, "lines", _P),
    "V31": Rule("País «Unspecified» (va a «Otros» y se marca)", _W, "lines", _P),
    "M01": Rule("Trampa de fuga: el AUC del candidato elegido en V1 es menor que el umbral de alarma", _B, "model", _L),
    "M02": Rule("Las columnas de la matriz son exactamente las del conjunto elegido, sin etiquetas, calendario ni identificadores", _B, "model", _P),
    "M03": Rule("El artefacto del modelo tiene la huella registrada, antes de deserializarlo", _B, "model", _P),
    "M04": Rule("Una probabilidad finita en [0, 1] por cliente puntuado", _B, "model", _P),
    "M05": Rule("La configuración es la sellada (si no, todo lo calculado es posterior al sello)", _W, "model", _L),
    "M06": Rule("SHAP es aditivo en cada fila explicada", _B, "model", _P),
    "M07": Rule("Ningún bloque usado (entrenamiento, V1, V2, prueba) tiene una sola clase", _B, "model", _L),
    "M08": Rule("El ajuste de BG/NBD converge", _B, "model", _L),
    "I01": Rule("Clientes nuevos en la entrega", _I, "delivery", _P),
    "I02": Rule("Líneas e importe de invitados (sin cliente), en libras y en porcentaje de la entrega", _I, "delivery", _P),
    "I03": Rule("Copias del solapamiento entre hojas quitadas al leer la fuente", _I, "source", _S),
    "I04": Rule("Clientes activos puntuados en el corte de la corrida", _I, "model", _P),
    "I05": Rule("Contactos sugeridos en el corte de la corrida", _I, "model", _P),
    "I06": Rule("Clientes inactivos más de M días en el corte (fuera de la población)", _I, "model", _P),
    "I07": Rule("Clientes de los cortes puntuados que ya volvieron a comprar", _I, "model", _L),
    "I08": Rule("Contactos de ventanas cerradas que se fueron", _I, "model", _L),
}
SOURCE_RULES = tuple(rule_id for rule_id, rule in RULES.items() if rule.scope == "source")
SOURCE_BLOCKING = tuple(rule_id for rule_id in SOURCE_RULES if RULES[rule_id].severity is Severity.BLOCKING)
DELIVERY_RULES = tuple(rule_id for rule_id, rule in RULES.items() if rule.scope in ("delivery", "lines"))
MODEL_RULES = tuple(rule_id for rule_id, rule in RULES.items() if rule.scope == "model")


@dataclass(frozen=True)
class RuleResult:
    rule_id: str
    name_es: str
    severity: Severity
    scope: str
    aggregation: Aggregation
    passed: bool
    rows_affected: int
    customers_affected: int
    value_gbp: float
    examples: list[dict]

    @property
    def status(self) -> str:
        """``pass``, ``fail`` (a blocking rule) or ``warn`` (a warning); an informative rule always passes."""
        if self.passed:
            return "pass"
        return "fail" if self.severity is Severity.BLOCKING else "warn"


@dataclass(frozen=True)
class ValidationReport:
    run_key: str
    source_sha256: str
    delivery_id: str | None
    rows_delivery: int
    results: list[RuleResult]
    not_evaluated: tuple[str, ...] = field(default=())

    @property
    def blocking_failed(self) -> bool:
        return any(r.severity is Severity.BLOCKING and not r.passed for r in self.results)


class ValidationError(RuntimeError):
    """The run was rejected: at least one blocking rule failed (raised by the ``validate`` task)."""

    def __init__(self, report: ValidationReport) -> None:
        self.report = report
        failing = ", ".join(r.rule_id for r in report.results if r.severity is Severity.BLOCKING and not r.passed)
        super().__init__(f"la validación de {report.run_key} rechazó la corrida: fallan las reglas bloqueantes {failing}")


# --- the roles of the lines (U05) -------------------------------------------------------------------------------------

# The rules that set a line aside, in the order of the table of the plan (section 6): a line belongs to the first that matches it. Then a line
# of a «C» invoice is a cancellation and any other a purchase. The same order goes into sql/staging/stg_lines.sql (U09); a test compares them.
EXCLUSION_RULES: dict[str, str] = {
    "no_customer": "V20", "non_positive_quantity": "V23", "non_positive_price": "V24", "service_code": "V25", "gift_voucher": "V26",
    "adjustment_invoice": "V27",
}
ROLES = ("purchase", "cancellation", "excluded")


def _first_reason(frame: pd.DataFrame) -> pd.Series:
    """For every line, the first rule of ``EXCLUSION_RULES`` that sets it aside, or None."""
    invoice = frame["invoice"].astype(str)
    cancel = invoice.str.startswith("C")
    quantity, price, kind = frame["quantity"], frame["price"], frame["code_kind"]
    matches = [
        ("no_customer", frame["customer_id"].isna()),
        # the wrong sign for its invoice: zero or less outside a «C» invoice, zero or more inside one (project 02, D36)
        ("non_positive_quantity", (cancel & (quantity >= 0)) | (~cancel & (quantity <= 0))),
        ("non_positive_price", price <= 0),
        ("service_code", kind == "service"),
        ("gift_voucher", kind == "gift_voucher"),
        ("adjustment_invoice", invoice.str.startswith("A")),
    ]
    reason = np.full(len(frame), None, dtype=object)
    for name, mask in matches:
        reason[pd.isna(reason) & np.asarray(mask, dtype=bool)] = name
    return pd.Series(reason, index=frame.index, dtype=object)


def classify_lines(frame: pd.DataFrame) -> pd.DataFrame:
    """``role`` (``purchase``, ``cancellation`` or ``excluded``) and ``exclusion_reason`` of every line of `frame`.

    `frame` has the canonical columns ``invoice``, ``quantity``, ``price``, ``customer_id`` and ``code_kind``. A line is set aside by the first rule
    that applies, in this order: no customer, a quantity of the wrong sign, a price of zero or below, a service code (``PADS`` included), a gift
    voucher, an «A» invoice (an adjustment of bad debt). A line that no rule sets aside is a cancellation if its invoice starts with «C» and a
    purchase otherwise: a cancellation has a customer, a product code, a negative quantity and a positive price.
    """
    reason = _first_reason(frame)
    cancel = frame["invoice"].astype(str).str.startswith("C").to_numpy()
    role = np.where(reason.notna().to_numpy(), "excluded", np.where(cancel, "cancellation", "purchase"))
    return pd.DataFrame({"role": role, "exclusion_reason": reason}, index=frame.index)


# --- helpers ------------------------------------------------------------------------------------------------------------


def _py(value: Any) -> Any:
    """A JSON-friendly Python value from a pandas or numpy scalar (dates as ISO text)."""
    if value is None or value is pd.NaT or value is pd.NA:
        return None
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if np.isnan(value) else float(value)
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat() if value == value.normalize() else value.isoformat()
    return value


def gross_value(frame: pd.DataFrame) -> float:
    """Gross value in pounds of the lines of `frame`: the sum of ``|quantity x price|``."""
    if frame.empty:
        return 0.0
    return round(float((frame["quantity"] * frame["price"]).abs().sum()), 2)


def _customers(frame: pd.DataFrame) -> int:
    return int(frame["customer_id"].dropna().nunique())


def _result(rule_id: str, passed: bool, rows: int = 0, customers: int = 0, value: float = 0.0, examples: list[dict] | None = None) -> RuleResult:
    rule = RULES[rule_id]
    return RuleResult(rule_id, rule.name_es, rule.severity, rule.scope, rule.aggregation, True if rule.severity is Severity.INFO else bool(passed),
                      int(rows), int(customers), round(float(value), 2), examples or [])


def _ordered(results: dict[str, RuleResult]) -> list[RuleResult]:
    return [results[rule_id] for rule_id in RULES if rule_id in results]


def _log_verdict(report: ValidationReport) -> None:
    blocking = [r.rule_id for r in report.results if r.status == "fail"]
    warnings = [r.rule_id for r in report.results if r.status == "warn"]
    logger.log(logging.WARNING if blocking else logging.INFO, "validation of %s (%s): %s; rows=%d; blocking failed: %s; warnings: %s; not evaluated: %s",
               report.run_key, report.delivery_id or "source", "rejected" if blocking else "accepted", report.rows_delivery,
               ", ".join(blocking) or "none", ", ".join(warnings) or "none", ", ".join(report.not_evaluated) or "none")


def _line_examples(lines: pd.DataFrame) -> list[dict]:
    """The first lines of a rule by ``line_id``, with the columns that do not identify anybody (D26)."""
    return [{"line_id": int(r.line_id), "stock_code": r.stock_code, "quantity": int(r.quantity), "price": float(r.price), "invoice_date": _py(r.invoice_date)}
            for r in lines.sort_values("line_id").head(EXAMPLE_LIMIT).itertuples()]


def _flag(rule_id: str, lines: pd.DataFrame) -> RuleResult:
    """A warning over the `lines` that match its rule: it warns when there are any."""
    return _result(rule_id, lines.empty, len(lines), _customers(lines), gross_value(lines), _line_examples(lines))


# --- the rules of the source --------------------------------------------------------------------------------------------


def _source_problem(problem: dict[str, Any]) -> dict[str, Any]:
    """A problem of a ``SourceError`` as an example: JSON-safe and without a path of this machine."""
    return {key: _py(value) if not isinstance(value, (list, dict)) else value for key, value in problem.items() if key not in _PATH_KEYS}


def _source_failure_rows(error: SourceError) -> int:
    if error.rule_id == "V05":
        return sum(int(p.get("count", 0)) for p in error.problems)
    if error.rule_id == "V06":
        return sum(int(p.get("only_in_first", 0)) + int(p.get("only_in_second", 0)) for p in error.problems)
    return 0


def validate_source(outcome: SourceError | Any, *, run_key: str, source_sha256: str = "") -> ValidationReport:
    """The report of rules V01-V06 and I03 from what the first task found.

    A ``SourceError`` fails its rule (V01 to V06, nothing else), the blocking rules before it pass and every other rule is ``not_evaluated``.
    A ``SourceReport`` (the canonical reading's report) means the whole source was read: V01-V06 pass and I03 counts the overlap copies.
    """
    results: dict[str, RuleResult] = {}
    if isinstance(outcome, SourceError):
        if outcome.rule_id not in SOURCE_BLOCKING:
            raise ValueError(f"{outcome.rule_id} no es una regla bloqueante de la fuente ({', '.join(SOURCE_BLOCKING)})")
        for rule_id in SOURCE_BLOCKING[: SOURCE_BLOCKING.index(outcome.rule_id)]:
            results[rule_id] = _result(rule_id, True)
        examples = [_source_problem(p) for p in outcome.problems[:EXAMPLE_LIMIT]]
        results[outcome.rule_id] = _result(outcome.rule_id, False, _source_failure_rows(outcome), examples=examples)
        not_evaluated = tuple(r for r in RULES if r not in results)
    else:
        for rule_id in SOURCE_BLOCKING:
            results[rule_id] = _result(rule_id, True)
        window = ([{"overlap_start": outcome.overlap_start.isoformat(), "overlap_end": outcome.overlap_end.isoformat()}] if outcome.overlap_rows else [])
        results["I03"] = _result("I03", True, outcome.overlap_rows, value=outcome.overlap_value_gbp, examples=window)
        not_evaluated = ()
    report = ValidationReport(run_key, source_sha256, None, 0, _ordered(results), not_evaluated)
    _log_verdict(report)
    return report


# --- what the warehouse already holds (read only) -------------------------------------------------------------------------

_KNOWN_COLUMNS = ("line_id", "invoice", "stock_code", "quantity", "price", "customer_id", "country", "invoice_ts", "invoice_date", "code_kind")


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)).fetchone() is not None


def loaded_deliveries(conn: sqlite3.Connection) -> set[str]:
    """The deliveries the warehouse holds as loaded (none before the first load)."""
    if not _table_exists(conn, "deliveries"):
        return set()
    return {row[0] for row in conn.execute("SELECT delivery_id FROM deliveries WHERE status = 'loaded'")}


def known_lines(conn: sqlite3.Connection) -> pd.DataFrame:
    """The lines already loaded (``raw_lines``), with the columns the rules and the netting need and the types of the canonical lines."""
    if not _table_exists(conn, "raw_lines"):
        rows: list[tuple] = []
    else:
        rows = conn.execute(f"SELECT {', '.join(_KNOWN_COLUMNS)} FROM raw_lines ORDER BY line_id").fetchall()
    columns = list(zip(*rows, strict=True)) if rows else [[] for _ in _KNOWN_COLUMNS]
    data = dict(zip(_KNOWN_COLUMNS, columns, strict=True))
    return pd.DataFrame({
        "line_id": pd.Series(data["line_id"], dtype="int64"), "invoice": pd.Series(data["invoice"], dtype=object),
        "stock_code": pd.Series(data["stock_code"], dtype=object), "quantity": pd.Series(data["quantity"], dtype="int64"),
        "price": pd.Series(data["price"], dtype="float64"), "customer_id": pd.array(data["customer_id"], dtype="Int64"),
        "country": pd.Series(data["country"], dtype=object), "invoice_ts": pd.to_datetime(pd.Series(data["invoice_ts"], dtype=object)).astype("datetime64[ns]"),
        "invoice_date": pd.to_datetime(pd.Series(data["invoice_date"], dtype=object)).astype("datetime64[ns]"),
        "code_kind": pd.Series(data["code_kind"], dtype=object),
    })


# --- the rules of the delivery ------------------------------------------------------------------------------------------


def _require_columns(lines: pd.DataFrame) -> None:
    missing = [name for name in CANONICAL_SCHEMA.names if name not in lines.columns]
    if missing:
        raise ValueError(f"la entrega no tiene las columnas del esquema canónico: faltan {', '.join(missing)}")


def _rule_v10(lines: pd.DataFrame, spec: DeliverySpec, loaded: set[str], cfg: Any) -> RuleResult:
    plan = delivery_plan(cfg)
    index = next((i for i, planned in enumerate(plan) if planned.delivery_id == spec.delivery_id), None)
    problem: dict[str, Any] | None = None
    if index is None:
        problem = {"reason": "not_in_plan", "plan": [p.delivery_id for p in plan]}
    elif plan[index] != spec:
        planned = plan[index]
        problem = {"reason": "other_period", "period": f"{spec.lines_from.isoformat()}/{spec.lines_to.isoformat()}",
                   "expected_period": f"{planned.lines_from.isoformat()}/{planned.lines_to.isoformat()}"}
    elif spec.delivery_id in loaded:
        problem = {"reason": "already_loaded"}
    else:
        missing = [p.delivery_id for p in plan[:index] if p.delivery_id not in loaded]
        if missing:
            problem = {"reason": "previous_not_loaded", "missing": missing}
    if problem is None:
        return _result("V10", True)
    return _result("V10", False, len(lines), _customers(lines), gross_value(lines), [{"delivery_id": spec.delivery_id, **problem}])


def _rule_v11(lines: pd.DataFrame, spec: DeliverySpec) -> RuleResult:
    start, after = pd.Timestamp(spec.lines_from), pd.Timestamp(spec.lines_to) + pd.Timedelta(days=1)
    outside = lines[(lines["invoice_date"] < start) | (lines["invoice_date"] >= after)]
    return _result("V11", outside.empty, len(outside), _customers(outside), gross_value(outside), _line_examples(outside))


def _rule_v12(lines: pd.DataFrame, known: pd.DataFrame) -> RuleResult:
    loaded = lines["line_id"].isin(known["line_id"]).to_numpy()
    repeated = lines["line_id"].duplicated(keep="first").to_numpy() & ~loaded
    bad = lines[loaded | repeated]
    reasons = np.where(loaded[loaded | repeated], "loaded", "repeated")
    examples = [{"line_id": int(r.line_id), "reason": r.reason} for r in bad.assign(reason=reasons).sort_values("line_id").head(EXAMPLE_LIMIT).itertuples()]
    return _result("V12", bad.empty, len(bad), _customers(bad), gross_value(bad), examples)


def _rule_v13(lines: pd.DataFrame, known: pd.DataFrame) -> RuleResult:
    """One customer and one country per invoice, over this delivery and what is loaded. A missing customer next to a present one is two
    customers; a missing customer on every line is consistent (a guest invoice). Examples count, never name (D26)."""
    parties = lines[["invoice", "customer_id", "country"]].drop_duplicates()
    before = known.loc[known["invoice"].isin(parties["invoice"]), ["invoice", "customer_id", "country"]].drop_duplicates()
    both = pd.concat([parties, before], ignore_index=True).drop_duplicates()
    customers = both.groupby("invoice")["customer_id"].nunique(dropna=False)
    countries = both.groupby("invoice")["country"].nunique()
    bad_invoices = customers.index[(customers > 1) | (countries > 1)]
    bad = lines[lines["invoice"].isin(bad_invoices)]
    examples = []
    for _invoice, group in sorted(bad.groupby("invoice"), key=lambda item: int(item[1]["line_id"].min()))[:EXAMPLE_LIMIT]:
        invoice = group["invoice"].iloc[0]
        examples.append({"line_id": int(group["line_id"].min()), "lines": len(group), "customers": int(customers[invoice]), "countries": int(countries[invoice])})
    return _result("V13", bad.empty, len(bad), _customers(bad), gross_value(bad), examples)


def _rule_v14(lines: pd.DataFrame, entry: ManifestEntry, delivery_path: Path) -> RuleResult:
    digest = sha256_file(delivery_path)
    reasons = [reason for reason, wrong in (("empty", lines.empty), ("rows_differ_from_manifest", len(lines) != entry.rows),
                                            ("sha256_differs_from_manifest", digest != entry.sha256)) if wrong]
    if not reasons:
        return _result("V14", True)
    example = {"delivery_id": entry.delivery_id, "reasons": reasons, "rows": len(lines), "manifest_rows": entry.rows, "sha256": digest, "manifest_sha256": entry.sha256}
    return _result("V14", False, len(lines), _customers(lines), gross_value(lines), [example])


def _rule_v22(lines: pd.DataFrame, known: pd.DataFrame, spec: DeliverySpec) -> RuleResult:
    """The cancellations, or what is left of them, that no purchase covers, netting every line known on the delivery's date (D04)."""
    everything = pd.concat([known, lines[list(_KNOWN_COLUMNS)]], ignore_index=True)
    purchases, cancellations = netting_inputs(everything)
    unmatched = net_cancellations(purchases, cancellations, spec.as_of).unmatched
    left = cancellations.set_index("line_id").loc[unmatched["cancel_line_id"]].reset_index()
    examples = [{"line_id": int(line), "stock_code": code, "unmatched_units": int(units), "value_gbp": round(float(value), 2)}
                for line, code, units, value in zip(unmatched["cancel_line_id"].head(EXAMPLE_LIMIT), left["stock_code"].head(EXAMPLE_LIMIT),
                                                    unmatched["quantity"].head(EXAMPLE_LIMIT), unmatched["value_gbp"].head(EXAMPLE_LIMIT), strict=True)]
    return _result("V22", unmatched.empty, len(unmatched), int(left["customer_id"].nunique()), float(unmatched["value_gbp"].sum()), examples)


def _rule_v30(lines: pd.DataFrame, known: pd.DataFrame) -> RuleResult:
    """Customers whose second country shows up in this delivery: the runs add up to the customers with more than one country."""
    def countries(frame: pd.DataFrame) -> pd.Series:
        return frame.dropna(subset=["customer_id"]).groupby("customer_id")["country"].nunique()

    now = countries(pd.concat([known, lines[list(_KNOWN_COLUMNS)]], ignore_index=True))
    before = countries(known).reindex(now.index, fill_value=0)
    newly = now.index[(now > 1) & (before <= 1)]
    affected = lines[lines["customer_id"].isin(newly)]
    examples = [{"line_id": int(group["line_id"].min()), "countries": int(now[customer])}
                for customer, group in sorted(affected.groupby("customer_id"), key=lambda item: int(item[1]["line_id"].min()))[:EXAMPLE_LIMIT]]
    return _result("V30", affected.empty, len(affected), len(newly), gross_value(affected), examples)


def _rule_i01(lines: pd.DataFrame, known: pd.DataFrame) -> RuleResult:
    seen = set(known["customer_id"].dropna().astype(int))
    customers = lines["customer_id"].dropna().astype(int)
    new = lines[lines["customer_id"].notna() & ~customers.reindex(lines.index).isin(seen).fillna(False)]
    return _result("I01", True, len(new), _customers(new), gross_value(new))


def _rule_i02(lines: pd.DataFrame) -> RuleResult:
    """The lines without a customer (guests) and their positive value, also as shares of the delivery's lines and positive value."""
    amount = lines["quantity"] * lines["price"]
    guests = lines["customer_id"].isna()
    positive, guest_positive = float(amount.clip(lower=0).sum()), float(amount[guests].clip(lower=0).sum())
    summary = {"lines": len(lines), "positive_value_gbp": round(positive, 2), "share_of_lines": round(int(guests.sum()) / len(lines), 6) if len(lines) else 0.0,
               "share_of_value": round(guest_positive / positive, 6) if positive else 0.0}
    return _result("I02", True, int(guests.sum()), 0, guest_positive, [summary])


def validate_delivery(lines: pd.DataFrame, spec: DeliverySpec, conn: sqlite3.Connection, cfg: Any, *, entry: ManifestEntry, delivery_path: Path,
                      run_key: str) -> ValidationReport:
    """Validate one delivery against the plan, its manifest entry and what the warehouse holds; every rule of the delivery and its lines is evaluated.

    `cfg` has ``[deliveries]`` and ``[label]`` (the plan of V10); `entry` and `delivery_path` are the manifest line of the delivery and its file,
    whose rows and SHA-256 V14 compares. The warehouse is only read.
    """
    _require_columns(lines)
    known = known_lines(conn)
    reasons = _first_reason(lines)
    roles = classify_lines(lines)["role"]
    results = {
        "V10": _rule_v10(lines, spec, loaded_deliveries(conn), cfg), "V11": _rule_v11(lines, spec), "V12": _rule_v12(lines, known),
        "V13": _rule_v13(lines, known), "V14": _rule_v14(lines, entry, Path(delivery_path)),
        "V21": _flag("V21", lines[roles == "cancellation"]), "V22": _rule_v22(lines, known, spec),
        "V28": _flag("V28", lines[lines["is_repeated_line"]]), "V29": _flag("V29", lines[lines["quantity"] >= LARGE_QUANTITY_UNITS]),
        "V30": _rule_v30(lines, known), "V31": _flag("V31", lines[lines["country"] == UNSPECIFIED_COUNTRY]),
        "I01": _rule_i01(lines, known), "I02": _rule_i02(lines),
    }
    for reason, rule_id in EXCLUSION_RULES.items():
        results[rule_id] = _flag(rule_id, lines[reasons == reason])
    report = ValidationReport(run_key, "", spec.delivery_id, len(lines), _ordered(results), ())
    _log_verdict(report)
    return report


# --- the rules of the model (their tasks evaluate them) ---------------------------------------------------------------------


def model_result(rule_id: str, *, passed: bool, rows: int = 0, customers: int = 0, value: float = 0.0, examples: list[dict] | None = None) -> RuleResult:
    """The result of a rule of the model (M01-M08, I04-I08), with the severity, scope and aggregation of its rule."""
    if rule_id not in MODEL_RULES:
        raise ValueError(f"{rule_id} no es una regla del modelo ({', '.join(MODEL_RULES)})")
    return _result(rule_id, passed, rows, customers, value, examples)


def add_results(report: ValidationReport, results: Iterable[RuleResult]) -> ValidationReport:
    """The report with `results` added in the order of ``RULES``; a rule already in the report is refused (a result is written once)."""
    current = {r.rule_id: r for r in report.results}
    for result in results:
        if result.rule_id in current:
            raise ValueError(f"la regla {result.rule_id} ya está en el reporte de {report.run_key}")
        current[result.rule_id] = result
    return replace(report, results=_ordered(current), not_evaluated=tuple(r for r in report.not_evaluated if r not in current))


def combine_reports(source: ValidationReport, delivery: ValidationReport) -> ValidationReport:
    """The report of a run: the rules of the source and then those of the delivery, in the order of ``RULES``."""
    results = {r.rule_id: r for r in [*source.results, *delivery.results]}
    return replace(delivery, source_sha256=source.source_sha256 or delivery.source_sha256, run_key=delivery.run_key or source.run_key,
                   results=_ordered(results), not_evaluated=tuple(r for r in source.not_evaluated if r not in results))


# --- report files ----------------------------------------------------------------------------------------------------


def _money(value: float) -> str:
    return f"{value:,.2f}".replace(",", " ").replace(".", ",")


def _report_document(report: ValidationReport) -> dict[str, Any]:
    return {
        "run_key": report.run_key, "source_sha256": report.source_sha256, "delivery_id": report.delivery_id, "rows_delivery": report.rows_delivery,
        "blocking_failed": report.blocking_failed, "not_evaluated": list(report.not_evaluated),
        "results": [{"rule_id": r.rule_id, "name_es": r.name_es, "severity": r.severity.value, "scope": r.scope, "aggregation": r.aggregation.value,
                     "status": r.status, "rows_affected": r.rows_affected, "customers_affected": r.customers_affected, "value_gbp": r.value_gbp,
                     "examples": r.examples} for r in report.results],
    }


def _report_markdown(report: ValidationReport) -> str:
    verdict = "Rechazado: hay reglas bloqueantes que fallan." if report.blocking_failed else "Aceptado: ninguna regla bloqueante falla."
    lines = [
        "# Reporte de validación", "", f"- Corrida: `{report.run_key}`", f"- Resultado: **{verdict}**",
        f"- SHA-256 del zip: `{report.source_sha256 or 'no disponible'}`",
        f"- Entrega: {report.delivery_id or 'ninguna'}; filas de la entrega: {report.rows_delivery}", "", "## Reglas", "",
        "| ID | Regla | Severidad | Agregación | Estado | Filas | Clientes | Valor (£) |", "| --- | --- | --- | --- | --- | ---: | ---: | ---: |",
    ]
    for r in report.results:
        lines.append(f"| {r.rule_id} | {r.name_es} | {SEVERITY_ES[r.severity]} | {r.aggregation.value} | {STATUS_ES[r.status]} | {r.rows_affected} | "
                     f"{r.customers_affected} | {_money(r.value_gbp)} |")
    if report.not_evaluated:
        lines += ["", "## No evaluadas", "", "No se pudieron evaluar porque una regla bloqueante anterior falló o porque las evalúa otra tarea: "
                  + ", ".join(report.not_evaluated) + "."]
    shown = [r for r in report.results if r.examples and (not r.passed or r.severity is Severity.INFO)]
    if shown:
        lines += ["", "## Ejemplos", ""]
        for r in shown:
            lines += [f"### {r.rule_id}: {r.name_es}", ""] + [f"- `{json.dumps(example, ensure_ascii=False)}`" for example in r.examples] + [""]
    return "\n".join(lines).rstrip("\n") + "\n"


def write_report(report: ValidationReport, out_dir: Path) -> tuple[Path, Path]:
    """Write ``latest.json`` and ``latest.md`` and a copy per run in ``history/``; return the latest pair."""
    if not _SAFE_RUN_KEY.fullmatch(report.run_key):
        raise ValueError(f"run_key {report.run_key!r} no sirve como nombre de archivo")
    out_dir = Path(out_dir)
    text_json = json.dumps(_report_document(report), indent=2, ensure_ascii=False) + "\n"
    text_md = _report_markdown(report)
    for directory, stem in ((out_dir / "history", report.run_key), (out_dir, "latest")):
        write_atomic(directory / f"{stem}.json", text_json)
        write_atomic(directory / f"{stem}.md", text_md)
    return out_dir / "latest.json", out_dir / "latest.md"


def read_report(path: Path) -> ValidationReport:
    """The report written by ``write_report`` (``latest.json`` or a copy in ``history/``)."""
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    results = [RuleResult(r["rule_id"], r["name_es"], Severity(r["severity"]), r["scope"], Aggregation(r["aggregation"]), r["status"] == "pass",
                          r["rows_affected"], r["customers_affected"], r["value_gbp"], r["examples"]) for r in document["results"]]
    return ValidationReport(document["run_key"], document["source_sha256"], document["delivery_id"], document["rows_delivery"], results,
                            tuple(document["not_evaluated"]))
