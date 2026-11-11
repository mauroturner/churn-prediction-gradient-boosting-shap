"""Cuts, population and label (RF11, RF12, D05-D07, D24): the two flows that never touch.

A cut ``c`` is day 1 of a month from ``first_cut`` to ``last_cut``. Its **population** are the customers with a net purchase day in
``[c - M, c - 1]``, with the cancellations known on ``c - 1``: what is known before the cut. Its **label** is ``churned = 1`` when the customer
has no net purchase day in ``[c, c + N - 1]``, with the cancellations known on ``c + N - 1`` (a purchase of the window cancelled inside it does
not count; one cancelled later does): what happens in its window. They live in two insert-only tables, ``cut_features`` and ``cut_labels``,
and a label is written only once the calculation date reaches the end of its window (D06).

``build_cuts`` runs at every calculation date ``as_of``: it writes the population of every cut ``c <= as_of + 1`` that has none yet, with its
features (``features.compute_features``, from what is known before the cut), the label of every cut whose window has closed
(``c + N - 1 <= as_of``) and that has none yet, and the block of every cut (``cut_blocks``), rebuilds the marts of ``sql/marts/ops/`` and
runs the controls of ``sql/checks/cuts/``, all in one transaction. It nets only the lines dated on or before each date it needs, so what the
warehouse holds since changes nothing (RNF06 b).
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

from churnrisk.config import SealedConfig
from churnrisk.features import compute_features, known_before
from churnrisk.netting import customer_days, known_netting_inputs, net_cancellations
from churnrisk.schema import FEATURE_COLUMNS
from churnrisk.split import blocks, check_purges, is_censored
from churnrisk.warehouse import CheckResult, _fail_on, apply_schema, rebuild_marts, run_checks, sql_params

FEATURE_INSERT = (f"INSERT INTO cut_features (cut_date, customer_id, {', '.join(FEATURE_COLUMNS)}, computed_as_of, run_key) "
                  f"VALUES ({', '.join('?' for _ in range(len(FEATURE_COLUMNS) + 4))})")

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CutsResult:
    as_of: date
    populated_cuts: list[date]       # cuts whose population this build wrote
    labelled_cuts: list[date]        # cuts whose label this build wrote
    rows: dict[str, int]             # rows written to cut_features and cut_labels
    checks: list[CheckResult]


def cut_dates(view: SealedConfig) -> list[date]:
    """The first day of every month from ``first_cut`` to ``last_cut``."""
    out, day = [], view.label.first_cut
    while day <= view.label.last_cut:
        out.append(day)
        day = date(day.year + (day.month == 12), day.month % 12 + 1, 1)
    return out


def label_end(cut: date, horizon_days: int) -> date:
    """The last day of the window of `cut`: ``c + N - 1``."""
    return cut + timedelta(days=horizon_days - 1)


def population(days_before: pd.DataFrame, cut: date, active_days: int) -> pd.Index:
    """The customers with a net purchase day in ``[c - M, c - 1]``, sorted. `days_before` are the customer days netted with what is known on
    ``c - 1`` (``netting.customer_days``)."""
    start, end = pd.Timestamp(cut - timedelta(days=active_days)), pd.Timestamp(cut - timedelta(days=1))
    days = days_before["day"]
    active = days_before.loc[(days >= start) & (days <= end), "customer_id"]
    return pd.Index(sorted(active.unique()), dtype="int64", name="customer_id")


def label(days_known_at_end: pd.DataFrame, cut: date, horizon_days: int, customers: pd.Index) -> pd.Series:
    """``churned`` (1 or 0) of each of `customers`: 1 when it has no net purchase day in ``[c, c + N - 1]``. `days_known_at_end` are the
    customer days netted with what is known on ``c + N - 1``."""
    start, end = pd.Timestamp(cut), pd.Timestamp(label_end(cut, horizon_days))
    days = days_known_at_end["day"]
    returned = set(days_known_at_end.loc[(days >= start) & (days <= end), "customer_id"])
    index = pd.Index(customers, dtype="int64", name="customer_id")
    return pd.Series([0 if c in returned else 1 for c in index], index=index, dtype="int64", name="churned")


def _done(conn: sqlite3.Connection, table: str) -> set[date]:
    return {date.fromisoformat(r[0]) for r in conn.execute(f"SELECT DISTINCT cut_date FROM {table}")}


def build_cuts(conn: sqlite3.Connection, as_of: date, view: SealedConfig, run_key: str) -> CutsResult:
    """Write the population and the label of every cut that the calculation date `as_of` allows and that has none yet, and the blocks, in one
    transaction with the controls of the cuts. Refuses a split without its purges (``PurgeError``) before writing anything."""
    n, m = view.label.horizon_days, view.label.active_days
    check_purges(view, n)
    conn.execute("BEGIN IMMEDIATE")
    try:
        apply_schema(conn)
        purchases, cancellations = known_netting_inputs(conn, as_of)

        def days_known(on: date) -> pd.DataFrame:
            return customer_days(net_cancellations(purchases, cancellations, on).net_lines)

        cuts = cut_dates(view)
        populated = [c for c in cuts if c <= as_of + timedelta(days=1) and c not in _done(conn, "cut_features")]
        for cut in populated:
            days_before, lines_before = known_before(purchases, cancellations, cut)
            members = population(days_before, cut, m)
            values = compute_features(days_before, lines_before, cut, members, view)
            conn.executemany(FEATURE_INSERT, [(cut.isoformat(), int(customer), *(v.item() if hasattr(v, "item") else v for v in row), as_of.isoformat(), run_key)
                                              for customer, row in zip(values.index, values.itertuples(index=False, name=None), strict=True)])
        labelled = [c for c in cuts if label_end(c, n) <= as_of and c not in _done(conn, "cut_labels")]
        for cut in labelled:
            members = pd.Index([r[0] for r in conn.execute("SELECT customer_id FROM cut_features WHERE cut_date = ? ORDER BY customer_id",
                                                             (cut.isoformat(),))], dtype="int64")
            churned = label(days_known(label_end(cut, n)), cut, n, members)
            conn.executemany("INSERT INTO cut_labels (cut_date, customer_id, churned, label_end, known_as_of, run_key) VALUES (?, ?, ?, ?, ?, ?)",
                             [(cut.isoformat(), int(c), int(y), label_end(cut, n).isoformat(), as_of.isoformat(), run_key) for c, y in churned.items()])
        conn.executemany(
            "INSERT INTO cut_blocks (cut_date, block, label_end, is_censored) VALUES (?, ?, ?, ?) ON CONFLICT (cut_date) DO UPDATE SET "
            "block = excluded.block, label_end = excluded.label_end, is_censored = excluded.is_censored",
            [(c.isoformat(), b, label_end(c, n).isoformat(), int(is_censored(c, view))) for c, b in blocks(view).items()],
        )
        rebuild_marts(conn, "ops", sql_params(as_of))
        checks = run_checks(conn, "cuts", {**sql_params(as_of), "horizon_days": n, "active_days": m})
        _fail_on(checks, f"cuts {run_key} at {as_of}")
        rows = {table: int(conn.execute(f"SELECT COUNT(*) FROM {table} WHERE run_key = ?", (run_key,)).fetchone()[0]) for table in ("cut_features", "cut_labels")}
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    logger.info("cuts %s at %s: populated %s, labelled %s, rows %s", run_key, as_of, [c.isoformat() for c in populated], [c.isoformat() for c in labelled], rows)
    return CutsResult(as_of, populated, labelled, rows, checks)
