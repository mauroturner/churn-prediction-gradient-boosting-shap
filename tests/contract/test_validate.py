"""The validation (U08, AC07; RF08, D23): the rules of the source, of the delivery and of the lines, the interface of the model's rules, and
how each rule aggregates over runs. Until the warehouse exists (U09), what a delivery is validated against is written by ``load_known``,
which fills the two tables the validation reads (``deliveries`` and ``raw_lines``) with the columns the plan gives them (section 5)."""

from __future__ import annotations

import json
import re
import sqlite3
import zipfile
from pathlib import Path

import pandas as pd
import pytest

from churnrisk.deliveries import delivery_plan, delivery_rows, publish
from churnrisk.ingest import extract_member, read_source
from churnrisk.schema import CANONICAL_SCHEMA, IDENTIFIER_COLUMNS, SourceError
from churnrisk.validate import (
    RULES,
    Aggregation,
    Severity,
    ValidationReport,
    add_results,
    combine_reports,
    model_result,
    read_report,
    validate_delivery,
    validate_source,
    write_report,
)
from tests.fixtures.make_fixture import MEMBER

PLAN_MD = Path(__file__).resolve().parents[2] / "docs" / "plan.md"
SEVERITY_ES = {"bloqueante": Severity.BLOCKING, "advertencia": Severity.WARNING, "informativa": Severity.INFO}
SCOPE_ES = {"fuente": "source", "entrega": "delivery", "líneas": "lines", "modelo": "model"}
SOURCE_KINDS = {
    "wrong_hash": "V01", "oversize": "V02", "extra_member": "V03", "member_with_path": "V03", "inflated_member": "V03", "missing_sheet": "V04",
    "renamed_sheet": "V04", "extra_column": "V04", "missing_column": "V04", "renamed_column": "V04", "bad_date": "V05", "bad_quantity": "V05",
    "six_digit_customer": "V05", "overlap_mismatch": "V06",
}
COLUMNS = ("line_id", "invoice", "stock_code", "quantity", "price", "customer_id", "country", "invoice_ts", "invoice_date", "code_kind")


def load_known(conn: sqlite3.Connection, rows: pd.DataFrame, delivery_id: str) -> None:
    """Record a delivery as loaded, with its lines, in the two tables the validation reads (U09 replaces this with the warehouse)."""
    conn.execute("CREATE TABLE IF NOT EXISTS deliveries (delivery_id TEXT PRIMARY KEY, status TEXT)")
    conn.execute(f"CREATE TABLE IF NOT EXISTS raw_lines ({', '.join(COLUMNS)})")
    conn.execute("INSERT INTO deliveries VALUES (?, 'loaded')", (delivery_id,))
    values = rows.assign(invoice_ts=rows["invoice_ts"].dt.strftime("%Y-%m-%d %H:%M:%S"), invoice_date=rows["invoice_date"].dt.strftime("%Y-%m-%d"),
                         customer_id=rows["customer_id"].astype(object).where(rows["customer_id"].notna(), None))
    conn.executemany(f"INSERT INTO raw_lines VALUES ({', '.join('?' for _ in COLUMNS)})", values[list(COLUMNS)].itertuples(index=False))


def validate_all(cfg, frame: pd.DataFrame, folder: Path) -> list[ValidationReport]:
    """Publish and validate every delivery of the plan in order, each against the ones before it, as the monthly runs will."""
    conn = sqlite3.connect(":memory:")
    reports = []
    for spec in delivery_plan(cfg):
        entry = publish(spec, frame, folder)
        rows = delivery_rows(spec, frame)
        reports.append(validate_delivery(rows, spec, conn, cfg, entry=entry, delivery_path=folder / entry.file, run_key=f"r{len(reports) + 1}"))
        load_known(conn, rows, spec.delivery_id)
    conn.close()
    return reports


@pytest.fixture(scope="module")
def fixture_reports(cfg, canonical, tmp_path_factory):
    frame, _report = canonical
    return validate_all(cfg, frame, tmp_path_factory.mktemp("validate") / "deliveries")


def by_rule(report: ValidationReport) -> dict:
    return {r.rule_id: r for r in report.results}


# --- the RED of U08 ---------------------------------------------------------------------------------------------------


def test_every_rule_declares_how_it_aggregates_over_runs():
    """D23 and project 03's D94: each rule carries its severity, its scope and how it is published over runs (``source`` once, ``per_run``
    summed over the loaded runs, ``latest`` read once from the last one), exactly as the table of the plan, section 6, says."""
    section = PLAN_MD.read_text(encoding="utf-8").split("## 6. ", 1)[1].split("\n## ", 1)[0]
    table = {}
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 5 and re.fullmatch(r"[VMI]\d\d", cells[0]):
            table[cells[0]] = (SEVERITY_ES[cells[1]], SCOPE_ES[cells[2]], Aggregation(cells[3]))
    assert len(table) == 39
    assert {rule_id: (rule.severity, rule.scope, rule.aggregation) for rule_id, rule in RULES.items()} == table
    assert list(RULES) == list(table), "the report lists the rules in the order of the table"
    assert all(rule.name_es.strip() for rule in RULES.values())


def test_warning_and_info_counts_match_fixture_truth(fixture_reports, fixture_truth, canonical):
    """The valid fixture, delivered and validated month by month: no blocking rule fails, every result carries the aggregation of its rule,
    and the warnings and the informative rules, aggregated as their rule says, are the counts of the fixture's truth."""
    _frame, source_report = canonical
    assert [r.blocking_failed for r in fixture_reports] == [False] * 6
    for report in fixture_reports:
        assert all(r.aggregation is RULES[r.rule_id].aggregation and r.scope == RULES[r.rule_id].scope for r in report.results)
        assert report.not_evaluated == () and [r.rule_id for r in report.results] == [rule for rule in RULES if RULES[rule].scope in ("delivery", "lines")]

    def total(rule_id: str, field: str = "rows_affected") -> float:
        rule = RULES[rule_id]
        values = [getattr(by_rule(report)[rule_id], field) for report in fixture_reports]
        return values[-1] if rule.aggregation is Aggregation.LATEST else sum(values)

    truth = fixture_truth
    roles = truth.roles
    expected = {
        "V20": roles["no_customer"], "V21": roles["cancellation"], "V23": roles["non_positive_quantity"], "V24": roles["non_positive_price"],
        "V25": roles["service_code"], "V26": roles["gift_voucher"], "V27": roles["adjustment_invoice"], "V28": truth.repeated_lines,
        "V29": truth.large_quantity_lines, "V31": truth.unspecified_country_lines, "V22": truth.unmatched_cancellations_at_end,
        "I02": truth.guest_lines,
    }
    assert {rule_id: total(rule_id) for rule_id in expected} == expected
    # the fixture's gift voucher has no customer, as in the real file (D51): V20 sets it aside first and V26 counts none
    assert expected["V26"] == 0 and all(value > 0 for rule_id, value in expected.items() if rule_id != "V26"), "every other rule is exercised"
    assert total("V30", "customers_affected") == truth.multi_country_customers == 1
    assert total("I01", "customers_affected") == truth.customers
    assert total("I02", "value_gbp") == pytest.approx(truth.guest_positive_value, abs=0.05)
    source = validate_source(source_report, run_key="r0", source_sha256="0" * 64)
    assert by_rule(source)["I03"].rows_affected == truth.overlap_rows > 0 and not source.blocking_failed
    warned = {r.rule_id for report in fixture_reports for r in report.results if r.status == "warn"}
    assert warned == {rule_id for rule_id, rule in RULES.items() if rule.severity is Severity.WARNING and rule.scope == "lines"} - {"V26"}


# --- the rules of the source --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", sorted(SOURCE_KINDS))
def test_each_malformed_source_fails_its_rule_and_leaves_the_later_ones_not_evaluated(rejection, kind):
    error = rejection(kind)
    report = validate_source(error, run_key="r1", source_sha256="")
    failing = [r.rule_id for r in report.results if not r.passed]
    assert failing == [SOURCE_KINDS[kind]] and report.blocking_failed
    order = list(RULES)
    assert [r.rule_id for r in report.results if r.passed] == [rule for rule in order[: order.index(failing[0])] if RULES[rule].severity is Severity.BLOCKING]
    assert set(report.not_evaluated) == set(order) - {r.rule_id for r in report.results}
    shown = json.dumps([r.examples for r in report.results], ensure_ascii=False)
    assert "kept" not in shown and '"zip"' not in shown, "no path of this machine in an example"


def test_a_clean_read_passes_the_source_rules_and_counts_the_overlap_copies(canonical):
    _frame, source_report = canonical
    report = validate_source(source_report, run_key="r1", source_sha256="a" * 64)
    assert [r.rule_id for r in report.results] == ["V01", "V02", "V03", "V04", "V05", "V06", "I03"] and report.not_evaluated == ()
    i03 = by_rule(report)["I03"]
    assert (i03.rows_affected, i03.value_gbp, i03.aggregation) == (source_report.overlap_rows, source_report.overlap_value_gbp, Aggregation.SOURCE)
    with pytest.raises(ValueError, match="no es una regla bloqueante de la fuente"):
        validate_source(SourceError("V20", "x"), run_key="r1")


# --- the rules of the delivery ------------------------------------------------------------------------------------------


def test_a_second_customer_on_an_invoice_is_v13_and_its_example_never_shows_a_number(cfg, malformed, tmp_path, fixture_truth):
    xlsx = extract_member(malformed("two_customers_one_invoice"), MEMBER, cfg.source.max_member_bytes, "", out_dir=tmp_path / "x")
    frame, _report = read_source(xlsx, cfg)
    spec = delivery_plan(cfg)[0]
    entry = publish(spec, frame, tmp_path / "deliveries")
    conn = sqlite3.connect(":memory:")
    report = validate_delivery(delivery_rows(spec, frame), spec, conn, cfg, entry=entry, delivery_path=tmp_path / "deliveries" / entry.file, run_key="r1")
    assert [r.rule_id for r in report.results if r.severity is Severity.BLOCKING and not r.passed] == ["V13"]
    v13 = by_rule(report)["V13"]
    assert v13.rows_affected >= 2 and v13.customers_affected == 2 and v13.status == "fail"
    assert all(set(example) == {"line_id", "lines", "customers", "countries"} for example in v13.examples)
    assert_no_identifier(report, frame)


def assert_no_identifier(report: ValidationReport, frame: pd.DataFrame) -> None:
    """No example names a customer or an invoice (D26): no identifier key, and no customer or invoice number among its values."""
    numbers = set(frame["customer_id"].dropna().astype(int)) | {int(i) for i in frame["invoice"].str.lstrip("CA") if i.isdigit()}
    for result in report.results:
        for example in result.examples:
            assert not set(example) & {*IDENTIFIER_COLUMNS, "customer", "customers_ids", "invoices"}, (result.rule_id, example)
            values = [v for v in json.loads(json.dumps(example)).values() if isinstance(v, int) and not isinstance(v, bool)]
            assert not set(values) & numbers - {example.get("line_id")}, (result.rule_id, example)


def test_no_example_of_the_fixture_reports_names_a_customer_or_an_invoice(fixture_reports, canonical):
    frame, _report = canonical
    for report in fixture_reports:
        assert_no_identifier(report, frame)


def small_delivery(**changes) -> pd.DataFrame:
    frame = pd.DataFrame({
        "line_id": [10_000_001, 10_000_002, 10_000_003], "sheet": 1, "source_row": [1, 2, 3], "invoice": ["500001", "500001", "500002"],
        "stock_code": ["85123A", "22423", "85123A"], "description": "X", "quantity": [2, 3, 1],
        "invoice_ts": pd.to_datetime(["2011-08-03 10:00", "2011-08-03 10:00", "2011-08-04 11:00"]), "price": [2.5, 4.0, 2.5],
        "customer_id": pd.array([90001, 90001, 90002], dtype="Int64"), "country": "United Kingdom", "code_kind": "product", "is_repeated_line": False,
    })
    for column, values in changes.items():
        frame[column] = values
    frame["invoice_date"] = frame.groupby("invoice")["invoice_ts"].transform("min").dt.normalize()
    return frame[CANONICAL_SCHEMA.names]


def run_delivery(cfg, tmp_path, rows, *, loaded=(), conn=None, spec_index=1, entry_rows=None, tamper=False):
    spec = delivery_plan(cfg)[spec_index]
    conn = conn or sqlite3.connect(":memory:")
    for delivery_id, known in loaded:
        load_known(conn, known, delivery_id)
    out = tmp_path / "deliveries"
    entry = publish(spec, rows, out)
    if entry_rows is not None:
        entry = type(entry)(**{**entry.__dict__, "rows": entry_rows})
    if tamper:
        (out / entry.file).write_bytes((out / entry.file).read_bytes() + b"\0")
    return by_rule(validate_delivery(delivery_rows(spec, rows), spec, conn, cfg, entry=entry, delivery_path=out / entry.file, run_key="r9"))


def test_the_delivery_must_be_the_next_one_of_the_plan(cfg, tmp_path):
    rows = small_delivery()
    assert not run_delivery(cfg, tmp_path / "a", rows)["V10"].passed, "the launch is not loaded"
    launch = small_delivery(invoice_ts=pd.to_datetime(["2011-07-03 10:00"] * 2 + ["2011-07-04 11:00"]), line_id=[1, 2, 3])
    ok = run_delivery(cfg, tmp_path / "b", rows, loaded=[("L2011-07", launch)])
    assert ok["V10"].passed and ok["V11"].passed and ok["V12"].passed and ok["V13"].passed and ok["V14"].passed
    again = run_delivery(cfg, tmp_path / "c", rows, loaded=[("L2011-07", launch), ("M2011-08", rows.iloc[:0])])
    assert not again["V10"].passed and again["V10"].examples[0]["reason"] == "already_loaded"


def test_lines_outside_the_period_already_loaded_or_repeated_and_a_delivery_unlike_its_manifest_are_blocking(cfg, tmp_path):
    launch = small_delivery(invoice_ts=pd.to_datetime(["2011-07-03 10:00"] * 2 + ["2011-07-04 11:00"]), line_id=[1, 2, 3])
    rows = small_delivery(line_id=[1, 10_000_002, 10_000_002])
    result = run_delivery(cfg, tmp_path / "a", rows, loaded=[("L2011-07", launch)])
    assert (result["V12"].passed, result["V12"].rows_affected) == (False, 2), "one already loaded, and the second copy of a repeated id"
    assert [e["reason"] for e in result["V12"].examples] == ["loaded", "repeated"]
    outside = small_delivery(invoice_ts=pd.to_datetime(["2011-09-01 00:00", "2011-09-01 00:10", "2011-08-04 11:00"]))   # the day after the period
    spec = delivery_plan(cfg)[1]
    conn = sqlite3.connect(":memory:")
    load_known(conn, launch, "L2011-07")
    out = tmp_path / "b"
    entry = publish(spec, outside, out)
    report = by_rule(validate_delivery(outside, spec, conn, cfg, entry=entry, delivery_path=out / entry.file, run_key="r9"))
    assert (report["V11"].passed, report["V11"].rows_affected) == (False, 2) and not report["V14"].passed, "the manifest has 1 row"
    assert not run_delivery(cfg, tmp_path / "c", small_delivery(), loaded=[("L2011-07", launch)], tamper=True)["V14"].passed
    mismatch = run_delivery(cfg, tmp_path / "d", small_delivery(), loaded=[("L2011-07", launch)], entry_rows=4)["V14"]
    assert not mismatch.passed and mismatch.examples[0]["reasons"] == ["rows_differ_from_manifest"]


def test_an_invoice_with_two_customers_or_countries_also_against_what_is_loaded_is_blocking(cfg, tmp_path):
    launch = small_delivery(invoice_ts=pd.to_datetime(["2011-07-03 10:00"] * 2 + ["2011-07-04 11:00"]), line_id=[1, 2, 3], invoice=["500001", "500001", "400002"],
                            customer_id=pd.array([90003, 90003, 90002], dtype="Int64"))
    guest = small_delivery(invoice=["600001", "600001", "600002"], customer_id=pd.array([90001, None, 90002], dtype="Int64"))
    assert not run_delivery(cfg, tmp_path / "a", guest, loaded=[("L2011-07", launch)])["V13"].passed, "a guest line next to a customer is two customers"
    clean = small_delivery(invoice=["600001", "600001", "600002"])
    assert run_delivery(cfg, tmp_path / "b", clean, loaded=[("L2011-07", launch)])["V13"].passed
    against = run_delivery(cfg, tmp_path / "c", small_delivery(), loaded=[("L2011-07", launch)])["V13"]
    assert not against.passed and against.examples[0]["customers"] == 2 and against.examples[0]["countries"] == 1 and against.rows_affected == 2
    assert against.customers_affected == 1, "the customer of this delivery's lines; the loaded one is only counted in the example"
    country = small_delivery(invoice=["600001", "600001", "600002"], country=["United Kingdom", "France", "EIRE"])
    assert not run_delivery(cfg, tmp_path / "d", country, loaded=[("L2011-07", launch)])["V13"].passed


def test_a_customer_with_a_second_country_is_counted_once_in_the_delivery_where_it_shows_up(cfg, tmp_path):
    """V30 aggregates per run, so a customer is counted in the delivery that shows its second country and not again in the later ones (the
    lesson of project 02's V21 and project 03's D94: a cumulative count summed over runs counts the same customer many times)."""
    launch = small_delivery(invoice_ts=pd.to_datetime(["2011-07-03 10:00"] * 2 + ["2011-07-04 11:00"]), line_id=[1, 2, 3], invoice=["400001", "400001", "400002"])
    august = small_delivery(invoice=["500001", "500001", "500002"], country=["Germany", "Germany", "United Kingdom"])
    first = run_delivery(cfg, tmp_path / "a", august, loaded=[("L2011-07", launch)])["V30"]
    assert (first.passed, first.customers_affected, first.rows_affected, first.examples) == (False, 1, 2, [{"line_id": 10_000_001, "countries": 2}])
    september = small_delivery(invoice=["600001", "600001", "600002"], line_id=[20_000_001, 20_000_002, 20_000_003],
                               invoice_ts=pd.to_datetime(["2011-09-03 10:00"] * 2 + ["2011-09-04 11:00"]))
    later = run_delivery(cfg, tmp_path / "b", september, loaded=[("L2011-07", launch), ("M2011-08", august)], spec_index=2)["V30"]
    assert later.passed and later.customers_affected == 0, "already counted in M2011-08"


# --- the model's rules and the report files -------------------------------------------------------------------------------


def test_the_model_rules_are_added_by_their_tasks_in_the_order_of_the_rules(fixture_reports):
    report = fixture_reports[0]
    m01 = model_result("M01", passed=False, rows=0, examples=[{"auc_v1": 0.97, "tripwire": 0.95}])
    i04 = model_result("I04", passed=True, rows=1200, customers=1200)
    combined = add_results(report, [i04, m01])
    ids = [r.rule_id for r in combined.results]
    assert ids.index("M01") < ids.index("I01") and ids.index("V31") < ids.index("M01") and ids[-1] == "I04"
    assert combined.blocking_failed and (m01.aggregation, i04.aggregation) == (Aggregation.LATEST, Aggregation.PER_RUN) and i04.status == "pass"
    with pytest.raises(ValueError, match="no es una regla del modelo"):
        model_result("V20", passed=True)
    with pytest.raises(ValueError, match="ya está"):
        add_results(combined, [m01])


def test_the_report_files_are_written_with_a_copy_per_run_and_read_back(fixture_reports, canonical, tmp_path):
    _frame, source_report = canonical
    report = combine_reports(validate_source(source_report, run_key="r1", source_sha256="b" * 64), fixture_reports[0])
    assert [r.rule_id for r in report.results][:7] == ["V01", "V02", "V03", "V04", "V05", "V06", "V10"] and report.source_sha256 == "b" * 64
    latest_json, latest_md = write_report(report, tmp_path / "validation")
    assert (tmp_path / "validation" / "history" / "r1.json").read_bytes() == latest_json.read_bytes()
    assert read_report(tmp_path / "validation" / "history" / "r1.json") == report
    document = json.loads(latest_json.read_text(encoding="utf-8"))
    assert {"rule_id", "name_es", "severity", "scope", "aggregation", "status", "rows_affected", "customers_affected", "value_gbp", "examples"} == set(document["results"][0])
    text = latest_md.read_text(encoding="utf-8")
    assert "Aceptado: ninguna regla bloqueante falla." in text and "| V20 |" in text and "advierte" in text
    with pytest.raises(ValueError, match="no sirve como nombre de archivo"):
        write_report(ValidationReport("../x", "", None, 0, []), tmp_path / "validation")
