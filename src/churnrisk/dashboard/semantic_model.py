"""The semantic model of the Power BI report: the single source of its tables and relationships (RF25, AC27; D25, D26; plan, section 19). Adapted
from project 03's ``dashboard/semantic_model.py``.

The tables with their columns (type, description, unit) and the relationships (all one to many, single direction, active) live here; the Arrow
schema of every Parquet file and, later, the data dictionary and the HTML design come from this module. Names of tables, columns and files are
in English; descriptions and labels in Spanish (D36). The measures, the what-if parameters and the pages arrive with U21.

Dimensions have a unique key; facts have a grain (``Table.key``). ``dim_as_of``, ``dim_model`` and the facts of the evaluation have no key
relationship: they feed their own visuals. The customer-level fact (``fact_customer_cut``) carries the customer number and is written to
``outputs/private/`` only, never to the versioned folder (D26). ``FEATURES_ES`` names each feature in Spanish: the reasons store the feature's
identifier and the report and the site translate it from here (D60).
"""

from __future__ import annotations

from dataclasses import dataclass
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
class SemanticModel:
    tables: tuple[Table, ...]
    relationships: tuple[Relationship, ...]

    def table(self, name: str) -> Table:
        return next(t for t in self.tables if t.name == name)


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
MODEL = SemanticModel(TABLES, RELATIONSHIPS)


def arrow_schema(table: Table) -> pa.Schema:
    """The Arrow schema of a table: its columns in order with their types."""
    return pa.schema([pa.field(c.name, ARROW_TYPES[c.dtype]) for c in table.columns])


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
    return problems
