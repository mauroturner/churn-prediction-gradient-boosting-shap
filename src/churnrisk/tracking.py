"""The monthly tracking of the scored cuts (RF22, AC24; D44; plan, section 18): what a retention team would see month by month.

For each scored cut and the run's calculation date ``as_of``: the customers scored and contacted; how many bought again (a net purchase day in
``[c, min(as_of, c + N - 1)]``, netted with what is known on ``as_of``); whether the window has closed (``as_of >= c + N - 1``); how many churned
(the label of ``cut_labels``, only once the window has closed); how many contacted customers churned or bought again; the expected churners (the
sum of the risks); and whether the cut is censored (its window ends after the last date of the data, so its label is never complete).
``returned`` is provisional: a purchase cancelled later can turn a customer who came back into a churner when the window closes; the label is what
counts. The tracking changes nothing of the model, the threshold or the costs. This module receives the sealed view, never the whole
configuration (D19).
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta

import pandas as pd

from churnrisk.config import SealedConfig
from churnrisk.netting import customer_days, net_lines_at
from churnrisk.warehouse import apply_schema

TRACKING_COLUMNS = ("as_of_date", "cut_date", "scored", "contacted", "returned", "window_closed", "churned", "contacted_churned", "contacted_returned",
                    "expected_churners", "is_censored")


def customer_returns(scores: pd.DataFrame, purchase_days: pd.DataFrame, as_of: date, horizon_days: int) -> pd.DataFrame:
    """For each scored customer (``cut_date``, ``customer_id``), whether it bought again by `as_of` (a net purchase day in
    ``[c, min(as_of, c + N - 1)]`` of `purchase_days`) and its first such day: the one rule of a return, for the tracking and the star model."""
    out = scores[["cut_date", "customer_id"]].copy()
    first = pd.Series(pd.NaT, index=out.index, dtype="datetime64[ns]")
    days = purchase_days[["customer_id", "day"]]
    for cut, part in out.groupby("cut_date", sort=True):
        seen = min(as_of, cut + timedelta(days=horizon_days - 1))
        window = days[(days["day"] >= pd.Timestamp(cut)) & (days["day"] <= pd.Timestamp(seen))].groupby("customer_id")["day"].min()
        first.loc[part.index] = part["customer_id"].map(window).to_numpy()
    out["first_return_date"] = first
    out["returned"] = first.notna().to_numpy()
    return out


def track_counts(scores: pd.DataFrame, purchase_days: pd.DataFrame, labels: pd.Series | None, as_of: date, horizon_days: int,
                 last_date: date) -> pd.DataFrame:
    """The tracking of each cut of `scores` (``cut_date``, ``customer_id``, ``risk``, ``is_contact``) on `as_of`, one row per cut in order.
    `purchase_days` are the net purchase days known on `as_of` (``customer_id``, ``day``); `labels` the ``churned`` of each ``(cut_date,
    customer_id)`` whose window has closed (None or missing for the others)."""
    rows = []
    ordered = scores.sort_values(["cut_date", "customer_id"]).reset_index(drop=True)
    returns = customer_returns(ordered, purchase_days, as_of, horizon_days)
    for cut, part in ordered.groupby("cut_date", sort=True):
        end = cut + timedelta(days=horizon_days - 1)
        returned = returns.loc[part.index, "returned"].to_numpy()
        contact = part["is_contact"].astype(bool).to_numpy()
        closed = as_of >= end
        churned = contacted_churned = None
        if closed:
            keys = pd.MultiIndex.from_arrays([part["cut_date"], part["customer_id"]])
            label = None if labels is None else labels.reindex(keys)
            if label is None or label.isna().any():
                raise ValueError(f"la ventana del corte {cut} cerró el {end} y faltan etiquetas de sus clientes en cut_labels")
            label = label.to_numpy().astype("int64")
            churned, contacted_churned = int(label.sum()), int(label[contact].sum())
        rows.append((as_of, cut, int(len(part)), int(contact.sum()), int(returned.sum()), bool(closed), churned, contacted_churned,
                     int((returned & contact).sum()), float(part["risk"].sum()), bool(end > last_date)))
    table = pd.DataFrame(rows, columns=list(TRACKING_COLUMNS))
    return table.astype({"churned": "Int64", "contacted_churned": "Int64"})     # missing until the window closes


def tracking_at(conn: sqlite3.Connection, as_of: date, view: SealedConfig) -> pd.DataFrame:
    """The tracking of every scored cut on `as_of`, from the warehouse: the scores, the net purchase days known on `as_of` and the labels whose
    window has closed."""
    apply_schema(conn)
    scores = pd.read_sql_query("SELECT cut_date, customer_id, risk, is_contact FROM model_scores WHERE as_of_date <= ?", conn, params=(as_of.isoformat(),))
    scores["cut_date"] = [date.fromisoformat(v) for v in scores["cut_date"]]
    labels = pd.read_sql_query("SELECT cut_date, customer_id, churned FROM cut_labels WHERE known_as_of <= ?", conn, params=(as_of.isoformat(),))
    labels["cut_date"] = [date.fromisoformat(v) for v in labels["cut_date"]]
    days = customer_days(net_lines_at(conn, as_of))
    return track_counts(scores, days, labels.set_index(["cut_date", "customer_id"])["churned"], as_of, view.label.horizon_days, view.deliveries.last_date)


def track(conn: sqlite3.Connection, as_of: date, view: SealedConfig, run_key: str) -> pd.DataFrame:
    """The task's body: the tracking on `as_of`, replacing the rows of that calculation date (repeating a date gives the same rows)."""
    table = tracking_at(conn, as_of, view)
    rows = [(r.as_of_date.isoformat(), r.cut_date.isoformat(), r.scored, r.contacted, r.returned, int(r.window_closed),
             None if pd.isna(r.churned) else int(r.churned), None if pd.isna(r.contacted_churned) else int(r.contacted_churned), r.contacted_returned,
             r.expected_churners, int(r.is_censored), run_key) for r in table.itertuples()]
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("DELETE FROM tracking WHERE as_of_date = ?", (as_of.isoformat(),))
        conn.executemany("INSERT INTO tracking VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    return table
