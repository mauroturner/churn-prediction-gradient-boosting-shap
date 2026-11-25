# Investigación previa: clientes que están por irse, antes de que se vayan

Fecha de la investigación: 2026-11-11.

**Leyenda de etiquetas**

- **[Verificado]**: medido directamente sobre el archivo real descargado, o comprobado en la página de la fuente. Se indica el script o la URL.
- **[Documentación]**: tomado de una página oficial o de un registro bibliográfico que se abrió o que aparece en una búsqueda. Se indica la URL.
- **[Fuente secundaria]**: tomado de un fragmento de búsqueda o de un texto que no se abrió completo. Conviene confirmarlo antes de citarlo.
- **[Inferido]**: deducción propia a partir de datos observados. No está confirmada por una fuente.

Esta investigación es una primera mirada: no es el resultado del proyecto. Las cifras de la sección "Primera mirada del modelo" salen de una sola configuración, sin búsqueda de hiperparámetros, evaluada en un único corte de validación. **Ningún cálculo se hizo sobre los cortes propuestos para prueba** (2011-08-01 y 2011-09-01): ni tasas, ni modelos, ni líneas base. Los tiempos entre compras se midieron solo con compras anteriores al primer corte de prueba.

---

## Objetivo

Verificar la fuente, la licencia, el esquema, la definición de "se fue" sin contrato, la fuga de información, los cortes y la partición en el tiempo, las líneas base, la primera mirada del modelo, SHAP, el criterio de valor y de costo, los datos personales y los trabajos previos del proyecto "Clientes que están por irse, antes de que se vayan" (proyecto 04 del catálogo, tarea T5 en `odd/tasks/portfolio-projects.md`): un modelo de gradient boosting que, con las compras anteriores a una fecha de corte, estima el riesgo de que un cliente no compre en los N días siguientes; con SHAP por cliente y una curva de ganancia.

**Hallazgos principales**

1. La fuente es el conjunto "Online Retail II" de UCI, de Daqing Chen, con licencia CC BY 4.0 y DOI 10.24432/C5CG6D. El archivo `online_retail_II.xlsx` tiene 1.067.371 filas en dos hojas y su SHA-256 es el mismo que fijó el proyecto 02. [Verificado]
2. El archivo no dice quién se fue. Con la regla propuesta (sin compra neta en los N = 90 días que siguen a la fecha de corte), la tasa de bajas en los cortes de entrenamiento va de 31 % a 58 % según el mes del corte. La regla es ruidosa: el 39 % de los silencios de 90 días o más vuelve a comprar en los 90 días siguientes. [Verificado]
3. Propuesta: N = 90 días y M = 90 días (un cliente entra en un corte si compró en los 90 días anteriores). Cortes mensuales del 1 de cada mes, con purgas de 90 días entre bloques. Entrenamiento: 7 cortes de 2010-06-01 a 2010-12-01. Validación: 2011-03-01 a 2011-05-01. Prueba: 2011-08-01 y 2011-09-01 (la última ventana de etiqueta termina el 2011-11-29, dentro de los datos). [Verificado en el cálculo de los cortes; Inferido en la elección]
4. Calidad para churn: 22,5 % de las líneas no tienen identificador de cliente y aportan 15,1 % del importe bruto positivo; las anulaciones (factura con "C") son 1,8 % de las líneas y 7,1 % del importe; hay 63 códigos de producto no estándar, de los que casi todos son servicios (envío, comisiones, ajustes); el precio máximo de 38.970 es una línea de ajuste manual anulada. [Verificado]
5. Líneas base en el primer corte de validación (2011-03-01, 1.677 clientes, tasa de baja 43,4 %): RFM AUC 0,784; recencia AUC 0,625; BG/NBD P(vivo) AUC 0,433 (no sirve: casi todos los clientes activos tienen P(vivo) cercana a 1); BG/NBD compras esperadas en 90 días AUC 0,776. La línea base más difícil de superar es **RFM**. [Verificado]
6. Primera mirada: `HistGradientBoostingClassifier` con 25 columnas, entrenado solo en los cortes de entrenamiento, da AUC 0,769, PR-AUC 0,691 y lift de 1,80 en el 10 % superior. **No supera a RFM**: la diferencia es -0,014 con intervalo al 95 % de -0,033 a 0,005 (bootstrap pareado). Las columnas con señal son la frecuencia, el tiempo entre compras y el gasto; el país aporta poco. [Verificado]
7. SHAP corre: `shap` 0,51.0 con `TreeExplainer` sobre el modelo de la primera mirada, con aditividad exacta (error máximo 8·10⁻¹⁵ en log-odds). Con divisiones categóricas nativas de scikit-learn, `TreeExplainer` corre pero **no es aditivo** (error 3,6 en log-odds): el país debe ir como indicadores one-hot. Tiempo: 1,0 s para 1.677 filas; 9,0 s para 15.297 filas. [Verificado]
8. El sitio tiene cinco puntos que cambiar: LightGBM (no está en el landing ni se usó), "recencia" como variable principal (la frecuencia pesa más), "un minorista del Reino Unido" (91 % de los clientes son del Reino Unido, pero hay 41 países), la automatización mensual (el archivo es estático) y el costo de la oferta (no hay costos en el archivo). Ver "Contradicciones con el sitio". [Verificado]
9. No se encontró un costo de retención ni un valor de cliente retenido que sea público y defendible para este caso. El umbral debe partir de supuestos declarados. [Verificado en búsqueda]
10. No se encontró un estudio revisado por pares que use Online Retail II para churn con cortes documentados. Verbeke y otros (2012) son la referencia primaria para la evaluación por beneficio. [Verificado en búsqueda; hueco declarado]

---

## Fuentes

**Datos**

- Página del conjunto: https://archive.ics.uci.edu/dataset/502/online+retail+ii. [Verificado: página abierta el 2026-11-11]
  - Licencia: "This dataset is licensed under a Creative Commons Attribution 4.0 International (CC BY 4.0) license." [Verificado]
  - Citación que da la página: Chen, D. (2012). Online Retail II [Dataset]. UCI Machine Learning Repository. https://doi.org/10.24432/C5CG6D. [Verificado]
  - Instancias: 1.067.371. Variables: 8 (`InvoiceNo`, `StockCode`, `Description`, `Quantity`, `InvoiceDate`, `UnitPrice`, `CustomerID`, `Country`). Rango de fechas: "between 01/12/2009 and 09/12/2011". La página indica "Donated on 9/20/2019" y no muestra fecha de actualización. [Verificado]
  - Metadatos de la API de UCI, usados por el proyecto 02: `last_updated` = "Fri Jan 05 2024" (`02-Ecommerce-Customer-Segmentation/docs/research.md`). No se contradicen: son campos distintos. [Documentación, proyecto 02]
- Archivo descargado por el proyecto 02 (zip oficial): https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip. Esta investigación no lo volvió a descargar: copió `online_retail_II.xlsx` y `online_retail_ii.zip` de `02-Ecommerce-Customer-Segmentation/data/raw/` en solo lectura. [Verificado]
- Decisiones del proyecto 02 reutilizadas: D02 (huella fijada), D03 (copias del solapamiento), D04 (anulaciones LIFO por cliente y producto), D05 (líneas sin cliente, vales y códigos de servicio), D06 (transacción = día de compra). `02-Ecommerce-Customer-Segmentation/docs/decisions.md`. [Verificado: se leyeron las decisiones y el código `src/custseg/netting.py` y `validate.py`]

**Trabajos previos** (ver la sección correspondiente)

- Verbeke, W., Dejaeger, K., Martens, D., Hur, J., Baesens, B. (2012). "New insights into churn prediction in the telecommunication sector: A profit driven data mining approach". *European Journal of Operational Research* 218(1), 211–229. DOI 10.1016/j.ejor.2011.09.031. [Documentación: registros de EconPapers, Univ. de Amberes y Peeref en búsqueda; el artículo no se abrió completo. Un registro de EconBiz lista otro coautor y otra paginación: se descartan por ser errores de catálogo.] Es la referencia que cita el sitio ("Verbeke y otros (2012)").
- Gupta, S., Lehmann, D. R., Stuart, J. A. (2004/2003), "Valuing Customers", *Journal of Marketing Research*. El PDF de la Universidad de Columbia dice 2003; el año no está confirmado. [Fuente secundaria: resultado de búsqueda; no se abrió el artículo]
- Búsqueda de estudios sobre Online Retail II y churn: resultados sin artículo revisado por pares que use este conjunto (ver "Trabajos previos"). [Fuente secundaria]

**Librerías**

- scikit-learn, `HistGradientBoostingClassifier`: https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.HistGradientBoostingClassifier.html [Documentación: no se abrió en esta investigación; se usó la versión instalada 1.9.1]
- SHAP, `TreeExplainer`: versión instalada 0.51.0; la documentación no se abrió. Su comportamiento se verificó directamente con las pruebas de aditividad [Verificado]
- lifetimes 0.11.3 (BG/NBD): versión instalada; la URL de documentación no se abrió. El proyecto 02 registró que no tiene mantenimiento desde 2020 [Documentación, proyecto 02]

---

## Metodología de verificación

- **Entorno**: Windows 10 Pro. Python 3.11.1 en una venv de scratch (`py -3.11 -m venv`). Versiones instaladas: pandas 2.3.3 (la misma que fijó el proyecto 02), NumPy 2.4.6, SciPy 1.17.1, scikit-learn 1.9.1, pyarrow 26.0.1, openpyxl 3.1.5, lifetimes 0.11.3, shap 0.51.0 (con numba 0.68.1), psutil 7.2.2 (solo para medir memoria). Todos los scripts se ejecutaron con `python -I`.
- **Lectura**: `pandas.read_excel` con `openpyxl` y tipos de texto para `Invoice`, `StockCode`, `Description`, `Country` y `Customer ID`, para no perder ceros. Tiempo de lectura: 42 s. Resultado: `raw.parquet` de 1.067.371 filas. [Verificado: `out/s01_load.out`]
- **Netting**: el archivo `netting.py` del proyecto 02 se cargó por ruta con `importlib` en modo de solo lectura, sin importar el paquete ni modificar el repositorio. Con ese código se calcularon las compras netas (anulaciones emparejadas LIFO) y los días de compra. [Verificado]
- **Cortes y regla de prueba**: los cortes de prueba se fijaron por calendario antes de calcular cualquier tasa: 2011-08-01 y 2011-09-01. Los tiempos entre compras usan solo compras anteriores a 2011-08-01. La tabla de churn por N y M usa solo los cortes de entrenamiento. La primera mirada usa el primer corte de validación. Los perfiles de calidad (sección de datos) son descriptivos del archivo completo: no son tasas ni modelos sobre un corte, pero **un conteo de clientes con compra neta en todo el archivo sí usó el periodo de prueba** (`out/s06_extra_profile.out`); se declara aquí y no interviene en ninguna decisión.
- **Convención de fechas**: un corte en la fecha `c` usa solo compras y anulaciones con fecha anterior a `c`. La etiqueta usa la ventana `[c, c+N-1]` con anulaciones conocidas hasta `c+N-1`. [Inferido: convención de este documento]
- **Scripts**: `<temp>\scripts\` (`s01` a `s07`, `common.py`, y dos diagnósticos `s04b`, `s04c` y `s05b`, `s05c`). Las salidas están en `...\tmp.4G0E3y6lZg\out\`.
- **Límites**: la primera mirada es una sola configuración y un solo corte de validación con 1.677 clientes. El error de muestreo de un AUC con ese tamaño es de unos ±0,02 (ver "Primera mirada del modelo"). Las cifras de costo son supuestos.

---

## Fuente de datos

### Descarga y control de cambios

| Concepto | Valor | Estado |
|---|---|---|
| Archivo zip | `online_retail_ii.zip`, 45.622.418 bytes | [Verificado] |
| SHA-256 del zip | `572e36277c2390fbfde10664750731e0a86f55e33470d91919085f0408e67bfb`, igual a la huella fijada en el proyecto 02 (D02) | [Verificado] |
| Libro dentro del zip | `online_retail_II.xlsx`, 45.622.278 bytes | [Verificado] |
| SHA-256 del libro | `bcbe73b35f5b7babf197fb0cb983a11f5d9ff929078d4aa53d171b1f2df2e980`, igual a la del proyecto 02 | [Verificado] |
| Validadores del servidor | El proyecto 02 registró que no hay `ETag`, `Last-Modified` ni soporte de `Range`. No se repitió | [Documentación, proyecto 02] |

**Consecuencia**: la ingesta debe comparar el SHA-256 del zip y del libro con la huella fijada, como en el proyecto 02. El archivo es estático: no llegan facturas nuevas.

### Hojas, filas, columnas y tipos

- **Hojas**: `Year 2009-2010` con 525.461 filas (2009-12-01 07:45 a 2010-12-09 20:01; 28.816 facturas; 4.383 clientes con ID) y `Year 2010-2011` con 541.910 filas (2010-12-01 08:26 a 2011-12-09 12:50; 25.900 facturas; 4.372 clientes con ID). [Verificado: `out/s02_profile.out`]
- **Filas totales**: 1.067.371, igual que el número de instancias de UCI. [Verificado]
- **Columnas**: `Invoice`, `StockCode`, `Description`, `Quantity`, `InvoiceDate`, `Price`, `Customer ID`, `Country`. Ninguna columna contiene nombres, direcciones, correos ni contraseñas. [Verificado]
- **Codificación de cliente**: `Customer ID` es un número de 5 dígitos entre 12346 y 18287. Es un identificador de cuenta, no una persona comprobada. [Verificado]
- **Base del proyecto**: tras quitar las copias del solapamiento (proyecto 02, D03) quedan 1.044.848 filas. Las repeticiones internas se conservan. Facturas: 53.628. Clientes con ID: 5.942. Países: 43. [Verificado]

### Duplicados y solapamiento

- Copias exactas en las ocho columnas: 34.335 filas en total: 22.523 son copias de la hoja 2 dentro de la ventana común (2010-12-01 a 2010-12-09), y 11.812 son repeticiones dentro de una misma hoja. [Verificado]
- Regla del proyecto 02 (D03), reutilizada: se quitan solo las copias de la hoja 2 en la ventana común, por multiconjunto. Las repeticiones internas se conservan, porque el proyecto 02 midió que vienen del sistema de origen. [Verificado; coincide con la base de D03 de 1.044.848 filas]
- Repeticiones internas con la misma factura, código, cantidad, precio, fecha y cliente: 11.814 filas en la base. Son compras de dos líneas idénticas o cargas repetidas; no se pueden separar con el archivo. [Verificado; Inferido en la interpretación]

---

## Perfil de calidad de datos (para churn)

Todas las cifras de esta sección son del archivo completo, salvo que se diga otra cosa. Son descriptivas: no hay cortes ni etiquetas.

### Clientes y compras

- Líneas sin cliente: 235.287 de 1.044.848 (22,52 %). En el archivo crudo son 243.007 (22,77 %), la cifra que midió el proyecto 02. [Verificado; la cifra cruda, Documentación proyecto 02]
- Por qué importa para una etiqueta por cliente: una línea sin ID no puede asignarse a un cliente, así que su compra no entra en la baja de nadie. Las líneas sin cliente aportan 15,11 % del importe bruto positivo y 22,42 % de las líneas con importe positivo. Un cliente invitado que compra una vez y no vuelve no puede contarse como baja. **Propuesta**: la etiqueta solo se calcula para clientes con ID; el ingreso de las líneas sin ID se informa aparte. [Verificado]
- Clientes con compra neta en todo el archivo: 5.839 (de 5.852 con alguna línea de compra válida; 13 se quedan sin compra neta tras las anulaciones). Primera compra: 2009-12-01. Última: 2011-12-09. Con un solo día de compra: 28,6 %; con dos o más: 71,4 %. [Verificado]

### Cancelaciones y devoluciones

- Facturas que empiezan por "C": 8.292 facturas; 19.165 líneas (1,83 % de la base). Casi todas las líneas tienen cantidad negativa: 19.164 de 19.165. [Verificado]
- Líneas con cliente y producto en "C": 18.446, de 2.572 clientes distintos. Líneas "C" sin cliente: 719. [Verificado]
- Importe anulado: 7,14 % del importe bruto positivo. [Verificado]
- Anulaciones emparejadas con compras (netting LIFO del proyecto 02, D04, sobre todo el archivo, con anulaciones conocidas al final de los datos): 16.426 pares anulación-compra, y 1.706 líneas de anulación sin compra que cubrir, por un valor de 34.199 libras. [Verificado]
- Comparación con el proyecto 02: su D04 reportó 15.875 anulaciones completas, 126 parciales y 1.585 sin compra, sobre su base. Los conteos son del mismo orden, pero no son comparables línea por línea: la base de este proyecto y el conteo de líneas cambian. **No se concilió** la diferencia. [Verificado en parte; diferencia abierta]
- Devoluciones: el archivo no distingue devolución de anulación; todo lo que tiene "C" se trata como anulación. [Inferido]
- Factura que empieza por "A" (ajuste de deuda incobrable): 6 líneas. El proyecto 02 no lo documenta. Se excluyen por el criterio de rol (no son compras). [Verificado]

### Códigos de producto no estándar

- Códigos de producto estándar (cinco dígitos con hasta dos letras, o prefijo `DCGS`): 99,43 % de las filas crudas. Hay 63 códigos distintos no estándar. [Verificado; proyecto 02 y `out/s02_profile.out`]
- Líneas de servicio (no producto) en la base: 5.736. Los principales: `POST` (2.086, envío), `DOT` (1.425, envío de comercio electrónico), `M` (1.398, ajuste manual), `C2` (277, transporte), `D` (173, descuento), `S` (102, muestras), `BANK CHARGES` (100), `ADJUST` (67), `AMAZONFEE` (36), `PADS` (19), `CRUK` (16), `TEST001` (15). [Verificado]
- Vales de regalo (`gift_0001_*`): 100 filas, todas sin cliente. [Verificado]
- Aplicación de la regla de rol del proyecto 02 (`validate.classify_lines`): de las 239.020 líneas excluidas, 235.287 no tienen cliente, 3.663 son códigos de servicio con cliente y 70 tienen precio cero con cliente. [Verificado]
- `PADS` ("PADS TO MATCH ALL CUSHIONS") no cumple el patrón de cinco dígitos: el proyecto 02 lo trata como servicio. Esta investigación lo mantiene como el proyecto 02 para no abrir otra decisión. [Verificado; pendiente de decisión para el plan]

### Precios, cantidades y valores atípicos

- Precios negativos: 5 líneas. Precios cero: 6.024 líneas (70 con cliente). [Verificado]
- Precio mayor de 1.000: 239 líneas; mayor de 100: 1.911. Cuantiles de precio: p1 = 0,21; mediana = 2,10; p99 = 18,00; p99,9 = 214,59. [Verificado]
- El precio unitario máximo, 38.970, es una línea `M` de ajuste manual (factura `C556445`, cantidad -1). Su línea de compra asociada es la de mayor importe positivo: 60 unidades a 649,50 (factura 556444, código 22502), con importe 38.970. [Verificado]
- La línea de mayor importe es la factura 581483: 80.995 unidades a 2,08 (168.469,60 libras). La anula la factura C581484 doce minutos después; el proyecto 02 documentó el mismo caso. [Verificado]
- Cantidades: de -80.995 a 80.995. Líneas con |cantidad| ≥ 10.000: 15. Líneas con cantidad ≥ 5.000: 43. [Verificado]
- Regla de atípicos propuesta: no se eliminan por tamaño. Las anulaciones grandes se cancelan con el netting, que ya quita las compras anuladas. [Inferido]

### Países

- Países distintos: 43 en la base. Reino Unido: 91,88 % de las líneas y 91,03 % de los clientes (5.410 de 5.942). [Verificado]
- Países con al menos un cliente: 41. Países con menos de 10 clientes: 24; con menos de 5: 18; con un solo cliente: 10. Clientes en países con menos de 10: 73 de 5.942. [Verificado]
- Valor "Unspecified": 756 líneas; 7 clientes. [Verificado]
- Clientes con más de un país en el archivo: 13. [Verificado; coincide con el proyecto 02]

### Mayoristas y mezcla de clientes

- Regla de mayoristas del proyecto 02 (D10: mediana de unidades por línea de 24 o más, con al menos 3 líneas): 434 clientes, 7,4 % de los 5.852 con compra válida, que aportan 29,5 % del importe bruto de compras con cliente. [Verificado; regla del proyecto 02, no validada]
- Invitados: 22,5 % de las líneas no tienen cliente y aportan 15,1 % del importe positivo. Son una mezcla distinta: no se pueden seguir en el tiempo. [Verificado]

---

## Definir "se fue" cuando nada lo dice

### Definición propuesta

- **Compra neta**: una línea de cliente, de producto, con cantidad positiva y precio positivo, que no está en una factura "C" ni "A", cuya cantidad queda positiva tras las anulaciones emparejadas (LIFO, proyecto 02 D04).
- **Día de compra**: un día con al menos una compra neta del cliente (proyecto 02 D06).
- **Baja (churn)**: el cliente tiene compra neta en el corte (dentro de su historia y de su población activa) y **no tiene ningún día de compra neta en los N días que empiezan en la fecha de corte** `[c, c+N-1]`.
- **Propuesta**: N = 90 días, como dice el sitio. Ver la evidencia en las secciones siguientes. [Inferido a partir de los datos]

### Tiempos entre compras

Sobre compras netas hasta 2011-07-31 (antes del primer corte de prueba). 5.108 clientes con compra neta; 1.620 (31,7 %) con un solo día de compra; 3.488 con dos o más. [Verificado: `out/s03_churn_window.out`]

| Medida | Días |
|---|---:|
| Brecha entre días de compra consecutivos: mediana | 31 |
| Cuartil 75 | 68 |
| Percentil 90 | 134 |
| Percentil 95 | 191 |
| Percentil 99 | 322 |
| Media | 53,8 |

Brechas consecutivas: 20.095. Porcentaje de brechas mayores que 30, 60, 90, 120 y 180 días: 50,8; 28,1; 18,0; 11,9 y 5,6. Mediana por cliente de sus brechas (clientes con dos o más días): 63 días.

**Lectura**: una brecha de 90 días es ya una brecha larga para la mitad de los clientes. Un N de 30 días marcaría bajas a la mitad de la base.

### Silencio y regreso

Tras un día de compra `d`, se mira si el cliente calla más de N días, y si vuelve en los 90 días siguientes al silencio. Solo se cuentan días con `d + N + 90` dentro del periodo observado, para no censurar. [Verificado: `out/s03_churn_window.out`]

| N (silencio) | Días observados | Silencios > N | Vuelven en los 90 días siguientes |
|---:|---:|---:|---:|
| 30 | 20.445 | 59,5 % | 57,1 % de los silencios |
| 60 | 19.314 | 40,3 % | 46,2 % |
| 90 | 18.295 | 31,2 % | **39,2 %** |
| 120 | 17.306 | 25,6 % | 33,4 % |
| 180 | 14.055 | 17,8 % | 24,3 % |

**Lectura**: ninguna N elimina el ruido. Con N = 90, casi 4 de cada 10 clientes que calla 90 días vuelve a comprar en los 90 días siguientes: la etiqueta marca como perdido a alguien que vuelve. Esto debe decirse en el sitio y en el tablero.

### Tasa de bajas según N

Cortes de entrenamiento (7 cortes mensuales de 2010-06-01 a 2010-12-01), población de clientes activos en los M días anteriores, promedio ponderado por el tamaño de la población. [Verificado: `out/s03_churn_window.out`, tabla B1]

| N (días sin compra) | M = 90: tasa de bajas | M = 180 | M = 365 | Rango por corte (M = 90) |
|---:|---:|---:|---:|---|
| 60 | 52,3 % | 57,1 % | 60,3 % | 42,0 % a 65,8 % |
| **90** | **43,2 %** | 48,3 % | 51,9 % | 31,2 % a 57,9 % |
| 120 | 36,9 % | 42,1 % | 45,9 % | 27,1 % a 51,0 % |
| 180 | 29,5 % | 34,7 % | 38,7 % | 23,3 % a 41,8 % |

**Lectura**: la tasa baja cuando N sube. Con N = 90 hay una base de bajas de 43 %, que es lo bastante equilibrada para entrenar. N = 60 detecta antes, pero etiqueta más falsas bajas (46 % de los silencios de 60 días vuelven). N = 120 y N = 180 dan etiquetas más firmes, pero con menos clientes y menos cortes para la prueba, y avisan más tarde.

### Propuesta de N y M, con evidencia

- **N = 90 días.** Razones: está en el texto del sitio; cae entre el cuartil 75 y el percentil 90 de las brechas (68 y 134 días); da una tasa de bajas utilizable (43 %); y deja cortes de prueba completos con los datos disponibles (ver "Fechas de corte"). Sensibilidad a registrar en el plan: N = 60 y N = 120. [Inferido]
- **M = 90 días.** La población de cada corte son los clientes que compraron en los 90 días anteriores: 2.185 en promedio, de 1.925 a 2.859 según el corte. Los que callaron más de 90 días (1.202 en promedio) vuelven en 32 % de los casos en los 90 días siguientes: un grupo de reactivación que no entra en este modelo. Ver la tabla siguiente. [Verificado]

| M (días activos antes del corte) | Clientes en la población (promedio) | Tasa de bajas en la población | Excluidos (inactivos más de M) | Excluidos que vuelven en 90 días |
|---:|---:|---:|---:|---:|
| 30 | 1.135 | 37,5 % | 2.253 | 40,9 % |
| 60 | 1.768 | 40,9 % | 1.620 | 36,1 % |
| **90** | **2.185** | **43,2 %** | **1.202** | **32,3 %** |
| 180 | 2.934 | 48,3 % | 454 | 24,7 % |
| 365 | 3.388 | 51,9 % | 0 | — |

**Lectura**: con M = 365 no hay excluidos porque el archivo empieza en diciembre de 2009. M = 180 aumenta la población y deja fuera menos reactivaciones, pero incluye clientes que ya llevan medio año sin comprar. M = 90 es lo que un equipo de retención entiende como "activo" y es el mismo horizonte que N. Alternativa a probar en el plan: M = 180. [Inferido]

### Estacionalidad

La tasa de bajas cambia mucho según el mes del corte: 44 % (junio 2010), 31 % (septiembre 2010), 46 % (noviembre 2010) y 58 % (diciembre 2010). Un corte de diciembre mira enero y febrero, después de las compras navideñas. [Verificado: `out/s04_first_look.out`, por corte] Esto es una fuente de error para un modelo con cortes mensuales. Ver "Riesgos y huecos".

---

## Fuga de información, cortes y partición

### Fechas de corte

- Serie mensual: el día 1 de cada mes. Los cortes trabajan con la misma regla: historia antes de `c`, etiqueta en `[c, c+89]`.
- Límite: el último corte debe tener la ventana completa antes de 2011-12-09. Con N = 90, `c + 89 ≤ 2011-12-09`, es decir, `c ≤ 2011-09-11`. El último corte mensual posible es **2011-09-01**.
- Primer corte: 2010-06-01, para tener al menos seis meses de historia (desde 2009-12-01).
- Serie propuesta: 2010-06-01 a 2011-09-01, mensual: 16 cortes. Los cortes de validación y de prueba no se calcularon.
- Alternativa trimestral: no se propone, porque deja solo cuatro cortes para entrenamiento. [Inferido]

### Partición

Purga igual a N (90 días) entre bloques, para que la etiqueta de un bloque no se solape con la de otro: `c_anterior + 90 ≤ c_siguiente`.

| Bloque | Cortes | Ventana de etiqueta | Estado en esta investigación |
|---|---|---|---|
| Entrenamiento | 2010-06-01 a 2010-12-01 (7 cortes mensuales) | 2010-06-01 a 2011-02-28 | Calculado: 15.297 filas, 3.942 clientes, tasa de bajas 43,2 % |
| Purga | 2010-12-01 + 90 días = 2011-03-01 | | |
| Validación | 2011-03-01, 2011-04-01, 2011-05-01 (3 cortes) | 2011-03-01 a 2011-07-29 | Solo el primero (2011-03-01): 1.677 clientes, tasa 43,4 % |
| Purga | 2011-05-01 + 90 días = 2011-07-30; el siguiente corte es 2011-08-01 (92 días) | | |
| Prueba | 2011-08-01 y 2011-09-01 (2 cortes) | 2011-08-01 a 2011-11-29 (el último) | **No calculada.** |

- Comprobación del corte de validación: `2011-03-01 ≥ 2010-12-01 + 90 días` (el script lo verifica con una aserción).
- Consecuencia: hay dos cortes de prueba, de solo 2 meses de etiqueta cada uno, y el último tiene 10 días de datos sobrantes. El conjunto de prueba es pequeño. [Inferido]
- Advertencia de la estacionalidad: la prueba (agosto y septiembre) mira agosto–noviembre, y el entrenamiento incluye un corte de diciembre. Ver "Riesgos y huecos".

### Rasgos que podrían filtrar información

| Rasgo o fuente | Por qué podría filtrar | Cómo lo detecta una prueba |
|---|---|---|
| Compras netas calculadas con anulaciones posteriores al corte | Una anulación posterior baja la compra anterior y cambia `freq_*`, `mon_*` y `gap_*` | Prueba de truncamiento: recalcular los rasgos con datos hasta `c−1` y comparar con los de datos completos; deben ser idénticos |
| Anulaciones posteriores al corte (`canc_365`, `canc_value_365`) | Una anulación dentro de la ventana de etiqueta también es un evento posterior | Igual que la anterior: contar solo `invoice_date < c` |
| Último país del archivo completo | Un cliente que cambia de país después revela el futuro | Asignar el país con las líneas anteriores a `c` |
| Recencia medida hasta el fin del archivo | Usa el futuro como referencia | Prueba: la recencia debe depender solo de `c` |
| Parámetros de BG/NBD ajustados con historia posterior a 2010-12-01 | Los parámetros ven la etiqueta de los cortes siguientes | Reajustar con historia truncada; los parámetros deben coincidir |
| Mediana de unidades por línea (`med_units_365`) con líneas posteriores | Igual que el primer punto | Igual que la prueba de truncamiento |
| Una etiqueta calculada con anulaciones conocidas hasta el final de los datos | Mezcla la etiqueta con información posterior a su ventana | Calcular la etiqueta con anulaciones hasta `c+N−1` (lo que hace este proyecto) |
| Cliente que aparece en varios cortes | No es fuga de etiqueta, pero el mismo cliente puede estar en entrenamiento y validación | Medir la proporción de clientes compartidos antes de la primera mirada del plan; no usar el ID como rasgo |

**Control de fuga, positivo**: el rasgo "días desde la última compra hasta el fin de la ventana de etiqueta", que mira el futuro, da AUC 1,000 en los tres primeros cortes de entrenamiento. Esto confirma que una prueba de fuga debe fallar con un rasgo así. [Verificado: `out/s04_first_look.out`]

**Pruebas que el plan debe escribir**: (1) truncamiento de todos los rasgos; (2) assert `c_siguiente ≥ c_anterior + N` entre bloques; (3) reajuste de BG/NBD con historia truncada; (4) un rasgo de control que mire el futuro debe dar AUC cercano a 1 y bloquear la ejecución.

---

## Líneas base

Todas las líneas base se evalúan con la misma etiqueta. Los parámetros (cuartiles, parámetros de BG/NBD) se fijan con los cortes de entrenamiento. [Verificado: `out/s04_first_look.out`]

| Línea base | Qué mide | Cómo se usa |
|---|---|---|
| Recencia | Días desde la última compra neta | Puntaje: más días, más riesgo |
| RFM | Quintiles dentro del corte de recencia (R), frecuencia de 365 días (F) y gasto de 365 días (M); puntaje 3 a 15 | Puntaje invertido: menos puntos, más riesgo |
| BG/NBD P(vivo) | `lifetimes` 0.11.3, parámetros congelados en el corte 2010-12-01 (r = 0,908; α = 75,76; a = 0,174; b = 108,27) | Puntaje 1 − P(vivo). Es lo que pidió el proyecto |
| BG/NBD compras esperadas en 90 días | Mismo ajuste, media de compras netas en los próximos 90 días | Variante añadida: puntaje invertido |

**Resultados en entrenamiento (promedio de los 7 cortes)**

| Línea base | AUC | PR-AUC | Lift 10 % | Lift 20 % |
|---|---:|---:|---:|---:|
| RFM | 0,734 | 0,612 | 1,64 | 1,62 |
| BG/NBD compras esperadas en 90 días | 0,732 | 0,605 | 1,58 | 1,55 |
| Recencia | 0,594 | 0,499 | 1,30 | 1,27 |
| BG/NBD 1 − P(vivo) | 0,362 | 0,369 | 0,74 | 0,76 |

**Lectura**

- **BG/NBD P(vivo) no sirve en esta población.** Los clientes activos tienen P(vivo) entre 0,996 y 1,000 (corte de 2010-12-01). Casi no hay varianza, así que el orden no dice nada. Por eso el AUC queda bajo 0,5. En el grupo sin repetición (una sola compra), la tasa de bajas es 82,5 %, y P(vivo) es casi 1 para ellos. [Verificado: salida en consola de `scripts/s04c_bgnbd_groups.py`, corte de 2010-12-01]
- **Lo que sí funciona es el número esperado de compras en 90 días** (AUC 0,732 en entrenamiento y 0,776 en validación): mide directamente la ventana de la etiqueta.
- **RFM es la línea base más difícil de superar** en entrenamiento (0,734) y en validación (0,784).

---

## Primera mirada del modelo

Primera mirada con una sola configuración de `HistGradientBoostingClassifier` de scikit-learn (`max_iter=300`, `learning_rate=0.05`, `max_leaf_nodes=31`, `min_samples_leaf=50`, `random_state=0`). **No es el resultado del proyecto.**

- Entrenamiento: los 7 cortes de entrenamiento apilados, 15.297 filas (clientes activos en M = 90 días en cada corte). Clientes distintos: 3.942.
- Validación: solo el primer corte (2011-03-01), 1.677 filas, tasa de bajas 43,35 %.
- Columnas (25): recencia (`rec_days`), antigüedad (`tenure_days`), frecuencia total y de 90 y 365 días, gasto total, de 90 y de 365 días, gasto medio por día de compra (`aov_day`), unidades de 90 días, brecha media y máxima entre días de compra (`gap_mean`, `gap_max`), productos distintos de 365 días, mediana de unidades por línea de 365 días, anulaciones y su valor de 365 días, y el país con indicadores one-hot (8 países más "Otros").
- Ningún rasgo usa datos posteriores a `c`. Ningún rasgo usa el ID del cliente.
- Ajuste en 146 iteraciones, 0,3 s.

**Resultados en validación (2011-03-01, 1.677 clientes, tasa de bajas 43,35 %)**

| Modelo | AUC | PR-AUC | % de bajas capturadas en el 10 % superior | Lift 10 % | % capturadas en el 20 % superior | Lift 20 % |
|---|---:|---:|---:|---:|---:|---:|
| Recencia | 0,625 | 0,559 | 14,7 | 1,47 | 28,1 | 1,41 |
| **RFM** | **0,784** | **0,684** | 18,2 | **1,81** | 34,1 | 1,71 |
| BG/NBD P(vivo) | 0,433 | 0,403 | 8,4 | 0,84 | 17,6 | 0,88 |
| BG/NBD compras esperadas en 90 días | 0,776 | 0,692 | 18,0 | 1,80 | 32,9 | 1,65 |
| **HistGradientBoosting (25 columnas)** | 0,769 | 0,691 | 18,0 | 1,80 | 33,8 | 1,69 |
| HistGradientBoosting con recencia y frecuencia de 365 días | 0,773 | 0,682 | 17,2 | 1,72 | 34,0 | 1,70 |

Lectura: "% capturadas" es la parte de todas las bajas que cae en el 10 % o el 20 % superior del riesgo. Lift es la tasa de bajas en ese tramo dividida por la tasa general. El 10 % superior del HGB tiene una tasa de bajas de unos 78 % (1,80 × 0,4335). [Inferido: cálculo a partir de la tabla]

**Incertidumbre** (bootstrap de 1.000 remuestreos sobre el corte de validación, `out/s07_bootstrap.out`):
- IC 95 % del AUC: RFM [0,763; 0,805]; HGB [0,749; 0,792]; BG/NBD compras esperadas [0,754; 0,798]; recencia [0,597; 0,652].
- Diferencia pareada HGB − RFM: −0,014, IC 95 % [−0,033; 0,005]. P(HGB > RFM) = 0,064.
- **Conclusión**: con un corte de 1.677 clientes, el modelo no supera a RFM ni a la variante de BG/NBD. Con un solo corte, esa diferencia no se puede declarar. El plan debe medirla en los tres cortes de validación antes de decidir.

**Qué columnas llevan la señal**

- Importancia por permutación en validación (caída del AUC): frecuencia total 0,046; brecha media 0,026; brecha máxima 0,020; gasto total y de 90 días 0,011; unidades de 90 días 0,008. La recencia sola aporta poco (0,004): la frecuencia y las brechas ya la contienen. El país suma muy poco. [Verificado: `out/s04_first_look.out`]
- Concordancia con SHAP (sección siguiente): frecuencia total, brecha media, brecha máxima y gasto encabezan la lista.

---

## SHAP: comprobación del explicador

- **Versión**: `shap` 0,51,0 con `TreeExplainer` (`feature_perturbation="tree_path_dependent"`). [Verificado: `out/s05_shap.out`]
- **Compatibilidad**: con `categorical_features` de scikit-learn sobre el país (columna entera), `TreeExplainer` corre pero **no es aditivo**: error máximo de 3,6 en log-odds. Sin el país, el error es de 1,1·10⁻¹⁴; con el país en one-hot, de 8,4·10⁻¹⁵. Por eso el modelo de la primera mirada usa one-hot. [Verificado: salida en consola de `scripts/s05c_additivity.py`]
- **Aditividad del modelo final** (validación): suma de SHAP más valor base igual a `decision_function` con error máximo de 8,4·10⁻¹⁵ en log-odds, y 1,6·10⁻¹⁵ en probabilidad. Mismo resultado en entrenamiento: 1,2·10⁻¹⁴. [Verificado]
- **Valor base** (log-odds): −0,469.
- **Tiempo**: construcción del explicador 0,03 s; `shap_values` de 1.677 filas y 25 columnas, 0,99 s; de 15.297 filas, 9,0 s. [Verificado]
- **Memoria**: pico de memoria de Python durante `shap_values` sobre validación, 0,8 MB (`tracemalloc`); memoria del proceso de unos 199 MB antes y 204 MB después (`psutil`), incluido el propio intérprete con los datos cargados. [Verificado]
- **Importancia media |SHAP|** (validación): frecuencia total 0,485; brecha media 0,405; brecha máxima 0,194; gasto total 0,152; antigüedad 0,136; frecuencia de 90 días 0,121; gasto de 90 días 0,114; productos distintos 0,094; gasto medio por día 0,075; anulaciones de 365 días 0,062; mediana de unidades 0,061; unidades de 90 días 0,058; recencia 0,056; valor anulado 0,039. Países: 0,016 en total (Francia 0,023, la mayor). [Verificado]
- **Lectura para un lector no técnico**: un cliente tiene riesgo alto porque compra poco, con pausas largas entre compras y poco gasto. Una frase por cliente con sus tres razones principales es posible con SHAP.
- **Alternativa si el explicador falla**: permutación e importancia parcial (PDP), como ya se corrió en la primera mirada. [Verificado]

---

## Valor, costo y curva de ganancia

### Fuentes de costo y de valor

- **Costo de una acción de retención y valor de un cliente retenido**: el archivo no trae costos, campañas ni márgenes. No se encontró una fuente pública que dé una cifra defendible para este caso. [Verificado en búsqueda; hueco declarado]
- **Marco de valor de cliente**: Gupta, Lehmann y Stuart (JMR) definen el valor de un cliente como flujo descontado de ganancias futuras, con retención y margen como insumos. No se abrió el artículo. La cifra de "1 % de retención ≈ 5 % de valor de la empresa" que aparece en una cita secundaria **no está verificada** y no se usa. [Fuente secundaria]
- **Evaluación por beneficio**: Verbeke y otros (2012) proponen medir el modelo por el beneficio máximo de una campaña que contacta a la fracción óptima de clientes con mayor probabilidad de abandono. Es la referencia que el sitio cita. [Documentación: registro en búsqueda, DOI 10.1016/j.ejor.2011.09.031]
- Hueco: no se encontró un estudio de costo de retención para un minorista en línea con fuente primaria. Antes de escribir una cifra en el sitio, hay que declararla como supuesto.

### Propuesta: supuestos declarados y cómo se elige el corte

- Declarar, antes de mirar prueba, tres supuestos: `c_oferta` (costo de contactar a un cliente), `r` (tasa de rescate: fracción de bajas que la oferta retiene) y `V` (valor de un cliente retenido, por ejemplo, gasto neto esperado de 12 meses multiplicado por un margen declarado).
- Un cliente se contacta si `p × r × V ≥ c_oferta`, es decir, si `p ≥ c_oferta / (r × V)`. Con los supuestos del proyecto, el umbral sale de validación.
- Opción de corte por top-k: contactar al k % superior del riesgo; la elección de k es la misma en validación. No se usa F1.
- Para `V` hay una base en los datos: el gasto neto esperado a 12 meses, que el proyecto 02 calcula con BG/NBD y Gamma-Gamma. [Inferido]
- Ejemplo ilustrativo, no fuente: si contactar cuesta 2, rescata el 20 % de las bajas y el valor de un cliente es 60, el umbral es 2 / (0,2 × 60) ≈ 0,17.

### Qué muestra la curva de ganancia

- **Para un lector no técnico**: "Si contactamos al 10 % de clientes con más riesgo, capturamos X % de los que se irían." Con el modelo de validación: contactar al 10 % superior capta cerca de 18 % de las bajas, y en ese 10 % la tasa de bajas es de unos 78 %, frente a 43 % en general.
- Un modelo sin mejora produce una diagonal; un buen modelo se separa de ella al principio.
- La curva no mide el dinero: para eso hace falta el costo y el valor declarados.

---

## Datos personales

| Columna | Qué contiene | Estado | Regla para las salidas |
|---|---|---|---|
| `Customer ID` | Número de 5 dígitos. Pseudonimizado: identifica una cuenta, no una persona comprobada | Pseudónimo | No publicar; no usar como rasgo; en los agregados, no mostrar IDs |
| `Country` | País del cliente (43 valores) | Cuasi identificador en países pequeños | Agrupar países con menos de 10 clientes en "Otros" |
| `Invoice`, `InvoiceDate`, `Quantity`, `Price` | Facturas y compras | No personal por sí mismas | Publicar solo agregados |
| `Description` | Nombre del producto | No personal | Puede publicarse por producto con agregados |
| `Country` con `Customer ID` | Un cliente en un país pequeño puede identificarse | Riesgo de reidentificación | Regla de celda pequeña |

- **Lo que no tiene el archivo**: nombres, apellidos, direcciones, correos, teléfonos, contraseñas. [Verificado: las 8 columnas]
- **Regla de celda pequeña propuesta**: ninguna celda publicada (país, mes, segmento, grupo de riesgo) tiene menos de 10 clientes. Con los datos: 24 países tienen menos de 10 clientes y agrupan 73 clientes; se publican como "Otros". [Verificado en conteos; regla propuesta]
- **Lo que se puede publicar en el sitio**: agregados (tasas, curvas, promedios), los motivos de un cliente solo como ejemplo sin identidad, y las tablas de países con celdas de 10 o más.
- **Lo que no se puede publicar**: la lista de clientes en riesgo con su ID, en ninguna forma, ni la lista de países pequeños por separado.
- Licencia CC BY 4.0: la atribución no exime de la regla de celda pequeña. [Inferido]

---

## Trabajos previos

| Trabajo | Qué reporta | Fuga o cortes | Estado |
|---|---|---|---|
| Verbeke y otros (2012), EJOR, DOI 10.1016/j.ejor.2011.09.031 | Churn en telecomunicaciones, con evaluación por beneficio de campaña | Documenta el beneficio, no la fuga en un conjunto de compras | Documentación: registro en búsqueda; no es sobre este conjunto |
| Chen, Sain y Guo (2012), *Journal of Database Marketing & Customer Strategy Management* 19(3), DOI 10.1057/dbm.2012.17 | RFM y k-means en un minorista en línea | Su texto no se abrió | Ver proyecto 02: la fuente de 2011 no coincide con este archivo; no se usa aquí |
| Estudios de churn sobre Online Retail II en búsquedas (blogs, tutoriales, un portafolio, una tesis, un artículo de 2024 sobre tienda en línea sin nombrar el conjunto) | Modelos de gradient boosting; cifras de AUC altas | Algunos muestran etiquetas por ventana de inactividad; ninguno documenta cortes | Fuente secundaria: no se pueden citar como resultado |
| Guía general de fuga (DEV Community) | Observación, hueco de bloqueo y ventana de etiqueta | Advierte que un rasgo del estado actual puede filtrar el futuro | Fuente secundaria |

**Conclusión**: no hay un artículo revisado por pares que use Online Retail II para churn con cortes documentados. Las cifras altas de AUC que aparecen en tutoriales no tienen cortes ni lista de rasgos publicada, así que no se usan como referencia. [Verificado en búsqueda; hueco declarado]

---

## Librerías: lo que se instaló y ejecutó

| Paquete | Versión | Uso | Resultado |
|---|---|---|---|
| Python | 3.11.1 | Venv de scratch | Ejecutado con `python -I` |
| pandas | 2.3.3 | Lectura, cortes, rasgos | Ejecutado sin errores |
| NumPy | 2.4.6 | Cálculos | Ejecutado |
| SciPy | 1.17.1 | Dependencia de lifetimes | Instalado |
| scikit-learn | 1.9.1 | `HistGradientBoostingClassifier`, métricas, permutación | Ejecutado |
| pyarrow | 26.0.1 | Parquet de trabajo | Ejecutado |
| openpyxl | 3.1.5 | Lectura del libro | Ejecutado (42 s) |
| lifetimes | 0.11.3 | BG/NBD, compras esperadas | Ejecutado: ajuste y `conditional_expected_number_of_purchases_up_to_time` |
| shap | 0.51.0 (con numba 0.68.1) | `TreeExplainer` | Ejecutado: aditividad verificada |
| psutil | 7.2.2 | Medir memoria (solo investigación) | Ejecutado |

- `lifetimes` no tiene mantenimiento desde 2020 (dato del proyecto 02). Para el plan, decidir si se usa o si se reimplementa como en el proyecto 02 (D13, D42).
- No se usó LightGBM: el sitio lo nombra, pero el landing no lo declara (ver "Contradicciones con el sitio").

---

## Tecnologías: landing y librerías nuevas

Tecnologías que el landing declara (`LANDING-EXPANSION.md` y el landing): Power BI, Looker Studio; Apache Airflow, n8n, Power Automate; FastAPI, Docker, RAG, TensorFlow, Edge AI; Python, dbt, SQL, BigQuery, pandas, scikit-learn; SAP, ERPs, REST APIs, Azure, Google Cloud. [Verificado: `LANDING-EXPANSION.md`; lista del proyecto 03]

| Herramienta que el proyecto usaría | En el landing | Observación |
|---|---|---|
| Python, pandas, scikit-learn | Sí | `HistGradientBoostingClassifier`, sin librería nueva |
| SQL | Sí | Para las capas de cortes |
| dbt y BigQuery | Sí (dbt, BigQuery) | Solo si se usa la misma ruta que P1 y P2. SQLite es el reemplazo ya anotado |
| Power BI | Sí | Tablero; si no se puede abrir, diseño en HTML (S4) |
| Apache Airflow y Docker | Sí | DAG mensual, si se decide hacerlo |
| lifetimes | No (ya anotada en `LANDING-EXPANSION.md`) | BG/NBD y compras esperadas |
| openpyxl, NumPy, pyarrow, matplotlib, pytest, SQLite | No (ya anotadas) | Sin cambio |
| **SHAP** (`shap`) | **No** | Nueva. Debe anotarse en `LANDING-EXPANSION.md` para expandir el landing (el sitio ya la nombra en su texto) |
| LightGBM | No | El sitio la nombra; no se usó. Decidir: usar scikit-learn (ya declarado) o anotar LightGBM |
| psutil | No | Solo para medir en esta investigación; no entra en el producto |

**Conclusión**: el proyecto necesita **SHAP**, que no está en el landing ni en `LANDING-EXPANSION.md`. Hay que anotarla. LightGBM no hace falta si se usa scikit-learn. [Verificado]

---

## Contradicciones con el sitio

Texto de `src/i18n/projects/churn-risk.ts` (es y en), archivo de `marca-personal` (solo lectura). Cada fila compara el texto con los datos y propone una redacción. [Verificado]

| Texto del sitio | Lo que muestran los datos | Redacción sugerida |
|---|---|---|
| Algoritmo 2: "Un modelo de árboles combina recencia, frecuencia, gasto, anuladas y país" | La recencia aporta poco; la frecuencia y las brechas entre compras encabezan la señal. El país aporta muy poco | "Un modelo de árboles combina frecuencia, tiempo entre compras, gasto y anulaciones" |
| Algoritmo 2 y producto: "LightGBM" | No se usó. El landing declara scikit-learn | Usar "scikit-learn" o anotar LightGBM en `LANDING-EXPANSION.md` |
| Algoritmo 2: "SHAP explica cada riesgo con los motivos de ese cliente" | Cierto: SHAP es aditivo con el país en one-hot (error 8·10⁻¹⁵). Con el país categórico nativo no sería cierto | Mantener, y decir que el país es un indicador |
| Algoritmo 3: "Un AUC casi perfecto se toma como una alarma de fuga" | Cierto: el rasgo de control que mira el futuro da AUC 1,000 | Mantener |
| Algoritmo 3: "Verbeke y otros (2012)" | Existe: EJOR 2012, DOI 10.1016/j.ejor.2011.09.031 | Mantener; citar DOI |
| Resumen y lede: "un minorista del Reino Unido" | 91 % de los clientes son del Reino Unido; hay 41 países con clientes | "un minorista en línea, sobre todo del Reino Unido" |
| Lede y resumen: "define la baja como ninguna compra en los 90 días siguientes" | Correcto (N = 90). Pero el 39 % de los silencios de 90 días vuelve | Decir la regla y su ruido |
| Automatización: "Cada mes un flujo mueve la fecha de corte" | El archivo es estático y termina el 2011-12-09. Hay que simular la llegada de datos, como hizo el proyecto 02 (D07) | "Cada mes un flujo simula la llegada de datos y mueve la fecha de corte" |
| Tablero: "un panel para mover el costo de la oferta, la tasa de rescate y el margen, cada uno marcado como supuesto" | Correcto: el archivo no trae costos ni tasas | Mantener, con la marca de supuesto |
| Datos: "1 millón de líneas de factura, aprox." | 1.067.371 en bruto; 1.044.848 tras quitar las copias del solapamiento | Correcto; "1,07 millones en bruto" |
| Datos: "2 años de compras, de 2009 a 2011" | 2009-12-01 a 2011-12-09 | Correcto |
| Datos: "0 columnas que digan quién se fue" | Correcto: ninguna de las 8 | Correcto |
| Datos: "Número de factura, con las anuladas" | Correcto: 8.292 facturas con "C" | Correcto |
| Fuente: "Daqing Chen, en UCI Machine Learning Repository", CC BY 4.0 | Correcto según la página de UCI | Citar el DOI completo |

---

## Riesgos y huecos

1. **Ruido de la etiqueta**: el 39 % de los silencios de 90 días vuelve en los 90 días siguientes. El modelo puede estar prediciendo "silencio" más que "baja". [Verificado]
2. **Estacionalidad**: la tasa de bajas va de 31 % a 58 % según el mes del corte. Un corte de diciembre mira enero y febrero. La prueba mira agosto–noviembre. Con cortes mensuales el modelo puede aprender el mes. [Verificado]
3. **Pocos cortes de prueba y de validación**: dos de prueba, tres de validación, uno de ellos usado en la primera mirada, con unos 1.700 clientes por corte. El error de un AUC con ese tamaño es de unos ±0,02; la diferencia con RFM no se puede declarar con un corte. [Verificado]
4. **Regla de bajas sin validación externa**: no hay una medición real de bajas en la tienda. Los resultados son predicciones de inactividad en un archivo público, no bajas comprobadas. [Inferido]
5. **Anulaciones y netting**: el criterio LIFO del proyecto 02 es una decisión, no una verdad. La diferencia de conteos con el proyecto 02 no está conciliada. [Verificado]
6. **Invitados**: 22,5 % de las líneas no tienen cliente y no entran en las bajas. Hay que decirlo: el modelo no ve a los clientes sin cuenta. [Verificado]
7. **BG/NBD**: P(vivo) no sirve en población activa (satura cerca de 1). La variante de compras esperadas sí, pero su uso debe declararse. `lifetimes` no tiene mantenimiento desde 2020. [Verificado]
8. **Calidad de los IDs**: un `Customer ID` puede agrupar a más de una persona o dividir a una persona en varias cuentas. No se puede comprobar con el archivo. [Inferido]
9. **Datos de 2009–2011**: el archivo tiene quince años de antigüedad. El comportamiento de compra actual es distinto. Los resultados se presentan como práctica con datos públicos. [Inferido]
10. **Cuadro de SHAP**: con divisiones categóricas nativas de scikit-learn 1.9.1, `TreeExplainer` no es aditivo (error 3,6). Hay que fijar el modelo con one-hot y probar la aditividad en cada versión. [Verificado]
11. **Cifras de costo**: no hay fuente pública. Cualquier valor de `c_oferta`, `r` o `V` es un supuesto. [Verificado en búsqueda]
12. **Quiebre de régimen**: el proyecto 03 detectó un cambio en la forma de los datos en octubre de 2017. Este archivo no tiene ese cambio: no lo medí, pero conviene revisar la forma de las facturas por mes en el plan. [Inferido]

---

## Preguntas abiertas para el plan

1. **N**: 90 días (propuesto), con sensibilidad a 60 y 120. Ver la tabla de churn por N.
2. **M**: 90 días (propuesto) o 180. Decidir si los clientes con más de M días de silencio se atienden con otro modelo de reactivación.
3. **Estacionalidad**: ¿se usan cortes mensuales con el mes como rasgo, o se evita el mes? ¿Se cambian los cortes de prueba para que cubran un año completo?
4. **Línea base a superar**: RFM (propuesta), con la variante de compras esperadas como segunda.
5. **Modelo**: `HistGradientBoostingClassifier` con 25 columnas one-hot (propuesto) o con menos columnas, dado que las dos columnas de recencia y frecuencia dan AUC 0,773.
6. **Costos del umbral**: declarar `c_oferta`, `r` y `V` antes de mirar prueba. ¿Qué margen se usa para `V`?
7. **Librería de BG/NBD**: `lifetimes` (verificada aquí) o reimplementación como en el proyecto 02.
8. **LightGBM**: ¿se usa scikit-learn (propuesto) o se anota LightGBM en el landing?
9. **SHAP en `LANDING-EXPANSION.md`**: anotar la nueva tecnología.
10. **Regla de celda pequeña**: 10 clientes (propuesta). ¿Se agrupan los países pequeños como "Otros"?
11. **Líneas `PADS` y de servicio**: mantener la clasificación del proyecto 02 o revisarla.
12. **Simulación mensual**: cómo se simula la llegada de datos (como el proyecto 02, D07, o con cortes fijos).
13. **Conciliación con el proyecto 02**: ¿se reconcilian los conteos de anulaciones (D04) antes de publicar?

---

## Resumen para el plan

- **Definición de baja**: sin compra neta en los 90 días que empiezan en el corte (N = 90). Su ruido se declara: 39 % de los silencios vuelve. [Verificado]
- **Población**: clientes con compra neta en los 90 días anteriores al corte (M = 90). 2.185 por corte en promedio. [Verificado]
- **Cortes**: mensuales, del 2010-06-01 al 2011-09-01. Último corte con ventana completa: 2011-09-01. [Verificado]
- **Partición**: entrenamiento 2010-06-01 a 2010-12-01 (7 cortes, 15.297 filas); purga de 90 días; validación 2011-03-01 a 2011-05-01 (primer corte de 1.677 clientes); purga de 90 días; prueba 2011-08-01 y 2011-09-01 (sin calcular). [Verificado]
- **Líneas base** (validación 2011-03-01): RFM AUC 0,784 (la más difícil); compras esperadas de BG/NBD 0,776; recencia 0,625; P(vivo) 0,433 (no sirve). [Verificado]
- **Primera mirada**: HGB con 25 columnas, AUC 0,769, PR-AUC 0,691, lift 1,80 en el 10 %. No supera a RFM (diferencia −0,014, IC [−0,033; 0,005]). [Verificado]
- **SHAP**: corre con `shap` 0,51.0; aditivo con el país en one-hot (error 8·10⁻¹⁵); 1 s para 1.677 filas, 9 s para 15.297; memoria de pico 0,8 MB. [Verificado]
- **Calidad de datos**: 22,5 % de las líneas sin cliente (15 % del importe); 1,8 % de líneas "C" (7,1 % del importe); casi todos los códigos no estándar son servicio; precio máximo de 38.970 es un ajuste manual. [Verificado]
- **Contradicciones con el sitio**: LightGBM, recencia como variable principal, "minorista del Reino Unido", automatización mensual sobre un archivo estático, costos. [Verificado]
- **Preguntas abiertas**: N y M, estacionalidad, costos de la oferta, librería de BG/NBD, LightGBM frente a scikit-learn, SHAP en el landing, celdas pequeñas, `PADS`, simulación mensual, conciliación de anulaciones con el proyecto 02. Ver la sección anterior.

---

## Salidas guardadas

Todas están fuera del repositorio:

- Copias de solo lectura de los archivos de UCI: `<temp>\raw\` (`online_retail_II.xlsx`, `online_retail_ii.zip`).
- Datos de trabajo: `...\tmp.4G0E3y6lZg\out\raw.parquet`, `base.parquet`, `train_rows.pkl`, `val_rows.pkl`, `shap_val.npy`, `s03_purchase_days_pre_test.csv`, `s03_churn_by_N_M.csv`.
- Scripts: `...\tmp.4G0E3y6lZg\scripts\` (`common.py`, `s01_load.py`, `s02_profile.py`, `s03_churn_window.py`, `s04_first_look.py`, `s05_shap.py`, `s06_extra_profile.py`, `s07_bootstrap.py`; diagnósticos `s04b`, `s04c`, `s05b`, `s05c`).
- Salidas de texto: `...\tmp.4G0E3y6lZg\out\s02_profile.out`, `s03_churn_window.out`, `s04_first_look.out`, `s05_shap.out`, `s06_extra_profile.out`, `s07_bootstrap.out`.
- Entorno: `...\tmp.4G0E3y6lZg\venv\` (Python 3.11.1, con las versiones de la sección de librerías).
