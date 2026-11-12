# Reporte de validación

- Corrida: `20261112T182457477294Z`
- Resultado: **Aceptado: ninguna regla bloqueante falla.**
- SHA-256 del zip: `572e36277c2390fbfde10664750731e0a86f55e33470d91919085f0408e67bfb`
- Entrega: C2011-12; filas de la entrega: 25526

## Reglas

| ID | Regla | Severidad | Agregación | Estado | Filas | Clientes | Valor (£) |
| --- | --- | --- | --- | --- | ---: | ---: | ---: |
| V01 | El zip tiene la huella aceptada (o la registrada, en modo local) | bloqueante | source | pasa | 0 | 0 | 0,00 |
| V02 | Descarga segura: HTTPS en cada salto, host permitido y topes de redirecciones, bytes y segundos | bloqueante | source | pasa | 0 | 0 | 0,00 |
| V03 | El zip tiene exactamente el miembro esperado, sin rutas, dentro del tope y con su huella | bloqueante | source | pasa | 0 | 0 | 0,00 |
| V04 | El libro tiene las hojas configuradas y en cada una las 8 columnas exactas, en orden | bloqueante | source | pasa | 0 | 0 | 0,00 |
| V05 | Cada columna tiene su tipo: cantidad entera, precio numérico, fecha y hora, factura y código no vacíos, cliente de 5 cifras o vacío | bloqueante | source | pasa | 0 | 0 | 0,00 |
| V06 | El solapamiento entre las hojas es el mismo conjunto de filas | bloqueante | source | pasa | 0 | 0 | 0,00 |
| V10 | La entrega es la siguiente del plan y su período empieza el día siguiente al fin de la anterior | bloqueante | per_run | pasa | 0 | 0 | 0,00 |
| V11 | La fecha de cada factura está dentro del período de la entrega | bloqueante | per_run | pasa | 0 | 0 | 0,00 |
| V12 | Ninguna línea de la entrega está ya en el almacén ni repetida dentro de ella | bloqueante | per_run | pasa | 0 | 0 | 0,00 |
| V13 | Cada factura tiene un solo cliente y un solo país, también contra lo ya cargado | bloqueante | per_run | pasa | 0 | 0 | 0,00 |
| V14 | La entrega no está vacía y sus filas y su SHA-256 son los del manifiesto | bloqueante | per_run | pasa | 0 | 0 | 0,00 |
| V20 | Línea sin cliente (se aparta) | advertencia | per_run | advierte | 7864 | 0 | 150 038,15 |
| V21 | Anulación con cliente y producto (se descuenta de la compra que anula) | advertencia | per_run | advierte | 347 | 130 | 174 111,46 |
| V22 | Anulación, o resto de una, sin compra que anular con lo conocido en la fecha (se descarta y se cuenta) | advertencia | latest | advierte | 1706 | 625 | 34 199,09 |
| V23 | Cantidad con el signo contrario al de su factura: cero o negativa sin «C», positiva con «C» (se aparta) | advertencia | per_run | pasa | 0 | 0 | 0,00 |
| V24 | Precio cero o negativo (se aparta) | advertencia | per_run | pasa | 0 | 0 | 0,00 |
| V25 | Código de servicio: envío, comisiones, ajustes, muestras, pruebas, PADS (se aparta) | advertencia | per_run | advierte | 73 | 61 | 6 555,31 |
| V26 | Vale de regalo (se aparta) | advertencia | per_run | pasa | 0 | 0 | 0,00 |
| V27 | Factura «A» de ajuste de deuda incobrable (se aparta) | advertencia | per_run | pasa | 0 | 0 | 0,00 |
| V28 | Línea idéntica a otra anterior de su hoja (se conserva y se marca) | advertencia | per_run | advierte | 279 | 83 | 1 037,75 |
| V29 | Cantidad de 5.000 unidades o más en una línea (se conserva y se marca) | advertencia | per_run | advierte | 1 | 1 | 168 469,60 |
| V30 | Cliente con más de un país (se usa el de su última línea anterior al corte y se marca) | advertencia | per_run | pasa | 0 | 0 | 0,00 |
| V31 | País «Unspecified» (va a «Otros» y se marca) | advertencia | per_run | pasa | 0 | 0 | 0,00 |
| M03 | El artefacto del modelo tiene la huella registrada, antes de deserializarlo | bloqueante | per_run | pasa | 0 | 0 | 0,00 |
| M05 | La configuración es la sellada (si no, todo lo calculado es posterior al sello) | advertencia | latest | pasa | 0 | 0 | 0,00 |
| M07 | Ningún bloque usado (entrenamiento, V1, V2, prueba) tiene una sola clase | bloqueante | latest | pasa | 0 | 0 | 0,00 |
| M08 | El ajuste de BG/NBD converge | bloqueante | latest | pasa | 0 | 0 | 0,00 |
| I01 | Clientes nuevos en la entrega | informativa | per_run | pasa | 653 | 28 | 24 114,05 |
| I02 | Líneas e importe de invitados (sin cliente), en libras y en porcentaje de la entrega | informativa | per_run | pasa | 7864 | 0 | 120 599,89 |
| I03 | Copias del solapamiento entre hojas quitadas al leer la fuente | informativa | source | pasa | 22523 | 0 | 500 216,85 |

## Ejemplos

### V20: Línea sin cliente (se aparta)

- `{"line_id": 20516455, "stock_code": "22169", "quantity": -2, "price": 7.65, "invoice_date": "2011-12-01"}`
- `{"line_id": 20516457, "stock_code": "90197B", "quantity": 1, "price": 4.95, "invoice_date": "2011-12-01"}`
- `{"line_id": 20516458, "stock_code": "90179C", "quantity": 1, "price": 5.95, "invoice_date": "2011-12-01"}`
- `{"line_id": 20516459, "stock_code": "90179B", "quantity": 1, "price": 5.95, "invoice_date": "2011-12-01"}`
- `{"line_id": 20516460, "stock_code": "84347", "quantity": 3, "price": 2.55, "invoice_date": "2011-12-01"}`

### V21: Anulación con cliente y producto (se descuenta de la compra que anula)

- `{"line_id": 20516385, "stock_code": "23245", "quantity": -8, "price": 4.15, "invoice_date": "2011-12-01"}`
- `{"line_id": 20516386, "stock_code": "84947", "quantity": -1, "price": 1.25, "invoice_date": "2011-12-01"}`
- `{"line_id": 20516387, "stock_code": "23374", "quantity": -1, "price": 0.82, "invoice_date": "2011-12-01"}`
- `{"line_id": 20516388, "stock_code": "84945", "quantity": -2, "price": 0.85, "invoice_date": "2011-12-01"}`
- `{"line_id": 20516389, "stock_code": "23485", "quantity": -1, "price": 25.0, "invoice_date": "2011-12-01"}`

### V22: Anulación, o resto de una, sin compra que anular con lo conocido en la fecha (se descarta y se cuenta)

- `{"line_id": 10000179, "stock_code": "22087", "unmatched_units": 12, "value_gbp": 35.4}`
- `{"line_id": 10000180, "stock_code": "85206A", "unmatched_units": 6, "value_gbp": 9.9}`
- `{"line_id": 10000181, "stock_code": "21895", "unmatched_units": 4, "value_gbp": 17.0}`
- `{"line_id": 10000182, "stock_code": "21896", "unmatched_units": 6, "value_gbp": 12.6}`
- `{"line_id": 10000183, "stock_code": "22083", "unmatched_units": 12, "value_gbp": 35.4}`

### V25: Código de servicio: envío, comisiones, ajustes, muestras, pruebas, PADS (se aparta)

- `{"line_id": 20516444, "stock_code": "POST", "quantity": 3, "price": 18.0, "invoice_date": "2011-12-01"}`
- `{"line_id": 20516456, "stock_code": "D", "quantity": -1, "price": 28.68, "invoice_date": "2011-12-01"}`
- `{"line_id": 20516485, "stock_code": "C2", "quantity": 1, "price": 50.0, "invoice_date": "2011-12-01"}`
- `{"line_id": 20516549, "stock_code": "POST", "quantity": 3, "price": 18.0, "invoice_date": "2011-12-01"}`
- `{"line_id": 20517028, "stock_code": "M", "quantity": 1, "price": 10.0, "invoice_date": "2011-12-01"}`

### V28: Línea idéntica a otra anterior de su hoja (se conserva y se marca)

- `{"line_id": 20517069, "stock_code": "21871", "quantity": 1, "price": 1.65, "invoice_date": "2011-12-01"}`
- `{"line_id": 20517250, "stock_code": "20727", "quantity": 1, "price": 1.65, "invoice_date": "2011-12-01"}`
- `{"line_id": 20517252, "stock_code": "22327", "quantity": 1, "price": 2.95, "invoice_date": "2011-12-01"}`
- `{"line_id": 20517399, "stock_code": "84581", "quantity": 2, "price": 3.75, "invoice_date": "2011-12-01"}`
- `{"line_id": 20517425, "stock_code": "22138", "quantity": 2, "price": 4.95, "invoice_date": "2011-12-01"}`

### V29: Cantidad de 5.000 unidades o más en una línea (se conserva y se marca)

- `{"line_id": 20540422, "stock_code": "23843", "quantity": 80995, "price": 2.08, "invoice_date": "2011-12-09"}`

### I02: Líneas e importe de invitados (sin cliente), en libras y en porcentaje de la entrega

- `{"lines": 25526, "positive_value_gbp": 638810.68, "share_of_lines": 0.308078, "share_of_value": 0.188788}`

### I03: Copias del solapamiento entre hojas quitadas al leer la fuente

- `{"overlap_start": "2010-12-01", "overlap_end": "2010-12-09"}`
