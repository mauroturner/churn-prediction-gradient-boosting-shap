"""Lines changed from a date on (AC13, RNF06 b): what a calculation for an earlier date must never see."""

from __future__ import annotations

from datetime import date

import pandas as pd


def perturbed(lines: pd.DataFrame, cut: date, customers: list[int]) -> pd.DataFrame:
    """`lines` with every line dated from `cut` on deleted (a third), changed (a third: twice the units at 1.5 times the price) or kept,
    plus, for each of `customers` that bought before the cut, a cancellation on the cut day of every unit of its last purchase day before
    the cut (one line per product, so that, netted, that whole day would be gone) and a large purchase on that day: if anything from the cut
    on reached a calculation for an earlier date, these would."""
    after = lines["invoice_date"] >= pd.Timestamp(cut)
    kept = lines[~(after & (lines["line_id"] % 3 == 0))].copy()
    change = (kept["invoice_date"] >= pd.Timestamp(cut)) & (kept["line_id"] % 3 == 1)
    kept.loc[change, "quantity"] = kept.loc[change, "quantity"] * 2
    kept.loc[change, "price"] = kept.loc[change, "price"] * 1.5
    added: list[dict] = []
    bought = lines[~after & lines["customer_id"].isin(customers) & (lines["quantity"] > 0) & ~lines["invoice"].str.startswith("C")]
    for i, (_customer, group) in enumerate(bought.sort_values(["invoice_ts", "line_id"]).groupby("customer_id")):
        last_day = group[group["invoice_date"] == group["invoice_date"].max()]
        template = last_day.iloc[-1].to_dict()
        when = pd.Timestamp(cut) + pd.Timedelta(minutes=i)
        for code, units in last_day.groupby("stock_code")["quantity"].sum().items():
            added.append({**template, "invoice": f"C{9_000_000 + i}", "stock_code": code, "quantity": -int(units)})
        for row in added[-last_day["stock_code"].nunique():]:
            row.update(invoice_ts=when, invoice_date=when.normalize(), is_repeated_line=False)
        later = when + pd.Timedelta(hours=12)       # after the cancellations, so that they take the units of the last day before the cut
        added.append({**template, "invoice": str(9_100_000 + i), "quantity": 999, "invoice_ts": later, "invoice_date": later.normalize(),
                      "is_repeated_line": False})
    for k, row in enumerate(added):
        row.update(line_id=30_000_000 + k, source_row=900_000 + k)
    return pd.concat([kept, pd.DataFrame(added)[list(lines.columns)].astype(lines.dtypes.to_dict())], ignore_index=True)
