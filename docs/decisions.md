# Registro de decisiones

Una entrada por decisión, con sus siete campos: Contexto, Opciones, Decisión, Motivo, Afecta, Quién y Estado. Donde había un solo camino razonable, «Opciones» lo dice y explica por qué. Las propuestas del agente de planificación (Opus) quedan para revisión del dueño; las del dueño citan el registro del documento de seguimiento (`odd/tasks/portfolio-projects.md`). El dueño pidió autonomía (S12): cada pregunta abierta de research.md tiene aquí un valor por defecto razonable y reversible, y solo las elecciones de producto que le pertenecen van a su lista (plan, sección 29). Las cifras salen de `research.md`, de los documentos del proyecto 05 y de la comprobación del agente de planificación (`requirements.md`, sección 4), que leyó **solo `data/raw/train.parquet`** y nunca abrió `eval.parquet`, la semana de prueba; ninguna métrica se calculó sobre la prueba. Sus scripts y salidas se versionan en `research/plan/` (`p01_structure.py` descuentos, estados del día, noche y momento de los quiebres; `p02_recovery.py` censura sintética y error horario; `p03_recovery_mass.py` sesgo de la masa por estado del día; `p04_effect.py` contrafactual, efectos, intervalos, réplica y pronósticos; `p05_forecast_value.py` el aumento de la celda frente a uno solo, convergencia del IPF y R2 frente a R1; `p06_recovery_choice.py` la elección por la masa por serie; `p07_band_order_gap.py` el orden de las bandas y el intervalo de recuperado menos crudo; salidas `p01.out` a `p07.out`), y cada uno se corre desde la carpeta del proyecto con `.venv\Scripts\python -I research/plan/<script>.py`.

Correspondencia con las doce preguntas abiertas de research.md: 1 → D04; 2 → D03; 3 → D14; 4 → D15 y D07; 5 → D06-D08; 6 → D38; 7 → D13; 8 → D05; 9 → D09; 10 → D32; 11 → D37; 12 → D14.

Estados: **vigente**, **pendiente del dueño**, **reemplazada por Dxx**.

---

## D01 Enfoque: un efecto descriptivo con su réplica en la semana siguiente, con criterios que pueden no cumplirse y el resultado esperado dicho antes

- **Contexto**: el sitio promete medir cuánto suma cada promoción después de recuperar la demanda que esconden los quiebres (S9). No hay identificador de promoción, ni precio, ni un experimento: la promoción se asigna por serie y por producto (eta² 0,45 y 0,35; research.md). En la comprobación del planificador, el orden de las celdas se repite del entrenamiento a la validación (Spearman 0,921) pero su nivel no (42,5 % de celdas consistentes), y el aumento de la celda mejora un pronóstico frente a un aumento único pero no frente a la última semana de la serie (`p04`, `p05`).
- **Opciones**: (a) un modelo de pronóstico de la demanda con la promoción como variable, juzgado por su error; (b) un efecto dentro de la serie, ajustado por la hora y el día, con su intervalo, su ranking y una comprobación una sola vez en la semana de prueba: si el orden se repite, si el nivel se repite y si el aumento agrega información a un pronóstico, con criterios fijados antes; (c) solo la tabla descriptiva, sin comprobación.
- **Decisión**: (b), con C01-C10 de `requirements.md`, sección 8.1 (D16), y lo esperable escrito: probablemente no se cumplan C06 ni C09.
- **Motivo**: lo que el equipo comercial necesita es qué combinaciones vendieron más y cuánto confiar en ese orden; (a) responde otra pregunta y el pronóstico ingenuo ya gana (`p04`); (c) no dice si el resultado sirve para la semana siguiente.
- **Afecta**: todo el proyecto; `requirements.md`, sección 8.1; `fact_evaluation_summary`; el README; el sitio.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D02 Fuente: los dos Parquet del commit `c374e859` fijados por tamaño y SHA-256; el flujo solo lee archivos locales

- **Contexto**: `research/s00_download.py` ya baja por HTTPS, sin cuenta, los dos Parquet fijados al commit del conjunto, compara tamaños y los identificadores LFS de la API y calcula el SHA-256 (research.md). Las huellas: `train.parquet` 106.436.287 bytes, `6706832d…5a3d`; `eval.parquet` 8.440.124 bytes, `1b118840…960e`.
- **Opciones**: (a) una descarga endurecida dentro del paquete, con lista de hosts, redirecciones y topes (la U04 del proyecto 04); (b) la descarga queda en el script de la investigación y el flujo comprueba tamaño y huella antes de leer un byte del contenido.
- **Decisión**: (b). `[source]` con rutas, tamaños y huellas; si un archivo falta o no coincide, `fetch_source` termina con `SourceError` (salida 3) sin escribir nada y nombra el runbook R1, que dice cómo correr `s00`. La descarga dentro del paquete queda como pendiente del dueño.
- **Motivo**: hay valores de confianza medidos (la investigación los comprobó contra la API); sin descarga en el flujo desaparece la superficie de red, y el riesgo queda en la lectura (D03, D05).
- **Afecta**: `ingest.py`; `config/pipeline.toml [source]`; V01; runbook R1; README «Cómo correrlo».
- **Quién**: agente de planificación.
- **Estado**: vigente; la descarga en el paquete, pendiente del dueño (plan, sección 29, ítem 6). **Nota del 2026-11-17 (U04)**: el esquema real de los dos archivos tiene **19** columnas (7 de identificadores, `dt`, los 9 campos diarios y las 2 listas; `pq.read_schema` de los dos), no 18 como dice V02 del plan por una suma mal hecha; `schema.SOURCE_SCHEMA` es el real, con las listas como `list<element: double>` y `list<element: int64>`, `stock_hour6_22_cnt`, `holiday_flag` y `activity_flag` como int32.

## D03 Las filas de descuento anómalo: 0 y mayor que 1 se excluyen y se cuentan; de 0 a 0,5 es la banda más profunda

- **Contexto**: 16.039 filas con descuento 0 (239 series, 8 productos, venta diaria mediana 15 frente a 0,7; en 114 series todos los días); 15.886 entre 0 y 0,5 con marca en el 99,99 % (venta mediana 1,6); 34 mayores que 1 (hasta 1,088) sin marca; 38.378 con marca y descuento 1 (research.md, `p01`). Qué son no está documentado.
- **Opciones**: (a) excluir todo lo que sale de 0,5 a 1; (b) excluir el 0 y lo mayor que 1, y conservar de 0 a 0,5 como una banda; (c) conservarlo todo.
- **Decisión**: (b). `anomalous` (V20, V21) se cuenta, se muestra en Datasets y se excluye del efecto y del control; la banda 0 es `(0; 0,5)`, rotulada «más del 50 %», con su tamaño a la vista (V22); la marca con descuento 1 cae en la banda 6 (V23).
- **Motivo**: un descuento 0 no es una rebaja interpretable (precio cero o código de otra cosa) y vende 20 veces más que el resto, lo que distorsionaría cualquier cociente; lo mayor que 1 son 34 filas; de 0 a 0,5 está marcado casi siempre, es coherente con una liquidación y research.md midió un aumento ordenado con las demás bandas.
- **Afecta**: `days.py`; V20-V23; `data.json` `anomalies`; el diccionario.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D04 La promoción es la marca; el control es un día sin marca y sin rebaja; el descuento sin marca se mide aparte

- **Contexto**: `activity_flag` marca el 37,8 % de los días válidos y cae sobre descuentos de 0,5 a 0,9; 654.330 filas tienen descuento y no marca, 38.378 marca y no descuento (research.md). «Sin rebaja» es el 1,0 exacto en 2.181.121 filas (`p01`). Con el umbral 0,999, las series-días son 37,84 % `promo`, 47,69 % `regular`, 14,11 % `unflagged_cut` y 0,36 % `anomalous`; 39.661 series tienen días de los dos primeros (`p01`). Sobre el entrenamiento, el aumento recuperado es +60,72 % con `regular` como control y +45,01 % con cualquier día sin marca; los días `unflagged_cut` venden +25,52 % ([+23,17; +28,31]) más que los `regular` (`p04`).
- **Opciones**: (a) la marca contra cualquier día sin marca (research.md, V4); (b) el descuento (por debajo de 0,9) contra el resto; (c) cuatro estados: la marca es la promoción, el control es un día sin marca ni rebaja, el descuento sin marca tiene su propio efecto y lo anómalo se excluye; (d) las dos definiciones como dos rankings.
- **Decisión**: (c), con `regular_min_discount = 0,999` (el 0,999 de 3.376 filas cuenta como sin rebaja). El control con cualquier día sin marca es la variante `any_flag0` de C10.
- **Motivo**: (a) mete en el control días con rebaja que venden 25 % más, y baja el aumento 16 puntos; (b) ignora lo que el sitio llama «marca de promoción» y mezcla rebajas mínimas; (c) responde «marca, descuento o las dos» con las dos cosas medidas y sin contaminar el control; (d) duplica el producto sin aclarar nada que (c) no aclare.
- **Afecta**: `days.py`; V24; `effect.py`; `fact_band_effect`; `algorithms.json` `bands[].unflagged`; el sitio (fila 5).
- **Quién**: agente de planificación.
- **Estado**: vigente; el umbral del control, pendiente del dueño (plan, sección 29, ítem 3).

## D05 Las horas de 06 a 21, la hora local supuesta, el día completo al cerrar y los campos diarios fuera

- **Contexto**: la noche (0 a 5 y 22 a 23) trae el 4,81 % de la venta y está sin stock el 34,9 % de sus horas (research.md, `p01`): puede ser cierre, no censura. `stock_hour6_22_cnt` cuenta de 6 a 21. La tarjeta no declara la zona horaria; los picos de 9 y 16 h apuntan a hora local. `sale_amount` y `stock_hour6_22_cnt` son sumas de las horas (fuga si se usan el mismo día); el clima es el observado del día y varía entre tiendas de una misma ciudad. El conjunto no dice cuándo llega cada dato.
- **Opciones**: para las horas, (a) las 24 o (b) 06 a 21; para el tiempo, (a) declarar una latencia por hora o (b) tratar el día como completo al cerrar; para los campos diarios, (a) usarlos como entradas o (b) dejarlos en la lectura.
- **Decisión**: horas de 06 a 21 (16 por día) en la recuperación, el efecto y los pronósticos; la noche se cuenta (I01) y no se recupera. Hora local como supuesto. Un día se procesa entero cuando cierra (`as_of` a las 00:00 del siguiente). `sale_amount`, `stock_hour6_22_cnt` y el clima no pasan de la lectura (V26 y V27 comprueban las identidades y los descartan); la marca y el descuento se suponen conocidos antes del día (la promoción se planifica), como supuesto declarado.
- **Motivo**: recuperar la noche inventaría demanda en horas cerradas; la recuperación y el efecto son retrospectivos (el día ya pasó), así que no hay una latencia que modelar dentro del día; `sale_amount` contiene la venta de las horas que una máscara oculta, de modo que usarlo daría una recuperación perfecta en la simulación e imposible en un quiebre real (D19).
- **Afecta**: `schema.FORBIDDEN_COLUMNS`; `cube.py`; RNF06; la ficha (limitaciones); el diccionario.
- **Quién**: agente de planificación.
- **Estado**: vigente; la zona horaria, pendiente del dueño (plan, sección 29, ítem 5).

## D06 Recuperación: cuatro métodos, de cero a gradient boosting

- **Contexto**: research.md recuperó con la media de la serie, la hora y el estado de promoción (V4) y dejó la validación pendiente. El artículo del conjunto usa modelos profundos (TimesNet, SAITS y otros). Los quiebres son colas: el 86,41 % sigue sin stock hasta las 21 h, con la primera hora en mediana a las 15 h (`p01`).
- **Opciones**: (a) solo V4; (b) R0 cero, R1 media de la serie, la hora y el estado, R2 R1 escalada por el nivel observado del mismo día con contracción κ, y R3 `HistGradientBoostingRegressor` con pérdida de Poisson; (c) los modelos del artículo.
- **Decisión**: (b), con R2 `k = (O + κ·m) / (E + κ·m)` y `κ ∈ {0,25; 0,5; 1; 2}`; R3 con la hora, el corte, R1, O, E, m, la marca, la profundidad, el día de la semana y el grupo, ajustado sobre 150.000 máscaras de cola del entrenamiento.
- **Motivo**: R2 usa la única información del día que un quiebre deja (las horas con stock anteriores) y es explicable; R3 es la comparación de aprendizaje automático que el landing declara (scikit-learn); (c) sale de las tecnologías del landing (PyTorch no está; S5) y pide horas de cómputo para una mejora no medida.
- **Afecta**: `recovery.py`; `[recovery]`; `fact_recovery_check`.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D07 Cómo se valida la recuperación sin verdad: censura sintética de horas con stock, juzgada por la masa por serie

- **Contexto**: en una hora sin stock no se observa la demanda. La comprobación del planificador ocultó la cola del día (de un corte sacado de la distribución real de la primera hora sin stock hasta las 21 h) en las series-días con stock todo el día, donde la venta oculta es la verdad. A nivel de la hora, ningún método supera a cero: WAPE 100 % para cero y de 108 % a 116 % para los demás, porque la venta horaria es intermitente (`p02`). Sumada por serie, R2 con κ = 0,25 da 30,06 % en V1 y 31,16 % en V2, frente a 35,38 % y 38,44 % de R1 (`p06`).
- **Opciones**: (a) MAE o WAPE por hora; (b) WAPE de la masa oculta por serie-día; (c) WAPE de la masa oculta por serie, con el sesgo total, el sesgo por estado del día y el sesgo que eso induce en el aumento; (d) ocultar horas al azar.
- **Decisión**: (c) como métrica de elección y de C01-C03; la máscara es de cola (`mask_tail`); la de tres horas al azar es un contraste (C10). Se publica lo que la simulación **no** valida: los quiebres reales llegan en días de más demanda, y las series-días con stock todo el día no representan esa selección; el accesorio sintético (D34) sí la planta, para que las pruebas vean el sesgo que deja.
- **Motivo**: el efecto suma la demanda por serie y por celda; una métrica horaria premia el cero y castigaría cualquier recuperación (`p02`); (c) mide lo que el aumento usa y el sesgo por estado (`p03`: de −0,75 % a −5,91 % en el aumento) es el que lo movería.
- **Afecta**: `masks.py`; `recovery.py`; `mask_checks`; C01-C03; la ficha.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D08 La elección: en V1 con métodos ajustados en el entrenamiento, vista previa en V2, reajuste con los 90 días

- **Contexto**: con la máscara de V1 (semilla 0), el menor WAPE por serie es R2 con κ = 0,25 (30,06 %), el borde inferior de la grilla; R3 da 31,99 %. En V2, R2 (κ = 0,25) menos R1: de −7,52 a −7,03 puntos; menos R3: de −4,30 a −3,90; R3 tiene un sesgo de −8,05 % en V2 (`p06`). La lección A2 del proyecto 05: una condición medida sobre un modelo reajustado con ese bloque está dentro de la muestra.
- **Opciones**: (a) elegir en toda la validación; (b) elegir en V1 con todo ajustado en el entrenamiento, mostrar V2 sin elegir nada, reajustar con los 90 días para la prueba; (c) validación cruzada por bloques de días.
- **Decisión**: (b). Empate a 10⁻⁶: el más simple (R1, R2 con κ creciente, R3). Las cifras de V1 y V2 se guardan con `fit_blocks = train` y nunca se recalculan con el método reajustado. κ no se reajusta. Si la elección cae en el borde de la grilla, se dice.
- **Motivo**: (b) deja una cifra fuera de muestra honesta (V2) y la prueba; (a) no la deja; (c) agrega complejidad sin un uso: la elección es de un parámetro.
- **Afecta**: `recovery.choose`; `launch.py`; el sello (`recovery`); `fact_recovery_check`.
- **Quién**: agente de planificación.
- **Estado**: vigente. **Nota del 2026-11-17 (U09, lanzamiento en seco sobre `train.parquet`; `eval.parquet` no se abre)**: otra vez gana R2 con κ = 0,25, en el borde inferior de la grilla (`grid_edge = lower` en el sello). WAPE por serie en V1: R1 38,11 %, R2 32,44 % (κ 0,25), 32,93 % (0,5), 34,15 % (1), 35,52 % (2) y R3 33,99 %; en V2: 37,47 %, 31,57 %, 32,14 %, 33,43 %, 34,83 % y 35,19 %, con R2 (κ 0,25) menos R1 de −6,13 a −5,67 puntos en V2. La razón R2 / R1 en V1 es 0,851, lejos del umbral 0,5 de M01. Las cifras de `p06` (35,38 %, 30,06 % y 31,99 % en V1) son menores porque la máscara del plan (sección 11) solo toma series-días `promo` o `regular` y `p06` también tomaba los `unflagged_cut`, y porque aquí cada día de V1 usa su turno del mismo generador; el orden de los métodos, el borde de la grilla y el sesgo de R3 en V2 (−8,69 % frente a −8,05 %) son los de `p06`. En V1, el sesgo de la masa recuperada por R2 es +6,52 % en días `promo` y +14,27 % en los demás (sesgo que induce en el aumento: −6,8 %); en V2, −3,78 % y +6,14 % (−9,3 %).

## D09 El efecto y su control de la confusión: un contrafactual de la misma serie y la misma hora, ajustado por el día del grupo, con IPF

- **Contexto**: la promoción se asigna por serie y producto, casi nada por calendario (research.md); la venta del fin de semana es 17 % a 19 % mayor; la validación vende 17,9 % más que el entrenamiento. La cuenta cruda da +11,1 % y la emparejada por serie y hora +33,6 % (research.md). El sitio declara statsmodels para «un modelo del efecto».
- **Opciones**: (a) el cociente emparejado por serie y hora de research.md; (b) una regresión de Poisson con efectos fijos de serie-hora y de grupo-día en statsmodels; (c) el mismo modelo de Poisson multiplicativo, `m(s, h, d) = a(s, h) · b(g, d)`, ajustado solo sobre los días `regular` por ajuste proporcional iterativo, y el aumento como observado sobre contrafactual (un estimador por imputación); (d) un modelo de series de tiempo con control sintético (Brodersen et al., 2015).
- **Decisión**: (c), con 30 iteraciones (cambio máximo de `b` entre 30 y 60: 3,65 · 10⁻¹⁴; `p05`). Todo aumento se publica como una asociación dentro de la serie, ajustada por la hora y por el día del grupo, nunca como causal.
- **Motivo**: (c) controla lo que (a) controla (producto, tienda, hora) y además el día de la semana, los feriados, el cambio de nivel y los choques comunes de cada grupo, sin ajustar 1,2 millones de efectos fijos con una matriz (lo que (b) necesitaría y statsmodels no maneja a esta escala **[Inferido]**); el IPF es el estimador de máxima verosimilitud de ese modelo y se escribe con NumPy en unas decenas de líneas; (d) es para una serie tratada, no para 35.000. No controla la razón por la que se lanzó la promoción (si se esperaba más demanda), y eso se dice.
- **Afecta**: `effect.py`; `fact_*_effect`; el sitio (filas 8 y 9); D32.
- **Quién**: agente de planificación.
- **Estado**: vigente. **Nota del 2026-11-17 (U08)**: `effect.day_factor` (el `b` de un día nuevo con `a` fijo) suma en el numerador solo las series que tienen `a`, como el denominador; `research/plan/p04_effect.py` sumaba también las series sin día `regular` en el período de ajuste (4.254 en el entrenamiento real) en el numerador y no en el denominador, lo que infla el `b` de su grupo en la réplica y en la prueba. Las cifras de réplica y de pronóstico de `p04` y `p05` pueden diferir por eso. El remuestreo toma como población los días del bloque que se evalúa (no los 90 del arreglo, como `p04`). **Nota del 2026-11-17 (U09, lanzamiento en seco sobre los 90 días reales)**: `effect.py` reproduce `p04` donde se puede comparar: con el contrafactual ajustado en el entrenamiento, el aumento crudo de las series-días con promoción del entrenamiento es +56,52 % sobre 34.603 series y 965.528 series-días, igual que `p04`. Dos hechos nuevos. **(1) El nivel del aumento depende de la ventana con que se ajusta `a`**: sobre esas mismas series-días del entrenamiento, el aumento crudo es +56,52 % con el ajuste del entrenamiento y +47,86 % con el ajuste de los 90 días (en la purga +59,53 %, en V1 +62,98 %, en V2 +60,07 %, todo con el ajuste de los 90 días); el aumento publicado de los 90 días es +51,98 % crudo [+49,68; +54,78] y +52,87 % recuperado [+51,20; +54,91]. El modelo no tiene tendencia por serie (solo el nivel del grupo y el día, `b(g, d)`), de modo que una serie que se promociona en un período y no en otro se compara con su nivel del otro período. El intervalo de dos vías (de unos ±2,5 puntos) no cubre esta sensibilidad de unos 8 puntos: el sitio, la ficha y el resumen deben decir que el nivel del aumento es una descripción del período y de la ventana, no solo que el intervalo es ancho. No cambia ninguna decisión del plan; queda para el dueño y para la evaluación independiente. **(2) La corrección de `day_factor` mueve la réplica**: con `a` del entrenamiento, el aumento crudo de la validación es +69,09 % con el `b` corregido y +63,56 % con el de `p04` (3,29 % de las series-días `regular` de la validación son de series sin `a` y inflaban el `b` de su grupo en 3,4 %). Con R2 (κ = 0,25): aumento recuperado del entrenamiento +60,03 % (`p04`, con κ = 1, +60,72 %), de la validación +61,74 % [+58,01; +65,20] (`p04`, +52,16 %); correlación de Spearman de las celdas entre los dos períodos 0,934 sobre 40 celdas (`p04`, 0,921), proporción de celdas cuyo intervalo de la diferencia contiene 0 de 55,0 % (`p04`, 42,5 %), proporción de aumentos de la validación dentro del intervalo del entrenamiento 20,0 % (`p04`, 20,0 %) y correlación de la profundidad con el aumento de las bandas en la validación 0,929 (igual a `p07`). En el lanzamiento, los quiebres esconden solo 0,90 puntos de los 52,87 (`p07`: 4,20 sobre el entrenamiento), porque el aumento recuperado depende de lo mismo que el crudo. Publicado sobre los 90 días: 47 celdas con series-días de 49, 43 ordenadas (con al menos 30 series), 5 grupos indistinguibles y 183 de 903 pares que se pisan (20,3 %; `p04`, con el entrenamiento solo, 157 de 903); bandas recuperadas de +100,22 % (0 a 0,5) y +139,57 % (0,5 a 0,6) a +13,29 % (0,95 a 1), con la banda 1 por encima de la 0 como en `p07`.

## D10 El aumento: observado sobre contrafactual, en las horas de 06 a 21, en dos versiones

- **Contexto**: el sitio promete el efecto «dos veces, con las ventas crudas y con la demanda corregida». Sobre el entrenamiento, +56,52 % crudo y +60,72 % recuperado; la diferencia, +4,20 puntos con un intervalo pareado de [+2,73; +5,76] (`p04`, `p07`). La recuperación agrega 20,15 % a la venta cruda de 06 a 21 (`p04`).
- **Opciones**: (a) la mediana del cociente por serie (research.md: 1,38); (b) el cociente de sumas `Σ observada / Σ contrafactual − 1`; (c) un efecto en unidades.
- **Decisión**: (b), con la versión `raw` (venta cruda en el ajuste y en el observado) y la `recovered` (demanda recuperada en los dos); la mediana por serie se informa en la ficha como contraste, nunca como el efecto.
- **Motivo**: (b) es el que suma lo que el comercio vende (pondera por venta, como un equipo comercial lee el resultado) y es coherente con el contrafactual; (c) no existe con venta normalizada sin precio (research.md).
- **Afecta**: `effect.lifts`; C04; `fact_overall_effect`.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D11 Las unidades del efecto: total, celda, banda, grupo, descuento sin marca, la cuenta ingenua y, como variante, la primera categoría

- **Contexto**: el sitio pide el efecto «por categoría y nivel de descuento». La jerarquía es producto → 3ª → 2ª → 1ª categoría → grupo de gestión (865 → 233 → 84 → 32 → 7; research.md).
- **Opciones**: un solo camino razonable para las unidades principales: las que el tablero y el sitio muestran. La primera categoría (32 × 7 = 224 celdas) tendría celdas con muy pocas series.
- **Decisión**: `overall`, `cell` (grupo × banda), `band`, `group`, `unflagged_band`, `naive_pooled` (la cuenta que sale mal, para contarlo en el sitio) y la variante `first_category_cell` en C10.
- **Motivo**: cada una responde una pregunta del equipo comercial o del relato; la cuenta ingenua es la demostración de la confusión.
- **Afecta**: `effect.py`; `fact_*_effect`; `algorithms.json`.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D12 Intervalos: remuestreo de dos vías, series y días, con el contrafactual fijo

- **Contexto**: research.md remuestreó solo series y avisó que sus intervalos ignoran los choques comunes de un día. Sobre las 43 celdas con 30 series, el de dos vías es 1,80 veces más ancho (ancho mediano 31,02 frente a 15,93 puntos) y los pares que se pisan pasan de 87 a 157 de 903 (`p04`). Un ajuste de IPF por remuestra multiplicaría el costo por 500.
- **Opciones**: (a) solo series; (b) dos vías con pesos producto (series × días) sin reajustar el contrafactual; (c) dos vías reajustando el IPF en cada remuestra.
- **Decisión**: (b), 500 remuestras, semilla 0, percentiles 2,5 y 97,5; (a) es la variante de C10.
- **Motivo**: (b) cubre la dependencia entre las horas de una serie y entre las series de un día; `b(g, d)` ya absorbe el nivel de cada día y con 50.000 series su variación por remuestra es chica **[Inferido]**; (c) no cabe en el presupuesto del lanzamiento. La réplica (C06) mide si aun así los intervalos alcanzan para la semana siguiente: en la validación, no (42,5 %).
- **Afecta**: `bootstrap.py`; C04-C09; `fact_cell_effect[ci_kind]`.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D13 El ranking: grupo de gestión × siete bandas de descuento en los días con marca, al menos 30 series, y grupos indistinguibles

- **Contexto**: no hay identificador de promoción; research.md midió celdas grupo × banda (44 de 49 con 30 series) y propuso decirle al sitio que la unidad es la celda. El sitio promete que «dos promociones cuyos intervalos se pisan no se presentan como distintas». Con el estimador de D09 y el de dos vías, 43 celdas y 157 pares que se pisan (`p04`).
- **Opciones**: (a) celdas grupo × banda; (b) primera categoría × banda; (c) bandas solas; para la regla, (a) que se pisen los intervalos de las dos celdas o (b) el intervalo de la diferencia.
- **Decisión**: celdas (a) con las bandas de research.md (`(0; 0,5)`, `[0,5; 0,6)`, … `[0,95; 1]`), mínimo 30 series en el período de lo que se ordena; regla del sitio tal cual (que se pisen los intervalos), con grupos indistinguibles (`tier`) armados en orden de aumento y el total de pares que se pisan publicado.
- **Motivo**: 49 celdas se leen en un tablero y casi todas tienen series suficientes; (b) da celdas de pocas series; la regla de los intervalos que se pisan es conservadora y es la que el sitio ya promete; el grupo indistinguible la vuelve una lectura visual.
- **Afecta**: `ranking.py`; `[ranking]`; `fact_cell_effect[tier]`; el sitio (filas 10 y 11).
- **Quién**: agente de planificación.
- **Estado**: vigente; las bandas y el mínimo, pendiente del dueño (plan, sección 29, ítem 4). **Nota del 2026-11-17 (U04, leyendo `train.parquet`)**: la columna `discount` del archivo real guarda el mismo descuento «limpio» de dos maneras, como el double que se quiso y como su vecino de float32 (`0,9` en 15.234 filas y `0,8999999761581421` en 2.127; igual con 0,7 en 58 filas, 0,95 en 1.124 y 0,8 en 29), y la comparación sin tolerancia con un borde manda esas 3.338 filas (0,07 %) a la banda de abajo; los recuentos por banda de `research.md` (78.127, 207.326, 429.102, 847.707, 411.689) las traen así. Cambio mínimo: `days.EDGE_TOLERANCE = 1e-6` (constante del código, no una clave de la configuración): un valor a menos de 1e-6 por debajo de un borde cuenta como el borde, en las bandas y en `regular_min_discount`; muy por debajo del paso de 0,001 de los descuentos que se quisieron y sin cambiar ningún estado del día (0 filas). Con la tolerancia los recuentos por banda de las filas con 0 < descuento ≤ 1 son 15.886, 78.127, 207.268, 429.131, 845.609, 412.692 y 2.495.214; las cifras de celdas de `p04` y `p07` se midieron sin ella y las publicadas (U19) con ella. No hay un redondeo a milésimas: el archivo trae descuentos reales con más decimales (2.600 valores distintos).

## D14 Partición: entrenamiento, purga de 7 días, V1, V2 y la semana de prueba del conjunto, leída una vez; 90 días alcanzan para este uso

- **Contexto**: research.md propuso entrenamiento 2024-03-28 a 05-31, purga 06-01 a 06-07, validación 06-08 a 06-25 y la semana de prueba del conjunto (06-26 a 07-02, que ningún cálculo usó). No hay estacionalidad anual en 97 días. Nada ajustado usa rezagos: la recuperación usa el propio día y medias del período; el contrafactual, días del mismo período o del mismo día; solo la regla ingenua F1 mira los 7 días anteriores, por diseño.
- **Opciones**: (a) la partición de research.md con la validación entera; (b) la misma, con la validación partida en V1 (06-08 a 06-16) para elegir y V2 (06-17 a 06-25) para la vista previa; (c) validación cruzada por bloques; para los 90 días, (a) bastan o (b) buscar otra fuente con un año.
- **Decisión**: (b), sin purga entre V1 y V2 ni antes de la prueba; la purga del entrenamiento a V1 se conserva para que la vista previa mire un período posterior, como la prueba. El lanzamiento reajusta con los 90 días. Los 90 días bastan para un ranking del período y su réplica en la semana siguiente; la estacionalidad anual queda fuera de alcance y se dice.
- **Motivo**: la prueba es la semana que sigue al período, como la usaría un comercio; una purga antes de ella no protege nada porque ningún ajuste cruza días; otra fuente no tendría los quiebres anotados, que son el centro del proyecto.
- **Afecta**: `split.py`; `[split]`; M06; requerimientos, sección 3.
- **Quién**: agente de planificación.
- **Estado**: vigente; otra fuente, pendiente del dueño (plan, sección 29, ítem 7).

## D15 La métrica del pronóstico y las bases que debe superar: WAPE de la masa con stock de las series-días con promoción

- **Contexto**: siempre cero tiene el menor MAE horario (0,0472; research.md); el WAPE horario de cero es exactamente 100 % y el de cualquier promedio pasa de 100 % (`p02`). En la validación, con todo ajustado en el entrenamiento: F0 sin aumento, WAPE 48,37 %; F2a con un aumento total, 45,62 %; F2 con el de la celda, 43,37 %; F1 la media de los 7 días anteriores de la serie, 35,64 % (`p04`, `p05`).
- **Opciones**: (a) MAE horario; (b) WAPE horario en horas con stock; (c) WAPE de la masa de las horas con stock por serie-día, solo en las series-días con promoción; (d) una métrica de cuantiles.
- **Decisión**: (c), con las bases F0 (el contrafactual sin aumento), F2a (un solo aumento) y F1 (la regla ingenua de la propia serie); C08 compara F2 con F2a y C09 con F1. El pronóstico usa los días `regular` de otras series del mismo día para `b(g, d)`: es un pronóstico con controles del mismo día, que mide si el aumento agrega información, no uno de la víspera, y así se rotula.
- **Motivo**: en (c) siempre cero da 100 % y el sesgo −100 %, de modo que la métrica separa los métodos; las horas con stock son las únicas con verdad observada; el pronóstico no es el producto (D01), así que no se busca uno que gane a F1.
- **Afecta**: `forecast.py`; C08, C09; `fact_forecast`.
- **Quién**: agente de planificación.
- **Estado**: vigente. **Nota del 2026-11-17 (U09, lanzamiento en seco)**: pronósticos de la validación con todo ajustado en el entrenamiento, sobre 317.372 series-días con promoción (53.080 más quedan fuera porque su serie no tiene `a`: `no_regular_day`): F0 WAPE 48,43 % y sesgo −37,68 %; F2a 45,29 % y −0,26 %; F2 43,10 % y +2,98 %; F1, la regla ingenua, **35,64 % y −20,28 %, igual a `p04`**. F2 − F0 −5,33 [−6,77; −3,92], F2 − F2a −2,19 [−2,84; −1,54] y F2 − F1 +7,47 [+5,86; +9,19] puntos (dos vías): como en `p05`, el aumento de la celda agrega información sobre un aumento único y no supera a la última semana de la serie (lo esperable para C09). Las diferencias de F0, F2a y F2 con `p04` y `p05` (48,37 %, 45,62 %, 43,37 %) vienen de κ y de la corrección de `day_factor` (D09).

## D16 Criterios C01-C10 y lo que se vio antes de fijarlos **Nota del 2026-11-18 (U11)**: C01 compara la recuperación sellada con R1 en la máscara de cola emitida de la prueba; si el método sellado fuera R1, la diferencia es 0 y el criterio no se cumple (un empate no supera). C05 y C06 usan las celdas con al menos `min_series` series en el lanzamiento y en la semana; C06 reconstruye los remuestreos del lanzamiento con su propia semilla desde el artefacto (`bundle.cf`) y los resta de los de la semana, que no comparten pesos (D41). C10 es informativo: dice cuántas cifras de variantes y cuántos días tiene el seguimiento.

- **Contexto**: el planificador midió casi todo sobre el entrenamiento y la validación (sección 4 de los requerimientos); los proyectos 03 a 05 dijeron lo esperable antes de medir.
- **Opciones**: un solo camino razonable: fijar los criterios con dos columnas de lo visto, la de la investigación y la del planificador, y lo esperable escrito.
- **Decisión**: los diez de `requirements.md`, sección 8.1, con sus umbrales en `[criteria]` (sellados) y lo esperable: C01, C02, C04, C05, C07 y C08 deberían cumplirse; C03 es incierto; C06 y C09 probablemente no.
- **Motivo**: un criterio que se sabe que no se cumplirá se deja igual, porque es lo que el sitio tiene que decir.
- **Afecta**: `evaluation.py`; `texts.py`; el resumen; el README; el sitio.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D17 La prueba se lee una vez: lanzamiento congelado y sello con una huella que cubre cada clave que cambia un valor sellado **Nota del 2026-11-18 (U11)**: la parte de la prueba del sello tiene las claves `run_key`, `as_of`, `config_sha256`, `criteria`, `metrics`, `recovery`, `effects`, `replication`, `forecast`, `variants` y `days` (`registry.TEST_KEYS`); `metrics` son las cifras de las que `evaluation.criteria_of` reconstruye C01-C10 (y `criteria_from_seal` exige que cada entrada del sello se reconstruya a 6 decimales). `check_test_evaluation` decide antes de escribir (`first`, `repeat`, `post_seal`, o `EvaluationRefusedError` con las claves que difieren) y `write_test_seal` escribe la parte una vez, la relee y compara una repetición a 6 decimales salvo `run_key`, `as_of` y las huellas. Las filas selladas de `eval_criteria`, `eval_replication`, `eval_forecast` y `eval_variants` (`003_eval.sql`) no se cambian, no se borran y no se insertan dos veces; `eval_pairs` y `eval_leakage` son de solo inserción sin estado posterior; un análisis `post_seal` guarda solo esas cuatro tablas con su estado y reemplaza las filas `post_seal` del análisis anterior, y los efectos y la recuperación de la prueba (`effect_estimates` y `recovery_checks` con alcance `test`) solo existen sellados.

- **Contexto**: la lección de los proyectos 02 a 05 (B4 del 03, D89 del 04): la prueba se toca una vez y una configuración distinta después del sello no reemplaza lo sellado.
- **Opciones**: un solo camino razonable: el sello del proyecto 05, adaptado.
- **Decisión**: `reports/model_seal.json` con la parte del lanzamiento y la de la prueba, cada una de creación exclusiva; `FINGERPRINT_KEYS` y `UNSEALED_KEYS` con una prueba de que cada hoja está en una; `config_sha256` es la huella de la vista sellada y `config_file_sha256` la del TOML (A8 del 05); con otra configuración todo es `post_seal`; la evaluación de la prueba con otra configuración mientras el sello no tiene la prueba se rechaza antes de escribir y alcanza a toda tarea de la corrida del cierre; ninguna prueba `real_data` lee la semana de prueba antes de U19.
- **Motivo**: incluir de más es seguro; incluir de menos es el defecto B4 del proyecto 03.
- **Afecta**: `config.py`; `registry.py`; `pipeline.py`; AC18, AC19.
- **Quién**: agente de planificación.
- **Estado**: vigente. **Nota del 2026-11-17 (U09)**: la parte del lanzamiento del sello tiene las claves `run_key`, `as_of`, `train_sha256`, `eval_sha256`, `config_sha256`, `sealed_config`, `model_version`, `artifact_sha256`, `r3_sha256`, `recovery`, `effects`, `validation` y `validation_digest`; una repetición con la misma huella puede cambiar `run_key`, `as_of` y los hash de los dos archivos del modelo (el `.npz` es determinista, el pickle de R3 no se promete), y todo lo demás se compara redondeado a 6 decimales. El resultado del sello (`written`, `unchanged`, `post_seal` o `SealMismatchError`) se decide **antes** de escribir el artefacto, el registro y las filas; el sello se escribe al final con creación exclusiva. `validation` incluye la demostración de la fuga (`leakage`). `effect_draws_digest` no se creó: los intervalos van en `effects` y se comparan a 6 decimales, y `validation_digest` cubre la validación.

## D18 Operación simulada: un lanzamiento con los 90 días, siete entregas diarias y un cierre que evalúa

- **Contexto**: el sitio promete «cada día un flujo carga las ventas por hora, marca las horas sin stock y deja la demanda corregida lista para el modelo». El conjunto es una extracción fija de 97 días.
- **Opciones**: (a) una sola corrida con todo; (b) el lanzamiento, una entrega por día de la prueba y un cierre sin filas que evalúa.
- **Decisión**: (b). Cada diaria recupera su día con el método sellado, ajusta `b(g, d)` con sus días `regular`, emite el efecto del día, los pronósticos y la máscara de cola del día (solo inserción); nada diario cambia el método, `a` ni los aumentos sellados.
- **Motivo**: es lo que el sitio describe, separa lo emitido de lo evaluado (lo que se evalúa es lo que se emitió) y prueba la independencia del tamaño de la entrega (AC12).
- **Afecta**: `deliveries.py`; `daily.py`; `pipeline.py`; el sitio (fila 13).
- **Quién**: agente de planificación.
- **Estado**: vigente. **Nota del 2026-11-17 (U10)**: `daily.run_day(conn, cube, bundle, run, spec, view, interim_dir=...)` (las tareas `recover` y `estimate` son `recover_delivery` y `estimate_delivery`; todavía no hay `RunContext`, lo trae U16) emite los días de una entrega diaria, uno por uno, con lo que congeló el lanzamiento y nada más: la historia de la regla ingenua son los 7 días anteriores del cubo, el factor `b` sale de los días `regular` del día con la `a` sellada, y la máscara sintética del día usa la semilla `[mask_seed_test, date_key]`. Lo emitido (`daily_cell`, `forecasts` con `scope = test` y `mask_checks`) son tablas de solo inserción; un día ya emitido se descubre dentro de la transacción que lo escribiría y no se toca. Una entrega de 7 días y siete de 1 día dan las mismas filas (menos `run_key`), y las cifras de un día no cambian si los días posteriores ya están cargados o si se los altera. Se niega (`ScoringError`) lo que no sea una entrega diaria cargada, una corrida cuyo instante no es el de cierre de la entrega y un día que no es posterior al lanzamiento. `mask_checks` guarda lo que estiman R1, el método sellado y R3 (R2 con el κ sellado, si es el elegido) junto a la verdad; si el elegido es R3, R2 no está en el artefacto y no se compara. Las series-días con promoción que no tienen pronóstico (`no_regular_day`, `no_day_factor`) y las celdas con promoción sin contrafactual (`no_counterfactual`) salen en el resultado con su razón.

## D19 La trampa de fuga M01 y la demostración de la fuga de los campos diarios

- **Contexto**: `sale_amount` es la suma de las horas (research.md): en una máscara sintética contiene la venta de las horas ocultas, así que una recuperación que lo lea acierta casi siempre en la simulación y nunca en un quiebre real (donde esas horas venden casi cero). La razón del método elegido sobre R1 en V1 es 30,06 / 35,38 = 0,85 (`p06`).
- **Opciones**: (a) confiar en la lista de columnas prohibidas; (b) la lista más una trampa: si el método elegido tiene en V1 un WAPE por serie menor que 0,5 × el de R1, el lanzamiento se detiene; más una demostración que mide una recuperación con `sale_amount` y la muestra.
- **Decisión**: (b): M01 con `leak_tripwire_ratio = 0,5`; `leakage_demo.py` mide en V2 la recuperación con `sale_amount` frente a la sellada y la publica en `fact_leakage` y `algorithms.json`, con la explicación.
- **Motivo**: la lista evita la fuga conocida; la trampa atrapa una que nadie previó; 0,5 deja lugar a una mejora real (0,85) y atrapa una fuga (que daría cerca de 0) **[Inferido]**.
- **Afecta**: `recovery.py`; `launch.py`; `leakage_demo.py`; AC13; runbook R5.
- **Quién**: agente de planificación.
- **Estado**: vigente. **Nota del 2026-11-17 (U09)**: la demostración mide en V2 una recuperación que resta de lo que dice el total diario (las 24 horas del cubo, que es `sale_amount`) lo que ve el método: da WAPE por serie de 1,4 · 10⁻⁸ frente a 31,57 % del método elegido y 37,47 % de R1, y la trampa lo habría detenido. `launch.fit_model` acepta controles extra (`extra_candidates`) que compiten en V1 solo para que una prueba muestre que M01 detiene el lanzamiento antes de escribir nada.

## D20 El artefacto: un `.npz` sin objetos de Python, y R3 en un pickle leído solo con su huella

- **Contexto**: el lanzamiento congela `base`, la distribución del corte, `a` y `b` de las dos versiones y los aumentos; son arreglos. R3 es un objeto de scikit-learn. El proyecto 05 cargó su artefacto con pickle bajo huella (su D39).
- **Opciones**: (a) todo en un pickle bajo huella; (b) los arreglos en `.npz` leído con `allow_pickle=False`, y R3 en un pickle bajo huella; (c) dejar R3 fuera para no tener ningún pickle.
- **Decisión**: (b). `load_artifact` comprueba tamaño y SHA-256 contra el registro antes de leer; un `.npz` con un arreglo de objetos se rechaza (M03). R3 se carga con el procedimiento del proyecto 05 (los bytes una vez, `hmac.compare_digest`, `pickle.loads` de esos bytes).
- **Motivo**: lo que el flujo usa cada día (R2 y el contrafactual) no pasa por pickle; R3 se conserva como comparación medida en la prueba (C10); (c) perdería esa comparación.
- **Afecta**: `registry.py`; M03; AC20; runbook R6.
- **Quién**: agente de planificación.
- **Estado**: vigente. **Nota del 2026-11-17 (U09)**: `r3.pkl` se guarda siempre que R3 es un candidato (ajustado de nuevo con los 90 días aunque no sea el elegido), porque la semana de prueba lo mide como comparación (C10) y la corrida diaria lo necesita para `mask_checks`; el registro lleva su nombre y su huella y se carga con el procedimiento de la huella antes del pickle. El `.npz` es un zip sin comprimir con hora fija de las entradas, de modo que el mismo modelo da los mismos bytes; un arreglo de objetos se rechaza (con `allow_pickle=False` y, además, por su tipo) aunque la huella coincida.

## D21 Cada cifra dice con qué se ajustó, el resumen sale del sello después del sello y ninguna cifra se escribe a mano

- **Contexto**: en el proyecto 05, una condición de la compuerta se midió sobre el modelo reajustado con ese bloque (A2), tres límites de intervalo se redondearon a mano en dos documentos (B3) y los documentos contaron unidades que el registro todavía no tenía (B4).
- **Opciones**: un solo camino razonable: cerrar las tres clases con reglas y pruebas.
- **Decisión**: toda fila de validación lleva `fit_blocks` y una prueba exige que ninguna cifra de un bloque venga de un método ajustado con ese bloque; después del sello, el resumen toma del sello lo que el almacén no tiene, comprobado a 6 decimales; toda cifra de los documentos sale del resumen o del sello por `docs-sync` o se compara con ellos a sus decimales; la documentación se sincroniza después de que el registro tiene su entrada.
- **Motivo**: son las clases que la evaluación del proyecto 05 encontró; cada una tiene su prueba con nombre (plan, sección 24.2).
- **Afecta**: `launch.py`; `reporting.py`; `tests/docs/`; RNF14; AC22, AC37.
- **Quién**: agente de planificación.
- **Estado**: vigente. **Nota del 2026-11-17 (U09)**: `fit_blocks` es `train` en las cifras de V1, V2, la réplica y los pronósticos de la validación (el `b` de cada día de la validación sale de sus propios días `regular`, D15), y `train+purge+valid_v1+valid_v2` en los efectos publicados del lanzamiento, que describen el período con el que se ajustan y se rotulan así. Una prueba (`test_every_validation_figure_names_the_blocks_its_method_saw_and_none_saw_its_own_block`) lo exige en la base y en el sello, y otra recalcula V1, V2, el aumento de la réplica y la base reajustada con funciones públicas.

## D22 Almacén: SQLite para lo relacional y un cubo de NumPy para las horas

- **Contexto**: 4.850.000 series-días con 24 horas cada una son unos 116 millones de valores por campo horario; ninguna consulta SQL los necesita sueltos. El proyecto 05 usó SQLite en capas.
- **Opciones**: (a) todo en SQLite, una fila por hora; (b) SQLite para series, series-días, entregas, corridas, validación, efectos, pronósticos y evaluación, y archivos `.npy` por entrega para las horas, con manifiesto; (c) DuckDB (fuera del landing).
- **Decisión**: (b), con `np.load(..., mmap_mode="r", allow_pickle=False)` y el SHA-256 de cada archivo en el manifiesto; las sumas por serie-día de SQLite se comprueban contra el cubo (V14, `chk_sums_match_cube`).
- **Motivo**: (a) haría un almacén de varios GB y cargas lentas **[Inferido]**; (c) agrega una tecnología sin necesidad; (b) deja SQL donde el landing lo declara y el cómputo horario en NumPy.
- **Afecta**: `cube.py`; `warehouse.py`; `sql/`; RNF03, RNF10.
- **Quién**: agente de planificación.
- **Estado**: vigente. **Nota del 2026-11-17 (U04 a U06)**: hay dos cubos. El canónico, `data/interim/canonical/<date_key>.{sales,stock}.npy` (float32 e int8, series × 24, los 97 días desde la primera lectura, con `interim_manifest.json` escrito al final), y el de las entregas cargadas, `data/interim/cube/<delivery_id>.{sales,stock}.npy` (series × días × 24) con su `manifest.json`, que `load_delivery(..., interim_dir=...)` llena **después** del commit de SQLite (una carga rechazada no toca el cubo; si la copia falla, `CubeStoreError` dice que la entrega quedó cargada sin su cubo y copiarla de nuevo termina el trabajo, runbook R12). Las tareas posteriores a `load` leen solo el segundo (`cube.open_loaded_cube`): un día que todavía no se entregó no se ve (RNF06 b). `hour_profile` guarda las 24 horas del día y el `delivery_id`; la entrega es `<id>.days.parquet` (las series-días con las sumas de 06 a 21) y `<id>.cube.npz` (un zip sin comprimir de tres `.npy` con hora fija, para que los mismos días den los mismos bytes). **Nota del 2026-11-17 (U09)**: lo recuperado de una entrega se guarda en `data/interim/cube/<delivery_id>.recovered.npy` (float32, series × días × 24: las horas de 06 a 21 recuperadas y la noche y las horas con stock como estaban) con un manifiesto propio, `recovered.json`, escrito al final (el del cubo de las entregas cargadas no cambia); se emite una vez y otro contenido para la misma entrega se rechaza. `series_days.recovered_sum` se fija solo donde sigue nulo, en la transacción del lanzamiento (los 90 días). **Hecho de los datos reales**: cada día del cubo es una vista de un `np.load(mmap_mode="r")` de todo el archivo de la entrega (432 MB para el lanzamiento, con la forma series × días × 24), de modo que 90 vistas vivas a la vez llevaron el conjunto de trabajo de la corrida en seco a 20,9 GB (`PeakWorkingSetSize`); con cada día copiado al leerlo (`np.array`), y una prueba que cuenta las vistas vivas, el pico de toda la corrida en seco (lectura, carga a SQLite y lanzamiento) es de 4,3 GB (`PeakWorkingSetSize`; `PeakPagefileUsage` 5,9 GB) y `fit_model` tarda unos 215 s de 288 s en este equipo. **Nota del 2026-11-17 (U10)**: `recover_delivery` (la tarea `recover`) guarda las horas recuperadas de la entrega y fija `recovered_sum` de sus series-días, y repetirla no cambia nada.

## D23 Validación: qué bloquea, qué se marca y qué se informa; las reglas acumuladas se leen una vez

- **Contexto**: las reglas del proyecto 05 y su agregación entre corridas (la lección D94 del proyecto 03); un rechazo de V01 no cambia nada de lo publicado y el informe lo registra (D51 del 05).
- **Opciones**: un solo camino razonable: la tabla del plan, sección 6.
- **Decisión**: V01-V07 y V10-V15 bloquean; V20-V27 marcan y se usan o se excluyen como dicen; I01-I04 cuentan; M01-M06 en el modelo; cada regla declara su agregación.
- **Motivo**: lo que rompe la estructura detiene la corrida; lo que es una propiedad de los datos se cuenta y se explica.
- **Afecta**: `validate.py`; `ingest.py`; `validation_rules.json`; AC06.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D24 Orquestación: Airflow 3.4.0 en Docker con todos los secretos del entorno, y la CLI

- **Contexto**: los proyectos 04 y 05 fijaron `apache/airflow:3.4.0` por su resumen y endurecieron el compose; el lanzamiento de este proyecto tiene tensores de cientos de MB (RNF03).
- **Opciones**: un solo camino razonable: el compose del proyecto 05 con `PROMOLIFT_`.
- **Decisión**: la imagen por el resumen de los proyectos 04 y 05, `pip check` por su código de salida, `data/raw/` en solo lectura, el límite de memoria del trabajador comprobado en U18; la prueba de Docker corre `airflow dags test` dos veces en modo rápido y deja los listados de Docker como estaban.
- **Motivo**: reusar lo que ya se revisó; el riesgo nuevo es la memoria.
- **Afecta**: `airflow/`; AC32, AC33; runbook R10.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D25 Estado de la corrida, cierre en orden y rechazos, con la corrección B2 del proyecto 05 desde el principio

- **Contexto**: en el proyecto 05, `task load` (y las siguientes) sin `--run-key` abría una corrida sin entrega, salía con 1 y dejaba un estado `failed` (B2); `replay --until` sin pendientes salía con 0 (A4).
- **Opciones**: un solo camino razonable: el diseño corregido del proyecto 05 desde la primera unidad.
- **Decisión**: los rechazos del plan, sección 22, en ese orden, incluida toda tarea desde `load` de una corrida sin entrega (salida 2, nada escrito, ni su archivo de estado), y `--until` de una entrega ya cargada con 2 haya o no pendientes; el cierre en el orden de la sección 3.
- **Motivo**: son defectos ya encontrados; prevenirlos cuesta una prueba cada uno.
- **Afecta**: `pipeline.py`; `cli.py`; AC28, AC30.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D26 Un solo escritor: el bloqueo del proyecto 05

- **Contexto**: el bloqueo del proyecto 05 (su D30) con sus correcciones (escritura atómica con `fsync`).
- **Opciones**: un solo camino razonable.
- **Decisión**: `lock.py` del proyecto 05 con `PROMOLIFT_*` y el runbook R8.
- **Motivo**: reusa lo revisado y probado.
- **Afecta**: `lock.py`; AC29.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D27 Rutas contra la carpeta del proyecto y modo rápido aislado

- **Contexto**: lecciones L14 del proyecto 01 y A2 del 03; el modo rápido del 05 con su huella registrada.
- **Opciones**: un solo camino razonable.
- **Decisión**: toda ruta relativa se resuelve contra `PROMOLIFT_HOME` o la carpeta del proyecto; el modo rápido escribe todo bajo `data/quick/`, con la primera huella vista registrada.
- **Motivo**: un comando corrido desde otro directorio no puede escribir en otra parte ni en lo versionado.
- **Afecta**: `config.py`; `pipeline.quick.toml`; AC31.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D28 Lecciones de los proyectos 01 a 05 que pasan a ser requisitos

- **Contexto**: las evaluaciones independientes de los cinco proyectos anteriores.
- **Opciones**: un solo camino razonable: convertir cada clase en un requisito y una prueba con nombre.
- **Decisión**: la tabla del plan, sección 24.2, con su origen; en particular del 05: los bordes de una regla probados uno por uno (B1), una tarea sin corrida con salida 2 (B2), ninguna cifra a mano (B3), los documentos después del registro (B4), la prueba real que compara lo que el sello fija (A1), ninguna cifra de validación dentro de la muestra (A2), `--until` coherente (A4), cada veredicto con su comparación (A7), los nombres de las huellas (A8), `pip check` por su código, `fsync` antes de `os.replace` y una transacción que se deshace ante un error (advertencias de sus revisiones).
- **Motivo**: cada clase costó una corrección en un proyecto anterior.
- **Afecta**: todo el plan, sección 24.2.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D29 La suite rápida: límite de 120 s y presupuesto de trabajo de 90 s **Nota del 2026-11-18 (U11)**: la suite por defecto pasó de 575 pruebas en 61,1 s (medida al empezar la sesión de U11, con el equipo más lento que en las notas anteriores) a 642 en 57,1 s y 58,2 s (dos corridas en reposo): U11 suma unos 5 s a la suite, menos de los 8 s que piden justificarse, de los cuales unos 4 s son el accesorio de sesión `issued_week` (las siete entregas de la prueba cargadas y emitidas sobre una copia del lanzamiento, una vez por sesión) y unos 2 s la evaluación del cierre (`evaluated_week`, una vez por sesión); las demás pruebas de la evaluación trabajan sobre esos dos estados o sobre copias de ellos. **Nota del 2026-11-18 (U12)**: 681 pruebas en 68,7 s y 68,7 s (dos corridas en reposo). U12 suma unos 11 s (de 57,6 s con U11), más de los 8 s que piden justificarse: el accesorio de sesión `star_export` (el modelo estrella exportado una vez: unos 2 s) y siete pruebas que exportan o copian el almacén y exportan de nuevo sobre una copia (de 1,3 a 2,3 s cada una: lo anterior a la semana cerrada, el cierre, un control que falla, el fallo en medio de las escrituras, el sello distinto, la recuperación parcial y el análisis posterior al sello, que evalúa otra vez), más las 12 variantes de la prueba de los controles, que copian el almacén (0,3 s cada una). Si U13 y U14 pasan los 90 s, la unidad siguiente es una de velocidad. **Nota del 2026-11-18 (U13)**: 699 pruebas en 68,3 s y 68,3 s (dos corridas en reposo): U13 suma 18 pruebas y menos de 1 s (el HTML se genera una vez por sesión, `rendered_html`, sobre el modelo exportado por `star_export`), sin pasar de los 8 s que piden justificarse. **Nota del 2026-11-18 (U14)**: 712 pruebas en 75,8 s y 75,5 s (dos corridas en reposo): U14 suma 7,2 s (de 68,3 s con U13), por debajo de los 8 s que piden justificarse: el accesorio `site_files` (la exportación una vez por sesión, unos 0,4 s), el de las nueve figuras (unos 2 s de matplotlib) y seis pruebas que copian el almacén y exportan de nuevo (de 0,6 a 1,5 s). Quedan 14 s hasta el presupuesto de 90 s: si U15 a U21 los pasan, la unidad siguiente es una de velocidad antes de cualquier otra. **Nota del 2026-11-18 (U15)**: 734 pruebas en 77,2 s (una corrida en reposo; la de la nota de U14 era de 75,5 s): U15 suma 22 pruebas y unos 2 s (los procesos aparte son el del segundo escritor y los que dejan un archivo abierto), por debajo de los 8 s que piden justificarse. Quedan unos 13 s hasta el presupuesto de 90 s.

- **Contexto**: el proyecto 05 terminó en 76,3 s tras tres unidades de velocidad y pasó una vez los 90 s (A3).
- **Opciones**: (a) el mismo límite y presupuesto; (b) un presupuesto más bajo.
- **Decisión**: (a): 120 s y 90 s, medidos después de cada unidad; un accesorio de 300 series que cabe en la suite; los estados caros una vez por sesión; las pruebas lentas con nombre en el plan, sección 24.1.
- **Motivo**: el presupuesto de 90 s alcanzó en el 05 con margen para las correcciones; el accesorio de aquí es más chico que el cubo real por cuatro órdenes.
- **Afecta**: `tests/conftest.py`; RNF15; AC38.
- **Quién**: agente de planificación.
- **Estado**: vigente. **Nota del 2026-11-17 (U07 a U09)**: la suite por defecto pasó de 429 pruebas en 33,3 s (U06) a 474 en 36,9 s (U07), 506 en 38,1 s (U08) y 564 en 48,1 s (U09, sin las del día de U10). U09 suma 10 s, más de los 8 s que pide justificar: el lanzamiento del accesorio estándar (1,6 s, una vez por sesión), diez pruebas que lanzan de nuevo sobre una copia (de 0,3 a 1,4 s cada una: el sello, la trampa M01, V2, los bloques chicos, la lectura de los días) y la del control negativo, que arma su propio almacén con el accesorio sin aumento (1,4 s). **Nota del 2026-11-17 (U10)**: 575 pruebas en 52,4 s y 51,0 s (dos corridas en reposo, con U07 a U10): U10 suma de 3 a 4 s (de 48,1 s sin ella): el día se emite sobre una copia del almacén del lanzamiento y las tres pruebas más lentas, de unos 2,1 s cada una, son la del primer día (carga su entrega y la emite), la de siete entregas de 1 día frente a una de 7 y la de los días posteriores alterados.

## D30 `pytest-xdist`: no se fija

- **Contexto**: los proyectos 04 y 05 lo dejaron como pendiente del dueño.
- **Opciones**: (a) fijarlo; (b) no fijarlo y diseñar la suite para un proceso.
- **Decisión**: (b).
- **Motivo**: los accesorios de sesión son el ahorro principal; paralelizar duplicaría estados caros.
- **Afecta**: `requirements-dev.txt`.
- **Quién**: agente de planificación.
- **Estado**: vigente; pendiente del dueño si la suite se acerca al límite.

## D31 Idioma y nombres: paquete `promolift`, alcance de commit `promotion-lift`

- **Contexto**: la investigación ya se confirmó con `docs(promotion-lift)` (`6afd46c`); los proyectos anteriores usan un paquete corto y un alcance por proyecto.
- **Opciones**: un solo camino razonable: seguir el alcance ya usado.
- **Decisión**: paquete `promolift`, variables `PROMOLIFT_*`, DAG `promolift_daily`, proyecto de Compose `promolift-airflow`, alcance `promotion-lift`; documentación en español neutro, código e identificadores en inglés.
- **Motivo**: coherencia con el historial y con S10.
- **Afecta**: todo el código; los commits.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D32 Tecnologías fuera del landing: ninguna nueva; statsmodels no se usa

- **Contexto**: S5 pide usar lo que declara el landing y anotar lo demás en `LANDING-EXPANSION.md`. El sitio declara statsmodels para el modelo del efecto; no está en el landing ni en `LANDING-EXPANSION.md` (research.md). pyarrow, NumPy, SQLite, matplotlib, pytest y PostgreSQL ya tienen su fila.
- **Opciones**: (a) usar statsmodels para una regresión de Poisson con efectos fijos y anotarla; (b) el IPF con NumPy (D09) y quitar statsmodels del sitio.
- **Decisión**: (b). U21 suma el 06 a las filas existentes de pyarrow, NumPy, SQLite, matplotlib, pytest y PostgreSQL; no agrega filas nuevas. SciPy llega como dependencia transitiva de scikit-learn y no se importa.
- **Motivo**: el IPF ajusta el mismo modelo sin una librería nueva y escala a 50.000 series; statsmodels no aportaría nada que se use.
- **Afecta**: `requirements.txt`; `LANDING-EXPANSION.md`; el sitio (fila 9); AC36.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D33 Entorno y versiones

- **Contexto**: el `.venv` del proyecto ya tiene numpy 2.4.6, pandas 2.3.3, pyarrow 26.0.1 y scikit-learn 1.9.1 con sus transitivas (`requirements-research.txt`), las mismas del proyecto 05; python-dateutil se queda en 2.9.0.post0 por Airflow (D37 del 05).
- **Opciones**: un solo camino razonable: las mismas versiones, más matplotlib y pytest con las del proyecto 05.
- **Decisión**: `requirements.txt` con numpy, pandas, pyarrow y scikit-learn (y sus transitivas fijadas); `requirements-dev.txt` con matplotlib y pytest en las versiones del proyecto 05 **[Verificar en U01 contra `05-Mining-Flotation-Silica/requirements-dev.txt`]**; todo con `==`; `pip check` limpio. **Nota del 2026-11-17 (U01, comprobado contra `05-Mining-Flotation-Silica/requirements*.txt`)**: matplotlib queda en `requirements.txt`, no en el de desarrollo, porque `figures.py` (U14) es código de ejecución y la prueba de dependencias exige que todo lo que importa `src/` sea un pin directo de ese archivo (como en el proyecto 05); `requirements-dev.txt` fija solo pytest (con `colorama`, que pytest pide en Windows, `iniconfig`, `pluggy` y `Pygments`); SciPy es un pin transitivo (lo pide scikit-learn; D32) y matplotlib trae `contourpy`, `cycler`, `fonttools`, `kiwisolver`, `packaging`, `pillow` y `pyparsing`.
- **Motivo**: las versiones ya conviven con la imagen de Airflow.
- **Afecta**: U01; RNF01; AC36.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D34 Accesorio sintético con una demanda latente conocida, quiebres que dependen de la demanda y controles positivo y negativo

- **Contexto**: la recuperación y el efecto no tienen verdad en los datos reales; la censura sintética de horas con stock no reproduce que los quiebres llegan en días de más demanda (D07).
- **Opciones**: (a) un accesorio sin demanda latente; (b) uno con demanda latente, quiebres cuando la demanda acumulada pasa un tope y aumentos plantados por celda, con una variante de aumento 0.
- **Decisión**: (b), con la verdad de cada hora sin stock y de cada celda en `FixtureTruth`; el control positivo exige que el aumento recuperado contenga el plantado y que el crudo quede por debajo; el negativo, que el intervalo del total contenga 0.
- **Motivo**: es la única forma de probar que el estimador puede encontrar un efecto conocido y que la recuperación corrige en el sentido correcto bajo la censura real.
- **Afecta**: `tests/fixtures/make_fixture.py`; AC15.
- **Quién**: agente de planificación.
- **Estado**: vigente. **Nota del 2026-11-17 (U08, con el accesorio de 300 series, `tests/integration/test_controls.py`)**: el control positivo no se cumple como lo dice el plan para la demanda **recuperada**. Con la demanda verdadera puesta en las horas sin stock (el oráculo), el intervalo de dos vías del total (+47,1 % [+44,5; +49,7] frente a +47,9 % de la verdad) y el de cada una de las siete bandas contienen el aumento plantado: el estimador (IPF, registros y pesos) encuentra un efecto conocido. Con la recuperación R2 (κ = 0,25) el total es +43,8 % [+41,0; +46,1], por debajo de la verdad y fuera del intervalo, y el crudo +26,4 % [+23,2; +29,5]: la recuperación cierra el 81 % de la distancia entre el crudo y la verdad y en cada banda queda más cerca de la verdad que el crudo, pero sigue baja en las bandas profundas (+90,6 % frente a +120,4 % en la banda 0). Es el límite que D07 anunció: R2 aprende el nivel de la serie de las horas que tuvieron stock, que son las de los días de menos demanda, y los quiebres de este accesorio llegan en los días de más demanda. La prueba exige lo que sí se cumple (el oráculo contiene la verdad, crudo < recuperado < verdad, la recuperación cierra más del 70 % de la distancia y queda más cerca en cada banda) y el resumen debe decir que el aumento recuperado es una cota inferior del que escondían los quiebres, no una corrección exacta. El control negativo se cumple en las tres versiones (el intervalo del total y de cada banda contiene 0).

## D35 Salidas para Power BI y diseño del tablero en HTML **Nota del 2026-11-18 (U12)**: el modelo estrella es `dashboard/semantic_model.py` (10 dimensiones, 15 hechos y las relaciones R01-R21 del plan, todas de uno a varios, de filtro unidireccional y activas, con una prueba que las compara con la tabla del plan) y `export.py` (`export_star_schema(..., seal_path, interim_dir)`: los marts `sql/marts/powerbi/mart_*.sql` y los controles `sql/checks/model/chk_*.sql` en una transacción, y un Parquet por tabla con el manifiesto al final). Lo que el plan no decía y se decidió: (1) la clave de un hecho de efecto incluye `seal_state` y la de `fact_band_effect` el estado de los días medidos (`promo` o `unflagged_cut`), de modo que un análisis posterior al sello se muestra al lado del sellado y nunca en su lugar; (2) `fact_daily_cell` guarda solo las filas de celda de `daily_cell`, no las del día entero ni las de banda, para que una suma sobre el hecho cuente una vez; (3) `raw_mass` y `recovered_mass` de `fact_stockout_daily` suman solo las series-días que ya tienen su recuperación, de modo que su cociente compara siempre las mismas series-días; (4) `dim_method` lleva los métodos tal como se miden (`r0`, `r1`, `r2@κ`, `r3`) y los cuatro pronósticos; (5) la serie-día de ejemplo (`fact_example_day`) se elige en Python desde el cubo y las horas recuperadas del lanzamiento con la regla fija del plan, sección 21 (la mediana inferior de los candidatos, por masa recuperada, serie y fecha), y los marts la leen de `ref_example_day`; (6) nada de la semana de prueba entra en los marts mientras la semana no cerró (`:test_closed`, `as_of` posterior al último día de la prueba), y `stg_series_days` se reconstruye dentro de la transacción para el instante de la corrida, como dice `rebuild_staging`; (7) `seal_state` de lo del lanzamiento y la validación es `sealed` si la huella del modelo registrado es la del sello y `post_seal` si no, y el de la prueba el de sus filas de evaluación; (8) `chk_interval_contains_lift` exige que el aumento esté dentro de su propio intervalo en cada fila con intervalo: si la corrida real (U19) encuentra una celda que no lo cumple, se dice en una nota y no se afloja el control sin una decisión. `export_run_table` (reescribir solo `dim_pipeline_run.parquet` al cerrar la corrida) no se construyó: lo necesita el cierre ordenado de U16 y se escribe allí con su prueba. **Nota del 2026-11-18 (U13)**: las 21 medidas DAX y las cinco páginas del plan (sección 20) están en `dashboard/semantic_model.py`, y `dashboard/render.py` con `svg.py` genera el HTML del diseño desde el modelo y los Parquet exportados (`render_design(model, parquet_dir, html_path, run_meta)`); ninguna medida se ejecuta, y `validate_model` hace de sustituto: cada tabla, columna, medida y función del DAX existe, no se quitan filtros, el texto con que se compara una columna es uno que la columna toma, cada visual lee solo tablas que las relaciones unen y los segmentadores llegan a los visuales de su página o el título dice «(no lo filtra …)». Cambios sobre el DAX del plan, para que ninguna medida dé una cifra vacía o doble cuando una tabla trae dos estados o dos versiones: las medidas de efecto piden `seal_state = "sealed"` (y las del lanzamiento, `scope = "launch"` y la versión que corresponda), `Aumento del día` suma solo `version_key = "recovered"` (las dos versiones son filas del hecho), `Celdas que mantienen su nivel (%)` cuenta solo las celdas comparables y selladas, `Celdas ordenadas` y `Grupos indistinguibles` fijan el lanzamiento y la versión recuperada, y `WAPE de la recuperación` pide solo las filas selladas; las medidas que fijan una versión lo dicen en su descripción y las tarjetas de `fact_overall_effect` dicen que el segmentador de grupo (que filtra por `dim_cell`) no las filtra. Una prueba estática exige que toda medida que lee una tabla con `seal_state` por `SELECTEDVALUE`, `COUNTROWS` o `DISTINCTCOUNT` pida solo las filas selladas (la lección D71 del proyecto 04). Las vistas previas son las cifras de los archivos exportados, sin segmentadores, y dicen cuándo muestran la validación y no la prueba.

- **Contexto**: S4: lo que necesita Power BI Desktop se entrega como tablas y un diseño en HTML.
- **Opciones**: un solo camino razonable: el modelo estrella y el HTML del proyecto 05, adaptados.
- **Decisión**: las 10 dimensiones y 15 hechos del plan, sección 19, con las relaciones R01-R21; las 21 medidas y las cinco páginas de la sección 20; las medidas de la prueba leen solo filas `sealed`.
- **Motivo**: el contrato con Power BI es estable y está probado; las medidas no se ejecutan, por eso U13 es de riesgo alto (ítem 6).
- **Afecta**: `dashboard/`; `export.py`; AC24, AC25.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D36 Exportación para el sitio, con manifiesto, y nada personal en lo publicado **Nota del 2026-11-18 (U14)**: `site_export.py` escribe los cinco JSON de la sección 21 con el envoltorio común (`schema_version`, `run_key`, `as_of`, `train_sha256`, `eval_sha256`, `attribution`) y `manifest.json` al final (`export_site`, `read_site`, `verify_site`, `SiteSetError`): el manifiesto se borra antes del primer archivo, un conjunto mezclado se rechaza por tamaño y SHA-256 o por un envoltorio que no es el del manifiesto, y nada se escribe si los cinco pasan `[site] max_total_bytes` (en la fixture, 45.229 bytes sin el manifiesto). Las cifras salen de las tablas `star_*` (las mismas filas que los Parquet), del sello y de la validación de cada corrida, y solo de las filas `sealed`: con otra configuración que la sellada, el sitio no muestra las cifras del lanzamiento (están `post_seal`) en lugar de mostrarlas como selladas; antes del cierre, los criterios, la réplica, los pronósticos de la prueba, el control con cualquier día sin marca y los intervalos de solo series van `null` o vacíos (los días ya emitidos sí se muestran: son seguimiento). Una regla `source` o `latest` se lee una vez, de la última corrida cargada que la registró, y una `per_run` se suma sobre las cargadas; `validation_rules.json` usa `series_days` (no `rows`) porque la unidad de este proyecto es la serie-día. Decisiones del contrato que el plan no fijaba: `day_states` lleva `shares` y `counts`; `operation.forecast[]` trae `wape` y `bias` de la prueba (`null` hasta el sello) y, al lado, `valid_wape`, `valid_bias` y `valid_fit_blocks`; `tiers_now[]` trae las celdas de cada grupo indistinguible con su aumento mayor y menor; `intervals.pairs` y `overlapping_two_way` salen del sello del lanzamiento hasta que la evaluación escribe `eval_pairs`. `figures.py` dibuja las nueve figuras solo desde los archivos que `read_site` verificó (sin SQLite ni Parquet) y dice, cuando la prueba no está sellada, que lo que muestra es la validación y con qué bloques se ajustó. Una prueba compara todo lo publicado (Parquet, JSON, HTML, sello, resumen y PNG) con la carpeta, el usuario y el equipo y no encuentra ninguno. El script de marca-personal (`scripts/export-promotion-lift.py`) y la página son de U21 y de la evaluación.

- **Contexto**: el sitio copia los JSON con un script que verifica el manifiesto (proyectos 04 y 05); el conjunto no tiene personas (tiendas y productos con números).
- **Opciones**: un solo camino razonable.
- **Decisión**: los cinco JSON de la sección 21 con su manifiesto al final, nada de la prueba antes del sello, la prueba de rutas locales del proyecto 05 sobre todo lo publicado; sin enmascarado.
- **Motivo**: el contrato ya lo consume marca-personal; cambiarlo después es de riesgo alto (ítem 3).
- **Afecta**: `site_export.py`; AC26; RNF12.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D37 La cifra del artículo (1,43 veces) no va al sitio por defecto

- **Contexto**: el artículo informa una mediana de uplift por serie de 1,43 (IQR 1,05 a 2,06) con otra definición y controlando festivos; research.md midió 1,38 con la suya, y este plan usa un cociente de sumas (D10), no una mediana por serie.
- **Opciones**: (a) mostrarla en el sitio junto a la propia; (b) citarla solo en la documentación, con la definición.
- **Decisión**: (b). La ficha y el README la citan con su definición y la diferencia de método.
- **Motivo**: en el sitio, dos cifras con definiciones distintas se leerían como una contradicción o como una validación que no es.
- **Afecta**: README; la ficha; el sitio (fila 18).
- **Quién**: agente de planificación.
- **Estado**: pendiente del dueño (plan, sección 29, ítem 1).

## D38 Contradicciones con el sitio, incluido «en línea o en tienda»

- **Contexto**: research.md encontró que el sitio dice 863 productos (son 865), «en línea o en tienda» (el artículo dice pedidos en línea y no hay campo de canal), «Descuento, de 0,5 a 1», «cada promoción» (la unidad es la celda), «ordenadas por lo que suman» (es un porcentaje) y statsmodels.
- **Opciones**: un solo camino razonable: proponer cada corrección como una fila de `SITE-UPDATES.md`; el texto final es del dueño.
- **Decisión**: las 18 filas del plan, sección 30; «pedidos en línea» como propuesta para el canal.
- **Motivo**: el sitio debe decir lo que los datos permiten (S9).
- **Afecta**: `SITE-UPDATES.md`; la página `promotion-lift`.
- **Quién**: agente de planificación.
- **Estado**: pendiente del dueño (plan, sección 29, ítem 2).

## D39 Memoria: medida y con el contador nombrado

- **Contexto**: los tensores float32 de 06 a 21 pesan 288 MB cada uno; `p04` tuvo en memoria tensores de 64 bits de las 24 horas y no midió su pico.
- **Opciones**: un solo camino razonable: el contador del proyecto 05.
- **Decisión**: `PeakWorkingSetSize` en Windows y `ru_maxrss` en Linux, por tarea y por corrida; RNF03 de 12 GB como supuesto a confirmar en U19; el cubo con `mmap_mode="r"`.
- **Motivo**: una cifra de memoria sin su contador no se puede comparar (lección del proyecto 02).
- **Afecta**: `sysinfo.py`; RNF03; AC34.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D40 Unidades de trabajo, commits y estrategia de entrega

- **Contexto**: el pronóstico es de unas 8.600 líneas en 21 unidades (plan, sección 27), con un rango realista de 8.500 a 13.000; la entrega del documento de seguimiento es `ask-on-risk`.
- **Opciones**: un solo camino razonable para las unidades; la estrategia de PR es del dueño.
- **Decisión**: las 21 unidades en orden, cada una con su RED, su suite medida y su commit; las de riesgo alto (U01, U04, U09 a U16, U18 y U19) en su propio commit para que la revisión nativa las tome solas; la estrategia de PR, `stacked-to-main` o `feature-branch-chain`, la elige el dueño antes de un PR.
- **Motivo**: unidades de unas 400 líneas con sus pruebas se revisan solas; las de riesgo alto no se mezclan.
- **Afecta**: la construcción; el documento de seguimiento.
- **Quién**: agente de planificación.
- **Estado**: vigente; la estrategia de PR, pendiente del dueño (plan, sección 29, ítem 14).

## D41 La semana de prueba se remuestrea con la semilla más uno, y el lanzamiento se reconstruye con su propia semilla para compararlos

- **Contexto**: C06 pide remuestrear por separado lo sellado y la prueba y restar remuestra a remuestra; el generador de pesos de `bootstrap.two_way_draws_many` toma primero los pesos de las series, de modo que dos poblaciones con las mismas series y la misma semilla comparten esos pesos. El sello guarda el aumento y el intervalo de cada celda del lanzamiento, no sus remuestras.
- **Opciones**: (a) usar la misma semilla en las dos y restar; (b) usar para la semana la semilla de la configuración más uno (como ya hace la réplica del lanzamiento sobre la validación) y reconstruir las remuestras del lanzamiento con su semilla desde el artefacto; (c) aproximar la diferencia con los dos intervalos publicados, como si fueran normales e independientes.
- **Decisión**: (b). `evaluation.SEED_OFFSET = 1` para todos los intervalos de la semana de prueba (efectos, C04, pronósticos y variantes); el lanzamiento se lee del cubo, se recupera con el método sellado y se estima con el contrafactual del artefacto, y una comprobación exige que sus aumentos sean los sellados (`SealError` si no).
- **Motivo**: (a) correlaciona las dos remuestras y estrecha la diferencia sin decirlo; (c) supone una distribución que no se midió; (b) cuesta una lectura más del período del lanzamiento, pero deja la diferencia con la dispersión que sus dos lados tienen por separado.
- **Afecta**: `evaluation.py`; `variants.py`; C04-C09; las filas `test` de `effect_estimates`.
- **Quién**: agente de construcción (Sonnet), U11.
- **Estado**: vigente.
