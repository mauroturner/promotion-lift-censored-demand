# Ficha del modelo: qué promociones venden de verdad

Esta ficha describe lo que el flujo estima, con qué datos, cómo se eligió y se midió, y lo que no se puede decir con él. Las cifras de las tablas salen de `reports/evaluation_summary.json`, de `reports/model_seal.json` y de los cinco archivos de `outputs/site/` (la corrida `20261118T083929959268Z`, del 2024-07-03 00:00:00); ninguna se escribió a mano. La documentación se escribió antes de la evaluación independiente y de sus correcciones, y se sincroniza otra vez después de la última (plan, sección 28).

## Uso previsto y no previsto

**Uso previsto.** Un ranking descriptivo de qué celdas de promoción (un grupo de gestión por una de siete bandas de descuento) vendieron más que lo que sus propias series habrían vendido sin promoción, en el período de los datos, con un intervalo del 95 % y con los grupos indistinguibles marcados. Es para el equipo comercial y el de categoría: decidir qué descuento repetir, y ver cuánta demanda esconden las horas sin stock de los días con promoción. La recuperación de la demanda de esas horas es una cota inferior de lo escondido, no una corrección exacta.

**Uso no previsto.** Prometer el aumento de una promoción futura: el orden de las celdas se repite de un período al siguiente (C05, C07) y el tamaño de cada aumento no (C06). Leer un aumento como causal: es una asociación dentro de la serie, ajustada por la hora y por el día de su grupo, y no es causal; no se sabe si la promoción se lanzó porque se esperaba más demanda. Hablar de ingreso, margen o unidades: no hay precio y la venta está normalizada. Identificar una promoción individual: no hay identificador y la unidad es la celda. Usar el pronóstico como producto: solo mide si el aumento de la celda agrega información (C08, C09).

## Datos

FreshRetailNet-50K (Dingdong-Inc, Hugging Face, CC BY 4.0, commit `c374e859`; Wang et al. (2026), arXiv:2505.16319): 50.000 series tienda × producto de 898 tiendas, 18 ciudades y 865 productos, 97 días (2024-03-28 a 2024-07-02), con 24 valores horarios de venta normalizada (sin unidades) y de estado del stock por serie-día. El análisis cubre las horas de 06 a 21; la noche trae el 4,8 % de la venta y no se recupera. No hay precio, canal ni identificador de promoción.

| Bloque | Días | Fechas | Para qué |
| --- | ---: | --- | --- |
| Entrenamiento | 65 | 2024-03-28 a 2024-05-31 | Ajustar R1-R3 y la réplica |
| Purga | 7 | 2024-06-01 a 2024-06-07 | Ninguno |
| Validación V1 | 9 | 2024-06-08 a 2024-06-16 | Elegir el método y κ |
| Validación V2 | 9 | 2024-06-17 a 2024-06-25 | Vista previa de la recuperación; no elige nada |
| Prueba | 7 | 2024-06-26 a 2024-07-02 | `eval.parquet`; se evalúa una vez, con lo sellado |

Cada cifra de validación dice con qué bloques se ajustó su método (columna «Se ajustó con» de las tablas, o la nota que la acompaña); ninguna cifra de un bloque sale de un método que se ajustó con ese mismo bloque (D21). El lanzamiento reajusta con los 90 días hasta 06-25 (`train+purge+valid_v1+valid_v2`), y las cifras de la prueba son de ese método.

## Estados del día y control

Cada serie-día tiene un estado (D04): `promo` (marca de promoción con descuento válido), `regular` (sin marca y sin rebaja, descuento de al menos 0,999: el control), `unflagged_cut` (descuento sin marca, que se mide aparte) o `anomalous` (descuento 0 o mayor que 1, que se cuenta y se aparta). Sobre las 4.500.000 series-días del entrenamiento y el reajuste (`train.parquet`, 50.000 series × 90 días):

| Estado | Series-días | Parte |
| --- | ---: | ---: |
| `promo` | 1.702.772 | 37,84 % |
| `regular` | 2.146.092 | 47,69 % |
| `unflagged_cut` | 635.063 | 14,11 % |
| `anomalous` | 16.073 | 0,36 % |

El control es un día sin marca y sin rebaja: con cualquier día sin marca como control, el aumento baja (D04), porque esos días incluyen descuentos que venden más. La banda de descuento de un día `promo` o `unflagged_cut` es una de siete: de más del 50 % (el descuento entre 0 y 0,5), 40 a 50 %, 30 a 40 %, 20 a 30 %, 10 a 20 %, 5 a 10 % y hasta 5 %; un valor a menos de 10⁻⁶ por debajo de un borde cuenta como el borde (D13).

## Recuperación y su validación sintética

Cuatro métodos (D06): R0 cero, R1 la media de las horas con stock de la serie, la hora y el estado, R2 R1 escalada por el nivel observado del mismo día con contracción κ y R3 un `HistGradientBoostingRegressor` con pérdida de Poisson. La validación oculta la cola del día en series-días con stock todo el día, donde la venta oculta es la verdad, y se juzga por el WAPE de la masa oculta sumada por serie (D07), porque a nivel de la hora ningún método supera a predecir cero. La elección se hizo en V1 con los métodos ajustados con el entrenamiento: R2 con κ = 0,25, el borde de la grilla (D08).

| Bloque | Método | Se ajustó con | WAPE por serie | Sesgo | Elegido |
| --- | --- | --- | ---: | ---: | --- |
| V1 | R0 (cero) | `train` | 100,0 % | −100,0 % |  |
| V1 | R1 (la media simple) | `train` | 38,1 % | 13,5 % |  |
| V1 | R2 con κ = 0,25 | `train` | 32,4 % | 9,7 % | sí |
| V1 | R2 con κ = 0,50 | `train` | 32,9 % | 10,6 % |  |
| V1 | R2 con κ = 1,00 | `train` | 34,2 % | 11,5 % |  |
| V1 | R2 con κ = 2,00 | `train` | 35,5 % | 12,3 % |  |
| V1 | R3 (gradient boosting) | `train` | 34,0 % | 4,4 % |  |
| V2 | R0 (cero) | `train` | 100,0 % | −100,0 % |  |
| V2 | R1 (la media simple) | `train` | 37,5 % | 2,3 % |  |
| V2 | R2 con κ = 0,25 | `train` | 31,6 % | 0,7 % | sí |
| V2 | R2 con κ = 0,50 | `train` | 32,1 % | 1,0 % |  |
| V2 | R2 con κ = 1,00 | `train` | 33,4 % | 1,4 % |  |
| V2 | R2 con κ = 2,00 | `train` | 34,8 % | 1,8 % |  |
| V2 | R3 (gradient boosting) | `train` | 35,2 % | −8,7 % |  |
| Prueba | R0 (cero) | `train+purge+valid_v1+valid_v2` | 100,0 % | −100,0 % |  |
| Prueba | R1 (la media simple) | `train+purge+valid_v1+valid_v2` | 35,6 % | −0,2 % |  |
| Prueba | R2 con κ = 0,25 | `train+purge+valid_v1+valid_v2` | 31,1 % | −0,2 % | sí |
| Prueba | R3 (gradient boosting) | `train+purge+valid_v1+valid_v2` | 33,0 % | −13,0 % |  |

**Lo que la simulación no puede validar.** Los quiebres reales llegan en los días de más demanda, y las series-días con stock todo el día, que son las que se pueden ocultar, no representan esa selección: la censura real que depende de la demanda no se reproduce en la validación. En el accesorio sintético, que sí la planta, la recuperación con R2 queda por debajo del aumento verdadero (cierra el 81 % de la distancia entre el crudo y la verdad; D34): el aumento recuperado es una cota inferior. La demostración de la fuga (`fact_leakage`) muestra que una recuperación que lee `sale_amount` da un WAPE por serie de 0,0 % frente a 31,6 % del método elegido: parece casi perfecta porque el total ya incluye la venta oculta, y no serviría en un quiebre real.

## Contrafactual

La venta esperada de una serie-día con promoción es `a(serie, hora) · b(grupo, día)`, ajustada por IPF (30 iteraciones) solo sobre los días `regular`, en dos versiones: venta cruda y demanda recuperada (D09, D10). El aumento es la suma observada sobre la suma del contrafactual menos 1, sobre las horas de 06 a 21. Una serie sin ningún día `regular` no tiene contrafactual y queda fuera del efecto. Con los 90 días, el aumento total sellado es de +52,0 % crudo [49,7; 54,8] y +52,9 % recuperado [51,2; 54,9], sobre 39.661 series y 1.529.251 series-días; la cuenta ingenua, que compara los días con promoción con los demás mezclando series, da +20,6 %. En la semana de prueba, +46,5 % crudo [41,0; 52,3] y +47,9 % recuperado [44,1; 51,2], sobre 103.629 series-días con promoción.

El nivel depende de la ventana con que se ajusta `a`: sobre las mismas series-días, el aumento crudo es +56,52 % con el ajuste del entrenamiento y +47,86 % con el de los 90 días, unas tres veces su semiancho (D09). El modelo no tiene tendencia por serie. El aumento no es causal: es una asociación dentro de la serie.

Aumento por banda, sobre los 90 días (series de la banda; versiones cruda y recuperada; intervalo de dos vías de la recuperada):

| Banda | Series | Crudo | Recuperado | Intervalo |
| --- | ---: | ---: | ---: | --- |
| más del 50 % | 2.183 | 162,1 % | 100,2 % | [92,6 %; 110,6 %] |
| 40 a 50 % | 6.567 | 171,3 % | 139,6 % | [124,0 %; 156,3 %] |
| 30 a 40 % | 12.333 | 71,6 % | 69,9 % | [65,6 %; 74,0 %] |
| 20 a 30 % | 23.212 | 55,8 % | 55,5 % | [52,9 %; 58,6 %] |
| 10 a 20 % | 34.039 | 38,1 % | 42,9 % | [41,0 %; 45,0 %] |
| 5 a 10 % | 20.678 | 26,8 % | 30,9 % | [28,4 %; 33,5 %] |
| hasta 5 % | 16.152 | 14,6 % | 13,3 % | [10,9 %; 16,0 %] |

Aumento por día de la semana de prueba (emitido con el método sellado, un día a la vez):

| Día | Series-días con promoción | Crudo | Recuperado | Tasa de quiebre |
| --- | ---: | ---: | ---: | ---: |
| 2024-06-26 | 15.168 | 33,5 % | 40,8 % | 17,2 % |
| 2024-06-27 | 15.384 | 52,1 % | 50,7 % | 15,6 % |
| 2024-06-28 | 14.958 | 56,3 % | 55,4 % | 13,3 % |
| 2024-06-29 | 15.861 | 48,7 % | 51,9 % | 15,5 % |
| 2024-06-30 | 14.735 | 40,5 % | 45,7 % | 23,0 % |
| 2024-07-01 | 14.101 | 41,1 % | 40,8 % | 20,7 % |
| 2024-07-02 | 13.422 | 56,5 % | 50,6 % | 21,4 % |

## Intervalos

Remuestreo de dos vías (D12): pesos de series enteras y de días enteros, con el contrafactual fijo, 500 remuestras, semilla 0, percentiles 2,5 y 97,5; la semana de prueba usa la semilla más uno (D41). Es 1,70 veces más ancho que el de solo series (ancho mediano de 24,1 % frente a 14,2 % en las celdas ordenadas) y se pisan 183 de 903 pares de celdas (106 con solo series). Ni el de dos vías cubre la sensibilidad a la ventana de ajuste de `a` (unos 8 puntos): por eso el nivel de un aumento se publica como la descripción de un período.

## Ranking

Las celdas con al menos 30 series (grupo × banda) se ordenan por su aumento recuperado y se reparten en grupos indistinguibles: dos celdas cuyos intervalos se pisan comparten grupo (D13). Con los 90 días, 7 grupos de gestión y siete bandas dan 49 celdas, 47 con series-días y 43 ordenadas, en 5 grupos indistinguibles. La semana de prueba repite el orden (C05: Spearman 0,897 sobre 36 celdas, las que tienen 30 series en los dos períodos) y no el nivel (C06: el intervalo de la diferencia contiene 0 en el 58,3 % de las celdas).

## Criterios y resultados

Diez criterios fijados antes de construir (`docs/requirements.md`, sección 8.1; D16), con lo que se esperaba dicho antes de medir: que C06 y C09 probablemente no se cumplirían. Las dos últimas columnas dicen qué se había visto antes de fijarlos. Los veredictos están tal como los escribe el flujo.

| Criterio | Umbral | Valor | Cumple | Veredicto | Visto por la investigación | Visto por el planificador |
| --- | --- | ---: | --- | --- | --- | --- |
| La recuperación supera a la media simple | límite superior del intervalo del 95 % de WAPE por serie (recuperación) − WAPE por serie (R1) < 0, en la máscara de cola de la prueba | 0,311 | sí | La recuperación (R2 con κ = 0,25) supera a la media simple (R1) en la máscara de cola de la prueba: WAPE por serie 31,1 % frente a 35,6 %; la diferencia va de −4,69 a −4,25 puntos. | no | sí |
| La masa recuperada no tiene sesgo grande | \|sesgo de la recuperación\| ≤ 0,10 en la máscara de cola de la prueba | −0,002 | sí | El sesgo de la masa recuperada cumple: la recuperación estima 0,2 % de menos y se pedía a lo sumo 10,0 %. | no | sí |
| La recuperación no cambia el aumento | \|(1 + sesgo en días con promoción) / (1 + sesgo en días regulares) − 1\| ≤ 0,05 en la máscara de cola de la prueba | −0,038 | sí | La recuperación no cambia el aumento: el sesgo en días con promoción frente al de los días regulares lo mueve 3,8 %, y se pedía a lo sumo 5,0 %. | no | en parte |
| Los quiebres esconden parte del efecto | límite inferior del intervalo del 95 % del aumento total recuperado − el crudo, en la prueba, > 0 | 0,479 | no | Los quiebres no esconden parte del efecto: el aumento total con la demanda recuperada es 47,9 % frente a 46,5 % con la venta cruda; la diferencia va de −1,81 a 4,36 puntos. | sí | sí |
| El orden de las celdas se repite | correlación de Spearman entre los aumentos sellados y los de la prueba, en las celdas con series suficientes en las dos, ≥ 0,80 | 0,897 | sí | El orden de las celdas se repite en la semana de prueba: correlación de Spearman 0,897 entre el aumento sellado y el de la prueba, sobre 36 celdas, y se pedía al menos 0,80. | no | sí |
| El nivel de cada celda se repite | proporción de esas celdas cuyo intervalo de la diferencia prueba − sellado contiene 0 ≥ 0,80 | 0,583 | no | El nivel de cada celda no se repite: el intervalo de la diferencia prueba − sellado contiene 0 en el 58,3 % de 36 celdas, y se pedía al menos 80,0 %. | no | sí |
| Más descuento, más aumento | correlación de Spearman entre la profundidad de la banda y su aumento en la prueba ≥ 0,90 | 1,000 | sí | Más descuento, más aumento: correlación de Spearman 1,000 entre la profundidad de la banda y su aumento en la prueba, y se pedía al menos 0,90. | sí | sí |
| El aumento de la celda mejora el pronóstico | límite superior del intervalo del 95 % de WAPE(F2) − WAPE(F2a) < 0, en las series-días con promoción de la prueba | 0,403 | sí | El aumento de la celda mejora el pronóstico frente a un aumento único (F2a): WAPE de F2 40,3 % frente a 43,9 % de F2a; la diferencia va de −4,07 a −3,19 puntos. | no | sí |
| El pronóstico con el aumento supera a la regla ingenua | límite superior del intervalo del 95 % de WAPE(F2) − WAPE(F1) < 0, en las mismas series-días | 0,403 | no | El pronóstico con el aumento de la celda no supera a la regla ingenua (F1), la media de los días anteriores de la propia serie: WAPE de F2 40,3 % frente a 35,0 % de F1; la diferencia va de 1,92 a 8,32 puntos. | no | sí |
| Variantes y seguimiento (informativo) | sin umbral: que esté escrito y sea consistente | sin dato | informativo | Informativo, sin umbral: se escribieron 257 cifras de variantes y el seguimiento de 7 días de la prueba. | en parte | sí, en el entrenamiento y la validación |

De los nueve criterios con umbral, seis se cumplen y tres no (C04, C06 y C09). Por criterio:

- **C01 se cumple:** la recuperación (R2 con κ = 0,25) tiene un WAPE por serie de 31,1 % frente a 35,6 % de la media simple (R1); la diferencia va de −4,69 a −4,25 puntos.
- **C02 y C03 se cumplen:** el sesgo es de −0,2 % y la recuperación mueve el aumento 3,8 % (sesgo de −2,5 % en días con promoción y de +1,4 % en días regulares).
- **C04 no se cumple, y se esperaba que sí:** el aumento total recuperado es +47,9 % y el crudo +46,5 %; la diferencia es de +1,37 puntos y va de −1,81 a +4,36, así que el límite inferior no pasa de 0. El planificador midió +4,20 puntos en el entrenamiento ([+2,73; +5,76]); con los 90 días del lanzamiento la diferencia es de +0,9 puntos.
- **C05 y C07 se cumplen:** Spearman 0,897 entre los aumentos sellados y los de la prueba, y 1,000 entre la profundidad de la banda y su aumento.
- **C06 no se cumple (esperado):** el 58,3 % de las 36 celdas mantiene su nivel y se pedía el 80 %.
- **C08 se cumple:** el aumento de la celda mejora el pronóstico frente a un aumento único (F2 40,3 % frente a 43,9 % de F2a); la diferencia va de −4,07 a −3,19 puntos.
- **C09 no supera (esperado):** el pronóstico con el aumento de la celda no supera a la regla ingenua (F2 40,3 % frente a 35,0 % de F1); la diferencia va de +1,92 a +8,32 puntos.
- **C10 es informativo:** 257 cifras de variantes y el seguimiento de 7 días.

Pronósticos de las horas con stock de las series-días con promoción (WAPE de la masa por serie-día; la prueba usa lo sellado con los 90 días y la validación lo ajustado con el entrenamiento):

| Pronóstico | WAPE de la prueba | Sesgo de la prueba | WAPE de la validación | Sesgo de la validación | Validación, se ajustó con |
| --- | ---: | ---: | ---: | ---: | --- |
| F0, el contrafactual sin aumento | 44,9 % | −32,1 % | 48,4 % | −37,7 % | `train` |
| F1, la media de los 7 días anteriores de la serie | 35,0 % | −18,8 % | 35,6 % | −20,3 % | `train` |
| F2a, un solo aumento total | 43,9 % | 3,8 % | 45,3 % | −0,3 % | `train` |
| F2, el aumento de la celda | 40,3 % | −0,8 % | 43,1 % | 3,0 % | `train` |

Réplica del entrenamiento en la validación (18 días, `fit_blocks = train`, 40 celdas con 30 series en los dos): Spearman 0,934 y el 55,0 % de las celdas con el nivel consistente (el 42,5 % de la comprobación del planificador, antes de corregir `day_factor`; D09); el 20,0 % de los aumentos de la validación cae dentro del intervalo del entrenamiento.

## Limitaciones

- **Un operador, 18 ciudades de un país, 97 días y venta normalizada.** Un solo comercio, sin estacionalidad anual (97 días no la contienen), sin unidades, precio ni margen.
- **No hay identificador de promoción.** La marca y el descuento no coinciden en el 14,11 % de las series-días y la unidad es la celda de grupo y banda.
- **La zona horaria es un supuesto.** La tarjeta no la declara; los picos de venta a las 9 y 16 h apuntan a hora local (D05). Un día se conoce completo al cerrar, también un supuesto.
- **La censura real depende de la demanda** y la validación sintética no la reproduce (ver «Recuperación y su validación sintética»): el aumento recuperado es una cota inferior.
- **El aumento es una asociación, no es causal**, y su nivel depende de la ventana de ajuste.
- **La semana de prueba es una sola semana:** 7 días, 103.629 series-días con promoción y 36 celdas comparables; C06 y C09 se midieron una vez.
- **La cifra del artículo** (1,43 veces de mediana por serie) usa otra definición y no se compara con la de este proyecto (D37).
- **El tiempo de la corrida diaria no se cumple (RNF02, abierto).** Las siete corridas diarias tardan de 62 a 68 s y el límite es 60 s; su prueba, `tests/e2e/test_real.py::test_every_daily_run_takes_at_most_the_required_seconds`, está en rojo a propósito. Es un requerimiento no cumplido que se corrige después de la evaluación independiente.
- **Sin evaluación independiente todavía, y sin `.pbix`.** La evaluación independiente, las correcciones de las advertencias de las revisiones (`docs/review-advisories.md`) y el `.pbix` están pendientes.

## Tiempos y memoria

Medidos en la repetición real completa (una sola, `replay`, en un solo proceso, con el equipo de desarrollo; D29, D39):

| Qué | Tiempo | Requerimiento | Se cumple |
| --- | ---: | --- | --- |
| Repetición completa con la corrida sin entrega | 876 s (14,6 min) | ≤ 20 min | sí |
| Lanzamiento | 310 s | ≤ 12 min | sí |
| Corridas diarias (siete) | de 62 a 68 s | ≤ 60 s (RNF02) | **no** |
| Cierre, con la primera evaluación de la prueba | 120 s | sin límite propio | |
| Corrida sin entrega | 1 s | | |

En las corridas diarias, la carga (de 24,6 a 26,3 s) y la exportación (de 31,2 a 35,6 s) suman unos 57 de los 62 a 68 s: reconstruyen todo en cada entrega. La corrección se mide sobre una copia de `data/` y va después de la evaluación independiente.

Memoria, con su contador: el pico del conjunto de trabajo de la repetición completa es de 4.077,9 MB de `PeakWorkingSetSize` (`GetProcessMemoryInfo`; el límite de RNF03 es 12 GB de ese contador), y `PeakPagefileUsage`, informativo, de 5.808,7 MB. El pico es el del proceso hasta ese momento y no baja, así que es el mismo en las nueve corridas; lo alcanzó la primera. En la corrida en seco de U09, 90 vistas vivas de un archivo mapeado en memoria habían llevado `PeakWorkingSetSize` a 20,9 GB, y copiar cada día al leerlo lo bajó a 4,3 GB (D22).

## La suite rápida

La suite por defecto (`pytest -m "not real_data and not docker"`) recoge 838 pruebas. La suite rápida tardó 127,05 s y 126,10 s (dos corridas en reposo) en el equipo de desarrollo, con un límite de 180 s y un presupuesto de trabajo de 150 s (D29; el dueño subió el límite de 120 s a 180 s el 2026-11-18). Una sesión completa que pasa el límite sale con falla y dice por cuánto. Las pruebas con los Parquet reales (`-m real_data`) y con Docker (`-m docker`) están fuera de la selección por defecto: la prueba de tiempo de la corrida diaria es de las primeras y está en rojo (RNF02).
