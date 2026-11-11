"""The roles of the lines (RF05, D03): purchase, cancellation or set aside by the first rule that sets it aside.

U05 brings ``classify_lines``; U08 adds the rules of the delivery and of the lines and the validation report.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# The rules that set a line aside, in the order of the table of the plan (section 6): a line belongs to the first that matches it. Then a line
# of a «C» invoice is a cancellation and any other a purchase. The same order goes into sql/staging/stg_lines.sql (U09); a test compares them.
EXCLUSION_RULES: dict[str, str] = {
    "no_customer": "V20", "non_positive_quantity": "V23", "non_positive_price": "V24", "service_code": "V25", "gift_voucher": "V26",
    "adjustment_invoice": "V27",
}
ROLES = ("purchase", "cancellation", "excluded")


def _first_reason(frame: pd.DataFrame) -> pd.Series:
    """For every line, the first rule of ``EXCLUSION_RULES`` that sets it aside, or None."""
    invoice = frame["invoice"].astype(str)
    cancel = invoice.str.startswith("C")
    quantity, price, kind = frame["quantity"], frame["price"], frame["code_kind"]
    matches = [
        ("no_customer", frame["customer_id"].isna()),
        # the wrong sign for its invoice: zero or less outside a «C» invoice, zero or more inside one (project 02, D36)
        ("non_positive_quantity", (cancel & (quantity >= 0)) | (~cancel & (quantity <= 0))),
        ("non_positive_price", price <= 0),
        ("service_code", kind == "service"),
        ("gift_voucher", kind == "gift_voucher"),
        ("adjustment_invoice", invoice.str.startswith("A")),
    ]
    reason = np.full(len(frame), None, dtype=object)
    for name, mask in matches:
        reason[pd.isna(reason) & np.asarray(mask, dtype=bool)] = name
    return pd.Series(reason, index=frame.index, dtype=object)


def classify_lines(frame: pd.DataFrame) -> pd.DataFrame:
    """``role`` (``purchase``, ``cancellation`` or ``excluded``) and ``exclusion_reason`` of every line of `frame`.

    `frame` has the canonical columns ``invoice``, ``quantity``, ``price``, ``customer_id`` and ``code_kind``. A line is set aside by the first rule
    that applies, in this order: no customer, a quantity of the wrong sign, a price of zero or below, a service code (``PADS`` included), a gift
    voucher, an «A» invoice (an adjustment of bad debt). A line that no rule sets aside is a cancellation if its invoice starts with «C» and a
    purchase otherwise: a cancellation has a customer, a product code, a negative quantity and a positive price.
    """
    reason = _first_reason(frame)
    cancel = frame["invoice"].astype(str).str.startswith("C").to_numpy()
    role = np.where(reason.notna().to_numpy(), "excluded", np.where(cancel, "cancellation", "purchase"))
    return pd.DataFrame({"role": role, "exclusion_reason": reason}, index=frame.index)
