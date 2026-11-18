## Resultados

Criterios fijados antes de construir, evaluados una vez sobre la prueba.

| Criterio | Umbral | Valor | Cumple | Veredicto |
| --- | --- | ---: | --- | --- |
| C01 La recuperación supera a la media simple | límite superior del intervalo del 95 % de WAPE por serie (recuperación) − WAPE por serie (R1) < 0, en la máscara de cola de la prueba | 0,311 | sí | La recuperación (R2 con κ = 0,25) supera a la media simple (R1) en la máscara de cola de la prueba: WAPE por serie 31,1 % frente a 35,6 %; la diferencia va de −4,69 a −4,25 puntos. |
| C02 La masa recuperada no tiene sesgo grande | \|sesgo de la recuperación\| ≤ 0,10 en la máscara de cola de la prueba | −0,002 | sí | El sesgo de la masa recuperada cumple: la recuperación estima 0,2 % de menos y se pedía a lo sumo 10,0 %. |
| C03 La recuperación no cambia el aumento | \|(1 + sesgo en días con promoción) / (1 + sesgo en días regulares) − 1\| ≤ 0,05 en la máscara de cola de la prueba | −0,038 | sí | La recuperación no cambia el aumento: el sesgo en días con promoción frente al de los días regulares lo mueve 3,8 %, y se pedía a lo sumo 5,0 %. |
| C04 Los quiebres esconden parte del efecto | límite inferior del intervalo del 95 % del aumento total recuperado − el crudo, en la prueba, > 0 | 0,479 | no | Los quiebres no esconden parte del efecto: el aumento total con la demanda recuperada es 47,9 % frente a 46,5 % con la venta cruda; la diferencia va de −1,81 a 4,36 puntos. |
| C05 El orden de las celdas se repite | correlación de Spearman entre los aumentos sellados y los de la prueba, en las celdas con series suficientes en las dos, ≥ 0,80 | 0,897 | sí | El orden de las celdas se repite en la semana de prueba: correlación de Spearman 0,897 entre el aumento sellado y el de la prueba, sobre 36 celdas, y se pedía al menos 0,80. |
| C06 El nivel de cada celda se repite | proporción de esas celdas cuyo intervalo de la diferencia prueba − sellado contiene 0 ≥ 0,80 | 0,583 | no | El nivel de cada celda no se repite: el intervalo de la diferencia prueba − sellado contiene 0 en el 58,3 % de 36 celdas, y se pedía al menos 80,0 %. |
| C07 Más descuento, más aumento | correlación de Spearman entre la profundidad de la banda y su aumento en la prueba ≥ 0,90 | 1,000 | sí | Más descuento, más aumento: correlación de Spearman 1,000 entre la profundidad de la banda y su aumento en la prueba, y se pedía al menos 0,90. |
| C08 El aumento de la celda mejora el pronóstico | límite superior del intervalo del 95 % de WAPE(F2) − WAPE(F2a) < 0, en las series-días con promoción de la prueba | 0,403 | sí | El aumento de la celda mejora el pronóstico frente a un aumento único (F2a): WAPE de F2 40,3 % frente a 43,9 % de F2a; la diferencia va de −4,07 a −3,19 puntos. |
| C09 El pronóstico con el aumento supera a la regla ingenua | límite superior del intervalo del 95 % de WAPE(F2) − WAPE(F1) < 0, en las mismas series-días | 0,403 | no | El pronóstico con el aumento de la celda no supera a la regla ingenua (F1), la media de los días anteriores de la propia serie: WAPE de F2 40,3 % frente a 35,0 % de F1; la diferencia va de 1,92 a 8,32 puntos. |
| C10 Variantes y seguimiento (informativo) | sin umbral: que esté escrito y sea consistente | sin dato | informativo | Informativo, sin umbral: se escribieron 257 cifras de variantes y el seguimiento de 7 días de la prueba. |

Validación (V2, no la prueba; métodos ajustados con train): recuperación sobre la máscara de cola.

| Método | WAPE por serie | Sesgo |
| --- | ---: | ---: |
| R0 (cero) | 100,0 % | −100,0 % |
| R1 (la media simple) | 37,5 % | 2,3 % |
| R2 con κ = 0,25 | 31,6 % | 0,7 % |
| R2 con κ = 0,50 | 32,1 % | 1,0 % |
| R2 con κ = 1,00 | 33,4 % | 1,4 % |
| R2 con κ = 2,00 | 34,8 % | 1,8 % |
| R3 (gradient boosting) | 35,2 % | −8,7 % |

Estado: sealed. Corrida 20261118T083929959268Z del 2024-07-03 00:00:00.
