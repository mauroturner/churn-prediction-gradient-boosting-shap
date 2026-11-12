-- The frozen model and its scores (plan, sections 5 and 15; D19, D40). model_registry holds the launch's model once per version, with the
-- SHA-256 of its artifact (M03: the artifact is deserialized only with it) and of the sealed configuration; baseline_calibrators the SHA-256 of
-- each calibrator of the baselines inside the artifact. model_scores and score_reasons are insert only: a score is never changed, deleted or
-- replaced (INSERT OR REPLACE deletes without firing the delete trigger, so a BEFORE INSERT on a key already written refuses it; project 02,
-- D44). The customer number lives here and in the tables of the cuts only (D26).

CREATE TABLE IF NOT EXISTS model_registry (
    model_version TEXT PRIMARY KEY,
    trained_as_of TEXT NOT NULL,
    artifact_path TEXT NOT NULL,
    artifact_sha256 TEXT NOT NULL,
    feature_set TEXT NOT NULL,
    feature_names_json TEXT NOT NULL,
    country_groups_json TEXT NOT NULL,
    params_json TEXT NOT NULL,
    calibration TEXT NOT NULL,
    threshold REAL NOT NULL CHECK (threshold >= 0 AND threshold <= 1),
    b_star TEXT NOT NULL,
    bgnbd_json TEXT NOT NULL,
    costs_json TEXT NOT NULL,
    config_sha256 TEXT NOT NULL,
    selection_json TEXT NOT NULL,
    valid_scores_sha256 TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS baseline_calibrators (
    method TEXT PRIMARY KEY,
    model_version TEXT NOT NULL REFERENCES model_registry (model_version),
    calibrator_sha256 TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS model_scores (
    cut_date TEXT NOT NULL,
    customer_id INTEGER NOT NULL,
    as_of_date TEXT NOT NULL,
    run_key TEXT NOT NULL,
    model_version TEXT NOT NULL,
    risk REAL NOT NULL CHECK (risk >= 0 AND risk <= 1),
    log_odds REAL NOT NULL,
    threshold REAL NOT NULL,
    is_contact INTEGER NOT NULL CHECK (is_contact IN (0, 1)),
    PRIMARY KEY (cut_date, customer_id)
);

CREATE TABLE IF NOT EXISTS score_reasons (
    cut_date TEXT NOT NULL,
    customer_id INTEGER NOT NULL,
    rank INTEGER NOT NULL CHECK (rank >= 1),
    feature TEXT NOT NULL,
    shap_value REAL NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('sube', 'baja')),
    PRIMARY KEY (cut_date, customer_id, rank)
);

CREATE TRIGGER IF NOT EXISTS model_registry_no_update BEFORE UPDATE ON model_registry
BEGIN
    SELECT RAISE(ABORT, 'model_registry es de solo inserción: el modelo del lanzamiento no cambia');
END;

CREATE TRIGGER IF NOT EXISTS model_registry_no_delete BEFORE DELETE ON model_registry
BEGIN
    SELECT RAISE(ABORT, 'model_registry es de solo inserción: el modelo del lanzamiento no cambia');
END;

CREATE TRIGGER IF NOT EXISTS model_scores_no_update BEFORE UPDATE ON model_scores
BEGIN
    SELECT RAISE(ABORT, 'model_scores es de solo inserción: un puntaje no cambia');
END;

CREATE TRIGGER IF NOT EXISTS model_scores_no_delete BEFORE DELETE ON model_scores
BEGIN
    SELECT RAISE(ABORT, 'model_scores es de solo inserción: un puntaje no cambia');
END;

CREATE TRIGGER IF NOT EXISTS model_scores_no_replace BEFORE INSERT ON model_scores
WHEN EXISTS (SELECT 1 FROM model_scores WHERE cut_date = NEW.cut_date AND customer_id = NEW.customer_id)
BEGIN
    SELECT RAISE(ABORT, 'model_scores es de solo inserción: ese cliente ya está puntuado en ese corte');
END;

CREATE TRIGGER IF NOT EXISTS score_reasons_no_update BEFORE UPDATE ON score_reasons
BEGIN
    SELECT RAISE(ABORT, 'score_reasons es de solo inserción: los motivos de un puntaje no cambian');
END;

CREATE TRIGGER IF NOT EXISTS score_reasons_no_delete BEFORE DELETE ON score_reasons
BEGIN
    SELECT RAISE(ABORT, 'score_reasons es de solo inserción: los motivos de un puntaje no cambian');
END;

CREATE TRIGGER IF NOT EXISTS score_reasons_no_replace BEFORE INSERT ON score_reasons
WHEN EXISTS (SELECT 1 FROM score_reasons WHERE cut_date = NEW.cut_date AND customer_id = NEW.customer_id AND rank = NEW.rank)
BEGIN
    SELECT RAISE(ABORT, 'score_reasons es de solo inserción: ese motivo ya está escrito');
END;
