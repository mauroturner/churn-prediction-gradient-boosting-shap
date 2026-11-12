# Diccionario de datos

Qué significa cada columna del libro de la fuente y para qué se usa, cómo se calcula cada una de las 16 variables del modelo y qué significa cada columna de cada tabla que el flujo exporta para Power BI, con su unidad. Las tres primeras partes se escribieron a mano a partir de `docs/research.md`, de `docs/requirements.md` (secciones 4 y 7), del plan (sección 10) y de `src/churnrisk/schema.py`, que es el único lugar del código que lista las columnas de la fuente y de las variables. La última parte la escribe `python -m churnrisk docs-sync` desde el modelo semántico (`src/churnrisk/dashboard/semantic_model.py`), la misma especificación contra la que el flujo comprueba cada Parquet antes de escribirlo; una prueba compara el bloque con lo que genera el comando y cada Parquet versionado con las columnas que lista (`tests/docs/test_docs.py`).

## Convenciones

- **Cliente y corte.** La unidad del modelo es el cliente con número en una fecha de corte (D05): la clave de una fila es (`cut_date`, `customer_id`), y vive solo en SQLite, en `data/interim/` y en `outputs/private/`, que no se versionan (D26). Ningún archivo publicado lleva el número de cliente.
- **Línea.** Una línea es una fila del libro después de quitar las copias del solapamiento entre las dos hojas; su clave es `line_id`, asignada en la lectura (la hoja por 10.000.000 más la fila de origen).
- **Montos.** En libras esterlinas (£), los del archivo, netos de anulaciones cuando se dice. Los costos del umbral están en unidades genéricas («u.»): lo que decide el umbral es su cociente (D22).
- **Tiempo.** `invoice_ts` es la fecha y hora local del archivo, sin zona; `invoice_date` es la fecha mínima de la factura. Un corte (`cut_date`) es el día 1 de un mes, y su ventana de etiqueta termina en `label_end = cut_date + N − 1`. La fecha de cálculo de una corrida (`as_of_date`) es el fin del día de su entrega. Las claves de fecha son enteros `AAAAMMDD` (`date_key`, `cut_key`, `as_of_key`).
- **Probabilidad y proporción.** Una probabilidad va de 0 a 1 (el riesgo, un umbral, un punto de equilibrio); una proporción es una parte de un total, también de 0 a 1 (una tasa de bajas, la parte contactada, la captura).
- **Memoria.** Toda cifra de memoria nombra su contador: `peak_working_set_mb` es el pico del conjunto de trabajo (`PeakWorkingSetSize` de `GetProcessMemoryInfo` en Windows; `ru_maxrss` de `resource.getrusage` en Linux) y `peak_commit_mb` el pico de memoria comprometida (`PeakPagefileUsage`, solo en Windows), en MB de 1.048.576 bytes (D39).
- **Vacíos.** Un valor que no existe queda nulo, no cero: un corte cuya ventana no cerró no tiene tasa de bajas, una regla sin probabilidad no tiene Brier, y una celda oculta por tener menos de 10 clientes tiene sus valores en nulo (D27, D86).

## Archivo de origen

`online_retail_ii.zip` (45.622.418 bytes, SHA-256 `572e36277c2390fbfde10664750731e0a86f55e33470d91919085f0408e67bfb`) con un solo miembro, `online_retail_II.xlsx` (45.622.278 bytes, SHA-256 `bcbe73b35f5b7babf197fb0cb983a11f5d9ff929078d4aa53d171b1f2df2e980`). El libro tiene dos hojas, `Year 2009-2010` (525.461 filas) y `Year 2010-2011` (541.910), cada una con estas 8 columnas en este orden; el flujo rechaza el libro si falta una hoja, si una columna falta, sobra o cambia de nombre o de lugar, o si un valor no se convierte a su tipo (V03-V05). El libro se trata como no confiable (RF03).

| Columna del libro | Nombre en el proyecto | Uso | Unidad | Significado |
| --- | --- | --- | --- | --- |
| `Invoice` | `invoice` | Agrupa las líneas de una factura; da el rol de la línea y la fecha mínima de la factura; solo en SQLite y en `data/interim/` | — | Número de factura. Las que empiezan con «C» son anulaciones; las que empiezan con «A» son ajustes de deuda y se apartan (D51). |
| `StockCode` | `stock_code` | Da `code_kind` (producto, vale de regalo o código de servicio, con `PADS` como servicio) y la clave del neteo LIFO por cliente y producto; cuenta los productos distintos | — | Código del producto: cinco cifras con hasta dos letras, o el prefijo `DCGS`; los demás son servicios como envíos, comisiones, ajustes o muestras (D03). |
| `Description` | `description` | Se guarda en la base canónica y en el almacén; no entra al modelo y se escapa en el HTML | — | Nombre del producto, texto libre. |
| `Quantity` | `quantity` | Rol de la línea (negativa en una anulación), neteo, unidades de las variables y V29 (5.000 unidades o más) | unidades | Unidades de la línea. |
| `InvoiceDate` | `invoice_ts` | Entrega de la línea, cortes, ventanas de las variables y de la etiqueta; `invoice_date` es su fecha mínima por factura | fecha y hora | Fecha y hora de la factura, sin zona horaria. |
| `Price` | `price` | Gasto de las variables y V24 (precio cero o negativo, se aparta) | £ por unidad | Precio unitario. |
| `Customer ID` | `customer_id` | La unidad del modelo; sin él la línea es de un invitado y se aparta (V20); nunca llega a un archivo publicado | — | Número de cliente de 5 cifras (V05). |
| `Country` | `country` | El país de la última línea anterior al corte (`country_group`, con los de menos de 10 clientes en «Otros») y V30-V31 | — | País del cliente en la línea; «Unspecified» va a «Otros» (V31). |

Recuentos de la corrida real (`outputs/site/validation_rules.json`, `totals`): 1.067.371 filas; 22.523 copias del solapamiento quitadas; 1.044.848 líneas; 235.287 sin número de cliente; 17.641 líneas de anulación.

## Variables

Las 16 variables de un cliente en un corte `c` (RF13, D12; plan, sección 10), calculadas solo con líneas y anulaciones con fecha anterior a `c` y con el neteo conocido en `c − 1`. Un día de compra es un día con al menos una compra neta del cliente. Ninguna mira la ventana de la etiqueta, el número de cliente ni el calendario (D09); una prueba de truncamiento y una de perturbación lo comprueban (AC12, AC13).

| Variable | Nombre | Unidad | Definición |
| --- | --- | --- | --- |
| `rec_days` | Días desde la última compra | días | Días entre el último día de compra neta y el corte. |
| `tenure_days` | Antigüedad | días | Días entre el primer día de compra neta y el corte. |
| `freq_total` | Días de compra | días de compra | Días con compra neta antes del corte. |
| `freq_90` | Compras en 90 días | días de compra | Días con compra neta en `[c − 90, c − 1]`. |
| `freq_365` | Compras en 365 días | días de compra | Días con compra neta en `[c − 365, c − 1]`; es también la regla B4. |
| `mon_total` | Gasto total | £ | Importe neto de todas las compras anteriores al corte. |
| `mon_90` | Gasto en 90 días | £ | Importe neto en `[c − 90, c − 1]`. |
| `mon_365` | Gasto en 365 días | £ | Importe neto en `[c − 365, c − 1]`. |
| `aov_day` | Gasto por día de compra | £ por día de compra | `mon_total / freq_total`. |
| `units_90` | Unidades en 90 días | unidades | Unidades netas compradas en `[c − 90, c − 1]`. |
| `gap_mean` | Tiempo medio entre compras | días | Media de los días entre días de compra consecutivos; 0 con un solo día de compra. |
| `gap_max` | Mayor tiempo entre compras | días | Máximo de los días entre días de compra consecutivos; 0 con un solo día de compra. |
| `n_products_365` | Productos distintos en 365 días | productos | Códigos de producto con compra neta en `[c − 365, c − 1]`. |
| `med_units_365` | Unidades medianas por línea | unidades por línea | Mediana de las unidades netas por línea en `[c − 365, c − 1]`. |
| `canc_365` | Anulaciones en 365 días | líneas | Líneas de anulación en `[c − 365, c − 1]`. |
| `canc_value_365` | Importe anulado en 365 días | £ | Importe absoluto de las anulaciones en `[c − 365, c − 1]`. |

Además, `country_group`: el país de la última línea anterior al corte, con los países de menos de 10 clientes en las filas de entrenamiento y «Unspecified» en «Otros» (13 grupos en la corrida real). Entra solo en el conjunto F2, como indicadores one-hot; el modelo elegido usa F1, las 16 de la tabla, sin el país (`reports/model_seal.json`, `launch.feature_set`).

## Tablas intermedias

No se versionan y nunca salen de la máquina que corre el flujo:

- `data/interim/source_lines.parquet`: la base canónica, una fila por línea, con `line_id`, `sheet`, `source_row`, las 8 columnas de la fuente con sus nombres del proyecto, `invoice_date`, `code_kind` e `is_repeated_line`, y un manifiesto de huellas escrito al final (`interim_manifest.json`).
- `data/raw/deliveries/`: las entregas publicadas por `deliver`, cada una en Parquet con su manifiesto (período, filas, SHA-256 y estado).
- `data/warehouse/churnrisk.sqlite`: el almacén, con las líneas cargadas (`raw_lines`), `stg_lines`, los cortes con sus variables y etiquetas (`cut_features`, `cut_labels`, de solo inserción), el registro de modelos, los puntajes y sus motivos (`model_scores`, `score_reasons`, de solo inserción), la evaluación, las corridas y los marts del modelo estrella.
- `data/interim/runs/<run_key>.json`: el estado de cada corrida, tarea por tarea, con sus tiempos, sus picos de memoria con el contador y, si falló, la traza.

## Tablas exportadas

Las 27 tablas del modelo semántico: 9 dimensiones y 18 hechos, de los que 26 se escriben en `outputs/powerbi/` con un manifiesto de huellas, y el hecho por cliente y corte en `outputs/private/`, que no se versiona. Las relaciones (18, todas de uno a varios, en un solo sentido) y las medidas DAX están en el diseño del tablero, `dashboard/powerbi-design.html`.

<!-- columns:start -->
### `dim_date`

Dimensión. Calendario del primero al último día de los datos. Se versiona en `outputs/powerbi/dim_date.parquet`. Clave: `date_key`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `date_key` | entero 32 | — | Fecha, como AAAAMMDD. |
| `date` | fecha | — | Fecha. |
| `year` | entero 32 | — | Año. |
| `month` | entero 32 | — | Mes (1-12). |
| `month_name_es` | texto | — | Nombre del mes. |
| `weekday` | entero 32 | — | Día de la semana (1 lunes, 7 domingo). |
| `weekday_es` | texto | — | Nombre del día. |

### `dim_cut`

Dimensión. Los cortes mensuales. Se versiona en `outputs/powerbi/dim_cut.parquet`. Clave: `cut_key`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `cut_key` | entero 32 | — | Corte, como AAAAMMDD. |
| `cut_date` | fecha | — | Fecha de corte (día 1 de un mes). |
| `label_end` | fecha | — | Último día de la ventana de la etiqueta (c + N − 1). |
| `block` | texto | — | Bloque de la partición. |
| `block_es` | texto | — | Bloque de la partición, en español. |
| `is_censored` | verdadero/falso | — | La ventana termina después de los datos: su etiqueta nunca se completa. |
| `active_customers` | entero 64 | clientes | Clientes activos en los M días anteriores al corte (la población). |
| `churn_rate` | decimal | proporción | Tasa de bajas del corte; nula hasta conocerla y, en la prueba, hasta el sello. |

### `dim_country`

Dimensión. Los grupos de país del lanzamiento. Se versiona en `outputs/powerbi/dim_country.parquet`. Clave: `country_key`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `country_key` | entero 32 | — | País. |
| `country_group` | texto | — | País o «Otros», con la lista fijada en el lanzamiento. |
| `country_es` | texto | — | País, en español. |
| `train_customers` | entero 64 | clientes | Clientes del país en las filas de entrenamiento. |

### `dim_risk_band`

Dimensión. Diez bandas fijas de riesgo de 0,1. Se versiona en `outputs/powerbi/dim_risk_band.parquet`. Clave: `band_key`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `band_key` | entero 32 | — | Banda de riesgo (1-10). |
| `band_es` | texto | — | Banda de riesgo, en texto. |
| `p_low` | decimal | probabilidad | Riesgo desde (incluido). |
| `p_high` | decimal | probabilidad | Riesgo hasta (excluido; la última incluye 1). |

### `dim_reason`

Dimensión. Las variables que pueden ser un motivo. Se versiona en `outputs/powerbi/dim_reason.parquet`. Clave: `reason_key`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `reason_key` | texto | — | Identificador de la variable. |
| `feature` | texto | — | Variable. |
| `feature_es` | texto | — | Variable, en español. |
| `description_es` | texto | — | Qué mide. |

### `dim_method`

Dimensión. El modelo y las líneas base. Se versiona en `outputs/powerbi/dim_method.parquet`. Clave: `method_key`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `method_key` | texto | — | Método: el modelo o una de las líneas base B0-B5. |
| `method_es` | texto | — | Método, en español. |
| `is_b_star` | verdadero/falso | — | Es la base más fuerte elegida en la validación (B*). |

### `dim_model`

Dimensión. El modelo congelado del lanzamiento. Se versiona en `outputs/powerbi/dim_model.parquet`. Clave: `model_version`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `model_version` | texto | — | Versión del modelo. |
| `feature_set` | texto | — | Conjunto de variables elegido en V1. |
| `params_es` | texto | — | Hiperparámetros del candidato elegido. |
| `calibration` | texto | — | Calibración (isotónica en V1). |
| `threshold` | decimal | probabilidad | Umbral de contacto elegido en V2. |
| `offer_cost` | decimal | u. | Costo de la oferta (supuesto). |
| `rescue_rate` | decimal | proporción | Tasa de rescate (supuesto). |
| `retained_value` | decimal | u. | Valor del cliente retenido (supuesto). |
| `break_even` | decimal | probabilidad | Punto de equilibrio: costo / (tasa × valor). |
| `b_star` | texto | — | Base más fuerte (B*). |
| `trained_as_of` | fecha | — | Fecha de cálculo del lanzamiento. |
| `config_sha256` | texto | — | Huella de la configuración sellada del modelo. |
| `seal_state` | texto | — | sealed (la configuración sellada) o post_seal (otra, posterior al sello). |

### `dim_pipeline_run`

Dimensión. Las corridas del flujo. Se versiona en `outputs/powerbi/dim_pipeline_run.parquet`. Clave: `run_key`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `run_key` | texto | — | Corrida. |
| `started_at` | texto | — | Inicio (UTC). |
| `finished_at` | texto | — | Fin (UTC). |
| `status` | texto | — | Estado. |
| `delivery_id` | texto | — | Entrega. |
| `as_of_date` | fecha | — | Fecha de cálculo. |
| `as_of_key` | entero 32 | — | Fecha de cálculo, como AAAAMMDD. |
| `lines_delivery` | entero 64 | líneas | Líneas de la entrega. |
| `customers_scored` | entero 64 | clientes | Clientes puntuados. |
| `contacts` | entero 64 | clientes | Contactos sugeridos. |
| `message` | texto | — | Mensaje. |

### `dim_as_of`

Dimensión. Tabla de parámetro de las fechas de cálculo, sin relaciones. Se versiona en `outputs/powerbi/dim_as_of.parquet`. Clave: `as_of_key`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `as_of_key` | entero 32 | — | Fecha de cálculo, como AAAAMMDD. |
| `as_of_date` | fecha | — | Fecha de cálculo. |
| `as_of_label` | texto | — | Fecha de cálculo, en texto. |

### `fact_cut_band`

Hecho. Clientes por corte y banda de riesgo. Se versiona en `outputs/powerbi/fact_cut_band.parquet`. Grano: `cut_key`, `band_key`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `cut_key` | entero 32 | — | Corte, como AAAAMMDD. |
| `band_key` | entero 32 | — | Banda de riesgo. |
| `customers` | entero 64 | clientes | Clientes puntuados. |
| `contacted` | entero 64 | clientes | Contactados. |
| `returned` | entero 64 | clientes | Volvieron a comprar hasta la última fecha de cálculo. |
| `churned` | entero 64 | clientes | Se fueron (con la ventana cerrada). |
| `expected_churners` | decimal | clientes | Bajas esperadas (Σ riesgo). |
| `suppressed` | verdadero/falso | — | Celda oculta: menos del mínimo de clientes, o la más chica de un desglose con una sola oculta. |

### `fact_cut_country`

Hecho. Clientes por corte y país. Se versiona en `outputs/powerbi/fact_cut_country.parquet`. Grano: `cut_key`, `country_key`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `cut_key` | entero 32 | — | Corte, como AAAAMMDD. |
| `country_key` | entero 32 | — | País. |
| `customers` | entero 64 | clientes | Clientes puntuados. |
| `contacted` | entero 64 | clientes | Contactados. |
| `churned` | entero 64 | clientes | Se fueron (con la ventana cerrada). |
| `suppressed` | verdadero/falso | — | Celda oculta, como en fact_cut_band. |

### `fact_reason_summary`

Hecho. Los motivos por corte (nulos con menos del mínimo de clientes o de contactados, y uno más donde se ocultaría uno solo). Se versiona en `outputs/powerbi/fact_reason_summary.parquet`. Grano: `cut_key`, `reason_key`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `cut_key` | entero 32 | — | Corte, como AAAAMMDD. |
| `reason_key` | texto | — | Variable. |
| `customers_top3` | entero 64 | clientes | Clientes con la variable entre sus motivos. |
| `contacted_top3` | entero 64 | clientes | Contactados con la variable entre sus motivos. |
| `mean_shap` | decimal | log-odds | Contribución media al log-odds de esos clientes. |

### `fact_tracking`

Hecho. El seguimiento de cada corte puntuado en cada fecha de cálculo. Se versiona en `outputs/powerbi/fact_tracking.parquet`. Grano: `as_of_key`, `cut_key`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `as_of_key` | entero 32 | — | Fecha de cálculo, como AAAAMMDD. |
| `cut_key` | entero 32 | — | Corte, como AAAAMMDD. |
| `scored` | entero 64 | clientes | Puntuados. |
| `contacted` | entero 64 | clientes | Contactados. |
| `returned` | entero 64 | clientes | Volvieron a comprar hasta la fecha de cálculo. |
| `window_closed` | verdadero/falso | — | La ventana cerró. |
| `churned` | entero 64 | clientes | Se fueron (nulo hasta que la ventana cierra). |
| `contacted_churned` | entero 64 | clientes | Contactados que se fueron. |
| `contacted_returned` | entero 64 | clientes | Contactados que volvieron. |
| `expected_churners` | decimal | clientes | Bajas esperadas (Σ riesgo). |
| `is_censored` | verdadero/falso | — | La ventana termina después de los datos. |

### `fact_method_metrics`

Hecho. Las métricas de cada método en V2 y en la prueba. Se versiona en `outputs/powerbi/fact_method_metrics.parquet`. Grano: `scope`, `method_key`, `seal_state`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `scope` | texto | — | Bloque evaluado: valid_v2 (validación V2) o test (prueba). |
| `method_key` | texto | — | Método: el modelo o una de las líneas base B0-B5. |
| `auc` | decimal | — | AUC. |
| `pr_auc` | decimal | — | PR-AUC. |
| `brier` | decimal | — | Brier. |
| `ece` | decimal | — | ECE de 10 intervalos. |
| `threshold` | decimal | — | Umbral elegido en V2. |
| `contact_share` | decimal | — | Proporción contactada. |
| `precision` | decimal | — | Precisión de los contactos. |
| `recall` | decimal | — | Recall de los contactos. |
| `capture_10` | decimal | — | Proporción de bajas en el 10 % de mayor riesgo. |
| `lift_10` | decimal | — | Lift en el 10 %. |
| `capture_20` | decimal | — | Proporción de bajas en el 20 %. |
| `lift_20` | decimal | — | Lift en el 20 %. |
| `nb_total` | decimal | u. | Beneficio neto total. |
| `nb_per_1000` | decimal | u. | Beneficio neto por cada 1.000 clientes. |
| `seal_state` | texto | — | sealed (la configuración sellada) o post_seal (otra, posterior al sello). |

### `fact_evaluation_summary`

Hecho. Los criterios C01-C10. Se versiona en `outputs/powerbi/fact_evaluation_summary.parquet`. Grano: `criterion_id`, `seal_state`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `criterion_id` | texto | — | Criterio C01-C10. |
| `name_es` | texto | — | Criterio. |
| `value` | decimal | — | Valor. |
| `baseline_value` | decimal | — | Valor de comparación. |
| `ci_low` | decimal | — | Límite inferior del intervalo del 95 %. |
| `ci_high` | decimal | — | Límite superior del intervalo del 95 %. |
| `threshold_es` | texto | — | Umbral del criterio. |
| `passed` | verdadero/falso | — | Se cumple (nulo en C10, informativo). |
| `seen_by_research` | texto | — | Lo vio la investigación antes de fijarlo. |
| `seen_by_planner` | texto | — | Lo vio el planificador antes de fijarlo. |
| `verdict_es` | texto | — | Veredicto. |
| `seal_state` | texto | — | sealed (la configuración sellada) o post_seal (otra, posterior al sello). |

### `fact_gain_curve`

Hecho. La curva de ganancia. Se versiona en `outputs/powerbi/fact_gain_curve.parquet`. Grano: `scope`, `method_key`, `point`, `seal_state`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `scope` | texto | — | Bloque evaluado: valid_v2 (validación V2) o test (prueba). |
| `method_key` | texto | — | Método: el modelo o una de las líneas base B0-B5. |
| `point` | entero 32 | — | Punto de la curva. |
| `share_contacted` | decimal | proporción | Proporción contactada. |
| `share_captured` | decimal | proporción | Proporción de bajas captadas. |
| `lift` | decimal | — | Lift. |
| `seal_state` | texto | — | sealed (la configuración sellada) o post_seal (otra, posterior al sello). |

### `fact_roc`

Hecho. La curva ROC. Se versiona en `outputs/powerbi/fact_roc.parquet`. Grano: `scope`, `method_key`, `point`, `seal_state`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `scope` | texto | — | Bloque evaluado: valid_v2 (validación V2) o test (prueba). |
| `method_key` | texto | — | Método: el modelo o una de las líneas base B0-B5. |
| `point` | entero 32 | — | Punto de la curva. |
| `fpr` | decimal | — | Tasa de falsos positivos. |
| `tpr` | decimal | — | Tasa de verdaderos positivos. |
| `seal_state` | texto | — | sealed (la configuración sellada) o post_seal (otra, posterior al sello). |

### `fact_calibration`

Hecho. La calibración por intervalo (nula con menos del mínimo de filas, y un intervalo más donde se ocultaría uno solo). Se versiona en `outputs/powerbi/fact_calibration.parquet`. Grano: `scope`, `method_key`, `point`, `seal_state`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `scope` | texto | — | Bloque evaluado: valid_v2 (validación V2) o test (prueba). |
| `method_key` | texto | — | Método: el modelo o una de las líneas base B0-B5. |
| `point` | entero 32 | — | Intervalo de probabilidad (1-10). |
| `p_mean` | decimal | probabilidad | Riesgo medio del intervalo. |
| `observed` | decimal | proporción | Tasa de bajas observada. |
| `rows` | entero 64 | filas | Filas del intervalo. |
| `seal_state` | texto | — | sealed (la configuración sellada) o post_seal (otra, posterior al sello). |

### `fact_cost_sensitivity`

Hecho. El beneficio neto según el punto de equilibrio, del modelo y de B*. Se versiona en `outputs/powerbi/fact_cost_sensitivity.parquet`. Grano: `scope`, `break_even`, `method_key`, `seal_state`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `scope` | texto | — | Bloque evaluado: valid_v2 (validación V2) o test (prueba). |
| `break_even` | decimal | probabilidad | Punto de equilibrio supuesto. |
| `method_key` | texto | — | Método: el modelo o una de las líneas base B0-B5. |
| `threshold` | decimal | probabilidad | Umbral elegido en V2. |
| `nb_per_1000` | decimal | u. | Beneficio neto por cada 1.000 clientes. |
| `contact_share` | decimal | proporción | Proporción contactada. |
| `seal_state` | texto | — | sealed (la configuración sellada) o post_seal (otra, posterior al sello). |

### `fact_sensitivity`

Hecho. Las sensibilidades de N, M y del corte de diciembre (informativas). Se versiona en `outputs/powerbi/fact_sensitivity.parquet`. Grano: `variant`, `method_key`, `seal_state`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `variant` | texto | — | Variante (n60, n120, m180, no_december). |
| `variant_es` | texto | — | Variante, en español. |
| `n` | entero 32 | — | N (días). |
| `m` | entero 32 | — | M (días). |
| `method_key` | texto | — | model, b2_rfm o b_star. |
| `auc` | decimal | — | AUC en su prueba. |
| `churn_rate` | decimal | proporción | Tasa de bajas de su prueba. |
| `rows` | entero 64 | filas | Filas de su prueba. |
| `diff_ci_low` | decimal | — | Límite inferior del intervalo de AUC(modelo) − AUC(método). |
| `diff_ci_high` | decimal | — | Límite superior del mismo intervalo. |
| `seal_state` | texto | — | sealed (la configuración sellada) o post_seal (otra, posterior al sello). |

### `fact_label_definition`

Hecho. La tasa de bajas del entrenamiento por N y M. Se versiona en `outputs/powerbi/fact_label_definition.parquet`. Grano: `n`, `m`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `n` | entero 32 | — | N (días). |
| `m` | entero 32 | — | M (días). |
| `churn_rate` | decimal | proporción | Tasa de bajas del entrenamiento. |
| `rows` | entero 64 | filas | Filas del entrenamiento. |

### `fact_silence_return`

Hecho. Los silencios que vuelven. Se versiona en `outputs/powerbi/fact_silence_return.parquet`. Grano: `n`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `n` | entero 32 | — | N (días). |
| `silences` | entero 64 | filas | Silencios de N días en el entrenamiento. |
| `return_share` | decimal | proporción | Proporción que vuelve a comprar en los N días siguientes. |

### `fact_importance`

Hecho. La importancia media de cada variable. Se versiona en `outputs/powerbi/fact_importance.parquet`. Grano: `scope`, `reason_key`, `seal_state`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `scope` | texto | — | Bloque evaluado: valid_v2 (validación V2) o test (prueba). |
| `reason_key` | texto | — | Variable. |
| `mean_abs_shap` | decimal | log-odds | Media de \|SHAP\|. |
| `seal_state` | texto | — | sealed (la configuración sellada) o post_seal (otra, posterior al sello). |

### `fact_selection`

Hecho. Los candidatos de la grilla y su pérdida en V1. Se versiona en `outputs/powerbi/fact_selection.parquet`. Grano: `feature_set`, `learning_rate`, `max_leaf_nodes`, `min_samples_leaf`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `feature_set` | texto | — | Conjunto de variables. |
| `learning_rate` | decimal | — | Tasa de aprendizaje. |
| `max_leaf_nodes` | entero 32 | — | Hojas. |
| `min_samples_leaf` | entero 32 | — | Muestras por hoja. |
| `log_loss_v1` | decimal | — | Pérdida logarítmica en V1. |
| `chosen` | verdadero/falso | — | Es el elegido. |

### `fact_leakage`

Hecho. La demostración de la fuga. Se versiona en `outputs/powerbi/fact_leakage.parquet`. Grano: `variable`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `variable` | texto | — | Conjunto. |
| `variable_es` | texto | — | Conjunto, en español. |
| `auc_valid_v2` | decimal | — | AUC en V2. |
| `note_es` | texto | — | Nota. |

### `fact_validation`

Hecho. Las reglas de validación de cada corrida. Se versiona en `outputs/powerbi/fact_validation.parquet`. Grano: `run_key`, `rule_id`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `run_key` | texto | — | Corrida. |
| `rule_id` | texto | — | Regla. |
| `name_es` | texto | — | Regla, en español. |
| `severity` | texto | — | Severidad. |
| `scope` | texto | — | Alcance. |
| `aggregation` | texto | — | Cómo se agrega entre corridas. |
| `status` | texto | — | pasa, falla, advierte o no evaluada. |
| `rows_affected` | entero 64 | filas | Filas afectadas. |
| `customers_affected` | entero 64 | clientes | Clientes afectados. |
| `value_gbp` | decimal | £ | Importe afectado. |

### `fact_customer_cut`

Hecho. Un cliente en un corte puntuado: la lista de riesgo. Privada: lleva el número de cliente y no se versiona (D26). Se escribe en `outputs/private/`, que no se versiona: es la única tabla con el número de cliente, para el `.pbix` armado en el equipo del dueño (D26). Grano: `customer_id`, `cut_key`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `customer_id` | entero 64 | — | Número de cliente (solo en la tabla privada). |
| `cut_key` | entero 32 | — | Corte, como AAAAMMDD. |
| `country_key` | entero 32 | — | País. |
| `band_key` | entero 32 | — | Banda de riesgo. |
| `rec_days` | entero 64 | días | Días desde la última compra. |
| `freq_365` | entero 64 | días | Días de compra en 365 días. |
| `mon_365` | decimal | £ | Gasto en 365 días. |
| `gap_mean` | decimal | días | Tiempo medio entre compras. |
| `risk` | decimal | probabilidad | Riesgo calibrado. |
| `is_contact` | verdadero/falso | — | Se contacta (riesgo ≥ umbral sellado). |
| `reason_1_es` | texto | — | Primer motivo. |
| `reason_2_es` | texto | — | Segundo motivo. |
| `reason_3_es` | texto | — | Tercer motivo. |
| `returned` | verdadero/falso | — | Volvió a comprar hasta la última fecha de cálculo. |
| `first_return_date` | fecha | — | Primer día de compra en la ventana. |
| `churned` | entero 64 | — | Se fue (nulo hasta que la ventana cierra). |
| `scored_as_of_date` | fecha | — | Fecha de cálculo de la puntuación. |
| `model_version` | texto | — | Versión del modelo. |
| `run_key` | texto | — | Corrida que puntuó. |
<!-- columns:end -->
