"""The HTML design of the Power BI report, generated from the semantic model and the exported Parquet (RF26, AC28; plan, section 20; D72).
Adapted from project 03's ``dashboard/render.py`` (it is not imported from it).

One self-contained page (inline CSS, inline SVG, no scripts, no fonts or images from the network) with the steps to build the report in Power
BI Desktop, the diagram of the model, the relationships, the Power Query code of each table, the three what-if parameters of the costs, the
DAX measures and the five pages placed on a 12 x 9 grid, each visual with a preview drawn from the exported tables. Nothing here is typed by
hand twice: change ``semantic_model.py`` and render again.

Three rules for what a preview shows (D26). Every text that comes from the data goes through ``html.escape``. An aggregate cell with fewer
customers than ``min_cell_customers`` shows a dash (the versioned facts already carry those cells empty, and the previews that group the
private fact hide them too). And the list of page 1, the one visual that shows a customer column, masks every customer number with as many
«•» as it has digits: the HTML never receives a customer number.
"""

from __future__ import annotations

import logging
from html import escape
from pathlib import Path

import pandas as pd

from churnrisk.dashboard import svg
from churnrisk.dashboard.semantic_model import (
    FEATURES_ES,
    PAGE_COLUMNS,
    PAGE_ROWS,
    Page,
    SemanticModel,
    Visual,
    dax_measure_refs,
    validate_model,
)
from churnrisk.export import ExportMeta
from churnrisk.files import write_atomic

logger = logging.getLogger(__name__)

MIN_CELL_CUSTOMERS = 10      # the default of [site] min_cell_customers; the task passes the configured value
PAGE_WIDTH_PX, PAGE_HEIGHT_PX = 1280, 720
CELL_W, CELL_H = PAGE_WIDTH_PX / PAGE_COLUMNS, PAGE_HEIGHT_PX / PAGE_ROWS
HEADER_PX = 26
LIST_ROWS = 14               # rows of the masked list on page 1
MASK = "•"
TITLE = "Diseño del tablero de Power BI: clientes que están por irse, antes de que se vayan"
SECTIONS = (
    ("armado", "Cómo armarlo en Power BI Desktop"),
    ("modelo", "El modelo en estrella"),
    ("relaciones", "Relaciones"),
    ("consultas", "Power Query: una consulta por tabla"),
    ("parametros", "Parámetros de los costos (supuestos)"),
    ("medidas", "Medidas DAX"),
    ("paginas", "Las cinco páginas"),
    ("fuente", "Fuente y licencia"),
)
KIND_ES = {"slicer": "Segmentador", "card": "Tarjeta", "lineChart": "Gráfico de líneas", "barChart": "Gráfico de barras", "matrix": "Matriz", "table": "Tabla"}
HIDDEN = "—"
CSS = """
:root{color-scheme:light;--surface:#fcfcfb;--panel:#f3f2ef;--text:#0b0b0b;--text-2:#52514e;--muted:#6f6e69;--line:#d9d8d3;--accent:#256abf;
--series-1:#2a78d6;--series-2:#eb6834;--series-3:#1baf7a;--series-4:#eda100;--series-5:#e87ba4;--series-6:#008300;--series-7:#6250d6;--series-8:#e34948}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])){color-scheme:dark;--surface:#1a1a19;--panel:#242422;--text:#f0efec;--text-2:#c3c2b7;--muted:#a3a299;--line:#3a3a37;--accent:#6da7ec;
--series-1:#3987e5;--series-2:#d95926;--series-3:#199e70;--series-4:#c98500;--series-5:#d55181;--series-6:#008300;--series-7:#9085e9;--series-8:#e66767}}
:root[data-theme="dark"]{color-scheme:dark;--surface:#1a1a19;--panel:#242422;--text:#f0efec;--text-2:#c3c2b7;--muted:#a3a299;--line:#3a3a37;--accent:#6da7ec;
--series-1:#3987e5;--series-2:#d95926;--series-3:#199e70;--series-4:#c98500;--series-5:#d55181;--series-6:#008300;--series-7:#9085e9;--series-8:#e66767}
*{box-sizing:border-box}
body{margin:0;background:var(--surface);color:var(--text);font:16px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1180px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:1.6rem;line-height:1.25;margin:0 0 4px}h2{font-size:1.3rem;margin:48px 0 8px;padding-top:8px;border-top:1px solid var(--line)}
h3{font-size:1.05rem;margin:28px 0 8px}p,li{max-width:78ch}a{color:var(--accent)}
.lead{color:var(--text-2);margin:0 0 16px}.meta{display:flex;flex-wrap:wrap;gap:8px 24px;color:var(--text-2);font-size:.9rem;margin:12px 0}
nav ul{display:flex;flex-wrap:wrap;gap:4px 16px;padding:0;list-style:none;margin:16px 0}
code,pre{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:.85rem}
pre{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:10px 12px;overflow-x:auto;margin:6px 0;white-space:pre}
table{border-collapse:collapse;width:100%;font-size:.88rem}th,td{border-bottom:1px solid var(--line);padding:5px 8px;text-align:left;vertical-align:top}
th{color:var(--text-2);font-weight:600;background:var(--surface)}td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
.scroll{overflow-x:auto}.warn{border-left:3px solid var(--series-4);padding:4px 12px;background:var(--panel);margin:12px 0}
.model-svg{width:100%;height:auto;display:block}.model-svg .box{fill:var(--panel);stroke:var(--line)}.model-svg .dim{stroke:var(--series-1)}
.model-svg .fact{stroke:var(--series-2)}.model-svg text{fill:var(--text);font-size:12px}.model-svg .small{fill:var(--text-2);font-size:10px}
.model-svg .rel{stroke:var(--muted);stroke-width:1;fill:none;opacity:.55}.model-svg .card{font-weight:700;fill:var(--accent)}
.canvas-wrap{overflow-x:auto;border:1px solid var(--line);border-radius:8px;background:var(--panel);padding:8px}
.canvas{display:grid;grid-template-columns:repeat(12,1fr);grid-template-rows:repeat(9,1fr);gap:6px;aspect-ratio:16/9;min-width:960px;max-width:1280px}
.visual{background:var(--surface);border:1px solid var(--line);border-radius:6px;overflow:hidden;display:flex;flex-direction:column;min-width:0;min-height:0}
.visual header{display:flex;justify-content:space-between;gap:6px;padding:2px 8px;font-size:.75rem;color:var(--text-2);height:26px;align-items:center}
.visual header b{color:var(--text);font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.visual header span{white-space:nowrap;color:var(--muted)}
.visual .body{flex:1;min-height:0;padding:0 8px 3px;overflow:hidden;font-size:.75rem}.visual .body svg{max-width:100%;height:auto;display:block}
.big{font-size:1.2rem;font-weight:700;line-height:1.15;font-variant-numeric:tabular-nums;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.sub{color:var(--muted);font-size:.65rem;line-height:1.1}
.chips{display:flex;flex-wrap:nowrap;gap:3px;overflow:hidden}.chip{white-space:nowrap;border:1px solid var(--line);border-radius:10px;padding:0 6px;font-size:.7rem;color:var(--text-2)}
.visual table{font-size:.7rem}.visual th,.visual td{padding:1px 5px}.rows p{margin:1px 0;font-size:.75rem}
.masked{letter-spacing:.05em;color:var(--muted)}
svg .svg-grid{stroke:var(--line);stroke-width:1}svg .svg-axis{stroke:var(--muted);stroke-width:1}svg .svg-reference{stroke:var(--text-2);stroke-width:1;stroke-dasharray:2 3}
svg .svg-tick,svg .svg-legend,svg .svg-note,svg .svg-value{fill:var(--text-2);font-size:10px}svg .svg-value{fill:var(--text)}svg .svg-on-fill{fill:var(--text);font-size:10px}
svg .svg-hit{fill:transparent}svg .svg-hit:hover{fill:var(--text);fill-opacity:.15}
.placement td:first-child{white-space:nowrap}
@media print{.canvas-wrap{break-inside:avoid}body{font-size:12px}}
"""


# --- data ---------------------------------------------------------------------------------------------------------------------


class _Data:
    """The exported tables the previews are drawn from: the versioned ones from `outputs_dir`, the customer-level fact from `private_dir`
    (a missing file is an empty table with its columns)."""

    def __init__(self, outputs_dir: Path, private_dir: Path, model: SemanticModel, min_cell: int) -> None:
        self.min_cell = min_cell
        self.t: dict[str, pd.DataFrame] = {}
        for table in model.tables:
            path = Path(private_dir if table.private else outputs_dir) / f"{table.name}.parquet"
            self.t[table.name] = pd.read_parquet(path) if path.exists() else pd.DataFrame(columns=list(table.column_names))
        customers = self.t["fact_customer_cut"]
        country = self.t["dim_country"].set_index("country_key")["country_es"] if len(self.t["dim_country"]) else pd.Series(dtype=object)
        self.customers = customers.assign(country_es=customers["country_key"].map(country))
        self.last_cut = customers["cut_key"].max() if len(customers) else None
        self.last = self.customers[self.customers["cut_key"] == self.last_cut] if self.last_cut is not None else self.customers
        self.model_row = self.t["dim_model"].iloc[0] if len(self.t["dim_model"]) else None
        method = self.t["dim_method"]
        self.method_es = dict(zip(method["method_key"], method["method_es"], strict=True)) if len(method) else {}
        self.b_star = next((k for k, s in zip(method["method_key"], method["is_b_star"], strict=True) if bool(s)), None) if len(method) else None

    def hidden(self, n: float) -> bool:
        return n < self.min_cell

    def scope(self, name: str) -> tuple[pd.DataFrame, str]:
        """The sealed rows of an evaluation fact for the test, or else those of V2, with the Spanish name of what is shown."""
        frame = self.t[name]
        sealed = frame[frame["seal_state"] == "sealed"] if "seal_state" in frame.columns else frame
        frame = sealed if len(sealed) else frame
        for scope, label in (("test", "prueba"), ("valid_v2", "validación (V2), no es la prueba")):
            part = frame[frame["scope"] == scope] if "scope" in frame.columns else frame.iloc[0:0]
            if len(part):
                return part, label
        return frame.iloc[0:0], "sin evaluar"


def _fmt(value, digits: int = 1) -> str:
    return HIDDEN if value is None or pd.isna(value) else svg.format_number(float(value), max(digits, 1))


def _int(value) -> str:
    return HIDDEN if value is None or pd.isna(value) else f"{int(value):,}".replace(",", ".")


def _pct(value, digits: int = 1) -> str:
    return HIDDEN if value is None or pd.isna(value) else f"{float(value) * 100:.{digits}f} %".replace(".", ",")


def _dec(value, digits: int = 3) -> str:
    return HIDDEN if value is None or pd.isna(value) else f"{float(value):.{digits}f}".replace(".", ",")


def _table_html(headers: list[str], rows: list[list[str]], numeric: set[int] = frozenset(), raw: set[int] = frozenset()) -> str:
    """A table; every cell is escaped except the columns in `raw`, which the caller already built from escaped text."""
    head = "".join(f'<th{" class=num" if i in numeric else ""}>{escape(h)}</th>' for i, h in enumerate(headers))
    body = "".join(
        "<tr>" + "".join(f'<td{" class=num" if i in numeric else ""}>{c if i in raw else escape(str(c))}</td>' for i, c in enumerate(row)) + "</tr>"
        for row in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body or '<tr><td>Sin datos</td></tr>'}</tbody></table>"


def _size(v: Visual) -> tuple[int, int]:
    return max(int(v.w * CELL_W - 22), 60), max(int(v.h * CELL_H - HEADER_PX - 12), 40)


def _card(big: str, sub: str = "") -> str:
    return f'<div class="big">{escape(big)}</div><div class="sub">{escape(sub)}</div>'


def _note(text: str) -> str:
    return f'<div class="rows"><p>{escape(text)}</p></div>'


def mask(customer_id) -> str:
    """A customer number as as many «•» as it has digits: the column keeps its width and the number never reaches the page."""
    return MASK * len(str(int(customer_id)))


# --- previews ---------------------------------------------------------------------------------------------------------------------


def _slicer(data: _Data, field: str) -> str:
    if field.startswith("'"):
        return '<div class="chips"><span class="chip">supuesto: elija un valor</span></div>'
    table, column = field.split("[")[0], field.split("[")[1].rstrip("]")
    values = data.t[table][column].dropna() if column in data.t[table].columns else pd.Series(dtype=object)
    shown = [str(x) for x in values.drop_duplicates().astype(str).sort_values()][:4]
    chips = "".join(f'<span class="chip">{escape(x)}</span>' for x in shown)
    more = f'<span class="chip">+{values.nunique() - len(shown)}</span>' if values.nunique() > len(shown) else ""
    return f'<div class="chips">{chips or "Sin datos"}{more}</div>'


def _cards(data: _Data) -> dict:
    last, model = data.last, data.model_row
    break_even = None if model is None else float(model["offer_cost"]) / (float(model["rescue_rate"]) * float(model["retained_value"]))
    panel = last[last["risk"] >= break_even] if break_even is not None and len(last) else last.iloc[0:0]
    benefit = None if model is None else float((panel["risk"] * float(model["rescue_rate"]) * float(model["retained_value"]) - float(model["offer_cost"])).sum())
    cut = "último corte" if data.last_cut is None else f"corte {str(data.last_cut)[:4]}-{str(data.last_cut)[4:6]}"
    runs = data.t["dim_pipeline_run"]
    ok = runs[runs["status"] == "ok"] if len(runs) else runs
    latest = runs.sort_values("as_of_key").iloc[-1] if len(runs) else None
    rules = data.t["fact_validation"]
    failed = rules[(rules["severity"] == "bloqueante") & (rules["status"] == "falla")] if len(rules) else rules
    guests = rules[rules["rule_id"] == "I02"]["rows_affected"].sum() if len(rules) else None
    tracking = data.t["fact_tracking"]
    last_as_of = tracking["as_of_key"].max() if len(tracking) else None
    returned = tracking[tracking["as_of_key"] == last_as_of]["returned"].sum() if len(tracking) else None

    def sized(n: int, make) -> str:
        """The card `make()` draws, or a dash when the customers it aggregates (`n`) are fewer than the minimum cell (D26)."""
        return _card(HIDDEN, f"menos de {data.min_cell} clientes") if data.hidden(n) else make()

    return {
        "[Clientes puntuados]": lambda: sized(len(last), lambda: _card(_int(len(last)), cut)),
        "[Contactos (umbral sellado)]": lambda: sized(int(last["is_contact"].sum()), lambda: _card(_int(int(last["is_contact"].sum())), f"umbral {_dec(None if model is None else model['threshold'], 2)}")),
        "[Riesgo medio]": lambda: sized(len(last), lambda: _card(_pct(last["risk"].mean() if len(last) else None), cut)),
        "[Bajas esperadas]": lambda: sized(len(last), lambda: _card(_fmt(last["risk"].sum() if len(last) else None), "suma de los riesgos")),
        "[Punto de equilibrio del panel]": lambda: _card(_dec(break_even), "con los valores por defecto (supuestos)"),
        "[Contactos con el panel]": lambda: sized(len(panel), lambda: _card(_int(len(panel)), cut)),
        "[Beneficio esperado con el panel (u.)]": lambda: sized(len(panel), lambda: _card(_fmt(benefit), "u. genéricas, supuestos")),
        "[Volvieron (seguimiento)]": lambda: _card(_int(returned), "en la última fecha de cálculo"),
        "[Última fecha de cálculo]": lambda: _card(str(ok["as_of_date"].max()) if len(ok) else HIDDEN, "corridas terminadas bien"),
        "dim_pipeline_run[status]": lambda: _card(HIDDEN if latest is None else str(latest["status"]), "" if latest is None else str(latest["run_key"])),
        "[Reglas bloqueantes fallidas]": lambda: _card(_int(len(failed)), "en las corridas cargadas"),
        "[Líneas de invitados]": lambda: _card(_int(guests), "regla I02, sumada por corrida"),
    }


def _list(data: _Data) -> str:
    """The list of page 1: the customers of the last scored cut by risk, highest first, with the customer column masked (D26)."""
    rows = data.last.sort_values(["risk", "customer_id"], ascending=[False, True]).head(LIST_ROWS)
    body = [[f'<span class="masked">{mask(r.customer_id)}</span>', r.country_es if isinstance(r.country_es, str) else HIDDEN, _int(r.rec_days),
             _int(r.freq_365), _fmt(r.mon_365), _pct(r.risk), *(x if isinstance(x, str) else HIDDEN for x in (r.reason_1_es, r.reason_2_es, r.reason_3_es)),
             "sí" if bool(r.is_contact) else "no"] for r in rows.itertuples()]
    return _table_html(["Cliente", "País", "Días", "Compras 365", "Gasto 365", "Riesgo", "Motivo 1", "Motivo 2", "Motivo 3", "Contacto"], body,
                       {2, 3, 4, 5}, raw={0})


def _reasons(data: _Data, v: Visual) -> str:
    w, h = _size(v)
    summary = data.t["fact_reason_summary"]
    if summary.empty:
        return svg.bar_chart([], w, h, v.title_es)
    part = summary[summary["cut_key"] == summary["cut_key"].max()]
    names = data.t["dim_reason"].set_index("reason_key")["feature_es"] if len(data.t["dim_reason"]) else {}
    shown = part[part["contacted_top3"].notna()].sort_values(["contacted_top3", "reason_key"], ascending=[False, True]).head(8)
    return svg.bar_chart([(str(names.get(k, k)), float(n)) for k, n in zip(shown["reason_key"], shown["contacted_top3"], strict=True)], w, h, v.title_es)


def _curve(data: _Data, v: Visual, name: str, x: str, y: str, label_key: str = "method_key") -> str:
    w, h = _size(v)
    frame, label = data.scope(name)
    keep = [m for m in ("model", "b2_rfm", data.b_star) if m]
    series = {}
    for method in dict.fromkeys(keep):
        part = frame[frame[label_key] == method].sort_values(x)
        if len(part):
            series[data.method_es.get(method, method)] = [(float(a), float(b)) for a, b in zip(part[x], part[y], strict=True) if pd.notna(a) and pd.notna(b)]
    return svg.line_chart(series, w, h, f"{v.title_es} ({label})")


def _cost_curve(data: _Data, v: Visual) -> str:
    w, h = _size(v)
    frame, label = data.scope("fact_cost_sensitivity")
    series = {}
    for method in dict.fromkeys(m for m in ("model", data.b_star) if m):
        part = frame[frame["method_key"] == method].sort_values("break_even")
        if len(part):
            series[data.method_es.get(method, method)] = [(float(a), float(b)) for a, b in zip(part["break_even"], part["nb_per_1000"], strict=True)]
    return svg.line_chart(series, w, h, f"{v.title_es} ({label})", unit=" u.")


def _tracking(data: _Data) -> str:
    frame = data.t["fact_tracking"].sort_values(["as_of_key", "cut_key"])
    rows = [[str(r.as_of_key), str(r.cut_key), _int(r.scored), _int(r.contacted), _int(r.returned), _int(r.churned), _fmt(r.expected_churners),
             "ventana incompleta" if bool(r.is_censored) else ""] for r in frame.itertuples()]
    return _table_html(["Fecha de cálculo", "Corte", "Puntuados", "Contactos", "Volvieron", "Se fueron", "Bajas esperadas", ""], rows[-12:], {2, 3, 4, 5, 6})


def _churn_lines(data: _Data, v: Visual) -> str:
    w, h = _size(v)
    frame = data.t["fact_tracking"]
    if frame.empty:
        return svg.line_chart({}, w, h, v.title_es)
    last = frame[frame["as_of_key"] == frame["as_of_key"].max()].sort_values("cut_key")
    xs = list(range(len(last)))
    return svg.line_chart({"Se fueron": [(float(i), float(c)) for i, c in zip(xs, last["churned"], strict=True) if pd.notna(c)],
                           "Bajas esperadas": [(float(i), float(e)) for i, e in zip(xs, last["expected_churners"], strict=True)]},
                          w, h, v.title_es, x_ticks=[(float(i), str(k)) for i, k in zip(xs, last["cut_key"], strict=True)])


def _criteria(data: _Data) -> str:
    frame = data.t["fact_evaluation_summary"]
    sealed = frame[frame["seal_state"] == "sealed"] if len(frame) else frame
    frame = (sealed if len(sealed) else frame).sort_values("criterion_id")
    rows = [[r.criterion_id, r.name_es, _dec(r.value, 3), r.threshold_es, r.verdict_es] for r in frame.itertuples()]
    return _table_html(["Criterio", "Nombre", "Valor", "Umbral", "Veredicto"], rows, {2})


def _auc_bars(data: _Data, v: Visual) -> str:
    w, h = _size(v)
    frame, label = data.scope("fact_method_metrics")
    shown = frame.sort_values("auc", ascending=False)
    return svg.bar_chart([(data.method_es.get(m, m), float(a)) for m, a in zip(shown["method_key"], shown["auc"], strict=True) if pd.notna(a)], w, h, f"{v.title_es} ({label})")


def _sensitivity(data: _Data) -> str:
    frame = data.t["fact_sensitivity"]
    sealed = frame[frame["seal_state"] == "sealed"] if len(frame) else frame
    rows = [[r.variant_es, r.method_key, _dec(r.auc), _dec(r.diff_ci_low), _dec(r.diff_ci_high)] for r in (sealed if len(sealed) else frame).itertuples()]
    return _table_html(["Variante", "Método", "AUC", "IC inferior", "IC superior"], rows[:8], {2, 3, 4})


def _definition(data: _Data) -> str:
    frame = data.t["fact_label_definition"]
    if frame.empty:
        return _table_html(["Sin datos"], [])
    ns, ms = sorted(frame["n"].unique()), sorted(frame["m"].unique())
    rate = {(n, m): None if pd.isna(k) or data.hidden(k) else r for n, m, r, k in zip(frame["n"], frame["m"], frame["churn_rate"], frame["rows"], strict=True)}
    return _table_html(["N \\ M", *[str(m) for m in ms]], [[str(n), *[_pct(rate.get((n, m))) for m in ms]] for n in ns], set(range(1, len(ms) + 1)))


def _bars(values: list[tuple[str, float]], v: Visual, unit: str = "") -> str:
    w, h = _size(v)
    return svg.bar_chart(values, w, h, v.title_es, unit=unit)


def _rules(data: _Data) -> str:
    frame = data.t["fact_validation"]
    latest = frame[frame["run_key"] == frame["run_key"].max()] if len(frame) else frame
    rows = [[r.rule_id, r.name_es, r.severity, _int(r.rows_affected), _int(r.customers_affected), _fmt(r.value_gbp), r.status] for r in latest.itertuples()]
    return _table_html(["Regla", "Nombre", "Severidad", "Filas", "Clientes", "Libras", "Estado"], rows, {3, 4, 5})


def _runs(data: _Data) -> str:
    frame = data.t["dim_pipeline_run"].sort_values("as_of_key") if len(data.t["dim_pipeline_run"]) else data.t["dim_pipeline_run"]
    rows = [[r.run_key, r.delivery_id, str(r.as_of_date), r.status, _int(r.customers_scored), _int(r.contacts), r.message or ""] for r in frame.itertuples()]
    return _table_html(["Corrida", "Entrega", "Fecha de cálculo", "Estado", "Puntuados", "Contactos", "Mensaje"], rows, {4, 5})


def _preview(data: _Data, v: Visual) -> str:
    """The body of a visual: its drawing or figure from the exported tables."""
    if v.kind == "slicer":
        return _slicer(data, v.fields[0])
    if v.kind == "card":
        maker = _cards(data).get(v.fields[0])
        return maker() if maker else _note("Se calcula en Power BI.")
    title = v.title_es
    importance, label = data.scope("fact_importance")
    names = data.t["dim_reason"].set_index("reason_key")["feature_es"] if len(data.t["dim_reason"]) else {}
    makers = {
        "Clientes por riesgo, con sus tres motivos": lambda: _list(data),
        "Motivos entre los contactados": lambda: _reasons(data, v),
        "Curva de ganancia en la prueba": lambda: _curve(data, v, "fact_gain_curve", "share_contacted", "share_captured"),
        "Curva de costo: beneficio por 1.000 clientes según el punto de equilibrio": lambda: _cost_curve(data, v),
        "Seguimiento de cada corte por fecha de cálculo": lambda: _tracking(data),
        "Bajas observadas y esperadas por corte": lambda: _churn_lines(data, v),
        "Criterios C01-C10": lambda: _criteria(data),
        "AUC por método": lambda: _auc_bars(data, v),
        "Calibración": lambda: _curve(data, v, "fact_calibration", "p_mean", "observed"),
        "Sensibilidades de N, M y diciembre": lambda: _sensitivity(data),
        "Tasa de bajas por N y M": lambda: _definition(data),
        "Silencios que vuelven": lambda: _bars([(f"N = {n}", float(s) * 100) for n, s in zip(data.t["fact_silence_return"]["n"], data.t["fact_silence_return"]["return_share"], strict=True)], v, "%"),
        "Tasa de bajas por corte (estacionalidad)": lambda: _bars([(str(c)[:10], float(r) * 100) for c, r in zip(data.t["dim_cut"]["cut_date"], data.t["dim_cut"]["churn_rate"], strict=True) if pd.notna(r)][-10:], v, "%"),
        "Importancia media |SHAP|": lambda: _bars([(str(names.get(k, FEATURES_ES.get(k, (k,))[0])), float(s)) for k, s in zip(importance["reason_key"], importance["mean_abs_shap"], strict=True)][:8], v),
        "Demostración de la fuga": lambda: _table_html(["Conjunto", "AUC en V2", "Nota"], [[r.variable_es, _dec(r.auc_valid_v2), r.note_es] for r in data.t["fact_leakage"].itertuples()], {1}),
        "Reglas de validación": lambda: _rules(data),
        "Corridas": lambda: _runs(data),
    }
    maker = makers.get(title)
    return maker() if maker else _note(title)


# --- sections -----------------------------------------------------------------------------------------------------------------


def _steps(model: SemanticModel) -> str:
    steps = [
        "Instale Power BI Desktop (gratuito, solo para Windows) y abra un informe en blanco.",
        "Cree un parámetro de texto llamado <code>CarpetaSalidas</code> con la ruta de <code>outputs\\powerbi</code> y otro llamado <code>CarpetaPrivada</code> "
        "con la de <code>outputs\\private</code> (no se versiona: tiene el número de cliente).",
        f"Cree una consulta por tabla ({len(model.tables)}) con el código de la sección «Power Query»; deje el nombre de la consulta igual al de la tabla.",
        f"En la vista de modelo, cree las {len(model.relationships)} relaciones de la tabla «Relaciones»: uno a varios (1:*), filtro único de la dimensión al "
        "hecho, todas activas. <code>dim_as_of</code>, <code>dim_model</code> y los hechos de la evaluación no tienen relaciones.",
        "Marque <code>dim_date</code> como tabla de fechas con la columna <code>date</code>; ordene <code>month_name_es</code> por <code>month</code> y "
        "<code>as_of_label</code> por <code>as_of_key</code>.",
        f"Cree los {len(model.parameters)} parámetros de hipótesis de la sección «Parámetros de los costos» con «Modelado → Nuevo parámetro → Rango numérico»: "
        "cada uno crea su tabla, su columna y un segmentador.",
        "Cree una tabla vacía llamada <code>_Medidas</code> y agregue en ella las medidas de la sección «Medidas DAX», con su formato.",
        f"Cree las {len(model.pages)} páginas a 1280 × 720 px y ubique cada visual según la grilla de {PAGE_COLUMNS} columnas por {PAGE_ROWS} filas.",
        "Guarde el informe como <code>.pbix</code>. Cuando corra el flujo, «Actualizar» vuelve a leer los mismos archivos.",
    ]
    return "<ol>" + "".join(f"<li>{s}</li>" for s in steps) + "</ol>"


def _diagram(model: SemanticModel) -> str:
    """Related dimensions above, the facts with relationships in the middle, the run table below, and the tables without relationships last."""
    width, height = 1500, 700
    related = {r.dim_table for r in model.relationships} | {r.fact_table for r in model.relationships}
    top = [t.name for t in model.tables if t.kind == "dimension" and t.name in related and t.name != "dim_pipeline_run"]
    bottom = [t.name for t in model.tables if t.name == "dim_pipeline_run" and t.name in related]
    facts = [t.name for t in model.tables if t.kind == "fact" and t.name in related]
    alone = [t.name for t in model.tables if t.name not in related]
    boxes: dict[str, tuple[float, float, float, float]] = {}
    for names, y, w, h in ((top, 24, 150, 46), (facts, 250, 150, 56), (bottom, 420, 170, 46), (alone, 590, 90, 46)):
        gap = (width - w * len(names)) / (len(names) + 1) if names else 0
        for i, name in enumerate(names):
            boxes[name] = (gap + i * (w + gap), y, w, h)
    dims = sum(1 for t in model.tables if t.kind == "dimension")
    nfacts = sum(1 for t in model.tables if t.kind == "fact")
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" class="model-svg" viewBox="0 0 {width} {height}" role="img" '
           f'aria-label="Diagrama del modelo en estrella: {dims} dimensiones y {nfacts} hechos">']
    out.append('<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">'
               '<path d="M0,0 L10,5 L0,10 z" fill="var(--muted)"/></marker></defs>')
    for r in model.relationships:
        dx, dy, dw, dh = boxes[r.dim_table]
        fx, fy, fw, fh = boxes[r.fact_table]
        up = r.dim_table in top
        x1, y1 = dx + dw / 2, (dy + dh if up else dy)
        x2, y2 = fx + fw / 2, (fy if up else fy + fh)
        out.append(f'<line class="rel" x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" marker-end="url(#arrow)">'
                   f'<title>{escape(r.rel_id)}: {escape(r.dim_table)}[{escape(r.dim_column)}] 1 → * {escape(r.fact_table)}[{escape(r.fact_column)}]</title></line>')
        sign = 1 if up else -1
        out.append(f'<text class="card" x="{x1 + 3:.1f}" y="{y1 + sign * 13:.1f}">1</text><text class="card" x="{x2 + 3:.1f}" y="{y2 - sign * 6:.1f}">*</text>')
    for name, (x, y, w, h) in boxes.items():
        table = model.table(name)
        cls = "dim" if table.kind == "dimension" else "fact"
        size = ' font-size="9"' if len(name) > 16 else ""
        key = ", ".join(table.key) if table.kind == "dimension" else f"{len(table.columns)} columnas"
        private = " (privada)" if table.private else ""
        out.append(f'<rect class="box {cls}" x="{x:.1f}" y="{y:.1f}" width="{w}" height="{h}" rx="6"/>'
                   f'<text x="{x + w / 2:.1f}" y="{y + h / 2 - 2:.1f}" text-anchor="middle"{size}>{escape(name)}</text>'
                   f'<text class="small" x="{x + w / 2:.1f}" y="{y + h / 2 + 12:.1f}" text-anchor="middle">{escape(key + private)}</text>')
    out.append('<text class="small" x="8" y="570">Sin relaciones: alimentan sus propios visuales y medidas.</text>')
    out.append(f'<text class="small" x="8" y="{height - 6}">Cada línea va de la dimensión («1») al hecho («*»); la flecha es la dirección del filtro, única y activa.</text>')
    out.append("</svg>")
    return "".join(out)


def _relationships(model: SemanticModel) -> str:
    rows = [[r.rel_id, f"{r.dim_table}[{r.dim_column}]", "1", f"{r.fact_table}[{r.fact_column}]", "*", "Uno a varios (1:*)",
             "Única: de la dimensión al hecho" if r.cross_filter == "single" else r.cross_filter, "Sí" if r.active else "No"] for r in model.relationships]
    return _table_html(["ID", "Dimensión", "", "Hecho", "", "Cardinalidad", "Dirección del filtro", "Activa"], rows)


def _queries(model: SemanticModel) -> str:
    parts = []
    for t in model.tables:
        folder = "CarpetaPrivada" if t.private else "CarpetaSalidas"
        dates = [c.name for c in t.columns if c.dtype == "date"]
        steps = f'    Origen = Parquet.Document(File.Contents({folder} & "\\{t.name}.parquet"))'
        last = "Origen"
        if dates:
            casts = ", ".join(f'{{"{d}", type date}}' for d in dates)
            steps += f",\n    Tipos = Table.TransformColumnTypes(Origen, {{{casts}}})"
            last = "Tipos"
        note = " Privada: tiene el número de cliente y no se versiona." if t.private else ""
        parts.append(f"<h3>{escape(t.name)}</h3><p>{escape(t.description_es + note)}</p><pre><code>{escape(f'let{chr(10)}{steps}{chr(10)}in{chr(10)}    {last}')}</code></pre>")
    return "".join(parts)


def _parameters(model: SemanticModel) -> str:
    rows = [[p.name_es, p.generateseries(), str(p.default).replace(".", ","), p.description_es] for p in model.parameters]
    return _table_html(["Parámetro (supuesto)", "Serie", "Por defecto", "Qué supone"], rows)


def _measures(model: SemanticModel) -> str:
    parts = []
    for m in model.measures:
        uses = sorted(dax_measure_refs(m.dax))
        used = f" Usa: {', '.join('[' + u + ']' for u in uses)}." if uses else ""
        parts.append(f"<h3>{escape(m.name_es)}</h3><p>{escape(m.description_es)}{escape(used)} Formato: <code>{escape(m.format_string)}</code>.</p>"
                     f"<pre><code>{escape(m.name_es)} =\n{escape(m.dax)}</code></pre>")
    return "".join(parts)


def _page_section(data: _Data, page: Page, number: int) -> str:
    visuals = []
    for v in page.visuals:
        style = f"grid-column:{v.x + 1} / span {v.w};grid-row:{v.y + 1} / span {v.h}"
        visuals.append(f'<section class="visual" style="{style}" aria-label="{escape(v.title_es)}"><header><b>{escape(v.title_es)}</b>'
                       f'<span>{escape(KIND_ES.get(v.kind, v.kind))}</span></header><div class="body">{_preview(data, v)}</div></section>')
    rows = [[KIND_ES.get(v.kind, v.kind), v.title_es, ", ".join(v.fields), f"x {v.x}, y {v.y}, ancho {v.w}, alto {v.h}"] for v in page.visuals]
    return (f'<h3 id="pagina-{number}">Página {number}: {escape(page.name_es)}</h3>'
            f'<div class="canvas-wrap"><div class="canvas" role="group" aria-label="Página {escape(page.name_es)}">{"".join(visuals)}</div></div>'
            f'<details><summary>Posición, tipo y campos de cada visual</summary><div class="scroll placement">'
            f'{_table_html(["Visual", "Título", "Campos", "Posición (celdas)"], rows)}</div></details>')


def _page_html(model: SemanticModel, data: _Data, meta: ExportMeta) -> str:
    nav = "".join(f'<li><a href="#{key}">{escape(title)}</a></li>' for key, title in SECTIONS)
    pages = "".join(_page_section(data, p, i) for i, p in enumerate(model.pages, start=1))
    dims = sum(1 for t in model.tables if t.kind == "dimension")
    facts = sum(1 for t in model.tables if t.kind == "fact")
    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(TITLE)}</title>
<style>{CSS}</style>
</head>
<body>
<main>
<h1>{escape(TITLE)}</h1>
<p class="lead">Guía para armar el informe en Power BI Desktop a partir de los archivos Parquet de <code>outputs/powerbi</code> y del hecho por cliente de <code>outputs/private</code>: modelo, relaciones, consultas, parámetros de los costos, medidas y las cinco páginas con sus visuales ubicados. Las vistas previas usan los números reales de esos archivos; las celdas con menos de {data.min_cell} clientes se ocultan y la columna de cliente de la lista se muestra enmascarada.</p>
<div class="meta"><span>Fecha de cálculo <b>{escape(meta.as_of.isoformat())}</b></span><span>Corrida <code>{escape(meta.run_key)}</code></span><span>SHA-256 de la fuente <code>{escape(meta.source_sha256[:12])}</code></span></div>
<nav aria-label="Secciones"><ul>{nav}</ul></nav>
<h2 id="armado">{escape(SECTIONS[0][1])}</h2>
{_steps(model)}
<div class="warn"><b>Qué se probó y qué no.</b> Las pruebas del proyecto comprueban que los archivos cumplen el modelo (claves únicas, claves foráneas en su dimensión, relaciones de uno a varios con filtro único), que cada columna, parámetro y medida que nombra el DAX existe y que el punto de equilibrio del panel empieza en el sellado y se mueve con los parámetros como dice la fórmula. <b>Ninguna medida se ejecutó</b>: no hay un motor de DAX en el equipo que generó este documento. Pendiente de verificar en Power BI: que <code>Contactos con el panel</code> y <code>Beneficio esperado con el panel (u.)</code> respeten los segmentadores de corte, país y banda (usan <code>KEEPFILTERS</code> y un <code>FILTER</code> sobre <code>fact_customer_cut</code>).</div>
<div class="warn"><b>Los costos son supuestos.</b> El umbral de contacto se eligió en V2 con un costo de la oferta, una tasa de rescate y un valor del cliente retenido declarados; los datos no traen ninguno. El panel de la página 2 deja moverlos y rotula cada uno «supuesto».</div>
<div class="warn"><b>Ningún número de cliente.</b> La lista de la página 1 lee <code>outputs/private</code>, que no se versiona; aquí su columna de cliente aparece enmascarada («{MASK * 5}») y ningún número de cliente llega a este documento.</div>
<h2 id="modelo">{escape(SECTIONS[1][1])}</h2>
<p>{dims} dimensiones y {facts} hechos. <code>dim_as_of</code> es una tabla de parámetro de las fechas de cálculo. <code>dim_model</code> y los hechos de la evaluación no tienen relaciones de clave. <code>fact_customer_cut</code> es el único hecho por cliente y se lee de la carpeta privada.</p>
{_diagram(model)}
<h2 id="relaciones">{escape(SECTIONS[2][1])}</h2>
<div class="scroll">{_relationships(model)}</div>
<h2 id="consultas">{escape(SECTIONS[3][1])}</h2>
{_queries(model)}
<h2 id="parametros">{escape(SECTIONS[4][1])}</h2>
<p>Cada parámetro se crea con «Nuevo parámetro → Rango numérico»; Power BI crea la tabla con la serie y la medida que la lee. Los valores por defecto son los costos sellados: con ellos el punto de equilibrio del panel es el del lanzamiento.</p>
<div class="scroll">{_parameters(model)}</div>
<h2 id="medidas">{escape(SECTIONS[5][1])}</h2>
<p>Todas van en la tabla <code>_Medidas</code>. Los nombres de las medidas y los textos están en español; las tablas y las columnas, en inglés.</p>
{_measures(model)}
<h2 id="paginas">{escape(SECTIONS[6][1])}</h2>
<p>Cada página es un lienzo de 1280 × 720 px (16:9) sobre una grilla de {PAGE_COLUMNS} columnas por {PAGE_ROWS} filas; la posición de cada visual está en celdas. Las vistas previas de la evaluación muestran la prueba sellada si existe y, si no, la validación (V2), rotulada.</p>
{pages}
<h2 id="fuente">{escape(SECTIONS[7][1])}</h2>
<p>{escape(meta.attribution)}</p>
<p>Datos de la corrida <code>{escape(meta.run_key)}</code>, con fecha de cálculo {escape(meta.as_of.isoformat())}. Este documento se genera desde <code>dashboard/semantic_model.py</code>; no se edita a mano.</p>
</main>
</body>
</html>
"""


def render_design(model: SemanticModel, outputs_dir: Path, private_dir: Path, html_path: Path, meta: ExportMeta, *,
                  min_cell_customers: int = MIN_CELL_CUSTOMERS) -> Path:
    """Write the HTML design of the report to `html_path` (atomically) and return the path; `min_cell_customers` is ``[site]
    min_cell_customers``."""
    problems = validate_model(model)
    if problems:
        raise ValueError(f"el modelo semántico es incoherente: {problems[0]}")
    if not isinstance(min_cell_customers, int) or isinstance(min_cell_customers, bool) or min_cell_customers < 1:
        raise ValueError(f"min_cell_customers debe ser un entero positivo; se recibió {min_cell_customers!r}")
    data = _Data(outputs_dir, private_dir, model, min_cell_customers)
    html = _page_html(model, data, meta)
    path = write_atomic(Path(html_path), html)
    logger.info("dashboard design written to %s (%d bytes)", path.name, len(html.encode("utf-8")))
    return path
