"""Deliveries: the feed that stands in for the monthly export of a sales system over a static file (RF07, D11); adapted from project 02.

The canonical lines are cut into a fixed plan: the launch ``L<yyyy-mm>`` (from ``first_date`` to ``launch_as_of``), one monthly delivery
``M<yyyy-mm>`` per calendar month after it and, when ``last_date`` is not the last day of its month, a close ``C<yyyy-mm>`` with the days of
that month. Each delivery's calculation date is the last day of its period, and the cut it scores is the day after, while that day is a cut
of ``[label]``; the close scores none. A line belongs to the delivery of its invoice date (the first date of its invoice), so an invoice is
never split and a cancellation travels with the date of its own invoice.

Each delivery is a Parquet file with the schema of the canonical lines, listed in ``manifest.json`` (``{"version": 1, "entries": [...]}``,
written to a temporary file and renamed) with its period, rows and SHA-256 and a status that moves from ``published`` to ``loaded`` (or
``rejected``). Publishing is idempotent: the same rows give the same bytes and leave the manifest untouched; a loaded delivery is never
replaced. The next pending delivery is always the first of the plan that is not loaded (runbook R4).
"""

from __future__ import annotations

import calendar
import hashlib
import io
import json
import logging
from dataclasses import asdict, dataclass, fields, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from churnrisk.config import DeliveriesConfig, LabelConfig
from churnrisk.files import write_atomic
from churnrisk.ingest import ATTRIBUTION, ATTRIBUTION_KEY
from churnrisk.schema import CANONICAL_SCHEMA

logger = logging.getLogger(__name__)

MANIFEST_NAME = "manifest.json"
MANIFEST_VERSION = 1
DELIVERY_KINDS = ("launch", "monthly", "close")
DELIVERY_STATUSES = ("published", "loaded", "rejected")
DELIVERY_ID_KEY = b"churnrisk.delivery_id"
PERIOD_KEY = b"churnrisk.period"
_DATE_FIELDS = ("lines_from", "lines_to", "as_of")


class _HasCalendar(Protocol):     # PipelineConfig and SealedConfig both have these two sections
    deliveries: DeliveriesConfig
    label: LabelConfig


@dataclass(frozen=True)
class DeliverySpec:
    """One delivery of the plan: the invoice dates it holds, its calculation date (the last of them) and the cut it scores (or None)."""

    delivery_id: str
    kind: str
    lines_from: date
    lines_to: date
    as_of: date
    cut: date | None


@dataclass(frozen=True)
class ManifestEntry:
    delivery_id: str
    kind: str
    lines_from: date
    lines_to: date
    as_of: date
    cut: date | None
    rows: int
    sha256: str
    file: str
    published_at: str
    status: str
    run_key: str | None


def delivery_plan(cfg: _HasCalendar) -> list[DeliverySpec]:
    """The fixed plan of D11: the launch, the monthly deliveries and the close, contiguous, each with its calculation date and its cut."""
    d, label = cfg.deliveries, cfg.label

    def cut_after(as_of: date) -> date | None:
        day = as_of + timedelta(days=1)
        return day if day.day == 1 and label.first_cut <= day <= label.last_cut else None

    plan = [DeliverySpec(f"L{d.launch_as_of:%Y-%m}", "launch", d.first_date, d.launch_as_of, d.launch_as_of, cut_after(d.launch_as_of))]
    start = d.launch_as_of + timedelta(days=1)
    while start <= d.last_date:
        month_end = start.replace(day=calendar.monthrange(start.year, start.month)[1])
        end = min(month_end, d.last_date)
        kind, prefix = ("monthly", "M") if end == month_end else ("close", "C")
        plan.append(DeliverySpec(f"{prefix}{start:%Y-%m}", kind, start, end, end, cut_after(end) if kind == "monthly" else None))
        start = end + timedelta(days=1)
    return plan


# --- manifest ---------------------------------------------------------------------------------------------------


def _entry_from(raw: Any) -> ManifestEntry:
    names = {f.name for f in fields(ManifestEntry)}
    if not isinstance(raw, dict) or set(raw) != names:
        raise KeyError(f"claves distintas de las esperadas: {sorted(names ^ set(raw)) if isinstance(raw, dict) else raw!r}")
    values = dict(raw)
    for key in _DATE_FIELDS:
        values[key] = date.fromisoformat(values[key])
    values["cut"] = None if values["cut"] is None else date.fromisoformat(values["cut"])
    if not isinstance(values["rows"], int) or isinstance(values["rows"], bool) or values["rows"] < 0:
        raise TypeError(f"rows: se esperaba un entero, se recibió {values['rows']!r}")
    for key in ("delivery_id", "sha256", "file", "published_at"):
        if not isinstance(values[key], str):
            raise TypeError(f"{key}: se esperaba un texto, se recibió {values[key]!r}")
    if values["kind"] not in DELIVERY_KINDS:
        raise ValueError(f"kind: {values['kind']!r} no es uno de {', '.join(DELIVERY_KINDS)}")
    if values["status"] not in DELIVERY_STATUSES:
        raise ValueError(f"status: {values['status']!r} no es uno de {', '.join(DELIVERY_STATUSES)}")
    if values["run_key"] is not None and not isinstance(values["run_key"], str):
        raise TypeError(f"run_key: se esperaba un texto o null, se recibió {values['run_key']!r}")
    return ManifestEntry(**values)


def read_manifest(path: Path) -> list[ManifestEntry]:
    """The entries in the order they were published; a missing manifest is an empty list."""
    path = Path(path)
    if not path.exists():
        return []
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict) or document.get("version") != MANIFEST_VERSION or set(document) != {"version", "entries"}:
            raise KeyError("versión o claves de primer nivel inesperadas")
        entries = [_entry_from(raw) for raw in document["entries"]]
        ids = [e.delivery_id for e in entries]
        if len(set(ids)) != len(ids):
            raise ValueError("hay entregas repetidas")
    except (ValueError, KeyError, TypeError) as error:
        raise ValueError(f"{path} no es un manifiesto de entregas válido: {error}") from error
    return entries


def _write_manifest(path: Path, entries: list[ManifestEntry]) -> None:
    def encode(entry: ManifestEntry) -> dict[str, Any]:
        document = asdict(entry)
        for key in _DATE_FIELDS:
            document[key] = document[key].isoformat()
        document["cut"] = None if entry.cut is None else entry.cut.isoformat()
        return document

    write_atomic(Path(path), json.dumps({"version": MANIFEST_VERSION, "entries": [encode(e) for e in entries]}, indent=2, ensure_ascii=False) + "\n")


def next_pending(manifest: Path, plan: list[DeliverySpec]) -> DeliverySpec | None:
    """The first delivery of the plan that is not loaded: the next one to run, or None when the plan is complete.

    A delivery that is ``published`` or ``rejected`` stays the pending one (a failed run is repeated with the same delivery). An entry that is
    not in the plan, has another period, or is loaded after one that is not is an error (runbook R4): the plan is never skipped.
    """
    entries = {e.delivery_id: e for e in read_manifest(manifest)}
    by_id = {spec.delivery_id: spec for spec in plan}
    for delivery_id, entry in entries.items():
        spec = by_id.get(delivery_id)
        if spec is None:
            raise ValueError(f"el manifiesto trae la entrega {delivery_id}, que no está en el plan (runbook R4)")
        if (entry.kind, entry.lines_from, entry.lines_to, entry.as_of, entry.cut) != (spec.kind, spec.lines_from, spec.lines_to, spec.as_of, spec.cut):
            raise ValueError(f"la entrega {delivery_id} tiene otro período en el manifiesto ({entry.lines_from} a {entry.lines_to}) que en el plan "
                             f"({spec.lines_from} a {spec.lines_to}) (runbook R4)")
    pending: DeliverySpec | None = None
    for spec in plan:
        entry = entries.get(spec.delivery_id)
        loaded = entry is not None and entry.status == "loaded"
        if pending is None:
            if not loaded:
                pending = spec
        elif loaded:
            raise ValueError(f"la entrega {spec.delivery_id} está cargada pero la anterior, {pending.delivery_id}, no lo está (runbook R4)")
    return pending


def mark_delivery(manifest: Path, delivery_id: str, status: str, run_key: str | None = None) -> None:
    """Set the status of a delivery (and its run, if given); everything else in the manifest is kept.

    A loaded delivery stays loaded by the run that loaded it: marking it rejected or published, or loaded by another run, is refused and the
    manifest is not touched, because ``next_pending`` would offer it again and its lines would load twice (project 03, D86 and D93). Out of
    ``published`` and ``rejected`` every status is allowed: a rejected delivery is published again and loaded by a later run."""
    if status not in DELIVERY_STATUSES:
        raise ValueError(f"status: {status!r} no es uno de {', '.join(DELIVERY_STATUSES)}")
    entries = read_manifest(manifest)
    entry = next((e for e in entries if e.delivery_id == delivery_id), None)
    if entry is None:
        raise ValueError(f"no hay una entrega {delivery_id} en el manifiesto {manifest}")
    if entry.status == "loaded" and (status != "loaded" or (run_key is not None and run_key != entry.run_key)):
        raise ValueError(f"la entrega {delivery_id} ya está cargada por la corrida {entry.run_key!r} y no pasa a {status!r}"
                         f"{'' if run_key is None else f' de la corrida {run_key!r}'}: sus líneas ya están en el almacén (runbook R4)")
    _write_manifest(Path(manifest), [
        replace(e, status=status, run_key=run_key if run_key is not None else e.run_key) if e.delivery_id == delivery_id else e for e in entries
    ])
    logger.info("manifest %s: delivery %s marked %s", manifest, delivery_id, status)


# --- publishing ---------------------------------------------------------------------------------------------------


def delivery_rows(spec: DeliverySpec, lines: pd.DataFrame) -> pd.DataFrame:
    """The lines whose invoice date falls in the period of `spec` (a selection; `lines` is not touched)."""
    days = lines["invoice_date"]
    return lines.loc[(days >= pd.Timestamp(spec.lines_from)) & (days < pd.Timestamp(spec.lines_to + timedelta(days=1)))]


def assert_covered(lines: pd.DataFrame, plan: list[DeliverySpec]) -> None:
    """Every line must fall in some period of the plan; otherwise it would never be delivered."""
    days = lines["invoice_date"]
    outside = int(((days < pd.Timestamp(plan[0].lines_from)) | (days >= pd.Timestamp(plan[-1].lines_to + timedelta(days=1)))).sum())
    if outside:
        raise ValueError(f"{outside} líneas tienen una fecha de factura fuera de todas las entregas del plan ({plan[0].lines_from} a "
                         f"{plan[-1].lines_to}) y no se entregarían nunca")


def read_delivery(path: Path) -> pd.DataFrame:
    """The lines of a published delivery, with the column types of the canonical lines (``customer_id`` nullable)."""
    table = pq.read_table(Path(path))
    frame = table.drop(["customer_id"]).to_pandas()
    frame.insert(CANONICAL_SCHEMA.names.index("customer_id"), "customer_id",
                 pd.Series(table.column("customer_id").to_numpy(zero_copy_only=False)).astype("Int64"))
    for column in ("invoice_ts", "invoice_date"):
        frame[column] = frame[column].astype("datetime64[ns]")
    return frame


def _serialise(spec: DeliverySpec, rows: pd.DataFrame) -> bytes:
    table = pa.Table.from_pandas(rows.reset_index(drop=True)[CANONICAL_SCHEMA.names], schema=CANONICAL_SCHEMA, preserve_index=False)
    metadata = {
        **(table.schema.metadata or {}), DELIVERY_ID_KEY: spec.delivery_id.encode("ascii"),
        PERIOD_KEY: f"{spec.lines_from.isoformat()}/{spec.lines_to.isoformat()}".encode("ascii"), ATTRIBUTION_KEY: ATTRIBUTION.encode("utf-8"),
    }
    sink = io.BytesIO()
    pq.write_table(table.replace_schema_metadata(metadata), sink)
    return sink.getvalue()


def publish(spec: DeliverySpec, lines: pd.DataFrame, out_dir: Path) -> ManifestEntry:
    """Write the lines of `spec`'s period as ``<out_dir>/<delivery_id>.parquet`` and list it in ``<out_dir>/manifest.json``.

    The same rows always give the same bytes, so publishing again changes nothing (not even the entry), and a file that went missing or was
    damaged is written again. If the rows changed, a delivery that is not loaded is replaced (and goes back to ``published``); a loaded one is
    never replaced: its rows are already in the warehouse.
    """
    out_dir = Path(out_dir)
    manifest_path = out_dir / MANIFEST_NAME
    rows = delivery_rows(spec, lines)
    payload = _serialise(spec, rows)
    digest = hashlib.sha256(payload).hexdigest()
    entries = read_manifest(manifest_path)
    existing = next((e for e in entries if e.delivery_id == spec.delivery_id), None)
    target = out_dir / f"{spec.delivery_id}.parquet"
    if existing is not None and existing.sha256 == digest:
        if not target.exists() or target.read_bytes() != payload:
            write_atomic(target, payload)
        return existing
    if existing is not None and existing.status == "loaded":
        raise ValueError(f"la entrega {spec.delivery_id} ya está cargada en el almacén y sus líneas cambiaron en la fuente "
                         f"({existing.sha256[:12]} → {digest[:12]}); no se publica de nuevo (runbook R4)")
    write_atomic(target, payload)
    entry = ManifestEntry(spec.delivery_id, spec.kind, spec.lines_from, spec.lines_to, spec.as_of, spec.cut, len(rows), digest, target.name,
                          datetime.now(UTC).isoformat(timespec="seconds"), "published", None)
    _write_manifest(manifest_path, [entry if e.delivery_id == spec.delivery_id else e for e in entries] if existing else [*entries, entry])
    logger.info("published %s: %d rows, sha256 %s", spec.delivery_id, entry.rows, digest)
    return entry
