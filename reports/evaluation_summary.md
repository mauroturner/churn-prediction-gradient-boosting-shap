## Resultados

Criterios fijados antes de construir, evaluados una vez sobre la prueba.

| Criterio | Umbral | Valor | Cumple | Veredicto |
| --- | --- | ---: | --- | --- |
| C01 Discriminación frente a RFM | AUC(modelo) > AUC(B2) | 0,745 | no | El modelo no supera a RFM en AUC: 0,745 frente a 0,746. |
| C02 Mejora fuera del ruido frente a RFM | límite inferior del intervalo del 95 % de AUC(modelo) − AUC(B2) > 0 | −0,002 | no | El modelo no supera a RFM fuera del ruido: la diferencia de AUC es −0,00, con un intervalo del 95 % de −0,01 a 0,01. |
| C03 Mejora fuera del ruido frente a la base más fuerte | límite inferior del intervalo del 95 % de AUC(modelo) − AUC(B*) > 0 | −0,004 | no | El modelo no supera a la base más fuerte fuera del ruido: la diferencia de AUC es −0,00, con un intervalo del 95 % de −0,02 a 0,01. |
| C04 Captura en el 10 % superior | bajas en el 10 % de mayor riesgo del modelo > las del 10 % de B* | 253,000 | no | En el 10 % de mayor riesgo, el modelo no capta más bajas que la base más fuerte: 253 frente a 268. |
| C05 Beneficio neto frente a la base más fuerte | BN(modelo, t*) > BN(B*, t*_B*) | 209,657 | no | Con los costos supuestos, el modelo no deja más beneficio neto que la base más fuerte con su propio umbral: 209,7 u. frente a 238,9 u. por cada 1.000 clientes. |
| C06 Conviene actuar con el modelo | BN(modelo, t*) > máx(BN(contactar a todos), 0) | 209,657 | sí | El modelo supera a contactar a todos y a no contactar a nadie: 209,7 u. por cada 1.000 clientes frente a 0,0. |
| C07 Calibración en la prueba | ECE ≤ 0,03 y |sesgo| ≤ 0,02 | 0,089 | no | La calibración en la prueba no cumple: ECE 0,089 y sesgo 0,088. |
| C08 Brier frente a la base más fuerte | Brier(modelo) < Brier(B*) | 0,198 | sí | El Brier del modelo es menor que el de la base más fuerte: 0,1976 frente a 0,2030. |
| C09 Sensibilidad a los costos | BN(modelo) ≥ BN(B*) en cada punto de equilibrio de 0,10 a 0,90 | 9,000 | no | El modelo no deja al menos el beneficio de la base más fuerte en cada punto de equilibrio: en 9 de los 17 de 0,10 a 0,90. |
| C10 Por corte y sensibilidades (informativo) | sin umbral: que esté escrito y sea consistente | sin dato | informativo | Por corte de prueba: 2011-08-01: AUC 0,744, tasa de bajas 0,366, diferencia con B2 −0,00 y con B* −0,00; 2011-09-01: AUC 0,746, tasa de bajas 0,321, diferencia con B2 −0,00 y con B* −0,01. Sensibilidades: N = 60 días (2011-08-01, 2011-09-01): AUC del modelo 0,737, de RFM 0,729 y de B* 0,744, intervalo de la diferencia con B* de −0,02 a 0,00; N = 120 días (2011-08-01): AUC del modelo 0,756, de RFM 0,766 y de B* 0,754, intervalo de la diferencia con B* de −0,02 a 0,02; M = 180 días (2011-08-01, 2011-09-01): AUC del modelo 0,750, de RFM 0,766 y de B* 0,760, intervalo de la diferencia con B* de −0,02 a −0,00; sin el corte de diciembre en el entrenamiento (2011-08-01, 2011-09-01): AUC del modelo 0,744, de RFM 0,746 y de B* 0,749, intervalo de la diferencia con B* de −0,02 a 0,01. |

Estado: sealed. Corrida 20261112T182457477294Z del 2011-12-09.
