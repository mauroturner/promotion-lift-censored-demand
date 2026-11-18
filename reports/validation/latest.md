# Reporte de validación

- Corrida: `20261118T104140428720Z`
- Resultado: **Aceptado: ninguna regla bloqueante falla.**
- SHA-256 de `train.parquet`: `6706832db892bbae4969c19d87e07975d2543d2ba7d7d4756360654785de5a3d`
- SHA-256 de `eval.parquet`: `1b118840664280c6b88bffc84c80ee1f54c05d911e354b7599e5da10995e960e`
- Entrega: C2024-07-03; series-días de la entrega: 0

## Reglas

| ID | Regla | Severidad | Agregación | Estado | Series-días | Horas |
| --- | --- | --- | --- | --- | ---: | ---: |
| V01 | Cada archivo existe y tiene el tamaño y la huella aceptados (o la registrada, en modo rápido) | bloqueante | source | pasa | 0 | 0 |
| V02 | Esquema exacto: las 19 columnas de la fuente, en orden y con su tipo | bloqueante | source | pasa | 0 | 0 |
| V03 | Archivo, filas y grupos de filas dentro de sus topes; metadatos de pyarrow leídos antes que los datos | bloqueante | source | pasa | 0 | 0 |
| V04 | Cada lista horaria con 24 valores, sin nulos ni NaN; venta finita en [0, tope]; estado en {0, 1}; campos diarios que se usan completos | bloqueante | source | pasa | 0 | 0 |
| V05 | (tienda, producto, día) único; día AAAA-MM-DD dentro de la ventana de su archivo; train y eval sin solaparse y contiguos | bloqueante | source | pasa | 0 | 0 |
| V06 | Jerarquía: cada producto con una sola cadena de categorías y un grupo; cada tienda con una ciudad | bloqueante | source | pasa | 0 | 0 |
| V07 | Cada serie tiene todos los días de su ventana, y son las mismas series en los dos archivos | bloqueante | source | pasa | 0 | 0 |
| V10 | La entrega es la siguiente del plan y su período empieza el día siguiente al fin de la anterior | bloqueante | per_run | pasa | 0 | 0 |
| V11 | Cada serie-día de la entrega está dentro de su período | bloqueante | per_run | pasa | 0 | 0 |
| V12 | Ninguna serie-día de la entrega está ya en el almacén ni repetida dentro de ella | bloqueante | per_run | pasa | 0 | 0 |
| V13 | Series-días, archivos y SHA-256 son los del manifiesto; solo el cierre puede no tener filas | bloqueante | per_run | pasa | 0 | 0 |
| V14 | Las sumas del archivo de días son las del cubo de la entrega, recalculadas | bloqueante | per_run | pasa | 0 | 0 |
| V15 | La entrega no trae ninguna columna prohibida | bloqueante | per_run | pasa | 0 | 0 |
| V20 | Descuento 0 (se cuenta y se excluye del efecto) | advertencia | per_run | pasa | 0 | 0 |
| V21 | Descuento mayor que 1 (se cuenta y se excluye del efecto) | advertencia | per_run | pasa | 0 | 0 |
| V22 | Descuento entre 0 y 0,5 (se usa: es la banda 0) | advertencia | per_run | pasa | 0 | 0 |
| V23 | Marca 1 con descuento 1 (se usa: banda 6) | advertencia | per_run | pasa | 0 | 0 |
| V24 | Marca 0 con descuento menor que 0,999 (efecto aparte, nunca control) | advertencia | per_run | pasa | 0 | 0 |
| V25 | Serie-día sin stock de 06 a 21 (se recupera con R1) | advertencia | per_run | pasa | 0 | 0 |
| V26 | El total diario de la venta es distinto de la suma de las horas (se cuenta; el campo no pasa de la lectura) | advertencia | source | pasa | 0 | 0 |
| V27 | El conteo de horas sin stock del archivo es distinto del conteo de 06 a 21 (se cuenta; el campo no pasa de la lectura) | advertencia | source | pasa | 0 | 0 |
| I01 | Horas sin stock de 0 a 5 y de 22 a 23 (solo cuenta: no se recuperan) | informativa | per_run | pasa | 0 | 0 |
| I02 | Días con la marca de feriado (solo cuenta: los absorbe el factor del día) | informativa | per_run | pasa | 0 | 0 |
| M03 | El artefacto tiene la huella registrada, antes de leerlo, y el .npz no trae objetos | bloqueante | per_run | pasa | 0 | 0 |
| M05 | La configuración es la sellada (si no, todo lo calculado es posterior al sello) | advertencia | latest | pasa | 0 | 0 |

## No evaluadas

No se pudieron evaluar porque una regla bloqueante anterior falló o porque las evalúa otra tarea: I03, I04, M01, M02, M04, M06.

## Ejemplos

### I01: Horas sin stock de 0 a 5 y de 22 a 23 (solo cuenta: no se recuperan)

- `{"night_out_hours": 0, "series_days": 0}`
