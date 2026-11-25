# Qué promociones venden de verdad

[English](README.md) · **Español**

| | |
| --- | --- |
| **Propuesta de valor** | Un ranking de qué combinaciones de grupo de gestión y descuento venden más que lo que esas mismas series habrían vendido sin promoción, corregido por la demanda que esconden las horas sin stock, con su intervalo del 95 % y medido contra la semana siguiente |
| **Stack tecnológico** | Python 3.11, NumPy, pandas, PyArrow, scikit-learn (solo para la comparación R3), SQLite y SQL, Parquet, Matplotlib, pytest, Apache Airflow 3.4.0 sobre Docker Compose, y el diseño de un tablero de Power BI en HTML |
| **Técnicas** | Recuperación de la demanda censurada por los quiebres, validada con una censura sintética; contrafactual de la misma serie por ajuste proporcional iterativo (IPF); remuestreo de dos vías (series y días); ranking con grupos indistinguibles; partición en el tiempo con una semana de prueba sellada |
| **Para auditar** | [Ficha del modelo](docs/model-card.md) · [Evaluación independiente](docs/evaluation.md) · [Última corrida: validación](reports/validation/latest.md) · [Última corrida: resultados](reports/evaluation_summary.md) |

Este README sigue la estructura común de los proyectos de datos del portafolio, descrita en `ESTRUCTURA-PROYECTOS.md` en la raíz del portafolio.

## 1. Resumen ejecutivo

### 1.1 Problema de negocio y solución

Un flujo que carga cada día las ventas por hora de 50.000 series tienda × producto de un comercio de perecederos con pedidos en línea, las valida, marca las horas sin stock y recupera la demanda que esconden; estima cuánto sube la venta en los días con promoción frente a lo que esa misma serie vendería a esa hora sin ella, con un intervalo del 95 %, y ordena las combinaciones de grupo y descuento sin presentar como distintas las que se pisan. Y mide, con criterios fijados antes de construir, si ese resultado se repite en la semana siguiente: **el orden de qué promociones venden más se repite y el tamaño de cada aumento no, y el aumento de cada celda mejora un pronóstico frente a un aumento único pero no supera a mirar la última semana de la propia serie.**

**El problema.**

Un comercio de perecederos lanza descuentos casi todas las semanas y quiere saber cuáles venden de verdad. La cuenta habitual compara la venta de los días con promoción con la de los días sin ella, y sale mal por dos motivos. Los días con promoción son de otros productos: la promoción se asigna por serie y por producto, no por calendario, y la serie explica el 44 % de su variación y el producto el 35 %, mientras que el día de la semana, la semana y el feriado juntos explican menos del 0,5 %. Y en las horas sin stock la venta cae aunque la gente quiera comprar, así que la venta observada esconde parte de la demanda, y más en los días con promoción. Comercial decide qué descuento repetir mirando un aumento que mezcla productos y quiebres, categoría no sabe si una línea responde más a la promoción o solo se quedó sin stock antes, y abastecimiento no ve cuánta demanda se perdió.

El dato es FreshRetailNet-50K (Dingdong-Inc, Hugging Face, CC BY 4.0): 50.000 series de 898 tiendas en 18 ciudades y 865 productos, 97 días (2024-03-28 a 2024-07-02), con 24 valores horarios de venta y de estado del stock por serie-día y un par de campos de promoción. La venta está normalizada y sin unidades, no hay precio ni canal ni identificador de promoción, y la marca y el descuento no coinciden: el 14,11 % de las series-días tiene un descuento sin marca. En las horas de 06 a 21, el 19,9 % de las horas está sin stock, desde el 6,2 % a las 6 h hasta el 41,0 % a las 21 h.

**La solución.**

Un flujo de once tareas que simula la operación sobre el archivo histórico: un lanzamiento con los 90 días de entrenamiento y reajuste, siete entregas diarias (2024-06-26 a 2024-07-02, la semana de prueba) y un cierre que evalúa, nueve corridas más una décima sin entrega. En cada una carga las series-días de la entrega en SQLite, las valida con 31 reglas, marca las horas sin stock, recupera la demanda de esas horas y emite, por celda de promoción, la suma observada, la contrafactual y el aumento del día, y por serie-día con promoción cuatro pronósticos. Lo emitido no se cambia.

Cuatro piezas hacen el trabajo:

1. **Los estados del día.** Cada serie-día es `promo` (marca con descuento válido), `regular` (sin marca y sin rebaja: el control), `unflagged_cut` (descuento sin marca, que se mide aparte) o `anomalous` (descuento 0 o mayor que 1, que se cuenta y se aparta).
2. **La recuperación de la demanda** (R0 cero, R1 la media de la serie, la hora y el estado, R2 R1 escalada por el nivel del mismo día y R3 gradient boosting con pérdida de Poisson), elegida en V1 con una censura sintética de horas que sí tuvieron stock, donde la venta real se conoce, y juzgada por la masa que devuelve sumada por serie. Gana R2 con κ = 0,25.
3. **El contrafactual de la misma serie, la misma hora y el mismo día del grupo** (ajuste proporcional iterativo, IPF, sobre los días `regular`), con el aumento como observado sobre contrafactual, en dos versiones (venta cruda y demanda recuperada) y con un intervalo del 95 % que remuestrea series y días enteros.
4. **El ranking de celdas** (7 grupos de gestión × 7 bandas de descuento, con al menos 30 series) en grupos indistinguibles: dos celdas cuyos intervalos se pisan no se presentan como distintas.

El resultado central no es un modelo sino una medición. Se compara con criterios C01-C10 fijados antes de construir, con lo esperable escrito por adelantado (que C06 y C09 probablemente no se cumplirían), y se sella: la prueba se evalúa una sola vez y lo sellado no se reescribe. Cada cifra de validación dice con qué bloques de días se ajustó su método. Salió desfavorable en tres criterios: el pronóstico con el aumento de la celda no supera a la regla ingenua (C09), el tamaño de cada aumento no se repite (C06) y recuperar la demanda no cambió el aumento total de forma detectable (C04).

- **La corrección de dos fuentes de error**: comparar productos distintos, que explica la mayor parte de la diferencia entre la cuenta ingenua (+20,6 % sobre los 90 días) y el aumento dentro de la serie (+52,0 % crudo), y las horas sin stock, que esconden mucho menos.
- **Un efecto descriptivo, no causal**: todo aumento es una asociación dentro de la serie, ajustada por la hora y el día del grupo; no dice si la promoción se lanzó porque se esperaba más demanda.
- **El flujo y el sello**: nueve corridas validadas y cargadas todo o nada, un modelo congelado y una prueba evaluada una vez bajo un sello que no se reescribe, con un solo escritor por carpeta de datos.
- **El tablero y el sitio**: las 25 tablas del modelo estrella, el diseño de cinco páginas en HTML y cinco JSON pequeños para el sitio, con un manifiesto que se escribe al final.

**Para qué sirve.**

- **Equipo comercial.** Ve cuáles combinaciones de grupo y descuento vendieron más que el contrafactual de su propia serie en el período, con su intervalo y con el aviso de cuáles no se distinguen. El orden es confiable de una semana a la siguiente (C05, C07); el tamaño de cada aumento no (C06), así que sirve para decidir qué descuento repetir y no para prometer cuánto va a subir la venta la semana que viene.
- **Equipo de categoría.** Ve que, en este conjunto, comparar productos distintos explica la mayor parte de la diferencia de la cuenta habitual, y que recuperar la demanda de las horas sin stock cambia poco el aumento total (C04).
- **Abastecimiento.** Ve cuánto de la demanda de los días con promoción queda escondido en las horas sin stock (la masa recuperada) y la tasa de quiebre por hora, con la aclaración de que la recuperación es una cota inferior.
- **Quien trabaje con datos de comercio** ve cómo se juzga una recuperación sin verdad, por qué una métrica horaria premia al cero, cómo se estima un aumento dentro de la serie y cómo se evalúa una vez, con criterios fijados antes.
- **Para un tablero:** las tablas en estrella y el diseño en HTML dicen cómo armar las cinco páginas en Power BI Desktop.

Lo que no sirve: leer un aumento como causal, prometer el aumento de una promoción futura, hablar de ingreso o margen (no hay precio y la venta está normalizada), identificar una promoción individual (la unidad es la celda), ni generalizar más allá de 18 ciudades de un país y 97 días de un solo operador.

### 1.2 Criterios de éxito e impacto

Los criterios C01-C10 se fijaron y se confirmaron en Git antes del primer código (`docs/requirements.md`, sección 8.1; `docs/decisions.md`, D16), con lo que se esperaba de cada uno: que C06 y C09 probablemente no se cumplirían y que C01, C02, C04, C05, C07 y C08 sí. Ningún criterio ni umbral se cambió.

Lo que el proyecto encontró, medido en la semana de prueba, una sola vez y bajo un sello (seis de los nueve criterios con umbral se cumplen; una evaluación independiente recalculó cada cifra y la encontró exacta):

- **El orden de las celdas se repite** (C05: Spearman 0,897 sobre 36 celdas) y **más descuento da más aumento** (C07: 1,000), pero **el tamaño de cada aumento no se repite**: el intervalo de la diferencia entre la prueba y lo sellado contiene 0 en el 58,3 % de las celdas, y se pedía el 80 % (C06, no se cumple, como se esperaba).
- **El aumento de cada celda mejora el pronóstico frente a un aumento único** (C08) **pero no supera a la regla ingenua**, la media de los 7 días anteriores de la propia serie: WAPE 40,3 % frente a 35,0 % (C09, no supera, como se esperaba).
- **Recuperar la demanda de las horas sin stock funciona como método** (C01 a C03: WAPE por serie 31,1 % frente a 35,6 % de la media simple, sin sesgo grande) **pero en la semana de prueba no cambia el aumento total de forma detectable**: +47,9 % recuperado frente a +46,5 % crudo, una diferencia de +1,37 puntos que va de −1,81 a +4,36 (C04, no se cumple, y es el único criterio que se esperaba cumplido y no lo hizo).
- **El tiempo de la corrida diaria se corrigió** (RNF02): en la corrida real tardaba de 62 a 68 s contra un límite de 60 s; con la corrección que siguió a la evaluación independiente (D46), una repetición real sobre una copia dio de 42 a 44 s, y la de la comprobación (L88), de 41 a 46 s.

Cada criterio contra su resultado, en [5.1](#51-evaluación-frente-a-criterios-de-éxito); el bloque completo que genera el flujo, en [Resultados completos de la corrida](#resultados-completos-de-la-corrida).

## 2. Datasets y preparación

### 2.1 Fuentes, alcance y granularidad

| | |
| --- | --- |
| Fuente | FreshRetailNet-50K (Dingdong-Inc, Hugging Face, CC BY 4.0), commit `c374e859` |
| Archivos | `train.parquet`, 106.436.287 bytes, 4.500.000 filas; `eval.parquet`, 8.440.124 bytes, 350.000 filas; las huellas completas están en «Fuente y licencia» |
| Series | 50.000 series tienda × producto, de 898 tiendas en 18 ciudades y 865 productos; 7 grupos de gestión y 32 primeras categorías |
| Período | 97 días, del 2024-03-28 al 2024-07-02; 90 de entrenamiento y reajuste y 7 de prueba |
| Por fila | 24 valores horarios de venta (normalizada, sin unidades) y de estado del stock (0 o 1), y nueve campos diarios: la marca de promoción, el descuento, el feriado y el clima, entre otros |
| Lo que no trae | Precio, canal, unidades y un identificador de promoción: la unidad de análisis es la celda de grupo y banda, no la promoción |

Los 19 campos de los dos archivos, con su tipo, su uso (identificador, se usa o prohibido) y su significado, y una tabla por cada Parquet de salida, están en el [diccionario de datos](docs/data-dictionary.md).

La partición en el tiempo, por día, con 7 días de purga entre el entrenamiento y V1:

| Bloque | Días | Fechas | Para qué |
| --- | --- | --- | --- |
| Entrenamiento | 65 | 2024-03-28 a 2024-05-31 | Ajustar R1-R3 y el contrafactual de la elección |
| Purga | 7 | 2024-06-01 a 2024-06-07 | Ninguno |
| V1 | 9 | 2024-06-08 a 2024-06-16 | Elegir el método de recuperación y κ |
| V2 | 9 | 2024-06-17 a 2024-06-25 | Vista previa de la recuperación y réplica del entrenamiento; no elige nada |
| Prueba | 7 | 2024-06-26 a 2024-07-02 | `eval.parquet`; se evalúa una vez, con lo sellado |

El lanzamiento reajusta con los 90 días hasta 06-25. No hay estacionalidad anual: 97 días no la contienen (D14).

![El perfil horario de la venta y de los quiebres](docs/figures/hour_profile.png)

### 2.2 Saneamiento y reglas de calidad

**Los estados del día.** Cada serie-día es `promo` (marca con descuento válido), `regular` (sin marca y sin rebaja: el control), `unflagged_cut` (descuento sin marca, que se mide aparte) o `anomalous` (descuento 0 o mayor que 1, que se cuenta y se aparta).

El conjunto esconde cosas que el proyecto mide y no corrige a ciegas:

- **Los dos campos de promoción no coinciden.** La marca (`activity_flag`) y el descuento (`discount`) discrepan: hay descuento sin marca en el 14,11 % de las series-días (635.063) y marca sin descuento en 38.405. Un descuento 0 (16.039 filas) y uno mayor que 1 (34) no se pueden interpretar y se apartan; uno de 0 a 0,5 es la banda más profunda.
- **Los quiebres son colas del día.** El 86,41 % de las series-días que se quedan sin stock entre 06 y 21 siguen así hasta las 21 h; la primera hora sin stock tiene mediana 15 h, y en el bloque de entrenamiento (la distribución que sella el lanzamiento para la censura sintética) el 14,7 % de las que se quedan sin stock empiezan a las 6 h. Los quiebres llegan antes en los días de más demanda: una censura que depende de la demanda.
- **La noche casi no vende** (el 4,8 % de la venta cae de 22 a 5 h) y no se recupera ni se mide: el análisis cubre las horas de 06 a 21.
- **Dos campos diarios son sumas de las horas**: `sale_amount` y `stock_hour6_22_cnt` contienen el objetivo del mismo día, y un método que los lea acierta en la simulación y nunca en un quiebre real. El flujo los descarta al leer y tiene una trampa de fuga (M01) que detiene el lanzamiento.

Cada entrega se valida con 31 reglas antes de cargarse; una regla bloqueante que falla pone la entrega en cuarentena y rechaza la corrida sin escribir en SQLite (`docs/runbook.md`, R3).

![La primera hora sin stock de las series-días que se quedan sin stock](docs/figures/first_stockout.png)

## 3. Arquitectura y metodología

Un flujo de once tareas, las mismas desde la línea de comandos y desde el DAG de Airflow en Docker, simula la operación sobre el archivo histórico en nueve corridas (el lanzamiento, siete entregas diarias y el cierre): comprueba la fuente, publica la entrega siguiente, la valida, la carga en SQLite, recupera la demanda de las horas sin stock, congela y sella el modelo en el lanzamiento, emite el aumento de cada celda y los pronósticos, evalúa la prueba una sola vez en el cierre y exporta el modelo estrella, el diseño del tablero y los archivos del sitio.

### 3.1 Fuente e ingesta

Sobre la fuente: los dos Parquet se tratan como no confiables. Los lee pyarrow con tope de bytes, de filas y de grupos de filas, esquema exacto, listas horarias de largo 24 sin nulos y claves únicas, y se aceptan solo si su tamaño y su SHA-256 son los fijados. El flujo no descarga nada: los coloca quien corre el proyecto (ver «Cómo correrlo de punta a punta»).

La segunda tarea hace de sistema de origen: como el conjunto es una extracción fija de 97 días, el flujo lo reparte en un lanzamiento con los 90 días de `train.parquet`, siete entregas diarias con un día de `eval.parquet` cada una y un cierre sin filas que evalúa, y una décima corrida termina `no_delivery`. La tercera corta el flujo, sin tocar nada, si la entrega no cumple el contrato. Un día se conoce completo al cerrar (un supuesto, no un dato del conjunto).

### 3.2 Orquestación y transformación

Once tareas que corren siempre en este orden, las mismas desde la línea de comandos (`python -m promolift run`) y desde el DAG de Apache Airflow (`promolift_daily`):

```mermaid
flowchart LR
  A[fetch_source<br/>dos Parquet con tamaño y huella fijados] --> B[deliver<br/>la siguiente entrega]
  B --> C[validate<br/>31 reglas]
  C --> D[load<br/>SQLite, todo o nada]
  D --> E[recover<br/>demanda de las horas sin stock]
  E --> F[fit_model<br/>elige, congela y sella en el lanzamiento]
  F --> G[estimate<br/>aumento por celda y pronósticos]
  G --> H[evaluate<br/>la prueba, una vez]
  H --> I[export<br/>25 Parquet y 5 JSON]
  I --> J[render_dashboard<br/>HTML]
  J --> K[report<br/>cierra la corrida]
```

El DAG `promolift_daily` corre una vez por día, con una corrida y una tarea activas a la vez, porque el almacén es un SQLite de un solo escritor. Un rechazo de la validación, de la fuente, de la trampa de fuga o de la corrida falla la tarea sin reintentos, porque falla igual con los mismos datos; otro error (la red, el disco) reintenta según la tarea (`airflow/dags/promolift_daily.py`, `src/promolift/pipeline.py`).

El método se elige una sola vez, en el lanzamiento, y queda congelado: su artefacto (un `.npz` sin objetos de Python) se lee solo si su tamaño y su SHA-256 coinciden con los registrados. Lo emitido se escribe en tablas de solo inserción. El sello guarda la huella de cada clave de la configuración que cambia un valor sellado: una evaluación de la prueba con otra configuración se rechaza antes de escribir, y lo que se calcule después con otra configuración se informa aparte, como posterior al sello. Un solo proceso escribe la carpeta de datos a la vez: cada tarea toma un bloqueo y un segundo proceso se rechaza con código 2 sin escribir.

### 3.3 Almacenamiento y modelado de datos

**El almacén.** SQLite guarda lo relacional (las series, las series-días, las entregas, las corridas, la validación, los efectos, los pronósticos y la evaluación) y un cubo de NumPy guarda las 24 horas de cada serie-día, en archivos `.npy` por entrega con el SHA-256 de cada uno en un manifiesto; las sumas por serie-día de SQLite se comprueban contra el cubo (D22). Lo emitido se escribe en tablas de solo inserción.

**Las tablas del modelo estrella** (`outputs/powerbi/`): 10 dimensiones y 15 hechos en Parquet, con claves únicas e integridad referencial, descritas en `docs/data-dictionary.md`.

### 3.4 Experimentación y Machine Learning

El resultado central no es un modelo sino una medición. Se compara con criterios C01-C10 fijados antes de construir, con lo esperable escrito por adelantado (que C06 y C09 probablemente no se cumplirían), y se sella: la prueba se evalúa una sola vez y lo sellado no se reescribe. Cada cifra de validación dice con qué bloques de días se ajustó su método. Salió desfavorable en tres criterios: el pronóstico con el aumento de la celda no supera a la regla ingenua (C09), el tamaño de cada aumento no se repite (C06) y recuperar la demanda no cambió el aumento total de forma detectable (C04).

#### 3.4.1 Ingeniería de características y línea base (baseline)

**La cuenta que sale mal.** Comparar la venta de los días con promoción con la de los días sin ella da +20,6 % sobre los 90 días, porque mezcla productos. Comparar cada serie consigo misma, a la misma hora y ajustando por el día de su grupo, da +52,0 % crudo y +52,9 % recuperado: la mayor parte de la diferencia es mezcla de productos y no quiebres.

La unidad es la serie-día, con sus horas de 06 a 21. Lo que leen los métodos: el estado del día (`promo`, `regular`, `unflagged_cut` o `anomalous`), que sale de la marca y del descuento; la media de las horas con stock de la serie, la hora y el estado (R1); el nivel observado ese mismo día antes del quiebre (R2); y, para el contrafactual, solo los días `regular`. Las líneas base que cada método debe superar: la cuenta ingenua para el efecto, la media simple R1 para la recuperación (C01) y, para el pronóstico, F2a (un solo aumento, C08) y F1, la media de los 7 días anteriores de la propia serie (C09).

#### 3.4.2 Decisiones de modelado y ablación (ADR)

**La recuperación de la demanda** (R0 cero, R1 la media de la serie, la hora y el estado, R2 R1 escalada por el nivel del mismo día y R3 gradient boosting con pérdida de Poisson), elegida en V1 con una censura sintética de horas que sí tuvieron stock, donde la venta real se conoce, y juzgada por la masa que devuelve sumada por serie. Gana R2 con κ = 0,25.

**La demanda de las horas sin stock** (`recovery.py`). R1 es la media de las horas con stock de la serie, la hora y el estado; R2 la multiplica por el nivel del mismo día, `k = (O + κ·m) / (E + κ·m)`, con κ de 0,25 a 2; R3 es un `HistGradientBoostingRegressor` con pérdida de Poisson. A nivel de la hora, ningún método supera a predecir cero (el WAPE horario de cero es 100 % y el de cualquier método pasa de 108 %), porque la venta horaria es intermitente: por eso la recuperación se juzga por la masa que devuelve sumada por serie, con una censura sintética que oculta la cola del día de series-días con stock todo el día. La elección fue R2 con κ = 0,25, el borde de la grilla (V1: WAPE por serie 32,4 % frente a 38,1 % de R1 y 34,0 % de R3; V2: 31,6 %, 37,5 % y 35,2 %, métodos ajustados con train). Lo que la simulación no valida: los quiebres reales llegan en días de más demanda y las series-días con stock todo el día no representan esa selección; por eso el aumento recuperado es una cota inferior del que esconden los quiebres, no una corrección exacta (D34).

![La comprobación de la recuperación](docs/figures/recovery_check.png)

![Un día de ejemplo: la venta observada y la demanda recuperada de las horas sin stock](docs/figures/example_day.png)

**El contrafactual de la misma serie, la misma hora y el mismo día del grupo** (ajuste proporcional iterativo, IPF, sobre los días `regular`), con el aumento como observado sobre contrafactual, en dos versiones (venta cruda y demanda recuperada) y con un intervalo del 95 % que remuestrea series y días enteros.

**El contrafactual** (`effect.py`). La venta esperada de una serie-día con promoción es `a(serie, hora) · b(grupo, día)`, con `a` y `b` ajustados por IPF solo sobre los días `regular` (30 iteraciones; el cambio máximo de `b` entre 30 y 60 iteraciones es de 10⁻¹⁴ sobre el entrenamiento, según `research/plan/p05`, y de 4,4·10⁻¹² sobre los 90 días, según la evaluación independiente). Una serie sin ningún día `regular` no tiene contrafactual y no entra en ningún efecto. El aumento es la suma observada sobre la suma del contrafactual menos 1, y no es causal.

**Los intervalos** (`bootstrap.py`). Remuestreo de dos vías, con pesos de series enteras y de días enteros (500 remuestras, semilla 0), con el contrafactual fijo. En las celdas con 30 series, el ancho mediano es 24,1 puntos con las dos vías y 14,2 con solo series; se pisan 183 de 903 pares de celdas (106 con solo series).

**El ranking de celdas** (7 grupos de gestión × 7 bandas de descuento, con al menos 30 series) en grupos indistinguibles: dos celdas cuyos intervalos se pisan no se presentan como distintas.

**El ranking** (`ranking.py`). Las celdas con al menos 30 series se ordenan por su aumento y se reparten en grupos indistinguibles: las celdas unidas por intervalos que se pisan, directamente o por una cadena de celdas, comparten grupo (los componentes conexos del grafo de solapes). Con los 90 días, 43 celdas quedan ordenadas en 3 grupos, de 1, 33 y 9 celdas; en la semana de prueba (recuperado), las 36 celdas son un solo grupo. El sello guarda 5 grupos en el lanzamiento y 2 en la prueba, de un recorrido que comparaba cada celda solo con el grupo abierto y separaba celdas que se pisan: la evaluación independiente lo encontró (B1), y los componentes se publican al lado del grupo sellado como análisis posterior al sello, sin reescribirlo (D45). El orden se repite en la prueba (C05) y el nivel no (C06).

![La cuenta ingenua frente al contrafactual](docs/figures/naive_vs_adjusted.png)

![El aumento por banda de descuento](docs/figures/band_lift.png)

Cada decisión, con su contexto, sus opciones, su motivo y su estado, está en el [registro de decisiones](docs/decisions.md).

#### 3.4.3 Protocolo de validación (partición en el tiempo y prueba sellada)

Corrida real del 2026-11-18 sobre los dos Parquet de FreshRetailNet-50K: el lanzamiento (`L2024-06-25`, corrida `20261118T082648095357Z`), siete entregas diarias y el cierre (`C2024-07-03`, corrida `20261118T083929959268Z`). El método de recuperación se ajustó con el entrenamiento (2024-03-28 a 2024-05-31), se eligió con V1 (06-08 a 06-16), V2 (06-17 a 06-25) quedó de vista previa, y todo se reajustó con los 90 días hasta 06-25; la semana de prueba, del 2024-06-26 al 2024-07-02, se evaluó una sola vez y quedó en el sello `reports/model_seal.json`, que no se reescribe. Los criterios se fijaron y se confirmaron en Git antes del primer código (`docs/requirements.md`, sección 8.1; `docs/decisions.md`, D16), junto con lo que se esperaba: que C06 y C09 probablemente no se cumplirían y que C01, C02, C04, C05, C07 y C08 sí.

### 3.5 Consumo y gobernanza

**La exportación para el sitio** (`outputs/site/`): cinco JSON que suman menos de 200 KB y un manifiesto con el tamaño y el SHA-256 de cada uno, escrito al final; un conjunto mezclado se rechaza. Las figuras de este README se dibujan solo desde esos archivos verificados con `python -m promolift figures`.

| Documento | Qué contiene |
| --- | --- |
| [docs/research.md](docs/research.md) | La investigación del conjunto: quiebres, promociones, confusión, fugas, las líneas base y una primera mirada del efecto, con las contradicciones con el sitio |
| [docs/requirements.md](docs/requirements.md) | Requerimientos, datos medidos y criterios de aceptación, con los criterios del modelo fijados antes de construir |
| [docs/plan.md](docs/plan.md) | Arquitectura, módulos, contratos y las 21 unidades de trabajo |
| [docs/decisions.md](docs/decisions.md) | Registro de decisiones, cada una con su contexto, opciones, decisión, motivo, lo que afecta, quién y estado |
| [docs/model-card.md](docs/model-card.md) | Ficha del modelo: uso, datos, estados del día, recuperación, contrafactual, intervalos, ranking, criterios, límites, tiempos y la suite |
| [docs/data-dictionary.md](docs/data-dictionary.md) | Diccionario de datos: los campos de origen con su uso, los estados del día y las bandas, y una tabla por Parquet generada desde el modelo semántico con `docs-sync` |
| [docs/runbook.md](docs/runbook.md) | Qué hacer cuando algo no sale como se esperaba: R1 a R12 (los Parquet, la lectura, las entregas, la trampa de fuga, el artefacto, el sello, el bloqueo, un análisis nuevo, Airflow, reconstruir desde cero, el cubo) |
| [docs/paso-a-paso.md](docs/paso-a-paso.md) | La cronología real del proyecto, commit por commit, desde el registro y `git log` |
| [docs/review-advisories.md](docs/review-advisories.md) | Las advertencias de las revisiones nativas, cada una con su ubicación y su estado |
| [docs/evaluation.md](docs/evaluation.md) | La evaluación independiente: las cifras recalculadas, los bloqueantes, las advertencias y lo que se corrigió |

La evaluación independiente se hizo (L85), sus bloqueantes y advertencias se corrigieron o se dejaron dichos con su motivo (L86), las correcciones se revisaron (L87) y una comprobación hecha por quien no las escribió rehízo los cuatro bloqueantes sobre el commit evaluado y el corregido y los encontró corregidos, sin bloqueantes nuevos (L88; [docs/evaluation.md](docs/evaluation.md), sección «Comprobación»). El requerimiento de tiempo de la corrida diaria (RNF02) se cumple después de su corrección: 42 a 44 s en la repetición del código corregido y de 41 a 46 s en la de la comprobación.

Advertencias abiertas: ninguna.

## 4. Producto final

### 4.1 Entregables operativos

**Un flujo diario y una línea de comandos.** `python -m promolift replay` corre el lanzamiento, las siete entregas y el cierre; `run` corre la siguiente entrega pendiente con las once tareas, y `task` una sola. El DAG de Airflow `promolift_daily` corre las mismas tareas en Docker, con todos los secretos del entorno y una inicialización que se detiene en su primer error.

**El diseño del tablero** (`dashboard/powerbi-design.html`): cinco páginas, las 21 medidas DAX, las tablas, las relaciones y la carga en Power Query, con vistas previas de los datos reales, para armarlo a mano en Power BI Desktop. **El `.pbix` todavía no está hecho**: lo arma quien tenga Power BI Desktop siguiendo el HTML.

![El ranking de celdas](docs/figures/cell_ranking.png)

![La réplica de las celdas](docs/figures/replication.png)

![El error de cada pronóstico](docs/figures/forecast_wape.png)

### 4.2 Lectura de resultados actuales

Cómo se lee, con las cifras de la semana de prueba (103.629 series-días con promoción):

| | Cruda | Recuperada |
| --- | --- | --- |
| Aumento total de la prueba | +46,5 % [41,0; 52,3] | +47,9 % [44,1; 51,2] |
| Aumento total sellado, con los 90 días | +52,0 % [49,7; 54,8] | +52,9 % [51,2; 54,9] |

## 5. Conclusión

### 5.1 Evaluación frente a criterios de éxito

**Salió como se esperaba salvo en C04**, que se esperaba cumplido y no se cumplió. Ningún criterio ni umbral se cambió.

- **C01 a C03 se cumplen: la recuperación es mejor que la media simple y casi no tiene sesgo.** C01: WAPE por serie 31,1 % frente a 35,6 % de R1; la diferencia va de −4,69 a −4,25 puntos. C02: sesgo de −0,2 % (se pedía a lo sumo 10 %). C03: el sesgo de la recuperación en días con promoción frente al de los días regulares mueve el aumento 3,8 % (se pedía a lo sumo 5 %). Estas cifras son de la máscara de cola de la prueba y el método se ajustó con los 90 días hasta 06-25 (`train+purge+valid_v1+valid_v2`).
- **C04 no se cumple, y se esperaba que sí.** En la prueba, la diferencia entre el aumento recuperado y el crudo es de +1,37 puntos y va de −1,81 a +4,36: la parte del efecto que los quiebres esconden no se distingue de 0. La frase sellada dice «no esconden»; el intervalo contiene el 0, y eso no prueba que no escondan nada (A1 de la evaluación, D50). En la planificación se había medido +4,20 puntos sobre el entrenamiento ([+2,73; +5,76], con otra ventana de ajuste) y con los 90 días del lanzamiento la diferencia es de +0,9 puntos. El resultado es el que salió: recuperar la demanda no cambió el aumento de forma detectable en esta semana.
- **C05 y C07 se cumplen: el orden se repite.** C05: correlación de Spearman 0,897 entre el aumento sellado y el de la prueba sobre 36 celdas, y se pedía 0,80. C07: 1,000 entre la profundidad de la banda y su aumento en la prueba, y se pedía 0,90. Las bandas selladas van de +100,2 % (más del 50 %) y +139,6 % (40 a 50 %) a +13,3 % (hasta el 5 %), recuperadas.
- **C06 no se cumple (esperado): el tamaño de cada aumento no se repite.** El intervalo de la diferencia prueba − sellado contiene 0 en el 58,3 % de 36 celdas (21 de 36), y se pedía el 80 %. El intervalo de dos vías (series y días) es 1,70 veces más ancho que el de solo series y aun así no alcanza: el nivel del aumento de una celda es una descripción del período, no una promesa para la semana siguiente. Además, el nivel depende de la ventana con que se ajusta el contrafactual: sobre las mismas series-días el aumento crudo es +56,52 % con el ajuste del entrenamiento y +47,86 % con el de los 90 días (D09).
- **C08 se cumple y C09 no supera: el aumento de la celda agrega información, pero no gana a la regla ingenua.** C08: WAPE de F2 40,3 % frente a 43,9 % de F2a, un solo aumento total; la diferencia va de −4,07 a −3,19 puntos. C09: WAPE de F2 40,3 % frente a 35,0 % de F1, la media de los 7 días anteriores de la serie; la diferencia va de +1,92 a +8,32 puntos. El pronóstico no es el producto (D15): solo mide si el aumento agrega información.
- **C10 es informativo:** 257 cifras de variantes y el seguimiento de los 7 días de la prueba, de +40,8 % a +55,4 % recuperado por día.
- **RNF02 se cumple después de su corrección.** En la corrida real (U19) la repetición completa tardó 876 s, el lanzamiento 310 s y el cierre 120 s, pero las siete corridas diarias tardaron de 62 a 68 s contra un límite de 60 s: la carga (unos 25 s) y la exportación (unos 32 s) reconstruían entera la preparación de las series-días en cada entrega. La corrección (`8ef2a3e`, D46) la extiende con los días nuevos; una repetición real del código corregido sobre una copia de los datos, fuera del repositorio, dio corridas diarias de 42 a 44 s (la carga de 14,9 a 16,3 s y la exportación de 21,1 a 22,3 s), el lanzamiento en 310 s, el cierre en 97 s y la repetición completa en 717 s de reloj, con el sello igual byte a byte, y `tests/e2e/test_real.py::test_every_daily_run_takes_at_most_the_required_seconds` pasó. Lo sellado no se reconstruyó: el `data/` del proyecto no se tocó.
- **Memoria** (RNF03): el pico de la repetición completa fue de 4.077,9 MB de `PeakWorkingSetSize` en la corrida real y de 4.112,6 MB de `PeakWorkingSetSize` en la repetición del código corregido (el límite es 12 GB de ese contador); `PeakPagefileUsage`, informativo, 5.808,7 MB y 5.841,2 MB.

| Método | Uso | WAPE en la prueba | Criterio |
| --- | --- | ---: | --- |
| R2 con κ = 0,25 | Recuperación elegida (WAPE por serie de la masa oculta) | 31,1 % | C01: supera a R1 |
| R1 (la media simple) | Línea base de la recuperación | 35,6 % | |
| F2 (el aumento de la celda) | Pronóstico con el aumento de cada celda | 40,3 % | C08: mejora a F2a; C09: no supera a F1 |
| F2a (un solo aumento total) | Línea base del pronóstico | 43,9 % | |
| F1 (la media de los 7 días anteriores de la serie) | Regla ingenua | 35,0 % | |

### 5.2 Limitaciones metodológicas

- **Un efecto descriptivo, no causal**: todo aumento es una asociación dentro de la serie, ajustada por la hora y el día del grupo; no dice si la promoción se lanzó porque se esperaba más demanda.

Lo que no sirve: leer un aumento como causal, prometer el aumento de una promoción futura, hablar de ingreso o margen (no hay precio y la venta está normalizada), identificar una promoción individual (la unidad es la celda), ni generalizar más allá de 18 ciudades de un país y 97 días de un solo operador.

### 5.3 Trabajo futuro

- **Lo que no se hizo todavía.** El `.pbix`: lo arma quien tenga Power BI Desktop siguiendo el diseño en HTML, y las 21 medidas DAX todavía no se ejecutaron en Power BI.
- **Más semanas de prueba.** El nivel de cada celda (C06) se midió en una sola semana; repetir la réplica en otras semanas separaría lo que es de la semana de lo que es del método.

## Resultados completos de la corrida

El bloque siguiente lo copia `docs-sync` desde `reports/evaluation_summary.md`, que escribe el propio flujo desde el sello: no se escribe a mano. Trae cada criterio con su umbral, la cifra que el umbral compara, si se cumple y su veredicto tal como quedó sellado, y la tabla de la recuperación en V2 con los métodos ajustados con el entrenamiento. Su lectura, criterio por criterio, está en [5.1](#51-evaluación-frente-a-criterios-de-éxito): seis de los nueve criterios con umbral se cumplen, y C04, C06 y C09 no.

<!-- results:start -->
## Resultados

Criterios fijados antes de construir, evaluados una vez sobre la prueba.

| Criterio | Umbral | Lo que prueba el umbral | Cumple | Veredicto |
| --- | --- | ---: | --- | --- |
| C01 La recuperación supera a la media simple | límite superior del intervalo del 95 % de WAPE por serie (recuperación) − WAPE por serie (R1) < 0, en la máscara de cola de la prueba | −4,25 puntos | sí | La recuperación (R2 con κ = 0,25) supera a la media simple (R1) en la máscara de cola de la prueba: WAPE por serie 31,1 % frente a 35,6 %; la diferencia va de −4,69 a −4,25 puntos. |
| C02 La masa recuperada no tiene sesgo grande | \|sesgo de la recuperación\| ≤ 0,10 en la máscara de cola de la prueba | −0,002 | sí | El sesgo de la masa recuperada cumple: la recuperación estima 0,2 % de menos y se pedía a lo sumo 10,0 %. |
| C03 La recuperación no cambia el aumento | \|(1 + sesgo en días con promoción) / (1 + sesgo en días regulares) − 1\| ≤ 0,05 en la máscara de cola de la prueba | −0,038 | sí | La recuperación no cambia el aumento: el sesgo en días con promoción frente al de los días regulares lo mueve 3,8 %, y se pedía a lo sumo 5,0 %. |
| C04 Los quiebres esconden parte del efecto | límite inferior del intervalo del 95 % del aumento total recuperado − el crudo, en la prueba, > 0 | −1,81 puntos | no | Los quiebres no esconden parte del efecto: el aumento total con la demanda recuperada es 47,9 % frente a 46,5 % con la venta cruda; la diferencia va de −1,81 a 4,36 puntos. |
| C05 El orden de las celdas se repite | correlación de Spearman entre los aumentos sellados y los de la prueba, en las celdas con series suficientes en las dos, ≥ 0,80 | 0,897 | sí | El orden de las celdas se repite en la semana de prueba: correlación de Spearman 0,897 entre el aumento sellado y el de la prueba, sobre 36 celdas, y se pedía al menos 0,80. |
| C06 El nivel de cada celda se repite | proporción de esas celdas cuyo intervalo de la diferencia prueba − sellado contiene 0 ≥ 0,80 | 0,583 | no | El nivel de cada celda no se repite: el intervalo de la diferencia prueba − sellado contiene 0 en el 58,3 % de 36 celdas, y se pedía al menos 80,0 %. |
| C07 Más descuento, más aumento | correlación de Spearman entre la profundidad de la banda y su aumento en la prueba ≥ 0,90 | 1,000 | sí | Más descuento, más aumento: correlación de Spearman 1,000 entre la profundidad de la banda y su aumento en la prueba, y se pedía al menos 0,90. |
| C08 El aumento de la celda mejora el pronóstico | límite superior del intervalo del 95 % de WAPE(F2) − WAPE(F2a) < 0, en las series-días con promoción de la prueba | −3,19 puntos | sí | El aumento de la celda mejora el pronóstico frente a un aumento único (F2a): WAPE de F2 40,3 % frente a 43,9 % de F2a; la diferencia va de −4,07 a −3,19 puntos. |
| C09 El pronóstico con el aumento supera a la regla ingenua | límite superior del intervalo del 95 % de WAPE(F2) − WAPE(F1) < 0, en las mismas series-días | 8,32 puntos | no | El pronóstico con el aumento de la celda no supera a la regla ingenua (F1), la media de los días anteriores de la propia serie: WAPE de F2 40,3 % frente a 35,0 % de F1; la diferencia va de 1,92 a 8,32 puntos. |
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

Estado: sealed. Corrida 20261118T104140428720Z del 2024-07-03 00:00:00.
<!-- results:end -->

## Cómo correrlo de punta a punta

Requisitos: Windows 10 u 11 (o Linux), Python 3.11 y, solo para Airflow, Docker Desktop con al menos 12 GB. No se usa el Python global: el proyecto trae su propio entorno. El paquete no se instala: los comandos lo encuentran con `PYTHONPATH` en `src`, como hacen las pruebas y el compose.

```powershell
cd 06-Ecommerce-Promotion-Lift
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
$env:PYTHONPATH = "src"
```

**1. Los Parquet.** El flujo no los descarga. Se bajan con el script de la investigación, que los fija al commit del conjunto y comprueba tamaño y SHA-256, y quedan en `data\raw\` (que no se versiona):

```powershell
.venv\Scripts\python research\s00_download.py
```

`train.parquet` debe pesar 106.436.287 bytes y `eval.parquet` 8.440.124; las dos huellas están en «Fuente y licencia». Si falta uno o no coincide, la tarea `fetch_source` termina con salida 3 y no escribe más que el informe de validación y el estado de la corrida (runbook R1).

**2. Pruebas** (sin las que necesitan los Parquet reales ni Docker). La suite por defecto recoge 884 pruebas y termina en menos de 180 s en el equipo de desarrollo (ver la ficha del modelo, que dice en qué commit se midieron los tiempos):

```powershell
.venv\Scripts\python -m pytest
```

**3. Modo rápido**, sobre datos sintéticos. Todo lo que lee y escribe queda en `data\quick\` (no se versiona): no toca el almacén, los Parquet, el HTML, los reportes ni el sello de la corrida real.

```powershell
.venv\Scripts\python -m promolift make-fixture data\quick
.venv\Scripts\python -m promolift replay --config config\pipeline.quick.toml
```

**4. Corrida real**, con los Parquet ya en su lugar. `replay` corre el lanzamiento, las siete entregas diarias y el cierre; `run` corre la siguiente entrega pendiente con las once tareas en orden, y `task` una sola tarea de una corrida:

```powershell
.venv\Scripts\python -m promolift replay
.venv\Scripts\python -m promolift run
.venv\Scripts\python -m pytest -m real_data      # pruebas con los Parquet reales, sobre lo que dejó la repetición
```

**5. Figuras de la documentación y bloque de resultados del README** (`docs-sync` copia el resumen en el README y escribe, desde el modelo semántico, la tabla de cada Parquet en `docs/data-dictionary.md`; un segundo uso no cambia nada):

```powershell
.venv\Scripts\python -m promolift figures
.venv\Scripts\python -m promolift docs-sync
```

Todos los comandos aceptan `--config RUTA` y `-v`; salen con 0, 1 (una tarea falló), 2 (uso, configuración, una corrida cerrada o un bloqueo tomado) o 3 (la fuente o la entrega rechazadas). La corrida real ya se hizo y su sello está versionado: repetirla reescribe las salidas versionadas con sus propias claves de corrida, y con otra configuración el resultado se guarda aparte, como posterior al sello, y no reemplaza el sellado. Para repetirla sin tocar lo versionado, usar el modo rápido.

Medido en el equipo de desarrollo y en un solo proceso (D29, D39, D46). En la corrida real (U19): la repetición completa tardó 876 s (14,6 min contra 20); el lanzamiento 310 s (contra 12 min); las siete corridas diarias de 62 a 68 s contra un límite de 60 s (no se cumplía); el cierre 120 s; la corrida sin entrega 1 s; el pico de memoria, 4.077,9 MB de `PeakWorkingSetSize` (el límite es 12 GB de ese contador) y 5.808,7 MB de `PeakPagefileUsage` (informativo). En la repetición del código corregido sobre una copia: 717 s de reloj; el lanzamiento 310 s; las siete corridas diarias de 42 a 44 s (**se cumple**); el cierre 97 s; la corrida sin entrega 1 s; 4.112,6 MB de `PeakWorkingSetSize` y 5.841,2 MB de `PeakPagefileUsage`. La comprobación (L88) repitió la corrida del código corregido en `38a6c56`: 723 s de reloj; el lanzamiento 318 s; las siete corridas diarias de 41 a 46 s; el cierre 93 s; la corrida sin entrega 1 s; y 4.084,2 MB de `PeakWorkingSetSize` y 5.802,8 MB de `PeakPagefileUsage`.

## Paso a paso

El proyecto se construyó en 21 unidades de trabajo, cada una con sus pruebas y su commit: la investigación y el plan, el entorno y las dependencias, la configuración y la clasificación de claves, el accesorio sintético, la lectura de los Parquet, las entregas y la validación, el almacén, las máscaras y la recuperación, el contrafactual y el remuestreo, el lanzamiento y el sello, la corrida diaria, la evaluación, el modelo estrella, el diseño del tablero, la exportación para el sitio, el bloqueo, las tareas, la línea de comandos, Airflow y Docker, la corrida real y la documentación. [docs/paso-a-paso.md](docs/paso-a-paso.md) cuenta la cronología real, con el commit de cada paso, desde el registro de seguimiento y `git log`.

Lo que consta en el registro del documento de seguimiento (L70 a L88) y en `git log`:

- **Datos e investigación** (L70, L71). FreshRetailNet-50K se bajó con un script fijado al commit del conjunto y se comprobaron sus dos huellas; se perfilaron quiebres, promociones, confusión y fugas, se midieron las líneas base y una primera mirada del efecto (+11,1 % crudo, +38,6 % recuperado), sin calcular nada sobre la semana de prueba. Se encontraron nueve contradicciones con lo que dice el sitio y doce preguntas abiertas.
- **Requerimientos y plan** (L72). Parte de la medición se repitió **leyendo solo `train.parquet`**: a nivel de la hora ningún método de recuperación supera a predecir cero, los quiebres son colas del día, el día de control mueve el efecto más que los quiebres, el orden de las celdas se repite en la validación pero su nivel no y el aumento de la celda no gana a la última semana de la serie. Se fijaron C01-C10 con lo esperable, 40 decisiones (hoy el registro tiene 50) y 21 unidades de trabajo, y todo se confirmó en Git (`ed6d6c4`) antes de la primera línea de código.
- **Programación** (L73, L75, L77, L79, L81). U01 a U19, de a una a cuatro unidades por sesión, cada una con su prueba primero y su commit. Cada unidad vio su prueba fallar antes de escribir el código, y se probaron mutaciones de las reglas de negocio (el registro cuenta cuáles sobrevivieron y por qué).
- **Revisión** (L74, L76, L78, L80, L82, L84, L87). Las revisiones de código aprobaron todo lo que revisaron, con 33 hallazgos entre sugerencias, advertencias y uno marcado crítico (24 hasta L84 y 9 en L87), que `docs/review-advisories.md` lista con su ubicación y su estado, junto con la advertencia N1 de la comprobación. U19 no se pudo revisar: superó el presupuesto de la revisión (9.002 líneas, casi todas salidas generadas), y la evaluación independiente recalculó esas salidas (L82, L85); tampoco las salidas versionadas que regeneró la repetición del código corregido (`a5f6ebd..6843245`, L87), que reprodujo la repetición real de la comprobación (L88).
- **Una decisión del dueño** (L79). La suite rápida pasó el límite de 120 s (tardó 125 s). Entre fijar `pytest-xdist`, subir el límite o sacar de la suite por defecto las pruebas del flujo, el dueño eligió subir el límite: pasó a 180 s con un presupuesto de trabajo de 150 s (`4e73cdd`, D29).
- **La corrida real** (L81, `6253c31`). Una sola vez: `replay` sobre los dos Parquet reales, la evaluación de la prueba bajo el sello y la corrida sin entrega, con los tiempos y la memoria medidos. Seis de nueve criterios se cumplen, C06 y C09 no, como se esperaba, y C04 no, contra lo esperado. Una prueba de tiempo quedó en rojo a propósito (RNF02). Antes se corrigió una advertencia de una revisión (`f553c1e`).
- **La documentación** (L83). El README, la ficha del modelo, el diccionario, el runbook, el paso a paso y las advertencias se escribieron con la prueba primero (`tests/docs/test_docs.py`). Las cifras salen de los archivos sellados y del resumen, y una prueba las compara a los decimales que el documento escribe.
- **La evaluación independiente** (L85). Hecha por fuera de la construcción del proyecto, recalculó cada cifra con su propio lector de los Parquet (todas exactas, a 10⁻⁹ o mejor), repitió la corrida real en un clon y sondeó cada clase de defecto. Encontró cuatro bloqueantes: los grupos indistinguibles separaban celdas que se pisan (B1), una clave de la configuración se ignoraba (B2), esta documentación no contaba L82 (B3) y la corrida diaria pasaba de 60 s (B4).
- **Las correcciones** (L86). Se escribieron con la prueba primero, cada corrección de riesgo alto en su propio commit (`9c6e964`, `6eb7c68`, `8ef2a3e`, `75456e7`); la corrida real se repitió sobre una copia de los datos fuera del repositorio con el sello igual byte a byte, se versionaron las salidas que cambian por diseño (`6843245`) y se sincronizó esta documentación (D45 a D50).
- **La comprobación** (L88). Hecha por quien no escribió las correcciones, rehízo los cuatro bloqueantes en dos clones (`b15055c` y `38a6c56`): los cuatro están corregidos, ninguno es nuevo, el diferencial de 20 casos de la línea de comandos difiere solo donde se pidió y una repetición real reprodujo cada salida versionada, el sello y las figuras. Dejó una advertencia de documentación (N1, la cuenta de hallazgos de D49), que se corrigió en la sincronización final.
- **Lo que no se hizo todavía.** El `.pbix`.

## Fuente y licencia

Fuente de datos: Dingdong-Inc, FreshRetailNet-50K, Hugging Face, CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/), commit `c374e859`; Wang et al. (2026), arXiv:2505.16319. Copia usada: los dos Parquet del commit fijado, `train.parquet` (106.436.287 bytes, SHA-256 `6706832db892bbae4969c19d87e07975d2543d2ba7d7d4756360654785de5a3d`) y `eval.parquet` (8.440.124 bytes, SHA-256 `1b118840664280c6b88bffc84c80ee1f54c05d911e354b7599e5da10995e960e`).

Los datos crudos no se versionan: el flujo no descarga nada y exige que cada archivo tenga el tamaño y la huella fijados. El conjunto no trae datos personales: las tiendas y los productos son identificadores numéricos. La cifra de 1,43 veces de mediana por serie que da el artículo usa otra definición que este proyecto (cociente de sumas) y no se compara con la propia (D37); la medida con la definición del artículo sobre el entrenamiento fue de 1,38.
