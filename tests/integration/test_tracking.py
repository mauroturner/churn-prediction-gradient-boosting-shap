"""The tracking in the quick history (U19, AC24; RF22; D44): every run tracks every cut scored so far on its date; a window closes once, its
label decides who churned, and the cuts whose window ends after the data stay censored."""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta

import pytest

from churnrisk.tracking import track
from churnrisk.warehouse import connect

COLUMNS = "as_of_date, cut_date, scored, contacted, returned, window_closed, churned, contacted_churned, contacted_returned, expected_churners, is_censored"


def test_every_run_tracks_every_scored_cut_and_a_window_closes_with_its_label(quick_history, copy_of):
    view = quick_history.view
    conn = sqlite3.connect(quick_history.warehouse)
    try:
        rows = conn.execute(f"SELECT {COLUMNS} FROM tracking ORDER BY 1, 2").fetchall()
        scores = conn.execute("SELECT cut_date, COUNT(*), SUM(is_contact), SUM(risk) FROM model_scores GROUP BY cut_date").fetchall()
        labels = dict(conn.execute("SELECT cut_date, SUM(churned) FROM cut_labels GROUP BY cut_date").fetchall())
        contacted_churned = dict(conn.execute("SELECT s.cut_date, SUM(l.churned) FROM model_scores s JOIN cut_labels l USING (cut_date, customer_id) "
                                              "WHERE s.is_contact = 1 GROUP BY s.cut_date").fetchall())
    finally:
        conn.close()
    scored = {cut: (n, contacts, risk) for cut, n, contacts, risk in scores}
    runs = [(r.spec.as_of, [x.spec.cut for x in quick_history.runs[: i + 1] if x.spec.cut]) for i, r in enumerate(quick_history.runs)]
    assert [(r[0], r[1]) for r in rows] == [(a.isoformat(), c.isoformat()) for a, cuts in runs for c in cuts], "each run tracks every cut scored so far"
    for as_of, cut, n, contacts, returned, closed, churned, c_churned, c_returned, expected, censored in rows:
        a, c = date.fromisoformat(as_of), date.fromisoformat(cut)
        end = c + timedelta(days=view.label.horizon_days - 1)
        assert (n, contacts) == scored[cut][:2] and expected == pytest.approx(scored[cut][2])
        assert closed == int(a >= end) and censored == int(end > view.deliveries.last_date)
        if closed:
            assert (churned, c_churned) == (labels[cut], contacted_churned.get(cut, 0)), "the label decides who churned"
            assert returned <= n - churned, "a purchase seen in the window was known when it closed: whoever churned has none"
        else:
            assert churned is None and c_churned is None
        assert c_returned <= min(returned, contacts) and (returned == 0 if a < c else True)
    final = {cut: (closed, censored) for as_of, cut, _n, _c, _r, closed, _ch, _cc, _cr, _e, censored in rows if as_of == "2011-12-09"}
    assert final == {"2011-08-01": (1, 0), "2011-09-01": (1, 0), "2011-10-01": (0, 1), "2011-11-01": (0, 1), "2011-12-01": (0, 1)}
    # running the same date again gives the same rows, and replaces them rather than adding any
    conn = connect(copy_of(quick_history.warehouse))
    try:
        track(conn, quick_history.runs[-1].spec.as_of, view, "r9")
        again = conn.execute(f"SELECT {COLUMNS} FROM tracking ORDER BY 1, 2").fetchall()
    finally:
        conn.close()
    assert again == rows
