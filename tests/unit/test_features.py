"""The features of a cut and the guards against leakage (U11, AC12, AC13; RF13, D12, M02): the 16 variables and the country of the last line,
all from what is known before the cut; a matrix takes exactly the columns of its set and nothing that looks at the window, identifies a
customer or names the calendar; the code of the features never reads a table of labels."""

from __future__ import annotations

import re
from datetime import date

import numpy as np
import pandas as pd
import pytest

from churnrisk import features
from churnrisk.config import SealedConfig
from churnrisk.features import (
    FEATURE_SETS,
    NUMERIC_FEATURES,
    OTHERS,
    LeakageError,
    build_matrix,
    check_matrix,
    compute_features,
    country_groups,
    known_before,
)
from churnrisk.schema import CALENDAR_COLUMNS, FEATURE_COLUMNS, IDENTIFIER_COLUMNS, LABEL_COLUMNS
from churnrisk.warehouse import SQL_DIR
from tests.fixtures import hand_cases

SHA = "e" * 64


def a_frame(rows: int = 3) -> pd.DataFrame:
    """A frame with every allowed column, as ``read_features`` gives it (the keys are the index, never a column)."""
    rng = np.random.default_rng(0)
    data = {name: rng.integers(1, 50, rows).astype("float64") for name in NUMERIC_FEATURES}
    data["country_group"] = ["United Kingdom", "France", "Unspecified"][:rows]
    index = pd.MultiIndex.from_tuples([(date(2011, 3, 1), 90001 + i) for i in range(rows)], names=["cut_date", "customer_id"])
    return pd.DataFrame(data, index=index)[list(FEATURE_COLUMNS)]


# --- the RED of U11 -------------------------------------------------------------------------------------------------------


LABEL, IDENTIFIER, CALENDAR, UNKNOWN = "de la etiqueta o de su ventana", "un identificador", "del calendario", "no está en la lista"
REFUSED = [*((n, LABEL) for n in LABEL_COLUMNS), *((n, IDENTIFIER) for n in IDENTIFIER_COLUMNS), *((n, CALENDAR) for n in CALENDAR_COLUMNS),
           ("Customer ID", IDENTIFIER), ("CUSTOMER_ID", IDENTIFIER), ("Churned", LABEL), ("cut month", CALENDAR), ("days to next purchase", LABEL),
           ("rfm_score", UNKNOWN)]


@pytest.mark.parametrize(("name", "kind"), REFUSED)
@pytest.mark.parametrize("feature_set", list(FEATURE_SETS))
def test_leaking_or_identifier_column_cannot_reach_the_matrix(name, kind, feature_set):
    """A column of the label or its window, an identifier, the calendar or anything off the allowed list, in any spelling: refused by name,
    saying which kind it is."""
    frame = a_frame().assign(**{name: 1})
    with pytest.raises(LeakageError, match=re.escape(repr(name))) as error:
        build_matrix(frame, feature_set, ("France", "United Kingdom", OTHERS))
    assert kind in str(error.value)


def test_a_set_that_would_produce_a_leaking_column_is_refused(monkeypatch):
    """What the matrix produces is checked too: a set that names the label cannot build one (M02)."""
    monkeypatch.setitem(FEATURE_SETS, "f1", NUMERIC_FEATURES + ("churned",))
    with pytest.raises(LeakageError, match="churned"):
        build_matrix(a_frame().assign(churned=1), "f1", (OTHERS,))


def test_feature_code_never_reads_label_tables():
    """The code of the features and the SQL that serves them never name a table of labels or the reader of the labelled rows (AC12)."""
    files = [features.__file__, SQL_DIR / "marts" / "ops" / "mart_cut_population.sql"]
    for path in files:
        text = open(path, encoding="utf-8").read().lower()
        for name in ("cut_labels", "mart_labelled_rows", "labelled_rows"):
            assert name not in text, f"{path} names {name}"


# --- the matrix ---------------------------------------------------------------------------------------------------------


def test_each_set_gives_exactly_its_columns_in_order_and_unknown_countries_go_to_others():
    frame = a_frame()
    groups = ("France", OTHERS)
    for name, columns in FEATURE_SETS.items():
        matrix = build_matrix(frame, name, groups)
        assert tuple(matrix.columns) == columns and matrix.index.equals(frame.index)
        check_matrix(matrix, name)
    assert FEATURE_SETS["f0"] == ("rec_days", "freq_365") and len(FEATURE_SETS["f1"]) == 16 and FEATURE_SETS["f2"] == FEATURE_SETS["f1"] + ("country_group",)
    assert build_matrix(frame, "f2", groups)["country_group"].tolist() == ["Otros", "France", "Otros"], "not in the launch's groups, or Unspecified"
    with pytest.raises(ValueError, match="Otros"):
        build_matrix(frame, "f2", ("France",))
    with pytest.raises(ValueError, match="conjunto"):
        build_matrix(frame, "f9", groups)


@pytest.mark.parametrize("change", ["reordered", "missing", "extra"])
def test_m02_refuses_a_matrix_whose_columns_are_not_exactly_its_set(change):
    matrix = build_matrix(a_frame(), "f1", (OTHERS,))
    broken = {"reordered": matrix[list(reversed(matrix.columns))], "missing": matrix.drop(columns="gap_max"),
              "extra": matrix.assign(country_group="France")}[change]
    with pytest.raises(LeakageError, match="M02"):
        check_matrix(broken, "f1")


def test_the_country_groups_are_the_countries_with_enough_training_customers_and_others():
    index = pd.MultiIndex.from_tuples([(date(2010, 6, 1), c) for c in range(1, 8)] + [(date(2010, 7, 1), c) for c in range(1, 4)],
                                      names=["cut_date", "customer_id"])
    rows = pd.DataFrame({"country_group": ["France"] * 3 + ["Unspecified"] * 3 + ["Japan"] + ["France"] * 3}, index=index)
    # France: customers 1-3 in two cuts, 3 distinct; Unspecified 3 but always Others; Japan 1
    assert country_groups(rows, 3) == ("France", OTHERS)
    assert country_groups(rows, 1) == ("France", "Japan", OTHERS)
    assert country_groups(rows, 4) == (OTHERS,)


# --- the features -------------------------------------------------------------------------------------------------------


def test_features_hand_case(cfg):
    """hand_cases.features_case: every feature of three customers, written by hand, with lines after the cut that must not count."""
    case = hand_cases.features_case()
    days, lines = known_before(case.purchases, case.cancellations, case.cut)
    got = compute_features(days, lines, case.cut, pd.Index(case.customers, name="customer_id"), SealedConfig.of(cfg, SHA))
    assert tuple(got.columns) == FEATURE_COLUMNS and tuple(got.index) == case.customers and got.index.name == "customer_id"
    for customer, expected in case.expected.items():
        row = got.loc[customer]
        for name, value in expected.items():
            assert row[name] == pytest.approx(value, abs=1e-12) if isinstance(value, float) else row[name] == value, (customer, name, row[name])
    assert {name: str(got[name].dtype) for name in ("rec_days", "freq_90", "gap_max", "canc_365", "mon_90", "gap_mean")} == {
        "rec_days": "int64", "freq_90": "int64", "gap_max": "int64", "canc_365": "int64", "mon_90": "float64", "gap_mean": "float64"}


def test_the_windows_are_the_configured_days(cfg):
    import dataclasses

    case = hand_cases.features_case()
    view = SealedConfig.of(cfg, SHA)
    shorter = dataclasses.replace(view, features=dataclasses.replace(view.features, short_window_days=89, long_window_days=364))
    days, lines = known_before(case.purchases, case.cancellations, case.cut)
    got = compute_features(days, lines, case.cut, pd.Index([201]), shorter).loc[201]
    # 2010-12-01 and 2010-03-01 are now one day too old
    assert (got["freq_90"], got["mon_90"], got["units_90"], got["freq_365"], got["mon_365"]) == (1, 12.0, 8, 2, 39.0)
    assert (got["n_products_365"], got["med_units_365"]) == (3, 6.0), "B of 2010-03-01 is out; B of 2011-02-28 keeps the product in"


def test_lines_from_the_cut_on_are_refused_not_dropped(cfg):
    """compute_features never filters in silence: a history that holds the cut day or later is the caller's leak, and it is an error."""
    case = hand_cases.features_case()
    days, lines = known_before(case.purchases, case.cancellations, case.cut)
    view = SealedConfig.of(cfg, SHA)
    late_day = pd.concat([days, days.head(1).assign(day=pd.Timestamp(case.cut))], ignore_index=True)
    with pytest.raises(LeakageError, match="2011-03-01"):
        compute_features(late_day, lines, case.cut, pd.Index([201]), view)
    late_line = pd.concat([lines, lines.head(1).assign(invoice_date=pd.Timestamp(2011, 3, 2))], ignore_index=True)
    with pytest.raises(LeakageError, match="2011-03-01"):
        compute_features(days, late_line, case.cut, pd.Index([201]), view)
    with pytest.raises(ValueError, match="sin días de compra"):
        compute_features(days, lines, case.cut, pd.Index([201, 299]), view)
