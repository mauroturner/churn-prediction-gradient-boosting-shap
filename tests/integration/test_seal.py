"""The frozen launch and its seal on the quick history (U16, AC20, AC21, AC23; RF20; D19, D40; M03, M05): the launch writes the launch part of
the seal once; a rebuild with the sealed configuration reproduces it; another configuration is ``post_seal`` and leaves the seal byte for byte;
the later runs reuse the artifact unchanged and one that does not have its registered SHA-256 is refused before it is deserialized."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import shutil
from pathlib import Path

import pandas as pd
import pytest

from churnrisk.baselines import fit_baselines
from churnrisk.bgnbd import fit_in_warehouse
from churnrisk.features import build_matrix
from churnrisk.model import LAUNCH_BLOCKS, predict_risk, train_model
from churnrisk.schema import FEATURE_COLUMNS
from churnrisk.split import labelled_rows
from churnrisk.threshold import v2_threshold
from churnrisk.launch import LaunchRequiredError, artifact_path, fit_model, load_registered
from churnrisk.registry import (
    ArtifactMismatchError, SealMismatchError, config_fingerprint, read_seal, sealed_document, sealed_view, valid_scores_fingerprint,
)
from churnrisk.warehouse import connect
from tests.fixtures.history import quick_config


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fresh_launch(folder: Path, launch_cuts: Path, history, **sections):
    """A new folder with a copy of the launch warehouse (no model registered) and of the history's seal, and its configuration: the quick one
    with `sections` replaced. Returns ``(cfg, fit_model's result)`` of the launch run."""
    cfg = quick_config(folder, **sections)
    cfg.paths.warehouse.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(launch_cuts, cfg.paths.warehouse)
    cfg.paths.seal.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(history.cfg.paths.seal, cfg.paths.seal)
    conn = connect(cfg.paths.warehouse)
    try:
        return cfg, fit_model(conn, cfg, run_key="r1", as_of=cfg.deliveries.launch_as_of, source_sha256=history.view.source_sha256)
    finally:
        conn.close()


# --- the RED of U16 ------------------------------------------------------------------------------------------------------


def test_other_costs_after_the_seal_are_post_seal_and_the_seal_stays(quick_history, launch_cuts, tmp_path):
    """A rebuild from scratch after the seal with another offer cost: it trains and registers its own model (M05 fails: everything it computes
    is post_seal), and the seal keeps, byte for byte, what the sealed launch wrote."""
    sealed = quick_history.cfg.paths.seal.read_bytes()
    launch = quick_history.runs[0].fit
    other = dataclasses.replace(quick_history.cfg.costs, offer_cost=7.0)
    cfg, fit = fresh_launch(tmp_path / "other_costs", launch_cuts, quick_history, costs=other)
    assert (fit["mode"], fit["seal_state"], fit["m05_passed"]) == ("launch", "post_seal", False)
    assert fit["config_sha256"] == config_fingerprint(sealed_view(cfg, quick_history.view.source_sha256)) != launch["config_sha256"]
    assert cfg.paths.seal.read_bytes() == sealed, "the seal is never rewritten by another configuration"
    assert read_seal(cfg.paths.seal)["launch"]["sealed_config"]["costs"]["offer_cost"] == quick_history.cfg.costs.offer_cost
    conn = connect(cfg.paths.warehouse)
    try:
        registered = load_registered(conn, cfg)
        assert registered.config_sha256 == fit["config_sha256"] and registered.threshold == fit["threshold"]
        later = fit_model(conn, cfg, run_key="r2", as_of=quick_history.runs[1].spec.as_of, source_sha256=quick_history.view.source_sha256)
    finally:
        conn.close()
    assert (later["mode"], later["seal_state"], later["m05_passed"]) == ("reuse", "post_seal", False)
    assert cfg.paths.seal.read_bytes() == sealed
    # a later run with other costs on the sealed model: what decides M05 is this run's configuration, not the one the model was trained with
    folder = tmp_path / "sealed_model_other_costs"
    on_sealed = quick_config(folder, costs=other)
    on_sealed.paths.seal.parent.mkdir(parents=True)
    shutil.copy2(quick_history.cfg.paths.seal, on_sealed.paths.seal)
    shutil.copy2(quick_history.warehouse, on_sealed.paths.warehouse)
    conn = connect(on_sealed.paths.warehouse)
    try:
        reused = fit_model(conn, on_sealed, run_key="r7", as_of=quick_history.runs[-1].spec.as_of, source_sha256=quick_history.view.source_sha256)
    finally:
        conn.close()
    assert (reused["mode"], reused["seal_state"], reused["registered_config_sha256"]) == ("reuse", "post_seal", launch["config_sha256"])
    assert on_sealed.paths.seal.read_bytes() == sealed


# --- the launch part of the seal --------------------------------------------------------------------------------------------


def test_the_launch_seals_what_it_chose_and_a_rebuild_with_the_sealed_configuration_reproduces_it(quick_history, launch_cuts, tmp_path):
    """AC20 and AC21: the launch part holds the whole sealed view, the chosen set, its parameters, the country groups, the threshold chosen on V2,
    B* chosen on the validation, BG/NBD and the fingerprint of the validation risks; a rebuild from scratch with the same configuration
    reproduces every value (the seal is not rewritten) and the same artifact."""
    launch = quick_history.runs[0].fit
    part = read_seal(quick_history.cfg.paths.seal)["launch"]
    assert part["sealed_config"] == sealed_document(quick_history.view) and part["config_sha256"] == launch["config_sha256"]
    assert (part["run_key"], part["as_of"], part["source_sha256"]) == ("r1", "2011-07-31", quick_history.view.source_sha256)
    assert (part["feature_set"], part["threshold"], part["b_star"], part["valid_scores_sha256"]) == (
        launch["feature_set"], launch["threshold"], launch["b_star"], launch["valid_scores_sha256"])
    assert part["b_star"] in quick_history.view.baselines.strongest_candidates and 0.01 <= part["threshold"] <= 0.99
    assert set(part["bgnbd"]) == {"r", "alpha", "a", "b", "log_likelihood"} and part["params"] == launch["params"]
    assert part["country_groups"][-1] == "Otros" and launch["seal_state"] == "sealed"
    # every sealed value is what the public functions give on the launch's own rows: B* on the validation, the threshold on V2 only, and the
    # fingerprint of the calibrated risks of V1 and V2
    conn = connect(launch_cuts)
    try:
        labelled = labelled_rows(conn, LAUNCH_BLOCKS)
        bgnbd = fit_in_warehouse(conn, quick_history.view)
    finally:
        conn.close()
    trained = train_model(labelled, quick_history.view)
    valid = labelled[labelled["block"].isin(["valid_v1", "valid_v2"])]
    risks = predict_risk(trained.model, build_matrix(valid[list(FEATURE_COLUMNS)], trained.model.feature_set, trained.model.country_groups))
    assert part["valid_scores_sha256"] == valid_scores_fingerprint(pd.DataFrame({"risk": risks}, index=valid.index))
    assert part["threshold"] == v2_threshold(trained.valid_v2, quick_history.view).threshold
    assert part["b_star"] == fit_baselines(labelled, bgnbd.params, quick_history.view).b_star and part["feature_set"] == trained.selection.chosen.feature_set
    assert part["bgnbd"] == {**bgnbd.params.as_dict(), "log_likelihood": bgnbd.log_likelihood}
    assert part["country_groups"] == list(trained.model.country_groups) and part["params"] == trained.selection.chosen.params()
    cfg, again = fresh_launch(tmp_path / "rebuild", launch_cuts, quick_history)
    assert (again["seal_state"], again["m05_passed"]) == ("match", True)
    assert {k: again[k] for k in ("feature_set", "threshold", "b_star", "valid_scores_sha256", "config_sha256")} == {
        k: launch[k] for k in ("feature_set", "threshold", "b_star", "valid_scores_sha256", "config_sha256")}
    assert cfg.paths.seal.read_bytes() == quick_history.cfg.paths.seal.read_bytes()
    assert again["artifact_sha256"] == launch["artifact_sha256"] == sha(artifact_path(cfg)), "the same configuration gives the same artifact"


def test_a_sealed_configuration_that_does_not_reproduce_stops_the_launch_before_anything_is_saved(quick_history, launch_cuts, tmp_path):
    """Runbook R7: the seal says another threshold for the same configuration; the rebuild names it and saves and registers nothing."""
    folder = tmp_path / "mismatch"
    cfg = quick_config(folder)
    cfg.paths.seal.parent.mkdir(parents=True)
    document = json.loads(quick_history.cfg.paths.seal.read_text(encoding="utf-8"))
    document["launch"]["threshold"] = round(document["launch"]["threshold"] + 0.01, 2)
    cfg.paths.seal.write_text(json.dumps(document), encoding="utf-8")
    shutil.copy2(launch_cuts, cfg.paths.warehouse)
    before = sha(cfg.paths.warehouse)
    conn = connect(cfg.paths.warehouse)
    try:
        with pytest.raises(SealMismatchError, match=r"threshold: .* sellado, .* en esta corrida"):
            fit_model(conn, cfg, run_key="r1", as_of=cfg.deliveries.launch_as_of, source_sha256=quick_history.view.source_sha256)
        assert conn.execute("SELECT COUNT(*) FROM model_registry").fetchone()[0] == 0
    finally:
        conn.close()
    assert not artifact_path(cfg).exists() and not cfg.paths.models_dir.exists() and sha(cfg.paths.warehouse) == before


def test_later_runs_reuse_the_artifact_and_one_with_another_hash_is_refused_before_loading(quick_history, launch_cuts, tmp_path):
    """AC23: every run after the launch trains nothing and reuses the registered artifact, whose bytes never change; an artifact replaced on
    disk is refused (M03) before any byte of it is deserialized, and the warehouse is not touched."""
    launch, later = quick_history.runs[0].fit, [r.fit for r in quick_history.runs[1:]]
    assert {(f["mode"], f["artifact_sha256"], f["seal_state"], f["m05_passed"]) for f in later} == {("reuse", launch["artifact_sha256"], "match", True)}
    assert sha(artifact_path(quick_history.cfg)) == launch["artifact_sha256"]
    cfg, _fit = fresh_launch(tmp_path / "tampered", launch_cuts, quick_history)     # a launch of its own, so its artifact can be damaged
    data = bytearray(artifact_path(cfg).read_bytes())
    data[-2] ^= 0xFF
    artifact_path(cfg).write_bytes(bytes(data))
    before = sha(cfg.paths.warehouse)
    conn = connect(cfg.paths.warehouse)
    try:
        with pytest.raises(ArtifactMismatchError, match="M03"):
            fit_model(conn, cfg, run_key="r7", as_of=quick_history.runs[-1].spec.as_of, source_sha256=quick_history.view.source_sha256)
    finally:
        conn.close()
    assert sha(cfg.paths.warehouse) == before


def test_without_a_registered_model_only_the_launch_trains(quick_history, launch_cuts, tmp_path):
    cfg = quick_config(tmp_path / "late")
    cfg.paths.warehouse.parent.mkdir(parents=True)
    shutil.copy2(launch_cuts, cfg.paths.warehouse)
    conn = connect(cfg.paths.warehouse)
    try:
        with pytest.raises(LaunchRequiredError, match="el modelo se entrena una sola vez, en el lanzamiento"):
            fit_model(conn, cfg, run_key="r2", as_of=quick_history.runs[1].spec.as_of, source_sha256=quick_history.view.source_sha256)
    finally:
        conn.close()
    assert not cfg.paths.seal.exists() and not cfg.paths.models_dir.exists()
