# Evaluación final independiente

Qué se evaluó, quién lo evaluó, qué encontró y cómo se resolvió cada hallazgo. Es el control que el proyecto dejó para el final (plan, sección 28): lo hizo un agente que no escribió el código, sobre una copia aparte del commit `b15055c` (el código de `8585877`, U21; `b15055c` solo agrega L83), y sus cuatro bloqueantes y sus nueve advertencias se corrigieron o se dejaron dichos después; otro agente comprobó los cuatro bloqueantes sobre el commit evaluado y el corregido (L88, la sección «Comprobación»). Lo que dice este documento de quién hizo qué, con qué modelo, con qué commit y con qué cifras es lo que consta en el registro del documento de seguimiento (`odd/tasks/portfolio-projects.md`, L85 a L88) y en `git log`; el detalle de cada sonda es el del informe del evaluador, que el orquestador transcribió porque la herramienta del evaluador no pudo escribir el archivo (L85), copiado aquí con las rutas del equipo quitadas. Está al día con el registro hasta L88: las correcciones son las de L86 (el último commit de código es `8b73512`; `a5f6ebd` agrega pruebas de documentación y `6843245` versiona las salidas de la repetición del código corregido), la comprobación es la de L88 y esta sincronización no cambia código ni salidas versionadas.

## Quién evaluó y cómo

Un agente de Claude Code con el modelo Opus, **distinto de los agentes que construyeron el proyecto** y sin su contexto de trabajo, en solo lectura sobre el repositorio. Clonó el repositorio con `git clone --no-hardlinks` en una carpeta temporal, se paró en `b15055c`, armó su propio entorno (Python 3.11.1, `pip install -r requirements-dev.txt`) y copió `data/raw/train.parquet` y `eval.parquet`; el `data/` original no se tocó. Las sondas que escriben corrieron en copias propias (`git archive b15055c`), en modo rápido.

Recalculó las cifras con un **lector independiente** que lee los Parquet con pyarrow y no importa `promolift`: los estados del día y las bandas (D03, D04, D13), R1 y R2 (RF09), el IPF (D09), los aumentos (D10), el remuestreo de dos vías (D12, D41), los grupos indistinguibles (los componentes conexos del grafo de solapes, como dice RF15, y la cadena del código para comparar), la réplica, los pronósticos F0, F1, F2a y F2 (D15) y las máscaras de cola de V1, V2 y la prueba, con las semillas documentadas para comparar límites exactos, y C01 a C03 también con otra semilla. No recalculó R3 ni C10, y no corrió el runbook paso a paso.

## Veredicto

El núcleo numérico es correcto: cada cifra recalculada del resumen, el sello y la ficha coincide con el lector independiente a 10⁻⁹ o mejor; la repetición real del evaluador reprodujo el contenido de los 25 Parquet y los seis JSON (sin las columnas de corrida), el artefacto y el sello (`seal unchanged`); los rechazos de la línea de comandos, el sello, el bloqueo y el manejador de fallas se comportan como dicen. Hubo cuatro bloqueantes (B1 a B4). C04, C06 y C09 no se cumplen tal como se informó y no son bloqueantes.

## Especificaciones y criterios de aceptación

S1-S5, S7, S8 y S11 se cumplen; S9 en parte (las diferencias con el sitio están en `SITE-UPDATES.md`, sin aplicar, y las filas del ranking heredaban B1); S10 y S12 estaban en curso (faltaban este documento y la página del sitio; hoy falta solo la página del sitio); S6 no aplica. De AC01 a AC38, todos se cumplen salvo **AC17** (B1), **AC34** (B4) y **AC37** (B3); AC18 se cumple con B2 y AC22 con las advertencias A1, A2 y A5.

## Las cifras recalculadas

Todas exactas:

| Criterio | Declarado | Recalculado | Veredicto |
| --- | --- | --- | --- |
| C01 | 31,1 % frente a 35,6 %; −4,69 a −4,25 puntos | 0,3112276 y 0,3559090; −4,694 a −4,245 | Cumple |
| C02 | −0,2 % | −0,00201 | Cumple |
| C03 | −3,8 % | −0,038415 | Cumple |
| C04 | +1,37 puntos; −1,81 a +4,36 | +1,3723; −1,808 a +4,359 | No cumple |
| C05 | 0,897 sobre 36 celdas | 0,8973 sobre 36 | Cumple |
| C06 | 58,3 % (21 de 36) | 0,5833 (21) | No cumple |
| C07 | 1,000 | 1,000 | Cumple |
| C08 | 40,3 % frente a 43,9 %; −4,07 a −3,19 puntos | 0,402632 y 0,438928; −4,068 a −3,188 | Cumple |
| C09 | 40,3 % frente a 35,0 %; +1,92 a +8,32 puntos | 0,402632 y 0,350497; +1,918 a +8,323 | No cumple |
| C10 | informativo | no se recalculó | — |

Con otra semilla de máscara, C01 da 31,4 % frente a 35,8 %, C02 −0,47 % y C03 −4,74 %: los veredictos se mantienen. También coinciden el lanzamiento (+51,976 % crudo y +52,873 % recuperado, sobre 39.661 series y 1.529.251 series-días), las siete bandas con sus intervalos, la cuenta ingenua (+20,64 % cruda y +18,70 % recuperada), la semana de prueba (+46,485 % crudo y +47,857 % recuperado) con sus siete aumentos diarios, los pronósticos (F0 44,88 %, F1 35,05 %, F2a 43,89 %, F2 40,26 %), V1 y V2, la réplica (0,9336 sobre 40 celdas, 55,0 % consistentes), las 43 de 47 celdas ordenadas y los 183 de 903 pares que se pisan (106 con solo series). Lo que **no** coincidía con RF15 eran los grupos (B1).

## Las corridas

En el clon del evaluador, una repetición real en reposo: 867 s de reloj; el lanzamiento 307 s; las siete corridas diarias 61, 62, 62, 62, 63, 64 y 65 s (la carga de 24,7 a 26,0 s y la exportación de 30,9 a 32,6 s); el cierre 111 s; la corrida sin entrega 1 s; un pico de 4.093,0 MB de `PeakWorkingSetSize`. El modo rápido completo tardó 20,8 s, `pytest -m docker` 88,7 s (2 pasaron) y la suite rápida 139,11 s y 131,30 s.

## Los bloqueantes

Las ubicaciones son las de `b15055c`. Cada hallazgo termina con su **Estado**.

### B1. Los grupos indistinguibles separaban celdas que se pisan (RF15, D13, AC17)

- **Qué pasaba.** `ranking.rank_cells` comparaba una celda solo con el grupo abierto, así que una celda que pisa a otra de un grupo ya cerrado caía en otro grupo. En el lanzamiento, `g0-b1` [6,098; 8,073] quedaba en el grupo 2 y `g5-b0` [2,786; 6,214] en el 3, y `g6-b4` (grupo 4) se pisa con `g1-b6`, `g3-b6` y `g4-b5` (grupo 5); con la regla escrita (los componentes conexos del grafo de solapes) hay 3 grupos, no 5. En la semana de prueba (recuperado), `g0-b1`, `g0-b2` y `g0-b3` (grupo 1) se pisan con `g0-b6` (grupo 2): hay 1 grupo, no 2. Se publicaba en el README, la ficha, D09, `fact_cell_effect`, `algorithms.json`, `operation.json`, el tablero y las filas del sitio.
- **Reproducción.** Sobre `reports/model_seal.json`, los pares de celdas ordenadas del lanzamiento que se pisan y tienen `tier` distinto: debía dar ninguno y daba cuatro.
- **Estado: corregida en `9c6e964` como análisis posterior al sello (D45).** Los grupos sellados cambian un valor sellado, así que no se reescribieron: el sello guarda su `tier` como estaba. `ranking.overlap_groups` da los componentes conexos sobre los intervalos sellados, y `fact_cell_effect.overlap_group`, `algorithms.json`, `summary.json`, `operation.json`, el tablero y la figura del ranking los publican al lado del grupo sellado, con su control propio. Impacto medido: en el lanzamiento, 5 grupos sellados (de 1, 1, 32, 1 y 8 celdas) son 3 componentes (de 1, 33 y 9); en la prueba recuperada, 2 grupos (de 4 y 32) son 1 (de 36); en la prueba cruda, 1 y 1. Los aumentos, los intervalos, el orden, los pares que se pisan y los diez criterios no cambian. La prueba que reproduce el hallazgo con un caso a mano se vio fallar antes del cambio.

### B2. `[effect] versions` se aceptaba, entraba en la huella y se ignoraba

- **Qué pasaba.** Ningún módulo leía la clave. Con `versions = ["raw"]`, `replay` terminaba con 0, calculaba las dos versiones y evaluaba C04.
- **Estado: corregida en `6eb7c68` (D47).** Cualquier valor que no sea exactamente `["raw", "recovered"]` es un error de configuración que nombra la clave: la línea de comandos sale con 2 antes de escribir nada. El valor sellado no cambia, ni `config_sha256`.

### B3. La documentación de U20 y U21 no reflejaba L82 (RNF14, AC37)

- **Qué pasaba.** L82 estaba confirmada antes de `4ad3f14` y `8585877`, y aun así `review-advisories.md` decía «20 en total» y que la revisión de U19 «todavía no consta», le faltaba el hallazgo de L82 (`NOT_FILTERED_MARK`); `paso-a-paso.md` ponía la revisión de U19 como pendiente; el README decía «20 hallazgos» y «40 decisiones (hoy son 41)», cuando eran 43 al escribirlo y 44 en `8585877`; D44 decía que el registro llegaba a L81.
- **Estado: corregida en la documentación de las correcciones (D50).** Las advertencias, el paso a paso y el README cuentan L82 (U19 no se pudo revisar, por el presupuesto de contexto) y L84, y los 24 hallazgos con su estado; el número de decisiones es el del registro de decisiones; D44 tiene una nota fechada; `tests/docs/test_docs.py::test_open_advisories_match_review_file` exige que no quede «20 en total» ni «todavía no consta».

### B4. RNF02 y AC34: la corrida diaria tardaba de 61 a 65 s contra 60 s

- **Qué pasaba.** Ya dicho en L81: la carga y la exportación sumaban de 56 a 58 s por corrida, porque cada una reconstruía entera la preparación de las series-días.
- **Estado: corregida en `8ef2a3e` (D46).** La preparación se extiende con los días que cerraron en lugar de reconstruirse dos veces por entrega, con un registro de lo que la armó y disparadores que lo borran ante cualquier cambio que el flujo no hace. Medido con una repetición real del código corregido (`8b73512`) en una copia del proyecto hecha con `git archive` en una carpeta temporal fuera de todo repositorio, con los dos Parquet copiados, en reposo: el lanzamiento 310 s, las siete corridas diarias 42, 42, 42, 43, 43, 43 y 44 s (la carga de 14,9 a 16,3 s y la exportación de 21,1 a 22,3 s), el cierre 97 s, la corrida sin entrega 1 s y la repetición completa 717 s de reloj; el pico fue de 4.112,6 MB de `PeakWorkingSetSize` y 5.841,2 MB de `PeakPagefileUsage`. `pytest -m real_data` sobre lo que dejó: 8 pasaron, la prueba del tiempo diario incluida. El `data/` del proyecto no se tocó.

## Las advertencias

- **A1.** El veredicto de C04 («Los quiebres no esconden parte del efecto») afirma una ausencia a partir de un intervalo que contiene el 0. **Estado: dejada con evidencia en el veredicto y corregida en la documentación (D50).** La frase es parte del sello (`criteria_from_seal` reconstruye cada criterio, frase incluida, y exige que sea la sellada), así que no se cambia; el README y la ficha dicen junto a ella que la diferencia no se distingue de 0 y que eso no prueba que los quiebres no escondan nada.
- **A2.** La columna «Valor» del resumen no es lo que el umbral prueba (C08 y C09 mostraban el mismo 0,403 con veredictos opuestos). **Estado: corregida en `8b73512` (D49):** la columna se llama «Lo que prueba el umbral» y muestra el límite de la diferencia en puntos para C01, C04, C08 y C09; el `value` sellado no cambia.
- **A3.** El «10⁻¹⁴» de convergencia del IPF del README es de `p05` sobre el entrenamiento; sobre los 90 días el evaluador midió 4,4·10⁻¹². **Estado: corregida en la documentación (D50):** el README cita el origen de cada cifra.
- **A4.** El «14,7 % empieza a las 6 h» es del entrenamiento (la distribución de la primera hora sin stock que sella el lanzamiento) y las cifras vecinas son de los 90 días. **Estado: corregida en la documentación (D50):** el README rotula el bloque.
- **A5.** `fact_overall_effect` y `fact_band_effect` no tenían `fit_blocks`. **Estado: corregida en `8b73512` (D49).**
- **A6.** Un rechazo en una copia nueva dejaba vacía `data/quick/interim/`. **Estado: corregida en `75456e7` (D48).**
- **A7.** La suite tardó 139,1 s y 131,3 s, contra los 125 s de la ficha. **Estado: remedida** con el código de `38a6c56`, el último commit de la carpeta antes de la sincronización final (883 pruebas recogidas; 133,58 s y 135,07 s, dos corridas en reposo del agente de las correcciones en `95f57f7`, que difiere de `38a6c56` solo en documentos; y 132,98 s y 130,73 s en las dos de la comprobación, en `38a6c56`; dentro del límite de 180 s y del presupuesto de 150 s). La sincronización final agrega una prueba de documentación, que cuesta milisegundos: la suite recoge 884 pruebas y los tiempos son los medidos con 883.
- **A8.** Dos pruebas versionaban el nombre del usuario; la docstring de `test_real.py` decía «two tests» y son tres; el total de tiempo sumaba duraciones. **Estado: corregida en `8b73512` (D49).**
- **A9.** `source.dataset_commit` entra en la huella y solo se valida su formato. **Estado: dejada con evidencia (D47):** lo que fija el contenido de los Parquet son sus bytes y su SHA-256, que `fetch_source` comprueba en cada corrida.

Las 19 advertencias abiertas de las revisiones y la de L82 se reprodujeron todas; solo U17/S1 (la ayuda) era un defecto. Su estado después de las correcciones, y el de los tres hallazgos de L84, está en [review-advisories.md](review-advisories.md). El hallazgo crítico de L84 sobre `docs_sync.py` no se reprodujo: la fila separadora tiene cuatro celdas.

## Las correcciones

Las escribió un agente con Opus (plan, sección 28, ítem 2), cada una con la prueba primero: la prueba nueva se vio fallar antes de su corrección, salvo los cambios de nombre y de limpieza, que no tienen una prueba que pueda fallar antes.

- `9c6e964` **B1** (ítem 1, sola; D45).
- `6eb7c68` **B2** (ítem 3, sola; D47).
- `8ef2a3e` **B4** (ítem 1, sola; D46).
- `75456e7` **A6** (ítem 4, sola; D48).
- `8b73512` **A2, A5, A8 y las advertencias de las revisiones que tocan el código** (D49).
- `a5f6ebd` Las pruebas de las tablas de la ficha y de la forma de todas las tablas.
- `6843245` **Las salidas versionadas de la repetición del código corregido** (ver abajo).
- **B3, A1, A3, A4, A7 y esta documentación** (D50), en los commits `95f57f7` y `38a6c56`.
- **La comprobación** (L88) no encontró ningún bloqueante nuevo y dejó una advertencia, N1 (D49 decía «veintitrés hallazgos» y son 24), y la sincronización final (plan, sección 28, ítem 4) la corrige con una nota fechada, escribe la sección «Comprobación», pone este documento entre los que comprueban las pruebas de la documentación y deja el paso a paso, las advertencias, el README, la ficha y las filas de `SITE-UPDATES.md` diciendo lo que consta en L86 a L88. No cambia código y las salidas versionadas son las que la repetición de la comprobación reprodujo (L88).

**Lo que cambió en las salidas versionadas, y lo que no.** La repetición del código corregido dejó `reports/model_seal.json` igual byte a byte (SHA-256 `060428fe…6a6a` antes y después) y el artefacto del modelo igual. Comparado con lo confirmado, sin las claves de corrida, las fechas y las celdas de memoria, el contenido de 22 de los 25 Parquet es el mismo, y en los otros tres solo se agregan columnas: `overlap_group` en `fact_cell_effect` (B1), `fit_blocks` en `fact_band_effect` y `fact_overall_effect` (A5), con las demás columnas iguales; `data.json`, `validation_rules.json`, `reports/evaluation_summary.json` y el informe de validación son iguales; `algorithms.json`, `summary.json` y `operation.json` solo agregan `overlap_group`, `headline.overlap_groups` y `overlap_groups_now`; `reports/evaluation_summary.md` cambia la columna «Lo que prueba el umbral» (A2); el diseño del tablero cambia la medida y la tarjeta de los grupos indistinguibles, el número de grupo y el color de 41 celdas del gráfico de intervalos y el número de columnas de las tres tablas que ganaron una; de las nueve figuras, solo `cell_ranking.png` cambia.

**El diferencial de la línea de comandos** contra `b15055c`, en el modo rápido, cada caso en una copia nueva de cada commit (14 casos: las ayudas, los rechazos de AC28 y AC30, `make-fixture`, y tres repeticiones), difiere solo donde se pidió: la ayuda de `make-fixture` (U17/S1), `replay` con `[effect] versions = ["raw"]` (antes 0, ahora 2 sin escribir; B2) y el tamaño del HTML del tablero en las repeticiones (B1); la salida, los errores y los archivos escritos de los demás casos son los mismos.

## Comprobación

Otro agente con Opus, que no escribió las correcciones, hizo esta comprobación en solo lectura sobre el repositorio (plan, sección 28, ítem 3). Trabajó en una carpeta de `mktemp -d` fuera de todo repositorio, con dos clones (`git clone --no-hardlinks`), uno en `b15055c` y otro en `38a6c56`. Cada uno tenía su `.venv` (Python 3.11.1, `pip install -r requirements-dev.txt`) y los dos Parquet copiados de `data/raw/`. Las sondas que escriben corrieron en copias hechas con `git archive`. «Nada escrito» quiere decir que el SHA-256 de toda la copia, nombres de carpetas incluidos, es igual antes y después.

La comprobación la transcribió el orquestador, porque la herramienta del agente no pudo escribir el archivo (L88), con las rutas del equipo quitadas. La sección de arriba cuenta lo que el agente midió; lo que se hizo con sus hallazgos está en el registro (L88) y en la sincronización de este documento (plan, sección 28, ítem 4).

### B1. Grupos indistinguibles

- **Cálculo propio.** Un guion que solo usa `json` armó los componentes conexos del grafo de solapes (tocarse cuenta) con los intervalos de `reports/model_seal.json`.
  - El sello es idéntico en los dos commits: `060428fe…6a6a`.
  - Lanzamiento: 43 celdas ordenadas en 3 componentes, de 1, 33 y 9 celdas, frente a 5 grupos sellados de 1, 1, 32, 1 y 8.
  - Prueba recuperada: 36 celdas en 1 componente, frente a 2 grupos sellados.
  - Prueba cruda: 1 componente y 1 grupo sellado.
  - Cada celda ordenada tiene su aumento dentro de su intervalo, así que la numeración por aumento es coherente.
- **Reproducción del informe, en `b15055c`.** Hay 4 pares que se pisan con `tier` distinto. `algorithms.json` publica solo `tier`, también con 4 pares, y `summary.json` publica 5 grupos: falla.
- **La misma reproducción en `38a6c56`.**
  - El sello sigue con sus 4 pares. Es lo esperado, porque el `tier` sellado no se reescribe (D45).
  - Sobre `overlap_group` de `algorithms.json` hay 0 pares que se pisan en grupos distintos.
  - Las 47 celdas tienen `overlap_group` igual al cálculo propio y `tier` igual al sello.
  - `summary.json`: `headline.overlap_groups = 3` y `tiers = 5`.
  - `operation.json`: `overlap_groups_now` tiene 3 grupos (1, 33 y 9 celdas, que suman 43), cada uno con un solo componente propio.
- **`fact_cell_effect`.** En los cinco alcances y versiones (lanzamiento crudo y recuperado, prueba cruda y recuperada, `valid_replication`), `overlap_group` coincide celda por celda con el cálculo propio, con 0 discrepancias. Pasa lo mismo en el modo rápido.
- **Tablero.** La medida «Grupos indistinguibles» es `DISTINCTCOUNT(fact_cell_effect[overlap_group])` sobre el lanzamiento recuperado sellado, y el gráfico de intervalos usa `overlap_group`.
- **Documentos.** El README, la ficha y `SITE-UPDATES.md` dicen «3 grupos, de 1, 33 y 9», «la semana de prueba (recuperado), un solo grupo» y los 5 y 2 grupos sellados. Todo coincide.
- **Ningún aumento, intervalo, recuento de pares (183/903) ni criterio cambió.** El contenido del sello es igual.
- **Estado: corregida.**

### B2. `[effect] versions`

- **En `b15055c`.** En una copia con `make-fixture data/quick --series 60` y `config/raw_only.toml` (`versions = ["raw"]`), `replay` sale con 0. `effect_estimates` tiene `raw` 118 y `recovered` 170 filas, y `daily_cell` tiene 139 y 139. Se ignora: falla.
- **En `38a6c56`.** Se probaron siete valores, cada uno con `replay` y con `run`:
  - `["raw"]`, `["recovered"]` y `["recovered", "raw"]` salen con 2 y un mensaje que nombra la clave y el valor aceptado.
  - `["raw", "recovered", "raw"]` y `[]` salen con 2 por «no vacía y sin repetidos».
  - `["raw", "bogus"]` sale con 2 por valor desconocido.
  - `"raw"` (texto en lugar de lista) sale con 2 por «se esperaba una lista».
  - En los 14 casos no se escribió nada.
- **El valor aceptado `["raw", "recovered"]`** corre igual que antes (ver el modo rápido abajo).
- **Estado: corregida.**

### B3. La documentación frente al registro y al último commit

- `review-advisories.md` cuenta 24 hallazgos de L74 a L84, y hay 24 bloques «Hallazgo:», incluido el de L82 (`NOT_FILTERED_MARK`). Ya no aparecen «20 en total», «todavía no consta», «hoy son 41» ni «20 hallazgos».
- `paso-a-paso.md` nombra L70 a L85 y U01 a U21, y da U19 como no revisable (L82).
- El README dice «40 decisiones (hoy el registro tiene 50)», y `grep -c "^## D" docs/decisions.md` da 50.
- D44 tiene su nota fechada (B3, L85).
- La suite recoge 883 pruebas: 882 pasadas y 1 saltada, y con `-m real_data` quedan 885 deseleccionadas. Total 893, que es 883 más 8 reales más 2 de Docker.
- Los tiempos de la ficha (133,58 s y 135,07 s en `95f57f7`) valen para `38a6c56`: `git diff --stat 95f57f7 38a6c56` solo toca `evaluation.md` y `model-card.md`, y se midieron 132,98 s y 130,73 s.
- `docs/evaluation.md` tenía «Comprobación» como pendiente.
- **Estado: corregida.** Queda una advertencia (N1, abajo).

### B4. RNF02 y AC34, la corrida diaria

Una repetición real completa (`python -m promolift replay`) en el clon de `38a6c56`, sin otra carga en el equipo:

| Corrida | Duración (de `dim_pipeline_run`) | Detalle |
| --- | --- | --- |
| Reloj de pared | 723 s | |
| Lanzamiento | 318 s | load 62,0; fit_model 205,2; export 32,9 |
| Corridas diarias | 41, 42, 43, 43, 43, 44 y 46 s | load 14,9 a 16,9 s; export 21,2 a 23,0 s |
| Cierre | 93 s | evaluate 53,4 |
| Corrida sin entrega (`run`) | 1 s | |

- **Memoria:** 4.084,2 MB de `PeakWorkingSetSize` (`peak_working_set_mb`, contador `memory_counter = PeakWorkingSetSize`). `peak_commit_mb`, el `PeakPagefileUsage` (memoria comprometida, informativo), es de 5.802,8 MB.
- **Prueba de tiempo:** después de la repetición, `pytest -m real_data` dio 8 pasadas, entre ellas `test_every_daily_run_takes_at_most_the_required_seconds`. En `b15055c` la evaluación había medido de 61 a 65 s.
- **Estado: corregida.** El margen es de 14 s en la corrida más lenta.

### El crítico de L84 (`docs_sync.py:44`)

- En `b15055c` la fila separadora ya tiene cuatro celdas (`| --- | --- | --- | --- |`).
- Las 28 tablas de `docs/data-dictionary.md` tienen el mismo número de celdas en el encabezado, el separador y las filas, en los dos commits.
- No se reproduce.

### Invariantes

- **Modo rápido completo en los dos commits** (mismo accesorio, SHA-256 `fb2d52e6…dfff`):
  - 22 de los 25 Parquet tienen el mismo contenido, sin las columnas de corrida.
  - En los otros tres solo se agregan columnas: `overlap_group` en `fact_cell_effect` (B1) y `fit_blocks` en `fact_band_effect` y `fact_overall_effect` (A5). Las demás columnas son iguales fila por fila.
  - `data.json`, `validation_rules.json`, `evaluation_summary.json` y `validation/latest.json` no cambian.
  - El sello rápido es igual salvo dos `run_key`.
  - `algorithms.json`, `operation.json` y `summary.json` solo agregan `overlap_group`, `overlap_groups_now` y `headline.overlap_groups`.
  - `evaluation_summary.md` solo cambia la columna «Lo que prueba el umbral» (A2) y la clave de corrida.
- **Diferencial de la línea de comandos.** Son 20 casos en el modo rápido, cada uno en una copia nueva de cada commit: las cinco ayudas, un comando desconocido, `make-fixture ../outside`, `--series 0`, `docs-sync` y `figures` antes de correr, `replay --until X…`, `run --only validate --from load`, `--run-key ABC`, `--only nosuchtask`, `task load`, `task recover`, `raw_only`, `--until L…` dos veces, repetir sin pendientes junto con `run` y `--until C…`, y repetir más `docs-sync` y `figures`. Se compararon la salida, los errores (normalizados por claves de corrida, rutas y tiempos), el código de salida y si la copia cambió. Las únicas diferencias son las pedidas:
  - la ayuda de `make-fixture` (U17/S1);
  - `raw_only` (antes 0, ahora 2 y nada escrito; B2);
  - `task load` y `task recover` de una corrida nueva: en `b15055c` la copia cambia por la carpeta vacía `data/quick/interim/`, y en `38a6c56` queda igual (A6).
- **La repetición real frente a lo confirmado en `38a6c56`:**
  - Los 25 Parquet tienen el mismo contenido sin las claves de corrida, las fechas y las celdas de memoria. `dim_pipeline_run` tiene las mismas 10 filas después de `run`.
  - Los cinco JSON del sitio, `evaluation_summary.json` y `validation/latest.json` no tienen diferencias.
  - `reports/model_seal.json` es igual byte a byte, y el lanzamiento dio `seal=unchanged`, `artifact_sha256=a0b0aa69…` y las corridas diarias `seal=match`.
  - El HTML del tablero es igual salvo claves de corrida y fechas.
  - Las nueve figuras de `figures` son iguales byte a byte.
  - `docs-sync` cambia en el README solo la clave de corrida.
- **Suite por defecto en `38a6c56`, en reposo:** 882 pasadas, 1 saltada, 10 deseleccionadas, en 132,98 s y 130,73 s (límite 180 s, presupuesto 150 s).
- **`-m real_data`** después de la repetición: 8 pasadas en 11,6 s.
- `-m docker` no se corrió en la comprobación; las correcciones lo corrieron (2 pasadas en 88,25 s).

### Hallazgos nuevos

- **N1 (advertencia, documentación).** D49 dice que las revisiones nativas dejaron «veintitrés hallazgos». `review-advisories.md`, el registro y `docs/evaluation.md` cuentan 24, y hay 24 bloques «Hallazgo:». Reproducción: `grep -c "Hallazgo:" docs/review-advisories.md` y `grep -n "veintitrés" docs/decisions.md`.
- Ningún bloqueante nuevo.

## Lo que queda

La página del sitio, el `.pbix` y lo que el plan deja al dueño (sección 29), entre ellos si una versión posterior, con su propio sello, guarda los componentes como grupo sellado (D45). Ningún bloqueante ni advertencia de esta evaluación queda abierto.
