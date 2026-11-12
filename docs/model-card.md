# Ficha del modelo

Qué hace el modelo, con qué datos, sobre qué definición de baja, cómo se validó, qué resultados dio y hasta dónde se puede confiar en él. Las cifras de resultados salen de `reports/evaluation_summary.json` y del sello `reports/model_seal.json`, que escribió la corrida real del 2026-11-12 (D85), la misma fuente del README; las de la partición, la etiqueta, la calibración y la curva de costo, de los archivos del sitio (`outputs/site/*.json`) y de los Parquet de `outputs/powerbi/` de esa corrida. Los criterios y sus umbrales se fijaron antes de escribir el código (`docs/requirements.md`, sección 8.1; D18) y ninguno se movió después de ver un resultado.

## Uso previsto y no previsto

**Para qué sirve.** Estimar, en cada fecha de corte (el día 1 de un mes) y con lo que se sabe antes de ella, la probabilidad calibrada de que un cliente activo no vuelva a comprar en los 90 días siguientes; dar sus tres motivos principales; marcar a los que conviene contactar con un umbral elegido por beneficio neto con costos supuestos; y seguir cada mes quién volvió y quién no. Sirve para ordenar a quién mirar primero, para comparar el modelo con las reglas que usaría un gerente y para alimentar un tablero de seguimiento.

**Para qué no sirve.**

- No dice quién se dio de baja: la baja es un silencio de 90 días definido por el proyecto, no un dato del archivo, y parte de esos silencios vuelve (ver «La definición de baja y su ruido»).
- No ordena mejor que una regla simple: en la prueba, la frecuencia de 365 días, RFM y BG/NBD ordenan a los clientes igual o mejor que el modelo (ver «Criterios y resultados»).
- No mide el efecto de una oferta: no hay un experimento de retención, y la tasa de rescate es un supuesto (D22).
- No pone un costo real a una oferta ni a un cliente: los costos son supuestos y declarados; otros costos dan otro umbral.
- No cubre a los clientes sin número (22,5 % de las líneas) ni a los que llevan más de 90 días sin comprar: no están en la población (D05, D07).
- No se reentrena cada mes: se entrena una vez, en el lanzamiento, y queda congelado (D19).
- No es un servicio: la función de puntuación queda lista para envolverla, pero no hay una API (D43; una con FastAPI queda a decisión del dueño).
- No cubre otra tienda ni otros años que los de este archivo.

## Datos

«Online Retail II», UCI Machine Learning Repository (Chen, 2012; https://doi.org/10.24432/C5CG6D; CC BY 4.0): un zip de 45.622.418 bytes con SHA-256 `572e3627…7bfb` y, adentro, un libro de Excel con dos hojas (`Year 2009-2010` y `Year 2010-2011`) y 8 columnas, 1.067.371 filas del 2009-12-01 al 2011-12-09. Las huellas del zip y del libro son las que fijó el proyecto 02 (D02). Las reglas de validación y sus recuentos reales están en `reports/validation/latest.md` y en `outputs/site/validation_rules.json`: 39 reglas, de las que 18 bloquean, 13 advierten y 8 informan.

- **Base canónica** (D03). Las dos hojas se solapan del 2010-12-01 al 2010-12-09: se quitan las 22.523 copias exactas del solapamiento y quedan 1.044.848 líneas; las 11.812 repeticiones internas de una hoja se conservan y se marcan (V28), como en el proyecto 02.
- **Roles de las líneas.** 788.187 compras, 17.641 anulaciones y 239.020 líneas apartadas por la primera regla que las aparta, en el orden de D03 (sin número de cliente, cantidad con el signo equivocado, precio cero o negativo, código de servicio con `PADS`, vale de regalo, factura «A»): 235.287 sin número de cliente, 70 con precio cero o negativo y 3.663 con un código de servicio (envíos, comisiones, ajustes, muestras); las 6 líneas de facturas «A» no tienen cliente y las toma la primera regla (D51).
- **Neteo conocido en una fecha** (RF06; D04 del proyecto 02). Cada anulación se descuenta de la compra que anula, la última primero por cliente y producto, usando solo las anulaciones con fecha anterior o igual a la fecha pedida: un cliente que compra y anula en el mismo período no cuenta como comprador. En el archivo completo hay 16.427 emparejamientos, y 1.706 anulaciones, o restos de una, quedan sin compra que anular (V22). Un día de compra es un día con al menos una compra neta del cliente.
- **Entregas** (D11). El archivo no cambia, así que el flujo lo reparte en un lanzamiento con las facturas hasta el 2011-07-31, cuatro entregas mensuales (2011-08 a 2011-11) y un cierre con los 9 días de 2011-12. Cada línea está exactamente en una entrega, la de la fecha de su factura.
- **Clientes.** 5.942 con al menos una compra, de 41 países; el 91 % es del Reino Unido.

## La definición de baja y su ruido

El archivo no dice quién se fue: la baja se define (D06). Un cliente de la población de un corte `c` se fue (`churned = 1`) si no tiene **ningún día de compra neta en los 90 días que empiezan en el corte**, `[c, c + 89]`, con el neteo conocido al final de esa ventana. La etiqueta de un corte entra al almacén recién cuando la fecha de cálculo alcanza `c + 89`: antes, no existe.

La definición es ruidosa, y el proyecto lo mide. En los siete cortes de entrenamiento hay 6.611 silencios de 90 días, y el 31,7 % de ellos vuelve a comprar en los 90 días siguientes, `[c + 90, c + 179]` (`outputs/site/label.json`, `silence_return`). La investigación, sobre el archivo completo y con otra forma de contar los silencios, midió 39 % (`research.md`). Con 60 días, el 29,5 % de 8.002 silencios vuelve; con 120, el 29,3 % de 5.644. Es decir: casi un tercio de lo que el modelo aprende a llamar «baja» es una pausa larga. Un modelo que acierta estas etiquetas predice silencios, no bajas comprobadas.

La tasa de bajas del entrenamiento según N y M (`fact_label_definition`):

| N (días) | M = 90 | M = 180 |
| ---: | ---: | ---: |
| 60 | 52,3 % | 57,1 % |
| 90 | 43,2 % | 48,3 % |
| 120 | 36,9 % | 42,1 % |

## La población y los invitados

La población de un corte son los clientes con al menos un día de compra neta en los 90 días anteriores, `[c − 90, c − 1]` (M = 90, D07), con el neteo conocido en `c − 1`: unos 2.000 clientes por corte, entre 1.677 (2011-03-01) y 2.859 (2010-12-01). Un cliente que lleva más de 90 días sin comprar no está en la población: ya está en silencio, y predecir si vuelve es otro problema (un modelo de reactivación, fuera de este alcance).

Los invitados quedan fuera (D05): las 235.287 líneas sin número de cliente, el 22,5 % de las líneas y el 15,1 % del importe bruto positivo, no se pueden seguir en el tiempo. Se cuentan en la validación (V20, I02) y en el sitio, y no entran en ningún corte.

## Cortes y estacionalidad

Un corte es el día 1 de un mes, del 2010-06-01 al 2011-12-01 (D08). Las tasas de bajas de los cortes de entrenamiento cambian con el mes: 44,3 %, 42,9 %, 35,9 %, 31,2 %, 36,5 %, 46,3 % y 57,9 % de junio a diciembre de 2010. Diciembre es el más alto: el silencio de enero a febrero que sigue a las compras de fin de año.

No hay una variable de calendario (D09): el modelo no sabe en qué mes está, y la estacionalidad llega por las variables de cada cliente. El corte de diciembre se queda en el entrenamiento, y una sensibilidad lo saca para ver qué cambia (ver «Sensibilidades»). La prueba, de agosto y septiembre, tiene menos bajas (36,6 % y 32,1 %) que la validación (42,6 % en V1 y 40,6 % en V2): es la razón de que la calibración falle (C07).

Los cortes de 2011-10-01, 2011-11-01 y 2011-12-01 se puntúan y se siguen, pero su ventana de 90 días termina después del fin de los datos: quedan **censurados** y nunca se evalúan (D44).

## Variables

Dieciséis, calculadas solo con líneas y anulaciones con fecha anterior al corte (RF13, D12):

- **Recencia y antigüedad**: días desde el último y desde el primer día de compra neta.
- **Frecuencia**: días de compra neta, todos, en los 90 y en los 365 días anteriores.
- **Gasto**: importe neto, total, en 90 y en 365 días, y el gasto por día de compra.
- **Volumen**: unidades netas en 90 días; productos distintos y unidades medianas por línea en 365 días.
- **Ritmo**: tiempo medio y máximo entre días de compra consecutivos (0 con un solo día).
- **Anulaciones**: líneas de anulación y su importe en 365 días.

Además, el país de la última línea anterior al corte, con los países de menos de 10 clientes en el entrenamiento en «Otros» (13 grupos). Tres conjuntos: **F0** (recencia y frecuencia de 365 días, la variante de dos columnas de la investigación), **F1** (las dieciséis) y **F2** (F1 y el país como indicadores). **El modelo elegido usa F1: el país no entra.**

Nunca llegan a la matriz el número de cliente, la etiqueta, una variable de calendario ni una salida de BG/NBD. Cuatro guardas lo impiden: `build_matrix` lanza `LeakageError` si recibe o produce una columna fuera de la lista; una prueba estática comprueba que el código de las variables no lee las tablas de etiquetas; una prueba de truncamiento comprueba que las variables calculadas con todo cargado son idénticas a las calculadas con los datos cortados el día anterior; y la trampa M01 detiene el lanzamiento si el AUC del modelo elegido en V1 llega a 0,95. La demostración de fuga (`outputs/site/label.json`, `leakage`): F1 con los días hasta la próxima compra, que mira la ventana de la etiqueta, da un AUC de 1,000 en V2, frente a 0,762 de F1 solo.

## Partición

Por fecha de corte, con purgas que no entran en ningún bloque (D08): cada borde cumple `c_anterior + N ≤ c_siguiente`, así que ninguna ventana de etiqueta de un bloque se cruza con el siguiente (RF14).

| Bloque | Cortes | Filas | Tasa de bajas | Uso |
| --- | --- | ---: | ---: | --- |
| Entrenamiento | 2010-06-01 a 2010-12-01 (7) | 15.297 | 43,2 % | Ajustar los 24 candidatos, las reglas y BG/NBD |
| Purga 1 | 2011-01-01 y 2011-02-01 | | | Ninguno |
| V1 | 2011-03-01 y 2011-04-01 | 3.449 | 42,6 % | Elegir el candidato, calibrar el modelo y las reglas, elegir B* |
| V2 | 2011-05-01 | 1.886 | 40,6 % | Elegir el umbral por costo |
| Purga 2 | 2011-06-01 y 2011-07-01 | | | Ninguno |
| Prueba | 2011-08-01 y 2011-09-01 | 3.935 | 34,4 % | Evaluar una sola vez, bajo el sello |
| Censurados | 2011-10-01 a 2011-12-01 (3) | | | Se puntúan y se siguen, nunca se evalúan |

Las filas del entrenamiento son 15.297 de 3.942 clientes: un cliente aparece en varios cortes, y por eso los intervalos remuestrean clientes enteros.

## Métodos

**Clasificador** (D12, D13). `HistGradientBoostingClassifier` de scikit-learn 1.9.1 con una grilla fija: tasa de aprendizaje 0,05 o 0,1, 15 o 31 hojas, 50 o 200 filas por hoja, regularización L2 1,0, 300 iteraciones sin parada temprana y semilla 0. Ocho configuraciones por conjunto de variables, 24 ajustes, todos en el entrenamiento. Gana el de menor pérdida logarítmica en V1: **F1, tasa 0,05, 15 hojas y 200 filas por hoja**, con una pérdida de 0,5705 (`fact_selection`). En F2 el país entra como indicadores one-hot, para que SHAP sea aditivo (D15); las divisiones categóricas nativas de scikit-learn se rechazan antes de explicar.

**Líneas base** (D16, D17), todas con la historia anterior a su corte: B0 contactar a todos; B1 la recencia; B2 RFM, la suma de los quintiles en el corte de recencia, frecuencia y gasto de 365 días (de 3 a 15); B3 las compras esperadas en los próximos 90 días según BG/NBD, con los parámetros ajustados con la historia anterior al último corte de entrenamiento (r 0,9091, α 75,83, a 0,1717, b 105,91, log-verosimilitud −59.505,3611; la implementación con SciPy del proyecto 02, comparada con `lifetimes` en las pruebas); B4 los días de compra en 365 días; y B5 1 − P(vivo), informativa (satura cerca de 1 entre los clientes activos). Para decidir por costo, cada puntaje se convierte en probabilidad con regresión isotónica en V1, como el modelo.

**Base más fuerte** (D14). B* es la de mayor AUC en la validación (V1 y V2) entre B2, B3 y B4, elegida en el lanzamiento y sellada: **B3, BG/NBD**, con 0,766 en la validación.

**Intervalos** (D21). Remuestreo pareado de los clientes de la prueba con reposición, por cliente entero (un cliente con dos filas, una por corte, entra o sale con las dos), 1.000 remuestras, semilla 0; percentiles 2,5 y 97,5 de la diferencia. Ninguna remuestra se descartó.

**Lanzamiento congelado y sello** (D19, D20). El lanzamiento entrena, elige, calibra, elige B* y el umbral, guarda el artefacto con su SHA-256 y escribe la parte del lanzamiento del sello, con una huella de cada clave de la configuración que cambia un valor sellado (`config_sha256` `beac418e…bc6d`) y la de los puntajes de V2. Las corridas siguientes cargan el artefacto solo si su huella coincide, antes de deserializarlo (D40), y puntúan a cada cliente activo de su corte una sola vez: los puntajes y sus motivos son de solo inserción. La corrida de M2011-11, la primera cuya fecha de cálculo cierra la ventana del último corte de prueba, evaluó la prueba y escribió la parte de la prueba del sello. Una configuración distinta de la sellada se informa como posterior al sello y no reemplaza el resultado sellado (M05).

## Calibración

Regresión isotónica ajustada solo con V1 sobre el clasificador ya entrenado y congelado (D13). El error de calibración esperado, con 10 intervalos de igual ancho, es 0,048 en V2 y **0,089 en la prueba, con un sesgo de 0,088: C07 no se cumple** (límites 0,03 y 0,02). El modelo sobreestima las bajas en la prueba, porque V1 tenía 42,6 % de bajas y la prueba 34,4 %. La calibración en la prueba, por intervalo de riesgo (`outputs/site/algorithms.json`; dos intervalos ocultos por la regla de las celdas chicas, D86):

| Intervalo | Riesgo medio | Tasa observada | Filas |
| ---: | ---: | ---: | ---: |
| 1 | 0,050 | 0,031 | 350 |
| 2 | 0,158 | 0,080 | 275 |
| 3 | 0,256 | 0,156 | 391 |
| 4 | 0,345 | 0,273 | 932 |
| 5 | oculto | oculto | oculto |
| 6 | 0,516 | 0,425 | 948 |
| 7 | 0,656 | 0,525 | 541 |
| 8 | 0,744 | 0,621 | 456 |
| 9 | 0,805 | 0,854 | 41 |
| 10 | oculto | oculto | oculto |

El seguimiento lo confirma en uso: en los dos cortes de prueba el modelo esperaba 875,0 y 825,2 bajas (la suma de los riesgos) y hubo 739 y 615 (`outputs/site/retention.json`).

## SHAP y qué explica

Los motivos de cada cliente salen de SHAP (`TreeExplainer`, shap 0.51.0) sobre el **log-odds del clasificador sin calibrar**, no sobre la probabilidad calibrada (D15). La suma de las contribuciones más el valor base reproduce el log-odds de cada fila explicada con un error de a lo sumo 10⁻⁶, o la tarea falla (M06); en la construcción, el mayor error medido fue 1,07 × 10⁻¹⁴ (D60). La calibración isotónica es monótona: no cambia el orden de los clientes, pero una contribución de SHAP no se traduce en puntos de probabilidad. Se guardan los tres motivos de mayor contribución hacia el riesgo, con su dirección.

La importancia media en la prueba (media de |SHAP|, en log-odds; `outputs/site/algorithms.json`): días de compra 0,723; mayor tiempo entre compras 0,226; antigüedad 0,224; tiempo medio entre compras 0,172; gasto total 0,151; compras en 90 días 0,138; gasto en 90 días 0,106; productos distintos en 365 días 0,091; anulaciones en 365 días 0,073; unidades en 90 días 0,067. La recencia, que el sitio nombraba como la variable principal, no está entre las diez primeras: la señal está en cuánto y con qué ritmo compra el cliente. Entre los contactados, el tiempo medio entre compras está entre los tres motivos del 77,9 % y los días de compra del 77,7 % (`outputs/site/retention.json`).

## Umbral y costos supuestos

**Beneficio neto** (D22). Contactar a un cliente cuesta `c_oferta`; si el cliente se iba, la oferta lo retiene con probabilidad `r`, y retenerlo vale `V`. El beneficio neto de contactar es `churned × r × V − c_oferta`, y no contactar vale 0. Con los costos supuestos, `c_oferta = 5`, `r = 0,2` y `V = 50`, en unidades genéricas («u.»): el punto de equilibrio es `c_oferta / (r × V) = 0,5`. Lo que decide el umbral es ese cociente. Ninguna fuente pública da un costo defendible de una oferta de retención ni del valor de un cliente para este caso (`research.md`; Verbeke y otros, 2012, https://doi.org/10.1016/j.ejor.2011.09.031, como referencia del método); el dueño no eligió otros costos antes de la corrida real (plan, sección 29), y después del sello un cambio es un análisis nuevo.

**Umbral.** El valor de la grilla de 0,01 a 0,99 que maximiza el beneficio neto en V2, nunca F1. El del modelo es **0,55**: en V2 contacta al 32,9 % y deja 564,7 u. por cada 1.000 clientes; en la prueba contacta al 26,5 % y deja 209,7. B* elige 0,60 con el mismo procedimiento.

**Curva de ganancia y sensibilidad.** La curva de ganancia dice qué parte de las bajas capta una lista de cada tamaño (`fact_gain_curve`): en la prueba, el 10 % de mayor riesgo del modelo capta el 18,7 % de las bajas (lift 1,87) y el de B* el 19,8 % (lift 1,98). Para cada punto de equilibrio de 0,10 a 0,90, de a 0,05, se repite la elección del umbral en V2 para el modelo y B* y se mide en la prueba (`fact_cost_sensitivity`, C09): el modelo deja al menos lo de B* en 9 de los 17 puntos.

## Criterios y resultados

Prueba: 3.935 filas de los cortes del 2011-08-01 y del 2011-09-01, con las etiquetas conocidas al 2011-11-30 y una tasa de bajas de 0,344. «Visto» dice si la investigación (en el primer corte de validación) o el agente de planificación (solo en el entrenamiento) habían mirado ese número antes de fijar el criterio.

| ID | Umbral | Visto por la investigación | Visto por el planificador | Veredicto |
| --- | --- | --- | --- | --- |
| C01 | AUC(modelo) > AUC(B2) | sí | en parte | El modelo no supera a RFM en AUC: 0,745 frente a 0,746. |
| C02 | límite inferior del intervalo del 95 % de AUC(modelo) − AUC(B2) > 0 | sí | no | El modelo no supera a RFM fuera del ruido: la diferencia de AUC es −0,00, con un intervalo del 95 % de −0,01 a 0,01. |
| C03 | límite inferior del intervalo del 95 % de AUC(modelo) − AUC(B*) > 0 | en parte | en parte | El modelo no supera a la base más fuerte fuera del ruido: la diferencia de AUC es −0,00, con un intervalo del 95 % de −0,02 a 0,01. |
| C04 | bajas en el 10 % de mayor riesgo del modelo > las del 10 % de B* | en parte | no | En el 10 % de mayor riesgo, el modelo no capta más bajas que la base más fuerte: 253 frente a 268. |
| C05 | BN(modelo, t*) > BN(B*, t*_B*) | no | no | Con los costos supuestos, el modelo no deja más beneficio neto que la base más fuerte con su propio umbral: 209,7 u. frente a 238,9 u. por cada 1.000 clientes. |
| C06 | BN(modelo, t*) > máx(BN(contactar a todos), 0) | no | no | El modelo supera a contactar a todos y a no contactar a nadie: 209,7 u. por cada 1.000 clientes frente a 0,0. |
| C07 | ECE ≤ 0,03 y \|sesgo\| ≤ 0,02 | no | no | La calibración en la prueba no cumple: ECE 0,089 y sesgo 0,088. |
| C08 | Brier(modelo) < Brier(B*) | no | no | El Brier del modelo es menor que el de la base más fuerte: 0,1976 frente a 0,2030. |
| C09 | BN(modelo) ≥ BN(B*) en cada punto de equilibrio de 0,10 a 0,90 | no | no | El modelo no deja al menos el beneficio de la base más fuerte en cada punto de equilibrio: en 9 de los 17 de 0,10 a 0,90. |
| C10 | sin umbral: que esté escrito y sea consistente | no | solo las tasas de entrenamiento | Por corte de prueba: 2011-08-01: AUC 0,744, tasa de bajas 0,366, diferencia con B2 −0,00 y con B* −0,00; 2011-09-01: AUC 0,746, tasa de bajas 0,321, diferencia con B2 −0,00 y con B* −0,01. Sensibilidades: N = 60 días (2011-08-01, 2011-09-01): AUC del modelo 0,737, de RFM 0,729 y de B* 0,744, intervalo de la diferencia con B* de −0,02 a 0,00; N = 120 días (2011-08-01): AUC del modelo 0,756, de RFM 0,766 y de B* 0,754, intervalo de la diferencia con B* de −0,02 a 0,02; M = 180 días (2011-08-01, 2011-09-01): AUC del modelo 0,750, de RFM 0,766 y de B* 0,760, intervalo de la diferencia con B* de −0,02 a −0,00; sin el corte de diciembre en el entrenamiento (2011-08-01, 2011-09-01): AUC del modelo 0,744, de RFM 0,746 y de B* 0,749, intervalo de la diferencia con B* de −0,02 a 0,01. |

**Veredicto: el modelo no cumple C01, C02, C03, C04, C05, C07 ni C09, y cumple C06 y C08.** No supera a RFM ni a la base más fuerte en ningún criterio de orden ni de beneficio.

Todos los métodos en la prueba (cada umbral, el elegido en V2; contactar a todos no tiene Brier):

| Método | AUC | PR-AUC | Brier | ECE | Umbral | Contactados | Captura en el 10 % | BN por 1.000 (u.) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Modelo | 0,7447 | 0,5607 | 0,1976 | 0,0890 | 0,55 | 26,5 % | 253 | 209,7 |
| B0 contactar a todos | 0,5000 | 0,3441 | — | — | — | 100,0 % | 120 | −1.559,1 |
| B1 recencia | 0,6004 | 0,4248 | 0,2270 | 0,0871 | 0,55 | 11,4 % | 181 | −47,0 |
| B2 RFM | 0,7464 | 0,5569 | 0,1956 | 0,0756 | 0,61 | 36,1 % | 259 | 209,7 |
| B3 BG/NBD (B*) | 0,7489 | 0,5838 | 0,2030 | 0,1104 | 0,60 | 35,1 % | 268 | 238,9 |
| B4 frecuencia | 0,7522 | 0,5465 | 0,1982 | 0,0967 | 0,59 | 46,6 % | 234 | 106,7 |
| B5 1 − P(vivo) | 0,4163 | 0,3002 | 0,2323 | 0,0816 | 0,99 | 0,0 % | 101 | 0,0 |

**Lo que dicen los números, incluido lo que no favorece al modelo.**

- **El modelo no ordena mejor que las reglas.** Su AUC (0,7447) queda por debajo de RFM (0,7464), de BG/NBD (0,7489) y de la frecuencia de 365 días (0,7522), la regla más simple de las tres y la que mejor ordena. Las diferencias con RFM (−0,0017, intervalo de −0,0145 a 0,0110) y con B* (−0,0043, de −0,0166 a 0,0078) no salen del ruido. Es lo que el plan escribió antes de medir (requerimientos, sección 8.1; D01): en el entrenamiento, la frecuencia sola ya ordenaba mejor que RFM y que BG/NBD.
- **Tampoco deja más beneficio.** B* deja 238,9 u. por cada 1.000 clientes con su umbral y el modelo 209,7, lo mismo que RFM. La frecuencia ordena mejor pero deja menos (106,7): con su umbral contacta al 46,6 %, demasiados para este punto de equilibrio. El AUC y el beneficio no siempre eligen la misma regla.
- **Lo que el modelo agrega es una probabilidad y los motivos, no un mejor orden.** Su Brier (0,1976) es menor que el de B* (0,2030, C08) y mayor que el de RFM (0,1956). Actuar con él conviene más que no hacer nada o contactar a todos (C06), como con cualquiera de las reglas fuertes.
- **La calibración no viaja de un período a otro.** Calibrado en V1 (42,6 % de bajas), sobreestima en la prueba (34,4 %): C07 no se cumple. La regla de la calibración funciona en el período en que se ajusta: en V2, el ECE del modelo es 0,048.

## Sensibilidades

Se informan dentro del sello y nunca se usaron para elegir nada (D10, RNF06 e). Cada variante vuelve a construir sus cortes, entrena el modelo con la misma elección del lanzamiento y mide la prueba que le cabe (C10):

| Variante | Cortes de prueba | AUC del modelo | AUC de RFM | AUC de B* | Diferencia con B*, intervalo del 95 % |
| --- | ---: | ---: | ---: | ---: | --- |
| N = 60 días | 2 | 0,737 | 0,729 | 0,744 | de −0,018 a 0,003 |
| N = 120 días | 1 (solo 2011-08-01) | 0,756 | 0,766 | 0,754 | de −0,017 a 0,020 |
| M = 180 días | 2 | 0,750 | 0,766 | 0,760 | de −0,021 a −0,0003 |
| Sin el corte de diciembre en el entrenamiento | 2 | 0,744 | 0,746 | 0,749 | de −0,019 a 0,009 |

Ninguna variante cambia la conclusión: en ninguna el modelo supera a B* fuera del ruido, y con M = 180 queda por debajo. Con N = 60 el modelo supera a RFM en AUC (0,737 frente a 0,729), y con N = 120 a B* (0,756 frente a 0,754), sin salir del ruido. Por corte de prueba, el AUC del modelo es 0,744 (2011-08-01, 36,6 % de bajas) y 0,746 (2011-09-01, 32,1 %).

## Limitaciones

- **Un archivo de 2009 a 2011, de una sola tienda.** Dos años de facturas de un minorista en línea, sobre todo del Reino Unido; el resultado dice lo que pasa en este archivo, no en otra tienda ni en otra época.
- **Sin bajas comprobadas ni experimento de retención.** La etiqueta es un silencio de 90 días, y casi un tercio de esos silencios vuelve a comprar después. No hay un registro de bajas ni una prueba con grupo de control de una oferta: el modelo predice silencios, y lo que una oferta lograría no se midió.
- **Costos supuestos.** Oferta 5, tasa de rescate 0,2 y cliente retenido 50 son supuestos declarados, no medidos; el umbral y el beneficio neto dependen de ellos. La sensibilidad muestra el efecto de otros puntos de equilibrio, pero no reemplaza un costo real. Elegir otros es una decisión del dueño, y después del sello es un análisis nuevo que se informa aparte.
- **Cortes censurados.** Los cortes de octubre a diciembre de 2011 se puntúan y se siguen, pero su ventana pasa el fin de los datos: no se evalúan, y su lista de contactos no tiene un resultado con qué compararse.
- **Evaluación única.** La prueba se evaluó una sola vez, con un lanzamiento, una partición, dos cortes y unos 2.000 clientes por corte; no separa diferencias de AUC de menos de unas 0,01, y no hay otra ventana con que comparar.
- **La calibración depende del período.** Calibrado en primavera, el modelo sobreestima las bajas de fin de verano (C07); en uso, la probabilidad habría que recalibrarla con un período reciente.
- **Sin API.** La función de puntuación no está publicada como servicio; una API con FastAPI queda a decisión del dueño (D43).
- **Las medidas DAX no se ejecutaron.** El diseño del tablero y sus 29 medidas se verificaron con pruebas estáticas contra el modelo semántico, pero nunca corrieron en Power BI Desktop, y el `.pbix` no está hecho.
- **Cuentas chicas de calidad de datos.** `validation_rules.json` y `fact_validation` publican cuántos clientes afecta cada regla de calidad, también cuando son menos de 10, sin ningún número de cliente; D85 las registra como una excepción conocida, y la evaluación independiente las vuelve a revisar.
- **Sin evaluación independiente todavía.** Ninguna cifra de esta ficha la recalculó alguien que no construyó el proyecto (plan, sección 28).

## Tiempos y memoria

Medido en esta máquina (AMD Ryzen 9 5950X de 16 núcleos, 64 GB, Windows 10, Python 3.11, un solo proceso) en la corrida real, con el archivo ya descargado: `python -m churnrisk replay` y a continuación `python -m churnrisk run`, que terminó sin entrega (D85). Los tiempos por tarea son los que registra el propio flujo en el archivo de estado de cada corrida de la primera corrida, la que escribió el sello.

| Tarea | Lanzamiento (s) | Mensuales M2011-08 a M2011-11 (s) | Cierre C2011-12 (s) |
| --- | ---: | ---: | ---: |
| `fetch_source` | 36,47 | 0,04 a 0,05 | 0,04 |
| `deliver` | 0,98 | 0,36 a 0,44 | 0,36 |
| `validate` | 2,51 | 4,59 a 5,87 | 6,14 |
| `load` | 9,40 | 4,65 a 6,09 | 5,70 |
| `build_cuts` | 20,89 | 6,03 a 7,38 | 5,60 |
| `fit_model` | 15,28 | 0,07 a 0,07 | 0,12 |
| `score` | 1,06 | 0,98 a 1,38 | 0,00 |
| `track` | 4,12 | 4,51 a 5,60 | 5,73 |
| `evaluate` | 26,46 | 0,06 a 30,33 | 0,06 |
| `export` | 5,25 | 5,43 a 6,93 | 7,17 |
| `render_dashboard` | 0,08 | 0,08 a 0,09 | 0,08 |
| `report` | 0,62 | 0,64 a 0,76 | 0,78 |
| **Corrida, sumando las tareas** | **123,12** | de 27,45 a 64,98 | **31,78** |

La evaluación de la prueba y de las sensibilidades corre en M2011-11 (los 30,33 s de `evaluate`); la del lanzamiento, 26,46 s, es la de V2, con SHAP y la demostración de fuga. La corrida sin entrega solo corre `fetch_source` (0,04 s) y `deliver` (0,45 s).

- **RNF02.** Repetición completa (las seis entregas y la corrida sin entrega): `replay` en 312,2 s de reloj y la corrida sin entrega en 3,6 s, contra el tope de 15 minutos; el lanzamiento, 123 s contra 5 minutos; cada corrida mensual, de 27 a 65 s contra 2 minutos. **Se cumplen.** La repetición en una copia nueva después de la corrección de D86 tardó 306,6 s en `replay` y 297 s sumando las corridas. La repetición completa en modo rápido (`make-fixture` y `replay --config config/pipeline.quick.toml` en una copia limpia del proyecto, al terminar U30) tardó 26,6 s de reloj, seis corridas, contra 2 minutos. La prueba de Docker todavía no se corrió.
- **RNF03.** El contador con tope es el pico del conjunto de trabajo del proceso, `PeakWorkingSetSize` de `GetProcessMemoryInfo` (en Linux sería `ru_maxrss` de `resource.getrusage`): el pico del conjunto de trabajo (`PeakWorkingSetSize`) fue de 1.448,6 MB al cerrar el lanzamiento y de 1.868,5 MB al cerrar `C2011-12`, contra el tope de 2,5 GB (2.560 MB); en la repetición, 1.877,8 MB (`PeakWorkingSetSize`). **Se cumple.** El pico de memoria comprometida del mismo proceso (`PeakPagefileUsage`), que se guarda como cifra informativa y sin tope, llegó a 3.709,2 MB (`PeakPagefileUsage`), y a 3.708,5 MB (`PeakPagefileUsage`) en la repetición. La corrida sin entrega, en su propio proceso, llegó a 592,6 MB de conjunto de trabajo (`PeakWorkingSetSize`). Cada tarea de cada corrida registró su pico y el nombre del contador.
- **Tamaños.** Los 26 Parquet de `outputs/powerbi/` suman 158.405 bytes; el mayor, `fact_roc.parquet`, 28.083 bytes, contra el tope de 25 MB por archivo. Los cinco archivos del sitio suman 71.424 bytes sin el manifiesto, contra 204.800. El HTML del diseño, 107.214 bytes; el sello, 17.435.

## La suite rápida

- **AC41, la suite rápida** (sin `real_data` ni `docker`): **108,19 s** y 107,05 s, medida dos veces al terminar U31, para 869 pruebas (una se salta en Windows: la que lee el id de arranque de Linux), contra el límite de 120 s. **Se cumple.** No había otro trabajo del proyecto corriendo; en la máquina seguían abiertos Visual Studio Code, Docker Desktop, NVIDIA Broadcast y Claude Code. Queda sobre el presupuesto de trabajo de 100 s, como desde U16: 574 pruebas en 108,6 s tras U20 (L50), 726 en 108,64 s tras U25 (L51), 845 y una omitida en 105,60 s tras G1 (L52), 849 y una omitida en 112,83 s tras U29 (L53) y 855 y una omitida en 109,14 s y 106,60 s tras U30. Se aceptó así: la suite no se acorta quitando casos, y `pytest-xdist` no está fijado (D35).
- **El límite se controla solo.** Una sesión completa de la suite por defecto que pasa los 120 s termina con falla y dice por cuánto (`tests/fixtures/suite_budget.py`, D34); una selección parcial nunca falla por su tiempo.
- **Las pruebas con el archivo real** (`-m real_data`): 9 de 9 en 51,65 s tras U29 (L53) y 9 de 9 en 52,38 s al terminar U31.
