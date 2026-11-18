# Diccionario de datos

Qué hay en cada archivo del proyecto: los campos de los dos Parquet de origen con su uso, los estados del día y las bandas de descuento que el flujo les calcula, las claves, y una tabla por Parquet de `outputs/powerbi/`, generada desde la especificación del modelo con `python -m promolift docs-sync` (`src/promolift/dashboard/semantic_model.py`; nunca a mano). Una prueba (`tests/docs/test_docs.py`) compara los campos de origen con `schema.SOURCE_SCHEMA`, los estados con `days.STATE_NAMES` y las tablas generadas con el esquema de cada Parquet versionado.

La venta del conjunto está normalizada por un coeficiente que la fuente no publica y no tiene unidades: toda cifra del proyecto es relativa (un aumento en %, un WAPE, un sesgo) o «venta normalizada». No hay precio, canal ni identificador de promoción.

## Archivo de origen

`train.parquet` (4.500.000 filas: 50.000 series × 90 días, 2024-03-28 a 2024-06-25) y `eval.parquet` (350.000 filas: 50.000 series × 7 días, 2024-06-26 a 2024-07-02) tienen las mismas 19 columnas, en este orden y con estos tipos de pyarrow (V02). La columna «Uso» dice qué hace el flujo con cada una: **identificador** (arma la serie y la jerarquía), **se usa** (entra a los estados del día, a la recuperación o al contrafactual) o **prohibido** (se descarta al leer y ninguna recuperación, contrafactual o pronóstico la ve: RNF06, D05).

| Columna | Tipo | Uso | Significado |
| --- | --- | --- | --- |
| `city_id` | `int64` | identificador | Ciudad de la tienda (18 ciudades) |
| `store_id` | `int64` | identificador | Tienda (898) |
| `management_group_id` | `int64` | identificador | Grupo de gestión del producto (7): el nivel de la jerarquía donde se arman las celdas del ranking |
| `first_category_id` | `int64` | identificador | Primera categoría del producto (32), la más amplia |
| `second_category_id` | `int64` | identificador | Segunda categoría del producto (84) |
| `third_category_id` | `int64` | identificador | Tercera categoría del producto (233) |
| `product_id` | `int64` | identificador | Producto (865, no 863 como dice el sitio) |
| `dt` | `string` | se usa | Día, `AAAA-MM-DD`: del 2024-03-28 al 2024-07-02 |
| `sale_amount` | `float64` | prohibido | Venta del día: la suma de las 24 horas de `hours_sale` (V26), de modo que contiene la venta de las horas que una máscara oculta |
| `hours_sale` | `list<double>` | se usa | Venta de cada una de las 24 horas, normalizada y sin unidades; el análisis usa las horas de 06 a 21 |
| `stock_hour6_22_cnt` | `int32` | prohibido | Cuenta de las horas sin stock de 06 a 21 del día (V27): contiene el estado del stock de las horas ocultas |
| `hours_stock_status` | `list<int64>` | se usa | Estado del stock de cada una de las 24 horas: 1 si la hora está sin stock, 0 si tiene |
| `discount` | `float64` | se usa | Factor del precio: 1,0 es sin rebaja y la profundidad es `1 − discount`; trae 0 (16.039 filas), valores hasta 1,088 (34 mayores que 1) y 3.338 filas del mismo descuento «limpio» guardadas como su vecino de float32 (D13) |
| `holiday_flag` | `int32` | se usa | 1 si el día es feriado (solo se cuenta, I02: el factor del día lo absorbe) |
| `activity_flag` | `int32` | se usa | Marca de promoción: 1 si el día de la serie tiene promoción; es la definición de promoción del proyecto (D04) |
| `precpt` | `float64` | prohibido | Precipitación del día: el clima observado del día y varía entre tiendas de una misma ciudad (D05) |
| `avg_temperature` | `float64` | prohibido | Temperatura media del día |
| `avg_humidity` | `float64` | prohibido | Humedad media del día |
| `avg_wind_level` | `float64` | prohibido | Nivel de viento medio del día |

## Estados del día

Cada serie-día tiene uno de cuatro estados (`days.py`; D03, D04), que salen de la marca y del descuento. El umbral de «sin rebaja» es 0,999 y un valor a menos de 10⁻⁶ por debajo de un borde cuenta como el borde (D13).

| Estado | Regla | Qué se hace con él |
| --- | --- | --- |
| `promo` | `activity_flag` = 1 y descuento entre 0 y 1 | Es la promoción: entra al efecto y se reparte en bandas |
| `regular` | Sin marca y descuento de al menos 0,999 | Es el control: ajusta el contrafactual (`a` y `b`) |
| `unflagged_cut` | Sin marca y descuento menor que 0,999 | Su efecto se informa aparte y no es control |
| `anomalous` | Descuento 0 o mayor que 1 | Se cuenta (V20, V21) y se aparta de todo |

## Bandas de descuento

Siete bandas de `1 − descuento` para los días `promo` y `unflagged_cut` (aristas de `[days] bands` en la configuración: 0; 0,5; 0,6; 0,7; 0,8; 0,9; 0,95; 1; D13). La banda 0 es la más profunda y la 6 la más liviana; la marca con descuento 1 cae en la banda 6 (V23).

| Banda | Descuento (`discount`) | Rebaja | Series-días con descuento 0 < d ≤ 1 |
| --- | --- | --- | ---: |
| 0 | de 0 a 0,5 | más del 50 % | 15.886 |
| 1 | de 0,5 a 0,6 | 40 a 50 % | 78.127 |
| 2 | de 0,6 a 0,7 | 30 a 40 % | 207.268 |
| 3 | de 0,7 a 0,8 | 20 a 30 % | 429.131 |
| 4 | de 0,8 a 0,9 | 10 a 20 % | 845.609 |
| 5 | de 0,9 a 0,95 | 5 a 10 % | 412.692 |
| 6 | de 0,95 a 1 | hasta 5 % | 2.495.214 |

## Claves y horas

- **`series_key`** (int32): una por (`store_id`, `product_id`), numerada desde 0 en orden en la lectura canónica; **`date_key`** (int32): `AAAAMMDD`; **la serie-día** es (`series_key`, `date_key`); **`cell_key`** (texto): `g<grupo>-b<banda>`, por ejemplo `g4-b2`.
- **Horas**: 0 a 23, hora local supuesta (la tarjeta del conjunto no declara la zona; D05). El análisis usa 06 a 21; la noche (0 a 5 y 22 a 23) trae el 4,8 % de la venta y no se recupera ni se mide.
- **Instantes**: el `as_of` de una corrida diaria es las 00:00 del día siguiente al de su entrega; un día se conoce completo al cerrar (supuesto, D05).
- **Cada tabla de salida** lleva el `run_key` de la corrida que la escribió, el instante de cálculo y las huellas de la fuente; los hechos de efecto llevan además `seal_state` (`sealed` o `post_seal`, D17).

## Tablas de salida

Las 10 dimensiones y 15 hechos de `outputs/powerbi/` (D35), cada una con su clave o su grano, sus columnas, su tipo, su unidad y su significado. Las escribe `docs-sync`: un segundo uso no cambia nada.

<!-- columns:start -->
### `dim_date`

Dimensión. Calendario de los días cargados que ya habían cerrado, con su bloque. Se versiona en `outputs/powerbi/dim_date.parquet`. Clave: `date_key`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `date_key` | entero 32 | — | Fecha, como AAAAMMDD. |
| `date` | fecha | — | Fecha. |
| `weekday_es` | texto | — | Nombre del día de la semana. |
| `is_weekend` | verdadero/falso | — | Sábado o domingo. |
| `holiday_flag` | entero 8 | — | 1 si alguna serie marca el día como feriado, 0 si no. |
| `block` | texto | — | Bloque de la partición en el tiempo. |
| `block_es` | texto | — | Bloque de la partición, en español. |

### `dim_hour`

Dimensión. Las 24 horas del día. Se versiona en `outputs/powerbi/dim_hour.parquet`. Clave: `hour`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `hour` | entero 8 | — | Hora del día, de 0 a 23 (hora local supuesta, D05). |
| `in_analysis` | verdadero/falso | — | La hora está entre las que analiza el proyecto (06 a 21). |
| `label_es` | texto | — | La hora, como «06:00». |

### `dim_group`

Dimensión. Los grupos de gestión. Se versiona en `outputs/powerbi/dim_group.parquet`. Clave: `group_key`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `group_key` | entero 8 | — | Grupo de gestión (el conjunto no los nombra). |
| `label_es` | texto | — | Grupo, como «Grupo 3». |

### `dim_band`

Dimensión. Las siete bandas de descuento. Se versiona en `outputs/powerbi/dim_band.parquet`. Clave: `band_key`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `band_key` | entero 8 | — | Banda de descuento, de 0 (la más profunda) a 6 (la más baja). |
| `discount_low` | decimal | — | Borde bajo del descuento (como factor del precio) de la banda. |
| `discount_high` | decimal | — | Borde alto del descuento de la banda. |
| `depth_label_es` | texto | — | Profundidad de la rebaja, como «más del 50 %» o «hasta 5 %». |

### `dim_cell`

Dimensión. Las celdas: cada grupo de gestión con cada banda; lleva el grupo y la banda como columnas (sin copo de nieve). Se versiona en `outputs/powerbi/dim_cell.parquet`. Clave: `cell_key`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `cell_key` | texto | — | Celda: grupo de gestión por banda de descuento, como g<grupo>-b<banda>. |
| `group_key` | entero 8 | — | Grupo de gestión (el conjunto no los nombra). |
| `band_key` | entero 8 | — | Banda de descuento, de 0 (la más profunda) a 6 (la más baja). |
| `label_es` | texto | — | Celda, como «Grupo 3, rebaja de 40 a 50 %». |

### `dim_version`

Dimensión. Las dos versiones de la venta. Se versiona en `outputs/powerbi/dim_version.parquet`. Clave: `version_key`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `version_key` | texto | — | Versión de la venta: raw (la venta cruda) o recovered (la demanda recuperada). |
| `label_es` | texto | — | Versión, en español. |

### `dim_method`

Dimensión. Los métodos de recuperación y de pronóstico. Se versiona en `outputs/powerbi/dim_method.parquet`. Clave: `method_key`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `method_key` | texto | — | Método: de recuperación (r0, r1, r2@κ, r3) o de pronóstico (f0 a f2). |
| `kind_es` | texto | — | Clase: recuperación o pronóstico. |
| `label_es` | texto | — | Método, en español. |

### `dim_city`

Dimensión. Las ciudades. Se versiona en `outputs/powerbi/dim_city.parquet`. Clave: `city_key`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `city_key` | entero 16 | — | Ciudad (el conjunto solo las numera). |
| `label_es` | texto | — | Ciudad, como «Ciudad 3». |

### `dim_model`

Dimensión. El modelo congelado del lanzamiento. Se versiona en `outputs/powerbi/dim_model.parquet`. Clave: `model_key`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `model_key` | texto | — | Modelo congelado del lanzamiento (su versión). |
| `model_version` | texto | — | Versión del modelo. |
| `recovery_method` | texto | — | Método de recuperación elegido en V1. |
| `kappa` | decimal | — | κ de R2; vacía para otros métodos. |
| `config_sha256` | texto | — | Huella de la configuración sellada del modelo. |
| `seal_state` | texto | — | sealed (la configuración sellada) o post_seal (otra, posterior al sello). |

### `dim_pipeline_run`

Dimensión. Las corridas del flujo. Se versiona en `outputs/powerbi/dim_pipeline_run.parquet`. Clave: `run_key`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `run_key` | texto | — | Corrida que lo escribió. |
| `started_at` | fecha y hora | — | Inicio. |
| `finished_at` | fecha y hora | — | Fin. |
| `status` | texto | — | Estado: running, ok, failed, rejected o no_delivery. |
| `delivery_id` | texto | — | Entrega que cargó. |
| `as_of` | fecha y hora | — | Instante de cálculo de la corrida. |
| `train_sha256` | texto | — | Huella de train.parquet. |
| `eval_sha256` | texto | — | Huella de eval.parquet. |
| `series_days_delivery` | entero 64 | series-días | Series-días de la entrega. |
| `rows_issued` | entero 64 | filas | Filas emitidas. |
| `peak_working_set_mb` | decimal | MB | Pico del conjunto de trabajo. |
| `peak_commit_mb` | decimal | MB | Pico de memoria confirmada (informativo). |
| `memory_counter` | texto | — | Contador de memoria que dio las cifras. |
| `message` | texto | — | Mensaje de la corrida. |

### `fact_cell_effect`

Hecho. El aumento de cada celda por alcance y versión, con su intervalo y su lugar en el ranking. Se versiona en `outputs/powerbi/fact_cell_effect.parquet`. Grano: `scope`, `version_key`, `cell_key`, `ci_kind`, `seal_state`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `scope` | texto | — | De dónde sale la cifra: launch (los 90 días del lanzamiento), valid_replication (la validación, con todo ajustado en el entrenamiento) o test (la semana de prueba). |
| `version_key` | texto | — | Versión de la venta: raw (la venta cruda) o recovered (la demanda recuperada). |
| `cell_key` | texto | — | Celda: grupo de gestión por banda de descuento, como g<grupo>-b<banda>. |
| `observed` | decimal | — | Suma de la venta observada de las series-días de la celda en las horas de 06 a 21 (venta normalizada). |
| `counterfactual` | decimal | — | Suma de lo que el modelo dice para esas series-días sin promoción (venta normalizada). |
| `lift` | decimal | fracción | Aumento: venta observada sobre contrafactual, menos 1; una asociación dentro de la serie, no una causa. |
| `ci_low` | decimal | fracción | Límite inferior del intervalo del 95 %. |
| `ci_high` | decimal | fracción | Límite superior del intervalo del 95 %. |
| `ci_kind` | texto | — | Intervalo: two_way (series y días) o series_only. |
| `series` | entero 32 | series | Series (tienda por producto) con series-días en la unidad. |
| `series_days` | entero 32 | series-días | Series-días en la unidad. |
| `ranked` | verdadero/falso | — | La celda tiene series suficientes y entra en el ranking. |
| `rank` | entero 32 | — | Lugar en el ranking por aumento (1 es el mayor); vacío si no se ordena. |
| `tier` | entero 32 | — | Grupo indistinguible: las celdas del mismo número no se distinguen entre sí; vacío si no se ordena. |
| `fit_blocks` | texto | — | Con qué bloques se ajustó el método que dio la cifra (train, o el período del lanzamiento): nada se mide como fuera de muestra con su propio bloque. |
| `seal_state` | texto | — | sealed (la configuración sellada) o post_seal (otra, posterior al sello). |

### `fact_band_effect`

Hecho. El aumento de cada banda de descuento, y el de los días con rebaja sin marca. Se versiona en `outputs/powerbi/fact_band_effect.parquet`. Grano: `scope`, `version_key`, `band_key`, `control`, `day_state`, `seal_state`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `scope` | texto | — | De dónde sale la cifra: launch (los 90 días del lanzamiento), valid_replication (la validación, con todo ajustado en el entrenamiento) o test (la semana de prueba). |
| `version_key` | texto | — | Versión de la venta: raw (la venta cruda) o recovered (la demanda recuperada). |
| `band_key` | entero 8 | — | Banda de descuento, de 0 (la más profunda) a 6 (la más baja). |
| `control` | texto | — | Días de control: regular (sin marca y sin rebaja) o any_flag0 (cualquier día sin marca). |
| `lift` | decimal | fracción | Aumento: venta observada sobre contrafactual, menos 1; una asociación dentro de la serie, no una causa. |
| `ci_low` | decimal | fracción | Límite inferior del intervalo del 95 %. |
| `ci_high` | decimal | fracción | Límite superior del intervalo del 95 %. |
| `series` | entero 32 | series | Series (tienda por producto) con series-días en la unidad. |
| `series_days` | entero 32 | series-días | Series-días en la unidad. |
| `day_state` | texto | — | Días medidos: promo, o unflagged_cut (rebaja sin marca: su propio efecto). |
| `seal_state` | texto | — | sealed (la configuración sellada) o post_seal (otra, posterior al sello). |

### `fact_group_effect`

Hecho. El aumento de cada grupo de gestión. Se versiona en `outputs/powerbi/fact_group_effect.parquet`. Grano: `scope`, `version_key`, `group_key`, `seal_state`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `scope` | texto | — | De dónde sale la cifra: launch (los 90 días del lanzamiento), valid_replication (la validación, con todo ajustado en el entrenamiento) o test (la semana de prueba). |
| `version_key` | texto | — | Versión de la venta: raw (la venta cruda) o recovered (la demanda recuperada). |
| `group_key` | entero 8 | — | Grupo de gestión (el conjunto no los nombra). |
| `lift` | decimal | fracción | Aumento: venta observada sobre contrafactual, menos 1; una asociación dentro de la serie, no una causa. |
| `ci_low` | decimal | fracción | Límite inferior del intervalo del 95 %. |
| `ci_high` | decimal | fracción | Límite superior del intervalo del 95 %. |
| `series` | entero 32 | series | Series (tienda por producto) con series-días en la unidad. |
| `seal_state` | texto | — | sealed (la configuración sellada) o post_seal (otra, posterior al sello). |

### `fact_overall_effect`

Hecho. El aumento total, con la cuenta ingenua al lado del contrafactual. Se versiona en `outputs/powerbi/fact_overall_effect.parquet`. Grano: `scope`, `version_key`, `estimator`, `control`, `seal_state`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `scope` | texto | — | De dónde sale la cifra: launch (los 90 días del lanzamiento), valid_replication (la validación, con todo ajustado en el entrenamiento) o test (la semana de prueba). |
| `version_key` | texto | — | Versión de la venta: raw (la venta cruda) o recovered (la demanda recuperada). |
| `estimator` | texto | — | naive_pooled (la cuenta que mezcla productos) o counterfactual (la misma serie y la misma hora). |
| `control` | texto | — | Días de control: regular o any_flag0. |
| `lift` | decimal | fracción | Aumento: venta observada sobre contrafactual, menos 1; una asociación dentro de la serie, no una causa. |
| `ci_low` | decimal | fracción | Límite inferior del intervalo del 95 %. |
| `ci_high` | decimal | fracción | Límite superior del intervalo del 95 %. |
| `series_days` | entero 32 | series-días | Series-días en la unidad. |
| `seal_state` | texto | — | sealed (la configuración sellada) o post_seal (otra, posterior al sello). |

### `fact_daily_cell`

Hecho. Lo que se emitió cada día de la semana de prueba por celda. Se versiona en `outputs/powerbi/fact_daily_cell.parquet`. Grano: `date_key`, `version_key`, `cell_key`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `date_key` | entero 32 | — | Fecha, como AAAAMMDD. |
| `version_key` | texto | — | Versión de la venta: raw (la venta cruda) o recovered (la demanda recuperada). |
| `cell_key` | texto | — | Celda: grupo de gestión por banda de descuento, como g<grupo>-b<banda>. |
| `observed` | decimal | — | Suma de la venta observada de las series-días con promoción de la celda ese día. |
| `counterfactual` | decimal | — | Suma de lo que el modelo sellado dice para esas series-días, con el factor de ese día. |
| `lift` | decimal | fracción | Aumento del día de la celda. |
| `series_days` | entero 32 | series-días | Series-días en la unidad. |
| `stockout_hours` | entero 32 | horas | Horas sin stock de 06 a 21 de esas series-días. |

### `fact_hour_profile`

Hecho. La venta y los quiebres por hora, día, grupo y estado del día. Se versiona en `outputs/powerbi/fact_hour_profile.parquet`. Grano: `date_key`, `group_key`, `hour`, `day_state`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `date_key` | entero 32 | — | Fecha, como AAAAMMDD. |
| `group_key` | entero 8 | — | Grupo de gestión (el conjunto no los nombra). |
| `hour` | entero 8 | — | Hora del día, de 0 a 23 (hora local supuesta, D05). |
| `day_state` | texto | — | Estado del día de la serie: promo, regular, unflagged_cut o anomalous. |
| `series_days` | entero 32 | series-días | Series-días en la unidad. |
| `mean_sales` | decimal | venta normalizada | Venta media de la hora por serie-día (venta normalizada). |
| `stockout_rate` | decimal | proporción | Parte de las series-días sin stock en la hora. |

### `fact_stockout_daily`

Hecho. Los quiebres y la demanda recuperada por día, ciudad y grupo. Se versiona en `outputs/powerbi/fact_stockout_daily.parquet`. Grano: `date_key`, `city_key`, `group_key`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `date_key` | entero 32 | — | Fecha, como AAAAMMDD. |
| `city_key` | entero 16 | — | Ciudad (el conjunto solo las numera). |
| `group_key` | entero 8 | — | Grupo de gestión (el conjunto no los nombra). |
| `series_days` | entero 32 | series-días | Series-días en la unidad. |
| `stockout_rate` | decimal | proporción | Parte de las horas de 06 a 21 sin stock. |
| `raw_mass` | decimal | — | Venta cruda de las series-días ya recuperadas (venta normalizada). |
| `recovered_mass` | decimal | — | Demanda recuperada de esas mismas series-días (venta normalizada); vacía si ninguna se recuperó todavía. |

### `fact_recovery_check`

Hecho. La comprobación de la recuperación con horas que se conocen. Se versiona en `outputs/powerbi/fact_recovery_check.parquet`. Grano: `scope`, `mask`, `method_key`, `seal_state`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `scope` | texto | — | Bloque medido: valid_v1 y valid_v2 (validación, métodos ajustados en el entrenamiento) o test (la semana de prueba). |
| `mask` | texto | — | Máscara sintética: tail (la cola del día, como un quiebre) o mcar (tres horas al azar, un contraste). |
| `method_key` | texto | — | Método: de recuperación (r0, r1, r2@κ, r3) o de pronóstico (f0 a f2). |
| `fit_blocks` | texto | — | Con qué bloques se ajustó el método que dio la cifra (train, o el período del lanzamiento): nada se mide como fuera de muestra con su propio bloque. |
| `wape_series` | decimal | fracción | WAPE de la masa oculta por serie. |
| `bias` | decimal | fracción | Sesgo total de la masa recuperada. |
| `bias_promo` | decimal | fracción | Sesgo en los días con promoción. |
| `bias_regular` | decimal | fracción | Sesgo en los días regulares. |
| `lift_bias` | decimal | fracción | Sesgo que eso induce en el aumento. |
| `ci_low_vs_r1` | decimal | fracción | Límite inferior del intervalo del 95 % de WAPE(método) − WAPE(R1). |
| `ci_high_vs_r1` | decimal | fracción | Límite superior del intervalo del 95 % de WAPE(método) − WAPE(R1). |
| `chosen` | verdadero/falso | — | Es el método que eligió el lanzamiento. |
| `seal_state` | texto | — | sealed (la configuración sellada) o post_seal (otra, posterior al sello). |

### `fact_forecast`

Hecho. Los pronósticos F0, F1, F2a y F2: si el aumento de la celda agrega información. Se versiona en `outputs/powerbi/fact_forecast.parquet`. Grano: `scope`, `method_key`, `seal_state`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `scope` | texto | — | valid (validación, todo ajustado en el entrenamiento) o test (la semana de prueba). |
| `method_key` | texto | — | Método: de recuperación (r0, r1, r2@κ, r3) o de pronóstico (f0 a f2). |
| `fit_blocks` | texto | — | Con qué bloques se ajustó el método que dio la cifra (train, o el período del lanzamiento): nada se mide como fuera de muestra con su propio bloque. |
| `wape` | decimal | fracción | WAPE de la masa de las horas con stock de las series-días con promoción. |
| `bias` | decimal | fracción | Sesgo del pronóstico. |
| `series_days` | entero 32 | series-días | Series-días en la unidad. |
| `seal_state` | texto | — | sealed (la configuración sellada) o post_seal (otra, posterior al sello). |

### `fact_replication`

Hecho. El aumento sellado de cada celda frente al de la semana de prueba. Se versiona en `outputs/powerbi/fact_replication.parquet`. Grano: `cell_key`, `seal_state`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `cell_key` | texto | — | Celda: grupo de gestión por banda de descuento, como g<grupo>-b<banda>. |
| `lift_launch` | decimal | fracción | Aumento sellado del lanzamiento. |
| `ci_low_launch` | decimal | fracción | Límite inferior del lanzamiento. |
| `ci_high_launch` | decimal | fracción | Límite superior del lanzamiento. |
| `lift_test` | decimal | fracción | Aumento de la semana de prueba. |
| `ci_low_test` | decimal | fracción | Límite inferior de la prueba. |
| `ci_high_test` | decimal | fracción | Límite superior de la prueba. |
| `diff_ci_low` | decimal | fracción | Límite inferior del intervalo de la diferencia prueba − sellado. |
| `diff_ci_high` | decimal | fracción | Límite superior del intervalo de la diferencia prueba − sellado. |
| `consistent` | verdadero/falso | — | El intervalo de la diferencia contiene 0; vacío si la celda no tiene series suficientes en las dos. |
| `seal_state` | texto | — | sealed (la configuración sellada) o post_seal (otra, posterior al sello). |

### `fact_evaluation_summary`

Hecho. Los criterios de la prueba y su veredicto. Se versiona en `outputs/powerbi/fact_evaluation_summary.parquet`. Grano: `criterion_id`, `seal_state`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `criterion_id` | texto | — | Criterio, de C01 a C10. |
| `name_es` | texto | — | Nombre del criterio. |
| `value` | decimal | — | Valor medido. |
| `baseline_value` | decimal | — | Valor de la base con que se compara. |
| `ci_low` | decimal | — | Límite inferior del intervalo. |
| `ci_high` | decimal | — | Límite superior del intervalo. |
| `threshold_es` | texto | — | Umbral, en español. |
| `passed` | verdadero/falso | — | Cumple; vacío en el informativo. |
| `seen_by_research` | texto | — | Si la investigación lo vio antes. |
| `seen_by_planner` | texto | — | Si el plan lo vio antes. |
| `verdict_es` | texto | — | Veredicto, en español. |
| `seal_state` | texto | — | sealed (la configuración sellada) o post_seal (otra, posterior al sello). |

### `fact_example_day`

Hecho. La serie-día de ejemplo (la de mediana de la regla fija del plan, sección 21): venta observada y recuperada por hora. Se versiona en `outputs/powerbi/fact_example_day.parquet`. Grano: `hour`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `hour` | entero 8 | — | Hora del día, de 0 a 23 (hora local supuesta, D05). |
| `observed` | decimal | — | Venta observada de la hora (venta normalizada). |
| `recovered` | decimal | — | Demanda recuperada de la hora. |
| `in_stock` | entero 8 | — | 1 si la hora tenía stock, 0 si no. |

### `fact_leakage`

Hecho. La demostración de la fuga: una recuperación que lee el total diario parece casi perfecta. Se versiona en `outputs/powerbi/fact_leakage.parquet`. Grano: `check`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `check` | texto | — | Comprobación. |
| `check_es` | texto | — | Qué se hizo, en español. |
| `value` | decimal | fracción | WAPE por serie en la máscara de V2. |
| `note_es` | texto | — | Lo que enseña. |

### `fact_data_quality`

Hecho. La calidad de los datos, día por día. Se versiona en `outputs/powerbi/fact_data_quality.parquet`. Grano: `date_key`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `date_key` | entero 32 | — | Fecha, como AAAAMMDD. |
| `series_days` | entero 32 | series-días | Series-días en la unidad. |
| `promo` | entero 32 | series-días | Series-días con promoción. |
| `regular` | entero 32 | series-días | Series-días regulares (sin marca y sin rebaja). |
| `unflagged_cut` | entero 32 | series-días | Series-días con rebaja y sin marca. |
| `anomalous` | entero 32 | series-días | Series-días con descuento 0 o mayor que 1. |
| `fully_out` | entero 32 | series-días | Series-días sin stock de 06 a 21. |
| `stockout_rate` | decimal | proporción | Parte de las horas de 06 a 21 sin stock. |

### `fact_validation`

Hecho. El resultado de cada regla en cada corrida. Se versiona en `outputs/powerbi/fact_validation.parquet`. Grano: `run_key`, `rule_id`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `run_key` | texto | — | Corrida que lo escribió. |
| `rule_id` | texto | — | Regla de validación. |
| `name_es` | texto | — | Nombre de la regla. |
| `severity` | texto | — | bloqueante, advertencia o informativa. |
| `scope` | texto | — | Alcance: source, delivery, days o model. |
| `aggregation` | texto | — | Cómo se agrega entre corridas: source, per_run o latest. |
| `status` | texto | — | pasa, falla (bloqueante que no pasa) o advierte. |
| `series_days_affected` | entero 64 | series-días | Series-días afectadas. |
| `hours_affected` | entero 64 | horas | Horas afectadas. |
<!-- columns:end -->
