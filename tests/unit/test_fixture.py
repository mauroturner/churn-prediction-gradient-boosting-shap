"""The synthetic fixture (U03, D42): what its truth says is what the workbook holds, read here apart from the generator; the cases whose
answer is known hold; the planted signals are where they should be; the malformed variants are damaged in their one way; and the hand
cases agree with a brute-force reading of their rule."""

from __future__ import annotations

import io
import math
import zipfile
from collections import Counter
from datetime import date, timedelta

import numpy as np
import openpyxl
import pytest
from sklearn.metrics import average_precision_score, roc_auc_score

from tests.fixtures import hand_cases
from tests.fixtures.make_fixture import (
    CASE_BASE,
    MALFORMED_KINDS,
    MEMBER,
    OVERLAP_END,
    OVERLAP_START,
    REAL_ID_RANGE,
    SCRIPT_DESCRIPTION,
    SHEETS,
    SOURCE_COLUMNS,
    WINDOW_END,
    cut_dates,
    make_fixture,
    net_purchase_days,
    simulate_customers,
)


def read_workbook(path) -> dict[str, list[tuple]]:
    """The rows of each sheet, header first, read with openpyxl straight from the zip."""
    with zipfile.ZipFile(path) as archive:
        payload = archive.read(MEMBER)
    book = openpyxl.load_workbook(io.BytesIO(payload), read_only=True)
    try:
        return {sheet.title: list(sheet.iter_rows(values_only=True)) for sheet in book.worksheets}
    finally:
        book.close()


def sim_rows(customers, cuts, horizon=90, active=90):
    """(group, freq_365, churned) of every synthetic customer active at each cut, from its purchase days."""
    out = []
    for customer in customers:
        days = np.array([d.toordinal() for d in customer.days])
        for cut in cuts:
            c = cut.toordinal()
            before = days[days < c]
            if not len(before) or before.max() < c - active:
                continue
            out.append((customer.group, int((before >= c - 365).sum()), int(not ((days >= c) & (days < c + horizon)).any())))
    return out


# --- the truth is the workbook ---------------------------------------------------------------------------------------


def test_truth_counts_match_the_workbook_and_the_planted_mechanics_hold(fixture_truth):
    truth = fixture_truth
    sheets = read_workbook(truth.path)
    assert list(sheets) == list(SHEETS)
    for name, rows in sheets.items():
        assert rows[0] == SOURCE_COLUMNS, name
        assert len(rows) - 1 == truth.rows_by_sheet[name], name
    first, second = sheets[SHEETS[0]][1:], sheets[SHEETS[1]][1:]

    # the nine shared days hold the same rows in both sheets; sheet 2's copies are dropped from the canonical lines
    shared_first = Counter(r for r in first if r[4].date() >= OVERLAP_START)
    shared_second = Counter(r for r in second if r[4].date() <= OVERLAP_END)
    assert shared_first == shared_second and sum(shared_second.values()) == truth.overlap_rows > 0
    assert max(r[4].date() for r in first) == OVERLAP_END and min(r[4].date() for r in second) == OVERLAP_START
    canonical = first + [r for r in second if r[4].date() > OVERLAP_END]
    assert len(canonical) == truth.canonical_lines
    assert (min(r[4].date() for r in canonical), max(r[4].date() for r in canonical)) == (truth.first_date, truth.last_date) == (date(2009, 12, 1), WINDOW_END)

    # repeated rows inside a sheet are kept, counted per sheet over the canonical lines
    repeated = sum(sum(n - 1 for n in Counter(rows).values()) for rows in (first, [r for r in second if r[4].date() > OVERLAP_END]))
    assert repeated == truth.repeated_lines == 9

    # every customer number has five digits outside the real range, so a byte search finds it; guests have none
    ids = {int(r[6]) for r in canonical if r[6] is not None}
    assert ids == set(truth.customer_ids) and len(ids) == truth.customers
    assert all(90001 <= i <= 99999 for i in ids) and not any(REAL_ID_RANGE[0] <= i <= REAL_ID_RANGE[1] for i in ids)
    guests = [r for r in canonical if r[6] is None]
    assert len(guests) == truth.guest_lines == truth.roles["no_customer"]
    assert 0.18 < len(guests) / len(canonical) < 0.26
    assert math.isclose(sum(r[3] * r[5] for r in guests if r[3] * r[5] > 0), truth.guest_positive_value, abs_tol=0.01)

    # the counts of the rules, read from the cells
    assert sum(str(r[0]).startswith("C") for r in canonical) == truth.cancellation_lines
    assert sum(r[3] >= 5000 for r in canonical) == truth.large_quantity_lines == 2   # the giant purchase (10,000) and the big line (5,000)
    assert sum(r[7] == "Unspecified" for r in canonical) == truth.unspecified_country_lines == 2
    countries: dict[int, set[str]] = {}
    for r in canonical:
        if r[6] is not None:
            countries.setdefault(int(r[6]), set()).add(r[7])
    assert sum(len(c) > 1 for c in countries.values()) == truth.multi_country_customers == 1
    assert sum(r[2] == SCRIPT_DESCRIPTION for r in canonical) == truth.script_lines > 0
    with_customer = [r for r in canonical if r[6] is not None]
    assert any(str(r[1]) == "PADS" and r[5] > 0 for r in with_customer)
    assert any(str(r[0]).startswith("A") for r in with_customer) and any(str(r[0]).startswith("A") for r in guests)
    assert any(str(r[1]).startswith("gift_") for r in guests)
    assert any(str(r[0]).startswith("C") and r[3] > 0 for r in with_customer)        # a «C» line with a positive quantity
    assert any(not str(r[0]).startswith(("C", "A")) and r[3] <= 0 for r in with_customer)
    assert any(r[5] == 0 for r in with_customer)
    assert truth.roles == {
        "purchase": truth.roles["purchase"], "cancellation": truth.roles["cancellation"], "no_customer": len(guests),
        "non_positive_quantity": 2, "non_positive_price": 1, "service_code": 10, "gift_voucher": 0, "adjustment_invoice": 1,
    }
    assert sum(truth.roles.values()) == len(canonical)
    assert truth.multi_date_invoices == 1 and truth.unmatched_cancellations_at_end == 2

    # the population and the labels: every cut from 2010-06-01 to 2011-12-01; labels only where the window closes inside the data
    cuts = cut_dates()
    assert list(truth.population) == cuts and cuts[0] == date(2010, 6, 1) and cuts[-1] == date(2011, 12, 1)
    assert list(truth.labels) == [c for c in cuts if c + timedelta(days=89) <= WINDOW_END] and max(truth.labels) == date(2011, 9, 1)
    for cut, labels in truth.labels.items():
        assert tuple(sorted(labels)) == truth.population[cut], cut
    # the dedicated customers whose answer follows from the rule by hand
    march, april, may = date(2011, 3, 1), date(2011, 4, 1), date(2011, 5, 1)
    assert CASE_BASE + 1 not in truth.population[march]                 # bought on 02-07, cancelled all of it on 02-09
    assert truth.labels[march][CASE_BASE + 2] == 1                      # 14 of 24 units left on 02-14, nothing in the window
    assert truth.labels[march][CASE_BASE + 8] == 0 and truth.labels[april][CASE_BASE + 8] == 1   # 04-20 cancelled on 06-15
    assert not any(CASE_BASE + 6 in truth.population[c] for c in cuts)  # the giant line was cancelled twelve minutes later
    assert CASE_BASE + 9 in truth.population[may]                       # the line of 5,000 units on 2011-04-04 is a purchase
    assert 0.15 < np.mean([np.mean(list(v.values())) for v in truth.labels.values()]) < 0.5
    # the synthetic customers with no cancellation: their population and labels follow from their purchase days alone
    cancelled = {int(r[6]) for r in canonical if str(r[0]).startswith("C") and r[6] is not None}
    for customer in truth.sim_customers:
        if customer.customer_id in cancelled:
            continue
        for cut in cuts:
            active = any(cut - timedelta(days=90) <= d < cut for d in customer.days)
            assert (customer.customer_id in truth.population[cut]) == active, (customer.customer_id, cut)
            if active and cut in truth.labels:
                churned = int(not any(cut <= d <= cut + timedelta(days=89) for d in customer.days))
                assert truth.labels[cut][customer.customer_id] == churned, (customer.customer_id, cut)

    # the planted mechanics, on the processes themselves
    train = cuts[:7]
    irregular = sim_rows(simulate_customers(1500, 0, "irregular_gaps"), train)
    rate = {g: np.mean([y for group, _f, y in irregular if group == g]) for g in ("irregular", "regular")}
    assert rate["irregular"] - rate["regular"] > 0.3, rate
    # within every tercile of the frequency RFM sees, the irregular customers still churn more: frequency does not absorb the signal
    edges = np.quantile([f for _g, f, _y in irregular], [1 / 3, 2 / 3])
    for low, high in ((-np.inf, edges[0]), (edges[0], edges[1]), (edges[1], np.inf)):
        band = [(g, y) for g, f, y in irregular if low < f <= high]
        by = {g: np.mean([y for gg, y in band if gg == g]) for g in ("irregular", "regular")}
        assert by["irregular"] - by["regular"] > 0.15, (low, high, by)
    none, rfm_only = simulate_customers(1500, 0, "none"), simulate_customers(1500, 0, "rfm_only")
    assert {c.shape for c in none} == {2.0} and {c.shape for c in rfm_only} == {1.0}
    assert [(c.customer_id, c.dropout, c.mean_gap, c.spend, c.days[0]) for c in none] == [(c.customer_id, c.dropout, c.mean_gap, c.spend, c.days[0]) for c in rfm_only]


def test_the_fixture_is_deterministic_for_a_seed_and_another_seed_changes_it(tmp_path, small_truth):
    again = make_fixture(tmp_path / "again.zip", n_customers=300, seed=0)
    assert again.zip_sha256 == small_truth.zip_sha256 and again.member_sha256 == small_truth.member_sha256
    assert simulate_customers(300, 1)[0].days != simulate_customers(300, 0)[0].days


def test_the_small_fixture_has_the_same_cases_with_fewer_customers(small_truth, fixture_truth):
    assert small_truth.canonical_lines < fixture_truth.canonical_lines / 3
    for key in ("non_positive_quantity", "non_positive_price", "service_code", "adjustment_invoice"):
        assert small_truth.roles[key] == fixture_truth.roles[key], key
    assert set(small_truth.positions) == set(fixture_truth.positions)


# --- the malformed variants -----------------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", MALFORMED_KINDS)
def test_each_malformed_variant_is_damaged_in_its_one_way(malformed, tiny_zip, kind):
    path = malformed(kind)
    assert path.read_bytes() != tiny_zip.read_bytes()
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        names = [i.filename for i in infos]
        if kind == "extra_member":
            assert names == [MEMBER, "notes.txt"]
            return
        if kind == "member_with_path":
            assert names == [f"../{MEMBER}"]
            return
        assert names == [MEMBER]
        if kind == "inflated_member":
            assert infos[0].file_size > 100 * 1024 * 1024 and path.stat().st_size < 1024 * 1024
            return
        if kind == "oversize":
            assert path.stat().st_size > 64 * 1024 * 1024 and archive.read(MEMBER) == zipfile.ZipFile(tiny_zip).read(MEMBER)
            return
    sheets = read_workbook(path)
    rows = {name: rows[1:] for name, rows in sheets.items()}
    header = {name: rows_[0] for name, rows_ in sheets.items()}
    expected_shape = {
        "missing_sheet": lambda: list(sheets) == [SHEETS[0]],
        "renamed_sheet": lambda: list(sheets) == [SHEETS[0], "Year 2010-11"],
        "extra_column": lambda: all(h[:8] == SOURCE_COLUMNS and h[8] == "Notes" for h in header.values()),
        "missing_column": lambda: all("Price" not in h and len(h) == 7 for h in header.values()),
        "renamed_column": lambda: all("CustomerID" in h and "Customer ID" not in h for h in header.values()),
        "bad_date": lambda: rows[SHEETS[0]][3][4] == "not a date",
        "bad_quantity": lambda: rows[SHEETS[0]][3][3] == "ten",
        "six_digit_customer": lambda: any(r[6] == 123456 for r in rows[SHEETS[0]]),
        "overlap_mismatch": lambda: Counter(r for r in rows[SHEETS[0]] if r[4].date() >= OVERLAP_START)
        != Counter(r for r in rows[SHEETS[1]] if r[4].date() <= OVERLAP_END),
        "two_customers_one_invoice": lambda: any(
            len({r[6] for r in rows[SHEETS[0]] if r[0] == invoice and r[6] is not None}) > 1 for invoice in {r[0] for r in rows[SHEETS[0]]}),
        "wrong_hash": lambda: sum(r[2] is not None and str(r[2]).endswith(" (changed)") for r in rows[SHEETS[1]]) == 1,
    }
    assert expected_shape[kind](), kind


def test_an_unknown_malformed_kind_or_signal_is_refused(tiny_zip, tmp_path):
    from tests.fixtures.make_fixture import make_malformed

    with pytest.raises(ValueError, match="unknown malformed kind"):
        make_malformed(tiny_zip, "nonsense", tmp_path / "x.zip")
    with pytest.raises(ValueError, match="unknown signal"):
        simulate_customers(10, 0, "nonsense")


def test_too_few_plain_rows_to_repeat_in_a_window_is_refused_with_the_window_and_both_sizes():
    """R3-fixture-repeat-rows-pool: the repeats are drawn without replacement, so a window with fewer plain rows than repeats is a clear
    error of the generator, not numpy's."""
    from datetime import datetime

    from tests.fixtures.make_fixture import _repeat_rows

    def row(day: date) -> dict:
        return {"labels": (), "Quantity": 1, "Price": 1.0, "InvoiceDate": datetime.combine(day, datetime.min.time())}

    rows = [row(date(2010, 1, d)) for d in range(1, 6)] + [row(date(2011, 2, d)) for d in range(1, 5)] + [row(date(2010, 12, 3))]
    with pytest.raises(ValueError, match=r"^the window 2010-12-01 to 2010-12-09 has 1 plain rows to repeat and 2 are needed$"):
        _repeat_rows(rows, np.random.default_rng(0))


# --- the hand cases agree with a brute-force reading of their rule ----------------------------------------------------


def test_the_cuts_hand_case_agrees_with_the_fixture_oracle():
    case = hand_cases.cuts_case()
    lines = []
    for order, row in enumerate(sorted([*case.purchases.to_dict("records"), *case.cancellations.to_dict("records")], key=lambda r: (r["invoice_ts"], r["quantity"] < 0, r["line_id"]))):
        lines.append({"order": order, "customer": int(row["customer_id"]), "code": row["stock_code"], "qty": int(row["quantity"]), "ts": row["invoice_ts"],
                      "invoice_date": row["invoice_date"].date(), "role": "cancellation" if row["quantity"] < 0 else "purchase"})
    n, m = timedelta(days=case.horizon_days), timedelta(days=case.active_days)
    for cut, population in case.population.items():
        before = net_purchase_days(lines, cut - timedelta(days=1))
        assert tuple(sorted(c for c, days in before.items() if any(cut - m <= d < cut for d in days))) == population, cut
        after = net_purchase_days(lines, cut + n - timedelta(days=1))
        assert {c: int(not any(cut <= d < cut + n for d in after.get(c, ()))) for c in population} == case.labels[cut], cut


def test_the_netting_hand_case_agrees_with_the_fixture_oracle():
    """A purchase day survives on a date exactly when one of its lines keeps units in the hand case's answer (last in, first out)."""
    case = hand_cases.netting_case()
    rows = sorted([*case.purchases.to_dict("records"), *case.cancellations.to_dict("records")], key=lambda r: (r["invoice_ts"], r["quantity"] < 0, r["line_id"]))
    lines = [{"order": order, "customer": int(r["customer_id"]), "code": r["stock_code"], "qty": int(r["quantity"]), "ts": r["invoice_ts"],
              "invoice_date": r["invoice_date"].date(), "role": "cancellation" if r["quantity"] < 0 else "purchase"} for order, r in enumerate(rows)]
    purchases = case.purchases.set_index("line_id")
    for as_of, net in case.net_quantity.items():
        expected: dict[int, set] = {}
        for line_id, quantity in net.items():
            if quantity > 0:
                expected.setdefault(int(purchases.loc[line_id, "customer_id"]), set()).add(purchases.loc[line_id, "invoice_date"].date())
        assert net_purchase_days(lines, as_of) == expected, as_of


def test_the_threshold_gain_and_metrics_hand_cases_agree_with_a_brute_force_reading():
    p, y = np.array(hand_cases.THRESHOLD_P), np.array(hand_cases.THRESHOLD_Y)
    grid = np.round(np.arange(1, 100) / 100, 2)
    benefit = [float(((p >= t) * (10 * y - 5)).sum()) for t in grid]
    best = max(benefit)
    threshold = max(t for t, b in zip(grid, benefit, strict=True) if b == best)
    expected = hand_cases.THRESHOLD_EXPECTED
    assert (threshold, best, int((p >= threshold).sum()), best / len(p) * 1000) == (expected["threshold"], expected["net_benefit"], expected["contacted"], expected["net_benefit_per_1000"])
    assert tuple(np.cumsum(y[np.argsort(-p, kind="stable")])) == hand_cases.GAIN_CAPTURED

    my, mp = np.array(hand_cases.METRICS_Y), np.array(hand_cases.METRICS_P)
    m = hand_cases.METRICS_EXPECTED
    assert math.isclose(roc_auc_score(my, mp), m["auc"]) and math.isclose(average_precision_score(my, mp), m["pr_auc"])
    assert math.isclose(np.mean((mp - my) ** 2), m["brier"]) and math.isclose(mp.mean() - my.mean(), m["bias"])
    bins = np.minimum((mp * 10 + 1e-9).astype(int), 9)
    ece = sum((bins == b).sum() / len(mp) * abs(mp[bins == b].mean() - my[bins == b].mean()) for b in np.unique(bins))
    assert math.isclose(ece, m["ece"])
    assert math.isclose(((mp >= 0.5) * (10 * my - 5)).sum(), m["net_benefit_at_0_5"])


def test_the_cell_writer_treats_pd_na_as_empty_and_refuses_illegal_xml_characters():
    """s2a R3-na-missing-value-coverage and R3-illegal-xml-char-coverage: the hand-written cell writer does what openpyxl did, an empty cell
    for every missing value (``pd.NA`` too) and ``IllegalCharacterError`` for a control character XML cannot hold."""
    import pandas as pd

    from tests.fixtures.make_fixture import _cell_xml

    assert _cell_xml("A1", pd.NA) == _cell_xml("A1", None) == _cell_xml("A1", float("nan")) == ""
    for bad in ("bell\x07", "\x00", "a\x1fb", "\x0b"):
        with pytest.raises(ValueError, match="ilegal"):
            _cell_xml("A1", bad)
    assert "<t>tab\tand new\nline</t>" in _cell_xml("A1", "tab\tand new\nline")
