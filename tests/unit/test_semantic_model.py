"""The measures, the what-if parameters and the pages of the Power BI report (U21, AC27; RF26; plan, section 20; D71): every DAX reference is a
column, a parameter or a measure of the model, the three cost parameters start at the sealed costs and move the panel's break-even as
``offer_cost / (rescue_rate x retained_value)`` says, the panel's contacts compare each customer's risk with that break-even inside the
slicers' filters, and the five pages place every visual inside the 12 x 9 grid with fields that exist.

No measure runs here (there is no Power BI in the project, as in project 03, D67): the panel's arithmetic is evaluated by a reader of the few
DAX functions it uses, written in this file."""

from __future__ import annotations

import dataclasses
import re

import pytest

from churnrisk.config import SealedConfig
from churnrisk.dashboard.semantic_model import (
    MEASURES,
    MODEL,
    PAGE_COLUMNS,
    PAGE_ROWS,
    PAGES,
    PARAMETERS,
    Measure,
    Page,
    SemanticModel,
    Visual,
    WhatIfParameter,
    dax_column_refs,
    dax_measure_refs,
    dax_parameter_refs,
    validate_model,
)
from churnrisk.threshold import Costs
from churnrisk.warehouse import SQL_DIR

SHA = "a" * 64
OFFER, RATE, VALUE = "Costo de la oferta", "Tasa de rescate", "Valor del cliente retenido"
PANEL = "Punto de equilibrio del panel"


def evaluate_scalar(name: str, selection: dict[str, float]) -> float:
    """The value of the scalar measure `name` with the parameters `selection` (a missing one takes its default): the measures it names are
    expanded, ``SELECTEDVALUE ( 'P'[P], d )`` reads the selection and ``DIVIDE ( a, b )`` divides. Anything else is an error."""
    text = MODEL.measure(name).dax

    def expand(match: re.Match) -> str:
        return f"({MODEL.measure(match.group(1)).dax})"

    for _ in range(10):
        text, changed = re.subn(r"(?<![\w\]'])\[([^\[\]]+)\]", expand, text)
        if not changed:
            break

    def selected(match: re.Match) -> str:
        table, column, default = match.group(1), match.group(2), match.group(3)
        assert table == column, "a what-if parameter's column has the parameter's name"
        return repr(selection.get(table, float(default)))

    text = re.sub(r"SELECTEDVALUE \( '([^']+)'\[([^\]]+)\], ([0-9.]+) \)", selected, text)
    while (start := text.find("DIVIDE (")) >= 0:          # DIVIDE ( a, b ): split at its own comma, whatever a and b hold
        depth, comma, end = 0, None, None
        for i in range(start + len("DIVIDE "), len(text)):
            depth += {"(": 1, ")": -1}.get(text[i], 0)
            if text[i] == "," and depth == 1:
                comma = i
            if depth == 0:
                end = i
                break
        numerator, denominator = text[start + len("DIVIDE ("):comma], text[comma + 1:end]
        text = f"{text[:start]}(({numerator}) / ({denominator})){text[end + 1:]}"
    assert re.fullmatch(r"[0-9.()+\-*/ eE]+", text), f"the panel uses only parameters, DIVIDE and arithmetic: {text}"
    return float(eval(text))  # noqa: S307 - digits and operators only, checked above


# --- the RED of U21 -------------------------------------------------------------------------------------------------------


def test_every_dax_reference_exists_and_the_cost_panel_moves_the_threshold(cfg):
    """AC27, RF26: each ``table[column]``, ``'Parameter'[Parameter]`` and ``[Measure]`` that a measure names exists; the parameters start at the
    sealed costs, so the panel's break-even starts at the sealed one, and each parameter moves it as the formula says; the panel's contacts
    and benefit compare the risk with that break-even, not with the sealed threshold, and keep the slicers' filters (KEEPFILTERS and FILTER
    over the fact, never ALL or REMOVEFILTERS)."""
    tables = {t.name: set(t.column_names) for t in MODEL.tables}
    parameters = {p.name_es for p in MODEL.parameters}
    measures = {m.name_es for m in MODEL.measures}
    for m in MODEL.measures:
        for table, column in dax_column_refs(m.dax):
            assert table in tables and column in tables[table], f"[{m.name_es}] names {table}[{column}]"
        for table, column in dax_parameter_refs(m.dax):
            assert table in parameters and column == table, f"[{m.name_es}] names '{table}'[{column}]"
        assert dax_measure_refs(m.dax) - {m.name_es} <= measures, f"[{m.name_es}] names {dax_measure_refs(m.dax) - measures}"
    costs = Costs.from_view(SealedConfig.of(cfg, SHA))
    defaults = {p.name_es: p.default for p in MODEL.parameters}
    assert (defaults[OFFER], defaults[RATE], defaults[VALUE]) == (costs.offer_cost, costs.rescue_rate, costs.retained_value)
    assert evaluate_scalar(PANEL, {}) == pytest.approx(costs.break_even()) == pytest.approx(0.5)
    for change, expected in (({OFFER: 7.0}, 7.0 / (0.2 * 50)), ({RATE: 0.4}, 5.0 / (0.4 * 50)), ({VALUE: 100.0}, 5.0 / (0.2 * 100)),
                             ({OFFER: 10.0, RATE: 0.25, VALUE: 80.0}, 10.0 / (0.25 * 80))):
        assert evaluate_scalar(PANEL, change) == pytest.approx(expected), change
    for name in ("Contactos con el panel", "Beneficio esperado con el panel (u.)"):
        dax = MODEL.measure(name).dax
        assert re.search(r"VAR t = \[Punto de equilibrio del panel\]", dax), name
        assert "fact_customer_cut[risk] >= t" in dax and "[Umbral sellado]" not in dax and "dim_model[threshold]" not in dax, name
        assert not re.search(r"\b(ALL|ALLEXCEPT|REMOVEFILTERS|ALLSELECTED)\b", dax), f"{name} keeps the slicers' filters"
    assert "KEEPFILTERS ( fact_customer_cut[risk] >= t )" in MODEL.measure("Contactos con el panel").dax
    assert "FILTER ( fact_customer_cut, fact_customer_cut[risk] >= t )" in MODEL.measure("Beneficio esperado con el panel (u.)").dax


# --- the measures of the plan -----------------------------------------------------------------------------------------------


def test_the_measures_of_the_plan_exist_each_with_a_format_and_a_description():
    expected = (
        "Costo de la oferta (u.)", "Tasa de rescate", "Valor del cliente retenido (u.)", PANEL, "Clientes puntuados", "Riesgo medio", "Bajas esperadas",
        "Contactos (umbral sellado)", "Contactos con el panel", "Beneficio esperado con el panel (u.)", "Ventanas cerradas", "Bajas observadas",
        "Tasa de bajas observada", "Volvieron a comprar", "Contactos que se fueron", "Contactos con ventana cerrada", "Precisión de los contactos",
        "Recall de los contactos", "Beneficio neto con los supuestos (u.)", "Clientes del corte (agregado)", "Contactos del corte (agregado)",
        "Volvieron (seguimiento)", "AUC del modelo (prueba)", "Captura en el 10 % (prueba)", "Umbral sellado", "Veredicto", "Última fecha de cálculo",
        "Reglas bloqueantes fallidas", "Líneas de invitados",
    )
    assert tuple(m.name_es for m in MEASURES) == expected
    for m in MEASURES:
        assert m.format_string and m.description_es and m.dax.count("(") == m.dax.count(")") and m.dax.count('"') % 2 == 0, m.name_es
    assert MODEL.measure("Contactos (umbral sellado)").dax == "CALCULATE ( COUNTROWS ( fact_customer_cut ), fact_customer_cut[is_contact] = TRUE () )"
    assert MODEL.measure("Tasa de bajas observada").dax == "DIVIDE ( [Bajas observadas], [Ventanas cerradas] )"


def test_the_sealed_test_figures_read_only_the_sealed_rows_of_the_model():
    """D71: the facts of the evaluation hold sealed and post-seal rows, so a card of the test reads the sealed rows of the model's own method;
    otherwise SELECTEDVALUE sees two values and the card is empty."""
    for name in ("AUC del modelo (prueba)", "Captura en el 10 % (prueba)"):
        dax = MODEL.measure(name).dax
        assert 'fact_method_metrics[scope] = "test"' in dax and 'fact_method_metrics[method_key] = "model"' in dax and 'fact_method_metrics[seal_state] = "sealed"' in dax, name
    assert 'fact_evaluation_summary[seal_state] = "sealed"' in MODEL.measure("Veredicto").dax


def test_the_text_a_measure_compares_a_column_with_is_a_value_that_column_takes():
    """A literal compared with a column (``"bloqueante"``, ``"falla"``, ``"ok"``, ``"test"``, ``"model"``, ``"sealed"``) is written by the SQL that
    builds that column or is one of its declared values."""
    declared = {("fact_method_metrics", "scope"): {"valid_v2", "test"}, ("fact_method_metrics", "seal_state"): {"sealed", "post_seal"},
                ("fact_evaluation_summary", "seal_state"): {"sealed", "post_seal"}, ("dim_pipeline_run", "status"): {"running", "ok", "failed", "rejected", "no_delivery"}}
    for m in MEASURES:
        for table, column, literal in re.findall(r"\b(\w+)\[(\w+)\] = \"([^\"]+)\"", m.dax):
            if (table, column) in declared:
                assert literal in declared[(table, column)], (m.name_es, table, column, literal)
            elif (table, column) == ("fact_validation", "rule_id"):
                from churnrisk.validate import RULES

                assert literal in RULES, (m.name_es, literal)
            elif (table, column) == ("fact_method_metrics", "method_key"):
                assert literal in {"model", "b0_all", "b1_recency", "b2_rfm", "b3_bgnbd", "b4_frequency", "b5_alive"}
            else:
                mart = next((SQL_DIR / "marts" / "powerbi").glob(f"mart_*_{table}.sql")).read_text(encoding="utf-8")
                assert f"'{literal}'" in mart, (m.name_es, table, column, literal)


# --- the what-if parameters ---------------------------------------------------------------------------------------------------


def test_the_three_cost_parameters_have_the_series_of_the_plan_and_say_they_are_assumptions(cfg):
    by_name = {p.name_es: p for p in PARAMETERS}
    assert list(by_name) == [OFFER, RATE, VALUE]
    assert [(p.start, p.end, p.step, p.default) for p in PARAMETERS] == [(1, 20, 0.5, 5), (0.05, 0.5, 0.05, 0.2), (10, 200, 5, 50)]
    assert by_name[OFFER].generateseries() == "GENERATESERIES(1, 20, 0.5)" and len(by_name[RATE].values()) == 10
    for p in PARAMETERS:
        assert "supuesto" in p.description_es and p.default in p.values(), p.name_es


# --- the pages ----------------------------------------------------------------------------------------------------------------


def test_there_are_five_pages_in_the_order_of_the_plan_inside_the_grid_without_overlaps():
    assert [p.name_es for p in PAGES] == ["Clientes en riesgo y sus motivos", "Ganancia y costos", "Seguimiento", "Validación del modelo", "Calidad y corridas"]
    assert (PAGE_COLUMNS, PAGE_ROWS) == (12, 9)
    for page in PAGES:
        cells = set()
        for v in page.visuals:
            assert 0 <= v.x and 0 <= v.y and v.x + v.w <= 12 and v.y + v.h <= 9 and v.w >= 1 and v.h >= 1, (page.name_es, v.title_es)
            mine = {(x, y) for x in range(v.x, v.x + v.w) for y in range(v.y, v.y + v.h)}
            assert not mine & cells, (page.name_es, v.title_es)
            cells |= mine
    assert validate_model(MODEL) == []


def visual(page: str, title: str) -> Visual:
    return next(v for v in next(p for p in PAGES if p.name_es == page).visuals if v.title_es == title)


def test_each_page_has_the_visuals_of_the_plan():
    first = "Clientes en riesgo y sus motivos"
    assert [v.fields for v in PAGES[0].visuals if v.kind == "slicer"] == [("dim_cut[cut_date]",), ("dim_country[country_es]",), ("dim_risk_band[band_es]",)]
    assert [v.fields[0] for v in PAGES[0].visuals if v.kind == "card"] == ["[Clientes puntuados]", "[Contactos (umbral sellado)]", "[Riesgo medio]", "[Bajas esperadas]"]
    table = visual(first, "Clientes por riesgo, con sus tres motivos")
    assert table.kind == "table" and table.fields[0] == "fact_customer_cut[customer_id]" and "fact_customer_cut[risk]" in table.fields
    assert visual(first, "Motivos entre los contactados").fields == ("dim_reason[feature_es]", "fact_reason_summary[contacted_top3]")
    costs = "Ganancia y costos"
    assert [v.fields[0] for v in PAGES[1].visuals if v.kind == "slicer"] == [f"'{OFFER}'[{OFFER}]", f"'{RATE}'[{RATE}]", f"'{VALUE}'[{VALUE}]"]
    assert all("supuesto" in v.title_es for v in PAGES[1].visuals if v.kind == "slicer")
    assert [v.fields[0] for v in PAGES[1].visuals if v.kind == "card"] == [f"[{PANEL}]", "[Contactos con el panel]", "[Beneficio esperado con el panel (u.)]"]
    assert visual(costs, "Curva de ganancia en la prueba").fields == ("fact_gain_curve[share_contacted]", "fact_gain_curve[share_captured]", "dim_method[method_es]")
    assert "fact_tracking[is_censored]" in visual("Seguimiento", "Seguimiento de cada corte por fecha de cálculo").fields
    titles = {v.title_es for v in PAGES[3].visuals}
    assert {"Criterios C01-C10", "AUC por método", "Calibración", "Sensibilidades de N, M y diciembre", "Tasa de bajas por N y M",
            "Silencios que vuelven", "Importancia media |SHAP|", "Demostración de la fuga"} <= titles
    quality = [v.fields[0] for v in PAGES[4].visuals if v.kind == "card"]
    assert quality == ["[Última fecha de cálculo]", "dim_pipeline_run[status]", "[Reglas bloqueantes fallidas]", "[Líneas de invitados]"]
    assert visual("Calidad y corridas", "Reglas de validación").fields[:2] == ("fact_validation[rule_id]", "fact_validation[name_es]")


def test_only_the_list_of_the_first_page_shows_the_customer_column():
    """D26: the customer number is a column of the private fact only, and the one visual that shows it is the list, which the HTML masks (U22)."""
    showing = [(p.name_es, v.title_es) for p in PAGES for v in p.visuals for f in v.fields if "customer_id" in f]
    assert showing == [("Clientes en riesgo y sus motivos", "Clientes por riesgo, con sus tres motivos")]


# --- the model check refuses every way a measure, a parameter or a page can be wrong ----------------------------------------------


def with_(**changes) -> SemanticModel:
    return dataclasses.replace(MODEL, **changes)


@pytest.mark.parametrize(("model", "message"), [
    (lambda: with_(measures=(*MEASURES, Measure("Roto", "SUM ( fact_customer_cut[nope] )", "0", "x"))), r"\[Roto\]: fact_customer_cut\[nope\] no existe"),
    (lambda: with_(measures=(*MEASURES, Measure("Roto", "[No hay tal]", "0", "x"))), r"\[Roto\]: la medida \[No hay tal\] no existe"),
    (lambda: with_(measures=(*MEASURES, Measure("Roto", "SELECTEDVALUE ( 'Otro'[Otro], 1 )", "0", "x"))), r"\[Roto\]: el parámetro 'Otro'\[Otro\] no existe"),
    (lambda: with_(measures=(*MEASURES, Measure("Roto", "SUM ( fact_customer_cut[risk]", "0", "x"))), r"\[Roto\]: paréntesis o comillas"),
    (lambda: with_(measures=(*MEASURES, Measure("Roto", "1", "", ""))), r"\[Roto\]: necesita un formato y una descripción"),
    (lambda: with_(measures=(*MEASURES, MEASURES[0])), r"la medida \[Costo de la oferta \(u.\)\] está repetida"),
    (lambda: with_(parameters=(*PARAMETERS[:2], dataclasses.replace(PARAMETERS[2], default=52.5))), r"el parámetro Valor del cliente retenido: el valor por defecto 52.5"),
    (lambda: with_(pages=(Page("P", (Visual("card", "a", ("[No hay tal]",), 0, 0, 2, 1),)),)), r"P: a: la medida \[No hay tal\] no existe"),
    (lambda: with_(pages=(Page("P", (Visual("card", "a", ("dim_cut[nope]",), 0, 0, 2, 1),)),)), r"P: a: la columna dim_cut\[nope\] no existe"),
    (lambda: with_(pages=(Page("P", (Visual("card", "a", ("[Riesgo medio]",), 11, 0, 2, 1),)),)), r"P: a: sale de la grilla de 12 x 9"),
    (lambda: with_(pages=(Page("P", (Visual("card", "a", ("[Riesgo medio]",), 0, 0, 2, 2), Visual("card", "b", ("[Riesgo medio]",), 1, 1, 2, 1))),)), r"P: b: se superpone con a"),
])
def test_the_model_check_names_every_way_a_measure_a_parameter_or_a_page_can_be_wrong(model, message):
    problems = validate_model(model())
    assert any(re.search(message, p) for p in problems), problems


def test_the_parameter_values_are_the_series_without_floating_point_drift():
    p = WhatIfParameter("Tasa de rescate", 0.05, 0.5, 0.05, 0.2, "x supuesto")
    assert p.values() == (0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5)
