# Evaluación final independiente

Qué se evaluó, quién lo evaluó, qué encontró y cómo se resolvió cada hallazgo. Es el control que el proyecto dejó para el final (plan, sección 28): lo hizo un agente que no escribió el código, sobre una copia aparte del commit `e28b1fb`, y su único bloqueante y sus advertencias se corrigieron o se dejaron dichos después (L55, L56). Otro agente comprobó esas correcciones («Comprobación»). Lo que describe este documento está al día con `816289e`, el último commit de código, y con `94843fd`, el último commit de documentación que lo precede; todo lo que dice de quién hizo qué, con qué modelo y con qué cifras es lo que consta en el registro del documento de seguimiento (`odd/tasks/portfolio-projects.md`, L55 y L56). Las únicas cifras de este documento que el registro todavía no tiene son las de «La medición de esta sincronización», al final.

## Quién evaluó y cómo

Un agente de Claude Code con el modelo Opus, **distinto de los agentes que construyeron el proyecto** y sin su contexto de trabajo. Trabajó en solo lectura sobre el repositorio: clonó `e28b1fb` con `git clone --no-hardlinks` en una carpeta temporal y copió el zip y el libro reales de `data/raw/`, cuyas huellas SHA-256 son las fijadas. Armó su propio entorno con `py -3.11 -m venv` desde `requirements-dev.txt` (`pip check` limpio) y no instaló el paquete (`PYTHONPATH` en `src`, como dice el README). Corrió la suite rápida dos veces en reposo, `-m real_data`, `-m docker`, una repetición real completa más la corrida sin entrega, en una copia sin `reports/`, `outputs/`, el HTML ni las figuras, como D85, y unas veinte sondas en copias del modo rápido. No corrió ninguna revisión nativa.

Recalculó las cifras con código propio, sin usar el del proyecto: un lector del libro en OOXML (`zipfile` y `ElementTree`, sin `openpyxl`), su propio retiro del solapamiento, los roles, el neteo en LIFO, los cortes y las etiquetas, su propio RFM, su propio BG/NBD (igual al de `lifetimes`: r 0,9084, α 75,76, a 0,1737, b 108,27; el óptimo de SciPy del proyecto es apenas menor, con log-verosimilitud −59.505,3611, como ya dicen los requerimientos, sección 4), la calibración isotónica, un AUC por rangos y un remuestreo por clientes. Su carpeta de trabajo, que tenía datos reales de clientes, la borró el agente que lo lanzó (L55), y la imagen `churnrisk-airflow:3.4.0` que dejó la prueba de Docker la borró él con `docker rmi`.

## Veredicto por especificación

| Especificación | Veredicto | Evidencia |
| --- | --- | --- |
| S1 | Cumple | Existe `04-Ecommerce-Churn-Risk/` |
| S2 | Cumple | Investigación, requerimientos, código, diseño en HTML, pruebas y documentación; la evaluación es esta |
| S3 | Cumple | El README tiene los 13 títulos del plan, en orden (la prueba de documentación pasa) |
| S4 | Cumple | `dashboard/powerbi-design.html`: 107.214 bytes, sin recursos externos, con 15 celdas enmascaradas |
| S5 | Cumple | Las herramientas fuera del landing (SHAP, SciPy, `lifetimes` y otras) están en `LANDING-EXPANSION.md` con el 04 |
| S6 | No aplica | |
| S7 | Cumple | |
| S8 | En parte | L44 a L53 coinciden (Haiku investigó, Opus planificó y programó, Sonnet corrigió); los modelos de U30 y U31 no estaban en el registro (B1) |
| S9 | Cumple | `SITE-UPDATES.md`, filas 1 a 16 |
| S10 | En parte | La documentación sigue la estructura del proyecto 01; faltaban este documento y la página del sitio (plan, sección 28) |
| S11 | Cumple | L46 a L53 |
| S12 | En parte | T5 seguía en curso, como se esperaba |

## Criterios de aceptación y requisitos medidos

- **Cumplen:** AC01 a AC42, salvo AC40 (en parte). AC01 a AC03 los cubre la suite, no una sonda. Recalculó AC04 (1.067.371 filas, 22.523 copias del solapamiento, 1.044.848 líneas), AC05 (1.706 anulaciones que quedan con unidades, igual al último valor de V22) y AC10 (los siete cortes de entrenamiento y 15.297, 3.942 y 43,2 %). AC06, AC07 y AC09 los probó con las corridas y con las 39 reglas acumulativas del sitio (0 diferencias). En AC08, un rechazo de V01 sale con 3 y deja intactos el almacén, los Parquet, el HTML, los archivos del sitio y el sello; solo cambian `reports/validation/latest.*`, como se diseñó. AC11 a AC21: las sondas y su recálculo (las 55 claves de la huella cambian `config_sha256` y las 27 no sellados no; la guarda rechaza `days_to_next_purchase` por su nombre; saltando la guarda, el AUC de V1 es 0,9991 y M01 detiene el lanzamiento; la aditividad de SHAP se cumple en las 3.935 filas de la prueba, con error máximo de 7,5e-15, y los tres motivos guardados coinciden en las 3.935). AC22 a AC39: las sondas y la suite (AC35, `-m docker`, 2 pasaron; AC37, la repetición real; AC38, dos copias rápidas dan sellos iguales y la repetición real reproduce el contenido). AC41: 109,69 s y 108,99 s. AC42: sus propios barridos de bytes, 0 números de cliente reales en lo versionado y 0 del accesorio en 58 archivos de salidas del modo rápido, con los estados de corrida.
- **En parte, AC40:** la prueba `test_privacy.py::…` que nombra el plan no existía (D88 lo decía) y las afirmaciones sobre U30 y U31 caían bajo B1.

| Requisito | Medido | Límite o nota |
| --- | --- | --- |
| RNF01 | El contenido se reproduce | |
| RNF02 | `replay` 305,1 s y la corrida sin entrega 3,3 s; el lanzamiento unos 121 s; las corridas mensuales de 26 a 63 s; la repetición rápida menos de 24 s; la prueba de Docker 147,6 s | Dentro de todos los topes |
| RNF03 | `PeakWorkingSetSize` 1.880,4 MB, leído con su propia llamada a `GetProcessMemoryInfo` e igual al que registra el flujo; `PeakPagefileUsage` 3.677,8 MB, informativo | Dentro de 2.560 MB; los documentos nombran bien el contador |
| RNF10 | 26 Parquet, 158.405 bytes (el mayor, 28.083); archivos del sitio, 71.424 bytes | Dentro |
| RNF15 | La suite rápida, unos 109 s | Dentro del límite de 120 s, sobre el presupuesto de trabajo de 100 s (dicho en los documentos) |

## Los criterios C01 a C10

Lo que dicen el resumen, el README, la ficha del modelo, D85, `SITE-UPDATES.md` y los archivos del sitio (que coinciden entre sí), contra lo que recalculó el evaluador.

| | Declarado | Recalculado | Veredicto |
| --- | --- | --- | --- |
| C01 | AUC 0,7447 contra RFM 0,7464 | 0,74466 contra 0,74638 | Coincide, no supera |
| C02 | Diferencia −0,0017, intervalo de −0,0145 a 0,0110 | −0,00172, de −0,01445 a 0,01098 | Coincide, no supera |
| C03 | Diferencia −0,0043, intervalo de −0,0166 a 0,0078 | −0,00428, de −0,01664 a 0,00781 | Coincide, no supera |
| C04 | 253 contra 268 bajas en el 10 % de mayor riesgo | 253 y 268 | Coincide, no supera |
| C05 | Beneficio neto por 1.000 clientes: 209,7 contra 238,9 | 209,657 y 238,882 | Coincide, no supera |
| C06 | 209,7 contra el máximo entre −1.559,1 y 0 | Igual | Coincide, cumple |
| C07 | ECE 0,089 y sesgo 0,088 | 0,08901 y 0,08799 | Coincide, no cumple |
| C08 | Brier 0,1976 contra 0,2030 | 0,19760 y 0,20297 | Coincide, cumple |
| C09 | El modelo deja al menos lo de B* en 9 de los 17 puntos | 9 (el lado de B* lo recalculó; el del modelo salió del Parquet) | Coincide, no supera (ver A5) |
| C10 | AUC por corte 0,744 y 0,746; las variantes | Igual; los AUC de RFM y de B* en las variantes, a menos de 0,001 | Coincide |

También recalculó: la prueba (3.935 filas con 34,4 % de bajas), los cortes (2.017 y 1.918), el umbral 0,55, la parte contactada (26,5 %), el PR-AUC 0,5607, los umbrales y beneficios de las reglas (B1 0,55 y −47,0; B2 0,61 y 209,7; B3 0,60 y 238,9; B4 0,59 y 106,7) y la elección de B*: BG/NBD, con AUC 0,7673 en V1 y V2 juntas contra 0,7666 de la frecuencia.

## Lo que el evaluador sondeó

- **Fuga.** Alteró el accesorio desde 2011-09-01 (líneas borradas y cambiadas, y 40 anulaciones fechadas en el corte que netean compras anteriores): los datos cambiaron, pero con fecha de cálculo 2011-08-31 las variables, los puntajes, los motivos, los bloques, el registro, los calibradores y el sello del lanzamiento son idénticos, y después de todas las entregas los del corte hasta 2011-09-01 también. Con la historia truncada desde 2010-12-10, los parámetros de BG/NBD del lanzamiento son los mismos; B* y el umbral cambian, con razón, porque cambian las etiquetas.
- **Sensibilidades.** `eval_variants` está vacía después del lanzamiento y tiene 44 filas después de M2011-11; ningún módulo que elige la lee.
- **Opciones de la línea de comandos y claves de `[costs]`.** `--only` con `--from`, `--run-key` solo, un `--until` malo y una tarea desconocida salen con 2 y dejan `data/` intacta; todas las opciones y las nueve claves de `[costs]` hacen lo que dicen (`offer_cost` no mueve la sensibilidad, correcto: la sensibilidad lo restablece en cada punto de equilibrio); `docs-sync` en modo rápido sale con 2, como está documentado.
- **El sello.** La corrida M2011-11 con `offer_cost = 8` salía como posterior al sello sin escribir la parte de la prueba, y la siguiente, con la configuración sellada, la escribía con la fecha de cálculo 2011-12-09 y no 2011-11-30; el sello se escribía así pero nunca se cambiaba (A1). Con un almacén nuevo, el sello limpio y `offer_cost = 8`, el resumen toma C01 a C09 del sello, idénticos a los sellados, y pone debajo el bloque posterior al sello (A2).
- **Corridas.** `build_cuts` de una corrida que no cargó su entrega y `load` sin validar salen con 2 sin cambiar nada; en una corrida cerrada, `--from`, `--only`, `task` y `deliver` salen con 2 con los archivos iguales; una corrida nueva se bloquea (1, R4) mientras una vieja fallida tiene una entrega cargada, y después de cerrarla todas las tareas con su clave salen con 2; con las tres escrituras del manejo de fallas fallando, quien llama ve el error de la propia tarea.
- **El bloqueo.** Con otro proceso que tiene el archivo 1 s, la liberación se logra; con 4 s, vuelve sin levantar a los 2 s y deja el bloqueo, que rechaza incluso al mismo proceso vivo (A12). Un segundo escritor sale con 2 sin escribir; un dueño matado deja el bloqueo viejo y hay que borrarlo a mano (plan, sección 22; D76; R9).
- **Modo rápido y compose.** Dos copias rápidas a la vez, una desde otro directorio, salen con 0 sin cambiar nada fuera de `data/quick/` y con sellos iguales salvo las claves de corrida. `docker compose config` sin las claves sale con 1 nombrando la que falta, una vez por cada una de las cuatro; el enlace en 127.0.0.1, los montajes de solo lectura y las imágenes fijadas por resumen se confirman.
- **Privacidad.** Cero números de cliente reales en lo versionado y cero del accesorio en las salidas rápidas (las coincidencias de cinco cifras son recuentos, huellas o el rango documentado). Ninguna celda mostrada tiene menos de 10 ni se recupera por resta. Dentro de celdas de al menos 10 hay cuentas chicas: `fact_cut_country` tiene 17 contactados y 6 que se fueron, `fact_cut_band` 5, 4 y 3, y `retention.json` por país, 4 (por ejemplo 3 contactados de 14); y diez `customers_affected` de validación son menores que 10 (A9).
- **La curva de costo.** `nb_model = 0` no es un piso: es el extremo de 0,99 de la grilla sin contactar a nadie, mientras la probabilidad isotónica de B3 llega a 1,0 (el 0,48 % de las filas de V2 está en 0,99 o más), así que B* no puede no contactar a nadie; la curva es la de V2 y está rotulada así (A6).
- **El tablero.** El filtro de la página 3 estaba atado a `dim_date`, con 739 días para las 6 fechas de cálculo de `fact_tracking`; `dim_as_of` no tenía relación ni visual; en la página 1, `fact_reason_summary` se relaciona solo con `dim_cut` y `dim_reason`, así que el país y la banda no podían filtrar el gráfico de motivos; la fila de C07 del resumen y del README tenía 8 barras en lugar de 6 (A4, A10).
- **La documentación.** Las 88 decisiones tienen sus 7 campos; las 162 advertencias del documento de entonces eran 87 corregidas, 23 dejadas con evidencia y 52 abiertas, y las 52 coinciden con la lista del README; los 83 nombres de advertencia del registro están; el paso a paso cubre cada commit del proyecto; se recogen 856 pruebas en `3ec6052`, como decían los documentos.

## El bloqueante

**B1, documentación que el registro no tenía (RNF14, AC40).** El registro en `e28b1fb` terminaba en L53, que pone a U30 y U31 después de la evaluación independiente, y varios documentos decían como hechos cosas que solo un L54 podía tener: el README («Un agente con Opus escribió este README…», y «29 unidades» cuando eran 31), el paso a paso («U30 (Opus)… 856 pruebas… 109,14 s y 106,60 s» y «U31 (Opus)»), la ficha del modelo (108,19 s y 107,05 s con 869 pruebas, y 52,38 s al terminar U31), D87 y D88 («Quién: agente de programación (Opus)») y la línea de tiempos de `SITE-UPDATES.md`. Las cuentas de 856 y 869 pruebas coincidían con las recogidas en `3ec6052` y `e28b1fb`, y los tiempos eran verosímiles (midió 109,69 s y 108,99 s), pero ni los modelos ni los tiempos constaban en el registro ni en `git log`. Para reproducirlo: `sed -n '80,89p' odd/tasks/portfolio-projects.md` y buscar esas cadenas. La corrección mínima: agregar L54 con U30 y U31 (commits, modelos, la suite medida dos veces, `real_data`) y corregir «29 unidades».

**Cómo se corrigió.** `e87dd0e` registró L54; L55 registró la evaluación y los tiempos de U30 como los informó quien la escribió; `ab8f0e4` hizo que cada afirmación del README, la ficha, el paso a paso, D87, D88 y `SITE-UPDATES.md` diga lo que dicen L54 y L55, y que el README diga 31 unidades. La comprobación encontró que el README, línea 223, seguía diciendo que la prueba de Docker nunca se corrió (ver «Comprobación»); esta sincronización la corrige.

## Las advertencias, una por una

Cada una, con su estado: **corregida** (con el commit), o **abierta** (dicha aquí y en `docs/review-advisories.md`, sección «Evaluación», con el motivo del registro, L55). Los commits son los de la tanda de correcciones (L55, L56).

| Id | Hallazgo | Estado |
| --- | --- | --- |
| A1 | La parte de la prueba del sello se podía escribir después de una evaluación posterior al sello, con `as_of` 2011-12-09 | **Corregida** en `c139ca2` (D89, R13): se rechaza antes de escribir |
| A2 | En un resumen posterior al sello, los `costs` de arriba eran los de la corrida, junto a cifras selladas | **Corregida** en `969f2b4` (D92) |
| A3 | El resumen versionado nombra claves de corrida del sello (18:20 y 18:23) distintas de las del sello (17:46 y 17:49) | **Abierta**: lo dice D85 (el sello es el de la primera corrida y las salidas, las de la repetición); el registro lo deja así |
| A4 | La barra sin escapar de C07 parte la fila | **Corregida** en `1829c5f` (D91) |
| A5 | El veredicto de C09 se lee como 9 fallas cuando 9 son los puntos donde el modelo cumple (falla en 8); y C09 es frágil: en 0,10, B* con los parámetros del óptimo de `lifetimes` da 2.501,9 contra 2.502,2 del modelo, lo que da vuelta un punto | **Corregida** en `1829c5f` (D91) en el texto del resumen, sin tocar lo sellado; la fragilidad queda dicha |
| A6 | El 0 del modelo contra los valores negativos de B* en la curva de costo sale de la grilla | **Abierta**: ninguna cifra publicada depende de eso (la misma clase que `U29-4/R3-001`) |
| A7 | `b_star.auc_valid` = 0,766 es el AUC de V2 sola, rotulado `chosen_on: valid`; el que decidió es cerca de 0,767, y B3 le gana a B4 por 0,0008 | **Abierta** |
| A8 | `capture_10` de las reglas con empates depende del orden interno (B4 234 contra 244,6 esperado; B2 259 contra 260,4) | **Abierta**: C04 usa B3, que no tiene empates |
| A9 | Cuentas chicas dentro de celdas de al menos 10 y cuentas de validación de menos de 10 | **Abierta**: según el evaluador, aceptable pero no por la letra de RNF12; D27, D68, D85 y D86 lo dicen; publicar «<10» o exceptuarlo en RNF12 es del dueño, y el registro no cambia el requisito sin él |
| A10 | Los tres defectos del tablero (filtro de 739 días, `dim_as_of` sin uso, país y banda que no llegan al gráfico de motivos) | **Corregida** en `aad019b` (D90) |
| A11 | La prueba de privacidad del plan no existía | **Corregida** en `969f2b4` y `07d2a54` (D92) |
| A12 | Un bloqueo que quedó por una liberación fallida rechaza a su propio proceso vivo, y uno viejo se borra a mano | **Abierta**: R9 documenta el borrado; reconocer la ficha del dueño queda para otra tanda |
| A13 | La prueba de Docker dejaba la imagen `churnrisk-airflow:3.4.0` | **Corregida** en `969f2b4` (D92) |
| A14 | `test_delivery` se recogía como prueba (una de más en la cuenta) y había un escape inválido en `test_star_schema.py:351` | **Corregida** en `969f2b4` (D92) |
| A15 | Una corrida rechazada porque otra más vieja tiene la entrega sale con 1 y deja un estado `failed` | **Abierta**: R4 lo documenta |
| A16 | El «77,9 %» de `SITE-UPDATES.md` no nombraba su corte (es el del 2011-09-01) | **Corregida** en `ab8f0e4` |
| A17 | Los ejemplos de validación versionados llevan `line_id`, código de producto y fecha, que señalan una línea de la fuente pública | **Abierta**: riesgo bajo; la fuente es pública |
| A18 | La suite rápida, sobre el presupuesto de trabajo de 100 s | **Abierta**: `816289e` la bajó (ver abajo) sin llegar a 100 s |

## Las correcciones

Decidió el registro (L55, plan 28.2) y escribió un agente con Opus, cada una con la prueba primero, un commit por grupo de hallazgos (L56):

- `c139ca2` **A1** (ítem 1, sola; D89). Seis de siete mutaciones hacen fallar la prueba nueva; la séptima es equivalente. Un diferencial de 11 comandos de la línea de comandos solo cambió en los 2 que la corrección rechaza, y una repetición rápida limpia da el mismo sello.
- `aad019b` **A10** (D90). R19, `dim_as_of` → `fact_tracking`; el filtro de la página 3 sobre `dim_as_of`; el gráfico de motivos rotulado como de todo el corte; el HTML regenerado por el renderizador.
- `1829c5f` **A4 y A5** (D91). Las celdas con las barras escapadas y C09 dicho en claro, solo en el Markdown del resumen, porque cada `verdict_es` es parte del sello. Comprobado con una repetición real completa en una copia nueva (298,8 s): su sello es igual al versionado salvo las dos claves de corrida.
- `969f2b4` **A11, A2, A14 y A13** (D92).
- `07d2a54` La prueba de privacidad toma lo sellado de la historia rápida y la repetición compartida termina antes de la corrida de la prueba, porque la suite estaba sobre el límite (D92).
- `ab8f0e4` **B1 y A16**, en la documentación.

Fuera del conjunto de la evaluación, porque con la suite en 119,97 s no quedaba margen bajo el límite, el registro pidió una tanda de velocidad aparte, y la escribió un agente con Sonnet: `816289e` (`gc.set_threshold(200_000, 100, 100)` en `tests/conftest.py`; sin el cambio 110,89 s y 111,98 s, con él 108,27 s y 107,36 s; las 880 pruebas recogidas, idénticas) y `94843fd` (D93 y los tiempos). El presupuesto de trabajo de 100 s sigue sin alcanzarse; bajar más pide `pytest-xdist` (D35, un pendiente del dueño) o cambios del producto.

Las cifras de la suite en cada punto, las del escritor (L56): 879 pruebas pasaron y 1 se omitió (880), 122,34 s y 123,43 s en `969f2b4` (sobre el límite de 120 s, de ahí `07d2a54`), 118,99 s y 119,17 s en `07d2a54`, 119,97 s en `ab8f0e4`; `-m real_data`, 9 de 9 en 55,68 s; `-m docker`, 2 de 2 en 95,44 s; el SHA-256 del sello no cambió (`128a7851…`); entre las salidas versionadas solo cambiaron `dashboard/powerbi-design.html` y `reports/evaluation_summary.md`.

## Las advertencias que se dejaron, y por qué

El registro (L55) las dejó como advertencias dichas, no corregidas: A3 (D85 lo explica), A6 (ninguna cifra depende de eso), A7, A8 (C04 usa B3, sin empates), A12 (R9 documenta el borrado a mano), A15 (R4 lo documenta), A17 (la fuente es pública), A18 (la suite sigue sobre el presupuesto de trabajo, dentro del límite) y A9. A9 es la única que el evaluador dijo que no cumple la letra del requisito: una cuenta publicada de 3 es en sí un agregado de 3 clientes; la fuente es pública y la baja se deduce de ella, y lo único nuevo es la marca de contacto del modelo. Como D27, D68, D85 y D86 lo dicen, el registro la mantiene como advertencia, y cambiar RNF12 o publicar «<10» es una decisión del dueño.

## Comprobación

Otro agente de Claude Code con Opus, que no construyó ni corrigió el proyecto, rehízo la prueba de cada corrección (L56). Trabajó en dos clones aparte (`git clone --no-hardlinks`), uno de `e28b1fb` y otro de `94843fd`, con copias de trabajo separadas de ambos para las sondas. Armó un entorno con Python 3.11.1 desde `requirements-dev.txt` (`pip check` limpio), copió el zip y el libro reales, cuyas huellas coinciden con la configuración, y puso `PYTHONPATH` en el `src` de cada copia. Corrió la suite rápida dos veces y una tercera sin los umbrales de D93, `-m real_data` y `-m docker` en las dos copias, una repetición real completa en una copia de `94843fd` y los diferenciales de la línea de comandos en el modo rápido de las dos copias (26 y 19 pasos). No corrió ninguna revisión nativa, no leyó ningún `.env` y dejó intacto el repositorio original. Su carpeta de trabajo, con datos reales de clientes, la borró el agente que lo lanzó (L56).

**Veredicto: B1 está cerrado en todo lo que la evaluación nombró; en la línea 223 del README quedaba una frase falsa (la que decía que la prueba de Docker nunca se corrió) y esta sincronización la corrige. Todas las correcciones hacen lo que dicen en `94843fd`, ninguna causó un bloqueante nuevo y no hay diferencia que nadie haya pedido.**

- **B1.** En `e28b1fb` se reproduce: el registro termina en L53 y el README, el paso a paso y la ficha dicen lo de U30 y U31. En `94843fd`, contra L54 y L55 tal como estaban, cada afirmación de U30 y U31 la tiene el registro, «29 unidades» ya no está y las declaraciones de Docker de la línea 59 y la 225 del README, de la ficha (RNF02), del runbook (R8) y del paso a paso son correctas. Quedaba la línea 223 del README, que terminaba «…estos pasos todavía no se corrieron en este proyecto: los correrá la evaluación independiente», contra L55 (`-m docker`, 2 pasaron en 147,6 s) y contra la línea 225 del mismo archivo. Se reproduce con `grep -n "los correrá la evaluación independiente" 04-Ecommerce-Churn-Risk/README.md`. **Corregida en esta sincronización:** la línea dice ahora que la prueba pasó en la evaluación (`e28b1fb`, 2 pasaron en 147,6 s) y en la comprobación (`94843fd`, 2 pasaron en 90,48 s) y que solo los pasos con el archivo real siguen sin correrse.

Cada corrección, corrida en los dos clones con el mismo accesorio (`make-fixture` con SHA-256 `d53d7760…`):

| Corrección | `e28b1fb` | `94843fd` | Veredicto |
| --- | --- | --- | --- |
| A1 | Con la repetición rápida hasta `M2011-10` y `run` con `[costs] offer_cost = 8.0`, sale con 0 y marca `post_seal`; la corrida siguiente con el sello escribe la parte de la prueba con `as_of` 2011-12-09 | Sale con 2 con el mensaje de R13 («…evaluaría la prueba (entrega M2011-11, cálculo al 2011-11-30)… difiere costs.offer_cost… No se escribió nada.») y el árbol de `data/quick` no cambia; el mismo rechazo sale de `task fetch_source`, de `replay`, de `run --only` y de `task deliver` de una corrida abierta con el sello; la corrida con el sello escribe la parte de la prueba con `as_of` 2011-11-30. Una repetición rápida limpia da sellos iguales en 476 hojas salvo `launch.run_key`. Con la parte de la prueba escrita, una corrida con costos 8 sale con 0 como posterior al sello y deja el sello intacto, como dice R13 | Cerrada |
| A2 | `build_summary` bajo costos 8 en un almacén rápido sellado da `costs.offer_cost` 8,0 | Da 5,0 arriba y 8,0 en `post_seal.costs`; C05 es igual en ambas | Cerrada |
| A4 y A5 | Las filas de criterios del resumen y del bloque del README tienen celdas `[5,5,5,5,5,5,7,5,5,5]` | Todas 5, como el encabezado; el diff solo toca C07 (barras escapadas) y C09 (agrega «lo deja en 9 de los 17… no lo deja en 8»); ningún número ni veredicto cambió; el bloque del README es el resumen con los títulos un nivel más abajo | Cerradas |
| A10 | El segmentador de la página 3 es `dim_date[date]` (2009-12-01… y 735 más) | Existe R19 (`dim_as_of[as_of_key]` 1→* `fact_tracking[as_of_key]`, única y activa) con su control SQL; el segmentador es `dim_as_of[as_of_label]` con las 6 fechas de cálculo, iguales a las claves de `fact_tracking`; el gráfico de motivos dice «(todo el corte: no lo filtran el país ni la banda)». Un diff por símbolos del HTML solo muestra: 18 a 19 relaciones, la fila R19 y su línea del diagrama, la descripción de `dim_as_of`, el título en 5 lugares y la lista y el enlace del segmentador | Cerrada |
| A11 | No existe | `test_privacy.py::test_no_fixture_customer_id_in_any_versioned_byte_or_run_log` existe y pasa (24,66 s); al escribir un número del accesorio en `_write_state` en una copia, falla nombrando los 6 archivos `interim/runs/*.json` | Cerrada |
| A13 | La prueba de Docker deja `churnrisk-airflow:3.4.0` (la comprobación lo borró con `docker image rm`) | Después de `-m docker`, ni esa imagen ni otra imagen, volumen, contenedor o red nuevos respecto de la línea de base | Cerrada |
| A14 | Se recoge `test_evaluation.py::test_delivery` y se compila con `invalid escape sequence '\['` en `test_star_schema.py:351` | No se recoge ni compila con avisos; los únicos avisos de la suite son 3 `PendingDeprecation` de `shap` | Cerrada |
| A16 | «77,9 %» sin corte | «entre los contactados del corte del 2011-09-01», coherente con `fact_reason_summary`: `gap_mean` tiene 380 contactados, cerca de 0,779 de los de ese corte | Cerrada |
| D93 | | Los identificadores recogidos son los mismos con y sin los umbrales (880, comparados línea a línea) y los resultados por prueba del JUnit son idénticos en las 880 | Cerrada |

**Las suites y la repetición real.**

| | Resultado | Tiempo |
| --- | --- | --- |
| Suite rápida en `94843fd`, en reposo (0 otros procesos de Python) | 879 pasaron y 1 se omitió | 111,14 s y 108,34 s |
| La misma, sin los umbrales de D93 | | 113,44 s |
| `-m real_data` (copia de la repetición) | 9 pasaron; en el clon limpio, 8 pasaron y 1 error, la dependencia conocida de un almacén de corrida real, igual que en `e28b1fb` | 46,08 s |
| `-m docker` en `94843fd` / en `e28b1fb` | 2 pasaron / 2 pasaron | 90,48 s / 89,34 s |
| `replay` real en una copia de `94843fd` (sin `reports/`, `outputs/`, el HTML ni las figuras) | Las tres órdenes (`replay`, la corrida sin entrega y `figures`) salieron con 0; `PeakWorkingSetSize` 1.888,5 MB | `replay` unos 304,6 s (el lanzamiento unos 123 s), la corrida sin entrega 3,6 s y `figures` unos 3,8 s (de las claves de corrida y las horas de los archivos: el cronómetro del intérprete de órdenes falló) |

- **La repetición contra lo versionado (46 archivos).** Las siete figuras, byte a byte iguales. Las 485 hojas del sello difieren solo en `launch.run_key` y `test.run_key`. Los 26 Parquet son iguales en valor salvo `dim_pipeline_run` (clave de corrida, `started_at` y `finished_at`) y la clave de corrida de `fact_validation`. Los archivos del sitio difieren solo en claves de corrida y los manifiestos solo en las huellas de esos archivos. El resumen en JSON y en Markdown, los reportes de validación y el HTML son iguales una vez normalizadas las claves de corrida y las horas. No apareció ningún archivo versionado de más.
- **El diferencial de la línea de comandos.** Los mismos pasos, con las mismas entradas, en las dos copias: `run` con `--from` sin `--run-key`, con `--run-key` solo y con `--only deliver` de una corrida cerrada; `task` con una tarea desconocida, con `build_cuts` antes de cargar, con `load` antes de validar y con `report` de una corrida cerrada; `replay` con un `--until` malo y `docs-sync` en modo rápido; los rechazos del bloqueo (un dueño vivo para `run`, `replay` y `task`, y después un bloqueo viejo al matar al dueño por su número); la corrida sin entrega; y `docs-sync` sobre el proyecto versionado (sin cambios en las dos). Con la salida estándar, el error y el código normalizados, todo es idéntico salvo los pasos de A1 y lo que de ellos se sigue: ninguna diferencia que nadie pidiera.

**Lo que encontró nuevo.** Ningún bloqueante y dos advertencias:

- **Constancia de lo corregido (RNF14).** Las afirmaciones de los documentos en `94843fd` sobre las correcciones —los tiempos de la suite 118,99 s y 119,17 s, 108,27 s y 107,36 s y 110,89 s y 111,98 s, los 95,44 s de Docker, los 55,68 s de `real_data`, los 298,8 s de la repetición de D91, «Un agente con Opus las escribió» y el «Quién: … (Sonnet)» de D93— no estaban en el registro: L55 solo tenía la decisión («escritor con Opus»). **Corregida** en `b5637a6`, que registra L56 con esos commits, modelos, tiempos y cuentas; esta sincronización, además, quitó de los documentos las cifras que L56 todavía no tiene (la cuenta de 432 valores del sello de D89 y D91, los 3,6 s de la corrida sin sello de D91, los «unos 3 s» de D89 y D92, y varias mediciones de la suite de la ficha del modelo) o las rotuló como del escritor (D91 y D93).
- **El margen de la suite rápida es frágil.** Tiene 8,9 s y 11,7 s bajo el límite de 120 s, y los documentos dan 122 y 123 s en `969f2b4` en esta máquina. Está dicho en D92 y D93. **Abierta**.

## La medición de esta sincronización

Estas cifras las midió la sincronización de la documentación, no el registro: el registro todavía no las tiene y las tendrá cuando registre esta sincronización.

- **Pruebas recogidas en `816289e`:** 880 (879 pasaron y 1 se omitió en las corridas de abajo).
- **Suite rápida, dos corridas seguidas en reposo, en una copia nueva (`git clone`) de `b5637a6`, que tiene el código de `816289e`:** 109,13 s y 108,23 s, las dos con 879 pruebas pasadas y 1 omitida.

## Lo que queda

La revisión nativa de lo que sigue a `94843fd`, la página del sitio, la corrida programada de Airflow sobre el archivo real, el `.pbix` y lo que el plan deja al dueño (sección 29), en particular los costos reales, el texto del sitio, la estrategia de entrega y el `push`. Las advertencias abiertas están en [review-advisories.md](review-advisories.md); ninguna es bloqueante.
