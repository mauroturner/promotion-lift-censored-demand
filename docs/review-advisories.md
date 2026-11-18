# Advertencias de las revisiones nativas

Cada hallazgo de las revisiones nativas de Gentle AI que el registro del documento de seguimiento anota (L74, L76, L78, L80, L82 y L84: 24 en total, entre sugerencias, advertencias y uno marcado crítico), con su ubicación y su estado después de las correcciones que siguieron a la evaluación independiente (L85). Las revisiones aprobaron todo lo que revisaron. Los hallazgos siguen el orden del registro. U19 (`6253c31`, la corrida real) no se pudo revisar: START lo rechazó con `lens_context_budget_exceeded` (9.002 líneas, casi todas salidas generadas) sin crear autoridad, y partirlo habría reescrito la historia confirmada (L82); la evaluación independiente recalculó cada cifra de esas salidas con su propio lector (L85). Una prueba (`tests/docs/test_docs.py::test_open_advisories_match_review_file`) exige que cada hallazgo tenga su ubicación y uno de los estados `corregida` (con su commit), `refutada`, `dejada con evidencia` o `abierta`, y que la lista de abiertas del README sea la de este archivo.

Los hallazgos se numeran dentro de cada tramo (`S` para una sugerencia, `W` para una advertencia). Las ubicaciones son las del código al cierre de U19 (`6253c31`) para L74-L80 y las del commit revisado para L82 y L84; las que el registro no precisa dicen que se toman del registro. Cada estado `dejada con evidencia` dice por qué no se cambió.

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
