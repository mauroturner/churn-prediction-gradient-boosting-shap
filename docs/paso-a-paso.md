# Paso a paso: cómo se construyó

La cronología real del proyecto, desde el registro del documento de seguimiento (`odd/tasks/portfolio-projects.md`, L44 a L53) y `git log`, con cada commit del proyecto en orden y lo que hizo. Los commits `docs(odd)` registran cada paso en el documento de seguimiento, fuera de esta carpeta; se nombran donde cierran una tanda. Quién escribió cada parte es lo que consta en el registro: un agente con Haiku investigó, uno con Opus escribió el plan, agentes con Opus escribieron las unidades U01 a U31, y agentes con Sonnet escribieron la tanda G1 y las correcciones de cuatro revisiones. Cada unidad se escribió con la prueba primero y vista fallar (la «RED» del plan, sección 27), salvo U22 a U25, cuyas REDs se recuperaron después quitando cada regla en una copia (L51); cada regla se comprobó con mutaciones que una prueba con nombre atrapa. Las cifras de la corrida real están en `docs/decisions.md`, D85, y en la [ficha del modelo](model-card.md).

## Investigación y plan (2026-11-11)

- `00378f8` **Investigación** (Haiku, L44). `docs/research.md`: la fuente de UCI con las huellas del proyecto 02, la calidad para medir bajas (22,5 % de líneas sin cliente, anulaciones, códigos de servicio, 41 países), la etiqueta propuesta (N = 90, M = 90) y su ruido (39 % de los silencios vuelve), los cortes y la partición, las reglas en el primer corte de validación (RFM 0,784) y una primera mirada que no supera a RFM; SHAP aditivo solo con el país como indicadores. Nada calculado sobre los cortes de prueba.
- `7ec593b` **Requerimientos, plan y decisiones** (Opus, L45), confirmados antes de la primera línea de código: `docs/requirements.md`, `docs/plan.md` (31 unidades) y `docs/decisions.md` (D01-D46). Con una medición propia solo sobre los cortes de entrenamiento: la frecuencia ordena mejor que RFM y que BG/NBD (AUC 0,746, 0,737 y 0,732), el BG/NBD con SciPy del proyecto 02 da lo mismo que `lifetimes`, y lo esperado se escribió antes de medir: el modelo probablemente no cumpla C02, C03 ni C07.

## U01-U05: entorno, configuración, accesorio, descarga y lectura (L46)

- `24f3003` **U01** Las versiones fijadas con `==` y la prueba de que cada importación directa es una dependencia fijada y documentada (ítem 5 de riesgo alto, revisada sola).
- `f6d377f` **U02** La configuración tipada: 55 claves selladas y 27 declaradas no selladas; rutas contra la carpeta del proyecto.
- `a2dc7ed` **U03** El libro sintético (30.504 líneas canónicas), su tabla de verdad, los accesorios de sesión y el límite de 120 s de la suite.
- `a5ba4eb` **U04** La descarga, un salto comprobado a la vez, con la huella fijada y lo que no coincide guardado como `.part` (ítem 2, sola).
- `5072548` **U05** La lectura del libro, la base canónica y el rol de cada línea (ítem 2, sola). En el archivo real: 1.067.371 filas, 22.523 copias quitadas, 1.044.848 líneas, 5.942 clientes.

Suite rápida: 311 pruebas en 28,2 s. Cuatro revisiones nativas, todas aprobadas; un hallazgo bloqueante refutado. Decisiones D47-D51. `667f292` lo registra.

## U06-U10: neteo, entregas, validación, almacén y cortes (L47)

- `d819034` Las nueve advertencias de U01-U05 que se corrigieron, cada una con la prueba primero.
- `bca7238` **U06** El neteo LIFO de las anulaciones conocido en una fecha, conciliado con D04 del proyecto 02 (16.427 emparejamientos en el archivo real).
- `c2bdf5f` **U07** El plan de entregas desde la configuración: el lanzamiento, las cuatro mensuales y el cierre, con su manifiesto.
- `9f3a4fd` **U08** La validación V10-V31 con la forma en que cada regla se agrega entre corridas.
- `cd089b1` **U09** La carga en SQLite en una transacción, con su tabla de preparación y sus controles: un control que falla deja el almacén byte a byte igual.
- `aefd17d` **U10** La población y la etiqueta de cada corte en tablas de solo inserción, con los bloques y sus purgas: los siete cortes de entrenamiento dan 15.297 filas, 3.942 clientes y 43,2 % de bajas.

Suite rápida: 392 pruebas en 42,2 s. La revisión del tramo entero superó el presupuesto de contexto y se hizo en tres partes, todas aprobadas. Decisiones D52-D56. `560e2ea` lo registra.

## U11-U15: variables, reglas, modelo, motivos y umbral (L48)

- `875fc85` **U11** Las variables de cada corte con lo anterior a él y las guardas que impiden que la etiqueta llegue a una matriz.
- `8a42399` **U12** Las reglas B0-B5 y BG/NBD ajustado con la historia anterior a su corte (r 0,9091, α 75,83, a 0,1717, b 105,91), y B* elegida en la validación.
- `67102ed` **U13** La elección y la calibración del modelo en V1, la trampa de fuga y el artefacto que solo se carga con su huella (ítem 2, sola). En V2, el control positivo supera a RFM y el negativo no.
- `522e18d` **U14** Los motivos con SHAP, comprobados fila por fila (error máximo 1,07·10⁻¹⁴), y el rechazo de las divisiones categóricas nativas.
- `aa09c45` **U15** El umbral por beneficio neto en V2, la curva de ganancia, la captura del 10 % y la sensibilidad a los costos.

Suite rápida: 507 pruebas en 97,75 s, dentro del presupuesto de 100 s por menos que el ruido. Tres revisiones, aprobadas. Decisiones D57-D61.

## U16-U20: sello, evaluación, sensibilidades, seguimiento y modelo estrella (L49, L50)

- `5a15281` Las diez advertencias de U06-U10, entre ellas `build_cuts` que ahora llama a `net_lines_at` (D62).
- `c3871ae` La suite más barata: el libro sintético escrito como XML y los cortes del lanzamiento una vez por sesión (de 95,7 a 80,7 s, D63).
- `56450e9` **U16** El lanzamiento congelado detrás de un sello sobre toda la vista sellada, y cada corte puntuado una sola vez con sus motivos (ítem 1, sola).
- `96ad707` **U17** La evaluación de V2 y, una sola vez, de la prueba; el remuestreo por clientes enteros, los criterios sellados y el resumen rehecho desde el sello (ítem 1, sola).
- `7a46452` **U18** Las sensibilidades de N, M y del corte de diciembre dentro del sello de la prueba (ítem 1, sola).
- `05d404d` **U19** El seguimiento de cada corte puntuado, mes a mes, con los cortes censurados marcados.
- `4455bd6` **U20** El modelo estrella desde una sola especificación, con el hecho por cliente fuera de la carpeta versionada (ítem 3, sola).
- `f40bc91` La corrección acotada de la revisión de U19: un comentario que dice de dónde viene el caso de prueba. El validador no la aceptó y la revisión quedó escalada (L50).

Suite rápida: 574 pruebas en 108,6 s en reposo, sobre el presupuesto. Seis revisiones: cinco aprobadas y la de U19 escalada por un hallazgo falso (el defecto de Gentle AI quedó publicado como gentle-ai#6106). Decisiones D62-D68. `38054a6` y `d445f92` lo registran.

## U21-U25: medidas, diseño del tablero, sitio, bloqueo y tareas (L51)

- `c6a52ce` Los defectos reales que dejaron las revisiones de U11-U20, cada uno visto fallar primero (D69).
- `267d26a` Lo que esas revisiones encontraron sin prueba: 19 casos, cada uno con una mutación atrapada.
- `69da8b3` La suite otra vez bajo su presupuesto, sin quitar casos (D70).
- `4b71e79` **U21** Las 29 medidas DAX, los tres parámetros de los costos y las cinco páginas en el modelo semántico (D71).
- `45e9e00` **U22** El diseño del tablero en HTML con la columna de cliente de la lista enmascarada (D72).
- `7567813` La suite bajo su presupuesto con las pruebas de la exportación del sitio (D73).
- `3519ad3` **U23** Los cinco archivos del sitio con su manifiesto, sin nada que nombre a un cliente ni una celda que se recupere por resta (ítem 3, sola; D74).
- `c06a076` Ocho hilos de OpenMP para los ajustes de la suite (D75).
- `bedee7f` **U24** Un solo proceso escribe la carpeta de datos, con un bloqueo cuya liberación nunca falla (ítem 4, sola; D76).
- `92d8305` **U25** Las doce tareas con su estado, un cierre ordenado y cada rechazo antes de escribir (ítem 4, sola; D77).
- `4e21c1a` Corrección de una revisión (Sonnet): los calibradores de las reglas por método y versión del modelo.
- `15fe8d1` Corrección de una revisión (Sonnet): las celdas de menos de 10 clientes ocultas en las vistas previas del diseño.
- `c18e47f` Corrección de una revisión (Sonnet): un cierre sin entrega reescribe la tabla de corridas y el HTML, y una reescritura que no se puede hacer queda en el registro.

Suite rápida: 726 pruebas en 108,64 s en reposo. Seis revisiones; tres aprobadas directamente y tres con una corrección acotada cada una, aprobadas después. `a6b8733` lo registra.

## U26-U28 y G1: línea de comandos, Airflow, figuras y advertencias (L52)

- `fb59d06` Las decisiones D78-D80 de las tres correcciones.
- `2e41f80` Los defectos reales que dejaron las revisiones de U21-U25, cada uno visto fallar primero.
- `45e76d9` Lo que esas revisiones encontraron sin prueba, seis casos con su mutación.
- `dfa7ff4` La suite más barata antes de U26 (D81).
- `17d123a` **U26** La línea de comandos y el modo rápido aislado (D82).
- `4a9d9f2` **U27** El DAG de Airflow, su imagen y el compose con cada secreto del entorno (ítems 5 y 2, sola; D83). Las pruebas que necesitan Docker no se corrieron.
- `ca3d2df` **U28** Las siete figuras, dibujadas solo desde los archivos del sitio verificados (D84).
- `6bda6c9` **G1** (Sonnet) Correcciones de advertencias de U27, U28 y de las revisiones de la tanda: la celda oculta de la figura de la definición, las figuras escritas todas o ninguna, `make-fixture` sin la carpeta `tests`, la lectura del id de arranque y el aviso del DAG.
- `4b32b8e` **G1** (Sonnet) Solo pruebas: el despertar del bloqueo, el id de arranque, las tarjetas sin divisor, `docs-sync` sin el resumen y las figuras entre procesos.

Suite rápida: 845 pruebas y una omitida en 105,60 s, sobre el presupuesto de 100 s y dentro del límite; se aceptó así, sin `pytest-xdist` (D35). Cinco revisiones, todas aprobadas sin corrección, y un tramo pasivo sin revisión. `bc9bfff` lo registra.

## U29: la corrida real, dos veces (L53)

- `4d0a36b` **La corrección de las celdas chicas** (D86). La primera corrida real terminó, pero antes de versionar, la revisión de privacidad encontró en `fact_calibration` y en `fact_reason_summary` celdas de menos de 10 filas o clientes que el sitio oculta; los dos marts ahora las ocultan con la regla del sitio, la secundaria incluida (ítem 2, revisada sola).
- `a108a12` **U29** La corrida real versionada (ítem 1, sola; D85). La misma corrida se repitió en una copia nueva del proyecto en `4d0a36b`: su sello coincide con el primero en los 485 valores salvo las dos claves de corrida, así que se versionaron las salidas de la repetición y el sello de la primera, byte a byte. `replay` tardó 312,2 s, el pico del conjunto de trabajo (`PeakWorkingSetSize`) fue de 1.868,5 MB y el modelo no supera a las reglas: AUC 0,745 frente a RFM 0,746, B* 0,749 y la frecuencia 0,752; cumple solo C06 y C08.
- `fe25112` La corrección de la revisión del HTML (Sonnet): el filtro de fechas de la página de seguimiento, que no filtraba nada, enlazado al calendario que filtra `fact_tracking`.

Suite rápida: 849 pruebas y una omitida en 112,83 s; `-m real_data`, 9 de 9 en 51,65 s. U29 tenía 5.855 líneas, más que el presupuesto de contexto de una revisión, y se revisó en partes; todas aprobaron salvo la del HTML, que abrió la corrección. `ceff9ea` lo registra.

## U30-U31: la documentación

- `3ec6052` **U30** (Opus) El README con los títulos del plan y el bloque de resultados que copia `docs-sync`, ahora con los títulos del resumen un nivel más abajo (D87), y la ficha del modelo con las cifras reales y sus intervalos. Suite rápida: 856 pruebas (una omitida) en 109,14 s y 106,60 s.
- **U31** (Opus) Este documento, el diccionario de datos con sus tablas escritas por `docs-sync` desde el modelo semántico, el runbook R1-R14 con los comandos corridos y sus códigos de salida, las advertencias de las revisiones con su estado, las filas del proyecto 04 en `SITE-UPDATES.md` y `LANDING-EXPANSION.md` y las pruebas de coherencia de la documentación (D88).

## Lo que falta

La evaluación independiente (plan, sección 28), con sus correcciones, su comprobación y la sincronización de la documentación con la última corrección; la prueba de Airflow en Docker; la página del sitio; y lo que es del dueño: los costos reales, el `.pbix`, el texto del sitio, la estrategia de entrega y el `push` (plan, sección 29).
