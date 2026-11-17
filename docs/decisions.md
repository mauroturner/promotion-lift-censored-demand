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
- **Estado**: vigente; la descarga en el paquete, pendiente del dueño (plan, sección 29, ítem 6).

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
- **Estado**: vigente.

## D09 El efecto y su control de la confusión: un contrafactual de la misma serie y la misma hora, ajustado por el día del grupo, con IPF

- **Contexto**: la promoción se asigna por serie y producto, casi nada por calendario (research.md); la venta del fin de semana es 17 % a 19 % mayor; la validación vende 17,9 % más que el entrenamiento. La cuenta cruda da +11,1 % y la emparejada por serie y hora +33,6 % (research.md). El sitio declara statsmodels para «un modelo del efecto».
- **Opciones**: (a) el cociente emparejado por serie y hora de research.md; (b) una regresión de Poisson con efectos fijos de serie-hora y de grupo-día en statsmodels; (c) el mismo modelo de Poisson multiplicativo, `m(s, h, d) = a(s, h) · b(g, d)`, ajustado solo sobre los días `regular` por ajuste proporcional iterativo, y el aumento como observado sobre contrafactual (un estimador por imputación); (d) un modelo de series de tiempo con control sintético (Brodersen et al., 2015).
- **Decisión**: (c), con 30 iteraciones (cambio máximo de `b` entre 30 y 60: 3,65 · 10⁻¹⁴; `p05`). Todo aumento se publica como una asociación dentro de la serie, ajustada por la hora y por el día del grupo, nunca como causal.
- **Motivo**: (c) controla lo que (a) controla (producto, tienda, hora) y además el día de la semana, los feriados, el cambio de nivel y los choques comunes de cada grupo, sin ajustar 1,2 millones de efectos fijos con una matriz (lo que (b) necesitaría y statsmodels no maneja a esta escala **[Inferido]**); el IPF es el estimador de máxima verosimilitud de ese modelo y se escribe con NumPy en unas decenas de líneas; (d) es para una serie tratada, no para 35.000. No controla la razón por la que se lanzó la promoción (si se esperaba más demanda), y eso se dice.
- **Afecta**: `effect.py`; `fact_*_effect`; el sitio (filas 8 y 9); D32.
- **Quién**: agente de planificación.
- **Estado**: vigente.

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
- **Estado**: vigente; las bandas y el mínimo, pendiente del dueño (plan, sección 29, ítem 4).

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
- **Estado**: vigente.

## D16 Criterios C01-C10 y lo que se vio antes de fijarlos

- **Contexto**: el planificador midió casi todo sobre el entrenamiento y la validación (sección 4 de los requerimientos); los proyectos 03 a 05 dijeron lo esperable antes de medir.
- **Opciones**: un solo camino razonable: fijar los criterios con dos columnas de lo visto, la de la investigación y la del planificador, y lo esperable escrito.
- **Decisión**: los diez de `requirements.md`, sección 8.1, con sus umbrales en `[criteria]` (sellados) y lo esperable: C01, C02, C04, C05, C07 y C08 deberían cumplirse; C03 es incierto; C06 y C09 probablemente no.
- **Motivo**: un criterio que se sabe que no se cumplirá se deja igual, porque es lo que el sitio tiene que decir.
- **Afecta**: `evaluation.py`; `texts.py`; el resumen; el README; el sitio.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D17 La prueba se lee una vez: lanzamiento congelado y sello con una huella que cubre cada clave que cambia un valor sellado

- **Contexto**: la lección de los proyectos 02 a 05 (B4 del 03, D89 del 04): la prueba se toca una vez y una configuración distinta después del sello no reemplaza lo sellado.
- **Opciones**: un solo camino razonable: el sello del proyecto 05, adaptado.
- **Decisión**: `reports/model_seal.json` con la parte del lanzamiento y la de la prueba, cada una de creación exclusiva; `FINGERPRINT_KEYS` y `UNSEALED_KEYS` con una prueba de que cada hoja está en una; `config_sha256` es la huella de la vista sellada y `config_file_sha256` la del TOML (A8 del 05); con otra configuración todo es `post_seal`; la evaluación de la prueba con otra configuración mientras el sello no tiene la prueba se rechaza antes de escribir y alcanza a toda tarea de la corrida del cierre; ninguna prueba `real_data` lee la semana de prueba antes de U19.
- **Motivo**: incluir de más es seguro; incluir de menos es el defecto B4 del proyecto 03.
- **Afecta**: `config.py`; `registry.py`; `pipeline.py`; AC18, AC19.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D18 Operación simulada: un lanzamiento con los 90 días, siete entregas diarias y un cierre que evalúa

- **Contexto**: el sitio promete «cada día un flujo carga las ventas por hora, marca las horas sin stock y deja la demanda corregida lista para el modelo». El conjunto es una extracción fija de 97 días.
- **Opciones**: (a) una sola corrida con todo; (b) el lanzamiento, una entrega por día de la prueba y un cierre sin filas que evalúa.
- **Decisión**: (b). Cada diaria recupera su día con el método sellado, ajusta `b(g, d)` con sus días `regular`, emite el efecto del día, los pronósticos y la máscara de cola del día (solo inserción); nada diario cambia el método, `a` ni los aumentos sellados.
- **Motivo**: es lo que el sitio describe, separa lo emitido de lo evaluado (lo que se evalúa es lo que se emitió) y prueba la independencia del tamaño de la entrega (AC12).
- **Afecta**: `deliveries.py`; `daily.py`; `pipeline.py`; el sitio (fila 13).
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D19 La trampa de fuga M01 y la demostración de la fuga de los campos diarios

- **Contexto**: `sale_amount` es la suma de las horas (research.md): en una máscara sintética contiene la venta de las horas ocultas, así que una recuperación que lo lea acierta casi siempre en la simulación y nunca en un quiebre real (donde esas horas venden casi cero). La razón del método elegido sobre R1 en V1 es 30,06 / 35,38 = 0,85 (`p06`).
- **Opciones**: (a) confiar en la lista de columnas prohibidas; (b) la lista más una trampa: si el método elegido tiene en V1 un WAPE por serie menor que 0,5 × el de R1, el lanzamiento se detiene; más una demostración que mide una recuperación con `sale_amount` y la muestra.
- **Decisión**: (b): M01 con `leak_tripwire_ratio = 0,5`; `leakage_demo.py` mide en V2 la recuperación con `sale_amount` frente a la sellada y la publica en `fact_leakage` y `algorithms.json`, con la explicación.
- **Motivo**: la lista evita la fuga conocida; la trampa atrapa una que nadie previó; 0,5 deja lugar a una mejora real (0,85) y atrapa una fuga (que daría cerca de 0) **[Inferido]**.
- **Afecta**: `recovery.py`; `launch.py`; `leakage_demo.py`; AC13; runbook R5.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D20 El artefacto: un `.npz` sin objetos de Python, y R3 en un pickle leído solo con su huella

- **Contexto**: el lanzamiento congela `base`, la distribución del corte, `a` y `b` de las dos versiones y los aumentos; son arreglos. R3 es un objeto de scikit-learn. El proyecto 05 cargó su artefacto con pickle bajo huella (su D39).
- **Opciones**: (a) todo en un pickle bajo huella; (b) los arreglos en `.npz` leído con `allow_pickle=False`, y R3 en un pickle bajo huella; (c) dejar R3 fuera para no tener ningún pickle.
- **Decisión**: (b). `load_artifact` comprueba tamaño y SHA-256 contra el registro antes de leer; un `.npz` con un arreglo de objetos se rechaza (M03). R3 se carga con el procedimiento del proyecto 05 (los bytes una vez, `hmac.compare_digest`, `pickle.loads` de esos bytes).
- **Motivo**: lo que el flujo usa cada día (R2 y el contrafactual) no pasa por pickle; R3 se conserva como comparación medida en la prueba (C10); (c) perdería esa comparación.
- **Afecta**: `registry.py`; M03; AC20; runbook R6.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D21 Cada cifra dice con qué se ajustó, el resumen sale del sello después del sello y ninguna cifra se escribe a mano

- **Contexto**: en el proyecto 05, una condición de la compuerta se midió sobre el modelo reajustado con ese bloque (A2), tres límites de intervalo se redondearon a mano en dos documentos (B3) y los documentos contaron unidades que el registro todavía no tenía (B4).
- **Opciones**: un solo camino razonable: cerrar las tres clases con reglas y pruebas.
- **Decisión**: toda fila de validación lleva `fit_blocks` y una prueba exige que ninguna cifra de un bloque venga de un método ajustado con ese bloque; después del sello, el resumen toma del sello lo que el almacén no tiene, comprobado a 6 decimales; toda cifra de los documentos sale del resumen o del sello por `docs-sync` o se compara con ellos a sus decimales; la documentación se sincroniza después de que el registro tiene su entrada.
- **Motivo**: son las clases que la evaluación del proyecto 05 encontró; cada una tiene su prueba con nombre (plan, sección 24.2).
- **Afecta**: `launch.py`; `reporting.py`; `tests/docs/`; RNF14; AC22, AC37.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D22 Almacén: SQLite para lo relacional y un cubo de NumPy para las horas

- **Contexto**: 4.850.000 series-días con 24 horas cada una son unos 116 millones de valores por campo horario; ninguna consulta SQL los necesita sueltos. El proyecto 05 usó SQLite en capas.
- **Opciones**: (a) todo en SQLite, una fila por hora; (b) SQLite para series, series-días, entregas, corridas, validación, efectos, pronósticos y evaluación, y archivos `.npy` por entrega para las horas, con manifiesto; (c) DuckDB (fuera del landing).
- **Decisión**: (b), con `np.load(..., mmap_mode="r", allow_pickle=False)` y el SHA-256 de cada archivo en el manifiesto; las sumas por serie-día de SQLite se comprueban contra el cubo (V14, `chk_sums_match_cube`).
- **Motivo**: (a) haría un almacén de varios GB y cargas lentas **[Inferido]**; (c) agrega una tecnología sin necesidad; (b) deja SQL donde el landing lo declara y el cómputo horario en NumPy.
- **Afecta**: `cube.py`; `warehouse.py`; `sql/`; RNF03, RNF10.
- **Quién**: agente de planificación.
- **Estado**: vigente.

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

## D29 La suite rápida: límite de 120 s y presupuesto de trabajo de 90 s

- **Contexto**: el proyecto 05 terminó en 76,3 s tras tres unidades de velocidad y pasó una vez los 90 s (A3).
- **Opciones**: (a) el mismo límite y presupuesto; (b) un presupuesto más bajo.
- **Decisión**: (a): 120 s y 90 s, medidos después de cada unidad; un accesorio de 300 series que cabe en la suite; los estados caros una vez por sesión; las pruebas lentas con nombre en el plan, sección 24.1.
- **Motivo**: el presupuesto de 90 s alcanzó en el 05 con margen para las correcciones; el accesorio de aquí es más chico que el cubo real por cuatro órdenes.
- **Afecta**: `tests/conftest.py`; RNF15; AC38.
- **Quién**: agente de planificación.
- **Estado**: vigente.

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
- **Estado**: vigente.

## D35 Salidas para Power BI y diseño del tablero en HTML

- **Contexto**: S4: lo que necesita Power BI Desktop se entrega como tablas y un diseño en HTML.
- **Opciones**: un solo camino razonable: el modelo estrella y el HTML del proyecto 05, adaptados.
- **Decisión**: las 10 dimensiones y 15 hechos del plan, sección 19, con las relaciones R01-R21; las 21 medidas y las cinco páginas de la sección 20; las medidas de la prueba leen solo filas `sealed`.
- **Motivo**: el contrato con Power BI es estable y está probado; las medidas no se ejecutan, por eso U13 es de riesgo alto (ítem 6).
- **Afecta**: `dashboard/`; `export.py`; AC24, AC25.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D36 Exportación para el sitio, con manifiesto, y nada personal en lo publicado

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
