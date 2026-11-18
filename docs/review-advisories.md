# Advertencias de las revisiones nativas

Cada hallazgo de las revisiones nativas de Gentle AI que el registro del documento de seguimiento anota (L74, L76, L78, L80, L82, L84 y L87: 33 en total, entre sugerencias, advertencias y uno marcado crítico) y la advertencia nueva de la comprobación (L88, N1), 34 en total, con su ubicación y su estado después de las correcciones que siguieron a la evaluación independiente (L85, L86) y de la sincronización final (L88). Las revisiones aprobaron todo lo que revisaron; la de L84 que dejó un hallazgo crítico lo aprobó igual, y el hallazgo no se reprodujo. Los hallazgos siguen el orden del registro. U19 (`6253c31`, la corrida real) no se pudo revisar: START lo rechazó con `lens_context_budget_exceeded` (9.002 líneas, casi todas salidas generadas) sin crear autoridad, y partirlo habría reescrito la historia confirmada (L82); la evaluación independiente recalculó cada cifra de esas salidas con su propio lector (L85). Tampoco se pudo revisar `a5f6ebd..6843245`, las salidas versionadas que regeneró la repetición del código corregido (L87: START lo rechazó con `lens_context_budget_exceeded`); la comprobación las revisó de otra manera, con su propia repetición real, que reprodujo cada Parquet y cada JSON versionado, el sello, el artefacto, el tablero y las nueve figuras (L88). Una prueba (`tests/docs/test_docs.py::test_open_advisories_match_review_file`) exige que cada hallazgo tenga su ubicación y uno de los estados `corregida` (con su commit), `refutada`, `dejada con evidencia` o `abierta`, y que la lista de abiertas del README sea la de este archivo.

Los hallazgos se numeran dentro de cada tramo (`S` para una sugerencia, `W` para una advertencia). Las ubicaciones son las del código al cierre de U19 (`6253c31`) para L74-L80 y las del commit revisado para L82 y L84; las que el registro no precisa dicen que se toman del registro. Cada estado `dejada con evidencia` dice por qué no se cambió.

Las ubicaciones de L87 son las del código en `38a6c56` (cuando difieren de las del commit revisado, se dice). Los hallazgos de L87 que son de código quedan **dejada con evidencia**: el código es el evaluado (L85) y el comprobado (L88), son advertencias y no bloqueantes, y la sincronización final no cambia código; los que son de documentación o de las pruebas de la documentación se corrigieron en ella.

## research (L74)

Tramo `37c2e99..6afd46c` (la investigación): aprobada con tres sugerencias.

- **S1**
  - Hallazgo: Una variable `dow` muerta.
  - Ubicación: `research/s03_censoring.py:24` (la de `research/s05_confounding.py:37` sí se usa).
  - Estado: **dejada con evidencia**. `research/` es el registro de la investigación tal como corrió, y queda fuera de lo que las correcciones podían tocar; la variable no cambia ninguna salida (la evaluación reprodujo el registro de `s04` byte a byte, L71).

- **S2**
  - Hallazgo: Las comprobaciones de consistencia interna se imprimen en lugar de afirmarse.
  - Ubicación: Los scripts de `research/` (`s00` a `s10`).
  - Estado: **dejada con evidencia**. Por lo mismo: es el registro de la investigación; las cifras que la investigación imprimió y el plan usó se volvieron a medir en el flujo con sus pruebas, y la evaluación las recalculó (L85).

- **S3**
  - Hallazgo: `to_tensors` lee una serie-día que falta como sin promoción, sin un error.
  - Ubicación: `research/common.py:77`.
  - Estado: **dejada con evidencia**. Latente: los dos Parquet no tienen series-días faltantes (50.000 series × 97 días, AC03), y el flujo no usa `research/common.py`; la lectura del flujo exige claves completas (U04).

## U01 (L74)

Tramo `ed6d6c4..ca24e22` (U01, escalada al ítem 5): aprobada con dos sugerencias.

- **S1**
  - Hallazgo: La prueba de las versiones instaladas corre en la selección por defecto.
  - Ubicación: `tests/unit/test_dependencies.py:317` (`test_installed_versions_match_the_pins`).
  - Estado: **dejada con evidencia**. Es de diseño: la prueba es la guarda de RNF01 (las versiones fijadas son las instaladas) y tarda milisegundos; sacarla de la selección por defecto dejaría sin comprobar el entorno con que corre la suite.

- **S2**
  - Hallazgo: Dos pruebas leen archivos fuera de la carpeta del proyecto.
  - Ubicación: `tests/unit/test_dependencies.py` (las que comparan con `05-Mining-Flotation-Silica/requirements*.txt`, D33); ubicación según el registro.
  - Estado: **dejada con evidencia**. Es de diseño (D33): comparan a propósito con los pines del proyecto 05 para que los dos proyectos no se separen en silencio; si esa carpeta falta, la prueba lo dice.

## U02-U03 (L74)

Tramo `ca24e22..79ac7a8` (U02 y U03, cierre del tramo): aprobada con dos sugerencias.

- **S1**
  - Hallazgo: Un parámetro `group` sin usar en `_draw_states`.
  - Ubicación: `tests/fixtures/make_fixture.py:186`.
  - Estado: **corregida** en `8b73512` (D49): el parámetro se quitó; el generador no sacaba números de él, así que el accesorio no cambia.

- **S2**
  - Hallazgo: `is_full_default_selection` depende de detalles internos de pytest.
  - Ubicación: `tests/fixtures/suite_budget.py:30`.
  - Estado: **dejada con evidencia**. pytest está fijado en 9.2.0 y `tests/unit/test_dependencies.py` falla si cambia; una actualización de pytest tiene que revisar esa función de todos modos.

## U05 (L76)

Tramo `b124c29..635cc48` (U05, cierre del tramo): aprobada con una sugerencia.

- **S1**
  - Hallazgo: `deliveries.py` reexporta `sha256_file` en `__all__` sin usarlo.
  - Ubicación: `src/promolift/deliveries.py:293` (`__all__`) y `:32` (la importación).
  - Estado: **corregida** en `8b73512` (D49): `__all__` ya no la nombra.

## U06 (L76)

Tramo `635cc48..a5f40d7` (U06 y la nota de D22): aprobada con una advertencia.

- **W1**
  - Hallazgo: `store_delivery_cube` reescribe el `manifest.json` del cubo de las entregas cargadas leyendo y modificando, sin un bloqueo. El bloqueo de un solo escritor de U15 lo cubre y la evaluación lo sondea.
  - Ubicación: `src/promolift/cube.py:225`.
  - Estado: **dejada con evidencia**. No se alcanza desde el flujo: toda escritura pasa por el bloqueo de un solo escritor (U15, D26), y la evaluación corrió dos copias a la vez sin que nada fuera de `data/` cambiara (L85).

## U07 (L76)

Tramo `a5f40d7..95de83d` (L73, L74 y U07): aprobada con una sugerencia.

- **S1**
  - Hallazgo: `recovery.py` importa `truth` de `masks` y reusa `truth`, `estimate` y `candidates` como nombres de parámetros.
  - Ubicación: `src/promolift/recovery.py:33` y las funciones `estimate` (`:112`) y `candidates` (`:209`).
  - Estado: **dejada con evidencia**. Solo nombres, en el módulo que calcula la recuperación sellada; la evaluación reprodujo R1 y R2 con su propio código (L85) y renombrar ahí no corrige nada.

## U08 (L76)

Tramo `95de83d..966189c` (U08 y la corrección de las claves de 32 bits): aprobada con tres hallazgos.

- **W1**
  - Hallazgo: Advertencia: `forecast.py` cae a 7 bandas escritas en el código cuando la vista no trae `days`.
  - Ubicación: `src/promolift/forecast.py:64`.
  - Estado: **corregida** en `8b73512` (D49): las bandas salen siempre de `view.days.bands`.

- **S1**
  - Hallazgo: `overlap_pairs` y `overlapping_pairs` se llaman casi igual (un carácter) y devuelven cosas distintas.
  - Ubicación: `src/promolift/ranking.py:20` y `:25`.
  - Estado: **corregida** en `8b73512` (D49): `overlapping_pairs` se llama ahora `pair_counts`; los grupos indistinguibles se corrigieron aparte (B1, `9c6e964`, D45).

- **S2**
  - Hallazgo: `forecast_errors` divide por el total observado sin cuidar el cero.
  - Ubicación: `src/promolift/forecast.py:75`.
  - Estado: **dejada con evidencia**. Fuera de dominio: cada alcance con pronósticos tiene series-días con venta observada (L85); un total cero sería un alcance vacío, que no se emite.

## U09 (L76)

Tramo `966189c..5c8aaa2` (U09, escalada al ítem 1): aprobada con una sugerencia.

- **S1**
  - Hallazgo: `two_way_draws_many` reimplementa a mano `weighted_sums`.
  - Ubicación: `src/promolift/bootstrap.py:31` (`two_way_draws_many`) y `:21` (`weighted_sums`).
  - Estado: **dejada con evidencia**. El remuestreo propio de la evaluación dio los mismos límites (L85); reescribir el camino que produjo los intervalos sellados no ganaría nada y arriesgaría reproducir el sello.

## U11 (L78)

Tramo `f051a68..9263e00` (L76 y U11, escalada al ítem 1): aprobada con una sugerencia.

- **S1**
  - Hallazgo: `registry._check_part` decide si comprueba `sealed_config` por la identidad `keys is LAUNCH_KEYS` y no por un valor.
  - Ubicación: `src/promolift/registry.py:459`.
  - Estado: **corregida** en `8b73512` (D49): la comprobación depende de que la parte tenga `sealed_config`.

## U13 (L78)

Tramo `a0927a1..a204643` (U13, escalada al ítem 6): aprobada con una advertencia.

- **W1**
  - Hallazgo: Advertencia: en `render._preview`, dos claves de `makers` usan el título sin más y los visuales le agregan la nota de «no filtrado», de modo que esas dos vistas previas no se dibujaban. Se corrigió con la prueba primero: las claves quedaron sin la nota. Según L81, la advertencia tenía la mitad de razón: las dos claves estaban muertas, pero unas ramas `startswith` ya dibujaban esos visuales.
  - Ubicación: `src/promolift/dashboard/render.py` (`_preview`).
  - Estado: **corregida** en `f553c1e` (L81)

## U14 (L78)

Tramo `a204643..26e9d66` (U14, escalada al ítem 3): aprobada con dos sugerencias.

- **S1**
  - Hallazgo: `figures._recovery_check` une `fit_blocks` sin filtrar los `None`.
  - Ubicación: `src/promolift/figures.py:109`.
  - Estado: **corregida** en `8b73512` (D49), con una prueba vista fallar antes (`tests/unit/test_figures.py::test_a_recovery_row_without_its_blocks_is_left_out_of_the_title_instead_of_breaking_it`).

- **S2**
  - Hallazgo: Las series de `cell_ranking` no pasan por `_none`, como las demás.
  - Ubicación: `src/promolift/figures.py:52` (los datos) y `:31` (`_none`).
  - Estado: **corregida** en `8b73512` (D49).

## U17 (L80)

Tramo `dd56dc6..936200c` (la unidad de velocidad y U17, cierre del tramo): aprobada con dos sugerencias.

- **S1**
  - Hallazgo: La ayuda de `make-fixture --output` dice que una ruta relativa se toma de la carpeta del proyecto, pero se resuelve contra `$PROMOLIFT_HOME` primero.
  - Ubicación: `src/promolift/cli.py:73`.
  - Estado: **corregida** en `8b73512` (D49): la ayuda dice «desde $PROMOLIFT_HOME o, sin él, desde la carpeta del proyecto».

- **S2**
  - Hallazgo: Un splat condicional muerto en la prueba de `--series` y `--days`.
  - Ubicación: `tests/e2e/test_cli.py:142`.
  - Estado: **corregida** en `8b73512` (D49).

## f553c1e (L82)

Tramo `593ffc8..f553c1e` (el límite de la suite del dueño, L79-L80 y la corrección de las vistas previas, cierre del tramo): aprobada con una sugerencia.

- **S1**
  - Hallazgo: `render.NOT_FILTERED_MARK` es el literal parcial `' (no lo'` y no sale de `semantic_model.NOT_FILTERED`.
  - Ubicación: `src/promolift/dashboard/render.py:355`.
  - Estado: **corregida** en `8b73512` (D49): sale de la nota misma, con una prueba vista fallar antes (`tests/unit/test_render.py::test_the_mark_that_cuts_the_not_filtered_note_is_derived_from_the_note_itself`).

## U20 (L84)

Tramo `6253c31..4ad3f14` (L81-L82 y U20, cierre del tramo): aprobada con dos hallazgos.

- **S1**
  - Hallazgo: Las tablas por banda y por día de la ficha del modelo traen cifras que ninguna prueba de la documentación fija.
  - Ubicación: `docs/model-card.md` («Contrafactual»); ubicación según el registro.
  - Estado: **corregida** en `a5f6ebd`: `tests/docs/test_docs.py::test_the_band_and_day_tables_of_the_model_card_are_the_site_files` compara cada fila con `algorithms.json` y `operation.json`.

- **W1**
  - Hallazgo: La docstring de `tests/docs/test_docs.py` anuncia invariantes de U21 como probadas en ese módulo.
  - Ubicación: `tests/docs/test_docs.py:1` (la docstring del módulo).
  - Estado: **corregida** en `8585877`: era cierta en `4ad3f14`, y U21 agregó una prueba por cada invariante que la docstring nombra (los siete campos, el número de pruebas, los contadores, las pruebas del plan, las entradas del registro, el diccionario, el runbook, el paso a paso, los enlaces, las advertencias y las filas de la raíz).

## U21 (L84)

Tramo `4ad3f14..8585877` (U21, cierre del tramo): aprobada con un hallazgo marcado crítico.

- **C1**
  - Hallazgo: En `docs_sync.render_dictionary_tables`, el encabezado y las filas tienen cuatro celdas y la fila separadora tres (`| --- | --- | --- |`), así que GitHub no muestra como tablas las del diccionario.
  - Ubicación: `src/promolift/docs_sync.py:44` (según el registro; la fila separadora está en la línea 45).
  - Estado: **refutada**. La fila separadora que escribe el código es `| --- | --- | --- | --- |`, de cuatro celdas, en `8585877` y hoy; las 25 tablas generadas del diccionario y todas las tablas del README y de `docs/` tienen en la fila separadora y en cada fila las celdas de su encabezado. `tests/docs/test_docs.py::test_every_markdown_table_has_as_many_cells_in_its_delimiter_and_its_rows_as_in_its_header` (`a5f6ebd`) lo mantiene, y falla si una fila separadora del diccionario pierde una celda.

## B1 (L87)

Tramo `8585877..9c6e964` (L84-L85 y B1, escalada al ítem 1): aprobada con una sugerencia.

- **S1**
  - Hallazgo: `svg.interval_chart` sigue atando el grupo a una variable que se llama `tier`, aunque ahora recibe el grupo indistinguible (`overlap_group`) y no el grupo sellado.
  - Ubicación: `src/promolift/dashboard/svg.py:270` y `:286` (la lista de elementos y el bucle).
  - Estado: **dejada con evidencia**. Es solo el nombre de una variable local: no cambia ninguna salida (el gráfico de intervalos se comprobó con `overlap_group` en los cinco alcances, L88), y el código es el evaluado y el comprobado. Renombrarla sería un cambio de código sin efecto que la sincronización final no hace.

## B4 (L87)

Tramo `6eb7c68..8ef2a3e` (B4, escalada al ítem 1): aprobada con una sugerencia.

- **S1**
  - Hallazgo: ninguna prueba recorre el disparador que borra el registro de la preparación cuando se inserta una serie-día anterior al instante registrado.
  - Ubicación: `sql/staging/stg_series_days_meta.sql:12` (`stg_meta_series_day_before_the_instant`).
  - Estado: **dejada con evidencia**. Es la segunda barrera: al extender, `warehouse._rebuild` ya compara cuántas series-días anteriores al instante tiene la tabla con las que dice el registro (`src/promolift/warehouse.py:418`) y reconstruye entera si no coinciden; `tests/integration/test_load.py::test_the_staging_is_rebuilt_whole_when_the_instant_goes_back_the_partition_changes_or_a_day_appears_before_the_instant` fija el resto de los disparadores y la reconstrucción. El código es el comprobado: la repetición real de L88 dio las corridas diarias de 41 a 46 s y el contenido versionado igual.

## A6 (L87)

Tramo `8ef2a3e..75456e7` (A6, escalada al ítem 4): aprobada con una sugerencia.

- **S1**
  - Hallazgo: si otras liberaciones quitan la carpeta entre cada intento, `_create_in_folder` puede terminar en un `FileNotFoundError` sin atrapar.
  - Ubicación: `src/promolift/lock.py:304` (el último `_create` después del bucle de `FOLDER_ATTEMPTS`).
  - Estado: **dejada con evidencia**. Pide que otro proceso quite la carpeta vacía cinco veces seguidas entre el `mkdir` y la creación del archivo, y el bloqueo es de un solo escritor (D26); si ocurriera, la toma falla con un error y no escribe nada, que es el rechazo de siempre. La carrera de una vez la cierra el reintento, con su prueba (D48).

## a5f6ebd (L87)

Tramo `75456e7..a5f6ebd` (las advertencias de la evaluación y las pruebas de las tablas de la ficha, cierre del tramo): aprobada con cuatro sugerencias.

- **S1**
  - Hallazgo: `forecast.forecasts` necesita ahora que la vista traiga `days` (las bandas salen siempre de `view.days.bands`).
  - Ubicación: `src/promolift/forecast.py:64`.
  - Estado: **dejada con evidencia**. Es lo que U08/W1 pedía (D49): el 7 literal de respaldo salía de la configuración y no de la vista; la vista de la corrida trae siempre `days`, y las dos llamadas del flujo (`src/promolift/daily.py:169` y `src/promolift/launch.py:333`) le pasan la vista de la corrida.

- **S2**
  - Hallazgo: la rama de `registry._check_part` que decide por la pertenencia (`"sealed_config" in keys`) no tiene una prueba directa que la fuerce a fallar.
  - Ubicación: `src/promolift/registry.py:459`.
  - Estado: **dejada con evidencia**. La rama se recorre en cada lectura y escritura del sello, con la parte del lanzamiento y con la de la prueba (`registry.py:474` y `:511`), y el sello es igual byte a byte en la comprobación (L88); lo que falta es una prueba que fuerce su error, y agregarla es un cambio de código fuera de esta sincronización.

- **S3**
  - Hallazgo: el mensaje de esa rama sigue nombrando la parte del lanzamiento, aunque `_check_part` se usa también para la de la prueba.
  - Ubicación: `src/promolift/registry.py:460`.
  - Estado: **dejada con evidencia**. Solo la parte del lanzamiento lleva `sealed_config`, así que la rama nunca falla para la de la prueba y el mensaje es el correcto en la práctica; es el texto de un error de un sello corrupto, que ninguna corrida produce.

- **S4**
  - Hallazgo: un recorrido de las tablas difícil de leer en `test_every_markdown_table_has_as_many_cells_in_its_delimiter_and_its_rows_as_in_its_header`.
  - Ubicación: `tests/docs/test_docs.py:582` en `a5f6ebd` (el cálculo de `body`).
  - Estado: **corregida** en `0000000`: el cuerpo de la tabla se arma en tres líneas con nombres, con el mismo resultado.

## 38a6c56 (L87)

Tramo `6843245..38a6c56` (la documentación de las correcciones): aprobada con dos hallazgos. El tramo intermedio, `a5f6ebd..6843245`, no se revisó (ver arriba).

- **W1**
  - Hallazgo: `docs/paso-a-paso.md:3` dice que la evaluación independiente y sus correcciones «no se hicieron todavía» y no están ahí, contra sus propias secciones 7 y 8.
  - Ubicación: `docs/paso-a-paso.md:3`.
  - Estado: **corregida** en `0000000`: la introducción dice lo que las secciones cuentan (la evaluación, las correcciones, la comprobación y esta sincronización, L85 a L88) y que lo que falta es la página del sitio y el `.pbix`.

- **S1**
  - Hallazgo: la tupla `DOCS` de `tests/docs/test_docs.py` no incluye `evaluation.md`.
  - Ubicación: `tests/docs/test_docs.py` (`DOCS`).
  - Estado: **corregida** en `0000000`: `evaluation.md` está en la tupla y la prueba `test_the_evaluation_and_its_check_are_recorded_as_done_and_no_document_says_otherwise` exige que cada bloqueante conste como corregido en la evaluación y en la comprobación.

## Comprobación (L88)

La comprobación (L88) no encontró ningún bloqueante nuevo. Dejó una advertencia.

- **N1**
  - Hallazgo: D49 dice que las revisiones nativas dejaron «veintitrés hallazgos», y este archivo, el registro y `docs/evaluation.md` cuentan 24 (hasta L84).
  - Ubicación: `docs/decisions.md` (D49, «Contexto»).
  - Estado: **corregida** en `0000000`: D49 lleva una nota fechada que dice que son 24 (y 33 con los de L87), y una prueba la fija.
