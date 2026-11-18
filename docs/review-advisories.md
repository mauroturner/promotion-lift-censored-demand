# Advertencias de las revisiones nativas

Cada hallazgo de las revisiones nativas de Gentle AI que el registro del documento de seguimiento anota (L74, L76, L78 y L80: 20 en total, entre sugerencias y advertencias), con su ubicación y su estado. Las revisiones aprobaron todo lo que revisaron; ningún hallazgo bloqueó. Los hallazgos de las unidades de riesgo alto, de U01 a U18, siguen el orden del registro; la revisión nativa de U19 todavía no consta en él. Una prueba (`tests/docs/test_docs.py::test_open_advisories_match_review_file`) exige que cada hallazgo tenga su ubicación y uno de los estados `corregida` (con su commit), `refutada`, `dejada con evidencia` o `abierta`, y que la lista de abiertas del README sea la de este archivo.

Los hallazgos se numeran dentro de cada tramo (`S` para una sugerencia, `W` para una advertencia). Las ubicaciones son las del código al cierre de U19 (`6253c31`); las que el registro no precisa dicen que se toman del registro.

## research (L74)

Tramo `37c2e99..6afd46c` (la investigación): aprobada con tres sugerencias.

- **S1**
  - Hallazgo: Una variable `dow` muerta.
  - Ubicación: `research/s03_censoring.py:24` (la de `research/s05_confounding.py:37` sí se usa).
  - Estado: **abierta**. Para las correcciones que siguen a la evaluación independiente (plan, sección 28).

- **S2**
  - Hallazgo: Las comprobaciones de consistencia interna se imprimen en lugar de afirmarse.
  - Ubicación: Los scripts de `research/` (`s00` a `s10`).
  - Estado: **abierta**. Para las correcciones que siguen a la evaluación independiente (plan, sección 28).

- **S3**
  - Hallazgo: `to_tensors` lee una serie-día que falta como sin promoción, sin un error.
  - Ubicación: `research/common.py:77`.
  - Estado: **abierta**. Para las correcciones que siguen a la evaluación independiente (plan, sección 28).

## U01 (L74)

Tramo `ed6d6c4..ca24e22` (U01, escalada al ítem 5): aprobada con dos sugerencias.

- **S1**
  - Hallazgo: La prueba de las versiones instaladas corre en la selección por defecto.
  - Ubicación: `tests/unit/test_dependencies.py:317` (`test_installed_versions_match_the_pins`).
  - Estado: **abierta**. Para las correcciones que siguen a la evaluación independiente (plan, sección 28).

- **S2**
  - Hallazgo: Dos pruebas leen archivos fuera de la carpeta del proyecto.
  - Ubicación: `tests/unit/test_dependencies.py` (las que comparan con `05-Mining-Flotation-Silica/requirements*.txt`, D33); ubicación según el registro.
  - Estado: **abierta**. Para las correcciones que siguen a la evaluación independiente (plan, sección 28).

## U02-U03 (L74)

Tramo `ca24e22..79ac7a8` (U02 y U03, cierre del tramo): aprobada con dos sugerencias.

- **S1**
  - Hallazgo: Un parámetro `group` sin usar en `_draw_states`.
  - Ubicación: `tests/fixtures/make_fixture.py:186`.
  - Estado: **abierta**. Para las correcciones que siguen a la evaluación independiente (plan, sección 28).

- **S2**
  - Hallazgo: `is_full_default_selection` depende de detalles internos de pytest.
  - Ubicación: `tests/fixtures/suite_budget.py:30`.
  - Estado: **abierta**. Para las correcciones que siguen a la evaluación independiente (plan, sección 28).

## U05 (L76)

Tramo `b124c29..635cc48` (U05, cierre del tramo): aprobada con una sugerencia.

- **S1**
  - Hallazgo: `deliveries.py` reexporta `sha256_file` en `__all__` sin usarlo.
  - Ubicación: `src/promolift/deliveries.py:293` (`__all__`) y `:32` (la importación).
  - Estado: **abierta**. Para las correcciones que siguen a la evaluación independiente (plan, sección 28).

## U06 (L76)

Tramo `635cc48..a5f40d7` (U06 y la nota de D22): aprobada con una advertencia.

- **W1**
  - Hallazgo: `store_delivery_cube` reescribe el `manifest.json` del cubo de las entregas cargadas leyendo y modificando, sin un bloqueo. El bloqueo de un solo escritor de U15 lo cubre y la evaluación lo sondea.
  - Ubicación: `src/promolift/cube.py:225`.
  - Estado: **abierta**. Para las correcciones que siguen a la evaluación independiente (plan, sección 28).

## U07 (L76)

Tramo `a5f40d7..95de83d` (L73, L74 y U07): aprobada con una sugerencia.

- **S1**
  - Hallazgo: `recovery.py` importa `truth` de `masks` y reusa `truth`, `estimate` y `candidates` como nombres de parámetros.
  - Ubicación: `src/promolift/recovery.py:33` y las funciones `estimate` (`:112`) y `candidates` (`:209`).
  - Estado: **abierta**. Para las correcciones que siguen a la evaluación independiente (plan, sección 28).

## U08 (L76)

Tramo `95de83d..966189c` (U08 y la corrección de las claves de 32 bits): aprobada con tres hallazgos.

- **W1**
  - Hallazgo: Advertencia: `forecast.py` cae a 7 bandas escritas en el código cuando la vista no trae `days`.
  - Ubicación: `src/promolift/forecast.py:64`.
  - Estado: **abierta**. Para las correcciones que siguen a la evaluación independiente (plan, sección 28).

- **S1**
  - Hallazgo: `overlap_pairs` y `overlapping_pairs` se llaman casi igual (un carácter) y devuelven cosas distintas.
  - Ubicación: `src/promolift/ranking.py:20` y `:25`.
  - Estado: **abierta**. Para las correcciones que siguen a la evaluación independiente (plan, sección 28).

- **S2**
  - Hallazgo: `forecast_errors` divide por el total observado sin cuidar el cero.
  - Ubicación: `src/promolift/forecast.py:75`.
  - Estado: **abierta**. Para las correcciones que siguen a la evaluación independiente (plan, sección 28).

## U09 (L76)

Tramo `966189c..5c8aaa2` (U09, escalada al ítem 1): aprobada con una sugerencia.

- **S1**
  - Hallazgo: `two_way_draws_many` reimplementa a mano `weighted_sums`.
  - Ubicación: `src/promolift/bootstrap.py:31` (`two_way_draws_many`) y `:21` (`weighted_sums`).
  - Estado: **abierta**. Para las correcciones que siguen a la evaluación independiente (plan, sección 28).

## U11 (L78)

Tramo `f051a68..9263e00` (L76 y U11, escalada al ítem 1): aprobada con una sugerencia.

- **S1**
  - Hallazgo: `registry._check_part` decide si comprueba `sealed_config` por la identidad `keys is LAUNCH_KEYS` y no por un valor.
  - Ubicación: `src/promolift/registry.py:459`.
  - Estado: **abierta**. Para las correcciones que siguen a la evaluación independiente (plan, sección 28).

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
  - Estado: **abierta**. Para las correcciones que siguen a la evaluación independiente (plan, sección 28).

- **S2**
  - Hallazgo: Las series de `cell_ranking` no pasan por `_none`, como las demás.
  - Ubicación: `src/promolift/figures.py:52` (los datos) y `:31` (`_none`).
  - Estado: **abierta**. Para las correcciones que siguen a la evaluación independiente (plan, sección 28).

## U17 (L80)

Tramo `dd56dc6..936200c` (la unidad de velocidad y U17, cierre del tramo): aprobada con dos sugerencias.

- **S1**
  - Hallazgo: La ayuda de `make-fixture --output` dice que una ruta relativa se toma de la carpeta del proyecto, pero se resuelve contra `$PROMOLIFT_HOME` primero.
  - Ubicación: `src/promolift/cli.py:73`.
  - Estado: **abierta**. Para las correcciones que siguen a la evaluación independiente (plan, sección 28).

- **S2**
  - Hallazgo: Un splat condicional muerto en la prueba de `--series` y `--days`.
  - Ubicación: `tests/e2e/test_cli.py:142`.
  - Estado: **abierta**. Para las correcciones que siguen a la evaluación independiente (plan, sección 28).
