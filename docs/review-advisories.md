# Advertencias de las revisiones nativas

Las advertencias que dejaron las revisiones nativas de Gentle AI de este proyecto, de U01 a U29, una sección por revisión, con su estado. Salen de los hallazgos que cada revisión devolvió (155 en sus archivos, más 5 que constan solo en el registro: el de U19 y los de la parte 2c de U29; todos sin bloqueo salvo los que se dicen) y del registro del documento de seguimiento (`odd/tasks/portfolio-projects.md`, L46 a L55), que dice cuáles se corrigieron, cuáles se dejaron con evidencia y cuáles quedaron como advertencias para este documento. Las dos últimas secciones suman lo que encontró U31 al escribir la documentación y lo que encontró la evaluación independiente de `e28b1fb` (un bloqueante y 18 advertencias, L55), con lo que hizo su tanda de correcciones.

Estados: **corregida** (con el commit que la corrige, con la prueba escrita primero), **dejada con evidencia** (el hallazgo no es un defecto, o ya está cubierto, con la evidencia) y **abierta** (cierta o posible, sin corregir; la tanda de correcciones de la evaluación independiente corrigió las que eligió el registro, L55, y las demás siguen abiertas). Ninguna advertencia se corrigió en U31. Lentes: riesgo (R1), legibilidad (R2), confiabilidad (R3) y resiliencia (R4). Las ubicaciones son relativas a la carpeta del proyecto y a la versión revisada.

Dos tramos no se revisaron porque la evaluación de riesgo los dio pasivos: `c18e47f..fb59d06` (las decisiones D78-D80) y la parte 2d de U29 (las siete figuras, binarias). Una revisión, la de U06-U10 entera, y otra, la de U29 entera, superaron el presupuesto de contexto sin crear autoridad, y se hicieron por partes.

## U01 (`f403772..24f3003`; riesgo y confiabilidad; aprobada; 6 advertencias)

- **R1-001** (`requirements.txt`, líneas 3-4; advertencia): los 30 paquetes están fijados con `==` pero sin `--hash`, así que `pip install` no verifica la integridad de lo que baja.
  - Estado: **abierta**: sin `--hash` a propósito, como el proyecto 02 (su D55; el comentario de `requirements.txt` lo dice); fijar huellas por plataforma es una decisión del dueño.
- **R1-002** (`.dockerignore`, líneas 2-3; sugerencia): el contexto de la imagen solo tiene `requirements.txt`, así que la imagen no lleva el código y depende de lo que se monte al correr.
  - Estado: **dejada con evidencia**: es el diseño de D29: el compose monta `src/`, `sql/`, `config/` y `dags/` en solo lectura (`airflow/docker-compose.yaml`, líneas 47-54).
- **R3-dep-problems-mislabel** (`tests/unit/test_dependencies.py`, líneas 97-116; advertencia): una dependencia directa de desarrollo importada desde `src/` se informaba como transitiva.
  - Estado: **corregida** en `d819034`: se nombra como dependencia de desarrollo.
- **R3-never-applies-brittle** (`tests/unit/test_dependencies.py`, líneas 119-124; advertencia): solo reconocía `python_version < "3.N"` con comillas dobles y `<`.
  - Estado: **corregida** en `d819034`: comillas simples y `<=` también.
- **R3-env-coupled-tests** (`tests/unit/test_dependencies.py`, líneas 208-224; advertencia): las versiones y `pip check` se comprueban en el intérprete que corre pytest, no en un entorno armado desde los requisitos.
  - Estado: **abierta**: por diseño según L46 (la suite corre en el entorno del proyecto); un entorno aparte armado desde `requirements.txt` sería otra prueba.
- **R3-missing-coverage-tests-scope** (`tests/unit/test_dependencies.py`, líneas 142-159; advertencia): ninguna sonda recorría el alcance `tests`.
  - Estado: **corregida** en `d819034`: sondas del alcance `tests` y del respaldo de `distribution_of`.

## U02-U03 (`24f3003..a2dc7ed`; riesgo, resiliencia y confiabilidad; aprobada; 3 advertencias)

- **R3-fixture-repeat-rows-pool** (`tests/fixtures/make_fixture.py`, líneas 413-423; advertencia): `pick` sorteaba sin comprobar que hubiera suficientes filas elegibles en la ventana.
  - Estado: **corregida** en `d819034`: el error nombra la ventana corta y los dos tamaños.
- **R3-suite-budget-args-source** (`tests/fixtures/suite_budget.py`, línea 33; advertencia): `config.args_source` y `pytest.Config.ArgsSource.ARGS` no son API estable de pytest.
  - Estado: **dejada con evidencia**: pytest está fijado en 9.2.0 (`requirements-dev.txt`), que los tiene, y `tests/unit/test_suite_budget.py` lo comprueba en cada suite.
- **R3-suite-budget-markexpr-drift** (`tests/fixtures/suite_budget.py`, línea 17; sugerencia): la expresión de marcas de la guarda no se comparaba con la de `pyproject.toml`.
  - Estado: **corregida** en `d819034`: se compara.

## U04 (`a2dc7ed..a5ba4eb`; riesgo, resiliencia y confiabilidad; aprobada; 7 advertencias)

- **R1-001** (`src/churnrisk/ingest.py`, líneas 69-100; sugerencia): `insecure_hosts` deja saltar HTTPS y el puerto por omisión para los hosts que nombra.
  - Estado: **dejada con evidencia**: solo las pruebas lo pasan (`tests/unit/test_fetch.py`, `tests/contract/test_source.py`, `tests/fixtures/http_server.py`); ni el flujo, ni la CLI, ni el DAG lo usan, y `fetch_source` lo recibe vacío por omisión.
- **R1-002** (`src/churnrisk/ingest.py`, líneas 182-187; sugerencia): el archivo de preparación de la descarga se abre con modo 0o666, sujeto a la máscara del sistema.
  - Estado: **abierta**.
- **R4-staging-leak** (`src/churnrisk/ingest.py`, líneas 175-189; advertencia): si el proceso muere de golpe, el archivo de preparación queda y nadie lo borra.
  - Estado: **abierta**: nunca se lee como fuente; el runbook (R2) dice que se borra a mano.
- **R4-hash-case** (`src/churnrisk/ingest.py`, línea 282; advertencia): la huella se compara sin pasar a minúsculas.
  - Estado: **dejada con evidencia**: la configuración solo acepta `[0-9a-f]{64}` (`src/churnrisk/config.py`, `_SHA256`), así que una huella en mayúsculas se rechaza al leerla.
- **R4-deadline-slack** (`src/churnrisk/ingest.py`, línea 39; sugerencia): el margen fijo de 0,05 s para distinguir el tiempo máximo de una falla común supone el tic de Windows.
  - Estado: **abierta**.
- **R3-missing-fixture-malformed** (`tests/unit/test_fetch.py`, líneas 472-479; bloqueante): la prueba pedía un accesorio `malformed` que no estaba en el candidato.
  - Estado: **dejada con evidencia**: refutado en la revisión: el accesorio está en `tests/conftest.py` desde U03 (`a2dc7ed`).
- **R3-vacuous-staging-restore-assertion** (`tests/unit/test_fetch.py`, línea 435; advertencia): la afirmación leía el nombre importado, no el valor del módulo, y no podía fallar.
  - Estado: **corregida** en `d819034`: lee el valor del módulo antes de cambiarlo.

## U05 (`a5ba4eb..5072548`; riesgo, resiliencia y confiabilidad; aprobada; 6 advertencias)

- **R4-except-exception-mask** (`src/churnrisk/ingest.py`, líneas 629-630; advertencia): `except Exception` alrededor de abrir el libro reclasifica también una falta de memoria como libro inválido.
  - Estado: **abierta**.
- **R4-tempdir-hard-kill** (`src/churnrisk/ingest.py`, líneas 825-827; advertencia): el libro extraído vive en una carpeta temporal que queda si el proceso muere de golpe.
  - Estado: **abierta**.
- **R4-canonical-toctou** (`src/churnrisk/ingest.py`, líneas 738-746; advertencia): entre comprobar la huella de la base canónica y volver a abrirla, otro proceso podría reemplazarla.
  - Estado: **dejada con evidencia**: desde U24 (`bedee7f`, D76) cada tarea toma el bloqueo de un solo escritor de la carpeta de datos, así que ningún otro `fetch_source` reescribe `data/interim/` mientras tanto.
- **R3-real-data-price-quantity-counts-unproven** (`tests/contract/test_source_real.py`, líneas 46-57; advertencia): la prueba real no afirmaba los recuentos de precio (70) y cantidad (0).
  - Estado: **corregida** en `d819034`: los afirma.
- **R3-windows-handle-cleanup-untested** (`src/churnrisk/ingest.py`, líneas 545-566; advertencia): nada probaba que el libro extraído no quede abierto en Windows tras una falla de lectura.
  - Estado: **corregida** en `d819034`: una lectura que falla después de extraer no deja el miembro ni la carpeta.
- **R3-sourcereport-blank-extra-fields-untested** (`src/churnrisk/ingest.py`, líneas 475-480; sugerencia): `blank_rows` y `extra_sheets` del reporte de la fuente no tenían prueba.
  - Estado: **corregida** en `d819034`: con una variante chica del libro.

## U06-U10a (`5072548..c2bdf5f`; confiabilidad; aprobada; 5 advertencias)

- **R3-entry-from-validation-branches-untested** (`src/churnrisk/deliveries.py`, líneas 102-121; advertencia): cuatro de las cinco comprobaciones de una entrada del manifiesto de entregas no tenían prueba.
  - Estado: **corregida** en `5a15281`.
- **R3-cut-after-launch-nonmonth-end-untested** (`src/churnrisk/deliveries.py`, líneas 84-86; advertencia): las pruebas del plan de entregas usaban siempre un lanzamiento a fin de mes.
  - Estado: **dejada con evidencia**: la configuración exige un lanzamiento a fin de mes (D48), así que otro no llega a esa función.
- **R3-mark-delivery-transition-unvalidated** (`src/churnrisk/deliveries.py`, líneas 180-190; sugerencia): una entrega cargada podía volver a `rejected` y cargarse otra vez.
  - Estado: **corregida** en `5a15281` (D62): una entrega cargada no cambia de estado.
- **R3-cancellation-outcomes-consistency-check-untested** (`src/churnrisk/netting.py`, líneas 151-165; advertencia): la comprobación de que emparejadas más sin emparejar sumen las anulaciones no tenía prueba.
  - Estado: **corregida** en `5a15281`.
- **R3-publish-empty-delivery-untested** (`src/churnrisk/deliveries.py`, líneas 233-260; sugerencia): nadie publicaba una entrega sin filas.
  - Estado: **corregida** en `5a15281`.

## U06-U10b (`c2bdf5f..cd089b1`; riesgo, resiliencia y confiabilidad; aprobada; 6 advertencias)

- **R4-fail-on-log-order** (`src/churnrisk/warehouse.py`, líneas 222-227; advertencia): el registro decía «rolled back» antes de que corriera el `ROLLBACK`.
  - Estado: **corregida** en `5a15281`.
- **R4-full-rescan-per-load** (`src/churnrisk/warehouse.py`, líneas 279-281; advertencia): cada carga reconstruye `stg_lines` y corre sus controles sobre todas las líneas cargadas.
  - Estado: **dejada con evidencia**: medida en la corrida real, como pedía L47: `load` tardó 9,40 s en el lanzamiento y de 4,65 a 6,09 s en las mensuales, y cada corrida mensual de 27 a 65 s contra el tope de 2 minutos (estado de la corrida; D85).
- **R4-write-lock-before-noop-check** (`src/churnrisk/warehouse.py`, líneas 264-269; sugerencia): una carga repetida toma la escritura de SQLite antes de ver que no tiene nada que hacer.
  - Estado: **abierta**.
- **R3-raw-unique-line-dead-check** (`sql/checks/load/chk_raw_unique_line.sql`, línea 2; advertencia): el control no podía fallar, porque la clave primaria rechaza antes la línea repetida.
  - Estado: **corregida** en `5a15281` (D62): el control se quitó.
- **R3-missing-check-failure-coverage** (`tests/integration/test_load.py`, líneas 63-77; advertencia): dos controles de la carga nunca se llevaban a fallar.
  - Estado: **corregida** en `5a15281`.
- **R3-schema-drift-partial-coverage** (`src/churnrisk/warehouse.py`, líneas 88-93; sugerencia): solo se probaba la columna faltante, no la que sobra ni la de otro tipo.
  - Estado: **corregida** en `5a15281`.

## U06-U10c (`cd089b1..aefd17d`; riesgo y confiabilidad; aprobada; 2 advertencias)

- **R3-001** (`src/churnrisk/netting.py`, líneas 176-180; advertencia): `build_cuts` reimplementaba `net_lines_at` en lugar de llamarla, y `net_lines_at` no tenía prueba.
  - Estado: **corregida** en `5a15281`: `build_cuts` la llama; los cortes y los marts salieron iguales byte a byte antes y después.
- **R3-002** (`src/churnrisk/cuts.py`, línea 111; sugerencia): `CutsResult.rows` no se afirmaba en ninguna prueba.
  - Estado: **corregida** en `5a15281`.

## U11-U12 (`aefd17d..8a42399`; riesgo y confiabilidad; aprobada; 5 advertencias)

- **R1-001** (`src/churnrisk/cuts.py`, líneas 30-31; sugerencia): la lista de columnas del `INSERT` se arma con un f-string sobre `FEATURE_COLUMNS`.
  - Estado: **dejada con evidencia**: `FEATURE_COLUMNS` es una tupla fija de `src/churnrisk/schema.py`; ninguna entrada externa llega a ella, como dice el propio hallazgo.
- **R1-002** (`src/churnrisk/features.py`, líneas 166-172; sugerencia): el país junto a los valores de RFM de cada corte puede identificar a un cliente de un país con pocos clientes.
  - Estado: **dejada con evidencia**: esas filas viven solo en SQLite, `data/interim/` y `outputs/private/`; lo publicado pone en «Otros» los países de menos de 10 clientes y oculta las celdas chicas (RNF12, D27), y la fuente es pública (L48).
- **R3-known-before-country-guard-unproved** (`src/churnrisk/features.py`, líneas 63-65; advertencia): la guarda de `known_before` sin la columna del país no tenía prueba.
  - Estado: **corregida** en `267d26a`.
- **R3-fit-baselines-finite-check-ordering** (`src/churnrisk/baselines.py`, líneas 119-123; advertencia): los puntajes se calibraban y B* se elegía antes de comprobar que fueran finitos.
  - Estado: **corregida** en `c6a52ce`: se comprueban antes.
- **R3-nelder-mead-retry-start-fallback-unproved** (`src/churnrisk/bgnbd.py`, línea 109; advertencia): el reintento con un punto de partida no finito no tenía prueba.
  - Estado: **corregida** en `267d26a`.

## U13 (`8a42399..67102ed`; riesgo, resiliencia y confiabilidad; aprobada; 8 advertencias)

- **R1-001** (`src/churnrisk/registry.py`, líneas 65-71; advertencia): `load_artifact` usa `pickle.loads` una vez que la huella coincide.
  - Estado: **dejada con evidencia**: es el diseño de D40, documentado: una sola lectura, la huella comparada con `hmac.compare_digest` antes de deserializar, y `tests/unit/test_registry.py::test_artifact_with_other_hash_is_refused_before_loading`.
- **R4-model-tripwire-no-log** (`src/churnrisk/model.py`, líneas 135-142; advertencia): la trampa M01 detenía el lanzamiento sin dejar nada en el registro.
  - Estado: **corregida** en `c6a52ce`: lo registra (el runbook, R5, cita el mensaje).
- **R4-fit-candidates-no-progress-observability** (`src/churnrisk/model.py`, líneas 92-101; advertencia): las 24 candidatas se ajustan sin registro de avance ni tiempo máximo.
  - Estado: **dejada con evidencia**: medido con U29, como pedía L48: `fit_model` del lanzamiento tardó 15,28 s en la corrida real (estado de la corrida).
- **R4-registry-save-no-log** (`src/churnrisk/registry.py`, líneas 49-53; sugerencia): guardar el artefacto no dejaba nada en el registro.
  - Estado: **corregida** en `c6a52ce`.
- **R3-log-odds-untested** (`src/churnrisk/model.py`, líneas 183-185; advertencia): `log_odds`, que alimenta SHAP, no tenía prueba.
  - Estado: **corregida** en `267d26a`.
- **R3-tripwire-nan-auc-untested** (`src/churnrisk/model.py`, líneas 135-142; advertencia): D59 afirma que M01 salta también con un AUC que no es un número, sin prueba.
  - Estado: **corregida** en `267d26a`.
- **R3-registry-model-roundtrip-untested** (`tests/unit/test_registry.py`, líneas 84-90; advertencia): el guardado y la carga nunca llevaban un `RiskModel` real.
  - Estado: **corregida** en `267d26a`.
- **R3-f1-static-test-claim-unbacked** (`src/churnrisk/model.py`, línea 21; sugerencia): el docstring citaba una prueba estática que no existía.
  - Estado: **corregida** en `c6a52ce`: el docstring nombra la prueba que existe.

## U14-U15 (`67102ed..aa09c45`; riesgo y confiabilidad; aprobada; 4 advertencias)

- **R3-gain-curve-zero-share** (`src/churnrisk/threshold.py`, líneas 165-167; advertencia): con más puntos que filas, `k` es 0 y `captured[k-1]` toma el último elemento.
  - Estado: **corregida** en `c6a52ce`: el primer punto que no tendría ningún cliente se rechaza antes de calcular.
- **R3-check-guards-untested** (`src/churnrisk/threshold.py`, líneas 80-90; advertencia): las guardas comunes del módulo del umbral no tenían prueba.
  - Estado: **corregida** en `267d26a`.
- **R3-explain-shape-guard-untested** (`src/churnrisk/explain.py`, líneas 87-88; advertencia): la guarda de la forma de la matriz de SHAP no tenía prueba.
  - Estado: **corregida** en `267d26a`.
- **R3-misc-validation-untested** (`src/churnrisk/threshold.py`, líneas 177-178; sugerencia): la parte fuera de (0, 1] de `top_share_capture` y la columna desconocida de `_feature_of` no tenían prueba.
  - Estado: **corregida** en `267d26a`.

## U16-U20a (`aa09c45..c3871ae`; resiliencia y confiabilidad; aprobada; 3 advertencias)

- **R3-na-missing-value-coverage** (`tests/fixtures/make_fixture.py`, líneas 347-357; advertencia): el escritor de celdas del accesorio no reconocía `pd.NA` como vacío.
  - Estado: **corregida** en `c6a52ce`.
- **R3-illegal-xml-char-coverage** (`tests/fixtures/make_fixture.py`, líneas 355-357; advertencia): un carácter de control se escribía tal cual en el XML, donde openpyxl fallaba con claridad.
  - Estado: **corregida** en `c6a52ce`.
- **R3-net-lines-at-inputs-unit-coverage** (`src/churnrisk/netting.py`, líneas 178-184; sugerencia): el parámetro `inputs` de `net_lines_at` solo se probaba de forma indirecta.
  - Estado: **corregida** en `267d26a`.

## U16 (`c3871ae..56450e9`; riesgo, resiliencia y confiabilidad; aprobada; 9 advertencias)

- **R1-001** (`src/churnrisk/registry.py`, líneas 228-232; sugerencia): en Windows el modo 0o600 del sello no es un control de acceso.
  - Estado: **dejada con evidencia**: el sello lo avisa en cada escritura en Windows («the owner-only mode 0o600 is not enforced on this system», comprobado al escribir el runbook) y el runbook, R7, dice que lo decide la lista de acceso de `reports/`.
- **R1-002** (`src/churnrisk/launch.py`, líneas 80-81; sugerencia): el nombre del artefacto sale de `model_version` sin validar.
  - Estado: **dejada con evidencia**: `model_version` se valida desde U02 (`c6a52ce` lo registra).
- **R4-launch-race** (`src/churnrisk/launch.py`, líneas 126-138; advertencia): entre ver que no hay modelo registrado y registrarlo no había bloqueo.
  - Estado: **dejada con evidencia**: desde U24 (`bedee7f`) `fit_model` corre con el bloqueo de un solo escritor (L50).
- **R4-launch-silent-rollback** (`src/churnrisk/launch.py`, líneas 176-179; advertencia): deshacer el registro del lanzamiento no dejaba nada en el registro.
  - Estado: **corregida** en `c6a52ce`.
- **R3-1** (`src/churnrisk/scoring.py`, líneas 90-105; advertencia): el camino de `score_cut` con clientes puntuados entretanto nunca se probaba.
  - Estado: **corregida** en `267d26a`.
- **R3-2** (`src/churnrisk/launch.py`, líneas 190-201; advertencia): sin sello, `_reuse` informaba `m05_passed` verdadero sin haber comparado nada.
  - Estado: **corregida** en `c6a52ce`: es nulo sin sello.
- **R3-3** (`sql/schema/003_model.sql`, líneas 26-30; advertencia): `baseline_calibrators` no tenía las guardas de solo inserción de las tablas vecinas.
  - Estado: **corregida** en `c6a52ce`.
- **R3-4** (`sql/schema/003_model.sql`, línea 40; sugerencia): `model_scores.threshold` no tenía el `CHECK` de 0 a 1.
  - Estado: **corregida** en `c6a52ce`.
- **R3-5** (`src/churnrisk/registry.py`, líneas 265-268; advertencia): el sello se enlazaba sin `fsync` del temporal.
  - Estado: **corregida** en `c6a52ce`.

## U17 (`56450e9..96ad707`; riesgo y confiabilidad; aprobada; 4 advertencias)

- **R3-block-data-error-paths** (`src/churnrisk/evaluation.py`, líneas 177-189; advertencia): las tres fallas nuevas de `block_data` no tenían prueba.
  - Estado: **corregida** en `267d26a`.
- **R3-cluster-bootstrap-length-mismatch** (`src/churnrisk/evaluation.py`, líneas 143-144; advertencia): el error por largos distintos del remuestreo no tenía prueba.
  - Estado: **corregida** en `267d26a`.
- **R3-evaluate-no-seal-error** (`src/churnrisk/reporting.py`, líneas 152-153; advertencia): `evaluate` antes de cualquier sello no tenía prueba.
  - Estado: **corregida** en `267d26a`.
- **R3-post-seal-costs-staleness** (`src/churnrisk/reporting.py`, líneas 290-299; sugerencia): el análisis posterior al sello se rotula con los costos de la llamada, no con los que produjeron sus filas.
  - Estado: **corregida** en `969f2b4`: los costos de arriba del resumen son los sellados cuando los criterios son los sellados, y el bloque posterior al sello lleva los de la corrida (A2 de la evaluación, D92).

## U18 (`96ad707..7a46452`; riesgo y confiabilidad; aprobada; 4 advertencias)

- **R3-rows-of-empty-cuts** (`src/churnrisk/sensitivity.py`, líneas 91-99; advertencia): `rows_of` no tenía guarda para una tupla de cortes vacía.
  - Estado: **corregida** en `c6a52ce`.
- **R3-eval-variants-persistence-untested** (`src/churnrisk/reporting.py`, líneas 146-157; advertencia): nada consultaba la tabla `eval_variants`.
  - Estado: **corregida** en `267d26a`.
- **R3-run-variants-every-post-seal-call** (`src/churnrisk/reporting.py`, línea 191; advertencia): las variantes se reentrenan en cada evaluación posterior al sello, también cuando no escriben el sello.
  - Estado: **abierta**.
- **R3-definition-tables-lookahead-unverified** (`src/churnrisk/sensitivity.py`, líneas 157-176; sugerencia): las tablas de la definición necesitan datos hasta `c + 2N − 1` y nada comprueba que existan con N = 120.
  - Estado: **abierta**.

## U19 (`7a46452..05d404d`; confiabilidad; escalada; 1 hallazgo)

- **R3-001** (`tests/unit/test_tracking.py`; bloqueante, inferencial): «`tracking_case` … cannot already exist in the unmodified baseline `hand_cases.py`».
  - Estado: **dejada con evidencia**: es falso: `tracking_case` entró en U03 (`a2dc7ed`, `git log -S`) y la suite recoge y pasa `test_tracking.py` (L50). La corrección acotada (un comentario de dos líneas que dice de dónde viene el caso, `f40bc91`) la rechazó el validador, que no lee archivos fuera de la corrección; la revisión quedó escalada, y el dueño publicó el defecto de Gentle AI como gentle-ai#6106. Este hallazgo no figura en los archivos de advertencias de las revisiones: sale del registro.

## U20 (`05d404d..4455bd6`; riesgo, legibilidad y confiabilidad; aprobada; 9 advertencias)

- **R2-suppression-cte-duplicated** (`sql/marts/powerbi/mart_10_fact_cut_band.sql`, líneas 14-24; advertencia): el algoritmo de la supresión secundaria se repite tal cual, sin un comentario que lo explique.
  - Estado: **abierta**: `267d26a` agregó el comentario que dice la regla en los dos marts; la repetición sigue.
- **R2-country-key-coalesce-duplicated** (`sql/marts/powerbi/mart_03_dim_country.sql`, línea 9; advertencia): la expresión que da la clave del país se copia en tres marts.
  - Estado: **abierta**.
- **R2-cryptic-unit-constant** (`src/churnrisk/dashboard/semantic_model.py`, línea 22; sugerencia): la constante `U`, de una letra, nombra la unidad genérica.
  - Estado: **abierta**.
- **R2-star-keys-check-repetition** (`sql/checks/model/chk_star_keys_unique.sql`, líneas 1-54; sugerencia): 27 bloques casi iguales escritos a mano en lugar de generarlos desde la especificación.
  - Estado: **abierta**.
- **R3-coverage-fk-checks** (`sql/checks/model/chk_fk_r01_fact_customer_cut_dim_cut.sql`, líneas 1-3; advertencia): ningún control de clave foránea se llevaba a fallar.
  - Estado: **corregida** en `267d26a`.
- **R3-coverage-star-keys** (`sql/checks/model/chk_star_keys_unique.sql`, líneas 1-54; advertencia): el control de claves únicas no tenía una mutación.
  - Estado: **corregida** en `267d26a`.
- **R3-coverage-parquet-size** (`src/churnrisk/export.py`, líneas 177-178; advertencia): el rechazo de un Parquet de más de 25 MB no tenía prueba.
  - Estado: **corregida** en `267d26a`.
- **R3-coverage-unregistered-model** (`src/churnrisk/export.py`, líneas 69-70; advertencia): exportar sin el modelo registrado no tenía prueba.
  - Estado: **corregida** en `267d26a`.
- **R3-coverage-validate-model-negative** (`src/churnrisk/dashboard/semantic_model.py`, líneas 266-295; advertencia): las ramas de error de `validate_model` no tenían prueba.
  - Estado: **corregida** en `267d26a`.

## U21-U25a (`4455bd6..69da8b3`; resiliencia y confiabilidad; una corrección y aprobada; 5 hallazgos)

- **R4-baseline-calibrators-replace-scope** (`sql/schema/003_model.sql`, líneas 75-79; bloqueante): el disparador de solo inserción miraba solo `method`, así que una segunda versión del modelo no podía registrar sus calibradores.
  - Estado: **corregida** en `4e21c1a` (D78): la tabla tiene la clave (`method`, `model_version`) y el disparador rechaza solo un par ya registrado.
- **R4-threshold-check-no-retroactive-migration** (`sql/schema/003_model.sql`, línea 40; advertencia): el `CHECK` nuevo de `model_scores.threshold` solo llega a los almacenes nuevos.
  - Estado: **abierta**: el runbook (R13) dice que un cambio de esquema pide reconstruir desde cero.
- **R3-baseline-calibrators-replace-trigger-overbroad** (`sql/schema/003_model.sql`, líneas 75-79; crítico): el mismo defecto que el primero, visto por la confiabilidad.
  - Estado: **corregida** en `4e21c1a`.
- **R3-baseline-calibrators-cross-version-coverage** (`tests/unit/test_model_schema.py`, líneas 25-33; advertencia): ninguna prueba insertaba otra versión con un método ya usado.
  - Estado: **corregida** en `4e21c1a`: `test_a_new_model_version_registers_its_own_calibrators_for_the_same_methods` (el commit y el registro no nombran este hallazgo).
- **R3-fixture-net-days-single-slot-cache-fragility** (`tests/fixtures/make_fixture.py`, líneas 613-634; advertencia): la memoria de `_prepared` guarda una sola lista y se borra en cada falta.
  - Estado: **abierta**.

## U21-U22 (`69da8b3..7567813`; riesgo, legibilidad y confiabilidad; una corrección y aprobada; 8 hallazgos)

- **R1-001** (`src/churnrisk/dashboard/render.py`, líneas 121-122; crítico): el diseño recibía `min_cell_customers` y decía ocultar las celdas chicas, pero no las ocultaba.
  - Estado: **corregida** en `15fe8d1` (D79): las tarjetas del hecho privado y la matriz N × M muestran un guion por debajo del mínimo.
- **R2-dead-cell-hiding** (`src/churnrisk/dashboard/render.py`, líneas 121-122; crítico): `_Data.hidden` no se llamaba nunca.
  - Estado: **corregida** en `15fe8d1`.
- **R2-title-dispatch** (`src/churnrisk/dashboard/render.py`, líneas 343-366; advertencia): las vistas previas se eligen por el título en español, copiado a mano de la especificación.
  - Estado: **corregida** en `45e76d9`: una prueba comprueba que cada visual de la especificación tiene su vista previa, nunca la de reemplazo.
- **R2-duplicated-sealed-filter** (`src/churnrisk/dashboard/render.py`, líneas 287-290; sugerencia): el filtro «filas selladas o, si no hay, todas» estaba escrito dos veces.
  - Estado: **corregida** en `2e41f80`: `export.prefer_sealed`, uno solo para el sitio y el HTML.
- **R3-min-cell-customers-unused** (`src/churnrisk/dashboard/render.py`, líneas 121-122; crítico): la regla de las celdas chicas del docstring no se aplicaba.
  - Estado: **corregida** en `15fe8d1`.
- **R3-break-even-zero-division** (`src/churnrisk/dashboard/render.py`, línea 195; advertencia): con una tasa de rescate o un valor de cero, el punto de equilibrio dividía por cero.
  - Estado: **corregida** en `2e41f80`: un guion, como los demás formatos.
- **R3-scope-fallback-untested** (`src/churnrisk/dashboard/render.py`, líneas 124-133; advertencia): la vuelta a V2 sin filas selladas de la prueba no tenía prueba.
  - Estado: **corregida** en `45e76d9`.
- **R3-mask-nan-customer-id** (`src/churnrisk/dashboard/render.py`, líneas 174-176; sugerencia): `mask` no se protegía de un número de cliente nulo.
  - Estado: **corregida** en `2e41f80`.

## U23 (`7567813..3519ad3`; riesgo, legibilidad y confiabilidad; aprobada; 7 advertencias)

- **R2-require-star-incomplete** (`src/churnrisk/site_export.py`, líneas 106-110; advertencia): `_require_star` pedía 5 tablas y la exportación lee unas doce más.
  - Estado: **corregida** en `2e41f80`: `REQUIRED_STAR` lista las 16 que el módulo consulta, y una prueba lo compara con sus consultas.
- **R2-lines-raw-duplicated-aggregation** (`src/churnrisk/site_export.py`, líneas 137-138; advertencia): las líneas crudas se calculaban por dos caminos distintos para dos archivos.
  - Estado: **corregida** en `2e41f80`: una sola agregación.
- **R2-sealed-rows-docstring-mismatch** (`src/churnrisk/site_export.py`, líneas 118-123; advertencia): el docstring decía que el respaldo devolvía las filas posteriores al sello y devolvía todas.
  - Estado: **corregida** en `2e41f80`.
- **R3-require-star-untested** (`src/churnrisk/site_export.py`, líneas 106-110; advertencia): el rechazo por una tabla faltante no tenía prueba.
  - Estado: **corregida** en `2e41f80`: la prueba de la tabla faltante quita cada una por su nombre.
- **R3-model-row-untested** (`src/churnrisk/site_export.py`, líneas 147-151; advertencia): exportar sin la fila del modelo no tenía prueba.
  - Estado: **corregida** en `45e76d9`.
- **R3-scored-not-suppressed** (`src/churnrisk/site_export.py`, líneas 388-391; advertencia): `retention.json` publicaba la cuenta de puntuados de un corte sin la regla de las celdas chicas.
  - Estado: **corregida** en `2e41f80`.
- **R3-open-window-pair-untested** (`src/churnrisk/site_export.py`, líneas 365-371; sugerencia): la ventana abierta de `_pair` no tenía una afirmación directa.
  - Estado: **corregida** en `45e76d9`.

## U21-U25b (`3519ad3..c06a076`; confiabilidad; aprobada; 2 advertencias)

- **R3-001** (`tests/conftest.py`, línea 14; advertencia): nada prueba que `OMP_NUM_THREADS` se fije en 8 solo si no está, ni que los resultados no cambien con el número de hilos.
  - Estado: **abierta**.
- **R3-002** (`tests/conftest.py`, líneas 9-16; sugerencia): que la variable se fije antes de importar scikit-learn depende de que pytest importe este archivo primero.
  - Estado: **abierta**.

## U24 (`c06a076..bedee7f`; resiliencia y confiabilidad; aprobada; 4 advertencias)

- **R4-001** (`src/churnrisk/lock.py`, líneas 323-335; advertencia): una toma anidada reescribía el archivo del bloqueo, con sus reintentos, mientras tenía el mutex del proceso.
  - Estado: **corregida** en `2e41f80`: reescrituras y borrados fuera del registro del proceso.
- **R4-002** (`src/churnrisk/lock.py`, líneas 160-172; advertencia): en Linux el arranque de un proceso se cuenta desde el arranque del equipo, que un corte de luz reinicia.
  - Estado: **corregida** en `2e41f80`: el bloqueo guarda el arranque de Linux, y uno de otro arranque es viejo.
- **R3-001** (`src/churnrisk/lock.py`, líneas 350-367; advertencia): entre soltar la entrada del proceso y borrar el archivo, otro hilo se rechazaba en lugar de esperar.
  - Estado: **corregida** en `2e41f80`: la entrada queda hasta que el archivo se borra, y el otro hilo espera.
- **R3-002** (`src/churnrisk/lock.py`, líneas 113-157; advertencia): las llamadas de Windows para ver si un proceso vive y cuándo arrancó no tenían prueba.
  - Estado: **corregida** en `45e76d9`: este proceso, un hijo, un hijo terminado y un número imposible.

## U25 (`bedee7f..92d8305`; riesgo, resiliencia y confiabilidad; una corrección y aprobada; 4 hallazgos)

- **R4-001** (`src/churnrisk/export.py`, líneas 238-259; crítico, inferencial): un proceso muerto entre escribir la tabla de corridas y actualizar su manifiesto deja un conjunto que no verifica.
  - Estado: **corregida** en `c18e47f` (D80): una reescritura que no se puede hacer sobre un manifiesto faltante o distinto queda en el registro, con la corrida y el motivo, y no toca nada.
- **R4-002** (`src/churnrisk/pipeline.py`, líneas 761-776; advertencia): `replay` toma el bloqueo y cada `run_all` lo vuelve a pedir adentro.
  - Estado: **dejada con evidencia**: es la toma anidada que admite U24; `2e41f80` la fija con una prueba de `replay` de varias corridas.
- **R3-001** (`src/churnrisk/pipeline.py`, líneas 301-325; bloqueante): una corrida sin entrega refrescaba las exportaciones antes de guardar su propio resultado, y la tabla de corridas y el HTML no se reescribían.
  - Estado: **corregida** en `c18e47f` (D80).
- **R3-002** (`src/churnrisk/export.py`, líneas 244-252; advertencia): el `BEGIN IMMEDIATE` manual supone una conexión en modo de confirmación automática.
  - Estado: **dejada con evidencia**: `warehouse.connect()` abre en ese modo; `2e41f80` lo fija con una prueba.

## F1 (`fb59d06..2e41f80`; riesgo, resiliencia y confiabilidad; aprobada; 6 advertencias)

- **R4-boot-id-narrow-exception** (`src/churnrisk/lock.py`, líneas 196-204; advertencia): `_boot_id` solo atrapaba `OSError`, y un error de decodificación salía.
  - Estado: **corregida** en `6bda6c9`: un id de arranque que no se decodifica no es un id.
- **R4-required-star-eager-tables** (`src/churnrisk/site_export.py`, líneas 55-61; advertencia): `REQUIRED_STAR` exige tablas que el módulo solo consulta con el sello.
  - Estado: **dejada con evidencia**: el modelo estrella se reconstruye entero en una transacción, así que no hay un camino con una tabla y sin otra (`6bda6c9`).
- **R3-release-earlyreturn-wakeup-untested** (`src/churnrisk/lock.py`, líneas 396-405; advertencia): soltar un bloqueo tomado por otro proceso no probaba que despierte al hilo que espera.
  - Estado: **corregida** en `4b32b8e`.
- **R3-boot-id-real-read-untested** (`src/churnrisk/lock.py`, líneas 197-205; sugerencia): `_boot_id` nunca se probaba de verdad, siempre reemplazado.
  - Estado: **corregida** en `4b32b8e`: en Linux, fuera de Linux, vacío e ilegible (la prueba con el archivo real se salta en Windows).
- **R3-acquire-wait-no-timeout** (`src/churnrisk/lock.py`, línea 369; sugerencia): la espera de `acquire` no tiene tiempo máximo.
  - Estado: **abierta**.
- **R3-cards-benefit-zero-divisor-untested** (`src/churnrisk/dashboard/render.py`, líneas 196-199; sugerencia): con un divisor cero, las tarjetas de contactos y beneficio no tenían prueba.
  - Estado: **corregida** en `4b32b8e`.

## F2 (`2e41f80..17d123a`; riesgo, legibilidad y confiabilidad; aprobada; 6 advertencias)

- **R2-bootstrap-offset-arithmetic** (`tests/integration/test_model.py`, líneas 43-50; advertencia): el remuestreo de la prueba pasó a una sola expresión vectorizada difícil de leer.
  - Estado: **abierta**.
- **R2-own-sheets-regex-xml** (`tests/fixtures/make_fixture.py`, líneas 787-833; advertencia): un lector a mano, con expresiones regulares, del XML que el propio accesorio escribe.
  - Estado: **abierta**.
- **R2-id-based-memoization** (`tests/fixtures/make_fixture.py`, líneas 713-716; sugerencia): `_truth` recuerda el cliente de cada fila por `id()`.
  - Estado: **abierta**.
- **R2-cli-imports-test-module** (`src/churnrisk/cli.py`, líneas 138-147; advertencia): `make-fixture` importa su generador desde `tests/`.
  - Estado: **corregida** en `6bda6c9`: sin la carpeta `tests`, sale con 2 y un mensaje en español.
- **R3-docs-sync-missing-summary-untested** (`src/churnrisk/cli.py`, líneas 158-159; advertencia): `docs-sync` sin el resumen no tenía prueba.
  - Estado: **corregida** en `4b32b8e`.
- **R3-make-fixture-imports-tests-tree** (`src/churnrisk/cli.py`, líneas 138-147; sugerencia): sin la carpeta `tests`, `make-fixture` fallaba con una traza.
  - Estado: **corregida** en `6bda6c9`.

## U27 (`17d123a..4a9d9f2`; riesgo, resiliencia y confiabilidad; aprobada; 5 advertencias)

- **R4-sqlite-race-window** (`airflow/docker-compose.yaml`, líneas 168-174; advertencia): `airflow dags test` corre fuera de la guarda del planificador, y el bloqueo solo se tiene mientras corre una tarea.
  - Estado: **abierta**: el compose y el runbook (R8) dicen que se corre con el planificador detenido.
- **R4-postgres-password-rotation-restart-loop** (`airflow/docker-compose.yaml`, líneas 69-82; advertencia): PostgreSQL aplica su contraseña solo al crear su carpeta de datos; cambiarla después deja a Airflow sin conectar.
  - Estado: **abierta**: el runbook (R8) dice qué hacer.
- **R4-nan-masking-in-xcom-summary** (`airflow/dags/churnrisk_monthly.py`, líneas 41-53; sugerencia): el resumen que va a XCom cambiaba un número no finito por nulo sin decirlo.
  - Estado: **corregida** en `6bda6c9`: avisa con la tarea y la clave.
- **R3-001** (`tests/unit/test_compose.py`, líneas 64-66; advertencia): el YAML del compose se comprueba con expresiones regulares, no con un lector de YAML.
  - Estado: **dejada con evidencia**: ninguna dependencia del proyecto es un lector de YAML (`requirements.txt` y `requirements-dev.txt`), y no se suma una para esto (`4b32b8e`).
- **R3-002** (`tests/e2e/test_airflow_docker.py`, líneas 46-52; sugerencia): la prueba de Docker pasa las claves por el entorno y apunta al `.env.example` vacío, así que no prueba la lectura de `.env`.
  - Estado: **abierta**.

## U28 (`4a9d9f2..ca3d2df`; legibilidad y confiabilidad; aprobada; 7 advertencias)

- **R2-figures-makefigures-atomicity-doc** (`src/churnrisk/figures.py`, líneas 296-306; advertencia): el docstring prometía más de lo que hacía: las figuras se escribían una por una.
  - Estado: **corregida** en `6bda6c9`: todas se preparan junto a su destino y se reemplazan solo cuando todas se escribieron.
- **R2-figures-loadsite-duplicate-check** (`src/churnrisk/figures.py`, líneas 49-60; sugerencia): `load_site` comprueba que existan los archivos y `read_site` lo vuelve a hacer.
  - Estado: **abierta**.
- **R2-cli-figures-except-filenotfound** (`src/churnrisk/cli.py`, línea 171; advertencia): `figures` atrapa solo `FileNotFoundError`.
  - Estado: **dejada con evidencia**: `SiteSetError` es un `FileNotFoundError`, y la prueba de punta a punta de una carpeta mezclada sale con 2 (`6bda6c9`); el runbook (R10) lo muestra.
- **R2-figures-shap-test-variable-name** (`src/churnrisk/figures.py`, línea 227; sugerencia): la variable `test` es un booleano con el nombre del bloque de la prueba.
  - Estado: **abierta**.
- **R3-1** (`src/churnrisk/figures.py`, líneas 135-158; advertencia): la figura de la definición fallaba con una celda oculta.
  - Estado: **corregida** en `6bda6c9`: la dibuja como un hueco con «celda oculta».
- **R3-2** (`src/churnrisk/cli.py`, líneas 169-172; sugerencia): lo mismo que `R2-cli-figures-except-filenotfound`, visto por la confiabilidad.
  - Estado: **dejada con evidencia**: la misma evidencia.
- **R3-3** (`tests/unit/test_figures.py`, líneas 85-87; sugerencia): la prueba de determinismo compara dos dibujos del mismo proceso.
  - Estado: **corregida** en `4b32b8e`: dos figuras dibujadas por otro proceso unos segundos después son iguales byte a byte.

## G1 (`ca3d2df..4b32b8e`; resiliencia, legibilidad y confiabilidad; aprobada; 6 advertencias)

- **R4-figures-partial-rename-observability** (`src/churnrisk/figures.py`, líneas 318-327; advertencia): si falla el renombrado final, quedan figuras nuevas y viejas mezcladas y nada lo registra.
  - Estado: **abierta**.
- **R2-cli-dup-module-literal** (`src/churnrisk/cli.py`, línea 146; sugerencia): los tres nombres de módulo del mensaje de `make-fixture` se repiten a mano junto a la importación.
  - Estado: **abierta**.
- **R2-figures-reversed-exitstack-order** (`src/churnrisk/figures.py`, línea 315; advertencia): el orden de reemplazo depende de entrar a los contextos al revés.
  - Estado: **abierta**.
- **R2-figures-duplicated-hidden-cell-logic** (`src/churnrisk/figures.py`, líneas 148-152; sugerencia): el dibujo de la celda oculta se repite en los dos paneles de la misma figura.
  - Estado: **abierta**.
- **R3-rename-partial-failure-untested** (`src/churnrisk/figures.py`, líneas 302-325; advertencia): la falla del renombrado que el docstring admite no tiene prueba.
  - Estado: **abierta**.
- **R3-make-fixture-importerror-not-generalized** (`src/churnrisk/cli.py`, líneas 143-149; sugerencia): un `ImportError` que no es `ModuleNotFoundError` sigue saliendo como traza.
  - Estado: **abierta**.

## D86 (`4b32b8e..4d0a36b`, la corrección de las celdas chicas; riesgo y confiabilidad; aprobada; 2 advertencias)

- **R3-reason-tie-coverage** (`tests/contract/test_site_export.py`, líneas 400-420; advertencia): el desempate de la supresión secundaria de los motivos, por `reason_key`, no tiene prueba.
  - Estado: **abierta**.
- **R3-shap-passthrough-unverified** (`tests/contract/test_site_export.py`, líneas 329-359; sugerencia): las pruebas comparan las cuentas de las celdas mostradas, no el riesgo, la tasa ni la contribución media que pasan sin cambiar.
  - Estado: **abierta**.

## U29-1 (la prueba, D85, el sello y el resumen; riesgo y confiabilidad; aprobada; 3 advertencias)

- **R3-001** (`tests/e2e/test_real.py`, líneas 87-92; advertencia): el contador de memoria guardado se compara con el de la plataforma de quien corre la prueba, no con una propiedad de la corrida.
  - Estado: **abierta**.
- **R3-002** (`tests/e2e/test_real.py`, líneas 5-7; advertencia): el docstring y D85 afirman qué pasa al repetir la corrida después del sello sin una prueba que lo muestre.
  - Estado: **abierta**: la evaluación independiente repite la corrida real (plan, sección 28).
- **R3-003** (`reports/evaluation_summary.json`, línea 88; sugerencia): C07 guarda el sesgo del propio modelo en `baseline_value`, que en los demás criterios es el valor de otro método.
  - Estado: **abierta**.

## U29-2a (el reporte de validación; riesgo y confiabilidad; aprobada; 2 advertencias)

- **R3-1** (`reports/validation/latest.json`, línea 2; advertencia): la clave de corrida, con su hora, queda dentro de un reporte versionado, que no se puede comparar entre repeticiones.
  - Estado: **abierta**.
- **R3-2** (`reports/validation/latest.json`, líneas 148-151; sugerencia): las reglas con muchas filas afectadas traen solo 5 ejemplos.
  - Estado: **abierta**: el registro (L53) no nombra este hallazgo.

## U29-2b (los Parquet; riesgo y confiabilidad; aprobada; 2 advertencias)

- **R3-manifest-integrity-unverified** (`outputs/powerbi/manifest.json`, líneas 1-139; advertencia): ninguna prueba compara los tamaños y huellas del manifiesto con los Parquet versionados.
  - Estado: **abierta**.
- **R3-run-key-nondeterministic** (`outputs/powerbi/manifest.json`, línea 136; sugerencia): la clave de corrida del manifiesto cambia en cada repetición aunque los datos sean iguales.
  - Estado: **abierta**.

## U29-2c (el HTML; riesgo y confiabilidad; una corrección; 4 hallazgos)

Esta revisión abrió una corrección; la corrección amplió el alcance, la revisión se recuperó y la aprobó la sucesora (sección siguiente). Sus hallazgos no figuran en los archivos de advertencias: salen del registro (L53), que les da un nombre solo al primero; los otros tres se nombran aquí por lo que dicen.

- **R3-dim-as-of-dead-slicer** (página 3 del diseño; crítico): el filtro de fechas de la página de seguimiento estaba enlazado a `dim_as_of`, que no filtra `fact_tracking`.
  - Estado: **corregida** en `fe25112`: el filtro usa `dim_date[date]`, que tiene una relación activa con `fact_tracking`; la escribió un agente con Sonnet, con la prueba primero, y el HTML lo regeneró el renderizador. Después, `aad019b` lo pasó a `dim_as_of[as_of_label]`, con su relación R19 (D90).
- **L53-slicer-739-dias** (página 3 del diseño; advertencia): con la corrección, el filtro lista 739 días de calendario para 6 fechas de cálculo.
  - Estado: **corregida** en `aad019b`: el filtro usa `dim_as_of[as_of_label]`, que lista solo las 6 fechas de cálculo (A10 de la evaluación, D90).
- **L53-dim-as-of-sin-uso** (`dim_as_of`; advertencia): después de la corrección, `dim_as_of` no lo usa ningún visual.
  - Estado: **corregida** en `aad019b`: R19 lo relaciona con `fact_tracking[as_of_key]` y es el filtro de la página 3 (D90).
- **L53-slicers-pagina-1** (página 1 del diseño; advertencia): los filtros de país y de banda de riesgo de la página 1 no llegan al gráfico de motivos.
  - Estado: **corregida** en `aad019b`: el título del gráfico dice que es de todo el corte y que el país y la banda no lo filtran (D90).

## U29-2c-sucesora (el HTML con la corrección; confiabilidad; aprobada; 2 advertencias)

- **R3-dim-as-of-fix-verified** (`tests/unit/test_semantic_model.py`, líneas 211-243; sugerencia): la prueba nueva prueba directamente la corrección del filtro.
  - Estado: **dejada con evidencia**: es una confirmación, no un defecto: `test_the_slicers_of_the_tracking_page_filter_every_one_of_its_visuals` pasa en la suite rápida. El registro (L53) no nombra este hallazgo.
- **R3-generic-slicer-test-weak-any** (`tests/unit/test_semantic_model.py`, líneas 217-222; sugerencia): la prueba general de los filtros se conforma con que un filtro llegue a algún visual de su página, no a todos.
  - Estado: **corregida** en `aad019b`: la prueba pide que cada filtro llegue a cada visual de su página, o que el título del visual diga que ese filtro no lo filtra, y solo si es cierto (D90).

## U29-3 (los archivos del sitio salvo `algorithms.json`; riesgo y confiabilidad; aprobada; 1 advertencia)

- **R1-001** (`outputs/site/retention.json`, líneas 61-81; advertencia): dentro de países publicados, con al menos 10 clientes, hay cuentas de contactados de menos de 10.
  - Estado: **abierta**: es lo que fijan D27 y D68 (la celda es el país, de al menos 10 clientes); D85 la deja para que la vuelva a revisar la evaluación independiente.

## U29-4 (`algorithms.json`; riesgo y confiabilidad; aprobada; 2 advertencias)

- **R3-001** (`outputs/site/algorithms.json`, líneas 194-200; advertencia): en la curva de costo, el beneficio del modelo se queda en 0 cuando su umbral se satura y el de B* baja de 0.
  - Estado: **abierta**: para la evaluación independiente (L53).
- **R3-002** (`outputs/site/algorithms.json`, líneas 38-44; sugerencia): los intervalos ocultos de la calibración no dicen si se ocultan por tener pocas filas o por la regla secundaria.
  - Estado: **abierta**.

## U31 (lo que encontró la documentación; 2 hallazgos)

- **plan-24.2-test_privacy** (`tests/integration/test_privacy.py`; advertencia): el plan, sección 24.2, nombra `test_no_fixture_customer_id_in_any_versioned_byte_or_run_log` y ninguna unidad la escribió: el archivo no existe. Otras pruebas cubren partes de la clase (`tests/contract/test_site_export.py::test_no_identifier_or_sentinel_and_small_cells_suppressed`, `tests/unit/test_render.py::test_html_has_every_page_escapes_data_text_and_masks_the_customer_column`, `tests/contract/test_star_schema.py::test_the_customer_level_fact_is_written_outside_the_versioned_folder`), pero ninguna recorre cada byte versionado y los registros de corrida.
  - Estado: **corregida** en `969f2b4` y `07d2a54`: la prueba existe y `KNOWN_MISSING` está vacío (A11 de la evaluación, D92).
- **resumen-C07-barras** (`reports/evaluation_summary.md`, la fila de C07; advertencia): el umbral de C07 escribe «|sesgo|» sin escapar las barras, así que la tabla del resumen, y con ella el bloque de resultados del README, se ve con una columna de más en esa fila.
  - Estado: **corregida** en `1829c5f`: `summary_markdown` escapa las barras de cada celda; el resumen se regeneró y `docs-sync` lo copió en el README (A4 de la evaluación, D91).

## Evaluación (la evaluación independiente de `e28b1fb`; un bloqueante y 18 advertencias)

Un agente con Opus que no construyó el proyecto lo evaluó en un clon aparte (L55). El registro eligió qué corregir; las demás quedan como advertencias, dichas aquí y en las decisiones que nombra cada una.

- **B1** (README, ficha del modelo, paso a paso, D87, D88 y `SITE-UPDATES.md`; bloqueante): la documentación decía de U30 y U31 quién las escribió, con qué modelo y en cuánto tiempo corrió la suite, y el registro en `e28b1fb` terminaba en L53; el README decía además «29 unidades».
  - Estado: **corregida** en `e87dd0e` (L54 registra U30 y U31) y en el commit de documentación que sigue a `07d2a54`: cada afirmación dice lo que dicen L54 y L55, y el README dice 31 unidades.
- **A1** (`src/churnrisk/pipeline.py`; advertencia): la parte de la prueba del sello se podía escribir después de una evaluación posterior al sello, con la fecha de cálculo del 2011-12-09.
  - Estado: **corregida** en `c139ca2`: mientras el sello no tiene la parte de la prueba, una corrida que la evaluaría con otra configuración se rechaza antes de escribir (D89, R13).
- **A2** (`src/churnrisk/reporting.py`; advertencia): en un resumen posterior al sello, los costos de arriba eran los de la corrida, junto a cifras selladas.
  - Estado: **corregida** en `969f2b4` (D92; la misma que `U17/R3-post-seal-costs-staleness`).
- **A3** (`reports/evaluation_summary.json`, `outputs/site/summary.json`; advertencia): el resumen versionado nombra claves de corrida del sello (18:20 y 18:23) distintas de las del sello versionado (17:46 y 17:49).
  - Estado: **abierta**: lo dice D85 (el sello es el de la primera corrida y las salidas, las de la repetición); el registro lo deja así (L55).
- **A4** (`reports/evaluation_summary.md`, la fila de C07; advertencia): «|sesgo|» sin escapar parte la fila (la misma que `U31/resumen-C07-barras`).
  - Estado: **corregida** en `1829c5f` (D91).
- **A5** (el veredicto de C09; advertencia): «no deja … en 9 de los 17» se lee como 9 fallas, y 9 son los puntos donde el modelo cumple; C09 es además frágil: con los parámetros del óptimo de `lifetimes`, B* en el punto 0,10 da 2.501,9 contra 2.502,2 del modelo.
  - Estado: **corregida** en `1829c5f`: la fila del resumen dice en cuántos puntos el modelo deja al menos el beneficio de B* (9) y en cuántos no (8), sin cambiar el veredicto sellado (D91). La fragilidad queda dicha aquí.
- **A6** (`outputs/site/algorithms.json`, la curva de costo; advertencia): el 0 del modelo contra los valores negativos de B* sale de la grilla (sin «no contactar a nadie» cuando p ≥ 0,99); ninguna cifra publicada depende de eso.
  - Estado: **abierta** (la misma clase que `U29-4/R3-001`).
- **A7** (`outputs/site/algorithms.json`, `b_star.auc_valid`; advertencia): el 0,766 es el AUC de V2 sola, rotulado `chosen_on: valid`; el que decidió (V1 y V2) es cerca de 0,767, y B3 le gana a B4 por 0,0008.
  - Estado: **abierta**.
- **A8** (`capture_10` de las reglas con empates; advertencia): depende del orden interno: B4 da 234 contra 244,6 esperado con empates al azar, B2 259 contra 260,4; C04 usa B3, sin empates.
  - Estado: **abierta**.
- **A9** (cuentas chicas dentro de celdas de al menos 10 y cuentas de validación de menos de 10; advertencia): aceptables según el evaluador, no por la letra de RNF12.
  - Estado: **abierta**: D27, D68, D85 y D86 las dicen; cambiar RNF12 o publicar «<10» es del dueño (L55).
- **A10** (`dashboard/powerbi-design.html`, páginas 1 y 3; advertencia): el filtro de la página 3 lista 739 días para 6 fechas de cálculo, `dim_as_of` no tiene relación ni visual, y los filtros de país y banda no llegan al gráfico de motivos.
  - Estado: **corregida** en `aad019b` (D90).
- **A11** (`tests/integration/test_privacy.py`; advertencia): la prueba de privacidad del plan no existía (D88).
  - Estado: **corregida** en `969f2b4` y `07d2a54` (D92).
- **A12** (`src/churnrisk/lock.py`; advertencia): un bloqueo que quedó por una liberación fallida rechaza incluso a su propio proceso vivo, y uno viejo se borra a mano.
  - Estado: **abierta**: R9 dice cómo borrarlo; reconocer la ficha del dueño queda para otra tanda (L55).
- **A13** (`tests/e2e/test_airflow_docker.py`; advertencia): la prueba de Docker dejaba la imagen `churnrisk-airflow:3.4.0`.
  - Estado: **corregida** en `969f2b4`: la borra si la construyó (D92).
- **A14** (`tests/integration/test_evaluation.py`, `tests/contract/test_star_schema.py`; advertencia): la función auxiliar `test_delivery` se recogía como prueba, y había un escape inválido.
  - Estado: **corregida** en `969f2b4`: `tests/unit/test_sources.py` vigila los dos casos (D92).
- **A15** (`src/churnrisk/pipeline.py`; advertencia): una corrida rechazada porque otra más vieja tiene la entrega termina con 1 y deja su estado `failed`.
  - Estado: **abierta**: R4 lo dice.
- **A16** (`SITE-UPDATES.md`; advertencia): el «77,9 %» no nombraba su corte.
  - Estado: **corregida** en el commit de documentación que sigue a `07d2a54`: es el del 2011-09-01.
- **A17** (`reports/validation/`; advertencia): los ejemplos de la validación versionados llevan `line_id`, código de producto y fecha, que señalan una línea de la fuente pública.
  - Estado: **abierta**: riesgo bajo según el evaluador; la fuente es pública.
- **A18** (la suite rápida; advertencia): sobre el presupuesto de trabajo de 100 s, como dice la ficha del modelo.
  - Estado: **abierta**: al cerrar las correcciones midió 118,99 s y 119,17 s, dentro del límite de 120 s.
