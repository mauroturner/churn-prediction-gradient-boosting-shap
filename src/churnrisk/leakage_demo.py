"""The leak, shown on purpose (D41; plan, section 16): what a variable that looks at the window does to the AUC on V2.

``leakage_table`` trains, with the launch's chosen hyperparameters, one classifier on the 16 numeric features (F1) and one on F1 plus a control,
``days_to_next_purchase`` (the days from the cut to the customer's next net purchase day, known on the calculation date: what the label is made
of), both on the training block, and measures each on V2. The control is added here, past ``features.build_matrix``, whose guards refuse it by
its name (AC12): this module exists to show what the guards and the tripwire M01 stop. It never writes the registry or the scores (a static test
reads this file), and nothing it computes reaches the model, a threshold or a criterion.
"""

from __future__ import annotations

import sqlite3
from datetime import date

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score

from churnrisk.config import SealedConfig
from churnrisk.features import NUMERIC_FEATURES, build_matrix
from churnrisk.netting import customer_days, net_lines_at
from churnrisk.schema import FEATURE_COLUMNS
from churnrisk.split import labelled_rows

CONTROL = "days_to_next_purchase"
NO_PURCHASE_DAYS = 400      # the control of a customer with no purchase from the cut to the calculation date
VARIABLES_ES = {"f1": "las 16 variables (F1)", f"f1_{CONTROL}": "F1 más los días hasta la próxima compra (mira la ventana)"}
NOTES_ES = {
    "f1": "Lo que se sabe antes del corte.",
    f"f1_{CONTROL}": "Mira la ventana de la etiqueta: por eso las guardas la rechazan por su nombre y la trampa M01 detiene un lanzamiento con un AUC así.",
}


def days_to_next_purchase(conn: sqlite3.Connection, rows: pd.DataFrame, as_of: date) -> np.ndarray:
    """For each row (index ``(cut_date, customer_id)``), the days from its cut to the customer's next net purchase day known on `as_of`."""
    days = customer_days(net_lines_at(conn, as_of))
    by_customer = {c: g["day"].to_numpy() for c, g in days.groupby("customer_id")}
    out = []
    for cut, customer in rows.index:
        later = by_customer.get(customer, np.array([], dtype="datetime64[ns]"))
        later = later[later >= np.datetime64(cut)]
        out.append(int((later.min() - np.datetime64(cut)) / np.timedelta64(1, "D")) if len(later) else NO_PURCHASE_DAYS)
    return np.asarray(out, dtype="float64")


def leakage_table(conn: sqlite3.Connection, view: SealedConfig, params: dict, as_of: date) -> pd.DataFrame:
    """``variable``, ``variable_es``, ``auc_valid_v2`` and ``note_es`` of F1 and of F1 with the control, each fitted on the training block
    with `params` (the launch's chosen ``learning_rate``, ``max_leaf_nodes`` and ``min_samples_leaf``)."""
    rows = labelled_rows(conn, ["train", "valid_v2"])
    x = build_matrix(rows[list(FEATURE_COLUMNS)], "f1", ("Otros",))[list(NUMERIC_FEATURES)].copy()
    control = days_to_next_purchase(conn, rows, as_of)
    train, v2 = (rows["block"] == "train").to_numpy(), (rows["block"] == "valid_v2").to_numpy()
    y = rows["churned"].to_numpy()
    out = []
    for name, matrix in (("f1", x), (f"f1_{CONTROL}", x.assign(**{CONTROL: control}))):
        classifier = HistGradientBoostingClassifier(
            learning_rate=params["learning_rate"], max_leaf_nodes=params["max_leaf_nodes"], min_samples_leaf=params["min_samples_leaf"],
            l2_regularization=view.model.l2_regularization, max_iter=view.model.max_iter, early_stopping=False, random_state=view.model.random_state,
        ).fit(matrix[train], y[train])
        out.append((name, VARIABLES_ES[name], float(roc_auc_score(y[v2], classifier.predict_proba(matrix[v2])[:, 1])), NOTES_ES[name]))
    return pd.DataFrame(out, columns=["variable", "variable_es", "auc_valid_v2", "note_es"])
