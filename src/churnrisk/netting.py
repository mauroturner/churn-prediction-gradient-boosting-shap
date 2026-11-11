"""Cancellation netting known on a date (RF06, D04): a cancellation comes off the purchase it cancels; copied from project 02 and adapted.

Each cancellation takes units from the most recent earlier purchase of the same customer and product (last in, first out) and, if that one
does not hold enough, from the one before it. What no purchase can cover is unmatched. A purchase keeps its own price: a matched unit is
valued at the price of the purchase, an unmatched one at the price of its cancellation.

Only lines whose invoice date is on or before the date count, so a cancellation that arrives later changes nothing in an earlier calculation
(RNF06 b): the features of a cut are netted with what is known on ``c - 1`` and its label with what is known on ``c + N - 1`` (D04, D24).
Events of one customer and product are ordered by time, a purchase before a cancellation of the same instant, and then by line id, so the
result does not depend on the order of the input rows. A day of purchase is a day with at least one net purchase (project 02, D06).

The purchases and the cancellations are the lines whose role (``validate.classify_lines``, RF05) is ``purchase`` and ``cancellation``:
``netting_inputs`` takes them from the canonical lines, so the netting and the roles read one definition.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

import pandas as pd

logger = logging.getLogger(__name__)

REQUIRED = ("line_id", "customer_id", "stock_code", "invoice", "invoice_ts", "invoice_date", "quantity", "price")
NET_COLUMNS = [
    "line_id", "customer_id", "stock_code", "invoice", "invoice_ts", "invoice_date", "price", "quantity", "allocated_quantity",
    "net_quantity", "net_revenue",
]
MATCH_COLUMNS = ["cancel_line_id", "purchase_line_id", "quantity", "value_gbp"]
UNMATCHED_COLUMNS = ["cancel_line_id", "quantity", "value_gbp"]
OUTCOME_COLUMNS = ["cancel_line_id", "cancelled", "matched", "unmatched", "outcome"]
OUTCOMES = ("complete", "partial", "unmatched")


@dataclass(frozen=True)
class NettingResult:
    """``net_lines``: every purchase known on the date with what was taken off it; ``matches``: which cancellation took how many units from
    which purchase; ``unmatched``: the units of a cancellation that no purchase could cover (one row per cancellation line with a remainder)."""

    net_lines: pd.DataFrame
    matches: pd.DataFrame
    unmatched: pd.DataFrame


def _check(frame: pd.DataFrame, what: str) -> None:
    missing = [name for name in REQUIRED if name not in frame.columns]
    if missing:
        raise ValueError(f"{what}: faltan las columnas {', '.join(missing)}")


def netting_inputs(lines: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """``(purchases, cancellations)``: the canonical lines whose role is a purchase or a cancellation (RF05), with an ``int64`` customer. The
    country of each line comes along when the lines have it: the country of a customer at a cut is the one of its last line (V30, U11)."""
    from churnrisk.validate import classify_lines   # here, not at the top: the validation nets the deliveries (V22) and imports this module

    roles = classify_lines(lines)["role"]
    columns = [c for c in lines.columns if c in (*REQUIRED, "code_kind", "country")]
    out = []
    for role in ("purchase", "cancellation"):
        chosen = lines.loc[roles == role, columns]
        out.append(chosen.assign(customer_id=chosen["customer_id"].astype("int64")).reset_index(drop=True))
    return out[0], out[1]


def net_cancellations(purchases: pd.DataFrame, cancellations: pd.DataFrame, as_of: date) -> NettingResult:
    """Net the `cancellations` (negative quantities) against the `purchases` (positive) known on `as_of`."""
    _check(purchases, "compras")
    _check(cancellations, "anulaciones")
    if (purchases["quantity"] <= 0).any():
        raise ValueError("compras: la cantidad debe ser positiva en todas las líneas")
    if (cancellations["quantity"] >= 0).any():
        raise ValueError("anulaciones: la cantidad debe ser negativa en todas las líneas")

    cutoff = pd.Timestamp(as_of)
    bought = purchases[purchases["invoice_date"] <= cutoff]
    cancelled = cancellations[cancellations["invoice_date"] <= cutoff]

    allocated: dict[int, int] = {}
    matches: list[tuple[int, int, int, float]] = []
    unmatched: list[tuple[int, int, float]] = []

    if len(cancelled):
        groups = cancelled[["customer_id", "stock_code"]].drop_duplicates()
        involved = bought.merge(groups, on=["customer_id", "stock_code"])
        events = pd.concat([
            pd.DataFrame({
                "customer_id": involved["customer_id"].astype("int64"), "stock_code": involved["stock_code"], "ts": involved["invoice_ts"],
                "kind": 0, "line_id": involved["line_id"].astype("int64"), "units": involved["quantity"].astype("int64"), "price": involved["price"],
            }),
            pd.DataFrame({
                "customer_id": cancelled["customer_id"].astype("int64"), "stock_code": cancelled["stock_code"], "ts": cancelled["invoice_ts"],
                "kind": 1, "line_id": cancelled["line_id"].astype("int64"), "units": -cancelled["quantity"].astype("int64"), "price": cancelled["price"],
            }),
        ], ignore_index=True).sort_values(["customer_id", "stock_code", "ts", "kind", "line_id"], kind="stable")

        group_key = events["customer_id"].astype(str) + "|" + events["stock_code"]
        stack: list[list] = []  # [line_id, units left, price] of the purchases still open, the latest on top
        current = None
        for key, kind, line_id, units, price in zip(
            group_key.tolist(), events["kind"].tolist(), events["line_id"].tolist(), events["units"].tolist(), events["price"].tolist(), strict=True,
        ):
            if key != current:
                stack, current = [], key
            if kind == 0:
                stack.append([line_id, units, price])
                continue
            left = units
            while left and stack:
                top = stack[-1]
                taken = min(left, top[1])
                matches.append((line_id, top[0], taken, taken * top[2]))
                allocated[top[0]] = allocated.get(top[0], 0) + taken
                top[1] -= taken
                left -= taken
                if top[1] == 0:
                    stack.pop()
            if left:
                unmatched.append((line_id, left, left * price))

    net = bought.assign(
        customer_id=bought["customer_id"].astype("int64"),
        allocated_quantity=bought["line_id"].map(allocated).fillna(0).astype("int64"),
    )
    net = net.assign(net_quantity=net["quantity"] - net["allocated_quantity"])
    net = net.assign(net_revenue=net["net_quantity"] * net["price"])
    net = net[NET_COLUMNS].astype({"line_id": "int64", "quantity": "int64"}).sort_values("line_id").reset_index(drop=True)

    match_frame = pd.DataFrame(matches, columns=MATCH_COLUMNS).astype(
        {"cancel_line_id": "int64", "purchase_line_id": "int64", "quantity": "int64", "value_gbp": "float64"}
    )
    unmatched_frame = pd.DataFrame(unmatched, columns=UNMATCHED_COLUMNS).astype({"cancel_line_id": "int64", "quantity": "int64", "value_gbp": "float64"})
    logger.info("netting as of %s: %d purchases, %d cancellations, %d matches, %d unmatched", as_of, len(net), len(cancelled), len(match_frame), len(unmatched_frame))
    return NettingResult(net, match_frame.sort_values(["cancel_line_id", "purchase_line_id"]).reset_index(drop=True),
                         unmatched_frame.sort_values("cancel_line_id").reset_index(drop=True))


def customer_days(net_lines: pd.DataFrame) -> pd.DataFrame:
    """One row per customer and day with a net purchase: ``customer_id``, ``day``, ``net_revenue``, ``units``, ``lines``.

    A line cancelled down to zero is not a purchase, and a day on which every line was cancelled has no row (project 02, D06).
    """
    live = net_lines[net_lines["net_quantity"] > 0]
    days = live.groupby(["customer_id", "invoice_date"], as_index=False).agg(
        net_revenue=("net_revenue", "sum"), units=("net_quantity", "sum"), lines=("line_id", "size"),
    )
    days = days.rename(columns={"invoice_date": "day"}).astype({"customer_id": "int64", "units": "int64", "lines": "int64"})
    return days.sort_values(["customer_id", "day"]).reset_index(drop=True)


def cancellation_outcomes(cancellations: pd.DataFrame, result: NettingResult, as_of: date) -> pd.DataFrame:
    """Each cancellation line known on `as_of`: its units, how many a purchase covered, how many were left, and whether it was ``complete``,
    ``partial`` or ``unmatched`` (no purchase at all). It is project 02's unit in its D04 (by cancellation, not by pair)."""
    known = cancellations[cancellations["invoice_date"] <= pd.Timestamp(as_of)]
    frame = pd.DataFrame({"cancel_line_id": known["line_id"].astype("int64").to_numpy(), "cancelled": (-known["quantity"]).astype("int64").to_numpy()})
    matched = result.matches.groupby("cancel_line_id")["quantity"].sum()
    left = result.unmatched.set_index("cancel_line_id")["quantity"]
    frame["matched"] = frame["cancel_line_id"].map(matched).fillna(0).astype("int64")
    frame["unmatched"] = frame["cancel_line_id"].map(left).fillna(0).astype("int64")
    if not (frame["matched"] + frame["unmatched"]).equals(frame["cancelled"]):
        raise ValueError("el resultado del neteo no corresponde a estas anulaciones: lo asignado más lo no asignado no es lo anulado")
    frame["outcome"] = "partial"
    frame.loc[frame["unmatched"] == 0, "outcome"] = "complete"
    frame.loc[frame["matched"] == 0, "outcome"] = "unmatched"
    return frame[OUTCOME_COLUMNS].sort_values("cancel_line_id").reset_index(drop=True)


def known_netting_inputs(conn, as_of: date) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The purchases and the cancellations loaded in the warehouse (``raw_lines``) and dated on or before `as_of`: whatever the warehouse holds
    since, a calculation for a date gets what was known on it (RNF06 b). The lines are read with the validation's reader of ``raw_lines``."""
    from churnrisk.validate import known_lines   # here, not at the top: the validation imports this module

    lines = known_lines(conn)
    return netting_inputs(lines[lines["invoice_date"] <= pd.Timestamp(as_of)].reset_index(drop=True))


def net_lines_at(conn, as_of: date) -> pd.DataFrame:
    """The net lines known on `as_of` (plan, section 8), whatever the warehouse holds since."""
    purchases, cancellations = known_netting_inputs(conn, as_of)
    return net_cancellations(purchases, cancellations, as_of).net_lines
