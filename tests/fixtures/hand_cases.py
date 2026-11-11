"""Small frames whose answer is written by hand (plan, section 24): the netting, the population and the label of a few customers at two
cuts, the RFM quintiles, the net benefit, the threshold and the gain curve, ten rows of metrics, a bootstrap by customer and the
monthly tracking with a censored cut. Each case says how its answer follows from the rule, so a reader can check it without code.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

LINE_COLUMNS = ("line_id", "customer_id", "stock_code", "invoice", "invoice_ts", "invoice_date", "quantity", "price")


def event(line_id: int, customer: int, code: str, when: str, quantity: int, price: float = 1.0, invoice: str | None = None) -> dict:
    """A purchase (positive quantity) or a cancellation (negative) of `customer` for `code` at `when` (``YYYY-MM-DD HH:MM``)."""
    ts = pd.Timestamp(when)
    return {
        "line_id": line_id, "customer_id": customer, "stock_code": code, "invoice": invoice or (f"C{line_id}" if quantity < 0 else str(line_id)),
        "invoice_ts": ts, "invoice_date": ts.normalize(), "quantity": quantity, "price": price,
    }


def split(*events: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The events as ``(purchases, cancellations)`` frames with the columns of the canonical lines."""
    frame = pd.DataFrame(list(events), columns=list(LINE_COLUMNS)).astype({"line_id": "int64", "customer_id": "int64", "quantity": "int64"})
    return frame[frame["quantity"] > 0].reset_index(drop=True), frame[frame["quantity"] < 0].reset_index(drop=True)


# --- the netting known on a date (U06, AC05) -----------------------------------------------------------------------


@dataclass(frozen=True)
class NettingCase:
    purchases: pd.DataFrame
    cancellations: pd.DataFrame
    net_quantity: dict[date, dict[int, int]]   # as_of -> purchase line_id -> net quantity
    unmatched: dict[date, dict[int, int]]      # as_of -> cancellation line_id -> units left without a purchase


def netting_case() -> NettingCase:
    """Last in, first out by customer and product, with only the cancellations known on the date.

    - Customer 1, product A: buys 10 (line 1) and 6 (line 2), cancels 8 (line 3): the 6 of line 2 go first, then 2 of line 1, so
      line 1 keeps 8 and line 2 keeps 0.
    - Customer 1, product B: buys 5 (line 4), cancels 8 (line 5): line 4 keeps 0 and 3 units of line 5 have no purchase.
    - Customer 2, product A: cancels 4 (line 6) before buying 4 (line 7): a purchase never takes an earlier cancellation, so line 7 keeps
      4 and line 6 has 4 units without a purchase. Another customer's purchase of the same product is never touched.
    - Customer 3, product C: buys 3 and cancels 3 in the same minute (lines 8 and 9): the purchase comes first, so it keeps 0.
    - Customer 1, product D: buys 7 on 2011-01-05 (line 10) and cancels them on 2011-01-20 (line 11): on 2011-01-10 the
      cancellation is not known and line 10 keeps 7; on 2011-01-20 it keeps 0.
    """
    purchases, cancellations = split(
        event(1, 1, "A", "2011-01-03 10:00", 10), event(2, 1, "A", "2011-01-04 10:00", 6), event(3, 1, "A", "2011-01-06 09:00", -8),
        event(4, 1, "B", "2011-01-03 11:00", 5), event(5, 1, "B", "2011-01-07 09:00", -8),
        event(6, 2, "A", "2011-01-02 09:00", -4), event(7, 2, "A", "2011-01-03 09:00", 4),
        event(8, 3, "C", "2011-01-05 10:00", 3), event(9, 3, "C", "2011-01-05 10:00", -3),
        event(10, 1, "D", "2011-01-05 12:00", 7), event(11, 1, "D", "2011-01-20 12:00", -7),
    )
    early, late = date(2011, 1, 10), date(2011, 1, 20)
    return NettingCase(
        purchases, cancellations,
        net_quantity={early: {1: 8, 2: 0, 4: 0, 7: 4, 8: 0, 10: 7}, late: {1: 8, 2: 0, 4: 0, 7: 4, 8: 0, 10: 0}},
        unmatched={early: {3: 0, 5: 3, 6: 4, 9: 0}, late: {3: 0, 5: 3, 6: 4, 9: 0, 11: 0}},
    )


# --- population and label at two cuts (U10, AC10) --------------------------------------------------------------------


@dataclass(frozen=True)
class CutsCase:
    purchases: pd.DataFrame
    cancellations: pd.DataFrame
    horizon_days: int
    active_days: int
    population: dict[date, tuple[int, ...]]
    labels: dict[date, dict[int, int]]


def cuts_case() -> CutsCase:
    """Five customers at the cuts 2011-03-01 and 2011-04-01 with N = M = 90.

    For 2011-03-01 the population window is [2010-12-01, 2011-02-28] (known on 2011-02-28) and the label window [2011-03-01,
    2011-05-29] (known on 2011-05-29); for 2011-04-01, [2011-01-01, 2011-03-31] and [2011-04-01, 2011-06-29].

    - 101 buys on 2010-12-15 and 2011-03-10: active at both cuts; churned 0 at 03-01 (03-10 is in its window), 1 at 04-01.
    - 102 buys on 2010-11-20 and 2011-02-28, and cancels the second on 2011-03-05: on 2011-02-28 the cancellation is not known, so it
      is active at 03-01 and churns (nothing in the window); on 2011-03-31 that day is gone and 2010-11-20 is too old: not in 04-01.
    - 103 buys on 2011-01-05 and 2011-05-29, the last day of the 03-01 window: 0 at both cuts.
    - 104 buys on 2011-02-10 and 2011-03-15 and cancels the second on 2011-03-20, inside the window: churned 1 at 03-01; at 04-01 it is
      active through 2011-02-10 and churned 1.
    - 105 buys on 2011-02-01 and 2011-05-20 and cancels the second on 2011-06-10, after the 03-01 window closed: 0 at 03-01; at 04-01
      the cancellation is known on 2011-06-29, so it churned 1.
    """
    purchases, cancellations = split(
        event(1, 101, "A", "2010-12-15 10:00", 2), event(2, 101, "A", "2011-03-10 10:00", 2),
        event(3, 102, "A", "2010-11-20 10:00", 2), event(4, 102, "B", "2011-02-28 10:00", 5), event(5, 102, "B", "2011-03-05 10:00", -5),
        event(6, 103, "A", "2011-01-05 10:00", 1), event(7, 103, "A", "2011-05-29 18:00", 1),
        event(8, 104, "A", "2011-02-10 10:00", 3), event(9, 104, "B", "2011-03-15 10:00", 4), event(10, 104, "B", "2011-03-20 10:00", -4),
        event(11, 105, "A", "2011-02-01 10:00", 2), event(12, 105, "B", "2011-05-20 10:00", 6), event(13, 105, "B", "2011-06-10 10:00", -6),
    )
    march, april = date(2011, 3, 1), date(2011, 4, 1)
    return CutsCase(
        purchases, cancellations, horizon_days=90, active_days=90,
        population={march: (101, 102, 103, 104, 105), april: (101, 103, 104, 105)},
        labels={march: {101: 0, 102: 1, 103: 0, 104: 1, 105: 0}, april: {101: 1, 103: 0, 104: 1, 105: 1}},
    )


# --- RFM quintiles inside a cut (U12, AC15) -------------------------------------------------------------------------


def rfm_case() -> tuple[pd.DataFrame, dict[int, int]]:
    """Six customers of one cut and their RFM score, ``ceil(5 x average rank / n)`` per letter (project 02, D09), n = 6.

    R ranks -rec_days: -90 (4) 1, -60 (6) 2, -40 (2, 3) 3.5 each, -10 (1) 5, -5 (5) 6 -> scores 1, 2, 3, 3, 5, 5.
    F ranks freq_365: 1 (4) 1, 2 (2, 3) 2.5, 3 (6) 4, 6 (1) 5, 9 (5) 6 -> scores 1, 3, 3, 4, 5, 5.
    M ranks mon_365: 20 (4) 1, 80 (2, 6) 2.5, 120 (3) 4, 300 (1) 5, 500 (5) 6 -> scores 1, 3, 3, 4, 5, 5.
    """
    frame = pd.DataFrame({
        "customer_id": [1, 2, 3, 4, 5, 6],
        "rec_days": [10, 40, 40, 90, 5, 60],
        "freq_365": [6, 2, 2, 1, 9, 3],
        "mon_365": [300.0, 80.0, 120.0, 20.0, 500.0, 80.0],
    })
    return frame, {1: 15, 2: 9, 3: 10, 4: 3, 5: 15, 6: 9}


# --- net benefit, threshold and gain curve (U15, AC19) --------------------------------------------------------------

THRESHOLD_P = (0.9, 0.8, 0.6, 0.55, 0.4, 0.3, 0.2, 0.1)
THRESHOLD_Y = (1, 1, 0, 1, 1, 0, 0, 0)
# With offer_cost 5, rescue_rate 0.2 and retained_value 50, a contacted customer is worth 10 x churned - 5: +5, +5, -5, +5, +5, -5, -5, -5
# in the order above. Contacting p >= t gives 0 for t in (0.9, 0.99], 5 in (0.8, 0.9], 10 in (0.6, 0.8], 5 in (0.55, 0.6], 10 in
# (0.4, 0.55], 15 in (0.3, 0.4], 10 in (0.2, 0.3], 5 in (0.1, 0.2] and 0 in [0.01, 0.1]: the best is 15, reached from 0.31 to 0.40, and
# a tie goes to the largest t.
THRESHOLD_EXPECTED = {"threshold": 0.40, "net_benefit": 15.0, "contacted": 5, "net_benefit_per_1000": 1875.0}
# The gain curve over the same rows (4 churners): contacting the top k of 8 captures 1, 2, 2, 3, 4, 4, 4 and 4 churners.
GAIN_CAPTURED = (1, 2, 2, 3, 4, 4, 4, 4)


# --- ten rows of metrics (U17, AC25) --------------------------------------------------------------------------------

METRICS_Y = (1, 0, 1, 1, 0, 0, 1, 0, 0, 0)
METRICS_P = (0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.2, 0.1)
METRICS_EXPECTED = {
    # 4 churners and 6 others, 24 pairs; the churners at 0.9, 0.7, 0.6 and 0.3 rank above 6, 5, 5 and 3 others: 19 / 24
    "auc": 19 / 24,
    # precision at each churner, in order of risk: 1/1, 2/3, 3/4, 4/7; their mean is 251/336
    "pr_auc": 251 / 336,
    # (0.01 + 0.64 + 0.09 + 0.16 + 0.25 + 0.16 + 0.49 + 0.04 + 0.04 + 0.01) / 10
    "brier": 0.189,
    "mean_p": 0.47, "rate": 0.4, "bias": 0.07,
    # ten bins of width 0.1, every row alone in its bin except the two at 0.2: the bins from 0.3 to 0.9 differ from their rate by
    # 0.7, 0.4, 0.5, 0.4, 0.3, 0.8 and 0.1 (3.2 in all), the pair at 0.2 by 0.2 (weight 2) and the row at 0.1 by 0.1: (3.2 + 0.4 + 0.1) / 10
    "ece": 0.37,
    # the top ceil(0.10 x 10) = 1 row holds 1 of the 4 churners (lift 0.25 / 0.10); the top 2 rows hold 1 (lift 0.25 / 0.20)
    "captured_10": 1, "lift_10": 2.5, "captured_20": 1, "lift_20": 1.25,
    # contacting p >= 0.5 with the default costs: rows 1 to 5, three churners, 10 x 3 - 5 x 5
    "net_benefit_at_0_5": 5.0,
}


# --- a bootstrap by customer (U17, AC25) ----------------------------------------------------------------------------


def bootstrap_case() -> pd.DataFrame:
    """Eight rows of five customers, three of them in both test cuts: a resample must take a customer with all its rows or none."""
    return pd.DataFrame({
        "customer_id": [1, 1, 2, 3, 3, 4, 5, 5],
        "cut_date": [date(2011, 8, 1), date(2011, 9, 1)] * 2 + [date(2011, 9, 1), date(2011, 8, 1), date(2011, 8, 1), date(2011, 9, 1)],
        "churned": [1, 0, 1, 0, 0, 1, 0, 1],
        "score_a": [0.9, 0.2, 0.8, 0.3, 0.4, 0.7, 0.1, 0.6],
        "score_b": [0.5, 0.5, 0.6, 0.4, 0.2, 0.3, 0.3, 0.9],
    })


# --- monthly tracking with a censored cut (U19, AC24) ---------------------------------------------------------------


@dataclass(frozen=True)
class TrackingCase:
    scores: pd.DataFrame          # cut_date, customer_id, risk, is_contact
    purchase_days: pd.DataFrame   # customer_id, day: net purchase days after the cuts
    as_of: date
    last_date: date
    expected: dict[date, dict]


def tracking_case() -> TrackingCase:
    """Two scored cuts seen on 2011-11-30, with the data ending on 2011-12-09.

    Cut 2011-08-01 (window to 2011-10-29, closed): A (contacted, 0.7) buys on 2011-08-20; B (contacted, 0.8) never; C (0.3) buys on
    2011-10-29, the last day; D (0.4) on 2011-10-30, a day late. Returned A and C; churned B and D; contacted and churned B; contacted
    and returned A; expected churners 0.7 + 0.8 + 0.3 + 0.4 = 2.2.
    Cut 2011-10-01 (window to 2011-12-29, after the data: censored): E (contacted, 0.6) buys on 2011-10-15, F (0.5) not yet. Returned E;
    the window has not closed, so nobody has churned yet; expected churners 1.1.
    """
    august, october = date(2011, 8, 1), date(2011, 10, 1)
    scores = pd.DataFrame({
        "cut_date": [august] * 4 + [october] * 2,
        "customer_id": [1, 2, 3, 4, 5, 6],
        "risk": [0.7, 0.8, 0.3, 0.4, 0.6, 0.5],
        "is_contact": [True, True, False, False, True, False],
    })
    days = pd.DataFrame({"customer_id": [1, 3, 4, 5], "day": pd.to_datetime(["2011-08-20", "2011-10-29", "2011-10-30", "2011-10-15"])})
    expected = {
        august: {"scored": 4, "contacted": 2, "returned": 2, "window_closed": True, "churned": 2, "contacted_churned": 1,
                 "contacted_returned": 1, "expected_churners": 2.2, "is_censored": False},
        october: {"scored": 2, "contacted": 1, "returned": 1, "window_closed": False, "churned": None, "contacted_churned": None,
                  "contacted_returned": 1, "expected_churners": 1.1, "is_censored": True},
    }
    return TrackingCase(scores, days, as_of=date(2011, 11, 30), last_date=date(2011, 12, 9), expected=expected)
