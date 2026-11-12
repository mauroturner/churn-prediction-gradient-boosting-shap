"""The task ``fit_model``: the model is trained once, at the launch, and frozen (RF17, RF20, AC20, AC21, AC23; D19, D40; plan, sections 3 and 15).
Adapted from project 03's ``launch.py`` (its D62).

At the launch it fits BG/NBD on the history before ``bgnbd_fit_cut``, the baselines (their calibrators on V1 and B* on the validation), the 24
candidates of the model (selection, M01 and calibration on V1), chooses the threshold on V2, checks the configuration against the seal and
writes the launch part of the seal, saves the artifact with its SHA-256 and registers it, in that order: a sealed configuration that does not
reproduce what was sealed (runbook R7) stops the run before anything is saved or registered, and a registered model always has its seal. An
interruption leaves the seal only, or the seal and the artifact, and repeating the launch finishes the same launch from either. In every other
run nothing is trained: the artifact is loaded only if it still has the registered SHA-256 (M03) and the configuration is compared with the
sealed one (M05: another one makes everything the run computes ``post_seal``).

This is the one module of the launch that receives the whole configuration: it needs the paths of the seal and of the artifact. The sealed
calculations it calls receive the sealed view only (D19).
"""

from __future__ import annotations

import hashlib
import json
import logging
import pickle
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from churnrisk.baselines import fit_baselines
from churnrisk.bgnbd import BGNBDParams, fit_in_warehouse
from churnrisk.config import PipelineConfig
from churnrisk.features import FEATURE_SETS, build_matrix
from churnrisk.model import LAUNCH_BLOCKS, predict_risk, train_model
from churnrisk.registry import (
    PICKLE_PROTOCOL,
    ModelBundle,
    config_fingerprint,
    load_artifact,
    save_artifact,
    seal_state,
    sealed_document,
    sealed_view,
    valid_scores_fingerprint,
    write_launch_seal,
)
from churnrisk.schema import FEATURE_COLUMNS
from churnrisk.split import labelled_rows
from churnrisk.threshold import v2_threshold
from churnrisk.warehouse import apply_schema

logger = logging.getLogger(__name__)

SEAL_STATES = {"written": "sealed", "unchanged": "match", "post_seal": "post_seal"}
# M05 as it was actually compared: the sealed configuration (True), another one (False), or no seal on disk to compare with (None, not evaluated)
M05_PASSED = {"sealed": True, "match": True, "post_seal": False, "none": None}
REGISTRY_COLUMNS = (
    "model_version", "trained_as_of", "artifact_path", "artifact_sha256", "feature_set", "feature_names_json", "country_groups_json", "params_json",
    "calibration", "threshold", "b_star", "bgnbd_json", "costs_json", "config_sha256", "selection_json", "valid_scores_sha256",
)


class LaunchRequiredError(RuntimeError):
    """There is no registered model and this run is not the launch: the model is trained once, at the launch, and in no other run."""


@dataclass(frozen=True)
class RegisteredModel:
    """The frozen model as the registry has it, its artifact already checked against its SHA-256 (M03)."""

    bundle: ModelBundle
    model_version: str
    trained_as_of: date
    feature_set: str
    threshold: float
    b_star: str
    artifact_sha256: str
    config_sha256: str
    valid_scores_sha256: str


def artifact_path(cfg: PipelineConfig) -> Path:
    return cfg.paths.models_dir / f"{cfg.model.model_version}.pkl"


def _relative(path: Path, root: Path) -> str:
    try:
        return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return str(path)


def _row(conn: sqlite3.Connection, version: str) -> tuple | None:
    return conn.execute(f"SELECT {', '.join(REGISTRY_COLUMNS)} FROM model_registry WHERE model_version = ?", (version,)).fetchone()


def load_registered(conn: sqlite3.Connection, cfg: PipelineConfig) -> RegisteredModel:
    """The model registered for ``[model] model_version``, deserialized only if its artifact has the registered SHA-256 (M03)."""
    apply_schema(conn)
    row = _row(conn, cfg.model.model_version)
    if row is None:
        raise LaunchRequiredError(f"no hay un modelo registrado con la versión {cfg.model.model_version}: se entrena en el lanzamiento")
    values = dict(zip(REGISTRY_COLUMNS, row, strict=True))
    location = Path(values["artifact_path"])
    bundle = load_artifact(location if location.is_absolute() else cfg.project_root / location, values["artifact_sha256"])
    return RegisteredModel(bundle, values["model_version"], date.fromisoformat(values["trained_as_of"]), values["feature_set"], float(values["threshold"]),
                           values["b_star"], values["artifact_sha256"], values["config_sha256"], values["valid_scores_sha256"])


def validation_risks(trained, labelled: pd.DataFrame) -> pd.DataFrame:
    """The calibrated risk of the model on every row of V1 and V2 (index ``(cut_date, customer_id)``, column ``risk``): the scores the seal
    fingerprints (``valid_scores_sha256``)."""
    model = trained.model
    rows = labelled[labelled["block"].isin(["valid_v1", "valid_v2"])]
    risk = predict_risk(model, build_matrix(rows[list(FEATURE_COLUMNS)], model.feature_set, model.country_groups))
    return pd.DataFrame({"risk": risk}, index=rows.index)


def calibrator_digest(calibrator) -> str:
    """The SHA-256 of a calibrator of the baselines, pickled as the artifact pickles it: what ``baseline_calibrators`` registers."""
    return hashlib.sha256(pickle.dumps(calibrator, protocol=PICKLE_PROTOCOL)).hexdigest()


def _bgnbd_json(params: BGNBDParams, log_likelihood: float) -> dict[str, float]:
    return {**params.as_dict(), "log_likelihood": float(log_likelihood)}


def fit_model(conn: sqlite3.Connection, cfg: PipelineConfig, *, run_key: str, as_of: date, source_sha256: str) -> dict[str, Any]:
    """Train and freeze the model if this is the launch; otherwise check the frozen one. Returns what the run records (JSON-ready).

    ``seal_state`` is ``sealed`` (this run wrote the launch part of the seal), ``match`` (the sealed configuration, reproduced or reused),
    ``post_seal`` (another configuration than the sealed one: M05 fails and nothing sealed is touched) or ``none`` (no seal file).
    """
    apply_schema(conn)
    if _row(conn, cfg.model.model_version) is not None:
        return _reuse(conn, cfg, run_key=run_key, as_of=as_of, source_sha256=source_sha256)
    if as_of != cfg.deliveries.launch_as_of:
        raise LaunchRequiredError(f"no hay un modelo registrado con la versión {cfg.model.model_version} y la corrida es la del {as_of}, no la del "
                                  f"lanzamiento ({cfg.deliveries.launch_as_of}): el modelo se entrena una sola vez, en el lanzamiento")
    return _launch(conn, cfg, run_key=run_key, as_of=as_of, source_sha256=source_sha256)


def _launch(conn: sqlite3.Connection, cfg: PipelineConfig, *, run_key: str, as_of: date, source_sha256: str) -> dict[str, Any]:
    view = sealed_view(cfg, source_sha256)
    labelled = labelled_rows(conn, LAUNCH_BLOCKS)                 # the training block, V1 and V2: the test has no label yet, and is never read
    bgnbd = fit_in_warehouse(conn, view)                         # M08
    baselines = fit_baselines(labelled, bgnbd.params, view)
    trained = train_model(labelled, view)                        # M07, M01
    choice = v2_threshold(trained.valid_v2, view)
    chosen = trained.selection.chosen
    config_sha256 = config_fingerprint(view)
    valid_sha = valid_scores_fingerprint(validation_risks(trained, labelled))
    launch = {
        "run_key": run_key, "as_of": as_of.isoformat(), "source_sha256": source_sha256, "config_sha256": config_sha256, "sealed_config": sealed_document(view),
        "model_version": view.model.model_version, "feature_set": chosen.feature_set, "params": chosen.params(),
        "country_groups": list(trained.model.country_groups), "threshold": choice.threshold, "b_star": baselines.b_star,
        "bgnbd": _bgnbd_json(bgnbd.params, bgnbd.log_likelihood), "valid_scores_sha256": valid_sha,
    }
    outcome = write_launch_seal(cfg.paths.seal, launch)          # stops the run before anything is saved if the sealed one does not reproduce (R7)
    bundle = ModelBundle(view.model.model_version, trained.model, baselines.calibrators, bgnbd.params, baselines.b_star)
    path = artifact_path(cfg)
    artifact_sha256 = save_artifact(bundle, path)
    selection = [{"feature_set": c.feature_set, **c.params(), "log_loss_v1": loss, "chosen": c == chosen} for c, loss in trained.selection.losses]
    costs = {"offer_cost": view.costs.offer_cost, "rescue_rate": view.costs.rescue_rate, "retained_value": view.costs.retained_value,
             "break_even": choice.break_even}
    values = (
        view.model.model_version, as_of.isoformat(), _relative(path, cfg.project_root), artifact_sha256, chosen.feature_set,
        json.dumps(list(FEATURE_SETS[chosen.feature_set])), json.dumps(list(trained.model.country_groups)), json.dumps(chosen.params()),
        view.model.calibration, choice.threshold, baselines.b_star, json.dumps(launch["bgnbd"]), json.dumps(costs), config_sha256,
        json.dumps(selection), valid_sha,
    )
    calibrators = [(method, view.model.model_version, calibrator_digest(calibrator)) for method, calibrator in sorted(baselines.calibrators.items())]
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(f"INSERT INTO model_registry ({', '.join(REGISTRY_COLUMNS)}) VALUES ({', '.join('?' for _ in REGISTRY_COLUMNS)})", values)
        conn.executemany("INSERT INTO baseline_calibrators (method, model_version, calibrator_sha256) VALUES (?, ?, ?)", calibrators)
        conn.execute("COMMIT")
    except BaseException as error:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        logger.warning("fit_model %s: the registration of %s rolled back (%s: %s): nothing was registered; the seal and the artifact stay",
                       run_key, view.model.model_version, type(error).__name__, error)
        raise
    state = SEAL_STATES[outcome]
    logger.info("fit_model %s: launch, set=%s threshold=%s b_star=%s seal=%s", run_key, chosen.feature_set, choice.threshold, baselines.b_star, state)
    return {
        "mode": "launch", "model_version": view.model.model_version, "feature_set": chosen.feature_set, "params": chosen.params(),
        "threshold": choice.threshold, "break_even": choice.break_even, "b_star": baselines.b_star, "artifact_sha256": artifact_sha256,
        "config_sha256": config_sha256, "valid_scores_sha256": valid_sha, "seal_state": state, "m05_passed": M05_PASSED[state],
        "rows": dict(trained.rows), "auc_v1": trained.selection.auc_v1,
    }


def _reuse(conn: sqlite3.Connection, cfg: PipelineConfig, *, run_key: str, as_of: date, source_sha256: str) -> dict[str, Any]:
    registered = load_registered(conn, cfg)                      # M03: deserialized only with the registered fingerprint
    config_sha256 = config_fingerprint(sealed_view(cfg, source_sha256))
    state = seal_state(cfg.paths.seal, config_sha256)
    logger.info("fit_model %s: reuse of %s trained %s, threshold=%s seal=%s", run_key, registered.model_version, registered.trained_as_of,
                registered.threshold, state)
    return {
        "mode": "reuse", "model_version": registered.model_version, "feature_set": registered.feature_set, "threshold": registered.threshold,
        "b_star": registered.b_star, "artifact_sha256": registered.artifact_sha256, "config_sha256": config_sha256,
        "registered_config_sha256": registered.config_sha256, "valid_scores_sha256": registered.valid_scores_sha256, "seal_state": state,
        "m05_passed": M05_PASSED[state],
    }
