"""The star model for Power BI: the marts in SQLite and one Parquet file per table (RF25, AC27; D25, D26; plan, section 19). Adapted from project
03's ``export.py``.

``build_powerbi_marts`` loads the reference tables that come from the code, the registry and the seal (``ref_*``: the methods with B*, the
reasons in Spanish, the launch's country groups, the bands, the blocks, the frozen model, the candidates and each scored customer's return by
the calculation date, with the one rule of ``tracking.customer_returns``), rebuilds the tables of ``sql/marts/powerbi`` (``star_<name>``) and
runs the controls of ``sql/checks/model``, all in one transaction: a control with rows undoes it. ``export_star_schema`` writes every table of
the semantic model with its Arrow schema and the run, the calculation date, the source and the attribution as file metadata: the versioned
tables to ``outputs/powerbi/`` and the customer-level fact, which carries the customer number, to ``outputs/private/`` only (D26). A file over
25 MB is an error before anything is written; each file is replaced atomically. Each folder's ``manifest.json`` (``STAR_MANIFEST``) is removed
before its first file is written and written again after its last one: the run, the date, the source, the attribution and each file's name,
bytes and SHA-256 (RNF05, D69). ``verify_star_schema`` checks a folder against it, so a set left half written by a failure has no manifest
and is refused.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from churnrisk.config import PipelineConfig
from churnrisk.dashboard.semantic_model import COUNTRIES_ES, FEATURES_ES, METHODS_ES, SemanticModel, Table, arrow_schema, validate_model
from churnrisk.features import FEATURE_SETS
from churnrisk.files import write_atomic
from churnrisk.ingest import ATTRIBUTION
from churnrisk.netting import customer_days, net_lines_at
from churnrisk.registry import config_fingerprint, read_seal, sealed_view
from churnrisk.schema import FEATURE_COLUMNS
from churnrisk.sensitivity import VARIANTS_ES
from churnrisk.split import BLOCKS, BLOCKS_ES
from churnrisk.tracking import customer_returns
from churnrisk.warehouse import SQL_DIR, _fail_on, apply_schema, rebuild_marts, run_checks, run_sql_file

logger = logging.getLogger(__name__)

MAX_PARQUET_BYTES = 25 * 1024 * 1024        # a versioned file stays under GitHub's limits (RNF10)
STAR_PREFIX = "star_"
METADATA_KEYS = ("churnrisk.run_key", "churnrisk.as_of", "churnrisk.source_sha256", "churnrisk.attribution")
STAR_MANIFEST = "manifest.json"
MANIFEST_VERSION = 1


@dataclass(frozen=True)
class ExportMeta:
    """What every Parquet file says about the run that wrote it (RNF07, RNF09)."""

    run_key: str
    as_of: date
    source_sha256: str
    attribution: str = ATTRIBUTION

    def metadata(self) -> dict[str, str]:
        return dict(zip(METADATA_KEYS, (self.run_key, self.as_of.isoformat(), self.source_sha256, self.attribution), strict=True))


def _replace(conn: sqlite3.Connection, name: str, columns: str, rows: list[tuple]) -> None:
    conn.execute(f"DROP TABLE IF EXISTS {name}")
    conn.execute(f"CREATE TABLE {name} ({columns})")
    if rows:
        conn.executemany(f"INSERT INTO {name} VALUES ({', '.join('?' for _ in rows[0])})", rows)


def _registered(conn: sqlite3.Connection, version: str) -> dict:
    row = conn.execute("SELECT model_version, trained_as_of, feature_set, country_groups_json, params_json, calibration, threshold, b_star, costs_json, "
                       "config_sha256, selection_json FROM model_registry WHERE model_version = ?", (version,)).fetchone()
    if row is None:
        raise RuntimeError(f"no hay un modelo registrado con la versión {version}: el modelo estrella se exporta después del lanzamiento")
    keys = ("model_version", "trained_as_of", "feature_set", "country_groups", "params", "calibration", "threshold", "b_star", "costs", "config_sha256", "selection")
    out = dict(zip(keys, row, strict=True))
    for key in ("country_groups", "params", "costs", "selection"):
        out[key] = json.loads(out[key])
    return out


def _load_references(conn: sqlite3.Connection, cfg: PipelineConfig, view, as_of: date) -> int:
    """The ``ref_*`` tables the marts read; returns the reasons each score must have (three, or every feature of a smaller set; D64)."""
    model = _registered(conn, view.model.model_version)
    seal = read_seal(cfg.paths.seal)
    sealed_config = None if seal is None else seal["launch"]["config_sha256"]
    _replace(conn, "ref_method", "method_key TEXT PRIMARY KEY, method_es TEXT, is_b_star INTEGER, sort_order INTEGER",
             [(m, label, int(m == model["b_star"]), i) for i, (m, label) in enumerate(METHODS_ES.items(), start=1)])
    _replace(conn, "ref_reason", "reason_key TEXT PRIMARY KEY, feature_es TEXT, description_es TEXT, sort_order INTEGER",
             [(f, *FEATURES_ES[f], i) for i, f in enumerate(FEATURE_COLUMNS, start=1)])
    _replace(conn, "ref_country", "country_key INTEGER PRIMARY KEY, country_group TEXT UNIQUE, country_es TEXT",
             [(i, g, COUNTRIES_ES.get(g, g)) for i, g in enumerate(model["country_groups"], start=1)])
    _replace(conn, "ref_band", "band_key INTEGER PRIMARY KEY, band_es TEXT, p_low REAL, p_high REAL",
             [(b, f"{(b - 1) / 10:.1f} a {b / 10:.1f}".replace(".", ","), (b - 1) / 10, b / 10) for b in range(1, 11)])
    _replace(conn, "ref_block", "block TEXT PRIMARY KEY, block_es TEXT", [(b, BLOCKS_ES[b]) for b in BLOCKS])
    _replace(conn, "ref_variant", "variant TEXT PRIMARY KEY, variant_es TEXT, sort_order INTEGER",
             [(v, label, i) for i, (v, label) in enumerate(VARIANTS_ES.items(), start=1)])
    params_es = ", ".join(f"{k} {v}" for k, v in model["params"].items())
    state = "sealed" if model["config_sha256"] == sealed_config else "post_seal"
    costs = model["costs"]
    _replace(conn, "ref_model", "model_version TEXT, feature_set TEXT, params_es TEXT, calibration TEXT, threshold REAL, offer_cost REAL, rescue_rate REAL, "
             "retained_value REAL, break_even REAL, b_star TEXT, trained_as_of TEXT, config_sha256 TEXT, seal_state TEXT",
             [(model["model_version"], model["feature_set"], params_es, model["calibration"], model["threshold"], costs["offer_cost"], costs["rescue_rate"],
               costs["retained_value"], costs["break_even"], model["b_star"], model["trained_as_of"], model["config_sha256"], state)])
    _replace(conn, "ref_selection", "feature_set TEXT, learning_rate REAL, max_leaf_nodes INTEGER, min_samples_leaf INTEGER, log_loss_v1 REAL, chosen INTEGER",
             [(c["feature_set"], c["learning_rate"], c["max_leaf_nodes"], c["min_samples_leaf"], c["log_loss_v1"], int(c["chosen"])) for c in model["selection"]])
    test_sealed = int(seal is not None and seal.get("test") is not None and seal["test"]["config_sha256"] == config_fingerprint(view))
    _replace(conn, "ref_flags", "test_sealed INTEGER", [(test_sealed,)])
    scores = pd.read_sql_query("SELECT cut_date, customer_id FROM model_scores WHERE as_of_date <= ?", conn, params=(as_of.isoformat(),))
    scores["cut_date"] = [date.fromisoformat(v) for v in scores["cut_date"]]
    returns = customer_returns(scores, customer_days(net_lines_at(conn, as_of)), as_of, view.label.horizon_days)
    _replace(conn, "ref_customer_return", "cut_date TEXT, customer_id INTEGER, returned INTEGER, first_return_date TEXT, PRIMARY KEY (cut_date, customer_id)",
             [(c.isoformat(), int(k), int(r), None if pd.isna(d) else d.date().isoformat())
              for c, k, r, d in zip(returns["cut_date"], returns["customer_id"], returns["returned"], returns["first_return_date"], strict=True)])
    return min(view.evaluation.shap_top_reasons, len(set(FEATURE_SETS[model["feature_set"]])))


def build_powerbi_marts(conn: sqlite3.Connection, cfg: PipelineConfig, source_sha256: str, as_of: date) -> None:
    """Rebuild the reference tables and the star model and run its controls in one transaction; a control with rows undoes it all
    (``CheckFailedError``) and the marts keep what they had."""
    apply_schema(conn)
    view = sealed_view(cfg, source_sha256)
    conn.execute("BEGIN IMMEDIATE")
    try:
        reasons = _load_references(conn, cfg, view, as_of)
        params = {"first_date": view.deliveries.first_date.isoformat(), "last_date": view.deliveries.last_date.isoformat(),
                  "min_cell_customers": cfg.site.min_cell_customers, "reasons_per_score": reasons}
        rebuild_marts(conn, "powerbi", params)
        _fail_on(run_checks(conn, "model", params), f"star model at {as_of}", "La exportación del modelo estrella")
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        logger.warning("star model at %s rolled back: the marts keep what they had", as_of)
        raise


def _arrow_table(frame: pd.DataFrame, table: Table) -> pa.Table:
    """The frame as an Arrow table with the model's schema; a key with a missing value is an error."""
    for key in table.key:
        if frame[key].isna().any():
            raise ValueError(f"{table.name}[{key}] tiene valores vacíos: una clave no puede")
    arrays = []
    for column in table.columns:
        series = frame[column.name]
        if column.dtype == "date":
            values = [None if pd.isna(v) else date.fromisoformat(str(v)[:10]) for v in series]
            arrays.append(pa.array(values, type=pa.date32()))
        elif column.dtype == "bool":
            arrays.append(pa.array([None if pd.isna(v) else bool(v) for v in series], type=pa.bool_()))
        elif column.dtype in ("int32", "int64"):
            arrays.append(pa.array([None if pd.isna(v) else int(v) for v in series], type=pa.int32() if column.dtype == "int32" else pa.int64()))
        elif column.dtype == "float64":
            arrays.append(pa.array([None if pd.isna(v) else float(v) for v in series], type=pa.float64()))
        else:
            arrays.append(pa.array([None if pd.isna(v) else str(v) for v in series], type=pa.string()))
    return pa.Table.from_arrays(arrays, schema=arrow_schema(table))


def _serialize(conn: sqlite3.Connection, table: Table, metadata: dict[str, str]) -> bytes:
    frame = pd.read_sql_query(f"SELECT {', '.join(table.column_names)} FROM {STAR_PREFIX}{table.name} ORDER BY {', '.join(table.key)}", conn)
    arrow = _arrow_table(frame, table)
    arrow = arrow.replace_schema_metadata({**(arrow.schema.metadata or {}), **{k.encode(): v.encode("utf-8") for k, v in metadata.items()}})
    sink = pa.BufferOutputStream()
    pq.write_table(arrow, sink, compression="snappy")
    return sink.getvalue().to_pybytes()


def _manifest_text(meta: ExportMeta, files: list[dict]) -> str:
    document = {"version": MANIFEST_VERSION, **dict(zip(("run_key", "as_of", "source_sha256", "attribution"), meta.metadata().values(), strict=True)),
                "files": files}
    return json.dumps(document, ensure_ascii=False, sort_keys=True, indent=1) + "\n"


def verify_star_schema(folder: Path) -> list[str]:
    """What does not match in `folder` against its ``manifest.json`` (empty when everything does): a missing or unreadable manifest, a listed
    file that is missing or whose bytes or SHA-256 differ, and a Parquet file the manifest does not list."""
    folder = Path(folder)
    try:
        manifest = json.loads((folder / STAR_MANIFEST).read_text(encoding="utf-8"))
        listed = {entry["name"]: entry for entry in manifest["files"]}
    except (OSError, ValueError, KeyError, TypeError) as error:
        return [f"{folder / STAR_MANIFEST}: no hay un manifiesto legible ({type(error).__name__}); el conjunto no se usa"]
    problems = []
    for name, entry in listed.items():
        path = folder / name
        if not path.is_file():
            problems.append(f"{name}: falta el archivo que lista el manifiesto")
            continue
        data = path.read_bytes()
        if len(data) != entry.get("bytes") or hashlib.sha256(data).hexdigest() != entry.get("sha256"):
            problems.append(f"{name}: los bytes no son los del manifiesto")
    problems += [f"{path.name}: el manifiesto no lo lista" for path in sorted(folder.glob("*.parquet")) if path.name not in listed]
    return problems


def export_star_schema(conn: sqlite3.Connection, out_dir: Path, private_dir: Path, model: SemanticModel, meta: ExportMeta, cfg: PipelineConfig) -> list[Path]:
    """Rebuild the marts and write one Parquet file per table of `model`: the versioned ones to `out_dir`, the private one to `private_dir`.
    Returns the paths in the model's order. The model is checked first and every file is serialized and measured before any is written."""
    problems = validate_model(model)
    if problems:
        raise ValueError(f"el modelo semántico es incoherente: {problems[0]}")
    if Path(out_dir).resolve() == Path(private_dir).resolve():
        raise ValueError("la carpeta privada no puede ser la versionada: el hecho por cliente lleva el número de cliente (D26)")
    build_powerbi_marts(conn, cfg, meta.source_sha256, meta.as_of)
    payloads = {}
    for table in model.tables:
        data = _serialize(conn, table, meta.metadata())
        if not table.private and len(data) > MAX_PARQUET_BYTES:
            raise ValueError(f"{table.name}.parquet pesa {len(data)} bytes, más de {MAX_PARQUET_BYTES}: no se escribe nada")
        payloads[table.name] = data
    folders = {False: Path(out_dir), True: Path(private_dir)}
    for folder in folders.values():               # a set being rewritten has no manifest until its last file is written
        (folder / STAR_MANIFEST).unlink(missing_ok=True)
    paths = []
    for table in model.tables:
        path = folders[table.private] / f"{table.name}.parquet"
        write_atomic(path, payloads[table.name])
        paths.append(path)
    for private, folder in folders.items():
        files = [{"name": f"{t.name}.parquet", "bytes": len(payloads[t.name]), "sha256": hashlib.sha256(payloads[t.name]).hexdigest()}
                 for t in model.tables if t.private == private]
        if files:
            write_atomic(folder / STAR_MANIFEST, _manifest_text(meta, files))
    logger.info("star model at %s: %d versioned files in %s and %d private in %s", meta.as_of, sum(not t.private for t in model.tables), out_dir,
                sum(t.private for t in model.tables), private_dir)
    return paths


RUN_TABLE = "dim_pipeline_run"


def export_run_table(conn: sqlite3.Connection, out_dir: Path, model: SemanticModel, meta: ExportMeta) -> Path | None:
    """Rewrite only ``dim_pipeline_run.parquet`` from ``pipeline_runs`` and its entry in the folder's manifest: what closing a run, a failure or
    a run with no delivery changes (plan, sections 3 and 22). Nothing is created that was not there: without an exported, verified set it
    returns None. The other files keep their bytes."""
    out_dir = Path(out_dir)
    manifest_path = out_dir / STAR_MANIFEST
    if not manifest_path.is_file() or verify_star_schema(out_dir):
        return None
    table = model.table(RUN_TABLE)
    conn.execute("BEGIN IMMEDIATE")
    try:
        run_sql_file(conn, SQL_DIR / "marts" / "powerbi" / "mart_08_dim_pipeline_run.sql")
        data = _serialize(conn, table, meta.metadata())
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    path = write_atomic(out_dir / f"{RUN_TABLE}.parquet", data)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for entry in manifest["files"]:
        if entry["name"] == path.name:
            entry.update(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
    write_atomic(manifest_path, json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=1) + "\n")
    logger.info("run table rewritten: %s (%d bytes)", path.name, len(data))
    return path
