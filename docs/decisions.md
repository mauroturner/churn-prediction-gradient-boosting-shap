# Registro de decisiones

Una entrada por decisión, con sus siete campos: Contexto, Opciones, Decisión, Motivo, Afecta, Quién y Estado. Donde había un solo camino razonable, «Opciones» lo dice y explica por qué. Las propuestas del agente de planificación (Opus) quedan para revisión del dueño; las del dueño citan el registro del documento de seguimiento (`odd/tasks/portfolio-projects.md`). Las cifras salen de `research.md`, de los documentos de los proyectos 02 y 03 y de la comprobación del agente de planificación (`requirements.md`, sección 4), que leyó **solo los cortes de entrenamiento**: las líneas canónicas del proyecto 02 con un filtro de lectura `invoice_ts < 2011-03-01`, de modo que ninguna línea de una ventana de validación o de prueba entró en memoria; ninguna métrica se calculó en un corte de validación ni de prueba. Sus scripts y salidas quedaron fuera del repositorio, en `C:\Users\user\AppData\Local\Temp\tmp.RaIT4QRc6Y\` (`scripts/train_cuts.py`, `bg_compare.py`, `alive_q.py`; `out/*.out`, `out/train_cuts.json`).

Estados: **vigente**, **pendiente del dueño**, **reemplazada por Dxx**.

---

## D01 Enfoque: un clasificador frente a las reglas que usaría un gerente, con criterios que pueden no cumplirse y el resultado esperado dicho antes

- **Contexto**: el sitio promete un modelo de gradient boosting que da el riesgo de baja de cada cliente con sus motivos, evaluado por la ganancia que deja actuar (S9). research.md encontró que su primera mirada (AUC 0,769 en el primer corte de validación) no supera a RFM (0,784; diferencia −0,014, intervalo de −0,033 a 0,005), y el agente de planificación midió en el entrenamiento que la frecuencia sola (0,746) ordena mejor que RFM (0,737) y que BG/NBD (0,732). El modelo del proyecto 03 tampoco superó a su regla de dos variables (su D81).
- **Opciones**: (a) solo el modelo, informando su AUC; (b) el modelo frente a las reglas de un gerente (recencia, RFM, frecuencia, BG/NBD), con criterios fijados antes de construir que pueden no cumplirse, y lo esperable escrito antes de medir; (c) solo reglas, sin modelo.
- **Decisión**: (b). `HistGradientBoostingClassifier` frente a B0-B5 (D16) con los criterios C01-C10 de `requirements.md`, sección 8.1 (D18). Lo esperable queda escrito: el modelo probablemente no cumpla C02 ni C03.
- **Motivo**: un AUC sin una regla al lado no dice si el modelo suma algo; aquí la evidencia dice que puede no sumar nada sobre una regla de una variable, y esa comparación es el resultado. (a) repetiría el error de los tutoriales con AUC altos sin cortes (research.md, «Trabajos previos»); (c) dejaría afuera lo que el sitio promete, incluidos los motivos por cliente, que una regla no da.
- **Afecta**: todo el proyecto; `requirements.md`, sección 8.1; `fact_evaluation_summary`; el README; el sitio.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D02 Fuente: el zip de UCI con la huella del proyecto 02, extracción con lista blanca y la descarga endurecida del proyecto 03

- **Contexto**: research.md comprobó que el zip y el libro tienen las huellas que fijó el proyecto 02 (`572e3627…7bfb` y `bcbe73b3…e980`); UCI no da `ETag`, `Last-Modified` ni `Range` (proyecto 02, D02); el archivo es estático. El proyecto 02 extrajo el miembro con una lista blanca (su V02, D33). El proyecto 03 endureció la descarga con hosts permitidos en cada salto, un tope de segundos y de bytes (sus D41, D48 y D49).
- **Opciones**: (a) copiar el libro de la carpeta del proyecto 02; (b) descargar el zip una vez por HTTPS con la huella fijada, la extracción del proyecto 02 y la descarga del proyecto 03; (c) descargar cada mes.
- **Decisión**: (b). `accepted_sha256` del zip y `member_sha256` del libro fijados; `allowed_hosts = ["archive.ics.uci.edu"]`, a lo sumo 3 redirecciones, 64 MiB y 900 s; el miembro exacto, sin rutas, con tope descomprimido de 100 MiB. En modo `local`, la primera huella vista se registra. **[Verificar en U04]** si UCI redirige hoy y a qué host; un host nuevo es una decisión nueva.
- **Motivo**: cada proyecto se construye solo desde su fuente pública; (a) dependería de otra carpeta del portafolio. Hay un valor de confianza (la huella medida dos veces), así que la huella sí verifica; (c) bajaría 45 MB por mes para descubrir que no cambió.
- **Afecta**: `ingest.py`; `config/pipeline.toml [source]`; V01-V03; runbook R1, R2 y R11.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D03 Base canónica y roles de las líneas: las reglas del proyecto 02, las facturas «A» y `PADS`

- **Contexto**: las dos hojas se solapan con 22.523 copias exactas; hay 11.812 repeticiones internas; 22,5 % de las líneas no tiene cliente; hay códigos de servicio (`POST`, `DOT`, `M` y otros, 3.663 líneas con cliente), vales de regalo (100), 6 líneas de facturas «A» y `PADS` («PADS TO MATCH ALL CUSHIONS»), que el proyecto 02 trata como servicio (research.md; proyecto 02, D03 y D05). research.md dejó `PADS` y las facturas «A» como preguntas abiertas.
- **Opciones**: (a) las reglas del proyecto 02 tal cual; (b) esas más una regla propia para las facturas «A»; (c) revisar `PADS` como producto.
- **Decisión**: (b). Se quitan solo las copias de la hoja 2 en la ventana común, por multiconjunto (V06 bloquea si no son iguales); las repeticiones internas se conservan y se marcan; los roles siguen el orden de `classify_lines` del proyecto 02 y se suma `adjustment_invoice` para las «A» (V27; **[Verificar en U05]** si otra regla, por ejemplo la de servicio, ya las aparta antes); `PADS` sigue como servicio.
- **Motivo**: es la base que midieron research.md y el proyecto 02 (1.044.848 líneas), así que las cifras son comparables; una factura «A» no es una compra; cambiar `PADS` abriría una diferencia con el proyecto 02 por 19 líneas sin efecto medible en una baja.
- **Afecta**: `ingest.py`; `validate.py`; `stg_lines.sql`; V06, V20-V31.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D04 Anulaciones: el neteo LIFO del proyecto 02, conocido en cada fecha, y la diferencia de conteos con el proyecto 02

- **Contexto**: una anulación posterior a un corte baja una compra anterior y cambiaría la frecuencia y el gasto de ese corte (research.md, «Rasgos que podrían filtrar»). El proyecto 02 netea LIFO por cliente y producto (su D04) con las anulaciones conocidas en la fecha (su D40). research.md contó 16.426 pares anulación-compra y 1.706 líneas sin compra y no concilió con los 15.875 completos, 126 parciales y 1.585 sin compra del proyecto 02 (pregunta abierta 13).
- **Opciones**: (a) netear una vez con todas las anulaciones; (b) netear en cada fecha con lo conocido en ella: las variables de un corte con lo conocido en `c − 1` y la etiqueta con lo conocido en `c + N − 1`; (c) no netear.
- **Decisión**: (b), con `netting.py` copiado del proyecto 02. U06 cuenta con la definición del proyecto 02 (por anulación) sobre la misma base y exige sus números en una prueba `real_data` **[Verificar en U06]**; si difieren, se registra la causa en una decisión antes de seguir.
- **Motivo**: (a) es la fuga que research.md señaló; (c) deja ventas que no existieron (las líneas de 80.995 unidades anuladas a los 12 minutos). Los conteos de research.md y del proyecto 02 son de unidades distintas (pares contra anulaciones); contar igual los hace comparables.
- **Afecta**: `netting.py`; `cuts.py`; `features.py`; V21, V22; AC05, AC13.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D05 Unidad y momento de la predicción: el cliente con número, en una fecha de corte

- **Contexto**: el archivo no dice quién se fue; una línea sin número de cliente no se puede seguir en el tiempo (22,5 % de las líneas, 15,1 % del importe bruto positivo). Un mismo cliente aparece en varios cortes: de los 3.942 clientes de entrenamiento, 701 están en los siete cortes (comprobación del planificador).
- **Opciones**: (a) un cliente una vez, con un solo corte; (b) la fila cliente × corte, con los cortes apilados; (c) incluir a los invitados por sesión o por factura.
- **Decisión**: (b). La unidad es (`cut_date`, `customer_id`); los invitados quedan fuera y su peso se informa (I02); el número de cliente nunca es una variable.
- **Motivo**: (a) desperdicia la historia y deja la prueba con pocos clientes; (b) es lo que hace un equipo que mira la lista cada mes, y sus filas correlacionadas se tratan remuestreando clientes enteros (D21); (c) no tiene una baja definible.
- **Afecta**: `cuts.py`; `features.py`; `evaluation.py`; el texto del sitio (fila 11).
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D06 Etiqueta: ningún día de compra neta en los 90 días desde el corte, con su ruido dicho

- **Contexto**: research.md: la brecha mediana entre días de compra es de 31 días, el cuartil 75 de 68 y el percentil 90 de 134; con N = 90 la tasa de bajas del entrenamiento es 43,2 % (52,3 % con 60, 36,9 % con 120); el 39,2 % de los silencios de más de 90 días vuelve en los 90 siguientes (46,2 % con 60 y 33,4 % con 120); el sitio dice 90 días. La última ventana completa de un corte mensual con N = 90 empieza el 2011-09-01.
- **Opciones**: N = 60, 90, 120 o 180.
- **Decisión**: N = 90: `churned = 1` si el cliente no tiene ningún día de compra neta en `[c, c + 89]`, con el neteo conocido en `c + 89`. La etiqueta entra en el almacén recién cuando la fecha de cálculo alcanza el fin de la ventana. El ruido (39,2 %) se dice en la ficha, el tablero y el sitio. N = 60 y N = 120 van como sensibilidad (D10).
- **Motivo**: cae entre el cuartil 75 y el percentil 90 de las brechas, da una tasa utilizable, deja dos cortes de prueba completos y es lo que dice el sitio; 60 marca más falsas bajas (46 % vuelve) y 120 deja un solo corte de prueba. Ninguna N elimina el ruido; decirlo es lo honesto.
- **Afecta**: `cuts.py`; `config [label]`; `cut_labels`; `label.json`; la ficha del modelo; las filas 2 y 12 del sitio.
- **Quién**: agente de planificación; el dueño puede cambiarla antes de U29 (pendiente 2).
- **Estado**: vigente.

## D07 Población: los clientes activos en los 90 días anteriores al corte

- **Contexto**: research.md: con M = 90, 2.185 clientes por corte en promedio y 43,2 % de bajas; con M = 180, 2.934 y 48,3 %; los que callaron más de 90 días (1.202 en promedio) vuelven en el 32,3 % de los casos, un grupo de reactivación. El planificador midió las poblaciones de cada corte con M = 90 (de 1.925 a 2.859) y M = 180 (de 2.646 a 3.456).
- **Opciones**: M = 30, 60, 90, 180 o 365; atender a los inactivos con este modelo o con otro.
- **Decisión**: M = 90; los clientes con más de M días de silencio quedan fuera de la población y se cuentan (I06); M = 180 va como sensibilidad (D10); un modelo de reactivación queda fuera del alcance (pendiente 10).
- **Motivo**: es lo que un equipo de retención llama «activo» y el mismo horizonte que N; M = 180 mete clientes que ya llevan medio año sin comprar, que son otro problema (reactivar, no retener).
- **Afecta**: `cuts.py`; `config [label]`; I06; la ficha del modelo.
- **Quién**: agente de planificación; el dueño puede cambiarla antes de U29 (pendiente 2).
- **Estado**: vigente.

## D08 Cortes y partición: mensuales, siete de entrenamiento, tres de validación en V1 y V2, dos de prueba, purgas de N días

- **Contexto**: research.md propuso cortes del día 1 del 2010-06-01 al 2011-09-01, entrenamiento de 2010-06-01 a 2010-12-01 (7 cortes, 15.297 filas), validación de 2011-03-01 a 2011-05-01, prueba 2011-08-01 y 2011-09-01, y purgas de 90 días (`c_anterior + 90 ≤ c_siguiente`). El proyecto 03 partió su validación en V1 (elegir y calibrar) y V2 (umbral) para no elegir el umbral sobre las filas del calibrador (su D08).
- **Opciones**: (a) una sola validación; (b) V1 = 2011-03-01 y 2011-04-01, V2 = 2011-05-01; (c) V1 = 2011-03-01, V2 = 2011-04-01 y 2011-05-01; (d) cortes trimestrales.
- **Decisión**: (b). Bloques: `train` (7), `purge_1` (2011-01-01, 2011-02-01), `valid_v1` (2), `valid_v2` (1), `purge_2` (2011-06-01, 2011-07-01), `test` (2) y `post_test` (2011-10-01 a 2011-12-01, censurados, D44). Purgas comprobadas: 2010-12-01 + 90 = 2011-03-01 y 2011-05-01 + 90 = 2011-07-30 ≤ 2011-08-01. Sin purga entre V1 y V2.
- **Motivo**: la selección entre 24 candidatos y la calibración isotónica necesitan más filas que el umbral, así que V1 se lleva dos cortes; (a) elige el umbral donde se calibró; (d) deja cuatro cortes de entrenamiento. V1 y V2 son los dos validación: que sus ventanas se solapen hace al umbral algo optimista, no toca la prueba, y se dice.
- **Afecta**: `split.py`; `config [split]`; AC11; la ficha del modelo.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D09 Estacionalidad: sin variable de calendario, tasas por corte, el corte de diciembre adentro y lo esperable para la prueba

- **Contexto**: el planificador midió la tasa de bajas de cada corte de entrenamiento (N = 90, M = 90): 44,3 % (junio de 2010), 42,9 %, 35,9 % (agosto), 31,2 % (septiembre), 36,5 %, 46,3 % y 57,9 % (diciembre, que mira enero y febrero). La prueba mira de agosto a noviembre de 2011; la validación, de marzo a julio. Cada mes aparece una sola vez en el entrenamiento, y los de la validación (marzo a mayo) no aparecen.
- **Opciones**: (a) el mes del corte como variable; (b) sin variable de calendario, con las tasas y las métricas por corte informadas; (c) cambiar los cortes de prueba para que cubran un año (no hay datos: el último corte completo es el 2011-09-01); (d) sacar el corte de diciembre del entrenamiento.
- **Decisión**: (b), con el corte de diciembre adentro y su salida como sensibilidad (D10). Lo esperable, escrito antes de medir **[Inferido]**: un año antes, los cortes de agosto y septiembre tuvieron 35,9 % y 31,2 % de bajas, por debajo del 43,2 % del entrenamiento; un modelo calibrado en marzo y abril probablemente sobrestime el riesgo en la prueba y no cumpla C07.
- **Motivo**: (a) aprendería la tasa de un solo corte por mes y no tendría valor en los meses de la validación, que no vio; (c) no es posible con el archivo; (d) tiraría la única muestra de la temporada posterior a las fiestas sin una razón medida. Escribir la expectativa antes hace creíble un C07 fallido.
- **Afecta**: `features.py` (sin calendario); `eval_per_cut`; `label.json` (`rates_by_cut`); C07, C10; la ficha del modelo.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D10 Sensibilidad de N, M y del corte de diciembre, informada y nunca usada para elegir

- **Contexto**: research.md pidió sensibilidad a N = 60 y 120 y a M = 180. El planificador midió las tasas de entrenamiento de cada variante (requerimientos, sección 4). Con N = 120, el corte de diciembre pisa la validación (2010-12-01 + 120 > 2011-03-01) y el de prueba del 2011-09-01 terminaría el 2011-12-29, después de los datos.
- **Opciones**: (a) elegir N y M por el mejor resultado; (b) informar las variantes en la misma evaluación sellada, con el candidato sellado reajustado y recalibrado, sin elegir nada; (c) no hacerlas.
- **Decisión**: (b): `n60`, `n120`, `m180` y `no_december` (sección 17 del plan). Cada una conserva las fechas de corte y deja afuera las que no cumplen su purga; usa el mismo conjunto e hiperparámetros sellados, su propio entrenamiento y su V1 para calibrar; informa AUC del modelo, de B2 y de B*, la tasa y el intervalo (C10). Corre después de escrita la parte del lanzamiento del sello; una prueba estática exige que nada que elige lea sus tablas. Sus claves están en la huella.
- **Motivo**: (a) sería elegir la etiqueta mirando la prueba; (c) dejaría sin respuesta la pregunta de research.md. Reajustar con los hiperparámetros sellados mide cuánto depende el resultado de la definición sin abrir otra selección.
- **Afecta**: `sensitivity.py`; `config [sensitivity]`; `eval_variants`; `fact_sensitivity`; `algorithms.json` (`variants`); AC26; C10.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D11 Refresco mensual sobre un archivo estático: lanzamiento al 2011-07-31, cuatro entregas mensuales y un cierre; el corte es el día siguiente a la fecha de cálculo

- **Contexto**: el sitio dice «Cada mes un flujo mueve la fecha de corte…»; el archivo termina el 2011-12-09 (contradicción de research.md). El proyecto 02 replicó el mismo archivo como un lanzamiento al 2011-05-31 y siete entregas mensuales (su D07). Aquí, calibrar y elegir el umbral necesita las etiquetas de la validación, que se conocen el 2011-07-29.
- **Opciones**: (a) el calendario del proyecto 02; (b) un lanzamiento al 2011-07-31 con todo lo anterior, las entregas 2011-08 a 2011-11 y un cierre con los 9 días de diciembre, cada corrida puntuando el corte del día siguiente; (c) repetir el historial mes a mes desde 2010; (d) un corte fijo sin flujo.
- **Decisión**: (b). `L2011-07` (2009-12-01 a 2011-07-31) entrena, sella y puntúa el corte 2011-08-01; `M2011-08` a `M2011-11` puntúan del 2011-09-01 al 2011-12-01; `C2011-12` solo sigue; una séptima corrida termina `no_delivery`. Las líneas de una entrega son las de su fecha de factura, con sus anulaciones. La prueba se evalúa en `M2011-11` (fecha de cálculo 2011-11-30, después del 2011-11-29).
- **Motivo**: (a) lanzaría antes de conocer la validación; (c) obligaría a entrenar sin etiquetas o con datos futuros; (d) no muestra el producto. Con (b), la ausencia del futuro es física: en el lanzamiento, las líneas de las ventanas de prueba no están en el almacén. En una empresa, `deliver` se reemplaza por la exportación mensual del sistema de ventas con el mismo contrato.
- **Afecta**: `deliveries.py`; `config [deliveries]`; el DAG; `tracking.py`; AC06; la fila 7 del sitio.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D12 Variables: las 16 de la investigación y el país como indicadores, en tres conjuntos

- **Contexto**: research.md usó 25 columnas (16 numéricas y el país en 9 indicadores); por permutación, la frecuencia total (0,046), la brecha media (0,026) y la máxima (0,020) llevan la señal y el país suma muy poco; una variante con recencia y frecuencia de 365 días dio AUC 0,773 en el primer corte de validación. Las salidas de BG/NBD se ajustan con la historia anterior al 2010-12-01, que incluye las ventanas de los primeros cortes de entrenamiento.
- **Opciones**: (a) un solo conjunto; (b) tres anidados elegidos en V1: F0 (`rec_days`, `freq_365`), F1 (las 16) y F2 (F1 y el país); (c) sumar las compras esperadas de BG/NBD o el mes; (d) sumar el número de cliente o los productos como texto.
- **Decisión**: (b), con las definiciones del plan, sección 10; ni (c) ni (d).
- **Motivo**: elegir entre conjuntos anidados con una grilla fija es selección de modelo sin tocar la prueba, y F0 dice si dos columnas alcanzan. (c): BG/NBD como variable miraría, dentro del entrenamiento, la ventana de sus primeros cortes, y el mes no se puede aprender con un corte por mes (D09). (d): el número es un identificador (D26) y el producto como texto no tiene una razón medida.
- **Afecta**: `features.py`; `schema.py`; la selección; `algorithms.json` (`selection`).
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D13 Modelo: `HistGradientBoostingClassifier` de scikit-learn, no LightGBM; one-hot explícito y grilla fija

- **Contexto**: el sitio nombra LightGBM en Algoritmos y en Producto; el landing declara scikit-learn y no LightGBM (research.md, contradicción con el sitio). research.md usó `HistGradientBoostingClassifier` (300 iteraciones, 0,3 s sobre 15.297 filas). LightGBM calcula contribuciones SHAP de forma nativa (`pred_contrib`), lo que evitaría el paquete `shap`, pero ninguna medición de este portafolio lo probó y suma una tecnología fuera del landing.
- **Opciones**: (a) LightGBM, anotándolo en `LANDING-EXPANSION.md`; (b) scikit-learn con `shap`; (c) XGBoost; (d) regresión logística.
- **Decisión**: (b): `HistGradientBoostingClassifier` con `OneHotEncoder` explícito del país y **sin `categorical_features`**, grilla de tasa 0,05 o 0,1, 15 o 31 hojas y 50 o 200 muestras por hoja, L2 1,0, 300 iteraciones, sin parada temprana, `random_state = 0`. La contradicción con el sitio se resuelve cambiando el sitio (fila 4).
- **Motivo**: scikit-learn está en el landing y research.md comprobó con él la aditividad de SHAP; (a) cambiaría una dependencia probada por una no probada para ahorrar otra, y no hay un motivo de rendimiento (15 mil filas); (d) necesitaría escribir a mano las interacciones. La parada temprana usaría una partición aleatoria dentro del entrenamiento, que rompe el orden en el tiempo.
- **Afecta**: `model.py`; `config [model]`; `SITE-UPDATES.md` (fila 4).
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D14 Selección y calibración en V1, umbral en V2 y la base más fuerte elegida en la validación

- **Contexto**: el umbral por costo necesita probabilidades (D22); scikit-learn 1.9.1 trae `FrozenEstimator` (proyecto 03, D13). Las bases (RFM, BG/NBD, frecuencia) dan puntajes, no probabilidades. Cuál es la base más fuerte no está claro: en el entrenamiento, B4 0,746, B2 0,737 y B3 0,732; en el primer corte de validación (research.md), B2 0,784 y B3 0,776, y B4 no se midió.
- **Opciones**: elegir por AUC, pérdida logarítmica o beneficio neto; calibrar o no; fijar la base a superar ahora (RFM) o elegirla en la validación.
- **Decisión**: se elige el modelo por la pérdida logarítmica en V1 sin calibrar y se calibra con isotónica en V1; cada base se convierte en probabilidad con isotónica en V1; el umbral de cada método sale de V2. **B*** es la de mayor AUC en toda la validación entre B4, B2 y B3; en un empate a 10⁻⁶, la primera de esa lista (la más simple); se sella. C01 y C02 comparan siempre con RFM, que es la regla del sitio y de la investigación.
- **Motivo**: la pérdida logarítmica premia la probabilidad, que es lo que usa el umbral; calibrar las bases con el mismo procedimiento hace justa la comparación por costo. Elegir B* en la validación es lo que haría un gerente con los datos a mano, sin mirar la prueba; fijarla hoy sería elegir con un solo corte de la investigación o con el entrenamiento.
- **Afecta**: `model.py`; `baselines.py`; `threshold.py`; el sello; C03, C04, C05, C08, C09.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D15 Explicaciones con SHAP: aditivas por construcción, comprobadas en cada fila, con una dependencia nueva

- **Contexto**: el sitio promete los motivos de cada cliente. research.md comprobó con `shap` 0.51.0 (`TreeExplainer`, `tree_path_dependent`) y scikit-learn 1.9.1 que la suma de SHAP y el valor base reproduce el log-odds con error 8,4·10⁻¹⁵ con el país en one-hot, y con error 3,6 con las divisiones categóricas nativas; 1,0 s para 1.677 filas. `shap` no está en el landing ni en `LANDING-EXPANSION.md` y trae numba 0.68.1.
- **Opciones**: (a) `shap` sobre el log-odds del modelo sin calibrar, con la aditividad comprobada en cada fila; (b) importancia por permutación, que no da motivos por cliente; (c) una implementación propia de TreeSHAP; (d) LightGBM nativo (D13).
- **Decisión**: (a). M06 falla la tarea si una fila no cumple `shap_additivity_tol` (10⁻⁶); `refuse_native_categorical` rechaza una canalización con divisiones categóricas nativas antes de explicar; se guardan los tres motivos de mayor contribución hacia el riesgo; la importancia publicada es la media de |SHAP| (el país, sumado). SHAP explica el log-odds sin calibrar: la isotónica es monótona y no cambia el orden, pero los motivos no suman la probabilidad calibrada, y la ficha lo dice.
- **Motivo**: es lo único verificado que da motivos exactos por cliente; comprobar la aditividad en cada fila convierte la condición de research.md en una guarda y no en una convención. (c) es otro proyecto; (b) no cumple la promesa del sitio.
- **Afecta**: `explain.py`; `score_reasons`; `requirements.txt`; `LANDING-EXPANSION.md` (D37); AC18; la fila 5 del sitio.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D16 Líneas base B0-B5

- **Contexto**: research.md midió recencia, RFM, BG/NBD P(vivo) y BG/NBD compras esperadas; el planificador sumó la frecuencia de 365 días, la más fuerte del entrenamiento (0,746), y midió que P(vivo) satura (el 93,4 % de los activos de 2010-12-01 en 0,996 o más; AUC 0,362).
- **Opciones**: (a) solo RFM; (b) las de research.md; (c) esas más la frecuencia y contactar a todos.
- **Decisión**: (c): B0 contactar a todos (y no contactar a nadie, BN = 0), B1 recencia, B2 RFM (quintiles por rango medio del proyecto 02, D09), B3 BG/NBD compras esperadas en N días, B4 frecuencia de 365 días y B5 1 − P(vivo), informativa. Todas con parámetros del entrenamiento y probabilidades por isotónica en V1 (D14).
- **Motivo**: el modelo tiene que enfrentar la mejor regla simple conocida antes de mirar la prueba, no una débil elegida para perder; B4 es lo que vio el planificador. B1 prueba la afirmación del sitio de que la recencia es la variable principal (en el entrenamiento ordena poco: 0,594). B5 muestra por qué P(vivo), que pidió la idea del proyecto, no sirve en una población activa.
- **Afecta**: `baselines.py`; `config [baselines]`; C01-C10; `algorithms.json` (`methods`).
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D17 BG/NBD con SciPy, reutilizado del proyecto 02 y comprobado sobre el entrenamiento contra `lifetimes`

- **Contexto**: `lifetimes` no tiene mantenimiento desde 2020 (proyecto 02, D13); el proyecto 02 implementó BG/NBD con SciPy desde las fórmulas publicadas y lo comprobó contra el artículo y contra `lifetimes` (sus D13 y D42). El planificador ajustó, con la historia anterior al 2010-12-01 (4.229 clientes), `lifetimes` (r = 0,9084, α = 75,76, a = 0,1737, b = 108,27: los de research.md; log-verosimilitud −59.505,3607) y el código del proyecto 02 (r = 0,9091, α = 75,83, a = 0,1717, b = 105,91; −59.505,3611; 0,34 s): b difiere un 2,2 %, pero las compras esperadas en 90 días de los 2.859 activos del corte difieren a lo sumo en 0,0045 (0,069 % relativo) y su orden tiene una correlación de Spearman de 0,9999996.
- **Opciones**: (a) `lifetimes` en producción; (b) el código del proyecto 02 copiado, con `lifetimes` solo como oráculo de las pruebas; (c) importar el paquete del proyecto 02.
- **Decisión**: (b), sin Gamma-Gamma ni el valor de vida (V es un supuesto constante, D22). Ajuste una vez, en el lanzamiento, con `bgnbd_fit_cut = 2010-12-01` y los parámetros fijos para todos los cortes; M08 si no converge; `lifetimes` 0.11.3 en `requirements-dev.txt` con la marca `oracle`.
- **Motivo**: «reutilizar si sirve»: sirve, medido sobre este mismo problema; la diferencia en b es una dirección casi plana de la verosimilitud (lo que describe la D42 del proyecto 02) y no cambia el puntaje que se usa. (a) pondría en producción una librería sin mantenimiento; (c) acoplaría dos proyectos que se publican por separado.
- **Afecta**: `bgnbd.py`; `requirements-dev.txt`; `tests/unit/test_bgnbd.py`; `LANDING-EXPANSION.md` (la fila de `lifetimes` suma el 04).
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D18 Criterios C01-C10 y lo que se vio antes de fijarlos

- **Contexto**: research.md vio, en el primer corte de validación, el AUC del modelo y de las bases, la diferencia con RFM y su intervalo, y la captura del 10 %. El planificador vio solo el entrenamiento (tasas, AUC de las bases sin modelo, BG/NBD) y no calculó nada en la validación ni en la prueba. Fijar umbrales después de ver números podría ajustarlos a ellos.
- **Opciones**: (a) solo criterios no vistos; (b) los criterios naturales, diciendo cuáles se vieron y quién, más criterios no vistos; (c) sin umbrales.
- **Decisión**: (b): C01-C10 (`requirements.md`, sección 8.1) con dos columnas sobre lo visto, umbrales naturales («mayor que», un intervalo por encima de 0, ECE 0,03 y sesgo 0,02, los del proyecto 03) y plantillas de veredicto que dicen «no supera». La expectativa queda escrita antes de medir: probablemente no se cumplan C02, C03 ni C07, C01 y C04 queden cerca de un empate y C06 se cumpla.
- **Motivo**: (a) dejaría fuera la pregunta principal (¿el modelo le gana a RFM?) porque alguien la miró; (c) permitiría leer cualquier resultado como bueno. Escribir lo esperado antes es lo que hace creíble un «no supera», como en el proyecto 03 (su D16 y su D81).
- **Afecta**: `config [criteria]`; `evaluation.py`; `reporting.py`; el README; la ficha; el tablero; el sitio (fila 16).
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D19 La prueba se toca una vez: modelo congelado y sello con una huella que cubre cada clave que cambia un valor sellado

- **Contexto**: el proyecto 03 congeló el modelo y escribió un sello de una sola escritura (su D17), pero su huella cubría solo los costos, y otra `sensitivity_step`, `threshold_min` o `bootstrap_seed` se tomaba como la configuración sellada y fallaba (su B4, corregido en su D89 con una lista de claves fuera de la huella).
- **Opciones**: (a) la huella del proyecto 03 y la corrección de su D89; (b) desde el principio, una huella sobre una vista sellada que incluye todas las claves que pueden cambiar un valor sellado, y los cálculos sellados que solo reciben esa vista; (c) solo la historia de Git.
- **Decisión**: (b). `config.py` declara `FINGERPRINT_KEYS` y `UNSEALED_KEYS`, y una prueba exige que cada hoja de la configuración esté en exactamente una; `SealedConfig` tiene solo las de la huella y la huella observada del zip; `config_sha256` es su SHA-256 canónico y el sello guarda la vista entera para nombrar las diferencias; una prueba estática exige que los módulos de cálculo no reciban `PipelineConfig`. El sello tiene la parte del lanzamiento y la de la prueba, cada una escrita una vez (creación exclusiva o enlace duro); con la misma huella, una repetición debe reproducir (si no, `SealMismatchError` con los valores); con otra, todo es `post_seal` y el sellado se conserva. Ninguna persona ni prueba calcula una métrica en la prueba real antes de U29.
- **Motivo**: incluir de más solo hace `post_seal` una corrida con un cambio cosmético; incluir de menos es el defecto B4. Que la vista sellada sea el único camino de una clave a un valor sellado lo hace estructural, no una lista que hay que acordarse de mantener. Sin un tercer caso («difiere solo donde actúan claves fuera de la huella»), el sello es más simple que el del proyecto 03.
- **Afecta**: `config.py`; `registry.py`; las tareas `fit_model` y `evaluate`; `reports/model_seal.json`; AC21; runbook R7, R10 y R13.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D20 Después del sello, el resumen toma del sello lo que el almacén no tiene

- **Contexto**: en el proyecto 03, después del sello, una corrida con otros costos (el camino que su propio README sugería) escribía un resumen que decía pendiente la prueba sellada (su B3, corregido en su D88). Sus revisiones dejaron dos ramas sin prueba (`R3-seal-mismatch-untested`, `R3-pending-why-branch-untested`) y un rango de C09 fijo en el código (`R3-c09-range-hardcoded`).
- **Opciones**: (a) recalcular siempre desde el almacén; (b) tomar del sello los criterios y las cifras selladas cuando el almacén no tiene las filas selladas, comprobando cada una contra su entrada, y mostrar debajo lo posterior al sello.
- **Decisión**: (b), desde el diseño: `load_summary` y `criteria_from_seal` comparten `_criteria_of` con `evaluate_criteria`; cada criterio reconstruido debe devolver su entrada a 6 decimales o el sello no se toma (`SealError`); el rango de C09 sale de la vista sellada; las tres ramas (del sello, que no reconstruye y pendiente con su motivo) tienen prueba propia.
- **Motivo**: un almacén reconstruido no tiene las filas selladas, pero el resultado sellado sigue siendo el del proyecto; (a) lo borraría del resumen. Comprobar cada entrada evita publicar un sello que el código ya no sabe rehacer.
- **Afecta**: `reporting.py`; `evaluation.py`; `summary.json` (`sealed_from`); AC22.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D21 Intervalos por remuestreo pareado de clientes

- **Contexto**: un cliente puede estar en los dos cortes de prueba; en el entrenamiento, 701 de 3.942 clientes están en los siete cortes. research.md remuestreó filas de un solo corte (intervalo de la diferencia con RFM de −0,033 a 0,005 con 1.677 clientes).
- **Opciones**: (a) remuestrear filas; (b) remuestrear clientes con todas sus filas; (c) DeLong.
- **Decisión**: (b): 1.000 remuestras, semilla 0, los mismos clientes para los dos puntajes, percentiles 2,5 y 97,5 de la diferencia; las remuestras con una sola clase se descartan y se cuentan.
- **Motivo**: con filas del mismo cliente en dos cortes, (a) trataría como independiente lo que no lo es y daría un intervalo demasiado angosto; (c) supone independencia y no sirve para el beneficio neto. (b) usa NumPy y es determinista con la semilla.
- **Afecta**: `evaluation.py`; C02, C03, C10; AC25.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D22 Costos supuestos, umbral por beneficio neto, curva de ganancia y sensibilidad

- **Contexto**: no hay una fuente pública defendible del costo de una oferta de retención ni del valor de un cliente retenido (research.md); Verbeke y otros (2012, DOI 10.1016/j.ejor.2011.09.031) proponen evaluar por el beneficio de contactar a la fracción óptima. El ejemplo ilustrativo de research.md (2, 0,2 y 60) da un punto de equilibrio de 0,17, por debajo de casi todas las tasas de bajas por corte (31,2 % a 57,9 %): contactaría a casi todos. El proyecto 03 eligió un punto de equilibrio neutro de 0,5 (su D14). El sitio promete un panel con el costo de la oferta, la tasa de rescate y el margen.
- **Opciones**: (a) los valores ilustrativos de research.md; (b) valores neutros con punto de equilibrio 0,5 (`offer_cost = 5`, `rescue_rate = 0,2`, `retained_value = 50` u.) y la sensibilidad de 0,10 a 0,90; (c) un valor por cliente (margen × gasto de los 365 días); (d) solo un k % fijo.
- **Decisión**: (b). El BN de un contactado es `churned × r × V − c_oferta`; el umbral maximiza el BN en V2 (grilla de 0,01 a 0,99, empate al mayor); la curva de ganancia, el lift y la captura al 10 % y al 20 % se informan; la sensibilidad repite la elección en 17 puntos de equilibrio para el modelo y B*. Todo se fija antes de la prueba y está en la huella. El tablero mueve los tres supuestos con parámetros de hipótesis. Ningún texto dice que los costos son reales.
- **Motivo**: con (a) la decisión es trivial y ningún orden ayuda; 0,5 dice «contactar cuando es más probable que se vaya que que se quede, con una oferta que cuesta la mitad de lo que rescata en promedio», una elección sin fuente que se declara. (c) haría que los clientes de mayor gasto (mayoristas: 7,4 % de los clientes y 29,5 % del importe, research.md) dominen la lista y mezclaría la comparación con las bases; (d) ignora los costos. «Margen» pasa a «valor de un cliente retenido» en el sitio (fila 8), porque el archivo no trae márgenes.
- **Afecta**: `threshold.py`; `config [costs]`; C05, C06, C09; el tablero (página 2); `algorithms.json`; el pendiente 1 del dueño.
- **Quién**: agente de planificación; el dueño puede cambiar los valores antes de U29; después, un cambio es posterior al sello (D19).
- **Estado**: vigente.

## D23 Validación: qué bloquea, qué se aparta y qué se informa; las reglas acumuladas se leen una vez

- **Contexto**: el proyecto 02 dejó una tabla de reglas para este mismo archivo (V01-V22, I01-I03). En el proyecto 03, `validation_rules.json` sumó sobre las quince corridas dos reglas que ya acumulaban los meses anteriores (66.761 alertas donde había 8.840; su D94).
- **Opciones**: (a) bloquear ante cualquier anomalía; (b) bloquear lo que rompe la estructura, la serie de entregas o el modelo, apartar y contar el resto, y declarar en cada regla cómo se agrega entre corridas.
- **Decisión**: (b), con la tabla del plan, sección 6: cada regla tiene `aggregation` (`source`, `per_run` o `latest`), y una prueba exige que la declare y que la exportación la respete.
- **Motivo**: una línea sin cliente o una anulación son normales en el negocio; un solapamiento distinto, una entrega fuera de orden o un SHAP que no suma tienen que frenar todo. Que la forma de agregar sea un dato de la regla, y no una lista aparte en el exportador, evita repetir el defecto de la D94 cuando aparezca una regla nueva.
- **Afecta**: `validate.py`; `site_export.py`; `fact_validation`; `validation_rules.json`; AC07, AC29.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D24 Almacén: SQLite en capas, el neteo en Python y dos flujos (lo anterior al corte y la ventana)

- **Contexto**: los proyectos 01 a 03 usaron SQLite con SQL en capas como el reemplazo local de dbt con BigQuery (`LANDING-EXPANSION.md`), probado en el contenedor de Airflow; el proyecto 02 neteó en Python dentro de la transacción de carga (su D20).
- **Opciones**: (a) SQLite como los proyectos anteriores, con tablas separadas para las variables de cada corte y para las etiquetas de cada ventana; (b) DuckDB; (c) dbt con BigQuery; (d) calcular los cortes en memoria sin guardarlos.
- **Decisión**: (a): `raw → stg → cortes → marts`; `cut_features` y `cut_labels` de solo inserción, la segunda escrita solo cuando la ventana cerró; `mart_labelled_rows` es la única fuente de etiquetas del modelo; controles que devuelven las filas que violan.
- **Motivo**: un millón de líneas le sobra a SQLite; (c) necesita credenciales que serían del dueño; (b) suma una tecnología. Guardar los cortes deja auditables las variables de cada fecha y hace estructural la separación entre lo anterior y lo posterior, como los dos flujos del proyecto 03 (su D09); (d) perdería eso.
- **Afecta**: `warehouse.py`; `sql/**`; `cuts.py`.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D25 Salidas para Power BI y diseño del tablero con el panel de supuestos

- **Contexto**: S4 pide el diseño del tablero en HTML donde Power BI necesita la interfaz. Los proyectos 01 a 03 generaron el HTML y los esquemas de los Parquet desde una sola especificación. El sitio promete la lista de clientes en riesgo, la curva de ganancia y un panel con los supuestos.
- **Opciones**: (a) el modelo estrella del plan, sección 19, con los hechos agregados versionados, el hecho por cliente fuera de lo versionado y parámetros de hipótesis para los supuestos; (b) un hecho por cliente y fecha de cálculo, versionado; (c) un HTML a mano.
- **Decisión**: (a): 9 dimensiones, 17 hechos versionados, 1 privado, 18 relaciones 1:* de filtro unidireccional y activas, cinco páginas, generados desde `dashboard/semantic_model.py`; los parámetros `Costo de la oferta`, `Tasa de rescate` y `Valor del cliente retenido` se crean en Power BI y el HTML lo explica.
- **Motivo**: ya probado y verificable con pruebas (relaciones 1:* de filtro unidireccional, como pidió el dueño en S2). (b) publicaría la lista con números de cliente (D26); (c) no se puede comprobar contra los Parquet.
- **Afecta**: `export.py`; `dashboard/**`; `docs/data-dictionary.md`; AC27, AC28.
- **Quién**: dueño (S4) y agente de planificación (forma).
- **Estado**: vigente.

## D26 Identificadores: el número de cliente nunca sale del almacén ni de una tabla no versionada

- **Contexto**: `Customer ID` es un seudónimo de cuenta (research.md); research.md dice que la lista de clientes en riesgo con su número no se publica en ninguna forma. El proyecto 03 publicó el número de pedido en sus Parquet (su D32, pendiente del dueño), y su captura del tablero para el sitio mostró nueve números de pedido que hubo que enmascarar después (L43).
- **Opciones**: (a) el número en los Parquet versionados, como el proyecto 03; (b) una clave propia en lo versionado (se reconstruye ordenando igual el archivo público, como dice la D32 del proyecto 03); (c) el número solo en SQLite, `data/interim/` y un hecho en `outputs/private/` sin versionar, y nada que lo lleve en lo publicado.
- **Decisión**: (c). El HTML recibe la lista con la columna enmascarada («•••••»); los JSON, las figuras, los reportes versionados, los registros y los estados de corrida no tienen el número; los ejemplos de las reglas llevan solo `line_id`. Los números del accesorio son de un rango propio (desde 90001) para que una búsqueda en bytes los encuentre en cualquier salida versionada (AC42).
- **Motivo**: un dato que no se publica no se filtra, y una captura del HTML no puede mostrar lo que el HTML no tiene; (a) contradice la regla de research.md; (b) no protege nada frente a quien tenga la fuente. La lista sigue sirviendo a quien corre el flujo, porque `outputs/private/` se genera en su equipo.
- **Afecta**: `export.py`; `site_export.py`; `dashboard/render.py`; `validate.py`; `.gitignore`; AC27-AC29, AC42; el pendiente 3 del dueño.
- **Quién**: agente de planificación; el dueño puede pedir (a) (pendiente 3).
- **Estado**: vigente.

## D27 Tamaño mínimo de celda y ejemplos que no señalan a un cliente

- **Contexto**: research.md propuso que ninguna celda publicada tenga menos de 10 clientes y que los 24 países con menos de 10 clientes se publiquen como «Otros». La revisión de U20 del proyecto 03 encontró un ejemplo cuya combinación de detalles señalaba un pedido y celdas ocultas que salían por resta (su D77).
- **Opciones**: (a) solo la regla del mínimo; (b) el mínimo con supresión secundaria y la regla de los ejemplos del proyecto 03; (c) no publicar ejemplos.
- **Decisión**: (b): `min_cell_customers = 10`; los países con menos de 10 clientes del entrenamiento, y «Unspecified», van a «Otros»; supresión secundaria en cada desglose cuyo total se publica; un ejemplo por quintil de riesgo del último corte de prueba, con sus detalles publicados en un orden fijo mientras al menos 10 clientes del corte los compartan, y nunca su número, su país, sus valores exactos ni sus SHAP.
- **Motivo**: un ejemplo con todos sus detalles se puede buscar en el archivo público; el sitio no debe ser lo que lo encuentra. (c) dejaría al sitio sin la promesa de «los motivos de ese cliente».
- **Afecta**: `site_export.py`; `features.py` (`country_group`); `dashboard/render.py`; AC29.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D28 Exportación para el sitio, con manifiesto

- **Contexto**: la página se arma con la estructura del proyecto 01 (S10). El proyecto 03 generó cinco JSON con un contrato y, desde su H5, un `manifest.json` escrito al final que el sitio verifica (su D77).
- **Opciones**: (a) exportar a mano después; (b) cinco JSON adaptados al problema y el manifiesto.
- **Decisión**: (b): `summary.json`, `validation_rules.json`, `label.json`, `algorithms.json` y `retention.json`, con el contrato exacto del plan, sección 21, ≤ 200 KB sin el manifiesto; `read_site` y `verify_site` comprueban el conjunto.
- **Motivo**: lo que muestra el sitio sale de la misma corrida que el README y el tablero, y una prueba lo compara. La definición de la baja es la historia de la sección de datos de este dataset y merece su archivo (`label.json`). Es un contrato que consume otro repositorio: cambiarlo después es de riesgo alto (ítem 3).
- **Afecta**: `site_export.py`; `outputs/site/*`; marca-personal.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D29 Orquestación: Airflow 3.4.0 en Docker con todos los secretos del entorno, y la CLI

- **Contexto**: el proyecto 03 dejó un compose con cada secreto desde el entorno, incluida la contraseña de la base de metadatos (su D23), complementos de solo lectura y configuración escribible (su D80), y una inicialización con `set -e` tras la corrección de su revisión de U23 (L36).
- **Opciones**: (a) copiar el compose del proyecto 02; (b) copiar el corregido del proyecto 03 y adaptarlo; (c) un diseño nuevo.
- **Decisión**: (b): DAG `churnrisk_monthly` (`0 6 2 * *`, sin catchup, una corrida y una tarea activas); las claves del proyecto 03 con el prefijo `CHURNRISK_` y `${…:?}` en todos sus usos; `init.sh` con `set -e`; la prueba de Docker corre `pip check` (con `shap` y `numba`) y dos `airflow dags test`. **[Verificar en U27]** que `numba` 0.68.1 instala en la imagen (Python 3.13.18).
- **Motivo**: es el compose que ya pasó dos evaluaciones y sus revisiones; (a) traería la contraseña literal que el proyecto 02 dejó pendiente (su D68); (c) repetiría trabajo.
- **Afecta**: `airflow/**`; AC35, AC36; runbook R8.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D30 Estado de la corrida, cierre en orden y rechazos, con las correcciones del proyecto 03

- **Contexto**: la evaluación del proyecto 03 encontró tareas que corrían sobre una corrida que nunca cargó su entrega (su B1, D86), y su comprobación, un `load` que cargaba sin validación o una entrega rechazada (su D93); antes, el proyecto 02 había encontrado una corrida cerrada que se reabría (su B1) y un manejador de fallas que tapaba el error (su A5).
- **Opciones**: solo había un camino razonable: empezar del diseño ya corregido del proyecto 03; empezar de uno anterior repetiría defectos ya encontrados.
- **Decisión**: el plan, sección 22: estado por corrida; cierre en el orden de la sección 3; manejador de fallas con cada escritura protegida; rechazos antes de escribir de una corrida cerrada, de una segunda entrega, de `load` sobre una entrega cargada por otra corrida o sin una validación aprobada de esta, de toda tarea posterior a `load` si esta corrida no cargó su entrega y de las tareas del modelo sobre una entrega que no es la última; `_close_sqlite` nunca crea la fila de una corrida.
- **Motivo**: cada regla cierra un defecto encontrado, y empezar con ellas cuesta menos que agregarlas después de una evaluación.
- **Afecta**: `pipeline.py`; `cli.py`; el DAG; AC30, AC31.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D31 Un solo escritor: el bloqueo del proyecto 03 con sus correcciones, desde el diseño

- **Contexto**: el proyecto 03 agregó en su H9 un bloqueo con `O_EXCL` (su D82). Su evaluación encontró que en Windows soltarlo levantaba `PermissionError` 32 mientras otro proceso tenía el archivo abierto (su B2); la corrección (su D87) reintenta y nunca levanta, y su revisión encontró que una toma anidada cuya reescritura fallaba dejaba el bloqueo atrás (corregido en su `8263735`). Quedó abierta una advertencia: el aviso de la liberación no llevaba la traza (`R3-retrying-exc-info-cleared`).
- **Opciones**: (a) sin bloqueo, confiando en `max_active_runs`; (b) el bloqueo del proyecto 03 en su versión corregida, con la advertencia abierta resuelta, en su propia unidad antes del envoltorio de tareas.
- **Decisión**: (b): `lock.py` como dice el plan, sección 22, con el aviso que lleva la traza de la última excepción.
- **Motivo**: la CLI y un `replay` manual pueden correr a la vez que el DAG; (a) deja eso a la disciplina. Llegar con las correcciones evita las tres clases de defecto que costaron una evaluación y una revisión.
- **Afecta**: `lock.py`; `pipeline.py`; AC32; runbook R9.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D32 Rutas contra la carpeta del proyecto y modo rápido aislado

- **Contexto**: en el proyecto 01, una ruta relativa al directorio de trabajo falló en el contenedor (L14) y el modo rápido escribía sobre las salidas versionadas (su B3); en el proyecto 03, un `LATEDEL_CONFIG` relativo se tomaba del directorio de trabajo (su A2, D90).
- **Opciones**: solo había un camino razonable, el de la D24 y la D90 del proyecto 03.
- **Decisión**: toda ruta relativa de la configuración, de `--config` y de `CHURNRISK_CONFIG` se resuelve contra `CHURNRISK_HOME` o la carpeta del proyecto; `pipeline.quick.toml` pone todas sus rutas bajo `data/quick/`, incluidos el sello, el README, las figuras y `outputs/private/`; una prueba corre la repetición rápida desde otro directorio y compara el hash de todo el árbol.
- **Motivo**: un comando no puede depender de desde dónde se lo llama, y un modo de prueba no puede escribir un sello con los resultados del accesorio.
- **Afecta**: `config.py`; `cli.py`; `config/*.toml`; `.gitignore`; AC34; runbook R12.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D33 Lecciones de los proyectos 01, 02 y 03 que pasan a ser requisitos

- **Contexto**: las evaluaciones y revisiones de los tres proyectos encontraron clases de defecto que este plan debe prevenir por diseño; la del proyecto 03, seis bloqueantes (B1-B6) y seis advertencias (A1-A6), más los hallazgos de su comprobación (D93) y de su página (D94).
- **Opciones**: solo había un camino razonable: una prueba con nombre por clase desde la unidad que la toca; esperar a la evaluación final ya se probó tres veces y encontró los mismos tipos de defecto.
- **Decisión**: la tabla del plan, sección 24.2, con su prueba y su AC por clase. Las nuevas respecto del plan del proyecto 03: tareas de una corrida que no cargó su entrega (B1), carga sin validación (D93), la liberación del bloqueo en Windows y la toma anidada (B2), el resumen después del sello (B3), la huella del sello (B4), las reglas acumuladas del sitio (D94), un identificador en una imagen publicada (la captura de L43), una dependencia directa documentada como transitiva (B6), la documentación sin sincronizar tras la última corrección (B5, con una prueba que exige que exista cada prueba nombrada en el plan) y el tiempo de la suite (A1, D91); más las de research.md (neteo posterior al corte, BG/NBD con historia posterior, la variable que mira la ventana, SHAP no aditivo) y la del planificador (filas del mismo cliente en el intervalo).
- **Motivo**: cada fila dice qué defecto previene y lo fija con una prueba desde la unidad que lo toca.
- **Afecta**: `requirements.md` (RNF03, RNF06, RNF11, RNF12, RNF14, RNF15, AC12-AC14, AC18, AC21, AC22, AC29-AC32, AC36, AC39-AC42); `plan.md`, secciones 24 y 28.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D34 La suite rápida: límite de 120 s, presupuesto de 100 s y accesorios de sesión desde el principio

- **Contexto**: el proyecto 03 tuvo un límite de 150 s y terminó en 147,15 s y 144,38 s, con menos de 3 s de margen y los 135 s pedidos sin alcanzar (su D91); llegó ahí después de dos rondas de aceleración (sus D66 y D76) que compartieron almacenes y lecturas una vez por sesión. Aquí la lectura de un `.xlsx` con `openpyxl` es lo más lento (42 s el libro real).
- **Opciones**: (a) el límite de 150 s y acelerar cuando haga falta; (b) un límite de 120 s, un presupuesto de 100 s medido después de cada unidad y los accesorios de sesión desde la primera unidad de pruebas; (c) sin límite.
- **Decisión**: (b), con lo que dice el plan, sección 24.1: una sesión completa por encima del límite falla y dice por cuánto; la cuenta de pruebas de la documentación usa la colección de la sesión; la CLI y el modo rápido se prueban en el mismo proceso; la unidad siguiente a un tiempo de más de 100 s es de velocidad.
- **Motivo**: un margen que se mide en cada unidad no se pierde sin que alguien lo vea; (a) repite el final del proyecto 03; (c) deja crecer la suite hasta que deja de correrse. 120 s con 20 s de holgura deja lugar a las pruebas de las correcciones de la evaluación.
- **Afecta**: `tests/conftest.py`; todas las unidades; RNF15; AC41.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D35 `pytest-xdist`: no se fija en las dependencias de desarrollo

- **Contexto**: el proyecto 03 rechazó `pytest-xdist` dos veces porque suma dependencias de desarrollo (con `execnet`) fuera de las fijadas, un cambio de ítem 5 sin autorización del dueño (sus D66 y D76).
- **Opciones**: (a) fijar `pytest-xdist` desde U01 y correr en paralelo; (b) no fijarlo y cumplir el límite en un solo proceso.
- **Decisión**: (b).
- **Motivo**: con `pytest-xdist`, cada proceso de trabajo construye sus propios accesorios de sesión (la repetición rápida y el lanzamiento se construirían una vez por proceso), así que la ganancia depende del reparto y no está medida; además, las pruebas de concurrencia (el bloqueo, el sello) y las que comparan un árbol completo antes y después se vuelven sensibles a otros procesos. (a) también fijaría versiones sin medirlas. Si la suite se acerca al límite pese a la sección 24.1, es una decisión del dueño (pendiente 7).
- **Afecta**: `requirements-dev.txt`; `pyproject.toml`; AC41.
- **Quién**: agente de planificación; el dueño puede pedir (a).
- **Estado**: vigente.

## D36 Idioma y nombres: paquete `churnrisk`, alcance de commit `churn`

- **Contexto**: el sitio está en español; el código del portafolio, en inglés (supuestos del documento de seguimiento). Los proyectos anteriores usan `oilgas`, `custseg` y `latedel`, cada uno con su propio proyecto de Docker. Este plan se confirma con el alcance `churn`.
- **Opciones**: solo había un camino razonable para el idioma; el nombre del paquete tiene que ser corto, decir el problema y no chocar con los otros.
- **Decisión**: documentación en español neutro; código, identificadores, tablas y columnas en inglés; medidas DAX, títulos de visuales y textos del sitio en español. El paquete se llama `churnrisk` (como el identificador `churn-risk` de la página del sitio); variables de entorno `CHURNRISK_*`, DAG `churnrisk_monthly`, proyecto de Docker Compose `churnrisk-airflow`; alcance de los commits `churn`.
- **Motivo**: el contexto lo dice; un nombre propio evita que un volumen o una red de Docker de un proyecto toque los de otro (proyecto 02, D55); `churn` a secas como paquete sería un nombre genérico.
- **Afecta**: todo.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D37 Tecnologías fuera del landing: SHAP y sus dependencias; las ya anotadas suman el 04

- **Contexto**: S5 pide anotar en `LANDING-EXPANSION.md` lo que el landing no declara. research.md: el proyecto necesita SHAP, que no está anotado; LightGBM no hace falta. En el proyecto 03, SciPy era una dependencia directa que su D27 llamó transitiva (su B6).
- **Opciones**: solo había un camino razonable: anotar cada tecnología que el código use y el landing no declare, con lo que la importa.
- **Decisión**: una fila nueva para SHAP (`shap`, con numba y llvmlite como sus dependencias), con el uso (los motivos de cada cliente, D15). El 04 se suma a las filas de SciPy (dependencia **directa**: `bgnbd.py` usa `scipy.optimize` y `scipy.special`), NumPy, SQLite, Parquet con pyarrow, matplotlib, pytest, PostgreSQL, openpyxl y `lifetimes` (solo pruebas). Ninguna fila para LightGBM. U01 fija la prueba que exige que cada módulo de terceros importado sea una dependencia directa fijada y documentada.
- **Motivo**: S5; y que la prueba exista desde la primera unidad evita repetir el B6 del proyecto 03.
- **Afecta**: `LANDING-EXPANSION.md` (U31); `tests/unit/test_dependencies.py`; AC39; el pendiente 5 del dueño.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D38 Entorno y versiones

- **Contexto**: el proyecto 02 instaló y probó, en Windows con Python 3.11 y en la imagen de Airflow con Python 3.13, `numpy==2.4.6`, `pandas==2.3.3`, `scipy==1.17.1`, `scikit-learn==1.9.1`, `pyarrow==26.0.1`, `matplotlib==3.11.2`, `openpyxl==3.1.5` y `et_xmlfile==2.0.0` (su D28), con `python-dateutil==2.9.0.post0` y `six==1.17.0` después de L28. research.md corrió `shap==0.51.0` con `numba==0.68.1` en Python 3.11.1.
- **Opciones**: (a) resolver de nuevo las versiones más recientes; (b) el juego del proyecto 02 y las transitivas del proyecto 03, más `shap` y `numba` en las versiones de research.md.
- **Decisión**: (b). `requirements.txt`: el juego del proyecto 02 con sus transitivas como en el proyecto 03 (su D28), más `shap==0.51.0`, `numba==0.68.1` y las transitivas que resuelva su instalación **[Verificar en U01: llvmlite, slicer, tqdm y otras; se anotan en la decisión de U01, con `pip check`]**; nunca `python-dateutil` 4.x. `requirements-dev.txt`: `-r requirements.txt`, `pytest==9.2.0` y sus transitivas, y `lifetimes==0.11.3`, `autograd==1.9.1` y `dill==0.4.1` como el proyecto 02. `requires-python = ">=3.11,<3.14"`. Sin `--hash`; imágenes por versión y resumen.
- **Motivo**: ese juego ya se instaló junto en las dos plataformas; resolver de nuevo abriría conflictos ya cerrados (L28). `shap` y `numba` son las versiones con las que se midió la aditividad. **[Verificar en U27]** que `numba` instala en la imagen.
- **Afecta**: `requirements*.txt`; `pyproject.toml`; `airflow/Dockerfile`.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D39 Memoria: medida y con el contador nombrado

- **Contexto**: el proyecto 02 midió 1.471 MB de `PeakWorkingSetSize` con la lectura de este libro y su evaluador 3.514 MB de `PeakPagefileUsage` (su D69); el proyecto 03 nombró el contador en cada cifra (su D29).
- **Opciones**: solo había un camino razonable: el del proyecto 03.
- **Decisión**: RNF03: pico del conjunto de trabajo ≤ 2,5 GB (`PeakWorkingSetSize` en Windows, `ru_maxrss` en Linux); `PeakPagefileUsage` guardado sin umbral; `MemoryPeaks.counter`; una prueba de documentación exige que cada cifra de memoria nombre su contador.
- **Motivo**: el conjunto de trabajo es comparable entre las dos plataformas; 2,5 GB deja margen sobre lo medido por el proyecto 02 con la misma lectura **[Supuesto: SHAP y los cortes suman poco; U29 lo mide]**.
- **Afecta**: `sysinfo.py`; `pipeline_runs`; la ficha; el README; AC37, AC40.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D40 Artefacto del modelo con huella verificada antes de cargarlo

- **Contexto**: el modelo congelado, sus calibradores y los de las bases tienen que persistir entre corridas; deserializar un archivo alterado con `pickle` puede ejecutar código; el proyecto 03 lo resolvió con la huella sobre los mismos bytes (su D30).
- **Opciones**: solo había un camino razonable sin sumar tecnología (`skops` u ONNX no están en el landing): el del proyecto 03.
- **Decisión**: `pickle` de la biblioteca estándar, protocolo 5, en `data/models/<model_version>.pkl` (no versionado); la huella en `model_registry`; `load_artifact` lee los bytes una vez, compara y deserializa esos mismos bytes (M03). El explicador SHAP no se guarda: se rehace desde el modelo.
- **Motivo**: cierra el caso de un archivo reemplazado o dañado y la ventana entre comprobar y cargar; no protege contra quien reescribe el archivo y la base a la vez, y la ficha lo dice.
- **Afecta**: `registry.py`; M03; runbook R6.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D41 Demostración de la fuga y trampa M01

- **Contexto**: research.md: la variable «días desde la última compra hasta el fin de la ventana de etiqueta», que mira el futuro, dio AUC 1,000 en los tres primeros cortes de entrenamiento; sin variables así, nada pasó de 0,784. El sitio dice que un AUC casi perfecto se toma como una alarma.
- **Opciones**: (a) solo las guardas estructurales; (b) también una trampa que detiene el lanzamiento si el AUC del elegido en V1 es ≥ 0,95, y una demostración en V2 con una variable de control; (c) solo una advertencia.
- **Decisión**: (b): `leak_tripwire_auc = 0,95`; `leakage_demo.py` mide en V2 el AUC de F1 con `days_to_next_purchase` frente a F1 solo, en su propio módulo, que no puede escribir en el registro ni en los puntajes; una prueba fuerza la variable de control más allá de la guarda y exige que M01 detenga el lanzamiento.
- **Motivo**: las guardas son la defensa; la trampa es una segunda línea independiente para una fuga que nadie imaginó, y la demostración cumple lo que el sitio promete con el código del proyecto, sin tocar la prueba.
- **Afecta**: `model.py`; `leakage_demo.py`; `label.json` (`leakage`); AC14; runbook R5.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D42 Accesorio sintético con controles positivo y negativo y números de cliente centinela

- **Contexto**: el proyecto 02 generó un accesorio de este mismo libro con clientes de parámetros conocidos; el proyecto 03 sumó controles positivo y negativo y valores centinela (su D34). Lo esperable en los datos reales es que el modelo no supere a RFM (D18).
- **Opciones**: (a) un accesorio aleatorio; (b) uno con un proceso de compra conocido; (c) el de (b) con un control positivo (una señal que RFM no ve: la irregularidad de las brechas), uno negativo (la baja depende solo de RFM), números de cliente de un rango propio y una variante malformada por regla bloqueante.
- **Decisión**: (c), como dice el plan, sección 24.
- **Motivo**: si C02 no se cumple con los datos reales, el lector tiene que saber que el método habría detectado una mejora si existiera (control positivo) y que no la inventa (control negativo). Un rango propio de números hace que la prueba de identificadores mire bytes, no nombres de columnas.
- **Afecta**: `tests/fixtures/*`; AC16, AC42.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D43 Sin API de puntuación en tiempo real

- **Contexto**: el landing declara FastAPI; el proyecto es una repetición mensual sobre un archivo estático; el proyecto 03 decidió lo mismo (su D33).
- **Opciones**: (a) un servicio con FastAPI; (b) una función de puntuación pura (`score_cut`) que un servicio envolvería.
- **Decisión**: (b).
- **Motivo**: nada del problema necesita tiempo real (la lista es mensual); un servicio suma un puerto, su seguridad y su contenedor sin cambiar ningún resultado.
- **Afecta**: `scoring.py`; la ficha; runbook R13.
- **Quién**: agente de planificación; el dueño puede pedirlo (pendiente 9).
- **Estado**: vigente.

## D44 Los cortes posteriores a la prueba: puntuados, seguidos y nunca evaluados

- **Contexto**: con N = 90, las ventanas de los cortes 2011-10-01, 2011-11-01 y 2011-12-01 terminan el 2011-12-29, el 2012-01-29 y el 2012-02-28, después del fin del archivo (2011-12-09). El producto, en uso, puntuaría esos cortes igual.
- **Opciones**: (a) no puntuarlos; (b) puntuarlos y seguir quién volvió, marcándolos como censurados, sin etiqueta completa ni métricas; (c) evaluarlos con la ventana truncada.
- **Decisión**: (b): bloque `post_test`, `is_censored = true`; `tracking` cuenta quién volvió; nunca entran en un criterio.
- **Motivo**: (a) dejaría el flujo sin sus tres últimos meses de lista; (c) mediría otra etiqueta (una ventana más corta) y la mezclaría con la sellada.
- **Afecta**: `split.py`; `tracking.py`; `retention.json`; la página 3 del tablero.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D45 Contradicciones con el sitio

- **Contexto**: research.md encontró cinco diferencias con la página (LightGBM, la recencia como variable principal, «un minorista del Reino Unido», la automatización mensual sobre un archivo estático y los costos sin datos), y confirmó otras afirmaciones (90 días, el AUC casi perfecto como alarma, Verbeke y otros, 2012, los «2 años», las «0 columnas que digan quién se fue»). La página vive en marca-personal, que esta planificación solo lee.
- **Opciones**: solo había un camino razonable: proponer el texto en `SITE-UPDATES.md` con su motivo y dejar el cambio al dueño y a la unidad del sitio.
- **Decisión**: las 16 filas del plan, sección 30; U31 las escribe con las cifras de U29.
- **Motivo**: S9 pide un proyecto fiel al sitio, y donde el proyecto real difiere, que la diferencia quede escrita con números reales (lección A9 del proyecto 01).
- **Afecta**: `SITE-UPDATES.md`; marca-personal, `src/i18n/projects/churn-risk.ts`; el pendiente 4 del dueño.
- **Quién**: agente de planificación; el texto, el dueño.
- **Estado**: vigente.

## D46 Unidades de trabajo, commits y estrategia de entrega

- **Contexto**: el documento de seguimiento fija `ask-on-risk` y un commit por unidad; el proyecto 03 llevó cada unidad de riesgo alto en su propio commit para que la revisión nativa la tomara sola, y partió una revisión que superó el presupuesto de contexto (L37). Este plan suma unas 12.400 líneas en 31 unidades.
- **Opciones**: (a) unidades de unas 400 líneas, cada una con su RED, sus pruebas y su documentación, y las de riesgo alto solas; (b) commits por capa (código, pruebas, documentación).
- **Decisión**: (a): U01-U31 del plan, sección 27; solas, con su ítem: U01 (5), U04 (2), U05 (2), U13 (2), U16 (1), U20 (3), U23 (3), U24 (4), U25 (4), U27 (5 y 2) y U29 (1); alcance de commit `churn`; push, PR y la estrategia de la cadena (`stacked-to-main` o `feature-branch-chain`) son del dueño.
- **Motivo**: una unidad con su comportamiento, sus pruebas y su documentación es lo que se revisa y se revierte entera; (b) separa lo que se prueba de lo que lo prueba.
- **Afecta**: el orden de construcción; la revisión nativa (S11); el pendiente 11 del dueño.
- **Quién**: agente de planificación; la estrategia de entrega, el dueño.
- **Estado**: vigente.
