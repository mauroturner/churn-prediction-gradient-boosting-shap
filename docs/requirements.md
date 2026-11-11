# Requerimientos: clientes que están por irse, antes de que se vayan

Fecha: 2026-11-11. Base: `docs/research.md` y una comprobación del agente de planificación que leyó **solo los cortes de entrenamiento** (sección 4). Las suposiciones se marcan como **[Supuesto]**; lo que hay que comprobar al programar, como **[Verificar]**; lo deducido sin fuente, como **[Inferido]**. Las decisiones citadas (Dxx) están en `decisions.md`; el diseño, en `plan.md`.

## 1. Problema

Una tienda que vende en línea ve quién compró y cuándo, pero ningún sistema marca quién dejó de comprar: cuando alguien lo nota, el cliente ya se fue. No hay contrato que se cancele ni aviso de baja; solo un silencio que se confunde con una pausa normal.

Quién lo sufre:

- **Retención y marketing**: no saben a quién llamar ni cuándo, y reparten ofertas a todos o a nadie.
- **Atención al cliente**: no sabe qué clientes conviene cuidar antes de que dejen de comprar.
- **Dirección**: no sabe cuánto rinde una oferta de retención ni si un modelo agrega algo a una regla que cualquiera puede escribir con las facturas (recencia, frecuencia y gasto).

Qué cuesta hoy:

- En los cortes de entrenamiento, el 43,2 % de los clientes activos en los 90 días anteriores no vuelve a comprar en los 90 siguientes, entre el 31,2 % y el 57,9 % según el mes (sección 4).
- **[Supuesto]**: el archivo no trae costos de una oferta, tasas de rescate ni márgenes; no hay una fuente pública defendible para este caso (research.md). El costo se declara, no se mide (D22).

## 2. Objetivo

Un flujo mensual que carga las facturas de cada mes, las valida, netea las anulaciones con lo que se sabe en cada fecha y, en cada fecha de corte, da a cada cliente activo la probabilidad calibrada de no volver a comprar en los 90 días siguientes, con sus tres motivos principales (SHAP), y la lista de los que conviene contactar según costos supuestos y declarados; sigue cada mes quién volvió y quién no, y deja las tablas de un tablero de Power BI en modelo estrella, el diseño del tablero en HTML y una exportación pequeña para el sitio, sin ningún número de cliente en lo que se publica. El modelo se compara con las reglas que usaría un gerente (recencia, RFM, frecuencia y BG/NBD) con criterios fijados antes de construir (sección 8.1), y los cortes de prueba se evalúan una sola vez, bajo un sello (D19).

## 3. Alcance

Incluido:

- Fuente: `online_retail_ii.zip` de UCI (Online Retail II, Chen, 2012, DOI 10.24432/C5CG6D, CC BY 4.0), el mismo archivo y la misma huella que el proyecto 02 (D02).
- Unidad: el cliente con número en una fecha de corte (D05). Baja: ningún día de compra neta en los 90 días desde el corte (N = 90, D06). Población: los clientes con compra neta en los 90 días anteriores (M = 90, D07).
- Cortes mensuales del día 1, del 2010-06-01 al 2011-12-01; partición en entrenamiento (7 cortes), V1 (2), V2 (1) y prueba (2), con purgas de al menos N días entre bloques (D08). Los cortes de 2011-10, 2011-11 y 2011-12 se puntúan y se siguen, pero su ventana termina después de los datos y nunca se evalúan (D44).
- Estacionalidad y sensibilidades: sin variable de calendario; tasas por corte; N = 60 y N = 120, M = 180 y el entrenamiento sin el corte de diciembre, informados como sensibilidad y nunca usados para elegir (D09, D10).
- Refresco mensual sobre un archivo que no cambia: un lanzamiento al 2011-07-31, cuatro entregas mensuales (2011-08 a 2011-11) y un cierre con los 9 días de 2011-12 (D11).
- Modelo: `HistGradientBoostingClassifier` de scikit-learn, tres conjuntos de variables y una grilla fija, elegido y calibrado en V1, con el umbral elegido en V2 (D12-D14). SHAP aditivo para los motivos de cada cliente (D15).
- Líneas base B0-B5, con BG/NBD de SciPy reutilizado del proyecto 02 (D16, D17); criterios C01-C10 (D18); intervalos por remuestreo pareado de clientes (D21).
- Umbral por costo con supuestos declarados (`c_oferta`, `r`, `V`), curva de ganancia y sensibilidad del punto de equilibrio (D22).
- Modelo congelado en el lanzamiento y sello con una huella que cubre cada clave que cambia un valor sellado (D19, D20).
- Orquestación en Apache Airflow sobre Docker Compose y una CLI equivalente para Windows sin Airflow, con un solo escritor por carpeta de datos (D29-D31).
- Tablas para Power BI en Parquet, diseño del tablero en HTML con el panel de supuestos, exportación para el sitio en JSON con manifiesto, documentación completa con la estructura del proyecto 01 (S10).

Fuera de alcance:

- Los clientes sin número (22,5 % de las líneas, 15,1 % del importe bruto positivo): no se pueden seguir en el tiempo; se informan aparte (D05).
- Un modelo de reactivación para los clientes que llevan más de M días sin comprar (D07).
- Reentrenar dentro del flujo mensual: el modelo se entrena una vez y se congela (D19).
- Costos reales de una oferta o del valor de un cliente: no hay una fuente defendible (research.md); se declaran supuestos (D22).
- Una medición real de bajas o un experimento de retención: el resultado predice silencios en un archivo público, no bajas comprobadas (research.md, «Riesgos y huecos» 4).
- Una API de puntuación en tiempo real (FastAPI) (D43).
- Construir el `.pbix` en Power BI Desktop (interfaz gráfica; S4) y publicarlo.
- LightGBM: el sitio lo nombra, pero el proyecto usa scikit-learn (D13, D45).

## 4. Datos medidos

Fuente (research.md, la misma que el proyecto 02): `https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip`, 45.622.418 bytes, SHA-256 `572e36277c2390fbfde10664750731e0a86f55e33470d91919085f0408e67bfb`; dentro, `online_retail_II.xlsx` de 45.622.278 bytes, SHA-256 `bcbe73b35f5b7babf197fb0cb983a11f5d9ff929078d4aa53d171b1f2df2e980`. Dos hojas (`Year 2009-2010`, 525.461 filas; `Year 2010-2011`, 541.910), 1.067.371 filas, 8 columnas, del 2009-12-01 al 2011-12-09. Lectura con `openpyxl`: 42 s (research.md); 47 s en la corrida real del proyecto 02 (`LANDING-EXPANSION.md`).

De research.md (archivo completo, descriptivo; sin cortes ni etiquetas):

| Medida | Valor |
| --- | --- |
| Filas tras quitar las copias del solapamiento entre hojas (proyecto 02, D03) | 1.044.848 (22.523 copias quitadas; 11.812 repeticiones internas conservadas) |
| Líneas sin número de cliente | 235.287 (22,52 %), 15,11 % del importe bruto positivo |
| Facturas «C» (anulaciones) | 8.292 facturas, 19.165 líneas (1,83 %), 7,14 % del importe bruto positivo |
| Líneas de servicio con cliente | 3.663 (envío, comisiones, ajustes, muestras, pruebas; `PADS` incluido) |
| Facturas «A» (ajuste de deuda incobrable) | 6 líneas |
| Clientes con número | 5.942; Reino Unido 91,03 % (5.410); 41 países con clientes, 24 con menos de 10 clientes (73 clientes) |
| Brechas entre días de compra (compras hasta 2011-07-31) | mediana 31 días, cuartil 75 68, percentil 90 134, percentil 95 191 |
| Silencios de más de 90 días que vuelven en los 90 siguientes | 39,2 % |

**Comprobación del agente de planificación, solo sobre los cortes de entrenamiento.** Se leyeron las líneas canónicas del proyecto 02 (`02-Ecommerce-Customer-Segmentation/data/interim/source_lines.parquet`, la misma base de 1.044.848 líneas) con un filtro de lectura `invoice_ts < 2011-03-01`, así que ninguna línea de una ventana de validación o de prueba entró en memoria (608.273 líneas leídas; 458.894 compras y 10.858 anulaciones con la regla de roles del proyecto 02). Se usaron, en solo lectura, las funciones del proyecto 02 (`classify_lines`, `net_cancellations`, `customer_days`, `summary_from_days`, `fit_bgnbd`, `expected_purchases`, `p_alive`) y `lifetimes` 0.11.3 como segunda implementación. Python 3.11.1 de la `.venv` del proyecto 02, con `python -I`; los scripts y sus salidas quedaron fuera del repositorio (`decisions.md`, encabezado). Ninguna métrica se calculó en un corte de validación ni de prueba.

Tasa de bajas por corte de entrenamiento (población: activos en los M días anteriores; filas = clientes):

| Corte | Activos M = 90 | Bajas N = 60 | Bajas N = 90 | Bajas N = 120 | Activos M = 180 | Bajas N = 90, M = 180 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2010-06-01 | 2.012 | 52,9 % | 44,3 % | 37,2 % | 2.646 | 50,0 % |
| 2010-07-01 | 2.013 | 54,1 % | 42,9 % | 32,1 % | 2.731 | 49,2 % |
| 2010-08-01 | 1.993 | 50,2 % | 35,9 % | 27,1 % | 2.810 | 43,0 % |
| 2010-09-01 | 1.925 | 43,6 % | 31,2 % | 27,8 % | 2.817 | 37,9 % |
| 2010-10-01 | 2.018 | 42,0 % | 36,5 % | 33,7 % | 2.892 | 42,0 % |
| 2010-11-01 | 2.477 | 51,6 % | 46,3 % | 41,8 % | 3.186 | 50,7 % |
| 2010-12-01 | 2.859 | 65,8 % | 57,9 % | fuera (la ventana pisa la validación) | 3.456 | 62,0 % |
| Entrenamiento (N = 90, M = 90) | 15.297 filas, 3.942 clientes | | 43,2 % | | | |

- Coincide con research.md (15.297 filas, 3.942 clientes, 43,2 %, rango de 31,2 % a 57,9 %).
- **Un cliente aparece en varios cortes**: de los 3.942 clientes, 543 están en un solo corte, 625 en dos, 870 en tres, 415 en cuatro, 401 en cinco, 387 en seis y 701 en los siete. Las filas no son independientes: los intervalos se remuestrean por cliente (D21).
- **Clientes con un solo día de compra**: 27,0 % de las filas de entrenamiento, con 67,0 % de bajas; en el corte de 2010-12-01, 684 clientes con 82,5 % de bajas (research.md dice 82,5 %).
- **La frecuencia sola es la regla más fuerte del entrenamiento.** AUC por corte (media de los 7; mínimo y máximo), con los empates por mitades: días de compra en los 365 días anteriores 0,746 (0,728 a 0,761); RFM 0,737 (0,711 a 0,760); BG/NBD compras esperadas en 90 días 0,732 (0,706 a 0,753); gasto de 365 días 0,731 (0,713 a 0,758); recencia 0,594 (0,550 a 0,623); BG/NBD 1 − P(vivo) 0,362 (0,327 a 0,392). Research.md: RFM 0,734, BG/NBD 0,732, recencia 0,594 y 1 − P(vivo) 0,362; la diferencia en RFM (0,737 frente a 0,734) sale de cómo se cortan los quintiles: aquí, el rango medio del proyecto 02 (su D09) **[no conciliada: research.md no documenta su método]**. En los cortes de entrenamiento la frecuencia de 365 días es igual a la total, porque el archivo empieza el 2009-12-01.
- **RFM ordena bien**: la tasa de bajas del entrenamiento baja con cada punto del puntaje, de 71,5 % (puntaje 3, 716 filas) a 4,3 % (puntaje 15, 853 filas), sin una inversión.
- **BG/NBD del proyecto 02 sirve.** Ajustado con la historia anterior al 2010-12-01 (4.229 clientes): `lifetimes` da r = 0,9084, α = 75,76, a = 0,1737, b = 108,27 (los parámetros de research.md) y log-verosimilitud −59.505,3607; la implementación con SciPy del proyecto 02 da r = 0,9091, α = 75,83, a = 0,1717, b = 105,91 y −59.505,3611 en 0,34 s. Difieren en b un 2,2 % (una dirección casi plana de la verosimilitud, como describe la D42 del proyecto 02), pero sobre los 2.859 activos del corte las compras esperadas en 90 días difieren a lo sumo en 0,0045 (0,069 % relativo; medias 1,3536 y 1,3537) y su orden tiene una correlación de Spearman de 0,9999996.
- **P(vivo) satura**: en los 2.859 activos del corte de 2010-12-01 va de 0,866 a 1,000, con el percentil 1 en 0,992 y la mediana en 0,998; el 93,4 % está en 0,996 o más y el 23,9 % no tiene compras repetidas (P(vivo) = 1).

De research.md, sobre el primer corte de validación (2011-03-01, 1.677 clientes, 43,4 % de bajas; lo vio la investigación, no el planificador): RFM AUC 0,784, BG/NBD compras esperadas 0,776, recencia 0,625, P(vivo) 0,433; `HistGradientBoostingClassifier` con 25 columnas 0,769, PR-AUC 0,691, lift 1,80 en el 10 % superior; diferencia pareada con RFM −0,014 (intervalo del 95 % de −0,033 a 0,005). SHAP 0.51.0 es aditivo con el país en one-hot (error máximo 8·10⁻¹⁵ en log-odds) y no con las divisiones categóricas nativas (3,6); 1,0 s para 1.677 filas y 9,0 s para 15.297.

Lo esperable en la prueba por estacionalidad **[Inferido]**: los cortes de prueba (2011-08-01 y 2011-09-01) miran de agosto a noviembre; un año antes, los mismos cortes tuvieron 35,9 % y 31,2 % de bajas, por debajo del 43,2 % del entrenamiento y del 43,4 % del primer corte de validación. Un modelo calibrado en marzo y abril probablemente sobrestime el riesgo en la prueba (D09).

Entorno: Python 3.11.1 en Windows (el único instalado); la imagen `apache/airflow:3.4.0` trae Python 3.13.18 (proyectos 01 a 03); scikit-learn 1.9.1 trae `sklearn.frozen.FrozenEstimator` (proyecto 03, D13). Pico del conjunto de trabajo del proyecto 02 con la misma lectura del libro: 1.471 MB (`PeakWorkingSetSize`), con 3.514 MB de memoria comprometida (`PeakPagefileUsage`) en la corrida de su evaluador (su D69).

## 5. Requerimientos funcionales

- **RF01 Fuente íntegra.** `fetch_source` descarga el zip por HTTPS solo si no está en `data/raw/`, a un `.part` con SHA-256 calculado al vuelo, y lo renombra con `os.replace` solo si la huella es `source.accepted_sha256` (modo `http`). En modo `local`, la primera huella vista queda registrada y las siguientes deben coincidir. Una huella distinta rechaza la corrida sin tocar nada (V01).
- **RF02 Descarga segura.** Cada salto, incluidas las redirecciones, es HTTPS y va a un host de `source.allowed_hosts`; a lo sumo `max_redirects` redirecciones, `max_bytes` bytes y `max_seconds` segundos en total (V02).
- **RF03 Extracción y lectura seguras.** El zip tiene exactamente el miembro esperado, sin rutas, con tope descomprimido y su propia huella; el libro tiene las hojas configuradas y en cada una las 8 columnas exactas; los tipos se convierten al 100 % (V03-V05). El libro se trata como no confiable.
- **RF04 Base canónica.** Se quitan las copias de la hoja 2 en la ventana común si el solapamiento es el mismo multiconjunto de filas (V06); las repeticiones internas se conservan y se marcan; se escribe `data/interim/source_lines.parquet` con `line_id`, `code_kind` y la fecha mínima de cada factura, y un manifiesto de huellas al final (proyecto 03, D50).
- **RF05 Roles de las líneas.** Cada línea es compra, anulación o apartada por la primera regla que la aparta, en el orden de la tabla del plan (sin cliente, cantidad con el signo equivocado, precio ≤ 0, código de servicio con `PADS`, vale de regalo, factura «A»), con su conteo y su importe (D03).
- **RF06 Neteo conocido en una fecha.** Las anulaciones se descuentan de la compra que anulan (LIFO por cliente y producto, proyecto 02, D04) usando solo las anulaciones con fecha ≤ la fecha pedida; un día de compra es un día con al menos una compra neta del cliente (proyecto 02, D06).
- **RF07 Entregas.** `deliver` publica la siguiente entrega pendiente con su manifiesto (período, filas, SHA-256): el lanzamiento `L2011-07` (del 2009-12-01 al 2011-07-31), las mensuales `M2011-08` a `M2011-11` y el cierre `C2011-12` (del 2011-12-01 al 2011-12-09). Una línea va en la entrega de la fecha de su factura. Sin pendientes, la corrida termina como `no_delivery` (D11).
- **RF08 Validación de la entrega.** Reglas del plan (sección 6), con filas, clientes e importe afectados y la forma en que cada regla se agrega entre corridas; reporte JSON y Markdown por corrida.
- **RF09 Rechazo sin daño.** Con una regla bloqueante, la entrega pasa a cuarentena, la corrida termina como `rejected` y el almacén, los Parquet, el HTML, la exportación del sitio y el sello quedan como estaban, byte a byte.
- **RF10 Carga.** Las líneas de la entrega se agregan a SQLite en una transacción; `staging` y los marts se reconstruyen con SQL versionado y controles en SQL. Un control con filas deshace todo. `load` se niega si la validación de esa misma corrida no existe o falló, y si la entrega la cargó otra corrida (D30).
- **RF11 Cortes y población.** Un corte `c` es el día 1 de un mes entre `first_cut` y `last_cut`; su población son los clientes con un día de compra neta en `[c − M, c − 1]`, con el neteo conocido en `c − 1`.
- **RF12 Etiqueta.** `churned = 1` si el cliente no tiene ningún día de compra neta en `[c, c + N − 1]`, con el neteo conocido en `c + N − 1`. La etiqueta de un corte se escribe en el almacén recién cuando la fecha de cálculo alcanza `c + N − 1` (D06).
- **RF13 Variables solo con lo anterior al corte.** Las 16 variables de research.md y el país de la última línea anterior al corte como indicadores one-hot (los países con menos de 10 clientes en el entrenamiento van a «Otros»), calculadas solo con líneas y anulaciones con fecha anterior a `c`; nunca el número de cliente, una variable de calendario ni una salida de BG/NBD (D12).
- **RF14 Partición en el tiempo.** Los bloques de D08 por fecha de corte; cada borde entre bloques cumple `c_anterior + N ≤ c_siguiente`; los cortes de las purgas no entran en ningún bloque.
- **RF15 Líneas base.** B0 (contactar a todos), B1 (recencia), B2 (RFM: quintiles en el corte de recencia, frecuencia y gasto de 365 días; puntaje 3 a 15), B3 (BG/NBD: compras esperadas en los N días, con los parámetros ajustados con la historia anterior al último corte de entrenamiento), B4 (días de compra en los 365 días anteriores) y B5 (1 − P(vivo), informativa). Para las decisiones por costo, cada puntaje se convierte en probabilidad con regresión isotónica en V1, como el modelo (D16).
- **RF16 Base más fuerte.** B* es la de mayor AUC en la validación (V1 y V2) entre B2, B3 y B4; en un empate a 10⁻⁶, la más simple (B4, después B2, después B3). Se elige en el lanzamiento y se sella (D14).
- **RF17 Modelo.** Los tres conjuntos de variables por la grilla fija se ajustan en el entrenamiento; se elige el de menor pérdida logarítmica en V1; se calibra con regresión isotónica en V1; el artefacto se guarda con su SHA-256 y solo se carga si la huella coincide (D12-D14, D40).
- **RF18 Motivos de cada cliente.** SHAP (`TreeExplainer`) sobre el log-odds del modelo sin calibrar da, para cada cliente puntuado, la contribución de cada variable; la suma más el valor base reproduce su log-odds con un error ≤ `shap_additivity_tol` en cada fila explicada, o la tarea falla (M06). Se guardan los tres motivos de mayor contribución hacia el riesgo, con su dirección (D15).
- **RF19 Umbral por costo y curva de ganancia.** Con `offer_cost`, `rescue_rate` y `retained_value` de la configuración, el beneficio neto de contactar a un cliente es `churned × r × V − c_oferta`; el umbral es el que maximiza el beneficio neto en V2, en una grilla de 0,01 a 0,99; nunca F1. Se calculan la curva de ganancia (proporción de bajas captadas según la proporción contactada), el lift al 10 % y al 20 % y la sensibilidad del punto de equilibrio de 0,10 a 0,90 (D22).
- **RF20 Lanzamiento congelado y sello.** El lanzamiento entrena, elige, calibra, elige B* y el umbral, registra el artefacto y escribe la parte del lanzamiento del sello (`reports/model_seal.json`) con un `config_sha256` que cubre cada clave de la configuración que cambia un valor sellado; las corridas siguientes reusan el artefacto sin cambios (D19).
- **RF21 Puntuación mensual.** Cada corrida puntúa una vez a cada cliente activo de su corte (el día siguiente a su fecha de cálculo) con el modelo congelado y guarda la probabilidad, si se contacta, el umbral, la versión del modelo, la fecha de cálculo y sus tres motivos. Un puntaje nunca cambia.
- **RF22 Seguimiento.** Cada corrida calcula, para cada corte puntuado, cuántos volvieron a comprar hasta su fecha de cálculo, si la ventana cerró, cuántos se fueron, cuántos contactados se fueron o volvieron y las bajas esperadas (Σ p); los cortes cuya ventana pasa el fin de los datos quedan marcados como censurados (D44).
- **RF23 Evaluación una sola vez.** Cuando la fecha de cálculo alcanza el fin de la ventana del último corte de prueba (2011-11-29), se calculan los criterios C01-C10 y las sensibilidades de D10 y se escriben en el sello. Con otra configuración que la sellada, el resultado se guarda como posterior al sello y no reemplaza el sellado.
- **RF24 Resumen honesto.** `reports/evaluation_summary.json` y `.md` dicen el veredicto de cada criterio según su número, incluido «no supera»; después del sello, un almacén sin las filas selladas toma los criterios y las cifras de la prueba del sello, cada una comprobada contra su entrada (D20); el bloque de resultados del README se copia de ese resumen entre marcadores.
- **RF25 Modelo estrella.** Se exportan a `outputs/powerbi/` las dimensiones y los hechos del plan en Parquet, con claves únicas e integridad referencial. El hecho por cliente y corte, que lleva el número de cliente, se escribe en `outputs/private/` (no versionada) (D26).
- **RF26 Diseño del tablero.** Se genera `dashboard/powerbi-design.html` desde una especificación del modelo semántico: tablas, relaciones, medidas DAX, los parámetros de hipótesis del costo de la oferta, la tasa de rescate y el valor del cliente retenido, carga en Power Query y cinco páginas con vistas previas de datos reales, sin ningún número de cliente (la columna de la lista se muestra enmascarada).
- **RF27 Exportación para el sitio.** Se escriben en `outputs/site/` cinco JSON pequeños con el contrato del plan (sección 21) y al final `manifest.json` con el tamaño y la huella de cada uno; sin números de cliente ni ningún identificador; ninguna celda publicada con menos de 10 clientes, con supresión secundaria; las reglas acumuladas se leen una vez, de la última corrida cargada (D27, D28).
- **RF28 Orquestación.** Un DAG de Airflow (`churnrisk_monthly`) en Docker Compose y una CLI (`python -m churnrisk run`, `replay`, `task`) ejecutan la misma lista de tareas, en el mismo orden, con las mismas funciones; un solo proceso escribe una carpeta de datos a la vez (D29-D31).
- **RF29 Documentación.** README con la narrativa del proyecto 01, diccionario de datos, ficha del modelo, registro de decisiones, runbook, paso a paso, advertencias de las revisiones y evaluación independiente, con figuras generadas desde los archivos del sitio.

## 6. Requerimientos no funcionales

- **RNF01 Reproducibilidad.** Versiones fijadas con `==` (D38), semillas fijas, ajustes sin parada temprana. Dos repeticiones completas sobre la misma fuente dan Parquet y JSON con el mismo contenido, salvo las columnas de la corrida.
- **RNF02 Rendimiento** (este equipo, medido en U29). Repetición completa (fuente ya descargada, 6 entregas y la corrida sin entrega) ≤ 15 min; lectura del libro y corrida de lanzamiento ≤ 5 min; corrida mensual ≤ 2 min; repetición completa en modo rápido ≤ 2 min; prueba de Docker ≤ 10 min. **[Supuesto]**: la lectura del libro (42 a 47 s), unos 30 neteos de 0,46 s (proyecto 02, D04), 24 ajustes de unos 0,3 s y SHAP de unos 1 s por corte (research.md).
- **RNF03 Memoria, con el contador nombrado.** Pico del conjunto de trabajo ≤ 2,5 GB: en Windows, `PeakWorkingSetSize` de `GetProcessMemoryInfo` (por `ctypes`, con `argtypes` y `restype` declarados); en Linux, `ru_maxrss` (KiB). En Windows se guarda además `PeakPagefileUsage`, informativo, sin umbral. Toda cifra de memoria de la documentación nombra su contador (D39).
- **RNF04 Portabilidad.** La CLI corre en Windows 10 con Python 3.11; el DAG, en `apache/airflow:3.4.0` (Python 3.13.18). Toda ruta relativa de la configuración, de `--config` y de `CHURNRISK_CONFIG` se resuelve contra `CHURNRISK_HOME` o la carpeta del proyecto, nunca contra el directorio de trabajo (D32).
- **RNF05 Idempotencia y atomicidad.** Repetir una tarea con la misma entrada no cambia el resultado; cada escritura de tablas es transaccional; cada archivo se escribe a un temporal y se renombra con `os.replace`; los conjuntos de archivos llevan un manifiesto escrito al final.
- **RNF06 Sin fuga de información.** (a) Las variables de un corte salen solo de líneas y anulaciones anteriores al corte; (b) todo lo calculado en una fecha de cálculo usa solo lo cargado hasta esa fecha y el neteo conocido en ella; (c) toda decisión del modelo (variables, configuración, calibración, B*, umbral, costos) usa solo entrenamiento y validación; (d) los cortes de prueba se evalúan una vez, con la configuración sellada (D19); (e) ninguna sensibilidad se lee para elegir (D10).
- **RNF07 Trazabilidad.** Cada fila de hechos y cada archivo de salida llevan el `run_key`, la fecha de cálculo y la huella de la fuente; los puntajes, la versión del modelo y el umbral. Cada tarea registra inicio, fin, filas, duración, picos de memoria con su contador y, si falla, la traza completa.
- **RNF08 Tecnologías.** Las del landing (S5) y las ya anotadas en `LANDING-EXPANSION.md`; este proyecto suma SHAP (y su dependencia numba) y lo anota (D37). Cada módulo de terceros que el código importe es una dependencia directa fijada y documentada como tal.
- **RNF09 Licencia.** La atribución CC BY 4.0 con la cita «Chen, D. (2012). Online Retail II [Dataset]. UCI Machine Learning Repository. https://doi.org/10.24432/C5CG6D» aparece en el README, el diseño del tablero, los metadatos de cada Parquet y la exportación del sitio.
- **RNF10 Versionado.** Nunca se versionan la fuente, las entregas, el almacén, los intermedios, el artefacto, `outputs/private/` ni `data/quick/`; cada Parquet versionado pesa ≤ 25 MB; la exportación del sitio, ≤ 200 KB sin el manifiesto. El sello sí se versiona.
- **RNF11 Seguridad.** Descarga: HTTPS en cada salto, lista de hosts, topes de redirecciones, bytes y segundos, huella fijada (D02). Zip y libro: miembro exacto, sin rutas, con tope descomprimido; lectura con límites (RF03). Artefacto: solo se deserializa si su SHA-256 coincide (D40). Compose: interfaz solo en `127.0.0.1`; **cada secreto con `${VAR:?}` y sin valor por defecto, incluida la contraseña de la base de metadatos en el servicio de PostgreSQL y en la cadena de conexión**; `src/`, `sql/`, `config/` y `dags/` en solo lectura; imágenes con versión y resumen; el script de inicialización con `set -e`; un rechazo no se reintenta (D29). Sin credenciales en el proyecto.
- **RNF12 Datos personales e identificadores.** El número de cliente vive solo en SQLite, en `data/interim/` y en `outputs/private/`; nunca llega a un Parquet versionado, al HTML, a un JSON, a un reporte versionado, a una figura, a una captura, a un registro ni al archivo de estado de una corrida. Ningún agregado publicado tiene una celda con menos de 10 clientes; los países con menos de 10 clientes se publican como «Otros» (D26, D27).
- **RNF13 Idioma.** Documentación en español neutro; código, identificadores, tablas y columnas en inglés; medidas, títulos de visuales y textos del sitio en español (D36).
- **RNF14 Honestidad.** La documentación dice solo lo que consta en el registro del documento de seguimiento y en `git log`, y se sincroniza después de la última corrección: el número de pruebas, los tiempos, las cifras de memoria y las advertencias abiertas que dice coinciden con lo medido en el último commit (lecciones del proyecto 02, B3, y del proyecto 03, B5).
- **RNF15 Suite rápida con presupuesto.** La suite por defecto termina en ≤ 120 s en este equipo, con un presupuesto de trabajo de 100 s que se mide después de cada unidad; los accesorios caros se construyen una vez por sesión; ninguna prueba lanza un proceso aparte para lo que la sesión ya tiene (D34, D35).
- **RNF16 Un solo escritor.** Un solo proceso escribe una carpeta de datos a la vez, con un bloqueo cuya liberación nunca levanta y que solo su dueño borra (D31).

## 7. Requerimientos de datos

- **Clave de la línea**: `line_id`, entero, asignado en la lectura canónica (proyecto 02). **Clave de la fila del modelo**: (`cut_date`, `customer_id`), solo en SQLite, `data/interim/` y `outputs/private/`.
- **Fechas**: `invoice_ts`, fecha y hora local del archivo, sin zona; `invoice_date`, la fecha mínima de la factura (proyecto 02); `cut_date`, el día 1 de un mes; `label_end = cut_date + N − 1`; `as_of_date`, la fecha de cálculo (fin del día).
- **Etiqueta**: `churned` (0 o 1), solo para la población del corte y solo cuando `as_of_date ≥ label_end`.
- **Montos**: libras esterlinas del archivo, netas de anulaciones. Los costos del umbral están en unidades genéricas («u.»): decide su cociente (D22).
- **Contrato del libro**: dos hojas con nombre fijo, cada una con las 8 columnas `Invoice`, `StockCode`, `Description`, `Quantity`, `InvoiceDate`, `Price`, `Customer ID`, `Country`, en orden.
- **Licencia**: CC BY 4.0, con la cita de RNF09.

## 8. Criterios de aceptación

«Sintético» quiere decir el accesorio que generan las pruebas; «real», el libro de UCI (marca `real_data`). Los nombres de las pruebas están en el plan, sección 24.

| ID | Criterio | Umbral | Verificación |
| --- | --- | --- | --- |
| AC01 | Fuente íntegra | Una huella distinta de la aceptada deja el `.part` sin renombrar, rechaza la corrida y no cambia nada; en modo `local`, una distinta de la registrada también | Unitaria con un servidor local |
| AC02 | Descarga segura | Una redirección a `http://`, a un host fuera de la lista o más allá de `max_redirects`, un cuerpo de más de `max_bytes` y una descarga que pasa `max_seconds` dan V02 y no escriben el archivo final | Unitaria con un servidor local |
| AC03 | Extracción y lectura seguras | Cada variante malformada (miembro de más, con ruta o inflado; hoja faltante o renombrada; columna de más, de menos o renombrada; tipo que no convierte; solapamiento distinto) da su regla y no escribe nada en `data/interim/` | Contrato |
| AC04 | Base canónica | Real: 1.067.371 filas, 22.523 copias quitadas, 1.044.848 líneas; sintético: los recuentos de la verdad del accesorio | Real y contrato |
| AC05 | Roles y neteo | Cada línea en una sola regla, en el orden de la tabla; neteo exacto en un caso a mano; `0 ≤ neta ≤ cantidad`; una anulación posterior a la fecha no cambia nada; el resultado no depende del orden de las filas; real: los conteos de anulaciones con la definición de la D04 del proyecto 02 **[Verificar en U06]** | Unitaria, contrato y real |
| AC06 | Entregas | El lanzamiento, cuatro mensuales y el cierre con sus períodos; la siguiente es siempre la contigua; cada línea en la entrega de su fecha; republicar no duplica; sin pendientes, `no_delivery` | Unitaria e integración |
| AC07 | Validación | Cada variante malformada da al menos su regla; el accesorio válido, 0 bloqueantes; los recuentos de advertencias e informativas son los de la verdad del accesorio; cada regla declara cómo se agrega entre corridas | Contrato |
| AC08 | Sin daño tras un rechazo | El SHA-256 del SQLite, de cada Parquet, del HTML, de cada JSON del sitio y del sello es idéntico antes y después de una corrida rechazada | Integración |
| AC09 | Carga | Filas cargadas = filas de la entrega; todos los controles en 0; recargar desde cero da el mismo contenido; un control que falla deja el almacén como estaba | Integración |
| AC10 | Cortes y etiqueta | Población y etiqueta exactas en un caso a mano; una etiqueta no existe en el almacén antes de `label_end`; real: las poblaciones y tasas de entrenamiento de la sección 4 | Unitaria, integración y real |
| AC11 | Partición y purgas | Cada borde entre bloques cumple `c_anterior + N ≤ c_siguiente`; los cortes de las purgas no entran en ningún bloque; una configuración que lo viola se rechaza con el nombre del borde; en cada sensibilidad, solo los cortes que cumplen | Unitaria |
| AC12 | Sin fuga I: columnas | `build_features` lanza `LeakageError` si recibe o produce una columna de etiqueta, de ventana, el número de cliente, una variable de calendario o cualquiera fuera de la lista permitida; el código de las variables no lee ninguna tabla de etiquetas | Unitaria y estática |
| AC13 | Sin fuga II: truncamiento y perturbación | Las variables de un corte son idénticas a las calculadas con los datos truncados el día anterior; borrar, cambiar o agregar líneas y anulaciones desde el corte no cambia ninguna variable, modelo, calibración, B*, umbral, puntaje ni motivo de esa fecha (igualdad exacta); los parámetros de BG/NBD con la historia truncada en su corte son idénticos | Integración |
| AC14 | Trampa de fuga | Una variable de control que mira la ventana (días hasta la próxima compra) da un AUC ≥ 0,95 en V1 y detiene el lanzamiento (M01) si se la fuerza a pasar la guarda | Integración |
| AC15 | Líneas base | Quintiles de RFM exactos en un caso a mano; BG/NBD igual a `lifetimes` en los datos de prueba del oráculo; cambiar etiquetas de validación o de prueba no cambia ningún parámetro de B1-B5 | Unitaria |
| AC16 | Modelo y controles | Con una señal plantada que RFM no ve (control positivo), el límite inferior del intervalo de AUC(modelo) − AUC(B2) es > 0; con etiquetas que dependen solo del puntaje RFM (control negativo), el intervalo contiene el 0; dos corridas eligen lo mismo y dan probabilidades idénticas | Integración (sintético) |
| AC17 | Calibración | El calibrador del modelo y los de las líneas base se ajustan solo con V1; probabilidades finitas en [0, 1] (M04) | Unitaria |
| AC18 | SHAP aditivo | En cada fila explicada, |Σ SHAP + valor base − log-odds| ≤ `shap_additivity_tol`; una fila que no cumple falla la tarea (M06); una canalización con divisiones categóricas nativas se rechaza antes de explicar; los tres motivos son los de mayor contribución hacia el riesgo | Unitaria |
| AC19 | Umbral, curvas y costos | Beneficio neto exacto en un caso a mano; el umbral sale solo de V2; cada clave de `[costs]` cambia el umbral, el beneficio o la sensibilidad como dice la fórmula; en un accesorio donde F1 marcaría ≥ 95 %, el umbral por costo no lo hace; la curva de ganancia es exacta en un caso a mano | Unitaria |
| AC20 | Base más fuerte | B* sale solo de la validación (cambiar etiquetas de la prueba no la cambia); el desempate es el de RF16; queda en el sello | Unitaria e integración |
| AC21 | Sello y huella | El lanzamiento escribe su parte y la primera evaluación de la prueba la suya; ninguna se reescribe; cada clave de la configuración está en la huella o declarada fuera de ella; cambiar una clave de la huella cambia `config_sha256`; los cálculos sellados solo reciben la vista sellada de la configuración; repetir desde cero con la misma configuración reproduce los valores sellados; con otra configuración, el resultado es `post_seal` y no reemplaza el sellado (M05) | Unitaria e integración |
| AC22 | Resumen después del sello | Un almacén sin las filas selladas de la prueba toma C01-C09 y las cifras de la prueba del sello, cada una reconstruida y comparada con su entrada a 6 decimales, y muestra debajo el análisis posterior al sello | Integración |
| AC23 | Lanzamiento congelado | Las corridas siguientes reusan el artefacto sin cambios; uno con otra huella se rechaza antes de deserializarlo (M03) | Integración |
| AC24 | Puntuación y seguimiento | Cada cliente activo de un corte recibe exactamente un puntaje con sus tres motivos; ningún puntaje cambia después; los conteos del seguimiento son exactos en un caso a mano, con un corte censurado | Unitaria e integración |
| AC25 | Evaluación y criterios | Métricas exactas en un caso a mano de diez filas; el remuestreo toma clientes enteros y da lo mismo con la misma semilla; el texto de cada veredicto coincide con su número; con un resumen desfavorable, el README dice «no supera» | Unitaria y consistencia real |
| AC26 | Sensibilidades | Cada variante usa solo los cortes que cumplen su N y su M; sus resultados se escriben en la evaluación sellada; ninguna función que elige (modelo, calibración, B*, umbral) lee sus tablas | Integración y estática |
| AC27 | Modelo estrella | Claves únicas y no nulas; 100 % de las claves foráneas en su dimensión; relaciones 1:* de filtro unidireccional y activas; esquema de cada Parquet = especificación; el hecho por cliente se escribe en `outputs/private/` y ningún Parquet de `outputs/powerbi/` tiene una columna con el número de cliente | Contrato |
| AC28 | Diseño del tablero | El HTML tiene todas las páginas, visuales, medidas, parámetros y relaciones de la especificación; no carga recursos externos; pesa < 2 MB; un texto con `<script>` aparece escapado; la lista muestra la columna de cliente enmascarada y ningún número de cliente del accesorio aparece en sus bytes | Unitaria |
| AC29 | Exportación para el sitio | Los cinco JSON cumplen su esquema y suman ≤ 200 KB; ninguna clave nombra un cliente y ningún número de cliente del accesorio aparece en sus bytes; ninguna celda publicada tiene menos de 10 clientes y ninguna celda oculta sale por resta; los ejemplos cumplen su regla; el manifiesto se escribe al final y un conjunto mezclado se rechaza; las reglas acumuladas se leen una vez; las cifras son las de los Parquet y del resumen de la misma corrida | Contrato |
| AC30 | Estado y cierre | La corrida queda `running` hasta que `report` la cierra en orden; una falla después de `load` deja `failed` y refresca lo exportado; una `no_delivery` refresca lo exportado; si las escrituras del manejador de fallas fallan, quien llama sigue viendo el error de la tarea | Integración |
| AC31 | Corridas cerradas y entregas ajenas | Cualquier tarea de una corrida `ok` o `no_delivery` se rechaza antes de escribir (salida 2); `load` y toda tarea posterior se rechazan si la corrida no cargó su propia entrega; `load` se rechaza sin una validación aprobada de esa corrida; los registros de la corrida cerrada quedan byte a byte iguales | Integración y punta a punta |
| AC32 | Un solo escritor | Un segundo escritor se rechaza (salida 2) sin escribir nada; soltar el bloqueo mientras otro proceso tiene el archivo abierto nunca levanta y deja el resultado de la tarea en pie; una toma anidada cuya reescritura falla nunca deja el bloqueo; un número de proceso reusado no se toma por el dueño; otro hilo se rechaza | Unitaria e integración |
| AC33 | CLI | Códigos de salida 0, 1, 2 y 3; una combinación de opciones incompatible sale con 2 antes de escribir; cada opción documentada cambia el resultado (una prueba por opción) | Punta a punta |
| AC34 | Modo rápido aislado | Desde un clon limpio y desde otro directorio de trabajo, la repetición rápida termina y nada fuera de `data/quick/` cambia | Punta a punta |
| AC35 | DAG y Docker | Identificadores y orden de tareas iguales a los de la CLI; programación mensual, sin catchup, una corrida y una tarea activas; `pip check` limpio en la imagen, con SHAP y numba; `airflow dags test` dos veces seguidas en modo rápido (lanzamiento y `M2011-08`) con el modelo congelado idéntico; un rechazo falla sin reintentos | Estática y Docker |
| AC36 | Compose endurecido | Interfaz en `127.0.0.1`; cada secreto con `${VAR:?}`, incluida la contraseña de PostgreSQL y la de la cadena de conexión; ningún valor literal de secreto (la prueba recorre cada valor); montajes de solo lectura; imágenes con versión y resumen; `set -e` en la inicialización; nombre de proyecto propio | Estática |
| AC37 | Punta a punta real | La repetición completa cumple RNF02 y RNF03 con tiempos y memoria medidos y el contador nombrado; cada Parquet versionado ≤ 25 MB | Real |
| AC38 | Reproducibilidad | Dos repeticiones completas seguidas dan el mismo contenido en cada Parquet y JSON, sin las columnas de la corrida | Integración (sintético) |
| AC39 | Dependencias | Cada módulo de terceros que importa `src/` es una dependencia directa fijada en `requirements.txt`; las que el landing no declara tienen su fila en `LANDING-EXPANSION.md` con el 04, y ninguna decisión llama transitiva a una directa | Estática |
| AC40 | Documentación | README con los títulos del plan en orden; diccionario de cada columna de cada Parquet con unidad; cada decisión con sus siete campos; runbook R1-R14; el número de pruebas que dicen los documentos es el de la colección de la sesión; cada cifra de memoria nombra su contador; el bloque de resultados es el del resumen; las advertencias abiertas del README son las de `docs/review-advisories.md`; cada prueba nombrada en el plan, sección 24, existe; todo esto en el último commit de corrección | Unitaria sobre los Markdown |
| AC41 | Suite rápida | La suite por defecto termina en ≤ 120 s, medida dos veces en reposo y anotada en la ficha del modelo; una sesión completa que pasa el límite termina con falla y dice por cuánto | Medición y unitaria |
| AC42 | Nada publicado señala a un cliente | Ningún número de cliente del accesorio aparece en ningún byte versionado de `outputs/powerbi/`, `outputs/site/`, `reports/`, `dashboard/` ni `docs/figures/`, ni en los registros y estados de corrida; las figuras se dibujan solo desde los archivos del sitio verificados | Contrato e integración |

### 8.1 Criterios del modelo, fijados antes de construir

Se fijan aquí, antes de escribir código, y se confirman en Git con este plan. **Prueba**: los cortes 2011-08-01 y 2011-09-01, con los clientes activos en los 90 días anteriores a cada uno; etiquetas conocidas al 2011-11-29. **Unidad**: la fila cliente × corte; un cliente puede estar en los dos cortes. Se evalúa el modelo congelado del lanzamiento, calibrado en V1, con el umbral `t*` elegido en V2 con los costos por defecto (`offer_cost = 5`, `rescue_rate = 0,2`, `retained_value = 50`: punto de equilibrio 0,5; D22). **B*** es la base más fuerte entre B2 (RFM), B3 (BG/NBD) y B4 (frecuencia), elegida por su AUC en la validación en el lanzamiento y sellada (RF16).

Dos columnas dicen qué se vio antes de fijarlos (D18): lo que vio la investigación (en el primer corte de validación) y lo que vio el agente de planificación (solo los cortes de entrenamiento, sección 4).

| ID | Criterio | Umbral | Visto por la investigación | Visto por el planificador |
| --- | --- | --- | --- | --- |
| C01 | Discriminación frente a RFM | AUC(modelo) > AUC(B2) | Sí: 0,769 frente a 0,784 en 2011-03-01 | Solo RFM en el entrenamiento (0,737), sin modelo |
| C02 | Mejora fuera del ruido frente a RFM | Límite inferior del intervalo del 95 % de AUC(modelo) − AUC(B2) > 0 | Sí: de −0,033 a 0,005 en 2011-03-01 | No |
| C03 | Mejora fuera del ruido frente a la base más fuerte | Límite inferior del intervalo del 95 % de AUC(modelo) − AUC(B*) > 0 | En parte: B3 0,776 y RFM 0,784; B4 no | En parte: en el entrenamiento, B4 0,746, B2 0,737 y B3 0,732, sin modelo |
| C04 | Captura en el 10 % superior | Las bajas entre el 10 % de mayor riesgo del modelo (por corte, `ceil(0,10 × n)`) > las del 10 % de B* | En parte: 18,0 % frente a 18,2 % de RFM en 2011-03-01 | No |
| C05 | Beneficio neto frente a la base más fuerte con su propio umbral | BN(modelo, `t*`) > BN(B*, `t*_B*`), los dos umbrales elegidos en V2 con el mismo procedimiento | No | No |
| C06 | Conviene actuar con el modelo | BN(modelo, `t*`) > máx(BN(contactar a todos), 0) | No | No |
| C07 | Calibración en la prueba | ECE ≤ 0,03 (10 intervalos de igual ancho) y \|media de p − tasa observada\| ≤ 0,02 | No | No |
| C08 | Brier frente a la base más fuerte | Brier(modelo) < Brier(B* calibrada en V1) | No | No |
| C09 | Sensibilidad a los costos | En cada punto de equilibrio de 0,10 a 0,90, de a 0,05, con los umbrales elegidos en V2: BN(modelo) ≥ BN(B*) | No | No |
| C10 | Por corte y sensibilidades (informativo) | Sin umbral: AUC, tasa de bajas y diferencia con B2 y B* por corte de prueba; y para N = 60, N = 120, M = 180 y el entrenamiento sin diciembre, AUC del modelo, de B2 y de B* y el intervalo de la diferencia. El criterio es que esté escrito y sea consistente | No | Solo las tasas de entrenamiento de cada variante (sección 4) |

Definiciones que fijan los criterios:

- **AUC**: `roc_auc_score`, con los empates contados por mitades (las reglas tienen pocos valores distintos). El puntaje de riesgo de B2 es −(puntaje RFM); el de B3, −(compras esperadas); el de B4, −(días de compra de 365 días); el de B1, la recencia en días.
- **Intervalo del 95 %**: remuestreo pareado de **clientes** con reposición (cada cliente remuestreado aporta todas sus filas de los cortes de prueba), 1.000 remuestras, semilla 0, los mismos clientes para los dos puntajes; percentiles 2,5 y 97,5 de la diferencia; una remuestra con una sola clase se descarta y se cuenta (D21).
- **Beneficio neto (BN)**: por cliente contactado, `churned × rescue_rate × retained_value − offer_cost`; 0 por cliente no contactado; total en u. y por cada 1.000 clientes. Con los costos por defecto, `BN = Σ_contactados (10 × churned − 5)`.
- **Umbral `t*`**: el valor de la grilla 0,01 a 0,99 que maximiza el BN en V2 sobre la probabilidad calibrada; en un empate, el mayor (menos contactos). Para B* en C05 y C09, el mismo procedimiento sobre su probabilidad calibrada en V1.
- **ECE**: `Σ_b (n_b / N) · |media de p en b − tasa observada en b|`, con 10 intervalos de igual ancho en [0, 1]. **Brier**: `mean((p − churned)²)`.
- Un criterio que no se puede calcular (por ejemplo, un corte con una sola clase) queda `passed = false` con el motivo, nunca aprobado. Un empate no supera: los criterios con «>» se cumplen solo con una diferencia a favor. Un criterio que no se cumple se informa con su número en el resumen, el README, la ficha del modelo, el tablero y el sitio.

**Lo esperable, dicho antes de medir.** La primera mirada de la investigación no superó a RFM (−0,014, con un intervalo de −0,033 a 0,005), como el modelo del proyecto 03 no superó a su regla de dos variables; y en el entrenamiento, la frecuencia sola ordena mejor que RFM y que BG/NBD. Con eso: el modelo probablemente **no cumpla C02 ni C03** (no supera a RFM ni a la base más fuerte fuera del ruido), quede cerca de RFM en C01 y C04 (un empate no supera), y no cumpla C07, porque la prueba (agosto a noviembre) tendría menos bajas que los cortes de marzo y abril en que se calibra (sección 4, D09). C06 debería cumplirse, como para cualquier orden razonable, porque contactar solo a los de riesgo alto rinde más que contactar a todos o a nadie con el punto de equilibrio en 0,5. C05, C08 y C09 son inciertos. Si es así, el resultado del proyecto es que **una regla que cualquiera escribe con las facturas (cuántas veces compró en el último año, o RFM) ordena a los clientes igual que el modelo**, y que el modelo agrega una probabilidad en escala y los motivos de cada cliente, no un mejor orden; el README, la ficha, el tablero y el sitio lo dicen con esos números (D18).

## 9. Plan de pruebas

Cinco niveles con pytest en el `.venv` del proyecto, con la prueba primero en cada unidad (plan, sección 24). Marcas: `real_data` (necesita el zip real en `data/raw/`), `docker` (necesita Docker), `oracle` (compara con `lifetimes`, en la suite por defecto). Por defecto: `-m "not real_data and not docker"`.

| Nivel | Qué prueba | Requerimientos | Criterios |
| --- | --- | --- | --- |
| Unitarias | Configuración y rutas, clasificación de claves y huella, descarga con un servidor local, neteo, cortes y etiqueta, variables y listas, partición, líneas base y BG/NBD, modelo, calibración, SHAP, umbral y curvas, sello, evaluación, criterios, bloqueo, especificación del modelo semántico, HTML, compose y DAG estáticos, dependencias, presupuesto de la suite | RF01-RF06, RF11-RF20, RF26, RF28 | AC01, AC02, AC05, AC10-AC12, AC15, AC17-AC21, AC25, AC28, AC32, AC36, AC39, AC41 |
| Contrato de datos | Contrato del zip y del libro, reglas sobre accesorios válidos y malformados, esquema de cada Parquet y de cada JSON, integridad referencial, referencias de DAX, números de cliente ausentes | RF03-RF05, RF08, RF25, RF27 | AC03, AC04, AC07, AC27, AC29, AC42 |
| Integración | Entregas, carga y controles, rechazo sin daño, sin fuga por truncamiento y perturbación, trampa de fuga, controles positivo y negativo, sello, resumen después del sello, lanzamiento congelado, puntuación, seguimiento, sensibilidades, estado y cierre, corridas cerradas, reproducibilidad | RF07, RF09, RF10, RF17, RF20-RF24, RF28 | AC06, AC08, AC09, AC13, AC14, AC16, AC20-AC24, AC26, AC30, AC31, AC38 |
| Punta a punta | CLI en modo rápido y aislada; repetición real (`real_data`); `airflow dags test` en Docker (`docker`) | RF28 | AC33-AC35, AC37, AC41 |
| Documentación | Títulos del README, diccionario, siete campos, runbook, número de pruebas de la sesión, contadores de memoria, bloque de resultados, advertencias abiertas, pruebas nombradas en el plan | RF29 | AC40 |

Accesorios (plan, sección 24): un generador escribe un zip con un libro de dos hojas y las 8 columnas reales, con clientes sintéticos cuyos días de compra siguen un proceso conocido, anulaciones que se emparejan y que no, líneas sin cliente, códigos de servicio, `PADS`, vales, una factura «A», copias exactas en la ventana común de las hojas y repeticiones internas, un texto con `<script>`, y números de cliente de un rango propio de cinco cifras fuera del real (12346 a 18287), para que una búsqueda en bytes los encuentre. Variantes de señal: `none`, `irregular_gaps` (control positivo: la baja depende de la irregularidad de las brechas, que RFM no ve) y `rfm_only` (control negativo: la baja depende solo del puntaje RFM). Una variante malformada por regla bloqueante. Dos tamaños: el estándar y uno chico (300 clientes) para las pruebas de una fila. Ninguna prueba ni ninguna persona calcula una métrica en los cortes de prueba reales antes de la corrida de U29, y ninguna prueba `real_data` pasa del lanzamiento antes de U29 (D19).
