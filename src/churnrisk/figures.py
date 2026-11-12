"""Figures of the documentation, drawn with matplotlib from the site files of a run (RF29, AC42; plan, sections 2 and 25; D84). Adapted from
project 03's ``figures.py``.

Seven PNG files, always from the verified site files (``label.json``, ``algorithms.json`` and ``retention.json``, read through
``site_export.read_site``, each checked against ``manifest.json``) and never from the warehouse, a Parquet file or a constant: the churn rate of
each cut, the label for each N and M with the silences that come back, the gain curve of the test, the net benefit at each break-even, the
calibration of the test, the mean absolute SHAP of each feature, and what the contact list did cut by cut. A folder whose files are not one
export is refused with ``SiteSetError`` (project 03, D77). The site files hold no customer number, so neither does a figure (D26, AC42).

The files are deterministic (no timestamp in the metadata), so a figure changes only when its data do. Nothing is written unless every figure
was drawn. Before the test is sealed the figures that need its results say so instead of staying empty (the site publishes nothing of the test
before the seal, D17); a hidden cell (fewer customers than ``min_cell_customers``) is a gap and never a number.
"""

from __future__ import annotations

import io
import json
import logging
import textwrap
from pathlib import Path

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.patches import Patch
from matplotlib.ticker import FuncFormatter

from churnrisk.files import write_atomic
from churnrisk.site_export import SiteSetError, read_site

logger = logging.getLogger(__name__)

FIGURE_NAMES = ("churn_by_cut.png", "label_n_by_m.png", "gain_curve.png", "cost_curve.png", "calibration.png", "shap_importance.png", "retention_by_cut.png")
SITE_FILES = {"label": "label.json", "algorithms": "algorithms.json", "retention": "retention.json"}
DPI = 130
INK, GRID, MUTED = "#1f2430", "#e4e6ea", "#5b6270"
ORANGE, BLUE, GREY, GOLD, GREEN = "#eb6834", "#2a78d6", "#8a8f98", "#eda100", "#1baf7a"
PENDING = "La prueba se evalúa una sola vez, con el sello, cuando se cierran las ventanas de sus cortes: hasta entonces no se publica ninguna cifra suya"
HIDDEN = "celda oculta"
BLOCK_COLORS = {"train": BLUE, "valid_v1": GOLD, "valid_v2": ORANGE, "test": GREEN, "post_test": GREY}
BLOCK_LABELS = {"train": "Entrenamiento", "valid_v1": "Validación V1", "valid_v2": "Validación V2", "test": "Prueba", "post_test": "Después de la prueba"}
METHOD_COLORS = [ORANGE, GREY, BLUE, GOLD]
METHOD_LABELS = {"model": "Modelo", "b2_rfm": "RFM (B2)", "b3_bgnbd": "BG/NBD (B3)", "b4_frequency": "Frecuencia (B4)"}


# --- data -------------------------------------------------------------------------------------------------------------------------


def load_site(site_dir: Path) -> dict:
    """``{"label": ..., "algorithms": ..., "retention": ...}`` from the site files of a run, read through ``read_site``: a missing file says
    what to run, and a folder that is not one export is a ``SiteSetError`` (never figures drawn from two exports)."""
    for name in SITE_FILES.values():
        path = Path(site_dir) / name
        if not path.is_file():
            raise FileNotFoundError(f"No existe {path}: corra el flujo (python -m churnrisk run) antes de dibujar las figuras")
    try:
        data = read_site(site_dir)
    except SiteSetError as error:
        raise SiteSetError(f"{error}. Corra el flujo (python -m churnrisk run) antes de dibujar las figuras") from None
    return {key: json.loads(data[name].decode("utf-8")) for key, name in SITE_FILES.items()}


# --- drawing helpers --------------------------------------------------------------------------------------------------------------


def _spanish(value: float, digits: int = 0) -> str:
    text = f"{value:,.{digits}f}"
    return text.replace(",", "\0").replace(".", ",").replace("\0", ".")


def _percent(value: float, _position=None) -> str:
    return f"{_spanish(value * 100)} %"


def _style(ax, y_label: str | None = None) -> None:
    ax.set_facecolor("white")
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(MUTED)
    ax.tick_params(colors=MUTED, labelsize=9)
    if y_label:
        ax.set_ylabel(y_label, color=MUTED, fontsize=9)


def _figure(width: float = 10, height: float = 4.8) -> Figure:
    fig = Figure(figsize=(width, height), dpi=DPI, facecolor="white")
    FigureCanvasAgg(fig)
    return fig


def _title(fig: Figure, title: str, subtitle: str) -> None:
    fig.text(0.01, 0.975, title, fontsize=13, fontweight="bold", color=INK, va="top")
    fig.text(0.01, 0.925, textwrap.fill(subtitle, 135), fontsize=9, color=MUTED, va="top", linespacing=1.4)


def _pending(ax, text: str = PENDING, width: int = 70) -> None:
    ax.text(0.5, 0.5, textwrap.fill(text, width), ha="center", va="center", transform=ax.transAxes, color=MUTED, fontsize=11)
    ax.set_xticks([])
    ax.set_yticks([])


def _method(method: str) -> str:
    return METHOD_LABELS.get(method, method)


# --- the figures --------------------------------------------------------------------------------------------------------------------


def draw_churn_by_cut(label: dict) -> Figure:
    fig = _figure()
    rule = label["rule"]
    _title(fig, "Tasa de bajas por corte", f"Clientes activos en los {rule['m_days']} días anteriores a cada corte que no compraron en los {rule['n_days']} siguientes. "
           "Un corte sin barra no tiene etiqueta todavía (su ventana no cerró o es de la prueba antes del sello) o tiene pocos clientes.")
    ax = fig.add_axes([0.08, 0.17, 0.9, 0.66])
    _style(ax, "Clientes que se fueron")
    rows = label["rates_by_cut"]
    heights = [0.0 if r["churn_rate"] is None else r["churn_rate"] for r in rows]
    ax.bar(range(len(rows)), heights, 0.7, color=[BLOCK_COLORS.get(r["block"], GREY) for r in rows])
    for i, r in enumerate(rows):
        if r["suppressed"]:
            ax.text(i, 0.01, HIDDEN, ha="center", va="bottom", rotation=90, fontsize=7, color=MUTED)
        elif r["churn_rate"] is not None:
            ax.text(i, r["churn_rate"] + 0.01, _spanish(r["churn_rate"] * 100), ha="center", fontsize=7, color=MUTED)
    ax.set_xticks(range(len(rows)), [r["cut"][:7] for r in rows], rotation=60, ha="right", fontsize=8)
    ax.set_ylim(0, 1.0)
    ax.yaxis.set_major_formatter(FuncFormatter(_percent))
    blocks = list(dict.fromkeys(r["block"] for r in rows))
    ax.legend(handles=[Patch(color=BLOCK_COLORS.get(b, GREY), label=BLOCK_LABELS.get(b, b)) for b in blocks], frameon=False, fontsize=8, loc="upper left", ncol=len(blocks))
    return fig


def draw_label_n_by_m(label: dict) -> Figure:
    fig = _figure()
    _title(fig, "La baja se define: cuánto cambia con la ventana", "Izquierda: la tasa de bajas del entrenamiento para cada ventana N (días sin comprar) y cada población M (días con "
           "alguna compra antes del corte). Derecha: de los clientes que callan N días, cuántos vuelven a comprar en los N siguientes.")
    left, right = fig.subplots(1, 2, gridspec_kw={"left": 0.07, "right": 0.98, "top": 0.78, "bottom": 0.14, "wspace": 0.22})
    _style(left, "Clientes que se fueron")
    cells = label["n_by_m"]
    ns, ms = sorted({c["n"] for c in cells}), sorted({c["m"] for c in cells})
    width = 0.8 / max(len(ms), 1)
    for j, m in enumerate(ms):
        part = {c["n"]: c["churn_rate"] for c in cells if c["m"] == m}
        xs = [i + (j - (len(ms) - 1) / 2) * width for i, n in enumerate(ns) if n in part]
        left.bar(xs, [part[n] for n in ns if n in part], width, color=[BLUE, ORANGE, GOLD, GREY][j % 4], label=f"M = {m}")
    left.set_xticks(range(len(ns)), [f"N = {n}" for n in ns])
    left.yaxis.set_major_formatter(FuncFormatter(_percent))
    left.legend(frameon=False, fontsize=8, loc="upper right")
    _style(right, "Callan N días y vuelven")
    returns = label["silence_return"]
    right.bar(range(len(returns)), [r["return_share"] for r in returns], 0.6, color=GREY)
    right.set_xticks(range(len(returns)), [f"N = {r['n']}" for r in returns])
    right.yaxis.set_major_formatter(FuncFormatter(_percent))
    for i, r in enumerate(returns):
        right.text(i, r["return_share"], f"{_percent(r['return_share'])} de {_spanish(r['silences'])}", ha="center", va="bottom", fontsize=8, color=MUTED)
    return fig


def draw_gain_curve(algorithms: dict) -> Figure:
    fig = _figure()
    _title(fig, "Curva de ganancia en la prueba", "Parte de los clientes que se fueron que se alcanza contactando a una parte de los clientes, de mayor a menor riesgo. "
           "La diagonal es contactar al azar.")
    ax = fig.add_axes([0.08, 0.15, 0.9, 0.68])
    _style(ax, "Bajas alcanzadas")
    rows = algorithms["gain"]
    if not rows:
        _pending(ax)
        return fig
    for k, method in enumerate(dict.fromkeys(g["method"] for g in rows)):
        part = [g for g in rows if g["method"] == method]
        ax.plot([0.0] + [g["share_contacted"] for g in part], [0.0] + [g["share_captured"] for g in part], color=METHOD_COLORS[k % 4], linewidth=2, label=_method(method))
    ax.plot([0.0, 1.0], [0.0, 1.0], color=MUTED, linewidth=1, linestyle=":", label="Al azar")
    ax.set_xlabel("Clientes contactados", color=MUTED, fontsize=9)
    ax.xaxis.set_major_formatter(FuncFormatter(_percent))
    ax.yaxis.set_major_formatter(FuncFormatter(_percent))
    ax.legend(frameon=False, fontsize=9, loc="lower right")
    return fig


def draw_cost_curve(algorithms: dict) -> Figure:
    fig = _figure()
    _title(fig, "Beneficio neto según el punto de equilibrio", "Beneficio por 1.000 clientes de V2 con el umbral de cada método para cada punto de equilibrio "
           "(costo de la oferta sobre lo que se rescata); la línea punteada es el de los costos supuestos.")
    ax = fig.add_axes([0.1, 0.15, 0.88, 0.68])
    _style(ax, "Beneficio por 1.000 clientes (u.)")
    rows = algorithms["cost_curve"]
    if not rows:
        _pending(ax, "No hay curva de costo: el lanzamiento no la calculó")
        return fig
    b_star = algorithms["b_star"]["method"]
    ax.plot([r["break_even"] for r in rows], [r["nb_model"] for r in rows], color=ORANGE, linewidth=2, label="Modelo")
    ax.plot([r["break_even"] for r in rows], [r["nb_b_star"] for r in rows], color=GREY, linewidth=2, label=f"B*: {_method(b_star)}")
    assumed = algorithms["threshold"]["break_even"]
    ax.axvline(assumed, color=INK, linewidth=1, linestyle=":", label=f"Supuesto: {_spanish(assumed, 2)}")
    ax.set_xlabel("Punto de equilibrio", color=MUTED, fontsize=9)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: _spanish(v, 2)))
    ax.legend(frameon=False, fontsize=9, loc="upper right")
    return fig


def draw_calibration(algorithms: dict) -> Figure:
    fig = _figure(8, 5.6)
    _title(fig, "Calibración en la prueba", "Riesgo medio de cada décimo de riesgo contra la parte de esos clientes que se fue; sobre la diagonal, el riesgo "
           "dice lo que pasa. Un décimo con pocos clientes no se dibuja.")
    ax = fig.add_axes([0.11, 0.12, 0.85, 0.7])
    _style(ax, "Se fueron")
    rows = algorithms["calibration"]
    if not rows:
        _pending(ax, width=55)
        return fig
    shown = [c for c in rows if not c["suppressed"]]
    ax.plot([c["p_mean"] for c in shown], [c["observed"] for c in shown], color=ORANGE, linewidth=0, marker="o", markersize=6, label="Décimos de riesgo")
    ax.plot([0.0, 1.0], [0.0, 1.0], color=MUTED, linewidth=1, linestyle=":", label="Calibración perfecta")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_xlabel(f"Riesgo medio ({len(rows) - len(shown)} de {len(rows)} décimos sin dibujar por tener pocos clientes)", color=MUTED, fontsize=9)
    ax.xaxis.set_major_formatter(FuncFormatter(_percent))
    ax.yaxis.set_major_formatter(FuncFormatter(_percent))
    ax.legend(frameon=False, fontsize=9, loc="upper left")
    return fig


def draw_shap_importance(algorithms: dict) -> Figure:
    fig = _figure()
    test = bool(algorithms["gain"])
    _title(fig, "Qué pesa en el riesgo: importancia media de SHAP", "Promedio del valor absoluto de SHAP de cada variable en "
           + ("la prueba" if test else "la validación V2 (la prueba todavía no se evaluó)") + ", en log-odds: cuánto mueve, en promedio, el riesgo de un cliente.")
    ax = fig.add_axes([0.3, 0.13, 0.67, 0.7])
    _style(ax)
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    rows = algorithms["importance"]
    ax.barh(range(len(rows)), [r["mean_abs_shap"] for r in rows], 0.6, color=ORANGE)
    ax.set_yticks(range(len(rows)), [r["feature_es"] for r in rows], fontsize=8)
    ax.invert_yaxis()
    for i, r in enumerate(rows):
        ax.text(r["mean_abs_shap"], i, " " + _spanish(r["mean_abs_shap"], 3), va="center", fontsize=8, color=MUTED)
    ax.set_xlabel("|SHAP| medio (log-odds)", color=MUTED, fontsize=9)
    return fig


def draw_retention_by_cut(retention: dict) -> Figure:
    fig = _figure()
    _title(fig, "La lista de contacto corte a corte", "Izquierda: clientes puntuados en cada corte y cuántos pasan el umbral. Derecha: las bajas que se esperaban "
           "según el riesgo y las observadas en la última fecha de cálculo (sin punto mientras la ventana sigue abierta).")
    left, right = fig.subplots(1, 2, gridspec_kw={"left": 0.07, "right": 0.98, "top": 0.78, "bottom": 0.17, "wspace": 0.22})
    cuts = retention["cuts"]
    positions = list(range(len(cuts)))
    _style(left, "Clientes")
    hidden = [c["scored"] is None or c["contacted"] is None for c in cuts]
    rest = [0.0 if h else c["scored"] - c["contacted"] for c, h in zip(cuts, hidden, strict=True)]
    contacted = [0.0 if c["contacted"] is None else c["contacted"] for c in cuts]
    left.bar(positions, rest, 0.7, color=GRID, label="Sin contacto")
    left.bar(positions, contacted, 0.7, bottom=rest, color=ORANGE, label="Contactados")
    for i, h in enumerate(hidden):
        if h:
            left.text(i, 0, HIDDEN, ha="center", va="bottom", rotation=90, fontsize=7, color=MUTED)
    left.legend(frameon=False, fontsize=8, loc="lower right", bbox_to_anchor=(1.0, 1.0), ncol=2)
    _style(right, "Clientes que se fueron")
    last = [c["by_as_of"][-1] for c in cuts]
    right.plot(positions, [r["expected_churners"] for r in last], color=BLUE, linewidth=2, linestyle="--", marker="o", markersize=3.5, label="Esperadas")
    shown = [(i, r["churned"]) for i, r in enumerate(last) if r["churned"] is not None]
    right.plot([i for i, _ in shown], [v for _, v in shown], color=INK, linewidth=0, marker="o", markersize=5, label="Observadas")
    right.legend(frameon=False, fontsize=8, loc="lower right", bbox_to_anchor=(1.0, 1.0), ncol=2)
    for ax in (left, right):
        ax.set_xticks(positions, [c["cut"][:7] for c in cuts], fontsize=8)
        ax.set_ylim(bottom=0)
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: _spanish(v)))
    return fig


def draw_all(site: dict) -> dict[str, Figure]:
    """The seven figures, by file name, from the site data; no file is touched."""
    return {
        "churn_by_cut.png": draw_churn_by_cut(site["label"]),
        "label_n_by_m.png": draw_label_n_by_m(site["label"]),
        "gain_curve.png": draw_gain_curve(site["algorithms"]),
        "cost_curve.png": draw_cost_curve(site["algorithms"]),
        "calibration.png": draw_calibration(site["algorithms"]),
        "shap_importance.png": draw_shap_importance(site["algorithms"]),
        "retention_by_cut.png": draw_retention_by_cut(site["retention"]),
    }


# --- entry point --------------------------------------------------------------------------------------------------------------------


def _png(fig: Figure) -> bytes:
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", metadata={"Software": None})
    return buffer.getvalue()


def make_figures(site_dir: Path, out_dir: Path) -> list[Path]:
    """Draw the seven figures from the verified site files of `site_dir` and write them to `out_dir` (each atomically); returns the paths in
    ``FIGURE_NAMES`` order. Every figure is drawn and rendered before the first file is written: a missing or mixed site folder, or a figure
    that fails, writes nothing."""
    drawn = draw_all(load_site(site_dir))
    rendered = {name: _png(drawn[name]) for name in FIGURE_NAMES}
    paths = []
    for name in FIGURE_NAMES:
        paths.append(write_atomic(Path(out_dir) / name, rendered[name]))
        logger.info("figure %s written", paths[-1])
    return paths


__all__ = ["FIGURE_NAMES", "PENDING", "draw_all", "load_site", "make_figures"]
