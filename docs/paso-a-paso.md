# Paso a paso: cómo se hizo el proyecto

La cronología real, desde el registro del documento de seguimiento (`odd/tasks/portfolio-projects.md`, L70 a L85) y `git log` de esta carpeta: qué se hizo en cada paso, quién (qué agente y con qué modelo, S8), con qué prueba y en qué commit. Todo lo que dice este documento consta en el registro; una prueba comprueba que cada unidad y cada entrada del registro que nombra existe, y que cada commit que cita está en el historial (`tests/docs/test_docs.py`). La evaluación independiente y sus correcciones no se hicieron todavía y no están aquí.

El dueño del proyecto pidió que cuando se termina un proyecto se siga con el siguiente sin preguntar (S12), que la estructura sea la del proyecto 01 (S10), que se acepten de forma automática las revisiones de Gentle AI (S11) y los modelos de los agentes: Opus para planes, arquitectura y evaluación, Sonnet para programar y Haiku para tareas acotadas como investigar (S8).

## 1. La investigación (L70, L71)

**Qué.** Empezó el proyecto 06 (L70). Un agente con Haiku bajó FreshRetailNet-50K (Hugging Face, CC BY 4.0) con un script fijado al commit del conjunto, comprobó sus dos huellas, perfiló los quiebres de stock, las promociones, la confusión y las fugas, midió las líneas base y una primera mirada del efecto (+11,1 % crudo, +38,6 % recuperado) y escribió `docs/research.md` con sus scripts `s00` a `s10`, sin calcular nada sobre la semana de prueba (L71).

**Lo que encontró.** El 19,9 % de las horas de 06 a 21 está sin stock; las horas sin stock venden 89,5 % menos en la misma serie y hora; la promoción sube esa tasa 4,5 puntos; la serie explica el 44 % de la variación de la promoción y el producto el 35 %; la marca y el descuento no coinciden; los dos campos diarios de venta y de horas sin stock son sumas de las horas y filtran el objetivo; nueve contradicciones con el sitio y doce preguntas abiertas.

**Commit.** `6afd46c`, el 2026-11-17.

## 2. Los requerimientos y el plan (L72)

**Qué.** Un agente con Opus leyó la investigación y los documentos del proyecto 05 con su evaluación, y repitió parte de la medición leyendo solo `train.parquet` (scripts `p01` a `p07` en `research/plan/`). Escribió `docs/requirements.md` (RF01-RF24, RNF01-RNF16, AC01-AC38 y los criterios C01-C10 con su resultado esperado dicho antes de medir: que C06 y C09 probablemente no se cumplirían), `docs/plan.md` (30 secciones, 21 unidades de trabajo) y `docs/decisions.md` (D01-D40, cada una con sus siete campos).

**Prueba.** Una repetición de `p01` dio una salida idéntica (revisión del orquestador).

**Commit.** `ed6d6c4`, antes de cualquier código: así los criterios y lo esperable quedaron en Git antes de la primera medición real.

## 3. La construcción, unidad por unidad (L73, L75, L77, L79, L81)

Agentes con Sonnet escribieron U01 a U19, cada unidad con su prueba primero (se vio fallar por la razón esperada antes de escribir el código), las mutaciones de sus reglas de negocio y un commit propio, y las de riesgo alto solas para que la revisión nativa las tomara sin mezclarlas.

| Unidad | Qué entrega | Commit | Registro |
| --- | --- | --- | --- |
| U01 | El entorno con las versiones fijadas y la prueba de que toda importación es una dependencia directa | `ca24e22` | L73 |
| U02 | La configuración con cada clave clasificada como sellada o no, y la partición en días | `f103cae` | L73 |
| U03 | El par de Parquet sintético con su demanda latente, los casos a mano, los accesorios de sesión y el límite de tiempo de la suite | `79ac7a8` | L73 |
| U04 | La lectura estricta de los Parquet no confiables, los tensores canónicos y los estados del día | `b124c29` | L73 |
| U05 | Las entregas y las reglas de validación V10 a V27 | `635cc48` | L73 |
| U06 | La carga a SQLite en una transacción con sus controles, y el cubo de las entregas cargadas copiado después de confirmar | `ab109b2`, `f41d484` | L73 |
| U07 | Las máscaras de censura sintética y los métodos de recuperación R0 a R3 | `95de83d` | L75 |
| U08 | El contrafactual por IPF, el remuestreo de dos vías, el ranking en grupos indistinguibles y los pronósticos | `9e41b79` | L75 |
| U09 | La elección en V1, la vista previa en V2, el reajuste con los 90 días, el modelo congelado y el sello del lanzamiento | `5c8aaa2` | L75 |
| U10 | La corrida diaria: lo emitido una sola vez | `f051a68` | L75 |
| U11 | La evaluación de la prueba una vez, con los criterios C01-C10, las variantes y el resumen | `9263e00` | L77 |
| U12 | El modelo estrella para Power BI | `a0927a1` | L77 |
| U13 | Las medidas DAX, las cinco páginas y el diseño del tablero en HTML | `a204643` | L77 |
| U14 | La exportación de cinco JSON para el sitio bajo un manifiesto escrito al final, y las nueve figuras | `26e9d66` | L77 |
| U15 | El bloqueo de un solo escritor | `ac59981` | L79 |
| U16 | Las once tareas bajo el bloqueo, los rechazos antes de escribir y el cierre ordenado | `dd56dc6` | L79 |
| U17 | La línea de comandos y el modo rápido aislado | `936200c` | L79 |
| U18 | El DAG `promolift_daily`, Docker y el compose con todos los secretos del entorno | `593ffc8` | L79 |
| U19 | La corrida real completa y la primera lectura de la semana de prueba | `6253c31` | L81 |
| U20 | El README y la ficha del modelo, desde el resumen sellado | `4ad3f14` | L83 |
| U21 | El diccionario, el runbook, este paso a paso y las advertencias de las revisiones | `8585877` | L83 |

**Commits que no son una unidad.**

- `a5f40d7` (L73): notas fechadas en D02, D13, D22 y D33 con lo que la lectura real mostró.
- `966189c` (L75): una corrección con su prueba primero, porque las claves de serie de un bloque se leían como enteros de 16 bits y las 50.000 series reales se envolvían.
- `5bd11a5` (L75): D29 con los tiempos medidos de U10.
- `1211979` (L79): una unidad de velocidad: la sesión corre sin `os.fsync`, y las pruebas de rechazo comparan tamaño y hora en lugar de recalcular huellas.
- `4e73cdd` (L79): el límite de la suite pasa de 120 s a 180 s y su presupuesto de trabajo de 90 s a 150 s, después de que el agente le preguntó al dueño por Telegram con tres salidas y el dueño eligió subir el límite («2 subir límite»).
- `f553c1e` (L81): las vistas previas del tablero con el título sin la nota de «no filtrado», que corrige la advertencia de la revisión de U13 (L78).

**Dos hechos de los datos reales que cambiaron una decisión durante la construcción** (L73, L75). La columna `discount` guarda el mismo descuento de dos maneras (el double que se quiso y su vecino de float32) en 3.338 filas, de modo que los bordes de las bandas usan una tolerancia de 10⁻⁶ (D13). Y 90 vistas vivas de un archivo mapeado en memoria llevaron el conjunto de trabajo de la corrida en seco a 20,9 GB (`PeakWorkingSetSize`): copiar cada día al leerlo lo bajó a 4,3 GB (D22).

## 4. Las revisiones nativas (L74, L76, L78, L80, L82, L84)

La revisión nativa de Gentle AI revisó la investigación, U01 a U18, U20, U21 y los tramos de documentos que alcanzó, cada unidad de riesgo alto sola y el resto en tramos, con el consentimiento aceptado de forma automática (S11). Aprobó todo lo que revisó, con 24 hallazgos entre sugerencias, advertencias y uno marcado crítico, que `docs/review-advisories.md` lista con su ubicación y su estado. Un tramo de documentos no tenía riesgo para revisar (L74) y otro superó el presupuesto de contexto (L74). **U19 no se pudo revisar** (L82): START lo rechazó con `lens_context_budget_exceeded` (9.002 líneas, casi todas salidas generadas) sin crear autoridad, y partirlo habría reescrito la historia confirmada; la evaluación independiente recalculó cada cifra de esas salidas con su propio lector (L85).

## 5. La corrida real (L81)

Una sola vez, `6253c31`: `replay` sobre los dos Parquet reales (el lanzamiento, siete entregas diarias y el cierre), una corrida sin entrega, y la evaluación de la semana de prueba bajo el sello. Seis de los nueve criterios con umbral se cumplen; C06 y C09 no, como se esperaba; **C04 no, aunque se esperaba que sí** (+1,37 puntos, de −1,81 a +4,36). La repetición completa tardó 876 s; las siete corridas diarias tardan de 62 a 68 s contra un límite de 60 s, y su prueba está en rojo a propósito (RNF02). El orquestador comprobó que los valores del resumen coinciden con el informe, y avisó al dueño por Telegram.

## 6. La documentación (L83)

U20, el README y la ficha del modelo (`4ad3f14`), y U21, el diccionario, el runbook, este paso a paso y las advertencias de las revisiones (`8585877`), escritos por un agente con Sonnet con la prueba primero: cada prueba nombrada se vio fallar contra el documento que faltaba antes de escribirlo. Las cifras de las tablas salen de los archivos sellados y del resumen; `docs-sync` aprendió a escribir las tablas del diccionario desde el modelo semántico (D44).

## 7. La evaluación independiente (L85)

Un agente con Opus que no construyó el proyecto evaluó `b15055c` en solo lectura, en un clon aparte con su propio entorno, con un lector propio de los Parquet que no importa `promolift`. Cada cifra recalculada coincide a 10⁻⁹ o mejor, y su repetición real reprodujo el sello. Encontró cuatro bloqueantes (B1: los grupos indistinguibles separaban celdas que se pisan; B2: `[effect] versions` se ignoraba; B3: esta documentación no reflejaba L82; B4: la corrida diaria pasaba de 60 s) y nueve advertencias. Su informe está en [evaluation.md](evaluation.md).

## 8. Las correcciones

Un agente con Opus, con la prueba primero, una corrección de riesgo alto por commit:

- `9c6e964` **B1** (ítem 1; D45): los grupos indistinguibles son los componentes conexos del grafo de solapes, publicados al lado del grupo sellado como análisis posterior al sello; el sello no cambia.
- `6eb7c68` **B2** (ítem 3; D47): `[effect] versions` acepta solo `["raw", "recovered"]`.
- `8ef2a3e` **B4** (ítem 1; D46): la preparación de las series-días se extiende en lugar de reconstruirse dos veces por entrega.
- `75456e7` **A6** (ítem 4; D48): el bloqueo quita las carpetas vacías que creó.
- `8b73512` **A2, A5, A8 y las advertencias de las revisiones que tocan el código** (D49).
- `a5f6ebd` las pruebas de las tablas de la ficha y de la forma de todas las tablas de la documentación.
- La repetición real sobre una copia, las salidas versionadas que cambian por diseño y esta documentación, en los commits que siguen.

## Lo que falta

La comprobación de las correcciones por otro agente con Opus, la página del sitio y el `.pbix`, que arma a mano quien tenga Power BI Desktop.
