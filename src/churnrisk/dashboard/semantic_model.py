"""The semantic model of the Power BI report: the single source of its tables and relationships (RF25, AC27; D25, D26; plan, section 19). Adapted
from project 03's ``dashboard/semantic_model.py``.

The tables with their columns (type, description, unit) and the relationships (all one to many, single direction, active) live here; the Arrow
schema of every Parquet file and, later, the data dictionary and the HTML design come from this module. Names of tables, columns and files are
in English; descriptions and labels in Spanish (D36). The measures (DAX), the three what-if parameters of the costs and the five pages of
the report (a 12 x 9 grid of visuals) live here too (U21, plan section 20, D71); ``validate_model`` checks that every DAX reference and every
field of a visual is a column, a parameter or a measure of the model.

Dimensions have a unique key; facts have a grain (``Table.key``). ``dim_as_of``, ``dim_model`` and the facts of the evaluation have no key
relationship: they feed their own visuals. The customer-level fact (``fact_customer_cut``) carries the customer number and is written to
``outputs/private/`` only, never to the versioned folder (D26). ``FEATURES_ES`` names each feature in Spanish: the reasons store the feature's
identifier and the report and the site translate it from here (D60).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

import pyarrow as pa

ARROW_TYPES = {"int32": pa.int32(), "int64": pa.int64(), "float64": pa.float64(), "string": pa.string(), "bool": pa.bool_(), "date": pa.date32()}
U, GBP = "u.", "£"

FEATURES_ES: dict[str, tuple[str, str]] = {   # identifier: (name, description)
    "rec_days": ("Días desde la última compra", "Días entre el último día de compra neta y el corte."),
    "tenure_days": ("Antigüedad", "Días entre el primer día de compra neta y el corte."),
    "freq_total": ("Días de compra", "Días con compra neta antes del corte."),
    "freq_90": ("Compras en 90 días", "Días con compra neta en los 90 días anteriores al corte."),
    "freq_365": ("Compras en 365 días", "Días con compra neta en los 365 días anteriores al corte."),
    "mon_total": ("Gasto total", "Importe neto de todas las compras anteriores al corte."),
    "mon_90": ("Gasto en 90 días", "Importe neto en los 90 días anteriores al corte."),
    "mon_365": ("Gasto en 365 días", "Importe neto en los 365 días anteriores al corte."),
    "aov_day": ("Gasto por día de compra", "Gasto total dividido por los días de compra."),
    "units_90": ("Unidades en 90 días", "Unidades netas compradas en los 90 días anteriores al corte."),
    "gap_mean": ("Tiempo medio entre compras", "Media de los días entre días de compra consecutivos (0 con un solo día)."),
    "gap_max": ("Mayor tiempo entre compras", "Máximo de los días entre días de compra consecutivos (0 con un solo día)."),
    "n_products_365": ("Productos distintos en 365 días", "Códigos de producto con compra neta en los 365 días anteriores al corte."),
    "med_units_365": ("Unidades medianas por línea", "Mediana de las unidades netas por línea en los 365 días anteriores al corte."),
    "canc_365": ("Anulaciones en 365 días", "Líneas de anulación en los 365 días anteriores al corte."),
    "canc_value_365": ("Importe anulado en 365 días", "Importe absoluto de las anulaciones en los 365 días anteriores al corte."),
    "country_group": ("País", "País de la última línea anterior al corte, con los de menos de 10 clientes en «Otros»."),
}
COUNTRIES_ES = {
    "United Kingdom": "Reino Unido", "Germany": "Alemania", "France": "Francia", "EIRE": "Irlanda", "Spain": "España", "Netherlands": "Países Bajos",
    "Belgium": "Bélgica", "Switzerland": "Suiza", "Portugal": "Portugal", "Australia": "Australia", "Italy": "Italia", "Sweden": "Suecia",
    "Channel Islands": "Islas del Canal", "Norway": "Noruega", "Japan": "Japón", "Otros": "Otros",
}
METHODS_ES = {"model": "Modelo", "b0_all": "Contactar a todos", "b1_recency": "Recencia", "b2_rfm": "RFM", "b3_bgnbd": "BG/NBD",
              "b4_frequency": "Frecuencia", "b5_alive": "1 − P(vivo)"}


@dataclass(frozen=True)
class Column:
    name: str
    dtype: str    # a key of ARROW_TYPES
    description_es: str
    unit: str | None = None


@dataclass(frozen=True)
class Table:
    name: str
    kind: Literal["dimension", "fact"]
    key: tuple[str, ...]          # a dimension's unique key or a fact's grain
    columns: tuple[Column, ...]
    description_es: str = ""
    private: bool = False         # written to outputs/private/ (not versioned), never to outputs/powerbi/

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.columns)


@dataclass(frozen=True)
class Relationship:
    rel_id: str
    dim_table: str
    dim_column: str
    fact_table: str
    fact_column: str
    cardinality: str = "one_to_many"
    cross_filter: str = "single"
    active: bool = True


@dataclass(frozen=True)
class Measure:
    name_es: str
    dax: str
    format_string: str
    description_es: str


@dataclass(frozen=True)
class WhatIfParameter:
    """A what-if parameter as Power BI's «Nuevo parámetro» creates it: a table and a column with its name, ``GENERATESERIES(start, end, step)``
    and a default; the report's measures read it with ``SELECTEDVALUE``."""

    name_es: str
    start: float
    end: float
    step: float
    default: float
    description_es: str

    def values(self) -> tuple[float, ...]:
        """The series, in decimal steps (0.05 + 0.05 is 0.1, not 0.1000000000000001)."""
        start, end, step = (Decimal(str(v)) for v in (self.start, self.end, self.step))
        count = int((end - start) / step) + 1
        return tuple(float(start + i * step) for i in range(count) if start + i * step <= end)

    def generateseries(self) -> str:
        return f"GENERATESERIES({_number(self.start)}, {_number(self.end)}, {_number(self.step)})"


def _number(value: float) -> str:
    return f"{value:g}"


@dataclass(frozen=True)
class Visual:
    kind: str                     # slicer, card, table, barChart, lineChart, matrix, ...
    title_es: str
    fields: tuple[str, ...]       # "table[column]", "'Parameter'[Parameter]" or "[Measure]"
    x: int
    y: int
    w: int
    h: int


@dataclass(frozen=True)
class Page:
    name_es: str
    visuals: tuple[Visual, ...]


@dataclass(frozen=True)
class SemanticModel:
    tables: tuple[Table, ...]
    relationships: tuple[Relationship, ...]
    measures: tuple[Measure, ...] = ()
    parameters: tuple[WhatIfParameter, ...] = ()
    pages: tuple[Page, ...] = ()

    def table(self, name: str) -> Table:
        return next(t for t in self.tables if t.name == name)

    def measure(self, name: str) -> Measure:
        return next(m for m in self.measures if m.name_es == name)


def _c(name: str, dtype: str, description_es: str, unit: str | None = None) -> Column:
    return Column(name, dtype, description_es, unit)


CUT_KEY = _c("cut_key", "int32", "Corte, como AAAAMMDD.")
SEAL_STATE = _c("seal_state", "string", "sealed (la configuración sellada) o post_seal (otra, posterior al sello).")
SCOPE = _c("scope", "string", "Bloque evaluado: valid_v2 (validación V2) o test (prueba).")
METHOD_KEY = _c("method_key", "string", "Método: el modelo o una de las líneas base B0-B5.")

DIM_DATE = Table("dim_date", "dimension", ("date_key",), (
    _c("date_key", "int32", "Fecha, como AAAAMMDD."), _c("date", "date", "Fecha."), _c("year", "int32", "Año."), _c("month", "int32", "Mes (1-12)."),
    _c("month_name_es", "string", "Nombre del mes."), _c("weekday", "int32", "Día de la semana (1 lunes, 7 domingo)."), _c("weekday_es", "string", "Nombre del día."),
), "Calendario del primero al último día de los datos.")
DIM_CUT = Table("dim_cut", "dimension", ("cut_key",), (
    CUT_KEY, _c("cut_date", "date", "Fecha de corte (día 1 de un mes)."), _c("label_end", "date", "Último día de la ventana de la etiqueta (c + N − 1)."),
    _c("block", "string", "Bloque de la partición."), _c("block_es", "string", "Bloque de la partición, en español."),
    _c("is_censored", "bool", "La ventana termina después de los datos: su etiqueta nunca se completa."),
    _c("active_customers", "int64", "Clientes activos en los M días anteriores al corte (la población).", "clientes"),
    _c("churn_rate", "float64", "Tasa de bajas del corte; nula hasta conocerla y, en la prueba, hasta el sello.", "proporción"),
), "Los cortes mensuales.")
DIM_COUNTRY = Table("dim_country", "dimension", ("country_key",), (
    _c("country_key", "int32", "País."), _c("country_group", "string", "País o «Otros», con la lista fijada en el lanzamiento."),
    _c("country_es", "string", "País, en español."), _c("train_customers", "int64", "Clientes del país en las filas de entrenamiento.", "clientes"),
), "Los grupos de país del lanzamiento.")
DIM_RISK_BAND = Table("dim_risk_band", "dimension", ("band_key",), (
    _c("band_key", "int32", "Banda de riesgo (1-10)."), _c("band_es", "string", "Banda de riesgo, en texto."),
    _c("p_low", "float64", "Riesgo desde (incluido).", "probabilidad"), _c("p_high", "float64", "Riesgo hasta (excluido; la última incluye 1).", "probabilidad"),
), "Diez bandas fijas de riesgo de 0,1.")
DIM_REASON = Table("dim_reason", "dimension", ("reason_key",), (
    _c("reason_key", "string", "Identificador de la variable."), _c("feature", "string", "Variable."), _c("feature_es", "string", "Variable, en español."),
    _c("description_es", "string", "Qué mide."),
), "Las variables que pueden ser un motivo.")
DIM_METHOD = Table("dim_method", "dimension", ("method_key",), (
    METHOD_KEY, _c("method_es", "string", "Método, en español."), _c("is_b_star", "bool", "Es la base más fuerte elegida en la validación (B*)."),
), "El modelo y las líneas base.")
DIM_MODEL = Table("dim_model", "dimension", ("model_version",), (
    _c("model_version", "string", "Versión del modelo."), _c("feature_set", "string", "Conjunto de variables elegido en V1."),
    _c("params_es", "string", "Hiperparámetros del candidato elegido."), _c("calibration", "string", "Calibración (isotónica en V1)."),
    _c("threshold", "float64", "Umbral de contacto elegido en V2.", "probabilidad"), _c("offer_cost", "float64", "Costo de la oferta (supuesto).", U),
    _c("rescue_rate", "float64", "Tasa de rescate (supuesto).", "proporción"), _c("retained_value", "float64", "Valor del cliente retenido (supuesto).", U),
    _c("break_even", "float64", "Punto de equilibrio: costo / (tasa × valor).", "probabilidad"), _c("b_star", "string", "Base más fuerte (B*)."),
    _c("trained_as_of", "date", "Fecha de cálculo del lanzamiento."), _c("config_sha256", "string", "Huella de la configuración sellada del modelo."),
    SEAL_STATE,
), "El modelo congelado del lanzamiento.")
DIM_PIPELINE_RUN = Table("dim_pipeline_run", "dimension", ("run_key",), (
    _c("run_key", "string", "Corrida."), _c("started_at", "string", "Inicio (UTC)."), _c("finished_at", "string", "Fin (UTC)."), _c("status", "string", "Estado."),
    _c("delivery_id", "string", "Entrega."), _c("as_of_date", "date", "Fecha de cálculo."), _c("as_of_key", "int32", "Fecha de cálculo, como AAAAMMDD."),
    _c("lines_delivery", "int64", "Líneas de la entrega.", "líneas"), _c("customers_scored", "int64", "Clientes puntuados.", "clientes"),
    _c("contacts", "int64", "Contactos sugeridos.", "clientes"), _c("message", "string", "Mensaje."),
), "Las corridas del flujo.")
DIM_AS_OF = Table("dim_as_of", "dimension", ("as_of_key",), (
    _c("as_of_key", "int32", "Fecha de cálculo, como AAAAMMDD."), _c("as_of_date", "date", "Fecha de cálculo."), _c("as_of_label", "string", "Fecha de cálculo, en texto."),
), "Tabla de parámetro de las fechas de cálculo, sin relaciones.")

FACT_CUT_BAND = Table("fact_cut_band", "fact", ("cut_key", "band_key"), (
    CUT_KEY, _c("band_key", "int32", "Banda de riesgo."), _c("customers", "int64", "Clientes puntuados.", "clientes"),
    _c("contacted", "int64", "Contactados.", "clientes"), _c("returned", "int64", "Volvieron a comprar hasta la última fecha de cálculo.", "clientes"),
    _c("churned", "int64", "Se fueron (con la ventana cerrada).", "clientes"), _c("expected_churners", "float64", "Bajas esperadas (Σ riesgo).", "clientes"),
    _c("suppressed", "bool", "Celda oculta: menos del mínimo de clientes, o la más chica de un desglose con una sola oculta."),
), "Clientes por corte y banda de riesgo.")
FACT_CUT_COUNTRY = Table("fact_cut_country", "fact", ("cut_key", "country_key"), (
    CUT_KEY, _c("country_key", "int32", "País."), _c("customers", "int64", "Clientes puntuados.", "clientes"), _c("contacted", "int64", "Contactados.", "clientes"),
    _c("churned", "int64", "Se fueron (con la ventana cerrada).", "clientes"), _c("suppressed", "bool", "Celda oculta, como en fact_cut_band."),
), "Clientes por corte y país.")
FACT_REASON_SUMMARY = Table("fact_reason_summary", "fact", ("cut_key", "reason_key"), (
    CUT_KEY, _c("reason_key", "string", "Variable."), _c("customers_top3", "int64", "Clientes con la variable entre sus motivos.", "clientes"),
    _c("contacted_top3", "int64", "Contactados con la variable entre sus motivos.", "clientes"),
    _c("mean_shap", "float64", "Contribución media al log-odds de esos clientes.", "log-odds"),
), "Los motivos por corte (nulos con menos del mínimo de clientes).")
FACT_TRACKING = Table("fact_tracking", "fact", ("as_of_key", "cut_key"), (
    _c("as_of_key", "int32", "Fecha de cálculo, como AAAAMMDD."), CUT_KEY, _c("scored", "int64", "Puntuados.", "clientes"), _c("contacted", "int64", "Contactados.", "clientes"),
    _c("returned", "int64", "Volvieron a comprar hasta la fecha de cálculo.", "clientes"), _c("window_closed", "bool", "La ventana cerró."),
    _c("churned", "int64", "Se fueron (nulo hasta que la ventana cierra).", "clientes"), _c("contacted_churned", "int64", "Contactados que se fueron.", "clientes"),
    _c("contacted_returned", "int64", "Contactados que volvieron.", "clientes"), _c("expected_churners", "float64", "Bajas esperadas (Σ riesgo).", "clientes"),
    _c("is_censored", "bool", "La ventana termina después de los datos."),
), "El seguimiento de cada corte puntuado en cada fecha de cálculo.")
_METRICS = (("auc", "AUC."), ("pr_auc", "PR-AUC."), ("brier", "Brier."), ("ece", "ECE de 10 intervalos."), ("threshold", "Umbral elegido en V2."),
            ("contact_share", "Proporción contactada."), ("precision", "Precisión de los contactos."), ("recall", "Recall de los contactos."),
            ("capture_10", "Proporción de bajas en el 10 % de mayor riesgo."), ("lift_10", "Lift en el 10 %."), ("capture_20", "Proporción de bajas en el 20 %."),
            ("lift_20", "Lift en el 20 %."), ("nb_total", "Beneficio neto total."), ("nb_per_1000", "Beneficio neto por cada 1.000 clientes."))
FACT_METHOD_METRICS = Table("fact_method_metrics", "fact", ("scope", "method_key", "seal_state"), (
    SCOPE, METHOD_KEY, *(_c(name, "float64", text, U if name.startswith("nb") else None) for name, text in _METRICS), SEAL_STATE,
), "Las métricas de cada método en V2 y en la prueba.")
FACT_EVALUATION_SUMMARY = Table("fact_evaluation_summary", "fact", ("criterion_id", "seal_state"), (
    _c("criterion_id", "string", "Criterio C01-C10."), _c("name_es", "string", "Criterio."), _c("value", "float64", "Valor."), _c("baseline_value", "float64", "Valor de comparación."),
    _c("ci_low", "float64", "Límite inferior del intervalo del 95 %."), _c("ci_high", "float64", "Límite superior del intervalo del 95 %."),
    _c("threshold_es", "string", "Umbral del criterio."), _c("passed", "bool", "Se cumple (nulo en C10, informativo)."),
    _c("seen_by_research", "string", "Lo vio la investigación antes de fijarlo."), _c("seen_by_planner", "string", "Lo vio el planificador antes de fijarlo."),
    _c("verdict_es", "string", "Veredicto."), SEAL_STATE,
), "Los criterios C01-C10.")
FACT_GAIN_CURVE = Table("fact_gain_curve", "fact", ("scope", "method_key", "point", "seal_state"), (
    SCOPE, METHOD_KEY, _c("point", "int32", "Punto de la curva."), _c("share_contacted", "float64", "Proporción contactada.", "proporción"),
    _c("share_captured", "float64", "Proporción de bajas captadas.", "proporción"), _c("lift", "float64", "Lift."), SEAL_STATE,
), "La curva de ganancia.")
FACT_ROC = Table("fact_roc", "fact", ("scope", "method_key", "point", "seal_state"), (
    SCOPE, METHOD_KEY, _c("point", "int32", "Punto de la curva."), _c("fpr", "float64", "Tasa de falsos positivos."), _c("tpr", "float64", "Tasa de verdaderos positivos."), SEAL_STATE,
), "La curva ROC.")
FACT_CALIBRATION = Table("fact_calibration", "fact", ("scope", "method_key", "point", "seal_state"), (
    SCOPE, METHOD_KEY, _c("point", "int32", "Intervalo de probabilidad (1-10)."), _c("p_mean", "float64", "Riesgo medio del intervalo.", "probabilidad"),
    _c("observed", "float64", "Tasa de bajas observada.", "proporción"), _c("rows", "int64", "Filas del intervalo.", "filas"), SEAL_STATE,
), "La calibración por intervalo.")
FACT_COST_SENSITIVITY = Table("fact_cost_sensitivity", "fact", ("scope", "break_even", "method_key", "seal_state"), (
    SCOPE, _c("break_even", "float64", "Punto de equilibrio supuesto.", "probabilidad"), METHOD_KEY, _c("threshold", "float64", "Umbral elegido en V2.", "probabilidad"),
    _c("nb_per_1000", "float64", "Beneficio neto por cada 1.000 clientes.", U), _c("contact_share", "float64", "Proporción contactada.", "proporción"), SEAL_STATE,
), "El beneficio neto según el punto de equilibrio, del modelo y de B*.")
FACT_SENSITIVITY = Table("fact_sensitivity", "fact", ("variant", "method_key", "seal_state"), (
    _c("variant", "string", "Variante (n60, n120, m180, no_december)."), _c("variant_es", "string", "Variante, en español."), _c("n", "int32", "N (días)."),
    _c("m", "int32", "M (días)."), _c("method_key", "string", "model, b2_rfm o b_star."), _c("auc", "float64", "AUC en su prueba."),
    _c("churn_rate", "float64", "Tasa de bajas de su prueba.", "proporción"), _c("rows", "int64", "Filas de su prueba.", "filas"),
    _c("diff_ci_low", "float64", "Límite inferior del intervalo de AUC(modelo) − AUC(método)."), _c("diff_ci_high", "float64", "Límite superior del mismo intervalo."),
    SEAL_STATE,
), "Las sensibilidades de N, M y del corte de diciembre (informativas).")
FACT_LABEL_DEFINITION = Table("fact_label_definition", "fact", ("n", "m"), (
    _c("n", "int32", "N (días)."), _c("m", "int32", "M (días)."), _c("churn_rate", "float64", "Tasa de bajas del entrenamiento.", "proporción"),
    _c("rows", "int64", "Filas del entrenamiento.", "filas"),
), "La tasa de bajas del entrenamiento por N y M.")
FACT_SILENCE_RETURN = Table("fact_silence_return", "fact", ("n",), (
    _c("n", "int32", "N (días)."), _c("silences", "int64", "Silencios de N días en el entrenamiento.", "filas"),
    _c("return_share", "float64", "Proporción que vuelve a comprar en los N días siguientes.", "proporción"),
), "Los silencios que vuelven.")
FACT_IMPORTANCE = Table("fact_importance", "fact", ("scope", "reason_key", "seal_state"), (
    SCOPE, _c("reason_key", "string", "Variable."), _c("mean_abs_shap", "float64", "Media de |SHAP|.", "log-odds"), SEAL_STATE,
), "La importancia media de cada variable.")
FACT_SELECTION = Table("fact_selection", "fact", ("feature_set", "learning_rate", "max_leaf_nodes", "min_samples_leaf"), (
    _c("feature_set", "string", "Conjunto de variables."), _c("learning_rate", "float64", "Tasa de aprendizaje."), _c("max_leaf_nodes", "int32", "Hojas."),
    _c("min_samples_leaf", "int32", "Muestras por hoja."), _c("log_loss_v1", "float64", "Pérdida logarítmica en V1."), _c("chosen", "bool", "Es el elegido."),
), "Los candidatos de la grilla y su pérdida en V1.")
FACT_LEAKAGE = Table("fact_leakage", "fact", ("variable",), (
    _c("variable", "string", "Conjunto."), _c("variable_es", "string", "Conjunto, en español."), _c("auc_valid_v2", "float64", "AUC en V2."), _c("note_es", "string", "Nota."),
), "La demostración de la fuga.")
FACT_VALIDATION = Table("fact_validation", "fact", ("run_key", "rule_id"), (
    _c("run_key", "string", "Corrida."), _c("rule_id", "string", "Regla."), _c("name_es", "string", "Regla, en español."), _c("severity", "string", "Severidad."),
    _c("scope", "string", "Alcance."), _c("aggregation", "string", "Cómo se agrega entre corridas."), _c("status", "string", "pasa, falla, advierte o no evaluada."),
    _c("rows_affected", "int64", "Filas afectadas.", "filas"), _c("customers_affected", "int64", "Clientes afectados.", "clientes"),
    _c("value_gbp", "float64", "Importe afectado.", GBP),
), "Las reglas de validación de cada corrida.")
FACT_CUSTOMER_CUT = Table("fact_customer_cut", "fact", ("customer_id", "cut_key"), (
    _c("customer_id", "int64", "Número de cliente (solo en la tabla privada)."), CUT_KEY, _c("country_key", "int32", "País."), _c("band_key", "int32", "Banda de riesgo."),
    _c("rec_days", "int64", "Días desde la última compra.", "días"), _c("freq_365", "int64", "Días de compra en 365 días.", "días"),
    _c("mon_365", "float64", "Gasto en 365 días.", GBP), _c("gap_mean", "float64", "Tiempo medio entre compras.", "días"),
    _c("risk", "float64", "Riesgo calibrado.", "probabilidad"), _c("is_contact", "bool", "Se contacta (riesgo ≥ umbral sellado)."),
    _c("reason_1_es", "string", "Primer motivo."), _c("reason_2_es", "string", "Segundo motivo."), _c("reason_3_es", "string", "Tercer motivo."),
    _c("returned", "bool", "Volvió a comprar hasta la última fecha de cálculo."), _c("first_return_date", "date", "Primer día de compra en la ventana."),
    _c("churned", "int64", "Se fue (nulo hasta que la ventana cierra)."), _c("scored_as_of_date", "date", "Fecha de cálculo de la puntuación."),
    _c("model_version", "string", "Versión del modelo."), _c("run_key", "string", "Corrida que puntuó."),
), "Un cliente en un corte puntuado: la lista de riesgo. Privada: lleva el número de cliente y no se versiona (D26).", private=True)

TABLES: tuple[Table, ...] = (
    DIM_DATE, DIM_CUT, DIM_COUNTRY, DIM_RISK_BAND, DIM_REASON, DIM_METHOD, DIM_MODEL, DIM_PIPELINE_RUN, DIM_AS_OF,
    FACT_CUT_BAND, FACT_CUT_COUNTRY, FACT_REASON_SUMMARY, FACT_TRACKING, FACT_METHOD_METRICS, FACT_EVALUATION_SUMMARY, FACT_GAIN_CURVE, FACT_ROC,
    FACT_CALIBRATION, FACT_COST_SENSITIVITY, FACT_SENSITIVITY, FACT_LABEL_DEFINITION, FACT_SILENCE_RETURN, FACT_IMPORTANCE, FACT_SELECTION, FACT_LEAKAGE,
    FACT_VALIDATION, FACT_CUSTOMER_CUT,
)
_PAIRS = (
    *(("dim_cut", "cut_key", fact, "cut_key") for fact in ("fact_customer_cut", "fact_cut_band", "fact_cut_country", "fact_reason_summary", "fact_tracking")),
    *(("dim_country", "country_key", fact, "country_key") for fact in ("fact_customer_cut", "fact_cut_country")),
    *(("dim_risk_band", "band_key", fact, "band_key") for fact in ("fact_customer_cut", "fact_cut_band")),
    *(("dim_reason", "reason_key", fact, "reason_key") for fact in ("fact_reason_summary", "fact_importance")),
    *(("dim_method", "method_key", fact, "method_key") for fact in ("fact_method_metrics", "fact_gain_curve", "fact_roc", "fact_calibration", "fact_cost_sensitivity")),
    ("dim_date", "date_key", "fact_tracking", "as_of_key"),
    ("dim_pipeline_run", "run_key", "fact_validation", "run_key"),
)
RELATIONSHIPS: tuple[Relationship, ...] = tuple(Relationship(f"R{i:02d}", *pair) for i, pair in enumerate(_PAIRS, start=1))

# --- the what-if parameters, the measures and the pages (plan, section 20; D71) ------------------------------------------------------

OFFER, RATE, VALUE = "Costo de la oferta", "Tasa de rescate", "Valor del cliente retenido"
PARAMETERS: tuple[WhatIfParameter, ...] = (
    WhatIfParameter(OFFER, 1, 20, 0.5, 5, "Costo de una oferta de retención, en unidades genéricas: un supuesto, no un dato (D22)."),
    WhatIfParameter(RATE, 0.05, 0.5, 0.05, 0.2, "Parte de los clientes que se iban y la oferta retiene: un supuesto, no un dato (D22)."),
    WhatIfParameter(VALUE, 10, 200, 5, 50, "Valor de un cliente retenido, en unidades genéricas: un supuesto, no un dato (D22)."),
)
INTEGER, PERCENT, DECIMAL_1, DECIMAL_2, DECIMAL_3, DATE_FORMAT, TEXT_FORMAT = "#,0", "0.0%", "#,0.0", "0.00", "0.000", "yyyy-mm-dd", "@"
_CONTACTED = "fact_customer_cut[is_contact] = TRUE ()"
_TEST_MODEL = 'fact_method_metrics[scope] = "test", fact_method_metrics[method_key] = "model", fact_method_metrics[seal_state] = "sealed"'

MEASURES: tuple[Measure, ...] = (
    Measure("Costo de la oferta (u.)", f"SELECTEDVALUE ( '{OFFER}'[{OFFER}], 5 )", DECIMAL_2, "El costo de la oferta elegido en el panel (supuesto); 5 sin elegir."),
    Measure("Tasa de rescate", f"SELECTEDVALUE ( '{RATE}'[{RATE}], 0.2 )", PERCENT, "La tasa de rescate elegida en el panel (supuesto); 0,2 sin elegir."),
    Measure("Valor del cliente retenido (u.)", f"SELECTEDVALUE ( '{VALUE}'[{VALUE}], 50 )", DECIMAL_2,
            "El valor del cliente retenido elegido en el panel (supuesto); 50 sin elegir."),
    Measure("Punto de equilibrio del panel", "DIVIDE ( [Costo de la oferta (u.)], [Tasa de rescate] * [Valor del cliente retenido (u.)] )", DECIMAL_3,
            "Riesgo desde el que contactar paga con los supuestos del panel: costo / (tasa × valor). Con los valores por defecto es el sellado, 0,5."),
    Measure("Clientes puntuados", "COUNTROWS ( fact_customer_cut )", INTEGER, "Clientes puntuados en los cortes elegidos."),
    Measure("Riesgo medio", "AVERAGE ( fact_customer_cut[risk] )", PERCENT, "Probabilidad media de irse de los clientes puntuados."),
    Measure("Bajas esperadas", "SUM ( fact_customer_cut[risk] )", DECIMAL_1, "Clientes que el modelo espera que se vayan: la suma de los riesgos."),
    Measure("Contactos (umbral sellado)", f"CALCULATE ( COUNTROWS ( fact_customer_cut ), {_CONTACTED} )", INTEGER,
            "Clientes cuyo riesgo alcanza el umbral sellado en V2."),
    Measure("Contactos con el panel", "VAR t = [Punto de equilibrio del panel]\n    RETURN CALCULATE ( COUNTROWS ( fact_customer_cut ), KEEPFILTERS ( fact_customer_cut[risk] >= t ) )",
            INTEGER, "Clientes cuyo riesgo alcanza el punto de equilibrio del panel, dentro de los segmentadores de corte, país y banda."),
    Measure("Beneficio esperado con el panel (u.)",
            "VAR t = [Punto de equilibrio del panel]\n    RETURN SUMX ( FILTER ( fact_customer_cut, fact_customer_cut[risk] >= t ),\n"
            "        fact_customer_cut[risk] * [Tasa de rescate] * [Valor del cliente retenido (u.)] - [Costo de la oferta (u.)] )",
            DECIMAL_1, "Beneficio esperado de contactar a esos clientes con los supuestos del panel: riesgo × tasa × valor − costo, sumado."),
    Measure("Ventanas cerradas", "CALCULATE ( COUNTROWS ( fact_customer_cut ), NOT ISBLANK ( fact_customer_cut[churned] ) )", INTEGER,
            "Clientes puntuados cuya ventana de 90 días ya cerró."),
    Measure("Bajas observadas", "CALCULATE ( COUNTROWS ( fact_customer_cut ), fact_customer_cut[churned] = 1 )", INTEGER,
            "Clientes que no volvieron a comprar en su ventana cerrada."),
    Measure("Tasa de bajas observada", "DIVIDE ( [Bajas observadas], [Ventanas cerradas] )", PERCENT, "Bajas observadas entre las ventanas cerradas."),
    Measure("Volvieron a comprar", "CALCULATE ( COUNTROWS ( fact_customer_cut ), fact_customer_cut[returned] = TRUE () )", INTEGER,
            "Clientes puntuados que volvieron a comprar hasta la última fecha de cálculo."),
    Measure("Contactos que se fueron", "CALCULATE ( [Contactos (umbral sellado)], fact_customer_cut[churned] = 1 )", INTEGER,
            "Contactos cuya ventana cerró sin una compra."),
    Measure("Contactos con ventana cerrada", "CALCULATE ( [Contactos (umbral sellado)], NOT ISBLANK ( fact_customer_cut[churned] ) )", INTEGER,
            "Contactos cuya ventana ya cerró."),
    Measure("Precisión de los contactos", "DIVIDE ( [Contactos que se fueron], [Contactos con ventana cerrada] )", PERCENT,
            "Parte de los contactos con ventana cerrada que se fue."),
    Measure("Recall de los contactos", "DIVIDE ( [Contactos que se fueron], [Bajas observadas] )", PERCENT, "Parte de las bajas observadas que se contactó."),
    Measure("Beneficio neto con los supuestos (u.)",
            "[Contactos que se fueron] * [Tasa de rescate] * [Valor del cliente retenido (u.)]\n    - [Contactos con ventana cerrada] * [Costo de la oferta (u.)]",
            DECIMAL_1, "Lo que habrían dejado los contactos de las ventanas cerradas con los supuestos del panel."),
    Measure("Clientes del corte (agregado)", "SUM ( fact_cut_band[customers] )", INTEGER, "Clientes puntuados según la tabla versionada, sin las celdas ocultas."),
    Measure("Contactos del corte (agregado)", "SUM ( fact_cut_band[contacted] )", INTEGER, "Contactos según la tabla versionada, sin las celdas ocultas."),
    Measure("Volvieron (seguimiento)",
            "VAR d = MAX ( fact_tracking[as_of_key] ) RETURN CALCULATE ( SUM ( fact_tracking[returned] ), fact_tracking[as_of_key] = d )", INTEGER,
            "Clientes que volvieron a comprar, en la última fecha de cálculo elegida."),
    Measure("AUC del modelo (prueba)", f"CALCULATE ( SELECTEDVALUE ( fact_method_metrics[auc] ), {_TEST_MODEL} )", DECIMAL_3,
            "AUC del modelo en la prueba sellada; vacío hasta el sello."),
    Measure("Captura en el 10 % (prueba)", f"CALCULATE ( SELECTEDVALUE ( fact_method_metrics[capture_10] ), {_TEST_MODEL} )", PERCENT,
            "Parte de las bajas en el 10 % de mayor riesgo de cada corte de prueba, del modelo; vacío hasta el sello."),
    Measure("Umbral sellado", "SELECTEDVALUE ( dim_model[threshold] )", DECIMAL_2, "Umbral de contacto elegido en V2 y sellado."),
    Measure("Veredicto", 'CALCULATE ( SELECTEDVALUE ( fact_evaluation_summary[verdict_es] ), fact_evaluation_summary[seal_state] = "sealed" )', TEXT_FORMAT,
            "El veredicto sellado del criterio elegido."),
    Measure("Última fecha de cálculo", 'CALCULATE ( MAX ( dim_pipeline_run[as_of_date] ), dim_pipeline_run[status] = "ok" )', DATE_FORMAT,
            "La fecha de cálculo de la última corrida que terminó bien."),
    Measure("Reglas bloqueantes fallidas",
            'CALCULATE ( COUNTROWS ( fact_validation ), fact_validation[severity] = "bloqueante", fact_validation[status] = "falla" )', INTEGER,
            "Reglas bloqueantes que fallaron en las corridas elegidas."),
    Measure("Líneas de invitados", 'CALCULATE ( SUM ( fact_validation[rows_affected] ), fact_validation[rule_id] = "I02" )', INTEGER,
            "Líneas sin cliente (invitados) de las entregas de las corridas elegidas (regla I02, sumada por corrida)."),
)

PAGE_COLUMNS, PAGE_ROWS = 12, 9
_LIST = ("fact_customer_cut[customer_id]", "dim_country[country_es]", "fact_customer_cut[rec_days]", "fact_customer_cut[freq_365]", "fact_customer_cut[mon_365]",
         "fact_customer_cut[risk]", "fact_customer_cut[reason_1_es]", "fact_customer_cut[reason_2_es]", "fact_customer_cut[reason_3_es]", "fact_customer_cut[is_contact]")
_TRACKING = ("fact_tracking[as_of_key]", "dim_cut[cut_date]", "fact_tracking[scored]", "fact_tracking[contacted]", "fact_tracking[returned]",
             "fact_tracking[churned]", "fact_tracking[expected_churners]", "fact_tracking[is_censored]")
_CRITERIA = ("fact_evaluation_summary[criterion_id]", "fact_evaluation_summary[name_es]", "fact_evaluation_summary[value]", "fact_evaluation_summary[threshold_es]",
             "fact_evaluation_summary[seen_by_research]", "fact_evaluation_summary[seen_by_planner]", "fact_evaluation_summary[verdict_es]")
PAGES: tuple[Page, ...] = (
    Page("Clientes en riesgo y sus motivos", (
        Visual("slicer", "Corte", ("dim_cut[cut_date]",), 0, 0, 4, 1),
        Visual("slicer", "País", ("dim_country[country_es]",), 4, 0, 4, 1),
        Visual("slicer", "Banda de riesgo", ("dim_risk_band[band_es]",), 8, 0, 4, 1),
        Visual("card", "Clientes puntuados", ("[Clientes puntuados]",), 0, 1, 3, 1),
        Visual("card", "Contactos (umbral sellado)", ("[Contactos (umbral sellado)]",), 3, 1, 3, 1),
        Visual("card", "Riesgo medio", ("[Riesgo medio]",), 6, 1, 3, 1),
        Visual("card", "Bajas esperadas", ("[Bajas esperadas]",), 9, 1, 3, 1),
        Visual("table", "Clientes por riesgo, con sus tres motivos", _LIST, 0, 2, 8, 7),
        Visual("barChart", "Motivos entre los contactados", ("dim_reason[feature_es]", "fact_reason_summary[contacted_top3]"), 8, 2, 4, 7),
    )),
    Page("Ganancia y costos", (
        Visual("slicer", f"{OFFER} (supuesto)", (f"'{OFFER}'[{OFFER}]",), 0, 0, 4, 1),
        Visual("slicer", f"{RATE} (supuesto)", (f"'{RATE}'[{RATE}]",), 4, 0, 4, 1),
        Visual("slicer", f"{VALUE} (supuesto)", (f"'{VALUE}'[{VALUE}]",), 8, 0, 4, 1),
        Visual("card", "Punto de equilibrio del panel", ("[Punto de equilibrio del panel]",), 0, 1, 4, 1),
        Visual("card", "Contactos con el panel", ("[Contactos con el panel]",), 4, 1, 4, 1),
        Visual("card", "Beneficio esperado con el panel (u.)", ("[Beneficio esperado con el panel (u.)]",), 8, 1, 4, 1),
        Visual("lineChart", "Curva de ganancia en la prueba", ("fact_gain_curve[share_contacted]", "fact_gain_curve[share_captured]", "dim_method[method_es]"), 0, 2, 6, 7),
        Visual("lineChart", "Curva de costo: beneficio por 1.000 clientes según el punto de equilibrio",
               ("fact_cost_sensitivity[break_even]", "fact_cost_sensitivity[nb_per_1000]", "dim_method[method_es]"), 6, 2, 6, 7),
    )),
    Page("Seguimiento", (
        Visual("slicer", "Fecha de cálculo", ("dim_as_of[as_of_label]",), 0, 0, 4, 1),
        Visual("slicer", "Corte", ("dim_cut[cut_date]",), 4, 0, 4, 1),
        Visual("card", "Volvieron (seguimiento)", ("[Volvieron (seguimiento)]",), 8, 0, 4, 1),
        Visual("table", "Seguimiento de cada corte por fecha de cálculo", _TRACKING, 0, 1, 12, 5),
        Visual("lineChart", "Bajas observadas y esperadas por corte", ("dim_cut[cut_date]", "fact_tracking[churned]", "fact_tracking[expected_churners]"), 0, 6, 12, 3),
    )),
    Page("Validación del modelo", (
        Visual("table", "Criterios C01-C10", _CRITERIA, 0, 0, 7, 3),
        Visual("barChart", "AUC por método", ("dim_method[method_es]", "fact_method_metrics[auc]"), 7, 0, 5, 3),
        Visual("lineChart", "Calibración", ("fact_calibration[p_mean]", "fact_calibration[observed]", "dim_method[method_es]"), 0, 3, 4, 3),
        Visual("table", "Sensibilidades de N, M y diciembre", ("fact_sensitivity[variant_es]", "fact_sensitivity[method_key]", "fact_sensitivity[auc]",
                                                                "fact_sensitivity[diff_ci_low]", "fact_sensitivity[diff_ci_high]"), 4, 3, 4, 3),
        Visual("matrix", "Tasa de bajas por N y M", ("fact_label_definition[n]", "fact_label_definition[m]", "fact_label_definition[churn_rate]"), 8, 3, 4, 3),
        Visual("barChart", "Silencios que vuelven", ("fact_silence_return[n]", "fact_silence_return[return_share]"), 0, 6, 3, 3),
        Visual("lineChart", "Tasa de bajas por corte (estacionalidad)", ("dim_cut[cut_date]", "dim_cut[churn_rate]"), 3, 6, 3, 3),
        Visual("barChart", "Importancia media |SHAP|", ("dim_reason[feature_es]", "fact_importance[mean_abs_shap]"), 6, 6, 3, 3),
        Visual("table", "Demostración de la fuga", ("fact_leakage[variable_es]", "fact_leakage[auc_valid_v2]", "fact_leakage[note_es]"), 9, 6, 3, 3),
    )),
    Page("Calidad y corridas", (
        Visual("card", "Última fecha de cálculo", ("[Última fecha de cálculo]",), 0, 0, 3, 1),
        Visual("card", "Estado de la última corrida", ("dim_pipeline_run[status]",), 3, 0, 3, 1),
        Visual("card", "Reglas bloqueantes fallidas", ("[Reglas bloqueantes fallidas]",), 6, 0, 3, 1),
        Visual("card", "Líneas de invitados", ("[Líneas de invitados]",), 9, 0, 3, 1),
        Visual("table", "Reglas de validación", ("fact_validation[rule_id]", "fact_validation[name_es]", "fact_validation[severity]", "fact_validation[rows_affected]",
                                                 "fact_validation[customers_affected]", "fact_validation[value_gbp]", "fact_validation[status]"), 0, 1, 12, 4),
        Visual("table", "Corridas", ("dim_pipeline_run[run_key]", "dim_pipeline_run[delivery_id]", "dim_pipeline_run[as_of_date]", "dim_pipeline_run[status]",
                                     "dim_pipeline_run[customers_scored]", "dim_pipeline_run[contacts]", "dim_pipeline_run[message]"), 0, 5, 12, 4),
    )),
)
MODEL = SemanticModel(TABLES, RELATIONSHIPS, MEASURES, PARAMETERS, PAGES)


def arrow_schema(table: Table) -> pa.Schema:
    """The Arrow schema of a table: its columns in order with their types."""
    return pa.schema([pa.field(c.name, ARROW_TYPES[c.dtype]) for c in table.columns])


_COLUMN_REF = re.compile(r"(?<!['\w])([A-Za-z_][A-Za-z0-9_]*)\[([A-Za-z_][A-Za-z0-9_]*)\]")
_PARAMETER_REF = re.compile(r"'([^']+)'\[([^\]]+)\]")
_MEASURE_REF = re.compile(r"(?<![\w\]'])\[([^\[\]]+)\]")


def dax_column_refs(dax: str) -> set[tuple[str, str]]:
    """The ``table[column]`` references of a DAX expression (a table named without quotes)."""
    return set(_COLUMN_REF.findall(dax))


def dax_parameter_refs(dax: str) -> set[tuple[str, str]]:
    """The ``'Table'[Column]`` references of a DAX expression: in this model, the what-if parameters (their names have spaces)."""
    return set(_PARAMETER_REF.findall(dax))


def dax_measure_refs(dax: str) -> set[str]:
    """The ``[Measure]`` references of a DAX expression: a bracket not attached to a table or a parameter."""
    return set(_MEASURE_REF.findall(_PARAMETER_REF.sub("", dax)))


def _field_problem(model: SemanticModel, field: str) -> str | None:
    """Why the field of a visual does not resolve, or None."""
    if field.startswith("'"):
        match = _PARAMETER_REF.fullmatch(field)
        ok = match is not None and match.group(1) == match.group(2) and any(p.name_es == match.group(1) for p in model.parameters)
        return None if ok else f"el parámetro {field} no existe"
    if field.startswith("["):
        return None if any(f"[{m.name_es}]" == field for m in model.measures) else f"la medida {field} no existe"
    match = _COLUMN_REF.fullmatch(field)
    if match is None:
        return f"el campo {field!r} no es una columna, un parámetro ni una medida"
    table, column = match.groups()
    return None if any(t.name == table and column in t.column_names for t in model.tables) else f"la columna {field} no existe"


def _measure_problems(model: SemanticModel) -> list[str]:
    problems: list[str] = []
    names = [m.name_es for m in model.measures]
    problems += [f"la medida [{n}] está repetida" for n in sorted({n for n in names if names.count(n) > 1})]
    tables = {t.name: set(t.column_names) for t in model.tables}
    parameters = {p.name_es for p in model.parameters}
    for m in model.measures:
        if m.dax.count("(") != m.dax.count(")") or m.dax.count('"') % 2:
            problems.append(f"[{m.name_es}]: paréntesis o comillas sin cerrar en el DAX")
        problems += [f"[{m.name_es}]: {t}[{c}] no existe" for t, c in sorted(dax_column_refs(m.dax)) if c not in tables.get(t, ())]
        problems += [f"[{m.name_es}]: el parámetro '{t}'[{c}] no existe" for t, c in sorted(dax_parameter_refs(m.dax)) if t not in parameters or c != t]
        problems += [f"[{m.name_es}]: la medida [{r}] no existe" for r in sorted(dax_measure_refs(m.dax) - {m.name_es}) if r not in names]
        if not m.format_string or not m.description_es:
            problems.append(f"[{m.name_es}]: necesita un formato y una descripción")
    for p in model.parameters:
        if not p.start < p.end or p.step <= 0 or p.default not in p.values():
            problems.append(f"el parámetro {p.name_es}: el valor por defecto {p.default} no está en {p.generateseries()}")
    return problems


def _page_problems(model: SemanticModel) -> list[str]:
    problems: list[str] = []
    for page in model.pages:
        taken: dict[tuple[int, int], str] = {}
        for v in page.visuals:
            label = f"{page.name_es}: {v.title_es}"
            problems += [f"{label}: {why}" for field in v.fields if (why := _field_problem(model, field)) is not None]
            if v.w < 1 or v.h < 1 or v.x < 0 or v.y < 0 or v.x + v.w > PAGE_COLUMNS or v.y + v.h > PAGE_ROWS:
                problems.append(f"{label}: sale de la grilla de {PAGE_COLUMNS} x {PAGE_ROWS}")
                continue
            cells = [(cx, cy) for cx in range(v.x, v.x + v.w) for cy in range(v.y, v.y + v.h)]
            clash = next((taken[c] for c in cells if c in taken), None)
            if clash is not None:
                problems.append(f"{label}: se superpone con {clash}")
            taken.update({c: v.title_es for c in cells})
    return problems


def validate_model(model: SemanticModel) -> list[str]:
    """What is incoherent in `model` (empty when nothing is): unique table names, known types, keys among the columns, relationships between a
    dimension's whole key and a fact's column of the same type, one to many, single direction and active, and the private table alone."""
    problems: list[str] = []
    names = [t.name for t in model.tables]
    if len(set(names)) != len(names):
        problems.append("hay tablas repetidas")
    by_name = {t.name: t for t in model.tables}
    for table in model.tables:
        columns = {c.name: c for c in table.columns}
        if len(columns) != len(table.columns):
            problems.append(f"{table.name} repite una columna")
        problems += [f"{table.name}[{c.name}] tiene un tipo desconocido {c.dtype}" for c in table.columns if c.dtype not in ARROW_TYPES]
        problems += [f"la clave {k} de {table.name} no es una columna" for k in table.key if k not in columns]
        if not table.private and any("customer_id" in c or "invoice" in c for c in columns):
            problems.append(f"{table.name} es versionada y tiene una columna de cliente o de factura (D26)")
    for r in model.relationships:
        dim, fact = by_name.get(r.dim_table), by_name.get(r.fact_table)
        if dim is None or fact is None or dim.kind != "dimension" or fact.kind != "fact":
            problems.append(f"{r.rel_id} no une una dimensión con un hecho")
            continue
        if dim.key != (r.dim_column,):
            problems.append(f"{r.rel_id} no usa la clave entera de {dim.name}")
        dim_col = next((c for c in dim.columns if c.name == r.dim_column), None)
        fact_col = next((c for c in fact.columns if c.name == r.fact_column), None)
        if dim_col is None or fact_col is None or dim_col.dtype != fact_col.dtype:
            problems.append(f"{r.rel_id}: {r.fact_table}[{r.fact_column}] no es una columna del tipo de {r.dim_table}[{r.dim_column}]")
        if (r.cardinality, r.cross_filter, r.active) != ("one_to_many", "single", True):
            problems.append(f"{r.rel_id} no es uno a varios, de filtro unidireccional y activa")
    return problems + _measure_problems(model) + _page_problems(model)
