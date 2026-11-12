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
    method TEXT NOT NULL,
    model_version TEXT NOT NULL REFERENCES model_registry (model_version),
    calibrator_sha256 TEXT NOT NULL,
    PRIMARY KEY (method, model_version)
);

CREATE TABLE IF NOT EXISTS model_scores (
    cut_date TEXT NOT NULL,
    customer_id INTEGER NOT NULL,
    as_of_date TEXT NOT NULL,
    run_key TEXT NOT NULL,
    model_version TEXT NOT NULL,
    risk REAL NOT NULL CHECK (risk >= 0 AND risk <= 1),
    log_odds REAL NOT NULL,
    threshold REAL NOT NULL CHECK (threshold >= 0 AND threshold <= 1),
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

CREATE TRIGGER IF NOT EXISTS baseline_calibrators_no_update BEFORE UPDATE ON baseline_calibrators
BEGIN
    SELECT RAISE(ABORT, 'baseline_calibrators es de solo inserción: los calibradores del lanzamiento no cambian');
END;

CREATE TRIGGER IF NOT EXISTS baseline_calibrators_no_delete BEFORE DELETE ON baseline_calibrators
BEGIN
    SELECT RAISE(ABORT, 'baseline_calibrators es de solo inserción: los calibradores del lanzamiento no cambian');
END;

CREATE TRIGGER IF NOT EXISTS baseline_calibrators_no_replace BEFORE INSERT ON baseline_calibrators
WHEN EXISTS (SELECT 1 FROM baseline_calibrators WHERE method = NEW.method AND model_version = NEW.model_version)
BEGIN
    SELECT RAISE(ABORT, 'baseline_calibrators es de solo inserción: ese calibrador ya está registrado');
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

-- The evaluation (plan, sections 5 and 16; D20): every measure of a block (valid_v2 at the launch, the test once its windows closed) by
-- scope and seal state. The sealed rows of the test are written once; the rows of the validation and every post_seal row are replaced when
-- the same date is evaluated again.

CREATE TABLE IF NOT EXISTS eval_metrics (
    scope TEXT NOT NULL CHECK (scope IN ('valid_v2', 'test')),
    method TEXT NOT NULL,
    metric TEXT NOT NULL,
    seal_state TEXT NOT NULL CHECK (seal_state IN ('sealed', 'post_seal')),
    value REAL,
    run_key TEXT NOT NULL,
    as_of_date TEXT NOT NULL,
    PRIMARY KEY (scope, method, metric, seal_state)
);

CREATE TABLE IF NOT EXISTS eval_per_cut (
    scope TEXT NOT NULL,
    cut_date TEXT NOT NULL,
    metric TEXT NOT NULL,
    seal_state TEXT NOT NULL CHECK (seal_state IN ('sealed', 'post_seal')),
    value REAL,
    run_key TEXT NOT NULL,
    PRIMARY KEY (scope, cut_date, metric, seal_state)
);

CREATE TABLE IF NOT EXISTS eval_bootstrap (
    scope TEXT NOT NULL,
    comparison TEXT NOT NULL,
    seal_state TEXT NOT NULL CHECK (seal_state IN ('sealed', 'post_seal')),
    diff REAL NOT NULL,
    ci_low REAL,
    ci_high REAL,
    kept INTEGER NOT NULL,
    discarded INTEGER NOT NULL,
    run_key TEXT NOT NULL,
    PRIMARY KEY (scope, comparison, seal_state)
);

CREATE TABLE IF NOT EXISTS eval_criteria (
    criterion_id TEXT NOT NULL,
    seal_state TEXT NOT NULL CHECK (seal_state IN ('sealed', 'post_seal')),
    name_es TEXT NOT NULL,
    value REAL,
    baseline_value REAL,
    ci_low REAL,
    ci_high REAL,
    threshold_es TEXT NOT NULL,
    passed INTEGER CHECK (passed IN (0, 1)),
    seen_by_research TEXT NOT NULL,
    seen_by_planner TEXT NOT NULL,
    verdict_es TEXT NOT NULL,
    run_key TEXT NOT NULL,
    PRIMARY KEY (criterion_id, seal_state)
);

CREATE TABLE IF NOT EXISTS eval_cost_sensitivity (
    scope TEXT NOT NULL,
    break_even REAL NOT NULL,
    method TEXT NOT NULL,
    seal_state TEXT NOT NULL CHECK (seal_state IN ('sealed', 'post_seal')),
    threshold REAL NOT NULL,
    net_benefit REAL NOT NULL,
    nb_per_1000 REAL NOT NULL,
    contact_share REAL NOT NULL,
    rows INTEGER NOT NULL,
    run_key TEXT NOT NULL,
    PRIMARY KEY (scope, break_even, method, seal_state)
);

CREATE TABLE IF NOT EXISTS eval_gain (
    scope TEXT NOT NULL,
    method TEXT NOT NULL,
    point INTEGER NOT NULL,
    seal_state TEXT NOT NULL CHECK (seal_state IN ('sealed', 'post_seal')),
    contacted INTEGER NOT NULL,
    captured INTEGER NOT NULL,
    share_contacted REAL NOT NULL,
    share_captured REAL NOT NULL,
    lift REAL NOT NULL,
    PRIMARY KEY (scope, method, point, seal_state)
);

CREATE TABLE IF NOT EXISTS eval_roc (
    scope TEXT NOT NULL,
    method TEXT NOT NULL,
    point INTEGER NOT NULL,
    seal_state TEXT NOT NULL CHECK (seal_state IN ('sealed', 'post_seal')),
    fpr REAL NOT NULL,
    tpr REAL NOT NULL,
    PRIMARY KEY (scope, method, point, seal_state)
);

CREATE TABLE IF NOT EXISTS eval_calibration (
    scope TEXT NOT NULL,
    method TEXT NOT NULL,
    bin INTEGER NOT NULL,
    seal_state TEXT NOT NULL CHECK (seal_state IN ('sealed', 'post_seal')),
    p_mean REAL,
    observed REAL,
    rows INTEGER NOT NULL,
    PRIMARY KEY (scope, method, bin, seal_state)
);

CREATE TABLE IF NOT EXISTS feature_importance (
    scope TEXT NOT NULL,
    feature TEXT NOT NULL,
    seal_state TEXT NOT NULL CHECK (seal_state IN ('sealed', 'post_seal')),
    mean_abs_shap REAL NOT NULL,
    run_key TEXT NOT NULL,
    PRIMARY KEY (scope, feature, seal_state)
);

CREATE TABLE IF NOT EXISTS eval_leakage (
    variable TEXT PRIMARY KEY,
    variable_es TEXT NOT NULL,
    auc_valid_v2 REAL NOT NULL,
    note_es TEXT NOT NULL,
    run_key TEXT NOT NULL
);

-- The sensitivity (plan, section 17; D10): each variant of N, M and of the December cut on its own test cuts, written with the evaluation of
-- the test; and the definition of the label on the training cuts (N x M and the silences that come back), written with the validation.

CREATE TABLE IF NOT EXISTS eval_variants (
    variant TEXT NOT NULL,
    method TEXT NOT NULL,
    metric TEXT NOT NULL,
    seal_state TEXT NOT NULL CHECK (seal_state IN ('sealed', 'post_seal')),
    value REAL,
    run_key TEXT NOT NULL,
    PRIMARY KEY (variant, method, metric, seal_state)
);

CREATE TABLE IF NOT EXISTS eval_label_definition (
    n INTEGER NOT NULL,
    m INTEGER NOT NULL,
    churn_rate REAL NOT NULL,
    rows INTEGER NOT NULL,
    run_key TEXT NOT NULL,
    PRIMARY KEY (n, m)
);

CREATE TABLE IF NOT EXISTS eval_silence_return (
    n INTEGER PRIMARY KEY,
    silences INTEGER NOT NULL,
    return_share REAL,
    run_key TEXT NOT NULL
);


-- The monthly tracking (plan, sections 5 and 18; D44): for each calculation date and scored cut, who bought again, whether the window closed,
-- who churned and how many contacted customers did either. The rows of a date are replaced when that date is run again.

CREATE TABLE IF NOT EXISTS tracking (
    as_of_date TEXT NOT NULL,
    cut_date TEXT NOT NULL,
    scored INTEGER NOT NULL,
    contacted INTEGER NOT NULL,
    returned INTEGER NOT NULL,
    window_closed INTEGER NOT NULL CHECK (window_closed IN (0, 1)),
    churned INTEGER,
    contacted_churned INTEGER,
    contacted_returned INTEGER NOT NULL,
    expected_churners REAL NOT NULL,
    is_censored INTEGER NOT NULL CHECK (is_censored IN (0, 1)),
    run_key TEXT NOT NULL,
    PRIMARY KEY (as_of_date, cut_date)
);
