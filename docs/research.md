# Investigación previa: qué promociones venden de verdad, con la demanda que esconden los quiebres

Fecha de la investigación: 2026-11-17.

**Leyenda de etiquetas**

- **[Verificado]**: medido directamente sobre los archivos reales descargados, o comprobado en la página de la fuente. Se indica el script o la URL.
- **[Documentación]**: tomado de una página oficial o de un artículo que se abrió. Se indica la URL.
- **[Fuente secundaria]**: tomado de un texto que no se pudo leer completo o de un preprint de bajo peso. Conviene confirmarlo antes de citarlo.
- **[Inferido]**: deducción propia a partir de datos observados. No está confirmada por una fuente.

Esta investigación es una primera mirada: no es el resultado del proyecto. Las cifras de "Primera mirada" salen de una sola especificación por comparación, sin búsqueda de parámetros, y de un bloque de validación de 18 días.

**Aviso sobre el periodo de prueba.** El conjunto trae su propia partición de prueba: 2024-06-26 a 2024-07-02 (7 días, 350.000 filas). Ningún cálculo de este documento usa sus valores. `s01` lee el archivo completo para verificar esquema e integridad, incluida esa partición, sin calcular métricas. `s06` lee solo sus claves (tienda, producto, fecha) para comprobar que no se solapan con el entrenamiento. El resto usa el periodo de entrenamiento del conjunto (2024-03-28 a 2024-06-25). Las líneas base se miden sobre el bloque de validación propuesto, dentro de ese periodo (2024-06-08 a 2024-06-25). En ningún paso se calculó una métrica sobre la prueba.

---

## Hallazgos principales

1. **Fuente y licencia.** El conjunto es FreshRetailNet-50K, de Dingdong-Inc en Hugging Face, con licencia CC BY 4.0. La tarjeta permite uso comercial y no comercial y exige atribución. Se descargó el commit `c374e859` (2026-11-17). Los dos Parquet coinciden en tamaño y SHA-256 con los identificadores de objeto que publica la API. [Verificado: `s00`]
2. **Estructura.** 50.000 series (tienda × producto) de 90 días en entrenamiento (2024-03-28 a 2024-06-25) y 7 días en prueba (2024-06-26 a 2024-07-02). Sin huecos ni duplicados. 898 tiendas, 18 ciudades, 865 identificadores de producto. Cada fila tiene 24 valores horarios y 9 valores diarios. [Verificado: `s01`, `s02`]
3. **La venta diaria es la suma de las horas.** `sale_amount` es exactamente la suma de `hours_sale` en todas las filas. `stock_hour6_22_cnt` cuenta las horas sin stock de 6 a 21 en todas las filas. Ambos campos son fuga si se usan para predecir el mismo día. [Verificado: `s01`, `s06`]
4. **Los quiebres son frecuentes.** El 19,9 % de las series-hora de 06 a 21 tiene estado 1 (sin stock). El 44,3 % de las series-días tiene al menos una hora sin stock en ese rango. La tasa sube de 6,2 % a las 6 h hasta 41,0 % a las 21 h. [Verificado: `s02`, `s03`]
5. **Una hora sin stock casi no vende.** El 97,1 % de las horas con estado 1 tiene venta cero, frente a 71,4 % de las horas con stock. En la misma serie y la misma hora, la venta en horas sin stock es 89,5 % menor. Esto mide la caída de la venta, no la demanda perdida. [Verificado: `s02`, `s03`]
6. **La curva de quiebres del artículo no se reproduce.** El artículo dice menos de 2 % de quiebres a las 6 h y un pico de 26 % a las 20 h. En el entrenamiento son 6,2 % y 38,8 %. Las horas pico de venta sí coinciden: 9 h y 16 h. [Verificado: `s02`]
7. **La promoción está en dos campos que no coinciden.** `activity_flag = 1` marca el 37,8 % de los días válidos. `discount < 1` aparece en el 51,5 % de las filas. Hay 654.330 filas con descuento y sin marca, y 38.378 con marca y sin descuento. La marca cae sobre descuentos de 0,5 a 0,9. [Verificado: `s04`]
8. **Anomalías en el descuento.** 16.039 filas tienen descuento 0 (239 series, 8 productos), con venta diaria mediana de 15 frente a 0,7 en el resto. 15.886 filas tienen descuento entre 0 y 0,5, con marca en el 99,99 %. El rango de "0,5 a 1" del sitio no describe los datos. [Verificado: `s04`]
9. **Las promociones suben los quiebres.** Dentro de la misma serie, los días con promoción tienen 4,5 puntos más de horas sin stock (IC 95 % [4,3; 4,6]). Por eso un quiebre tapa parte del efecto de la promoción. [Verificado: `s03`]
10. **La comparación cruda subestima el efecto, sobre todo por la mezcla de productos.** Sin igualar serie ni hora, la promoción suma +11,1 %. Dentro de cada serie y hora, +33,6 %. Con demanda recuperada, +38,6 % (IC 95 % [38,1; 39,3]). Es decir, el quiebre explica unos 5 puntos, y la mezcla de productos unos 22. [Verificado: `s08`]
11. **La asignación de la promoción depende de la serie, no del calendario.** Eta² de la serie: 0,45. Del producto: 0,35. Del día de la semana: 0,001. De la semana: 0,004. Del feriado: 0,0003. [Verificado: `s05`]
12. **El ranking por nivel de descuento es claro.** El efecto baja de +149 % (descuento de hasta 0,5) a +4,8 % (de 0,95 a 1). Ninguno de los 21 pares de bandas se pisa. Entre 946 pares de celdas (grupo de gestión por banda), 821 se separan. [Verificado: `s09`]
13. **Las líneas base son difíciles de batir con MAE.** Un pronóstico de cero tiene el menor MAE en horas (0,0472), frente a 0,0493 a 0,0563 de los promedios. A nivel diario, el mejor promedio naive tiene WAPE de 34,0 %. [Verificado: `s07`]
14. **La partición propuesta cambia de nivel.** Entrenamiento 2024-03-28 a 2024-05-31 (65 días), purga de 7 días, validación 2024-06-08 a 2024-06-25 (18 días), prueba 2024-06-26 a 2024-07-02 (la partición del conjunto, sin usar). La validación tiene ventas medias 17,9 % mayores que el entrenamiento y más días con promoción (41,2 % frente a 36,8 %). [Verificado: `s06`, `s07`]

---

## Objetivo

Verificar la fuente, la licencia, la estructura y la integridad del conjunto. Medir cuánto esconden los quiebres, cómo se codifican y se reparten las promociones, qué fugas hay y una partición en el tiempo. Dejar líneas base con cifras y una primera mirada al efecto de la promoción (ingenuo frente a ajustado por quiebres) y a la incertidumbre de un ranking. Todo para que el planificador escriba requisitos y un plan del proyecto 06 (`06-Ecommerce-Promotion-Lift`, tarea T7 en `odd/tasks/portfolio-projects.md`).

El proyecto responde qué promociones venden de verdad. En este conjunto no hay identificador de promoción: la unidad que se puede medir es la celda (grupo de gestión × banda de descuento, en días con marca). Esa restricción debe quedar en el sitio.

---

## Fuentes

**Datos**

- Conjunto: https://huggingface.co/datasets/Dingdong-Inc/FreshRetailNet-50K (tarjeta leída el 2026-11-17; commit `c374e85975c82816c495acfa904cc55ab14a47d3`). Metadatos: https://huggingface.co/api/datasets/Dingdong-Inc/FreshRetailNet-50K. [Verificado: API y tarjeta leídas]
  - Licencia: `license: cc-by-4.0` en las etiquetas y texto "CC BY 4.0" (https://creativecommons.org/licenses/by/4.0/legalcode). Autor: Dingdong-Inc. Versión 1.0 (fecha de publicación 05/08/2025). Última modificación del repositorio: 2026-10-09. [Verificado]
  - Archivos (LFS): `data/train.parquet`, 106.436.287 bytes, SHA-256 `6706832db892bbae4969c19d87e07975d2543d2ba7d7d4756360654785de5a3d`. `data/eval.parquet`, 8.440.124 bytes, SHA-256 `1b118840664280c6b88bffc84c80ee1f54c05d911e354b7599e5da10995e960e`. [Verificado: `s00`]
  - Lo que dice la tarjeta: "approximately 20% organically occurring stockout data", "50,000 store-product 90-day time series", "898 stores in 18 major cities", "865 perishable SKUs". [Verificado]
- Archivos locales: `data/raw/train.parquet`, `data/raw/eval.parquet`, `data/raw/manifest.json` y `data/raw/dataset_card_README.md`. Git los ignora (`**/data/raw/`).

**Literatura** (abiertos el 2026-11-17)

- Wang, Y., Gu, J., Long, L., Li, X., Shen, L., Fu, Z., Zhou, X., Jiang, X. (2026). *FreshRetailNet-50K: A Stockout-Annotated Censored Demand Dataset for Latent Demand Recovery and Forecasting in Fresh Retail*. arXiv:2505.16319v5 (18 jun 2026). https://arxiv.org/abs/2505.16319. PDF leído completo. [Documentación de los autores del conjunto; no verificada de forma independiente]
- Brodersen, K. H., Gallusser, F., Koehler, J., Remy, N., Scott, S. L. (2015). *Inferring causal impact using Bayesian structural time-series models*. Annals of Applied Statistics 9(1), 247–274. arXiv:1506.00356. https://arxiv.org/abs/1506.00356. Resumen leído. [Documentación]
- Gundem, K., Qi, Z. (2026, v2 de 11 mar). *Offline dynamic inventory and pricing strategy: addressing censored and dependent demand*. arXiv:2504.09831. https://arxiv.org/abs/2504.09831. Resumen leído. [Documentación]
- Wang, C., Jiang, H., Chen, N. (2026, v2 de 27 oct). *Demand estimation with unobserved stockout substitution: exact likelihood maximization*. arXiv:2610.34547. https://arxiv.org/abs/2610.34547. Resumen leído. [Documentación]
- Verma, A., Gupta, N. (2026, 9 nov). *Trade promotion optimisation for consumer goods*. arXiv:2611.12665. https://arxiv.org/abs/2611.12665. Resumen leído. Preprint de una empresa, con un experimento de 39 SKU. [Fuente secundaria: peso bajo]
- Código de referencia del conjunto: https://github.com/Dingdong-Inc/frn-50k-baseline (README leído en `raw.githubusercontent.com`). Modelos de recuperación y pronóstico del artículo. [Documentación]
- No abierto: Amjad, S., Shah, D. (2017), *Censored demand estimation in retail*, DOI 10.1145/3154503. ACM responde 403 ("Just a moment"). No se cita. No se buscó más literatura clásica de demanda censurada. [Hueco declarado]

**Librerías**

- numpy 2.4.6, pandas 2.3.3, scikit-learn 1.9.1, pyarrow 26.0.1, y sus dependencias (`requirements-research.txt`). Son las mismas versiones que el proyecto 05. [Verificado: `pip freeze`]
- Fuera del landing: `pyarrow` (lee los Parquet). Ya está en `LANDING-EXPANSION.md` (fila "Apache Parquet con pyarrow"), que debe ampliarse con el proyecto 06. `statsmodels`: no se usó en esta investigación, pero `promotion-lift.ts` la declara como herramienta del proyecto y no figura en `LANDING-EXPANSION.md`. Ver Riesgos.

---

## Cómo se verificaron los datos

- **Entorno.** Windows 10 Pro, Python 3.11.1, `.venv` del proyecto con las versiones de `requirements-research.txt`. RAM física de la máquina: 63,9 GB (medida con `Win32_ComputerSystem`). Los scripts se ejecutan con `python -I research/<script>.py` desde la carpeta del proyecto.
- **Descarga.** `research/s00_download.py`, por HTTPS, sin cuenta, fijada al commit. Antes de bajar, compara tamaños y los identificadores LFS del listado de la API. Después calcula SHA-256 de cada archivo. Ambos archivos quedan verificados. [Verificado: `s00`]
- **Escala.** No hubo muestreo. Las 4,5 millones de filas de entrenamiento se leen completas y se pasan a matrices densas de 50.000 × 90 × 24. No se midió el pico de memoria.
- **Integridad.** `s01`: sin nulos ni NaN, todas las listas horarias de longitud 24 (la carga falla si no se cumple), sin duplicados por serie y día, y jerarquía sin padres múltiples.
- **Identidades entre campos.** `sale_amount` coincide con la suma horaria (diferencia máxima 7,1·10⁻¹⁵). `stock_hour6_22_cnt` coincide con el conteo de estado 1 en las horas 6 a 21 en el 100 % de las filas. Con las horas 6 a 22 coincide solo en el 58 %. La tarjeta dice "between 6:00 and 22:00"; el conteo corresponde a 6:00 a 21:59. [Verificado: `s01`]
- **Tarjeta frente a datos.** Tiendas (898) y ciudades (18) coinciden. Productos: 865 en la tarjeta y en los datos, 863 en el artículo. [Verificado: `s01`]
- **Artículo frente a datos.** Ver la tabla de la sección siguiente.

| Cifra | Artículo (arXiv 2505.16319 v5) | Datos de entrenamiento |
|---|---|---|
| Quiebre a las 6 h (sección 3.3) | "below 2%" | 6,2 % (`s02`) |
| Quiebre máximo (sección 3.3) | "peak ... 26% by 8 PM" | 38,8 % a las 20 h; 41,9 % a las 22 h (`s02`) |
| Quiebre en el día (tarjeta) | "approximately 20%" | 19,9 % de 06 a 21; 24,9 % de las 24 h (`s02`, `s03`) |
| Picos de venta (sección 3.2) | "9:00 AM ... 4:00 PM" | 9 h y 16 h, los dos máximos locales (`s02`) |
| Efecto de la promoción (sección 3.2) | "median sales uplifts of 1.43×, IQR 1.05×–2.06×" | mediana por serie 1,38, IQR 1,14 a 1,73 (`s08`, con otra definición) |
| Origen de las ventas (sección 3.1) | "hourly sales data are derived from online order transaction systems" | no hay campo de canal (`s01`) |
| Periodo (sección 3.1) | "March to June 2024" | 2024-03-28 a 2024-07-02 (`s01`) |

---

## Estructura de los datos

- **Grano.** Una fila es una tienda × producto × día, con 24 valores horarios. Las horas van de 0 a 23. La zona horaria no está en la tarjeta. Las horas pico de venta (9 y 16) apuntan a hora local. [Inferido]
- **Series.** 50.000 pares tienda × producto. Cada serie tiene 90 días en entrenamiento y 7 en prueba. Sin valores faltantes. [Verificado: `s01`, `s02`]
- **Fechas.** Entrenamiento 2024-03-28 a 2024-06-25 (90 días, contiguos). Prueba 2024-06-26 a 2024-07-02 (7 días). Sin solape. [Verificado: `s01`, `s06`]
- **Campos horarios** (cambian dentro del día):
  - `hours_sale`: venta por hora normalizada con un coeficiente no publicado. No tiene unidades. Rango 0 a 16,9. [Verificado: `s01`; tarjeta]
  - `hours_stock_status`: 0 o 1. Según la tarjeta, es el estado de quiebre de la hora ("hourly out-of-stock status"). [Documentación]
- **Campos diarios** (un valor por fila): `sale_amount`, `stock_hour6_22_cnt`, `discount` (1,0 = sin descuento), `holiday_flag`, `activity_flag`, `precpt`, `avg_temperature`, `avg_humidity`, `avg_wind_level`. El clima varía entre tiendas de una misma ciudad: solo el 0,43 % de los días de ciudad tiene una sola precipitación. [Verificado: `s01`, `s06`]
- **Jerarquía.** Tienda → ciudad (898 → 18). Producto → 3ª categoría → 2ª → 1ª → grupo de gestión (865 → 233 → 84 → 32 → 7). Sin padres múltiples. [Verificado: `s01`]
- **Campos que no están.** Precio, canal de venta e identificador de promoción. [Verificado: `s01`, esquema completo]

**Perfil horario (entrenamiento)**

| Hora | Venta media (normalizada) | Tasa de quiebre | Tasa de venta cero |
|---:|---:|---:|---:|
| 0 | 0,0084 | 41,1 % | 93,2 % |
| 6 | 0,0310 | 6,2 % | 80,6 % |
| 9 | 0,1068 | 7,1 % | 53,1 % |
| 12 | 0,0542 | 14,8 % | 69,1 % |
| 16 | 0,0806 | 24,0 % | 61,0 % |
| 20 | 0,0253 | 38,8 % | 84,3 % |
| 22 | 0,0105 | 41,9 % | 91,8 % |

[Verificado: `s02`]

---

## Censura por quiebres: cuántas, cuándo y dónde

**Frecuencia (06 a 21, entrenamiento)** [Verificado: `s03`]

- Tasa global: 19,9 % de las series-hora. Por hora: 6 h, 6,2 %; 9 h, 7,1 %; 12 h, 14,8 %; 16 h, 24,0 %; 18 h, 33,6 %; 20 h, 38,7 %; 21 h, 41,0 %.
- Por día de la semana: de 17,6 % (viernes) a 22,4 % (domingo).
- Por grupo de gestión: de 16,0 % (grupo 3) a 22,6 % (grupo 0).
- Por serie: mediana 17,7 %; p10 13,1 %; p90 28,9 %; máximo 97,0 %.
- Por serie-día: 44,3 % tiene al menos una hora sin stock de 06 a 21. Solo 4,0 % tiene quiebre en todas esas horas. Ninguna serie queda sin quiebre en los 90 días.
- Noche (0 a 5 y 22 a 23): 34,9 % de las horas con estado 1, con venta media de 0,0034 en esas horas. La noche casi no vende; el quiebre nocturno censura poca demanda real. [Inferido]

**Venta en horas sin stock frente a con stock** (misma serie y misma hora, 06 a 21, 761.494 pares con los dos estados) [Verificado: `s03`]

- En el 97,8 % de los pares, la venta en horas sin stock es menor. La razón de ventas ponderada es 0,105 (caída de 89,5 %).
- Solo 2,9 % de las horas sin stock tiene venta positiva. El 62,1 % de las horas con stock tiene venta cero.
- Lectura: la caída es grande. La comparación no separa la demanda perdida: también ocurren quiebres en días de demanda baja. Recuperar la demanda exige supuestos (ver "Primera mirada"). [Inferido]

**Quiebres y promoción** [Verificado: `s03`, `s08`]

- Tasa en días de promoción (06 a 21, días válidos): 20,6 %. En días sin promoción: 19,4 %.
- Dentro de la misma serie (40.460 series con ambos tipos de día), la promoción suma +4,46 puntos de quiebre (IC 95 % [+4,33; +4,59]). En el 66,4 % de las series, la tasa sube en días de promoción.
- Por profundidad del descuento en días de promoción: 24,7 % (hasta 0,5), 21,3 % (0,5 a 0,6), 20,2 % (0,6 a 0,7), 21,1 % (0,7 a 0,8), 20,7 % (0,8 a 0,9), 19,7 % (0,9 a 0,95), 16,4 % (0,95 a 1). El gradiente es suave, pero va en el sentido que el artículo describe ("deeper price reductions ... increases stockouts"). [Verificado: `s03`; sentido según Documentación]

---

## Promociones: codificación y cobertura

**Descuento frente a la marca** (entrenamiento, filas) [Verificado: `s04`]

| Descuento | Filas | Con marca `activity_flag = 1` |
|---|---:|---:|
| 0 (anomalía) | 16.039 | 0,8 % |
| (0; 0,5) | 15.886 | 100,0 % |
| [0,5; 0,6) | 78.127 | 93,9 % |
| [0,6; 0,7) | 207.326 | 97,1 % |
| [0,7; 0,8) | 429.102 | 95,8 % |
| [0,8; 0,9) | 847.707 | 90,8 % |
| [0,9; 0,95) | 411.689 | 40,2 % |
| [0,95; 0,999) | 309.593 | 8,9 % |
| [0,999; 1) | 2.184.497 | 1,8 % |
| 1 o más | 34 | 0,0 % |

- La marca identifica los descuentos de 0,5 a 0,9. Entre 0,9 y 0,95 cae a 40 %, y por debajo de 0,95 casi no aparece. El campo que el sitio llama "marca de promoción" es `activity_flag`, pero el descuento también se usa. Hay que elegir cuál define la promoción.
- Cuantiles del descuento en días con marca: p5 0,599; p25 0,738; mediana 0,827; p75 0,878; p95 0,933. Es decir, de 7 % a 40 % de rebaja, con el centro entre 12 % y 26 %. [Verificado: `s04`]
- Discrepancias entre los dos campos: 654.330 filas con descuento menor que 1 y sin marca; 38.378 filas con marca y sin descuento; 1.467.837 de las 1.702.893 filas con marca (86 %) tienen descuento entre 0,5 y 0,9. [Verificado: `s04`]

**Anomalías**

- Descuento 0: 16.039 filas en 239 series, 8 productos y 230 tiendas. La venta diaria mediana es 15,0; en el resto de las filas, 0,7. En 114 series el descuento es 0 todos los días. [Verificado: `s04`]
- Descuento entre 0 y 0,5: 15.886 filas en 2.339 series, con marca en el 99,99 %. Venta diaria mediana 1,6. [Verificado: `s04`]
- Descuento mayor que 1: 34 filas, sin marca. [Verificado: `s04`]
- Todas estas filas se excluyen de las estimaciones de `s08` y `s09` (descuento válido: mayor que 0 y hasta 1). `s08` cuenta cuántas son.

**Cobertura** [Verificado: `s04`, `s10`]

- Series-días con marca: 37,8 %. Series con al menos un día con marca: 83,8 %. Días con marca por serie: mediana 28 de 90; p10 0; p90 81.
- Series-semana con promoción: 50,4 %. Series con promoción en todas las semanas completas: 15,3 %.
- A nivel cadena, las 13 semanas tienen promoción en al menos una serie.
- Rachas de días con marca: 165.408 rachas; mediana 3 días; p90 27; máximo 90.
- Cambios de un día al siguiente: el descuento cambia en 32,9 % de los pares de días; la marca, en 6,7 %.

**Feriados.** `holiday_flag` vale 1 en 31 de 90 días (34,4 % de las filas). Son sábados y domingos más los feriados que nombra el artículo (sección 3.1): 4 a 6 de abril, 1 a 5 de mayo, y 8 a 10 de junio. El campo mezcla fin de semana y feriado. [Verificado: `s05`; asociación de los feriados con el artículo, Documentación]

---

## Confusión: promociones frente a temporada, día, tienda y producto

Eta² (y omega², corregido por número de grupos) de la marca `activity_flag` [Verificado: `s05`]

| Factor | Grupos | Eta² | Omega² |
|---|---:|---:|---:|
| Día de la semana | 7 | 0,0011 | 0,0011 |
| Semana de la ventana | 13 | 0,0037 | 0,0037 |
| Feriado | 2 | 0,0003 | 0,0003 |
| Día | 90 | 0,0064 | 0,0063 |
| Ciudad | 18 | 0,0051 | 0,0051 |
| Grupo de gestión | 7 | 0,0287 | 0,0287 |
| Primera categoría | 32 | 0,0574 | 0,0573 |
| Tienda | 898 | 0,0101 | 0,0099 |
| Producto | 865 | 0,3460 | 0,3459 |
| Serie (tienda × producto) | 50.000 | 0,4492 | 0,4430 |

Lectura:

- La promoción se concentra por serie (omega² 0,44) y por producto (0,35). Un corte crudo entre días con y sin promoción compara productos distintos. Esto explica la diferencia entre la comparación cruda (+11 %) y la emparejada por serie (+34 %) de `s08`.
- Calendario y tiempo casi no explican la promoción: día de la semana, semana, feriado y día tienen omega² menor que 0,01. En 90 días no se mide estacionalidad anual.
- Por tienda, la proporción de días con marca va de 11 % a 52 % (mediana 37 %), para tiendas con al menos 100 filas. Por grupo de gestión, de 18 % (grupo 3) a 65 % (grupo 4). [Verificado: `s05`]
- Ventas por día de la semana: sábado y domingo tienen 1,17 y 1,19 veces la venta media de cada serie, y lunes a viernes entre 0,87 y 0,98. Explican el 3,9 % de la varianza de la venta diaria dentro de la serie. [Verificado: `s10`]

La asociación no es causal. La comparación dentro de la serie controla producto y tienda, no la demanda del día que dispara la promoción.

---

## Riesgos de fuga y partición propuesta

**Fugas medidas** [Verificado: `s01`, `s05`, `s06`]

| Fuente | Medida | Consecuencia |
|---|---|---|
| `sale_amount` | igual a la suma horaria en el 100 % de las filas | No usar en la predicción del mismo día |
| `stock_hour6_22_cnt` | igual al conteo de estado 1 de 6 a 21 en el 100 % de las filas | Igual que el anterior |
| `hours_stock_status` de la hora h | P(venta cero \| estado 1) = 0,971; P(estado 1 \| venta cero) = 0,311 | El estado de la hora es casi la venta de esa hora: no puede ser entrada para predecir esa hora |
| Clima diario | observado del mismo día; varía entre tiendas de la misma ciudad | Un pronóstico del mismo día debe usar pronóstico, no observado |
| Promoción (`discount`, `activity_flag`) | cambia en 32,9 % y 6,7 % de los pares de días | Si se planifica con antelación es una entrada válida; el conjunto no dice si se conocía antes del día |
| Evaluación solo en horas con stock | las promociones suben la tasa de quiebre (+4,5 puntos, `s03`) | La evaluación en horas con stock selecciona sobre una variable que la promoción mueve: reportar también todas las horas |
| Bloque de prueba del conjunto | contiguo, sin solape ni hueco | Sin purga, el primer día de prueba depende del último de entrenamiento |

**Partición propuesta** (`common.SPLIT_DATES`) [Verificado: `s06`]

| Bloque | Fechas | Días | Series-días | Valores horarios | Quiebre 06 a 21 | Marca | Venta horaria media |
|---|---|---:|---:|---:|---:|---:|---:|
| Entrenamiento | 2024-03-28 a 2024-05-31 | 65 | 3.250.000 | 78.000.000 | 20,6 % | 36,8 % | 0,0400 |
| Purga (sin usar) | 2024-06-01 a 2024-06-07 | 7 | 350.000 | 8.400.000 | — | — | — |
| Validación | 2024-06-08 a 2024-06-25 | 18 | 900.000 | 21.600.000 | 18,4 % | 41,2 % | 0,0472 |
| Prueba (del conjunto, sin usar) | 2024-06-26 a 2024-07-02 | 7 | 350.000 | — | — | — | — |

- Lógica [Inferido]: la purga de 7 días cubre la ventana semanal de rezagos. Los modelos entrenados solo ven el bloque de entrenamiento. La validación queda antes de la prueba del conjunto y después de mayo, y la prueba queda como bloque final sin uso previo.
- Cambio de nivel: la venta horaria media de validación es 17,9 % mayor que la de entrenamiento. Un modelo que aprende el nivel de entrenamiento se equivoca en el nivel. El plan debe decidir cómo tratarlo (ver preguntas).

---

## Líneas base

Validación 2024-06-08 a 2024-06-25 (18 días; 21,6 millones de valores horarios; 900.000 series-días). Los pronósticos de un día usan solo los días anteriores. Los intervalos son bootstrap por serie (B = 200, semilla 0). [Verificado: `s07`]

**Horas, todas**

| Línea base | MAE | IC 95 % | WAPE | Sesgo |
|---|---:|---|---:|---:|
| 0 Siempre cero (referencia) | 0,0472 | [0,0466; 0,0477] | 100,0 % | −100,0 % |
| 1 Misma hora del día anterior | 0,0563 | [0,0560; 0,0566] | 119,5 % | −1,2 % |
| 2 Misma hora, media de 7 días | 0,0495 | [0,0493; 0,0498] | 105,1 % | −4,9 % |
| 3 Misma hora, media de 28 días | 0,0493 | [0,0491; 0,0496] | 104,6 % | −6,8 % |
| 4 Nivel de 7 días × perfil horario del entrenamiento | 0,0500 | [0,0498; 0,0503] | 106,1 % | −4,9 % |

**Solo horas con stock (estado 0), 76,7 % de las horas**

| Línea base | MAE | IC 95 % | WAPE | Sesgo |
|---|---:|---|---:|---:|
| 0 Siempre cero (referencia) | 0,0601 | [0,0594; 0,0608] | 100,0 % | −100,0 % |
| 1 Misma hora del día anterior | 0,0648 | [0,0644; 0,0651] | 107,9 % | −12,3 % |
| 2 Misma hora, media de 7 días | 0,0563 | [0,0560; 0,0566] | 93,7 % | −15,7 % |
| 3 Misma hora, media de 28 días | 0,0558 | [0,0556; 0,0561] | 92,9 % | −17,9 % |
| 4 Nivel de 7 días × perfil horario | 0,0563 | [0,0561; 0,0566] | 93,8 % | −16,7 % |

**Totales diarios** (suma de las 24 horas)

| Línea base | WAPE | IC 95 % | Sesgo |
|---|---:|---|---:|
| 1 Total del día anterior | 41,4 % | [41,0; 41,7] | −1,2 % |
| 2 Media de los 7 días anteriores | 34,0 % | [33,8; 34,3] | −4,9 % |
| 3 Media de los 28 días anteriores | 36,6 % | [36,3; 36,9] | −6,8 % |

Lectura:

- Sobre todas las horas, el pronóstico de cero tiene menor MAE que cualquier promedio. La mediana de la venta horaria es cero, y el MAE premia predecir cero. Con esta distribución, el MAE no debe ser la única métrica. El WAPE y el sesgo sí separan los modelos. [Verificado: `s07`]
- Los promedios subestiman (sesgo de −5 % a −7 % en todas las horas, y de −16 % a −18 % en horas con stock): la validación tiene un nivel 17,9 % mayor que el entrenamiento. [Verificado: `s07`]
- A nivel diario, la media de 7 días da WAPE 34,0 %. El artículo reporta en su tabla 3 WAPE en el orden de 29 % a 32 % para SSA y TFT. Las cifras no son comparables: el artículo predice 7 días a partir de su propia construcción de la serie diaria. [Documentación; no comparable]

---

## Primera mirada: efecto de la promoción, ingenuo frente a ajustado por quiebres

Definiciones (entrenamiento, días válidos):

- Promoción: `activity_flag = 1` frente a `activity_flag = 0`. Sensibilidad: descuento de hasta 0,9 frente a descuento de 1,0.
- Cuatro estimaciones. Cada una es el aumento relativo de la venta en días con promoción frente a días sin promoción.
  - **V1 ingenua**: todas las filas de días con promoción frente a todas las demás, sin igualar serie ni hora.
  - **V2 emparejada**: dentro de cada serie y cada hora, la media en días con promoción frente a la media en días sin promoción de la misma serie y hora, sumada sobre series y horas.
  - **V3 solo en stock**: como V2, usando únicamente horas con estado 0. Quita los quiebres, pero condiciona sobre una variable que la promoción mueve.
  - **V4 demanda recuperada**: como V2, pero cada hora con quiebre toma la media de venta en stock de la misma serie, hora y estado de promoción (si no hay, la de la otra promoción). Supone que el quiebre es aleatorio dado serie, hora y promoción. Eso no está establecido: los quiebres también suben con la demanda.
- Intervalos: bootstrap por serie, B = 500, semilla 0. [Verificado: `s08`]

| Estimación | Marca: aumento | IC 95 % | Descuento ≤ 0,9 vs 1,0: aumento | IC 95 % |
|---|---:|---|---:|---|
| V1 ingenua, venta cruda, todas las horas | +11,1 % | [+10,0; +12,3] | +29,1 % | [+27,6; +30,8] |
| V2 emparejada, venta cruda | +33,6 % | [+33,0; +34,2] | +52,1 % | [+51,2; +53,0] |
| V3 emparejada, solo horas con stock | +39,1 % | [+38,6; +39,8] | +58,0 % | [+57,3; +58,8] |
| **V4 emparejada, demanda recuperada (ajustada)** | **+38,6 %** | **[+38,1; +39,3]** | **+55,9 %** | **[+55,1; +56,7]** |

- V4, marca: mediana de la razón por serie 1,383 (IQR 1,142 a 1,734), frente a 1,511 (IQR 1,193 a 1,996) con la definición por descuento.
- Recuperación (marca): 26,7 millones de horas con quiebre en días válidos; 239.832 celdas (serie, hora, promoción) toman la media de la otra promoción; 2.844 pares serie-hora sin ningún valor en stock se excluyen (de 1,2 millones).

Lectura:

- La comparación cruda subestima el efecto. La mayor parte de la diferencia entre V1 y V4 viene de comparar productos distintos (V1 a V2: 22,5 puntos). Los quiebres explican unos 5 puntos (V2 a V4). Así, lo que el sitio atribuye a que "la cuenta sale mal" por quiebres es, en estos datos, sobre todo un problema de mezcla de productos. [Verificado: `s08`]
- Comparación con el artículo: su mediana de uplift por serie es 1,43 (IQR 1,05 a 2,06). Aquí, 1,38 (IQR 1,14 a 1,73). Hay coincidencia de orden de magnitud. Las definiciones y las muestras no son las mismas, y el artículo controla festivos. [Documentación; comparación propia]
- Los quiebres sí cambian la cifra en la dirección esperada, pero poco (5 puntos sobre 38,6). Lo que mueve el resultado es la definición de promoción (marca frente a descuento: 38,6 % frente a 55,9 %).
- Ninguna de estas cifras es causal. V4 depende de un supuesto no verificado (quiebre aleatorio dado serie, hora y promoción). Sin demanda verdadera, no hay forma directa de validarlo. El artículo valida su recuperación con una simulación de censura sobre horas sin quiebre. Esa simulación no se reprodujo aquí. [Inferido]

---

## Primera mirada: incertidumbre del ranking

No hay identificador de promoción. Las celdas son grupo de gestión (7) × banda de descuento sobre días con marca. Cada celda se compara con los días sin marca de las mismas series, con la estimación V4 (demanda recuperada). Intervalos: bootstrap por serie. Solo se rankean celdas con al menos 30 series (44 de 49). [Verificado: `s09`]

**Por banda de descuento** (todos los grupos juntos)

| Banda | Aumento | IC 95 % | Series | Mediana por serie |
|---|---:|---|---:|---:|
| 0 a 0,5 | +149,1 % | [+142,9; +155,9] | 3.166 | +183,1 % |
| 0,5 a 0,6 | +132,0 % | [+127,9; +136,6] | 6.710 | +129,8 % |
| 0,6 a 0,7 | +70,4 % | [+68,9; +72,2] | 12.637 | +75,5 % |
| 0,7 a 0,8 | +48,1 % | [+47,3; +49,0] | 23.821 | +55,1 % |
| 0,8 a 0,9 | +28,6 % | [+28,1; +29,2] | 35.119 | +31,5 % |
| 0,9 a 0,95 | +17,9 % | [+17,0; +18,8] | 20.719 | +23,5 % |
| 0,95 a 1 | +4,8 % | [+3,9; +5,8] | 16.317 | +9,8 % |

Los 21 pares de bandas no se pisan. El orden coincide con la mediana por serie.

**Por grupo de gestión** (todas las bandas juntas): grupo 4 +105,7 % [+97,0; +114,2] (520 series); grupo 0 +86,9 % [+82,4; +92,1] (1.816); grupo 5 +47,9 % [+46,8; +48,8] (9.349); grupo 6 +37,5 % [+36,7; +38,2] (20.805); grupo 3 +36,9 % [+33,2; +40,5] (1.117); grupo 1 +34,7 % [+31,8; +37,9] (919); grupo 2 +25,1 % [+24,0; +26,3] (5.934). De 21 pares, 3 se pisan. [Verificado: `s09`]

**Por celda** (grupo × banda)

- 44 celdas rankeadas. De 946 pares, 125 se pisan (13 %) y 821 se separan.
- La celda de mayor aumento (grupo 0, de 0 a 0,5) tiene +576,6 % [+525,8; +631,5] con 605 series. Solo se pisa con una celda (grupo 1, de 0 a 0,5, con 46 series).
- Celda con aumento negativo: grupo 2, banda de 0,95 a 1, −16,5 % [−18,3; −14,8] (3.275 series, 9.544 días). Son días marcados con casi ninguna rebaja: pueden marcar otra actividad. [Verificado: `s09`; causa Inferida]

Lectura:

- Un ranking por nivel de descuento se sostiene: las bandas profundas tienen mayor aumento y no se pisan. Por grupo, el orden tiene pares que se pisan (3 de 21).
- Los aumentos por encima de +100 % vienen de bandas profundas con pocas series, y el cociente de sumas da más peso a las series con más venta. Son descriptivos y deben revisarse antes de publicarse. [Inferido]
- Los intervalos tratan cada serie como independiente y no tienen en cuenta los choques comunes de un día (por ejemplo, un fin de semana o un feriado). Son optimistas. Las celdas comparten series, así que el conteo de pares que se pisan es aproximado. [Inferido]

---

## Literatura

| Trabajo | Qué dice (lo leído) | Uso en el proyecto | Estado |
|---|---|---|---|
| Wang et al. (2026), arXiv:2505.16319 v5 | Conjunto y su tarea de recuperación de demanda latente. Dos etapas: recuperar la demanda en quiebres y pronosticar con la demanda recuperada. Uplift mediano de promociones 1,43 (IQR 1,05 a 2,06) tras controlar festivos. Tabla 2: WAPE de TimesNet 27,62 % en simulación MNAR | Definición del conjunto; cifras a contrastar (quiebres por hora, uplift) | [Documentación; autores del conjunto, no verificado de forma independiente] |
| Brodersen et al. (2015), AOAS 9(1), arXiv:1506.00356 | Causal impact con modelo de espacio de estados y control sintético (serie de control) | Candidato para un efecto con control, si el plan busca algo más que la comparación emparejada | [Documentación] |
| Gundem y Qi (2026), arXiv:2504.09831 | Política de inventario y precio con ventas censuradas por inventario | Marco de la censura por inventario | [Documentación] |
| Wang, Jiang y Chen (2026), arXiv:2610.34547 | Estimación de demanda con sustitución por quiebre (modelo logit multinomial). Tiempos de quiebre no observados | Marco de referencia reciente de la censura | [Documentación] |
| Verma y Gupta (2026), arXiv:2611.12665 | Elasticidad y lift de promoción; verosimilitud Tobit para censura por quiebre; experimento de 39 SKU | Referencia de método para censura y lift; poco peso | [Fuente secundaria] |
| Código de referencia (GitHub, Dingdong-Inc/frn-50k-baseline) | Líneas base TimesNet, ImputeFormer, SAITS, iTransformer, GPVAE, CSDI, DLinear y SSA | Referencia de construcción de la serie y de métricas WAPE/WPE | [Documentación] |

Huecos: Amjad y Shah (2017) no se abrió (ACM 403). Otros textos clásicos de demanda censurada no se buscaron.

---

## Contradicciones con el sitio

Texto de `marca-personal/src/i18n/projects/promotion-lift.ts` (es y en), leído sin modificar. Cada fila compara una afirmación concreta con lo que permiten los datos.

| Texto del sitio | Lo que muestran los datos | Redacción sugerida |
|---|---|---|
| "Un comercio de perecederos lanza descuentos todas las semanas" | Hay promoción en alguna serie cada una de las 13 semanas, pero solo el 50,4 % de las series-semana tiene una (`s10`, `s04`) | "Cada semana hay promociones, pero cada producto tiene una promoción en la mitad de sus semanas" |
| "cuando un producto se agota las ventas caen por falta de stock y no por la promoción" y "la cuenta sale mal" | Los quiebres ocultan unos 5 puntos del efecto (V2 a V4). La diferencia grande viene de comparar productos distintos: +11 % cruda frente a +34 % emparejada (`s08`) | Decir que el error principal es la mezcla de productos y que el quiebre resta unos 5 puntos |
| "dataset público de ventas por hora en 898 tiendas" | Correcto: 898 tiendas (`s01`) | Mantener |
| "50 mil series de ventas por hora, tienda y producto" | Correcto: 50.000 pares tienda × producto con 90 días (`s01`, `s02`) | Mantener |
| "898 tiendas en 18 ciudades" | Correcto: 18 ciudades (`s01`) | Mantener |
| "863 productos perecederos" | Hay 865 identificadores de producto en los datos y en la tarjeta. El artículo dice 863 (`s01`) | "865 productos" (con la tarjeta como fuente) |
| "Ventas por hora" | Las ventas están normalizadas por un coeficiente no publicado: no tienen unidades (tarjeta, `s01`) | "Ventas por hora, en unidades normalizadas" |
| "Descuento, de 0,5 a 1" | Rango medido de 0,0 a 1,088. Fuera de 0,5 a 1 hay 31.959 filas de entrenamiento (0,71 %): 16.039 con 0, 15.886 entre 0 y 0,5 y 34 por encima de 1 (`s04`) | "Descuento como factor (1 = sin descuento); hay valores fuera del rango que se tratan aparte" |
| "Marca de promoción" | Hay dos campos que no coinciden: 654.330 filas con descuento y sin marca, y 38.378 con marca y sin descuento (`s04`) | Elegir y explicar cuál define la promoción |
| "Estado del stock, hora por hora" | Correcto: 24 horas, 0 o 1 (`s01`, `s02`). De noche, el estado es 1 en 35 % de las horas, con venta casi nula | Mantener, y aclarar que de noche el estado casi no censura demanda |
| "Una hora sin stock vende menos porque no hay qué vender" | La caída es real: 97,1 % de las horas sin stock tienen venta cero, y la venta cae 89,5 % frente a la misma hora con stock. No se separa la demanda perdida (`s02`, `s03`) | Mantener, con "la venta cae" y no "la demanda se pierde" |
| "Las ventas se explican por el descuento, la marca de promoción y los efectos de la hora y del día" | Efecto de la hora: la venta media varía 48 veces entre la hora más baja y la más alta. Día de la semana: fin de semana +17 % a +19 %, pero explica solo 3,9 % de la varianza. Efecto de la promoción: medido en `s08` (`s10`) | Mantener; el efecto del día es pequeño |
| "Sin precio ni canal en el dataset" | Correcto: no hay columna de precio ni de canal (`s01`) | Mantener |
| Herramienta: "statsmodels" | No se usó en esta investigación. No está en el landing ni en `LANDING-EXPANSION.md` (`s01`, `s05`) | Usar scikit-learn o numpy, o registrar `statsmodels` en `LANDING-EXPANSION.md` si el plan la usa |
| "dos promociones cuyos intervalos se pisan no se presentan como distintas" | Se pisan 125 de 946 pares de celdas (13 %) (`s09`) | Aplicar la regla y decir cuántos pares no se distinguen |
| "Un ranking de qué promociones venden, por categoría y descuento" | No hay identificador de promoción: el ranking es por celda (grupo y banda), no por promoción (`s09`) | "Ranking por categoría y nivel de descuento" |
| "promociones ordenadas por lo que suman" | El efecto medido es relativo (en %). Las ventas normalizadas no permiten ordenar por unidades (`s08`, `s10`) | "ordenadas por cuánto suben las ventas (en %)" |
| "para los equipos comerciales ... en línea o en tienda" | El artículo dice que las ventas por hora vienen de sistemas de pedidos en línea (sección 3.1), desde un modelo de almacén de cercanía de 3 km (sección 1). No hay campo de canal (`s01`) | Decir "pedidos en línea" y no "en tienda" |
| "Cada día un flujo carga las ventas por hora" | El conjunto es una extracción fija de 97 días, sin actualización diaria. El flujo diario es un diseño, no un dato medido | Presentarlo como diseño del proyecto |

---

## Riesgos y huecos

1. **Un solo operador y un solo país.** El artículo describe 898 tiendas en 18 ciudades de China, entre marzo y junio de 2024, con pedidos en línea. El sitio no dice nada de esto. La generalización a otros comercios no está medida. [Verificado: artículo, sección 3.1]
2. **La curva de quiebres del artículo no se reproduce.** Quiebres a las 6 h y a las 20 h difieren de lo que dice el artículo. Se usa la medición propia; la sección 3.3 del artículo no describe cómo calcula esas tasas por hora. [Verificado: `s02`]
3. **Zona horaria no documentada.** Las horas 0 a 23 se leen como hora local por las horas pico. El plan debe confirmarlo o declararlo como supuesto. [Inferido]
4. **Venta normalizada sin unidades.** Las medidas son relativas. No hay precio, así que no hay ingreso ni margen. [Verificado: tarjeta]
5. **Identificación de la promoción.** Dos campos que no coinciden (`activity_flag` y `discount`). La marca sin rebaja da un efecto negativo en el grupo 2 (−16,5 %, `s09`): la marca puede incluir otra actividad. [Verificado; causa Inferida]
6. **Anomalías en el descuento.** Descuento 0 en 8 productos (239 series, venta mediana 15), descuento entre 0 y 0,5 en 15.886 filas y descuento mayor que 1 en 34 filas. Se excluyen de las estimaciones. Qué son no está documentado. [Verificado: `s04`]
7. **Quiebre no verificado de forma independiente.** El artículo habla de anotaciones de quiebre "verificadas" (sección 1) y no describe cómo se verificaron. No hay forma de confirmarlo con estos datos. [Documentación]
8. **Quiebre nocturno.** De 0 a 5 y de 22 a 23, el estado es 1 en 35 % de las horas, con ventas casi nulas. Puede ser cierre o falta de reposición, no censura. [Inferido]
9. **Demanda recuperada sin verdad de referencia.** V4 depende de un supuesto no verificable. Con una simulación de censura (como la del artículo) se podría validar; no se hizo. [Inferido]
10. **Un solo bloque de validación de 18 días y 90 días en total.** No hay estacionalidad anual. Los intervalos por serie son optimistas frente a choques comunes de un día. [Inferido]
11. **Latencia del dato.** La tarjeta no dice cuándo se cierra cada hora ni cuándo llega el dato de quiebre. Esto decide qué entradas son legítimas para predecir una hora. [Hueco declarado]
12. **Librerías fuera del landing.** `pyarrow` ya está registrado en `LANDING-EXPANSION.md`; falta agregar el proyecto 06. `statsmodels` aparece en el sitio, no está registrada y no se usó aquí. [Verificado]
13. **Licencia.** CC BY 4.0: atribución a Dingdong-Inc y enlace a la licencia. Uso comercial permitido según la tarjeta. [Verificado]

---

## Preguntas abiertas para el plan

1. ¿La promoción es `activity_flag` (la marca del sitio), el descuento (por debajo de 0,9) o las dos cosas por separado?
2. ¿Qué se hace con las filas de descuento 0 (8 productos), con las de 0 a 0,5 y con las de descuento mayor que 1?
3. ¿Se acepta la partición propuesta (entrenamiento hasta 2024-05-31, purga de 7 días, validación de 2024-06-08 a 2024-06-25, prueba del conjunto), o se usa validación cruzada por bloques de tiempo?
4. ¿Qué métrica para la venta horaria: WAPE diario, WAPE horario en horas con stock, o una métrica de cuantiles? El MAE horario premia predecir cero.
5. ¿La demanda recuperada es la imputación condicional (V4), un modelo de recuperación del artículo, o ambos? ¿Cómo se valida sin verdad de referencia?
6. ¿Se corrige "en línea o en tienda" en el sitio, dado que el artículo dice pedidos en línea?
7. ¿El ranking se presenta por celda (grupo y banda) o se busca otra unidad?
8. ¿Se confirma la zona horaria de las 24 horas, o se declara como supuesto?
9. ¿El efecto por nivel de descuento se presenta como asociación dentro de la serie, no como causal?
10. ¿`statsmodels` se usa (está declarada en el sitio) o se quita de la lista de herramientas del proyecto?
11. ¿Se incluye en el sitio la cifra del artículo (1,43×), dado que con este método se mide 1,38 con otra definición?
12. ¿El periodo de 90 días basta para el proyecto, o se busca otra fuente con un año completo?

---

## Scripts y salidas

Los scripts están en `research/`. Se ejecutan en orden, desde la carpeta del proyecto, con `python -I research/<script>.py`. Los datos intermedios van a `data/interim/research/` (ignorado por git), y las salidas de consola a `data/interim/research/logs/`.

- `s00_download.py`: descarga y verificación de los Parquet y de la tarjeta (`data/raw/manifest.json`).
- `s01_parse_verify.py`: esquema, filas, claves, jerarquía, identidades entre campos, anomalías de descuento, conteos de la prueba.
- `s02_structure.py`: grano, series, fechas, perfil horario, cifras del artículo frente a los datos.
- `s03_censoring.py`: frecuencia de quiebres, venta en quiebre frente a stock, quiebres y promoción.
- `s04_promotions.py`: codificación de la promoción, anomalías, cobertura, rachas, cambios.
- `s05_confounding.py`: eta² y omega² de la promoción frente a tiempo, tienda, producto y serie; feriados.
- `s06_leakage_split.py`: fugas medidas y bloques de la partición propuesta.
- `s07_baselines.py`: líneas base naive en validación, por hora y por día.
- `s08_promo_effect.py`: efecto de la promoción, V1 a V4, con sensibilidad.
- `s09_ranking_intervals.py`: celdas grupo × banda, intervalos por serie, pares que se pisan.
- `s10_site_claims.py`: cifras para la tabla de contradicciones.
- `common.py` (lectura y tensores; partición propuesta en `SPLIT_DATES`) y `estimators.py` (estimadores compartidos por `s08` y `s09`).

Preguntas que no se pudieron responder:

- Amjad y Shah (2017), texto completo: ACM bloquea el acceso.
- Qué son las filas con descuento 0 y las de descuento mayor que 1.
- Si la marca `activity_flag` representa solo promociones o también otras actividades.
- La zona horaria de las 24 horas.
- Latencia real de los datos de quiebre y de venta en el sistema de origen.
- Efecto de la promoción sobre la demanda verdadera, sin supuestos de recuperación.
- Estacionalidad anual: 90 días no alcanzan.
