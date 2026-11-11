"""The features of a cut and their guards against leakage (RF13, AC12, AC13; D09, D12, D26; plan, section 10).

The 16 variables of research.md and the country of the customer's last line, computed **only from what is known before the cut**: the
purchase days and the lines dated before ``c``, with the cancellations known on ``c - 1`` (``known_before``). The windows are
``[c - short_window_days, c - 1]`` and ``[c - long_window_days, c - 1]`` (90 and 365 days by default). ``compute_features`` never filters
in silence: a history that holds the cut day or later is the caller's leak and a ``LeakageError``.

The country is stored as it is (the one of the customer's last purchase or cancellation line before the cut); the groups of the model are
fixed at the launch from the training rows (``country_groups``: the countries with at least ``country_min_customers`` customers, and
«Otros» for the rest and for «Unspecified») and kept in the registry, and ``build_matrix`` maps any other country to «Otros».

Three guards keep what is known later, and what identifies someone, out of a matrix (AC12, M02):

- the **inputs** of ``build_matrix``: a column of the label or of its window, an identifier, the calendar or anything that is not an
  allowed feature (``schema.FEATURE_COLUMNS``) is a ``LeakageError`` naming it, in any spelling (``Customer ID`` is ``customer_id``);
- the **sets**: each column of ``FEATURE_SETS`` must be an allowed feature;
- the **output** (``check_matrix``): exactly the columns of the set, in order.

This module never reads a table of labels: ``read_features`` reads ``mart_cut_population``, the features joined to the blocks, and a static
test reads this file and that SQL and fails if either names one.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterable
from datetime import date, timedelta

import pandas as pd

from churnrisk.config import SealedConfig
from churnrisk.netting import customer_days, net_cancellations
from churnrisk.schema import CALENDAR_COLUMNS, FEATURE_COLUMNS, IDENTIFIER_COLUMNS, LABEL_COLUMNS
from churnrisk.validate import UNSPECIFIED_COUNTRY

COUNTRY = "country_group"
NUMERIC_FEATURES: tuple[str, ...] = tuple(name for name in FEATURE_COLUMNS if name != COUNTRY)
FEATURE_SETS: dict[str, tuple[str, ...]] = {
    "f0": ("rec_days", "freq_365"),            # the two-column variant of research.md
    "f1": NUMERIC_FEATURES,                    # the 16 numeric features
    "f2": NUMERIC_FEATURES + (COUNTRY,),       # and the country, one-hot in the model's pipeline (D13, D15)
}
OTHERS = "Otros"
INTEGER_FEATURES: tuple[str, ...] = ("rec_days", "tenure_days", "freq_total", "freq_90", "freq_365", "units_90", "gap_max", "n_products_365", "canc_365")
FLOAT_FEATURES: tuple[str, ...] = tuple(name for name in NUMERIC_FEATURES if name not in INTEGER_FEATURES)
# the lines before a cut that the features read: the purchases with their net units known on c - 1, and the cancellations
LINE_COLUMNS: tuple[str, ...] = ("line_id", "customer_id", "role", "stock_code", "invoice_ts", "invoice_date", "quantity", "price", "net_quantity", "country")


class LeakageError(RuntimeError):
    """Something that looks at the label window, identifies a customer, names the calendar or is not on the allowed list tried to reach a
    matrix (AC12, M02), or a history that holds the cut day or later reached the features of the cut (AC13)."""


# --- what is known before a cut -------------------------------------------------------------------------------------------------


def known_before(purchases: pd.DataFrame, cancellations: pd.DataFrame, cut: date) -> tuple[pd.DataFrame, pd.DataFrame]:
    """``(days_before, lines_before)`` of `cut`: the net purchase days (``netting.customer_days``) and the lines (``LINE_COLUMNS``) dated
    before the cut, netted with the cancellations known on ``c - 1``. `purchases` and `cancellations` are ``netting.netting_inputs`` with
    their ``country``; whatever they hold from the cut on is left out."""
    for frame, what in ((purchases, "compras"), (cancellations, "anulaciones")):
        if "country" not in frame.columns:
            raise ValueError(f"{what}: falta la columna country (netting.netting_inputs la trae de las líneas canónicas)")
    as_of = cut - timedelta(days=1)
    result = net_cancellations(purchases, cancellations, as_of)
    net = result.net_lines
    country = purchases.set_index("line_id")["country"]
    bought = net.assign(role="purchase", country=net["line_id"].map(country).to_numpy())
    known = cancellations[cancellations["invoice_date"] <= pd.Timestamp(as_of)]
    cancelled = known.assign(role="cancellation", net_quantity=0, customer_id=known["customer_id"].astype("int64"))
    lines = pd.concat([bought[list(LINE_COLUMNS)], cancelled[list(LINE_COLUMNS)]], ignore_index=True)
    return customer_days(net), lines.astype({"line_id": "int64", "customer_id": "int64", "quantity": "int64", "net_quantity": "int64"})


def compute_features(days_before: pd.DataFrame, lines_before: pd.DataFrame, cut: date, customers: pd.Index, view: SealedConfig) -> pd.DataFrame:
    """The features of each of `customers` at `cut`, one row per customer in their order (index ``customer_id``, columns
    ``FEATURE_COLUMNS``). `days_before` and `lines_before` are those of ``known_before``: a day or a line dated on the cut or later is a
    ``LeakageError``, and a customer without a net purchase day before the cut is a ``ValueError``."""
    cut_ts = pd.Timestamp(cut)
    late_days = days_before["day"] >= cut_ts
    late_lines = lines_before["invoice_date"] >= cut_ts
    if late_days.any() or late_lines.any():
        raise LeakageError(f"la historia del corte {cut} tiene {int(late_days.sum())} días de compra y {int(late_lines.sum())} líneas fechados el {cut} "
                           "o después: las variables de un corte solo usan lo anterior a él (RNF06 a)")
    index = pd.Index(customers, dtype="int64", name="customer_id")
    days = days_before[days_before["customer_id"].isin(index)].sort_values(["customer_id", "day"], kind="stable")
    absent = index.difference(pd.Index(days["customer_id"].unique()))
    if len(absent):
        raise ValueError(f"{len(absent)} clientes sin días de compra antes del corte {cut}: solo un cliente de la población tiene variables")
    short = cut_ts - pd.Timedelta(days=view.features.short_window_days)
    long = cut_ts - pd.Timedelta(days=view.features.long_window_days)
    keyed = days.set_index("customer_id")
    in_short, in_long = keyed[keyed["day"] >= short], keyed[keyed["day"] >= long]
    out = pd.DataFrame(index=index)
    out["rec_days"] = (cut_ts - keyed.groupby(level=0)["day"].max()).dt.days
    out["tenure_days"] = (cut_ts - keyed.groupby(level=0)["day"].min()).dt.days
    out["freq_total"] = keyed.groupby(level=0).size()
    out["freq_90"] = in_short.groupby(level=0).size().reindex(index, fill_value=0)
    out["freq_365"] = in_long.groupby(level=0).size().reindex(index, fill_value=0)
    out["mon_total"] = keyed.groupby(level=0)["net_revenue"].sum()
    out["mon_90"] = in_short.groupby(level=0)["net_revenue"].sum().reindex(index, fill_value=0.0)
    out["mon_365"] = in_long.groupby(level=0)["net_revenue"].sum().reindex(index, fill_value=0.0)
    out["aov_day"] = out["mon_total"] / out["freq_total"]
    out["units_90"] = in_short.groupby(level=0)["units"].sum().reindex(index, fill_value=0)
    gaps = keyed.groupby(level=0)["day"].diff().dt.days            # days between consecutive purchase days; none with one day
    out["gap_mean"] = gaps.groupby(level=0).mean().reindex(index).fillna(0.0)
    out["gap_max"] = gaps.groupby(level=0).max().reindex(index).fillna(0)

    lines = lines_before[lines_before["customer_id"].isin(index)].set_index("customer_id")
    live = lines[(lines["role"] == "purchase") & (lines["net_quantity"] > 0) & (lines["invoice_date"] >= long)]
    out["n_products_365"] = live.groupby(level=0)["stock_code"].nunique().reindex(index, fill_value=0)
    out["med_units_365"] = live.groupby(level=0)["net_quantity"].median().reindex(index, fill_value=0.0)
    cancelled = lines[(lines["role"] == "cancellation") & (lines["invoice_date"] >= long)]
    out["canc_365"] = cancelled.groupby(level=0).size().reindex(index, fill_value=0)
    out["canc_value_365"] = (cancelled["quantity"] * cancelled["price"]).abs().groupby(level=0).sum().reindex(index, fill_value=0.0)
    last = lines.reset_index().sort_values(["customer_id", "invoice_ts", "line_id"], kind="stable").groupby("customer_id")["country"].last()
    out[COUNTRY] = last.reindex(index)
    if out[COUNTRY].isna().any():
        raise ValueError(f"{int(out[COUNTRY].isna().sum())} clientes del corte {cut} sin el país de su última línea")
    return out.astype({**dict.fromkeys(INTEGER_FEATURES, "int64"), **dict.fromkeys(FLOAT_FEATURES, "float64"), COUNTRY: object})[list(FEATURE_COLUMNS)]


def country_groups(features: pd.DataFrame, min_customers: int) -> tuple[str, ...]:
    """The country groups of the model, fixed at the launch from the training rows `features` (index with a ``customer_id`` level): the
    countries with at least `min_customers` distinct customers, in alphabetical order, and «Otros» last for the rest and for «Unspecified»."""
    customers = features.index.get_level_values("customer_id")
    pairs = pd.DataFrame({"country": features[COUNTRY].to_numpy(), "customer": customers}).drop_duplicates()
    counts = pairs.groupby("country")["customer"].size()
    kept = sorted(str(c) for c, n in counts.items() if n >= min_customers and c not in (UNSPECIFIED_COUNTRY, OTHERS))
    return (*kept, OTHERS)


# --- the guards and the matrix --------------------------------------------------------------------------------------------------


def _norm(name: str) -> str:
    """A name without case, spaces, underscores or any other mark: ``Customer ID``, ``customer_id`` and ``CUSTOMERID`` are one name."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


_FORBIDDEN: dict[str, str] = {
    **{_norm(n): "de la etiqueta o de su ventana" for n in LABEL_COLUMNS},
    **{_norm(n): "un identificador" for n in IDENTIFIER_COLUMNS},
    **{_norm(n): "del calendario" for n in CALENDAR_COLUMNS},
}


def _refuse(name: object, where: str) -> None:
    if not isinstance(name, str):
        raise LeakageError(f"{where}: el nombre de columna {name!r} no es un texto")
    kind = _FORBIDDEN.get(_norm(name))
    if kind is not None:
        raise LeakageError(f"{where}: la columna {name!r} es {kind} y no puede entrar en una matriz del modelo (AC12)")
    if name not in FEATURE_COLUMNS:
        raise LeakageError(f"{where}: la columna {name!r} no está en la lista de variables permitidas ({', '.join(FEATURE_COLUMNS)})")


def _check_set(feature_set: str) -> tuple[str, ...]:
    if feature_set not in FEATURE_SETS:
        raise ValueError(f"conjunto de variables desconocido: {feature_set!r}; se esperaba uno de {', '.join(FEATURE_SETS)}")
    columns = FEATURE_SETS[feature_set]
    if len(set(columns)) != len(columns):
        raise LeakageError(f"el conjunto {feature_set} repite una columna")
    for name in columns:
        _refuse(name, f"el conjunto {feature_set}")
    return columns


def build_matrix(features: pd.DataFrame, feature_set: str, country_groups: tuple[str, ...]) -> pd.DataFrame:
    """The matrix of `feature_set` from `features` (the keys in the index, never in a column): exactly its columns, in order, with every
    country outside `country_groups` mapped to «Otros». Refuses a forbidden or unknown column of the input or of the set (``LeakageError``)."""
    columns = _check_set(feature_set)
    if not isinstance(features, pd.DataFrame):
        raise TypeError(f"se esperaba un DataFrame, se recibió {type(features).__name__}")
    if features.columns.duplicated().any():
        raise LeakageError(f"columnas repetidas en las variables: {sorted(set(features.columns[features.columns.duplicated()]))}")
    for name in features.columns:
        _refuse(name, "las variables")
    missing = [name for name in columns if name not in features.columns]
    if missing:
        raise ValueError(f"faltan las columnas {missing} del conjunto {feature_set}")
    matrix = features[list(columns)].copy()
    if COUNTRY in columns:
        groups = tuple(country_groups)
        if OTHERS not in groups or len(set(groups)) != len(groups) or UNSPECIFIED_COUNTRY in groups:
            raise ValueError(f"los grupos de país deben ser distintos, sin «{UNSPECIFIED_COUNTRY}» y con «{OTHERS}»; se recibió {list(groups)}")
        matrix[COUNTRY] = matrix[COUNTRY].where(matrix[COUNTRY].isin(groups), OTHERS).astype(object)
    check_matrix(matrix, feature_set)
    return matrix


def check_matrix(matrix: pd.DataFrame, feature_set: str) -> None:
    """M02: the columns of `matrix` are exactly those of `feature_set`, in order, and none looks at the label, identifies or names the
    calendar. ``LeakageError`` otherwise."""
    expected = _check_set(feature_set)
    got = tuple(matrix.columns)
    if got != expected:
        raise LeakageError(f"M02: la matriz del conjunto {feature_set} debe tener exactamente sus columnas, en orden: {list(expected)}; tiene {list(got)}")
    for name in got:
        _refuse(name, "M02")


# --- reading the features of the warehouse --------------------------------------------------------------------------------------


def read_features(conn: sqlite3.Connection, cuts: Iterable[date] | None = None) -> pd.DataFrame:
    """The features of the cuts in the warehouse (``mart_cut_population``), index ``(cut_date, customer_id)``, sorted, columns
    ``FEATURE_COLUMNS``; all the cuts, or those of `cuts`."""
    exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'mart_cut_population'").fetchone()
    wanted = None if cuts is None else sorted({c.isoformat() for c in cuts})
    rows: list[tuple] = []
    if exists:
        where = "" if wanted is None else f" WHERE cut_date IN ({', '.join('?' for _ in wanted)})"
        rows = conn.execute(f"SELECT cut_date, customer_id, {', '.join(FEATURE_COLUMNS)} FROM mart_cut_population{where} ORDER BY cut_date, customer_id",
                            wanted or []).fetchall()
    frame = pd.DataFrame(rows, columns=["cut_date", "customer_id", *FEATURE_COLUMNS])
    frame["cut_date"] = [date.fromisoformat(v) for v in frame["cut_date"]]
    frame = frame.astype({"customer_id": "int64", **dict.fromkeys(INTEGER_FEATURES, "int64"), **dict.fromkeys(FLOAT_FEATURES, "float64"), COUNTRY: object})
    return frame.set_index(["cut_date", "customer_id"])[list(FEATURE_COLUMNS)]
