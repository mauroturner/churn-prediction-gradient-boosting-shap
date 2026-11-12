# Runbook: qué hacer cuando algo no sale como se esperaba

Todos los comandos son para Windows (PowerShell), dentro de la carpeta `04-Ecommerce-Churn-Risk/` y con el entorno del proyecto. El paquete no está instalado en el entorno: una vez por sesión,

```powershell
$env:PYTHONPATH = "src"
.venv\Scripts\python -m churnrisk --help
```

Cada comando de este documento se corrió al escribirlo (U31), en una copia del proyecto y en modo rápido (`--config config\pipeline.quick.toml`, que lee y escribe solo en `data\quick\`) salvo donde se dice otra cosa, y el código de salida que se indica es el que dio. Los mensajes se citan tal como salen, con las rutas, las claves de corrida y el nombre del equipo abreviados. Lo que no se pudo provocar en una copia (una descarga real que falla, un SHAP que no suma, Airflow en Docker) se describe sin comandos, y lo dice.

Códigos de salida de la CLI (`src/churnrisk/cli.py`): `0` terminó bien (también una corrida sin entrega pendiente), `1` falló una tarea, `2` uso o configuración incorrectos (también una tarea rechazada por el estado de su corrida o porque otro proceso tiene la carpeta de datos), `3` la entrega o la fuente fueron rechazadas por la validación. Cada corrida deja su estado en `data\interim\runs\<run_key>.json`, tarea por tarea, con sus tiempos, sus picos de memoria con el contador y, si falló, la traza completa (la CLI la muestra con `-v`); la última validación queda en `reports\validation\latest.md` y las anteriores en `reports\validation\history\`.

Tres principios valen para todo el documento:

- **Un rechazo antes de la carga no deja nada a medias.** Si algo falla antes de `load`, el almacén, los Parquet, los JSON del sitio, el HTML y el sello quedan byte a byte como estaban (RF09); si falla después, la corrida queda `failed` y se retoma con su misma clave: `python -m churnrisk run --run-key <run_key> --from <tarea>`.
- **Una corrida cerrada no se vuelve a abrir.** Cualquier tarea de una corrida `ok` o `no_delivery` se rechaza con código `2` antes de escribir nada: la entrega siguiente es otra corrida.
- **El sello no se toca.** `reports\model_seal.json` guarda la configuración del lanzamiento y el primer resultado de la prueba; ninguna tarea lo reescribe con otros valores, y una evaluación con otra configuración se guarda aparte, como posterior al sello (D19, D20). Nada de este documento pide editarlo a mano.

Comandos que se corrieron para comprobar los principios, en modo rápido:

```powershell
# Una tarea de una corrida cerrada (código 2):
.venv\Scripts\python -m churnrisk task report --config config\pipeline.quick.toml --run-key <corrida cerrada>
# error: la corrida <corrida cerrada> está cerrada (estado ok): no se vuelve a abrir para correr report; otra entrega es otra corrida (python -m churnrisk run)

# Una corrida nueva que no empieza por fetch_source (código 2, antes de crear su estado):
.venv\Scripts\python -m churnrisk run --config config\pipeline.quick.toml --only load
# error: una corrida nueva empieza por fetch_source, no por load: indique con --run-key la corrida que continúa (...). No se escribió nada.

# Una tarea suelta de una corrida que no corrió las anteriores (código 1; el estado queda con la causa):
.venv\Scripts\python -m churnrisk task track --config config\pipeline.quick.toml
# falló: RunStateError: la corrida <nueva> no tiene el resultado de la tarea deliver: corra esa tarea antes (python -m churnrisk task deliver --run-key <nueva>)
```

## R1 La huella del zip cambió

**Síntoma.** `fetch_source` termina con código `3`, la CLI dice «rechazada: la validación de <corrida> rechazó la corrida: fallan las reglas bloqueantes V01» y el registro, «validation of <corrida> (source): rejected; rows=0; blocking failed: V01». El mensaje de la regla, en `reports\validation\latest.md`, dice «el zip … tiene la huella SHA-256 X y la aceptada es Y; no se cambió nada (runbook R1)»; en modo local, «la registrada» en lugar de «la aceptada».

**Qué significa.** El zip que hay en `data\raw\`, o el que llegó por la dirección configurada, no es el que se evaluó. La descarga se escribe en un archivo de preparación propio y solo se renombra si la huella coincide, así que no se tocó nada: ni el zip aceptado, ni la base canónica, ni el almacén.

**Qué hacer.**

1. Calcular la huella del archivo y compararla con la aceptada (`[source] accepted_sha256` en `config\pipeline.toml`, `572e3627…7bfb`). En el proyecto dio la fijada (código 0):

   ```powershell
   (Get-FileHash -Algorithm SHA256 data\raw\online_retail_ii.zip).Hash
   # 572E36277C2390FBFDE10664750731E0A86F55E33470D91919085F0408E67BFB
   ```

2. Si el archivo está cortado o dañado, borrarlo y volver a correr: el flujo lo descarga de nuevo (R2).
3. Si es una versión nueva y legítima del conjunto (R11), **no cambiar la huella sin más**: los criterios, los recuentos y el sello son de la versión actual. Registrar una decisión nueva en `docs/decisions.md`, cambiar `accepted_sha256` y `member_sha256`, reconstruir desde cero (R10) y tratar el resultado como un análisis nuevo, posterior al sello.
4. En modo local, la primera huella se registra en `source_manifest.json` y las siguientes deben coincidir: el mensaje quiere decir que se cambió el archivo local. Se comprobó así, con código `3`: después de un lanzamiento rápido, `make-fixture data\quick\online_retail_fixture.zip --seed 1` (código 0) escribe otro libro en la misma ruta, y la corrida siguiente lo rechaza. Volver a escribir el accesorio con la semilla de siempre (`make-fixture data\quick\online_retail_fixture.zip`, código 0) da los mismos bytes y la corrida siguiente sigue; si no, se borra `data\quick\` y se empieza de nuevo.

## R2 Descarga fallida o redirección rechazada

**Síntoma.** `fetch_source` falla con un error de descarga (un tiempo máximo superado, un HTTP 5xx, un tamaño anunciado por encima del tope), o termina con código `3` y V02 por un salto que no es HTTPS, un host que no está en `[source] allowed_hosts` o más de 3 redirecciones. Una dirección configurada con un host que no está en la lista ni siquiera se intenta: la configuración se rechaza al leerla, con código `2`.

**Qué pasó.** La descarga sigue cada redirección a mano: cada salto debe ser HTTPS, ir a un host de `[source] allowed_hosts` (hoy solo `archive.ics.uci.edu`; UCI no redirigía cuando se escribió U04, D50) y no pasar de 3 redirecciones, 64 MiB ni 900 s. Se escribe en un archivo de preparación de nombre propio y, ante cualquier falla, se borra; el zip aceptado, los intermedios y el manifiesto no cambian. Un archivo de preparación puede quedar si el proceso muere de golpe a la mitad (advertencia `U04/R4-staging-leak`, abierta): se borra a mano, porque nunca se lee como fuente.

**Qué hacer.**

1. Reintentar. Airflow reintenta `fetch_source` según su `TaskSpec`; en la CLI, `python -m churnrisk run`. Una descarga real no se provocó al escribir este documento.
2. **El tiempo máximo es también un piso de velocidad**: 900 s para 45.622.418 bytes exigen unos 51 kB/s. En un enlace más lento se sube `source.max_seconds`.
3. Si el host es otro, comprobarlo antes de agregarlo. Se probó con una configuración que extiende `pipeline.toml` y cambia `[source] url` a un host ajeno (código `2`, nada escrito):

   ```powershell
   .venv\Scripts\python -m churnrisk run --config config\r2.toml --only fetch_source --run-key R2A
   # error: [source] url: el host 'example.org' no está en allowed_hosts ['archive.ics.uci.edu']
   ```

   Un host nuevo es una decisión nueva (D02): se agrega el nombre exacto, nunca un sufijo.

## R3 Entrega rechazada, o `load` rechazado por la validación

**Síntoma.** `validate` termina con código `3` y la CLI dice «rechazada: la validación de <corrida> rechazó la corrida: fallan las reglas bloqueantes …», con las reglas que fallaron en `reports\validation\latest.md`; o `load` se rechaza con código `2` porque la corrida no validó su entrega.

**Qué significa.** Una regla bloqueante de la entrega (V10 a V14; de las 18 bloqueantes, V01 a V06 son de la fuente y M01 a M04 y M06 a M08 del modelo; plan, sección 6) encontró la entrega dañada; la entrega queda `rejected` en el manifiesto de entregas y el almacén, los Parquet, el HTML, el sitio y el sello quedan como estaban. La entrega rechazada sigue siendo la pendiente: la corrida siguiente la vuelve a publicar y a validar. `load` carga solo una entrega que la validación de su misma corrida aprobó (RF10).

**Qué hacer.**

1. Leer `reports\validation\latest.md`: cada regla dice cuántas filas, clientes e importe afecta, con ejemplos sin números de cliente.
2. Si el problema está en la fuente, es R1 o R11; si es una regla demasiado estricta para un caso legítimo, es una decisión nueva, nunca una regla apagada a mano.
3. Para `load` rechazado, seguir la corrida desde `validate` con su misma clave. Se comprobó así:

   ```powershell
   .venv\Scripts\python -m churnrisk run --config config\pipeline.quick.toml --only fetch_source deliver --run-key R3A   # código 0
   .venv\Scripts\python -m churnrisk task load --config config\pipeline.quick.toml --run-key R3A                         # código 2
   # error: la corrida R3A no validó su entrega: load carga solo una entrega que la validación de su corrida aprobó (python -m churnrisk run --run-key R3A --from validate)
   .venv\Scripts\python -m churnrisk run --config config\pipeline.quick.toml --run-key R3A --from validate                # código 0
   ```

## R4 Entregas fuera de orden o faltantes

**Síntoma.** `replay --until` se rechaza con código `2`, o `deliver` falla con un mensaje que termina en «(runbook R4)»: una entrega del manifiesto que no está en el plan, con otro período, cargada después de una que no lo está, o publicada de nuevo con otra huella.

**Qué significa.** El plan de entregas sale de la configuración (D11): el lanzamiento `L2011-07`, las mensuales `M2011-08` a `M2011-11` y el cierre `C2011-12`, en ese orden. La siguiente pendiente es siempre la primera que no está cargada; ninguna se salta y una cargada no se vuelve a publicar.

**Qué hacer.**

1. Para `replay`, nombrar una entrega del plan igual o posterior a la pendiente. Se comprobó, después de un lanzamiento rápido (código `2` las dos, nada escrito):

   ```powershell
   .venv\Scripts\python -m churnrisk replay --config config\pipeline.quick.toml --until L2011-07
   # error: --until L2011-07: es anterior a la siguiente entrega pendiente, M2011-08; no hay nada que correr hasta ella. No se escribió nada.
   .venv\Scripts\python -m churnrisk replay --config config\pipeline.quick.toml --until Z2099-01
   # error: --until Z2099-01: no es una entrega del plan (L2011-07, M2011-08, M2011-09, M2011-10, M2011-11, C2011-12)
   ```

2. Si el manifiesto de entregas (`data\raw\deliveries\manifest.json`) no coincide con el plan, es que cambió la configuración de las entregas o se editó el manifiesto: se reconstruye desde cero (R10), nunca se edita a mano.
3. Con todas cargadas, una corrida termina como `no_delivery` con código 0 y el mensaje «no hay entregas pendientes: las 6 del plan ya están cargadas».

## R5 La trampa de fuga detuvo el lanzamiento

**Síntoma.** `fit_model` del lanzamiento falla con código `1`: «falló: LeakageError: M01: el AUC del candidato elegido en V1 es X, igual o mayor que el umbral de 0.95: posible fuga de información (el conjunto …). El lanzamiento se detiene (docs/runbook.md, R5)». No queda ningún modelo registrado ni parte del sello.

**Qué significa.** Un AUC de 0,95 en V1 no es creíble con estos datos (el modelo real dio 0,7447 en la prueba): casi seguro una variable mira la ventana de la etiqueta. La demostración de fuga lo muestra: con los días hasta la próxima compra, F1 llega a un AUC de 1,000 en V2 (`outputs/site/label.json`, `leakage`). La trampa se comprobó en modo rápido bajando el umbral a 0,51 en una configuración que extiende la rápida (`[criteria] leak_tripwire_auc = 0.51`; 0,5 se rechaza al leerla, con código 2): el lanzamiento se detuvo con código `1`, sin `data\quick\models\` ni sello.

**Qué hacer.**

1. No subir el umbral. Buscar la variable: `git log -p -- src/churnrisk/features.py sql/` desde el último lanzamiento que pasó, y correr las pruebas de fuga (`tests/integration/test_no_leak.py`, `tests/unit/test_features.py`).
2. Corregir con una prueba que falle primero y volver a correr el lanzamiento: como no quedó nada registrado, la corrida se retoma desde `fit_model` con su misma clave, o se empieza de nuevo.

## R6 El artefacto del modelo no coincide con su huella

**Síntoma.** `fit_model` de una corrida mensual falla con código `1`: «falló: ArtifactMismatchError: M03: el artefacto v1.pkl tiene la huella … y la registrada es …: no se deserializó. Se restaura el archivo registrado o se vuelve a entrenar desde el lanzamiento (docs/runbook.md, R6)».

**Qué significa.** El archivo `data\models\v1.pkl` cambió después de registrarse: el flujo nunca deserializa un artefacto cuyos bytes no tienen el SHA-256 registrado (D40), porque un pickle ajeno puede ejecutar código.

**Qué hacer.**

1. Restaurar el archivo registrado desde una copia y retomar la corrida desde `fit_model` con su misma clave. Se comprobó en modo rápido agregando un byte al artefacto: la corrida siguiente falló con código `1`; con el archivo restaurado,

   ```powershell
   .venv\Scripts\python -m churnrisk run --config config\pipeline.quick.toml --run-key <corrida que falló> --from fit_model
   ```

   terminó con código 0 (`fit_model … seal_state=match`).

2. Sin copia del artefacto, no hay forma de reproducir los puntajes sellados con otro: se reconstruye desde cero (R10) y, si la configuración es la sellada, el lanzamiento nuevo debe reproducir el sello.

## R7 La evaluación no reproduce el sello

**Síntoma.** Una corrida falla con `SealMismatchError`: «M05: la configuración es la sellada pero el lanzamiento no la reproduce: …», «la evaluación de la prueba con la configuración sellada no reproduce los valores sellados, redondeados a 6 …» o «lo que consta en el sello no es lo que esta corrida escribió: otra escritura lo cambió (docs/runbook.md, R7)». En Windows, cada escritura del sello deja además el aviso «seal model_seal.json: the owner-only mode 0o600 is not enforced on this system (os.name nt); who can read it is decided by the access list of the folder … (runbook R7)».

**Qué significa.** Con la misma huella de configuración, el flujo esperaba los mismos valores, y no salieron: cambió una versión de una dependencia, la fuente o el código de un cálculo sellado. El aviso del modo 0o600 no es una falla: en Windows ese modo no es un control de acceso, y quién lee el sello lo decide la lista de acceso de la carpeta `reports\`.

**Qué hacer.**

1. No editar el sello. Comparar el entorno con los pines (`.venv\Scripts\python -m pytest tests/unit/test_dependencies.py`) y la fuente con su huella (R1).
2. Si cambió el código de un cálculo sellado, eso es una versión nueva del modelo (R13), no una corrección del sello.
3. La repetición que sí lo reprodujo está en D85: en una copia nueva del proyecto, con solo `data\raw\`, el sello salió igual en sus 485 valores salvo las dos claves de corrida.

## R8 Airflow no arranca

**Síntoma.** `docker compose up airflow-init` o `docker compose up -d` se detienen diciendo que falta una variable, el servicio de PostgreSQL no queda sano, o una tarea del DAG `churnrisk_monthly` se rechaza con código 2 porque otro proceso tiene la carpeta de datos (R9).

**Qué significa.** El compose (`airflow/docker-compose.yaml`) no tiene ningún secreto con valor por defecto: `CHURNRISK_FERNET_KEY`, `CHURNRISK_JWT_SECRET`, `CHURNRISK_ADMIN_PASSWORD` y `CHURNRISK_DB_PASSWORD` se leen del entorno con `${VAR:?}` (D29, D83). PostgreSQL aplica su contraseña solo al crear su carpeta de datos: cambiarla después en el entorno no la cambia en la base (advertencia `U27/R4-postgres-password-rotation-restart-loop`, abierta). `airflow dags test` corre fuera de la guarda del planificador, así que se corre con el planificador detenido (advertencia `U27/R4-sqlite-race-window`, abierta). En Linux hace falta `AIRFLOW_UID` con el id propio; Docker Desktop en Windows no lo necesita.

**Qué hacer.** La prueba de Docker (`tests/e2e/test_airflow_docker.py`, marca `docker`: construye la imagen, corre `pip check` y `airflow dags test` dos veces en modo rápido y al final borra lo que creó, la imagen incluida si no estaba antes) pasó en la evaluación independiente, 2 de 2 en 147,6 s en `e28b1fb`, y al cerrar sus correcciones, 2 de 2 en 95,44 s (`.venv\Scripts\python -m pytest -m docker`, código 0). Los pasos de abajo, con el archivo real, no se corrieron. Lo que dicen el compose y sus pruebas estáticas (`tests/unit/test_compose.py`, que pasan en la suite rápida): copiar `airflow/.env.example` a `airflow/.env` y completar las cuatro claves; `docker compose up airflow-init` y después `docker compose up -d`, desde `airflow/`; la interfaz queda solo en `127.0.0.1:8080`. Si se cambió la contraseña de la base después de crearla, o se cambia también dentro de PostgreSQL o se borra la carpeta de datos de PostgreSQL (que solo guarda los metadatos de Airflow, no el almacén del proyecto).

## R9 El bloqueo de un solo escritor y `database is locked`

**Síntoma.** Una corrida o una tarea se rechaza con código `2` antes de escribir nada: «Otro proceso escribe esta carpeta de datos: `<comando>` (…), proceso <pid> en <equipo>, desde <fecha>. Espere a que termine y vuelva a correr; con Airflow, detenga el planificador antes de usar `airflow dags test` (docs/runbook.md, R8 y R9). No se escribió nada.» O, si el proceso que lo tenía ya no está: «El bloqueo …\pipeline.lock quedó de un proceso que ya no está en marcha: … Ningún proceso lo borra solo: compruebe que nada más escribe esta carpeta (tampoco un contenedor que la monte), borre el archivo y, si esa corrida quedó a medias, retómela con `python -m churnrisk run --run-key <corrida> --from <tarea>` (docs/runbook.md, R9). No se escribió nada.»

**Qué significa.** Un solo proceso escribe una carpeta de datos a la vez (D31, D76): cada tarea toma `data\interim\pipeline.lock`, con el comando, la corrida, el proceso, el equipo y su arranque. Un bloqueo de un proceso vivo se respeta; uno de un proceso que ya no está se informa y no se borra solo, porque solo su dueño lo borra. `database is locked` es SQLite: otro escritor tuvo la escritura más de 30 s (`BUSY_TIMEOUT_MS`), lo que con el bloqueo no debería pasar salvo con `airflow dags test` y el planificador a la vez.

**Qué hacer.**

1. Si el proceso está vivo, esperar a que termine.
2. Si no lo está, comprobar que nada más escribe la carpeta y borrar el archivo. Se comprobó en modo rápido: un proceso propio tomó el bloqueo y otra corrida se rechazó con código `2`; terminado ese proceso de golpe, la corrida siguiente dio el segundo mensaje, también con código `2`; después de

   ```powershell
   Remove-Item data\quick\interim\pipeline.lock
   ```

   `run --config config\pipeline.quick.toml` siguió con la entrega pendiente y terminó con código 0.

3. Si la corrida del proceso muerto quedó `running` o `failed`, retomarla desde la tarea que no terminó, con su clave.

## R10 Reconstruir desde cero con el sello, y una carpeta del sitio que no verifica

**Síntoma.** Hace falta empezar otra vez (un almacén dañado, una tabla con otras columnas que las de su SQL, que se rechaza con `SchemaDriftError` «(runbook R10)», un cambio de la fuente o de las entregas); o `figures` se niega con código `2` porque los archivos del sitio no son de una misma exportación: «error: summary.json no es el que nombra manifest.json (otro tamaño o SHA-256): los archivos no son de una misma exportación. Corra el flujo (python -m churnrisk run) antes de dibujar las figuras. No se escribió ninguna figura.»

**Qué significa.** El almacén, los intermedios, el artefacto y las entregas se reconstruyen desde el zip; el sello no. Con el sello presente y la misma configuración, la repetición debe reproducir los valores sellados (R7); con otra, todo se guarda como posterior al sello. Los cinco archivos del sitio se leen solo si cada uno tiene el tamaño y el SHA-256 que dice `outputs\site\manifest.json` (D28, D84).

**Qué hacer.**

1. Reconstruir en una copia del proyecto, con solo `data\raw\` (el zip) en `data\`, y correr `replay` y después `run`: así se hizo la repetición de U29, que terminó con código 0 (D85). Comparar el sello que escribe con el versionado; si coincide salvo las claves de corrida, las salidas de la copia se pueden versionar.
2. Para el sitio, volver a exportar con una corrida (o reponer los seis archivos de una misma exportación) y dibujar otra vez. Se comprobó en una copia del proyecto: con un espacio agregado a `outputs\site\summary.json`, `figures` salió con código `2` y no escribió nada; con el archivo repuesto, `.venv\Scripts\python -m churnrisk figures` salió con 0 y las siete figuras quedaron iguales byte a byte a las versionadas.

## R11 UCI cambió la dirección o publicó otra versión

**Síntoma.** La descarga devuelve un error HTTP o una redirección a un host que no está en la lista (R2), o descarga un zip con otra huella (R1).

**Qué significa.** El conjunto «Online Retail II» (DOI 10.24432/C5CG6D) se descarga de `https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip`. Si UCI mueve el archivo, la dirección cambia; si publica otra versión, la huella cambia, y entonces los recuentos, los criterios y el sello ya no son comparables.

**Qué hacer.** Comprobar en la página del conjunto en UCI la dirección y, si existe, la versión. Una dirección nueva con el mismo archivo: cambiar `[source] url` (y `allowed_hosts`, con el nombre exacto, si el host es otro) en una decisión nueva; la huella debe seguir siendo la fijada. Otra versión: es R1, paso 3.

## R12 El modo rápido, dentro del contenedor y las rutas

**Síntoma.** El modo rápido escribe donde no se esperaba, `docs-sync` se niega en modo rápido, o un comando corrido desde otra carpeta lee otra configuración.

**Qué significa.** Toda ruta relativa de la configuración, de `--config` y de `CHURNRISK_CONFIG` se resuelve contra `CHURNRISK_HOME` o la carpeta del proyecto, nunca contra el directorio de trabajo (D32). El modo rápido lee y escribe solo en `data\quick\` y no tiene README, así que `docs-sync` no tiene adónde copiar. En el contenedor, `CHURNRISK_HOME` es la carpeta montada del proyecto.

**Qué hacer.** Se comprobó en una copia del proyecto:

```powershell
.venv\Scripts\python -m churnrisk make-fixture data\quick\online_retail_fixture.zip     # código 0
.venv\Scripts\python -m churnrisk replay --config config\pipeline.quick.toml            # código 0: seis corridas en 26,6 s
.venv\Scripts\python -m churnrisk docs-sync --config config\pipeline.quick.toml         # código 2
# error: docs-sync copia el resumen de resultados en el README de la configuración, …\data\quick\README.md, y ese archivo no existe: el modo rápido no tiene README, y su resumen queda en …\data\quick\reports\evaluation_summary.md. No se escribió nada.
```

Desde otra carpeta, con `$env:CHURNRISK_HOME` apuntando a la copia y `PYTHONPATH` a su `src`, `run --config config\pipeline.quick.toml` corrió la entrega pendiente con código 0 y no escribió nada en la carpeta de trabajo. Sin `PYTHONPATH`, Python no encuentra el paquete («No module named churnrisk», código 1).

## R13 Cambiar los costos supuestos, N o M, o hacer una versión 2 del modelo

**Síntoma.** Se quiere decidir con otros costos (`offer_cost`, `rescue_rate`, `retained_value`), otra ventana de etiqueta (N) o de población (M), u otro modelo.

**Qué significa.** Los costos, N y M están en la huella del sello (`config_sha256`): la prueba ya se evaluó con 5, 0,2 y 50 y N = M = 90 (D85). Mientras el sello no tiene la parte de la prueba, la corrida cuya fecha de cálculo cierra las ventanas de la prueba (la de `M2011-11`) solo corre con la configuración sellada: con otra, cada una de sus tareas se rechaza con código `2` antes de escribir nada, ni siquiera el estado de la corrida, y el mensaje nombra el comienzo de las dos huellas y las claves que difieren (D89). Así la prueba se toca una sola vez, con la configuración sellada y en su fecha. Una vez que el sello tiene la parte de la prueba, una corrida con otra configuración se marca `post_seal`: sus resultados se guardan aparte, el resumen los muestra como análisis posterior al sello y el resultado sellado no cambia (M05, D20). Las sensibilidades de N = 60, N = 120, M = 180 y sin diciembre ya están dentro del sello (D10). Los calibradores de las reglas se guardan por método y versión del modelo (D78), así que una versión 2 registra los suyos.

**Qué hacer.** Para costos, N o M: una configuración que extienda la del proyecto y cambie solo esas claves, y que corra después de que el sello tenga la parte de la prueba (en el proyecto ya la tiene: la corrida siguiente es una reconstrucción desde cero, R10). Se comprobó en modo rápido con `[costs] offer_cost = 8.0` en `config\costs8.quick.toml`, sobre una copia con `M2011-11` pendiente y el sello sin la parte de la prueba:

```powershell
.venv\Scripts\python -m churnrisk run --config config\costs8.quick.toml
# error: la corrida <nueva> evaluaría la prueba (entrega M2011-11, cálculo al 2011-11-30) con una configuración que no es la sellada: su huella empieza por 4b64a17f0f32 y la del lanzamiento sellado por f888900394c6 (difiere costs.offer_cost). Mientras el sello no tenga la parte de la prueba, la prueba se evalúa solo con la configuración sellada; fetch_source no corre (docs/runbook.md, R13). No se escribió nada.   (código 2; la carpeta data\quick quedó byte a byte igual)
.venv\Scripts\python -m churnrisk run --config config\pipeline.quick.toml
# … evaluate … seal_state=sealed, test=written · report … evaluation_status=sealed, run_status=ok   (código 0)
```

Antes de D89 esa misma corrida terminaba con código `0`, evaluaba la prueba como posterior al sello y dejaba que la corrida siguiente, con la configuración sellada, escribiera la parte de la prueba con la fecha de cálculo del 2011-12-09 (hallazgo A1 de la evaluación independiente). Para una versión 2 del modelo: cambiar `[model] model_version`, registrar la decisión y tratar su evaluación como posterior al sello de `v1`; los cambios de esquema de SQLite alcanzan solo a los almacenes nuevos (advertencia `U21-U25a/R4-threshold-check-no-retroactive-migration`, abierta), así que se reconstruye desde cero (R10).

## R14 SHAP no aditivo, o una versión nueva de `shap`

**Síntoma.** `score` o `evaluate` fallan con código `1` y `ExplanationError`: «M06: SHAP no suma el log-odds en N filas (tolerancia 1e-06); la primera en la posición …» o «M06: SHAP devolvió una matriz de … y se esperaba …». El mensaje nombra una posición, nunca un cliente.

**Qué significa.** Los motivos de cada cliente son SHAP sobre el log-odds del clasificador sin calibrar, y cada fila explicada debe sumar su log-odds con un error de a lo sumo `shap_additivity_tol` (10⁻⁶); en la construcción el error máximo fue 1,07·10⁻¹⁴ (D60). Una falla quiere decir que cambió la versión de `shap` (fijada en 0.51.0) o de scikit-learn, o que el modelo tiene divisiones categóricas nativas, que SHAP no explica de forma aditiva y que el flujo rechaza antes de explicar (D15). No se provocó al escribir este documento.

**Qué hacer.** Comprobar los pines (`.venv\Scripts\python -m pytest tests/unit/test_dependencies.py`) y correr `tests/unit/test_explain.py`. Una versión nueva de `shap` es un cambio de dependencia con su decisión, su prueba de aditividad y una revisión de riesgo (ítem 5); nunca se sube la tolerancia para que pase.
