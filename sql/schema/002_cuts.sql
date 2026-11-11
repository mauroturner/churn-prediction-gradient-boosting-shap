-- The cuts (plan, sections 5 and 9; D24): the block of every cut, the population known before it (cut_features) and the label of its window
-- (cut_labels), in separate tables. cut_features and cut_labels are insert only: an UPDATE, a DELETE or an INSERT on a key already written
-- (INSERT OR REPLACE deletes without firing the delete trigger; project 02, D44) is refused. U11 adds the features to cut_features.

CREATE TABLE IF NOT EXISTS cut_blocks (
    cut_date TEXT PRIMARY KEY,
    block TEXT NOT NULL CHECK (block IN ('before', 'train', 'purge_1', 'valid_v1', 'valid_v2', 'purge_2', 'test', 'post_test')),
    label_end TEXT NOT NULL,
    is_censored INTEGER NOT NULL CHECK (is_censored IN (0, 1))
);

CREATE TABLE IF NOT EXISTS cut_features (
    cut_date TEXT NOT NULL,
    customer_id INTEGER NOT NULL,
    computed_as_of TEXT NOT NULL,
    run_key TEXT NOT NULL,
    PRIMARY KEY (cut_date, customer_id)
);

CREATE TABLE IF NOT EXISTS cut_labels (
    cut_date TEXT NOT NULL,
    customer_id INTEGER NOT NULL,
    churned INTEGER NOT NULL CHECK (churned IN (0, 1)),
    label_end TEXT NOT NULL,
    known_as_of TEXT NOT NULL,
    run_key TEXT NOT NULL,
    PRIMARY KEY (cut_date, customer_id)
);

CREATE TRIGGER IF NOT EXISTS cut_features_no_update BEFORE UPDATE ON cut_features
BEGIN
    SELECT RAISE(ABORT, 'cut_features es de solo inserción: las variables de un corte no cambian');
END;

CREATE TRIGGER IF NOT EXISTS cut_features_no_delete BEFORE DELETE ON cut_features
BEGIN
    SELECT RAISE(ABORT, 'cut_features es de solo inserción: las variables de un corte no cambian');
END;

CREATE TRIGGER IF NOT EXISTS cut_features_no_replace BEFORE INSERT ON cut_features
WHEN EXISTS (SELECT 1 FROM cut_features WHERE cut_date = NEW.cut_date AND customer_id = NEW.customer_id)
BEGIN
    SELECT RAISE(ABORT, 'cut_features es de solo inserción: esa fila ya está escrita');
END;

CREATE TRIGGER IF NOT EXISTS cut_labels_no_update BEFORE UPDATE ON cut_labels
BEGIN
    SELECT RAISE(ABORT, 'cut_labels es de solo inserción: la etiqueta de un corte no cambia');
END;

CREATE TRIGGER IF NOT EXISTS cut_labels_no_delete BEFORE DELETE ON cut_labels
BEGIN
    SELECT RAISE(ABORT, 'cut_labels es de solo inserción: la etiqueta de un corte no cambia');
END;

CREATE TRIGGER IF NOT EXISTS cut_labels_no_replace BEFORE INSERT ON cut_labels
WHEN EXISTS (SELECT 1 FROM cut_labels WHERE cut_date = NEW.cut_date AND customer_id = NEW.customer_id)
BEGIN
    SELECT RAISE(ABORT, 'cut_labels es de solo inserción: esa fila ya está escrita');
END;
