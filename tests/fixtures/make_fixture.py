"""Synthetic fixture: a zip with the two-sheet workbook of UCI Online Retail II, built from customers whose purchase days follow a
known process, plus the special rows of the real file (plan, section 24; decision D42).

``make_fixture`` writes ``online_retail_II.xlsx`` (the real member name, the two sheets and the eight columns) inside a zip.

- **Synthetic customers** buy on days separated by Gamma gaps (mean ``mean_gap``, shape ``shape``) and, after every purchase day,
  stop for good with probability ``dropout``. ``signal`` decides what drives the dropout:
  ``"none"``: a Beta draw independent of everything else (the BG/NBD process);
  ``"irregular_gaps"`` (positive control): half the customers buy at irregular gaps (shape 0.6) and drop out at 0.30 per purchase,
  the other half at regular gaps (shape 8) and 0.04, with the same mean gaps and spend, so the irregularity of the gaps, which RFM
  does not see, carries the churn;
  ``"rfm_only"`` (negative control): the BG/NBD process itself, with exponential gaps (shape 1) and the Beta dropout of ``"none"``:
  the history says what it can about the future only through recency, frequency and tenure (Fader, Hardie and Lee, 2005), and the
  irregularity of memoryless gaps carries nothing, so RFM sees everything there is.
- **Dedicated customers** (99001 onwards) carry the cases whose answer is known: cancellations that match fully, partly, last in
  first out, with a remainder, never, the same minute and after a label window; a line of 5,000 units; an invoice across midnight;
  a customer with two countries; «Unspecified»; an «A» invoice with a customer; a zero price; a non-positive quantity outside a
  «C» invoice; a «C» line with a positive quantity; ``PADS``; and a product called ``<script>alert(1)</script>``.
- **Guests** (no customer) make about a fifth of the lines, with service codes, a gift voucher, «A» and «C» invoices among them.
- The nine days the sheets share (2010-12-01 to 2010-12-09) are in both sheets; some rows are repeated inside a sheet.

Every customer number has five digits from 90001 on, outside the real range (12346 to 18287), so a byte search finds any of them in
an output. Everything is deterministic for a given seed, down to the bytes of the zip. ``FixtureTruth`` holds what every rule must
count, the population and the label of every cut, written by an independent reading of the generated rows (``_truth``).
``make_malformed`` damages a valid fixture in one documented way for each blocking rule of the source.
"""

from __future__ import annotations

import hashlib
import io
import math
import re
import zipfile
from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path

from xml.sax.saxutils import escape as xml_escape

import numpy as np
import openpyxl
import pandas as pd
from openpyxl.utils.datetime import to_excel

MEMBER = "online_retail_II.xlsx"
SHEETS = ("Year 2009-2010", "Year 2010-2011")
SOURCE_COLUMNS = ("Invoice", "StockCode", "Description", "Quantity", "InvoiceDate", "Price", "Customer ID", "Country")
SIGNALS = ("none", "irregular_gaps", "rfm_only")
MALFORMED_KINDS = (
    "wrong_hash", "extra_member", "member_with_path", "inflated_member", "missing_sheet", "renamed_sheet", "extra_column",
    "missing_column", "renamed_column", "bad_date", "bad_quantity", "six_digit_customer", "overlap_mismatch",
    "two_customers_one_invoice", "oversize",
)

WINDOW_START = date(2009, 12, 1)
WINDOW_END = date(2011, 12, 9)
OVERLAP_START = date(2010, 12, 1)
OVERLAP_END = date(2010, 12, 9)
FIRST_CUT = date(2010, 6, 1)
LAST_CUT = date(2011, 12, 1)

FIXED_TIME = datetime(2024, 1, 5, 0, 0, 0)
ZIP_TIME = (2024, 1, 5, 0, 0, 0)
FIRST_INVOICE = 489434
CUSTOMER_BASE = 90000          # synthetic customers are 90001, 90002, ...
CASE_BASE = 99000              # dedicated customers are 99001, 99002, ...
REAL_ID_RANGE = (12346, 18287)
GUEST_SHARE = 0.22
QUANTITIES = (1, 2, 3, 4, 6, 8, 12, 24)
QUANTITY_WEIGHTS = (0.20, 0.14, 0.10, 0.08, 0.16, 0.08, 0.18, 0.06)
_QUANTITY_CDF = np.cumsum(np.asarray(QUANTITY_WEIGHTS, dtype="float64"))
_QUANTITY_CDF /= _QUANTITY_CDF[-1]


def _quantity(rng: np.random.Generator) -> int:
    """``rng.choice(QUANTITIES, p=QUANTITY_WEIGHTS)`` as numpy draws it (one uniform against the normalised cumulative weights), without
    checking the weights again on every line: the same draws and the same values (D70)."""
    return QUANTITIES[int(_QUANTITY_CDF.searchsorted(rng.random(), side="right"))]
MAX_UNIT_PRICE = 40.0
# 88 % of the synthetic customers are from the United Kingdom; Norway and Japan get so few that they go to «Otros» (D27)
COUNTRIES = ("Germany", "France", "EIRE", "Spain", "Netherlands", "Belgium", "Norway", "Japan")
COUNTRY_WEIGHTS = (0.26, 0.24, 0.18, 0.10, 0.08, 0.08, 0.04, 0.02)
WORDS = (
    "HEART", "VINTAGE", "RETROSPOT", "LANTERN", "CANDLE", "MUG", "BOX", "BAG", "CUSHION", "GARDEN", "BIRD", "METAL",
    "WOODEN", "FRAME", "STAR", "CHRISTMAS", "BUNTING", "TEA", "SPOT", "PAPER",
)
SCRIPT_DESCRIPTION = "<script>alert(1)</script>"
PRODUCT_CODE = re.compile(r"\d{5}[A-Za-z]{0,2}")
OVERSIZE_BYTES = 64 * 1024 * 1024 + 1            # one byte over the default source.max_bytes
INFLATED_BYTES = 100 * 1024 * 1024 + 1           # one byte over the default source.max_member_bytes

Position = tuple[int, int]  # (sheet number 1 or 2, data row from 1)


@dataclass(frozen=True)
class SimCustomer:
    """A synthetic customer: the process that drew its purchase days, and the days."""

    customer_id: int
    group: str            # "none", "regular" or "irregular" (irregular_gaps), "rfm" (rfm_only)
    mean_gap: float
    shape: float
    dropout: float
    spend: float          # mean spend of a purchase day, in pounds
    country: str
    days: tuple[date, ...]


@dataclass(frozen=True)
class FixtureTruth:
    """What the fixture holds, counted over the canonical lines (sheet 1, then sheet 2 without the days it shares with sheet 1)."""

    path: Path
    seed: int
    signal: str
    n_customers: int
    member: str
    zip_sha256: str
    member_sha256: str
    rows_by_sheet: dict[str, int]
    overlap_rows: int                     # rows of each sheet inside the shared days; sheet 2's copies are dropped
    canonical_lines: int
    repeated_lines: int                   # rows equal to an earlier row of their own sheet, kept and flagged (V28)
    first_date: date
    last_date: date
    customers: int                        # distinct customer numbers in the canonical lines
    customer_ids: tuple[int, ...]
    roles: dict[str, int]                 # purchase, cancellation and each exclusion reason, in the order of the rules (RF05)
    cancellation_lines: int               # lines of «C» invoices, whatever their role
    large_quantity_lines: int             # quantity >= 5000 (V29)
    multi_country_customers: int          # V30
    unspecified_country_lines: int        # V31
    multi_date_invoices: int
    script_lines: int
    guest_lines: int
    guest_positive_value: float           # sum of quantity x price over the guest lines with a positive amount (I02)
    unmatched_cancellations_at_end: int   # cancellation lines with units left unmatched, known at the end of the data (V22)
    population: dict[date, tuple[int, ...]]           # every cut: customers with a net purchase day in [c - M, c - 1]
    labels: dict[date, dict[int, int]]                # every cut whose window closes inside the data: customer -> churned
    sim_customers: tuple[SimCustomer, ...]
    positions: dict[str, tuple[Position, ...]] = field(default_factory=dict)


# --- the customers ------------------------------------------------------------------------------------------------


def simulate_customers(n_customers: int, seed: int, signal: str = "none") -> list[SimCustomer]:
    """The synthetic customers and their purchase days, deterministic for `seed` and `signal`."""
    if signal not in SIGNALS:
        raise ValueError(f"unknown signal {signal!r}; expected one of {', '.join(SIGNALS)}")
    rng = np.random.default_rng([seed, 4])
    span = (date(2011, 10, 31) - WINDOW_START).days
    # every customer's parameters are drawn first, the same for every signal; the days come from a stream of their own, so the
    # variants of one seed share customers, mean gaps, spends, births, countries and the Beta dropouts, and differ only in what the
    # signal changes
    mean_gaps = np.clip(np.exp(rng.normal(np.log(38.0), 0.55, n_customers)), 6.0, 220.0)
    spends = np.clip(np.exp(rng.normal(np.log(28.0), 0.6, n_customers)), 4.0, 600.0)
    births = (span * rng.random(n_customers) ** 1.6).astype(int)        # more customers early, as in the real file
    countries = [("United Kingdom" if rng.random() < 0.88 else str(rng.choice(COUNTRIES, p=COUNTRY_WEIGHTS))) for _ in range(n_customers)]
    betas = rng.beta(1.2, 8.0, n_customers)
    irregular = rng.random(n_customers) < 0.5
    days_rng = np.random.default_rng([seed, 5])
    out: list[SimCustomer] = []
    for i in range(n_customers):
        if signal == "none":
            group, shape, dropout = "none", 2.0, float(betas[i])
        elif signal == "irregular_gaps":
            group, shape, dropout = ("irregular", 0.6, 0.30) if irregular[i] else ("regular", 8.0, 0.04)
        else:
            group, shape, dropout = "rfm", 1.0, float(betas[i])
        days: list[date] = []
        t = int(births[i])
        while WINDOW_START + timedelta(days=t) <= WINDOW_END:
            days.append(WINDOW_START + timedelta(days=t))
            if days_rng.random() < dropout:
                break
            t += max(1, int(np.ceil(days_rng.gamma(shape, mean_gaps[i] / shape))))
        out.append(SimCustomer(CUSTOMER_BASE + 1 + i, group, float(mean_gaps[i]), shape, dropout, float(spends[i]), countries[i], tuple(days)))
    return out


# --- invoices -----------------------------------------------------------------------------------------------------


@dataclass
class _Invoice:
    ts: datetime
    customer: int | None
    country: str
    kind: str          # "" (a sale), "C" (a cancellation) or "A" (an adjustment)
    lines: list[dict]


def _line(code: str, desc: str | None, qty: int, price: float, ts: datetime, *labels: str) -> dict:
    # prices have two decimals, except the ones under a penny that the real file has (PADS costs 0.001)
    return {"code": code, "desc": desc, "qty": qty, "price": price if 0 < price < 0.01 else round(price, 2), "ts": ts, "labels": tuple(labels)}


def _stamp(day: date, rng: np.random.Generator) -> datetime:
    return datetime.combine(day, time(8, 0)) + timedelta(minutes=int(rng.integers(0, 600)))


def _catalogue(rng: np.random.Generator, size: int = 160) -> list[dict]:
    items: list[dict] = []
    used: set[int] = set()
    while len(items) < size:
        number = int(rng.integers(10000, 90000))
        if number in used:
            continue
        used.add(number)
        letters = "" if rng.random() < 0.6 else "".join(rng.choice(list("ABCDEFGHIJKLMNOPQRSTUVWXYZ"), size=int(rng.integers(1, 3))))
        items.append({"code": f"{number}{letters}", "desc": " ".join(rng.choice(WORDS, size=3, replace=False)),
                      "price": round(float(np.exp(rng.normal(0.9, 0.6))), 2)})
    items[7]["desc"] = SCRIPT_DESCRIPTION   # a product whose name is markup: every output must escape it
    return items


def _customer_invoices(customer: SimCustomer, catalogue: list[dict], rng: np.random.Generator) -> list[_Invoice]:
    out = []
    for day in customer.days:
        ts = _stamp(day, rng)
        spend = customer.spend * float(np.exp(rng.normal(0.0, 0.3)))
        n_lines = int(min(5, 1 + rng.poisson(1.3)))
        lines = []
        for share, index in zip(rng.dirichlet(np.ones(n_lines)), rng.choice(len(catalogue), size=n_lines, replace=False), strict=True):
            qty = max(_quantity(rng), int(np.ceil(spend * share / MAX_UNIT_PRICE)))
            item = catalogue[int(index)]
            lines.append(_line(item["code"], item["desc"], qty, max(0.10, spend * float(share) / qty), ts))
        out.append(_Invoice(ts, customer.customer_id, customer.country, "", lines))
    return out


def _case_invoices() -> list[_Invoice]:
    """The dedicated customers: every situation of the netting and of the roles whose answer is known."""
    out: list[_Invoice] = []

    def add(customer, ts, code, desc, qty, price, *labels, country="United Kingdom", kind=""):
        out.append(_Invoice(ts, customer, country, kind, [_line(code, desc, qty, price, ts, *labels)]))

    c = CASE_BASE
    add(c + 1, datetime(2011, 2, 7, 10, 15), "71001", "CASE FULL", 12, 2.10, "cancel:full:purchase")
    add(c + 1, datetime(2011, 2, 9, 11, 0), "71001", "CASE FULL", -12, 2.10, "cancel:full:cancel", kind="C")
    add(c + 2, datetime(2011, 2, 14, 9, 30), "71002", "CASE PARTIAL", 24, 1.25, "cancel:partial:purchase")
    add(c + 2, datetime(2011, 2, 16, 14, 5), "71002", "CASE PARTIAL", -10, 1.25, "cancel:partial:cancel", kind="C")
    add(c + 3, datetime(2011, 3, 1, 13, 20), "71003", "CASE UNMATCHED", -6, 3.00, "cancel:unmatched:cancel", kind="C")
    add(c + 4, datetime(2011, 1, 10, 10, 0), "71004", "CASE LIFO", 10, 1.50, "cancel:lifo:purchase")
    add(c + 4, datetime(2011, 1, 24, 15, 40), "71004", "CASE LIFO", 6, 1.50, "cancel:lifo:purchase")
    add(c + 4, datetime(2011, 2, 2, 12, 10), "71004", "CASE LIFO", -8, 1.50, "cancel:lifo:cancel", kind="C")
    add(c + 5, datetime(2011, 4, 4, 10, 30), "71005", "CASE REMAINDER", 5, 4.00, "cancel:remainder:purchase")
    add(c + 5, datetime(2011, 4, 12, 16, 0), "71005", "CASE REMAINDER", -8, 4.00, "cancel:remainder:cancel", kind="C")
    add(c + 6, datetime(2011, 3, 10, 9, 41), "71006", "CASE GIANT", 10_000, 0.50, "cancel:giant:purchase", "large_quantity")
    add(c + 6, datetime(2011, 3, 10, 9, 53), "71006", "CASE GIANT", -10_000, 0.50, "cancel:giant:cancel", kind="C")
    add(c + 7, datetime(2011, 3, 28, 14, 0), "71007", "CASE SAME MINUTE", 3, 6.20, "cancel:same_minute:purchase")
    add(c + 7, datetime(2011, 3, 28, 14, 0), "71007", "CASE SAME MINUTE", -3, 6.20, "cancel:same_minute:cancel", kind="C")
    # active at 2011-03-01 through 2011-02-10; bought in that cut's window on 2011-04-20 and cancelled on 2011-06-15, after the window
    # closed (2011-05-29): the label of 2011-03-01 stays 0, and the cut 2011-04-01, whose window closes on 2011-06-29, knows the
    # cancellation and churns
    add(c + 8, datetime(2011, 2, 10, 10, 0), "71025", "CASE BEFORE THE CUT", 2, 3.50)
    add(c + 8, datetime(2011, 4, 20, 10, 0), "71008", "CASE AFTER WINDOW", 4, 7.00, "cancel:after_window:purchase")
    add(c + 8, datetime(2011, 6, 15, 11, 0), "71008", "CASE AFTER WINDOW", -4, 7.00, "cancel:after_window:cancel", kind="C")
    add(c + 9, datetime(2011, 4, 4, 11, 15), "71009", "CASE BIG LINE", 5000, 0.21, "large_quantity")
    # an invoice whose lines carry two dates: its invoice date is the first one
    first, second = datetime(2011, 3, 15, 23, 56), datetime(2011, 3, 16, 0, 3)
    out.append(_Invoice(first, c + 10, "United Kingdom", "", [
        _line("71010", "CASE TWO DATES A", 2, 3.10, first, "multi_date_invoice"),
        _line("71011", "CASE TWO DATES B", 4, 1.15, second, "multi_date_invoice"),
    ]))
    add(c + 11, datetime(2011, 1, 20, 11, 0), "71013", "CASE TWO COUNTRIES", 6, 2.00, "two_country_customer")
    add(c + 11, datetime(2011, 3, 2, 15, 30), "71013", "CASE TWO COUNTRIES", 12, 2.00, "two_country_customer", country="Germany")
    add(c + 12, datetime(2011, 2, 10, 12, 45), "71016", "CASE UNSPECIFIED", 5, 3.25, "unspecified_country", country="Unspecified")
    add(c + 12, datetime(2011, 5, 10, 12, 45), "71017", "CASE UNSPECIFIED", 1, 12.50, "unspecified_country", country="Unspecified")
    # an «A» invoice with a customer, a product code and positive amounts: only the adjustment rule (V27) sets it aside
    add(c + 13, datetime(2011, 2, 22, 9, 0), "71019", "CASE ADJUSTMENT", 1, 30.00, "adjustment_with_customer", kind="A")
    add(c + 13, datetime(2011, 2, 23, 9, 0), "71020", "CASE PLAIN", 2, 3.00)
    add(c + 14, datetime(2010, 10, 4, 10, 0), "71021", "CASE ZERO PRICE", 3, 0.0, "zero_price_with_customer")
    add(c + 14, datetime(2010, 10, 5, 10, 0), "71022", "CASE NEGATIVE QUANTITY", -2, 1.95, "non_positive_quantity_with_customer")
    add(c + 14, datetime(2010, 10, 6, 10, 0), "71023", "CASE POSITIVE IN C", 2, 1.95, "positive_quantity_in_c", kind="C")
    add(c + 14, datetime(2010, 10, 7, 10, 0), "PADS", "PADS TO MATCH ALL CUSHIONS", 1, 0.001, "pads_with_customer")
    add(c + 14, datetime(2010, 10, 8, 10, 0), "71024", "CASE PLAIN", 6, 1.25)
    return out


def _guest_and_service_invoices(catalogue: list[dict]) -> list[_Invoice]:
    """Rows without a customer that carry the other special situations of the source."""
    out: list[_Invoice] = []

    def add(ts, code, desc, qty, price, *labels, kind=""):
        out.append(_Invoice(ts, None, "United Kingdom", kind, [_line(code, desc, qty, price, ts, *labels)]))

    add(datetime(2010, 3, 18, 10, 5), "71018", "CASE NO CUSTOMER", -3, 1.65, "no_customer_cancellation", kind="C")
    add(datetime(2011, 8, 1, 9, 10), catalogue[9]["code"], catalogue[9]["desc"], -2, 12.95, "no_customer_cancellation", kind="C")
    for ts, code, desc, qty, price in (
        (datetime(2010, 2, 15, 9, 0), "M", "Manual", 1, 4.50), (datetime(2010, 9, 20, 9, 0), "BANK CHARGES", "Bank Charges", 1, 15.00),
        (datetime(2011, 1, 11, 9, 0), "S", "SAMPLES", 1, 12.75), (datetime(2011, 7, 5, 9, 0), "TEST001", "This is a test product.", 5, 4.50),
    ):
        add(ts, code, desc, qty, price, "service_without_customer")
    add(datetime(2011, 3, 22, 10, 0), "gift_0001_20", "Dotcomgiftshop Gift Voucher £20.00", 1, 16.67, "gift_voucher")
    add(datetime(2011, 8, 12, 14, 0), "B", "Adjust bad debt", 1, 11062.06, "adjustment_without_customer", kind="A")
    add(datetime(2011, 8, 12, 14, 1), "B", "Adjust bad debt", 1, -11062.06, "adjustment_without_customer", kind="A")
    return out


# --- zip and workbook ---------------------------------------------------------------------------------------------


def _cell_value(code: str) -> int | str:
    """Even numeric codes are written as numbers and the rest as text, as the real workbook mixes both."""
    return int(code) if code.isdigit() and int(code) % 2 == 0 else code


def _normalise_xlsx(payload: bytes) -> bytes:
    """Rewrite the xlsx container with fixed member timestamps so equal content gives equal bytes (project 02)."""
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(payload)) as source, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
        for info in source.infolist():
            clone = zipfile.ZipInfo(info.filename, date_time=ZIP_TIME)
            clone.compress_type = zipfile.ZIP_DEFLATED
            clone.external_attr = 0o600 << 16
            data = source.read(info.filename)
            if info.filename == "docProps/core.xml":  # openpyxl stamps the save time in "modified"
                data = re.sub(rb"(<dcterms:(?:created|modified)[^>]*>)[^<]*(</dcterms:)", rb"\g<1>2024-01-05T00:00:00Z\g<2>", data)
            target.writestr(clone, data)
    return out.getvalue()


_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_DATETIME_STYLE = 1   # the cellXfs entry with the number format "yyyy-mm-dd hh:mm:ss" (custom format 164)
_STYLES = (
    f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<styleSheet xmlns="{_MAIN_NS}">'
    '<numFmts count="1"><numFmt numFmtId="164" formatCode="yyyy-mm-dd hh:mm:ss"/></numFmts>'
    '<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>'
    '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
    '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    '<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/></cellXfs>'
    '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>'
)


_ILLEGAL_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")   # openpyxl ILLEGAL_CHARACTERS_RE


def _column_letter(index: int) -> str:
    letters = ""
    while index:
        index, rest = divmod(index - 1, 26)
        letters = chr(65 + rest) + letters
    return letters


class _IllegalText(ValueError):
    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.text = text


def _is_empty(value) -> bool:
    return value is None or value is pd.NA or value is pd.NaT or (isinstance(value, float) and math.isnan(value))


def _cell_body(value) -> str | None:
    """The cell after its reference (``<c r="A2"`` + this), or None for an empty value; ``_IllegalText`` for a text XML cannot hold."""
    if _is_empty(value):
        return None
    if isinstance(value, datetime):
        return f' s="{_DATETIME_STYLE}" t="n"><v>{"%.16g" % to_excel(value)}</v></c>'
    if isinstance(value, (bool, np.bool_)):
        return f' t="b"><v>{int(value)}</v></c>'
    if isinstance(value, (int, float, np.integer, np.floating)):
        return f' t="n"><v>{"%.16g" % value}</v></c>'
    text = str(value)
    if _ILLEGAL_XML.search(text):          # what openpyxl refused with IllegalCharacterError: XML 1.0 cannot hold these characters
        raise _IllegalText(text)
    space = ' xml:space="preserve"' if text != text.strip() else ""
    return f' t="inlineStr"><is><t{space}>{xml_escape(text)}</t></is></c>'


def _cell_xml(ref: str, value) -> str:
    """One cell as openpyxl writes it: a number with ``%.16g``, a date and time as its Excel serial number with the date-time style, a text as
    an inline string; an empty value (None, NaN, NaT or pd.NA) writes no cell, which reads back as None, as the empty cell pandas writes does;
    a control character that XML 1.0 cannot hold is refused, as openpyxl refused it."""
    try:
        body = _cell_body(value)
    except _IllegalText as error:
        raise ValueError(f"la celda {ref} tiene un carácter ilegal en XML: {error.text!r}") from None
    return "" if body is None else f'<c r="{ref}"{body}'


def _column_bodies(letter: str, values: list) -> list[str | None]:
    """``_cell_body`` of every value of a column, each distinct value formatted once (codes, countries, quantities and customers repeat; D70)."""
    seen: dict[tuple, str | None] = {}
    out = []
    for number, value in enumerate(values, start=2):
        if _is_empty(value):
            out.append(None)
            continue
        key = (type(value), repr(value) if isinstance(value, (float, np.floating)) else value)   # -0.0 and 0.0 are equal keys otherwise
        body = seen.get(key, False)
        if body is False:
            try:
                body = seen[key] = _cell_body(value)
            except _IllegalText as error:
                raise ValueError(f"la celda {letter}{number} tiene un carácter ilegal en XML: {error.text!r}") from None
        out.append(body)
    return out


def _sheet_xml(frame: pd.DataFrame) -> str:
    letters = [_column_letter(i) for i in range(1, len(frame.columns) + 1)]
    rows = [f'<row r="1">{"".join(_cell_xml(f"{c}1", name) for c, name in zip(letters, frame.columns, strict=True))}</row>']
    columns = [_column_bodies(letter, frame[name].astype(object).tolist()) for letter, name in zip(letters, frame.columns, strict=True)]
    for number, bodies in enumerate(zip(*columns, strict=True), start=2):
        cells = "".join('<c r="' + c + str(number) + '"' + b for c, b in zip(letters, bodies, strict=True) if b is not None)
        rows.append(f'<row r="{number}">{cells}</row>')
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<worksheet xmlns="{_MAIN_NS}">'
            f'<dimension ref="A1:{letters[-1]}{len(frame) + 1}"/><sheetData>{"".join(rows)}</sheetData></worksheet>')


def _workbook_bytes(sheets: dict[str, pd.DataFrame]) -> bytes:
    """The xlsx of `sheets` (a header row with the column names, then one row per line), written part by part.

    The cells are what pandas' ``to_excel`` with openpyxl wrote (D49): the same values, the same number formatting and the date and time as a
    serial number with the format ``yyyy-mm-dd hh:mm:ss``, read back identically by openpyxl in read-only and in normal mode; writing the XML
    directly takes a tenth of the time (D63). Equal content gives equal bytes: the members have fixed timestamps (``_normalise_xlsx``)."""
    names = list(sheets)
    overrides = "".join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                        for i in range(1, len(names) + 1))
    parts = [
        ("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
         '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
         '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
         f'<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>{overrides}</Types>'),
        ("_rels/.rels", f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="{_PKG_REL_NS}">'
         '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>'),
        ("xl/workbook.xml", f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<workbook xmlns="{_MAIN_NS}" xmlns:r="{_REL_NS}"><sheets>'
         + "".join(f'<sheet name="{xml_escape(name)}" sheetId="{i}" r:id="rId{i}"/>' for i, name in enumerate(names, start=1)) + "</sheets></workbook>"),
        ("xl/_rels/workbook.xml.rels", f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="{_PKG_REL_NS}">'
         + "".join(f'<Relationship Id="rId{i}" Type="{_REL_NS}/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1, len(names) + 1))
         + f'<Relationship Id="rId{len(names) + 1}" Type="{_REL_NS}/styles" Target="styles.xml"/></Relationships>'),
        ("xl/styles.xml", _STYLES),
        *((f"xl/worksheets/sheet{i}.xml", _sheet_xml(frame)) for i, frame in enumerate(sheets.values(), start=1)),
    ]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, text in parts:
            archive.writestr(name, text.encode("utf-8"))
    return _normalise_xlsx(buffer.getvalue())


def write_zip(path: Path, members: list[tuple[str, bytes]], prefix: bytes = b"") -> Path:
    """A zip with fixed timestamps; `prefix` bytes before it (a zip reader finds the archive after them)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in members:
            info = zipfile.ZipInfo(name, date_time=ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, payload)
    path.write_bytes(prefix + buffer.getvalue())
    return path


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --- the fixture --------------------------------------------------------------------------------------------------


def make_fixture(path: Path, n_customers: int = 1500, seed: int = 0, signal: str = "none") -> FixtureTruth:
    """Write the fixture zip at `path` and return what it holds."""
    customers = simulate_customers(n_customers, seed, signal)
    rng = np.random.default_rng([seed, 17])
    catalogue = _catalogue(rng)
    invoices: list[_Invoice] = []
    for customer in customers:
        invoices += _customer_invoices(customer, catalogue, rng)
    sales = list(invoices)

    # service lines on invoices of customers: postage, carriage and a manual adjustment
    for index, (code, desc, price) in zip(rng.choice(len(sales), size=9, replace=False),
                                          [("POST", "POSTAGE", 18.0)] * 5 + [("DOT", "DOTCOM POSTAGE", 9.5)] * 2 + [("M", "Manual", 2.5)] * 2, strict=True):
        sales[int(index)].lines.append(_line(code, desc, 1, price, sales[int(index)].ts, "service_with_customer"))
    # cancellations of customers' lines, on invoices with two lines or more: most leave units of the line, some cancel all of it;
    # the netting takes each off the customer's latest purchase of that product, which the truth computes like any other
    eligible = [inv for inv in sales if len(inv.lines) >= 2 and inv.ts.date() <= date(2011, 11, 20)]
    for index in rng.choice(len(eligible), size=min(40, len(eligible)), replace=False):
        invoice = eligible[int(index)]
        line = next(item for item in invoice.lines if PRODUCT_CODE.fullmatch(item["code"]))
        units = line["qty"] if rng.random() < 0.3 else max(1, line["qty"] // 2)
        later = invoice.ts + timedelta(days=int(rng.integers(1, 20)), minutes=int(rng.integers(0, 300)))
        if later.date() <= WINDOW_END:
            invoices.append(_Invoice(later, invoice.customer, invoice.country, "C", [
                _line(line["code"], line["desc"], -units, line["price"], later, "customer_cancellation")]))
    invoices += _case_invoices()
    invoices += _guest_and_service_invoices(catalogue)

    # guests until about GUEST_SHARE of the lines have no customer; the first and last days of the file and both ends of the
    # shared days always have some
    total = sum(len(i.lines) for i in invoices)
    without = sum(len(i.lines) for i in invoices if i.customer is None)
    wanted = int(np.ceil((GUEST_SHARE * total - without) / (1 - GUEST_SHARE)))
    forced = [WINDOW_START, OVERLAP_START, date(2010, 12, 5), OVERLAP_END, WINDOW_END]
    guest_lines = 0
    n_days = (WINDOW_END - WINDOW_START).days + 1
    while guest_lines < wanted or forced:
        day = forced.pop(0) if forced else WINDOW_START + timedelta(days=int(rng.integers(0, n_days)))
        ts = _stamp(day, rng)
        lines = []
        for i in rng.choice(len(catalogue), size=int(min(4, 1 + rng.poisson(1.2))), replace=False):
            item = catalogue[int(i)]
            lines.append(_line(item["code"], item["desc"], _quantity(rng), item["price"] * float(rng.uniform(0.9, 1.1)), ts))
        invoices.append(_Invoice(ts, None, "United Kingdom" if rng.random() < 0.85 else str(rng.choice(COUNTRIES)), "", lines))
        guest_lines += len(lines)

    # number the invoices in time order; ties keep creation order, so a purchase comes before its same-minute cancellation
    invoices.sort(key=lambda inv: inv.ts)
    rows: list[dict] = []
    for sequence, invoice in enumerate(invoices, start=FIRST_INVOICE):
        number = f"{invoice.kind}{sequence}" if invoice.kind else sequence
        for line in invoice.lines:
            rows.append({
                "Invoice": number, "StockCode": _cell_value(line["code"]), "Description": line["desc"], "Quantity": line["qty"],
                "InvoiceDate": line["ts"].replace(microsecond=0), "Price": line["price"],
                "Customer ID": np.nan if invoice.customer is None else float(invoice.customer), "Country": invoice.country,
                "labels": line["labels"],
            })
    rows = _repeat_rows(rows, rng)
    first = [r for r in rows if r["InvoiceDate"].date() <= OVERLAP_END]
    second = [r for r in rows if r["InvoiceDate"].date() >= OVERLAP_START]
    payload = _workbook_bytes({SHEETS[0]: _frame(first), SHEETS[1]: _frame(second)})
    write_zip(path, [(MEMBER, payload)])
    return _truth(Path(path), seed, signal, n_customers, payload, first, second, tuple(customers))


def _repeat_rows(rows: list[dict], rng: np.random.Generator) -> list[dict]:
    """Insert, right after their original, exact copies of plain rows: 4 only in sheet 1, 3 only in sheet 2, 2 in the shared days."""
    plain = [i for i, r in enumerate(rows) if not r["labels"] and r["Quantity"] > 0 and r["Price"] > 0]

    def pick(low: date, high: date, count: int) -> list[int]:
        pool = [i for i in plain if low <= rows[i]["InvoiceDate"].date() <= high]
        if len(pool) < count:   # drawn without replacement: say which window is short, not numpy's generic error
            raise ValueError(f"the window {low} to {high} has {len(pool)} plain rows to repeat and {count} are needed")
        return [int(i) for i in rng.choice(pool, size=count, replace=False)]

    chosen = set(pick(WINDOW_START, OVERLAP_START - timedelta(days=1), 4))
    chosen |= set(pick(OVERLAP_END + timedelta(days=1), WINDOW_END, 3))
    chosen |= set(pick(OVERLAP_START, OVERLAP_END, 2))
    out: list[dict] = []
    for i, row in enumerate(rows):
        out.append(row)
        if i in chosen:
            out.append({**row, "labels": ("repeated_line",)})
    return out


def _frame(rows: list[dict]) -> pd.DataFrame:
    frame = pd.DataFrame([{c: r[c] for c in SOURCE_COLUMNS} for r in rows], columns=list(SOURCE_COLUMNS))
    frame["Invoice"] = frame["Invoice"].astype(object)
    frame["StockCode"] = frame["StockCode"].astype(object)
    frame["Quantity"] = frame["Quantity"].astype("int64")
    frame["InvoiceDate"] = pd.to_datetime(frame["InvoiceDate"])
    frame["Price"] = frame["Price"].astype("float64")
    frame["Customer ID"] = frame["Customer ID"].astype("float64")
    return frame


# --- the truth, read back from the generated rows -------------------------------------------------------------------


def code_kind(code: str) -> str:
    """product (five digits and up to two letters, or DCGS), gift_voucher (gift_) or service, as project 02 (D03)."""
    if PRODUCT_CODE.fullmatch(code) or code.startswith("DCGS"):
        return "product"
    return "gift_voucher" if code.startswith("gift_") else "service"


def role_of(invoice: str, code: str, qty: int, price: float, customer: int | None) -> str:
    """The role of a line by the first rule of RF05 that sets it aside, written apart from the product's ``classify_lines``."""
    cancel = invoice.startswith("C")
    kind = code_kind(code)
    if customer is None:
        return "no_customer"
    if (cancel and qty >= 0) or (not cancel and qty <= 0):
        return "non_positive_quantity"
    if price <= 0:
        return "non_positive_price"
    if kind == "service":
        return "service_code"
    if kind == "gift_voucher":
        return "gift_voucher"
    if invoice.startswith("A"):
        return "adjustment_invoice"
    return "cancellation" if cancel else "purchase"


ROLE_ORDER = ("purchase", "cancellation", "no_customer", "non_positive_quantity", "non_positive_price", "service_code", "gift_voucher", "adjustment_invoice")


def _event_order(r: dict) -> tuple:
    """Time, then a purchase before a cancellation of the same instant, then the order of the canonical lines (project 02, D04)."""
    return (r["ts"], r["role"] != "purchase", r["order"])


@dataclass(frozen=True)
class _NettingLines:
    """The purchase and cancellation lines of one ``lines`` list grouped once for every date (D70): the days of each customer from the
    products it never cancelled, sorted, and the lines of each customer and product that a cancellation touches, in event order."""

    uncancelled_days: dict[int, list[date]]
    cancelled_keys: dict[tuple[int, str], list[dict]]


_PREPARED: dict[int, tuple[list[dict], _NettingLines]] = {}


def _prepared(lines: list[dict]) -> _NettingLines:
    cached = _PREPARED.get(id(lines))
    if cached is not None and cached[0] is lines:
        return cached[1]
    by_key: dict[tuple[int, str], list[dict]] = {}
    for r in lines:
        if r["role"] in ("purchase", "cancellation"):
            by_key.setdefault((r["customer"], r["code"]), []).append(r)
    uncancelled: dict[int, set[date]] = {}
    cancelled: dict[tuple[int, str], list[dict]] = {}
    for key, group in by_key.items():
        if any(r["role"] == "cancellation" for r in group):
            cancelled[key] = group
        else:
            uncancelled.setdefault(key[0], set()).update(r["invoice_date"] for r in group if r["qty"] > 0)
    prepared = _NettingLines({c: sorted(d) for c, d in uncancelled.items()}, cancelled)
    _PREPARED.clear()                     # one list at a time: the fixture's truth, or the oracle of a test
    _PREPARED[id(lines)] = (lines, prepared)
    return prepared


def net_purchase_days(lines: list[dict], as_of: date) -> dict[int, set[date]]:
    """Each customer's days with a net purchase, with the cancellations known on `as_of`: last in, first out by customer and product.
    `lines` must be in ``_event_order``.

    A product that a customer never cancelled keeps every purchase, so its days are those dated on or before `as_of`; only the lines of a
    customer and product with a cancellation go through the stack, in event order. The grouping is done once per list (D70)."""
    prepared = _prepared(lines)
    days: dict[int, set[date]] = {}
    for customer, sorted_days in prepared.uncancelled_days.items():
        known = bisect_right(sorted_days, as_of)
        if known:
            days[customer] = set(sorted_days[:known])
    for key, group in prepared.cancelled_keys.items():
        stack: list[list] = []
        for r in group:
            if r["invoice_date"] > as_of:
                continue
            if r["role"] == "purchase":
                stack.append([r, r["qty"]])
                continue
            left = -r["qty"]
            while left > 0 and stack:
                take = min(left, stack[-1][1])
                stack[-1][1] -= take
                left -= take
                if stack[-1][1] == 0:
                    stack.pop()
        for r, remaining in stack:
            if remaining > 0:
                days.setdefault(key[0], set()).add(r["invoice_date"])
    return days


def _unmatched_cancellations(lines: list[dict], as_of: date) -> int:
    """Cancellation lines known on `as_of` with units that no earlier purchase of the customer and product covers. `lines` in ``_event_order``."""
    known = [r for r in lines if r["invoice_date"] <= as_of and r["role"] in ("purchase", "cancellation")]
    stacks: dict[tuple[int, str], list[int]] = {}
    unmatched = 0
    for r in known:
        key = (r["customer"], r["code"])
        if r["role"] == "purchase":
            stacks.setdefault(key, []).append(r["qty"])
            continue
        left = -r["qty"]
        stack = stacks.get(key, [])
        while left > 0 and stack:
            take = min(left, stack[-1])
            stack[-1] -= take
            left -= take
            if stack[-1] == 0:
                stack.pop()
        unmatched += left > 0
    return unmatched


def cut_dates(first: date = FIRST_CUT, last: date = LAST_CUT) -> list[date]:
    out, day = [], first
    while day <= last:
        out.append(day)
        day = date(day.year + (day.month == 12), day.month % 12 + 1, 1)
    return out


def _truth(path: Path, seed: int, signal: str, n_customers: int, payload: bytes, first: list[dict], second: list[dict],
           customers: tuple[SimCustomer, ...], horizon_days: int = 90, active_days: int = 90) -> FixtureTruth:
    kept = [(1, i, r) for i, r in enumerate(first, start=1)]
    kept += [(2, i, r) for i, r in enumerate(second, start=1) if r["InvoiceDate"].date() > OVERLAP_END]
    flat = [r for _s, _i, r in kept]

    def customer(r: dict) -> int | None:
        return None if np.isnan(r["Customer ID"]) else int(r["Customer ID"])

    invoice_dates: dict[str, date] = {}
    for r in flat:
        key = str(r["Invoice"])
        invoice_dates[key] = min(invoice_dates.get(key, r["InvoiceDate"].date()), r["InvoiceDate"].date())
    lines = []
    for order, r in enumerate(flat):
        invoice = str(r["Invoice"])
        lines.append({"order": order, "customer": customer(r), "code": str(r["StockCode"]), "qty": int(r["Quantity"]), "ts": r["InvoiceDate"],
                      "invoice_date": invoice_dates[invoice], "role": role_of(invoice, str(r["StockCode"]), int(r["Quantity"]), float(r["Price"]), customer(r))})
    roles = {name: sum(line["role"] == name for line in lines) for name in ROLE_ORDER}
    lines.sort(key=_event_order)

    labelled: dict[str, list[Position]] = {}
    for sheet, number, r in kept:
        for label in r["labels"]:
            labelled.setdefault(label, []).append((sheet, number))

    def repeated(rows: list[dict]) -> int:
        seen: set[tuple] = set()
        count = 0
        for r in rows:
            key = tuple(None if (isinstance(r[c], float) and np.isnan(r[c])) else r[c] for c in SOURCE_COLUMNS)
            count += key in seen
            seen.add(key)
        return count

    countries: dict[int, set[str]] = {}
    for r in flat:
        if customer(r) is not None:
            countries.setdefault(customer(r), set()).add(r["Country"])
    dates_by_invoice: dict[str, set[date]] = {}
    for r in flat:
        dates_by_invoice.setdefault(str(r["Invoice"]), set()).add(r["InvoiceDate"].date())

    population: dict[date, tuple[int, ...]] = {}
    labels: dict[date, dict[int, int]] = {}
    m, n = timedelta(days=active_days), timedelta(days=horizon_days)
    for cut in cut_dates():
        before = net_purchase_days(lines, cut - timedelta(days=1))
        active = tuple(sorted(c for c, days in before.items() if any(cut - m <= d < cut for d in days)))
        population[cut] = active
        end = cut + n - timedelta(days=1)
        if end <= WINDOW_END:
            after = net_purchase_days(lines, end)
            labels[cut] = {c: int(not any(cut <= d <= end for d in after.get(c, ()))) for c in active}

    guests = [r for r in flat if customer(r) is None]
    return FixtureTruth(
        path=path, seed=seed, signal=signal, n_customers=n_customers, member=MEMBER, zip_sha256=sha256_of(path.read_bytes()),
        member_sha256=sha256_of(payload), rows_by_sheet={SHEETS[0]: len(first), SHEETS[1]: len(second)},
        overlap_rows=sum(OVERLAP_START <= r["InvoiceDate"].date() <= OVERLAP_END for r in second), canonical_lines=len(kept),
        repeated_lines=repeated(first) + repeated([r for r in second if r["InvoiceDate"].date() > OVERLAP_END]),
        first_date=min(r["InvoiceDate"].date() for r in flat), last_date=max(r["InvoiceDate"].date() for r in flat),
        customers=len(countries), customer_ids=tuple(sorted(countries)), roles=roles,
        cancellation_lines=sum(str(r["Invoice"]).startswith("C") for r in flat),
        large_quantity_lines=sum(r["Quantity"] >= 5000 for r in flat),
        multi_country_customers=sum(len(c) > 1 for c in countries.values()),
        unspecified_country_lines=sum(r["Country"] == "Unspecified" for r in flat),
        multi_date_invoices=sum(len(d) > 1 for d in dates_by_invoice.values()),
        script_lines=sum(r["Description"] == SCRIPT_DESCRIPTION for r in flat),
        guest_lines=len(guests), guest_positive_value=round(sum(r["Quantity"] * r["Price"] for r in guests if r["Quantity"] * r["Price"] > 0), 2),
        unmatched_cancellations_at_end=_unmatched_cancellations(lines, WINDOW_END),
        population=population, labels=labels, sim_customers=customers,
        positions={label: tuple(found) for label, found in labelled.items()},
    )


# --- malformed variants ---------------------------------------------------------------------------------------------


def make_malformed(base: Path, kind: str, out: Path) -> Path:
    """Damage the fixture at `base` in one documented way and write the result at `out`; `base` is left untouched."""
    if kind not in MALFORMED_KINDS:
        raise ValueError(f"unknown malformed kind {kind!r}; expected one of {', '.join(MALFORMED_KINDS)}")
    original = Path(base).read_bytes()
    with zipfile.ZipFile(io.BytesIO(original)) as archive:
        payload = archive.read(MEMBER)
    if kind == "extra_member":
        return write_zip(out, [(MEMBER, payload), ("notes.txt", b"not part of the source\n")])
    if kind == "member_with_path":
        return write_zip(out, [(f"../{MEMBER}", payload)])
    if kind == "inflated_member":   # compresses to about 100 KB and inflates past max_member_bytes
        return write_zip(out, [(MEMBER, bytes(INFLATED_BYTES))])
    if kind == "oversize":          # the same archive, preceded by enough bytes to pass max_bytes
        return write_zip(out, [(MEMBER, payload)], prefix=bytes(max(0, OVERSIZE_BYTES - len(original))))

    workbook = openpyxl.load_workbook(io.BytesIO(payload))
    first, second = workbook[SHEETS[0]], workbook[SHEETS[1]]
    col = {name: index for index, name in enumerate(SOURCE_COLUMNS, start=1)}
    if kind == "wrong_hash":
        row = next(r for r in range(second.max_row, 1, -1) if second.cell(r, col["Description"]).value)
        second.cell(row, col["Description"]).value = str(second.cell(row, col["Description"]).value) + " (changed)"
    elif kind == "missing_sheet":
        del workbook[SHEETS[1]]
    elif kind == "renamed_sheet":
        second.title = "Year 2010-11"
    elif kind == "extra_column":
        for sheet in (first, second):
            sheet.cell(1, len(SOURCE_COLUMNS) + 1).value = "Notes"
            sheet.cell(2, len(SOURCE_COLUMNS) + 1).value = "extra"
    elif kind == "missing_column":
        for sheet in (first, second):
            sheet.delete_cols(col["Price"])
    elif kind == "renamed_column":
        for sheet in (first, second):
            sheet.cell(1, col["Customer ID"]).value = "CustomerID"
    elif kind == "bad_date":
        first.cell(5, col["InvoiceDate"]).value = "not a date"
    elif kind == "bad_quantity":
        first.cell(5, col["Quantity"]).value = "ten"
    elif kind == "six_digit_customer":
        row = next(r for r in range(2, first.max_row + 1) if first.cell(r, col["Customer ID"]).value is not None)
        first.cell(row, col["Customer ID"]).value = 123456.0
    elif kind == "overlap_mismatch":
        row = next(r for r in range(2, second.max_row + 1) if second.cell(r, col["InvoiceDate"]).value.date() >= OVERLAP_START)
        second.cell(row, col["Quantity"]).value = second.cell(row, col["Quantity"]).value + 1
    elif kind == "two_customers_one_invoice":
        rows = list(first.iter_rows(min_row=2, values_only=True))
        for index in range(len(rows) - 1):
            a, b = rows[index], rows[index + 1]
            if a[0] == b[0] and a[6] is not None and b[6] is not None and a[4].date() < OVERLAP_START:
                first.cell(index + 3, col["Customer ID"]).value = float(CASE_BASE + 99)
                break
        else:  # pragma: no cover - the fixture always has an invoice with two customer lines
            raise RuntimeError("no invoice with two customer lines to damage")
    workbook.properties.created = FIXED_TIME
    workbook.properties.modified = FIXED_TIME
    buffer = io.BytesIO()
    workbook.save(buffer)
    return write_zip(out, [(MEMBER, _normalise_xlsx(buffer.getvalue()))])
