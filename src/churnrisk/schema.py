"""The contract of the source and of the canonical lines: the one place that names them (plan, section 6).

``WORKBOOK_COLUMNS`` are the eight columns of each sheet of the workbook, in order; ``SOURCE_COLUMNS`` their English names. ``code_kind``
tells a product from a gift voucher and a service code (project 02, D03: five digits with up to two letters, or the ``DCGS`` prefix, is a
product; ``PADS`` is a service). The lists of allowed feature columns, of the columns that look at the label window and of the identifiers
are here too, so that the guards of the model and the exports read one definition; they never share a name.
"""

from __future__ import annotations

import re
from typing import Any

import pandas as pd
import pyarrow as pa

WORKBOOK_COLUMNS: tuple[str, ...] = ("Invoice", "StockCode", "Description", "Quantity", "InvoiceDate", "Price", "Customer ID", "Country")
SOURCE_COLUMNS: tuple[str, ...] = ("invoice", "stock_code", "description", "quantity", "invoice_ts", "price", "customer_id", "country")
COLUMN_NAMES: dict[str, str] = dict(zip(WORKBOOK_COLUMNS, SOURCE_COLUMNS, strict=True))
LINE_ID_SHEET_FACTOR = 10_000_000
CUSTOMER_ID_RANGE = (10_000, 99_999)          # five digits (V05): the real numbers go from 12346 to 18287, the fixture's from 90001
PRODUCT_PREFIXES = ("DCGS",)
GIFT_VOUCHER_PREFIX = "gift_"
_PRODUCT_CODE = re.compile(r"\d{5}[A-Za-z]{0,2}")

# Arrow schema of the canonical lines (data/interim/source_lines.parquet) and of every delivery
CANONICAL_SCHEMA = pa.schema([
    ("line_id", pa.int64()), ("sheet", pa.int64()), ("source_row", pa.int64()), ("invoice", pa.string()), ("stock_code", pa.string()),
    ("description", pa.string()), ("quantity", pa.int64()), ("invoice_ts", pa.timestamp("ns")), ("invoice_date", pa.timestamp("ns")),
    ("price", pa.float64()), ("customer_id", pa.int64()), ("country", pa.string()), ("code_kind", pa.string()), ("is_repeated_line", pa.bool_()),
])
CANONICAL_COLUMNS: tuple[str, ...] = tuple(CANONICAL_SCHEMA.names)

# The 16 features of research.md and the country group (plan, section 10; D12): the only columns a model matrix may take
FEATURE_COLUMNS: tuple[str, ...] = (
    "rec_days", "tenure_days", "freq_total", "freq_90", "freq_365", "mon_total", "mon_90", "mon_365", "aov_day", "units_90",
    "gap_mean", "gap_max", "n_products_365", "med_units_365", "canc_365", "canc_value_365", "country_group",
)
# What looks at the label window, or is the label (plan, section 6): never a feature
LABEL_COLUMNS: tuple[str, ...] = ("churned", "label_end", "known_as_of", "returned", "first_return_date", "days_to_next_purchase")
# What identifies a customer or an invoice (D26): never a feature and never in a published file
IDENTIFIER_COLUMNS: tuple[str, ...] = ("customer_id", "invoice")


class SourceError(RuntimeError):
    """A rule of the source (V01 to V06) failed; ``problems`` says what, one dict per failing item (never a customer number or an invoice)."""

    def __init__(self, rule_id: str, message: str, problems: list[dict[str, Any]] | None = None) -> None:
        super().__init__(f"{rule_id}: {message}")
        self.rule_id = rule_id
        self.problems = problems if problems is not None else []


def line_id(sheet: int, row: int) -> int:
    """Stable id of a line: the sheet (1 or 2) times ten million plus its data row (from 1) in that sheet (project 02)."""
    return sheet * LINE_ID_SHEET_FACTOR + row


def code_kind(stock_code: str) -> str:
    """``product`` (five digits with up to two letters, or a ``DCGS`` code), ``gift_voucher`` (``gift_``) or ``service`` (``PADS`` among them)."""
    if _PRODUCT_CODE.fullmatch(stock_code) or stock_code.startswith(PRODUCT_PREFIXES):
        return "product"
    return "gift_voucher" if stock_code.startswith(GIFT_VOUCHER_PREFIX) else "service"


def code_kinds(codes: pd.Series) -> pd.Series:
    """``code_kind`` of a whole column of text codes, without a Python call per row."""
    kinds = pd.Series("service", index=codes.index, dtype=object)
    kinds[codes.str.startswith(GIFT_VOUCHER_PREFIX)] = "gift_voucher"
    product = codes.str.fullmatch(_PRODUCT_CODE.pattern)
    for prefix in PRODUCT_PREFIXES:
        product |= codes.str.startswith(prefix)
    kinds[product] = "product"
    return kinds
