# Runbook: qué hacer cuando algo no sale como se esperaba

Todos los comandos son para Windows (PowerShell), dentro de la carpeta `06-Ecommerce-Promotion-Lift/` y con el entorno del proyecto. El paquete no está instalado en el entorno: una vez por sesión,

```powershell
$env:PYTHONPATH = "src"
.venv\Scripts\python -m promolift --help
```

**Cómo se escribió este documento.** Está escrito desde lo que dicen el código, las pruebas y el registro de decisiones, con los mensajes tal como los emite el código (las rutas, las claves de corrida y el nombre del equipo se abrevian); **no se corrió el runbook sobre una copia del proyecto**, como sí se hizo con el del proyecto 05. Cada entrada que el código cita (R1 a R8, R10 a R12) está en una prueba que comprueba que existe y que trata de lo que el mensaje dice (`tests/docs/test_docs.py::test_the_runbook_has_r1_to_r12_and_every_reference_of_the_code_points_to_one`). La evaluación independiente probará lo que aquí se describe, y esta página se sincroniza con lo que encuentre.

Códigos de salida de la CLI (`src/promolift/cli.py`): `0` terminó bien (también una corrida sin entrega pendiente y un `replay` sin pendientes), `1` falló una tarea, `2` uso o configuración incorrectos (también una tarea rechazada por el estado de su corrida o porque otro proceso tiene la carpeta de datos), `3` la fuente o la entrega fueron rechazadas por la validación. Cada corrida deja su estado en `data\interim\runs\<clave>.json`, tarea por tarea, con sus tiempos, sus picos de memoria con el contador (`PeakWorkingSetSize` en Windows) y, si falló, la traza (con `-v` también sale por la pantalla).

Tres principios valen para todo el documento:

- **Un rechazo de la fuente no deja nada a medias.** Una fuente que no pasa V01-V07 escribe su informe de validación (`reports\validation\latest.md` y `latest.json`, con una copia en `history\`) y el estado de la corrida y nada más: ni almacén, ni Parquet, ni sello. Si algo falla después de `load`, la corrida queda `failed` y se retoma con su misma clave: `python -m promolift run --run-key <clave> --from <tarea>`.
- **Una corrida cerrada no se vuelve a abrir.** Cualquier tarea de una corrida `ok` o `no_delivery` se rechaza con código `2` antes de escribir nada: la entrega siguiente es otra corrida. Una tarea desde `load` sin `--run-key` también sale con `2` sin escribir nada, ni su archivo de estado.
- **El sello no se toca.** `reports\model_seal.json` guarda la configuración del lanzamiento y el primer resultado de la prueba; ninguna tarea lo reescribe con otros valores, y una evaluación con otra configuración se guarda aparte, como posterior al sello (D17). Nada de este documento pide editarlo a mano.

## R1 Falta un Parquet, o no tiene el tamaño o la huella fijados

**Síntoma.** Cualquier corrida con la configuración por defecto sale con código `3`: `rechazada: la validación de <corrida> rechazó la corrida: fallan las reglas bloqueantes V01`, con el motivo en `reports\validation\latest.md` y el texto «runbook R1: docs/runbook.md»: el archivo falta, pesa otra cosa o tiene otro SHA-256.

**Qué significa.** El flujo no descarga nada (D02): exige que `[source] train_path` y `eval_path` (`data\raw\train.parquet` y `data\raw\eval.parquet`) existan y sean los dos archivos que se evaluaron: `train.parquet` de 106.436.287 bytes y SHA-256 `6706832db892bbae4969c19d87e07975d2543d2ba7d7d4756360654785de5a3d`, y `eval.parquet` de 8.440.124 bytes y SHA-256 `1b118840664280c6b88bffc84c80ee1f54c05d911e354b7599e5da10995e960e`. `data/raw/` no se versiona, así que un clon nuevo no los tiene. Nada se leyó de un archivo que no cumple, y el almacén, el modelo, el sello y las salidas publicadas no cambian.

**Qué hacer.**

1. Bajarlos con el script de la investigación, que los fija al commit `c374e859` del conjunto y comprueba tamaño y SHA-256 antes de aceptarlos:

   ```powershell
   .venv\Scripts\python research\s00_download.py
   ```

2. Comprobar a mano, si hace falta:

   ```powershell
   (Get-Item data\raw\train.parquet).Length
   (Get-FileHash data\raw\train.parquet -Algorithm SHA256).Hash
   ```

3. Si un archivo está cortado o dañado, volver a bajarlo. Si es otra versión legítima del conjunto, **no se cambia la huella sin más**: los criterios, los recuentos y el sello son de estos archivos. Es un análisis nuevo (R9).
4. En modo rápido no hay huella fijada: la primera que ve la guarda `data\quick\source.lock.json` y las siguientes deben coincidir. El mismo mensaje en modo rápido quiere decir que se cambió el accesorio; se vuelve a escribir con `make-fixture` y la misma semilla.

## R2 Una regla de lectura falló

**Síntoma.** La corrida sale con código `3` y V01 pasa, pero otra regla de la fuente falla (V02 a V07, «runbook R2: docs/runbook.md»): en `reports\validation\latest.md`, la tabla de reglas marca «falla» y dice dónde, con claves y recuentos y nunca con un valor medido. Las reglas siguientes quedan «no evaluadas».

**Qué significa.** El lector es estricto (D05): trata los Parquet como no confiables y rechaza, sin corregir, lo que no cumple el esquema exacto de 19 columnas (V02), los topes de bytes, filas y grupos de filas (V03), las listas horarias de largo 24 sin nulos ni NaN, la venta finita en el rango y el estado en {0, 1} (V04), la clave (tienda, producto, día) única y las fechas dentro de la ventana de cada archivo (V05), la jerarquía sin padres múltiples (V06) y todos los días de cada serie (V07). Con las huellas de R1 correctas, los archivos reales las cumplen todas; si una falla con ellos, algo los cambió en el camino, o se está usando otra copia.

**Qué hacer.** No editar un archivo para que pase. Comprobar que son los de R1 (mismas huellas); si lo son y la regla igual falla, es un defecto del lector: guardar el informe y abrir una decisión nueva. Con otros archivos, es R1 o R9.

## R3 Entrega rechazada, o `load` rechazado por la validación

**Síntoma.** La tarea `validate` de una corrida sale con código `3` (fallan las reglas bloqueantes V10 a V15), o `load` se niega con código `2`: «la validación de la corrida <clave> rechazó su entrega (V12): load no carga una entrega rechazada (docs/runbook.md, R3)», o dice que la corrida no validó su entrega.

**Qué significa.** Una entrega solo se carga si la validación de su misma corrida aprobó sus reglas bloqueantes: es la siguiente del plan (V10), sus series-días están dentro de su período (V11) y no están ya en el almacén (V12), sus archivos son los del manifiesto (V13), las sumas de su archivo de días son las del cubo (V14) y no trae ninguna columna prohibida (V15). Una entrega rechazada pasa a cuarentena, la corrida queda `rejected` y el almacén, los tensores, los Parquet, el HTML, la exportación del sitio y el sello quedan como estaban (RF07). Una entrega rechazada queda en el manifiesto de entregas como pendiente y la próxima corrida la repite. No se pudo provocar una entrega rechazada de verdad: las entregas salen del mismo archivo que ya pasó V01-V07; lo cubren `tests/contract/test_validate.py` y `tests/integration/test_pipeline.py`.

**Qué hacer.**

1. Leer `reports\validation\latest.md`: dice qué regla falló y con cuántas series-días.
2. Si la causa es la entrega (un archivo de `data
aw\deliveries\` que no es el del manifiesto), no se edita ni el archivo ni el manifiesto a mano: la entrega queda pendiente y la próxima corrida la vuelve a intentar; si el archivo no es el que el manifiesto dice, es R11.
3. Retomar la corrida con su clave desde `validate`: `python -m promolift run --run-key <clave> --from validate`.

## R4 Entregas fuera de orden o faltantes

**Síntoma.** Un mensaje del flujo nombra la entrega: «la entrega D2024-06-28 está cargada pero la anterior, D2024-06-27, no lo está (runbook R4)», «el manifiesto trae la entrega … que no está en el plan», «ya está cargada por la corrida <clave> y el manifiesto no la marca cargada: retome esa corrida (python -m promolift run --run-key <clave> --from <tarea>)», o «ya se publicó con otro contenido; no se publica de nuevo».

**Qué significa.** El plan es fijo: el lanzamiento `L2024-06-25`, las siete diarias `D2024-06-26` a `D2024-07-02` y el cierre `C2024-07-03` (D18). La siguiente entrega pendiente es siempre la primera del plan que no está cargada: nunca se salta una, el orden se comprueba (V10) y una entrega ya cargada no se reemplaza ni se carga dos veces. Republicar la misma entrega con el mismo contenido no cambia nada; con otro contenido, se rechaza. `replay --until <entrega>` sale con 2 si esa entrega ya está cargada, haya o no pendientes.

**Qué hacer.**

1. Ver cuál es la siguiente: `python -m promolift run` corre la siguiente pendiente y dice cuál es (`replay --until` la nombra).
2. Si una corrida quedó a medias (`failed`), retomarla con su clave: `python -m promolift run --run-key <clave> --from <tarea>`; no se abre otra corrida para la misma entrega.
3. Si el manifiesto de entregas (`data
aw\deliveries\manifest.json`) no coincide con el plan o con el contenido de los archivos, no se edita: se reconstruye desde cero (R11).

## R5 La trampa de fuga detuvo el lanzamiento, o el lanzamiento no puede ajustar

**Síntoma.** La tarea `fit_model` del lanzamiento falla con un `LaunchError` y no escribe nada. El mensaje de la trampa (M01) dice que el error por serie del método elegido en V1 es menor que `leak_tripwire_ratio` (0,5) por el de la media simple: «una mejora real sobre ella ronda 0,85 veces (D19). El lanzamiento se detuvo y no escribió nada (docs/runbook.md, R5)». Otros mensajes de la misma entrada: «no hay con qué estimar un efecto», «el error de la recuperación no se puede juzgar con tan pocos» (M06: menos de `min_masked_days` series-días enmascarables), «el cubo no tiene los N días del lanzamiento» y M04 (un aumento, un contrafactual o un pronóstico no finito).

**Qué significa.** La trampa es la defensa contra una fuga que nadie previó (D19): `sale_amount` contiene la venta de las horas que la censura sintética oculta, de modo que un método que lo lea acierta casi siempre en la simulación y nunca en un quiebre real. La demostración (`fact_leakage`) mide en V2 una recuperación así: WAPE por serie de 1,4 · 10⁻⁸ frente a 31,57 % del método elegido. Con el método elegido en el real (R2, κ = 0,25), la razón con R1 es 0,851: la trampa no se activa. Si se activa, alguna entrada nueva trae el objetivo.

**Qué hacer.**

1. No aflojar `leak_tripwire_ratio` para que pase. Buscar qué columna llegó a una entrada de la recuperación: `tests/unit/test_inputs.py::test_forbidden_columns_cannot_reach_any_input` y `::test_model_code_never_names_a_forbidden_column` dicen cuáles están prohibidas (`schema.FORBIDDEN_COLUMNS`).
2. Para los demás mensajes, el cubo del lanzamiento tiene que tener los 90 días: volver a la corrida con `python -m promolift run --run-key <clave> --from load`, o a R12 si el cubo no coincide con su manifiesto.
3. Con los datos reales, M06 y M04 no se activaron en la corrida de U19.

## R6 El artefacto no coincide con su huella

**Síntoma.** Una tarea que usa el modelo falla con un mensaje M03 «(docs/runbook.md, R6)»: «no hay un artefacto legible en launch.npz», «pesa N bytes, más que el tope», «no coincide con la huella registrada», «guarda objetos de Python», «no tiene los arreglos del modelo», «el método elegido es r3 y el registro no tiene la huella de su r3.pkl», «la versión N del modelo no está registrada» o, en la evaluación, «el lanzamiento que se reconstruye con el artefacto no da los aumentos que el sello guardó».

**Qué significa.** El artefacto (`data\models\launch.npz`, un zip de arreglos numéricos sin objetos de Python) y `r3.pkl` (R3, que se guarda siempre que es candidato, D20) se leen solo si su tamaño y su SHA-256 coinciden con los del registro de modelos, y el `.npz` se lee con `allow_pickle=False`. Un archivo cambiado, cortado, de otra corrida o con un objeto de Python se rechaza antes de leerlo: nunca se deserializa nada que no coincida. `data/models/` no se versiona; el sello (`artifact_sha256` y `r3_sha256`) sí.

**Qué hacer.**

1. No editar el registro ni copiar un `.npz` de otro lugar para que coincida.
2. Si el archivo se dañó, la huella del sello dice cuál era (`reports\model_seal.json`, `launch.artifact_sha256`): el mismo lanzamiento con la misma configuración reproduce el mismo `.npz` byte a byte (D20) y el sello lo comprueba. Reconstruir con R11.
3. Si el sello no coincide con un lanzamiento reconstruido, es R7.

## R7 La evaluación no reproduce el sello, o no hay sello

**Síntoma.** Un mensaje M05 o del sello «(docs/runbook.md, R7)»: «M05: la configuración es la sellada pero el lanzamiento no la reproduce: …», «no hay sello: el lanzamiento lo escribe antes de que se evalúe la prueba, y no se evalúa sin él», «el criterio C0X del sello no se reconstruye desde sus cifras: lo sellado no se toma», «lo que consta en el sello no es lo que esta corrida escribió: otra escritura lo cambió», «se evalúa lo emitido y no otra cosa» (cuando `daily_cell` dice otra cosa que el sello) o «las variantes se calculan después de la parte del lanzamiento del sello, que no está escrita».

**Qué significa.** El sello tiene dos partes de creación exclusiva (D17): el lanzamiento y la prueba. La huella de la configuración (`config_sha256`) cubre cada clave que cambia un valor sellado; con la sellada, una repetición debe dar los mismos valores (a 6 decimales, menos las claves de corrida, los instantes y las huellas del modelo); con otra configuración, todo se guarda aparte como `post_seal`; y una evaluación de la prueba con otra configuración mientras el sello no tiene la prueba se rechaza antes de escribir. El estado de lo ya sellado es `sealed`, y `reports\evaluation_summary.md` lo dice («Estado: sealed»).

**Qué hacer.**

1. Para ver qué difiere, leer el mensaje: nombra hasta seis valores. Si dice que la configuración es la sellada y algo no se reproduce, algo cambió en el código o en los datos: es un defecto, no un análisis nuevo.
2. Si se quiso cambiar una clave de la configuración, es un análisis posterior al sello y se hace con otra configuración (R9); no se vuelve a evaluar la prueba.
3. Nunca borrar `reports\model_seal.json` para «volver a sellar»: la prueba se leyó una vez (D17).

## R8 El bloqueo de un solo escritor y `database is locked`

**Síntoma.** Un comando sale con código `2` y «Otro proceso escribe esta carpeta de datos: `python -m promolift run` (corrida …), proceso N en <equipo>, desde …. Espere a que termine y vuelva a correr; con Airflow, detenga el planificador antes de usar `airflow dags test` (docs/runbook.md, R8). No se escribió nada.» Variantes: «Un proceso de otro equipo o contenedor tiene esta carpeta de datos», «El bloqueo … quedó de un proceso que ya no está en marcha» (también con el número reusado por otro proceso), «Otro hilo de este mismo proceso escribe esta carpeta de datos», «existe pero no se puede leer quién lo tiene». O, de SQLite, `database is locked` después de 30 s (`BUSY_TIMEOUT_MS`) de espera.

**Qué significa.** Un proceso escribe una carpeta de datos a la vez (D26): cada tarea toma el bloqueo `pipeline.lock` de la carpeta de datos con un archivo creado en exclusiva, y lo suelta al terminar sin levantar nunca una excepción. Un segundo escritor se rechaza con código 2 antes de escribir. El bloqueo cubre el tiempo que corre un proceso: entre dos tareas de una corrida de Airflow, que son procesos distintos, otro proceso puede tomarlo. Lo que nadie borra solo es un bloqueo que dejó un proceso muerto: lo decide una persona. Para `database is locked`: dos procesos escribieron el mismo `data\warehouse\promolift.sqlite` sin pasar por el bloqueo (por ejemplo, un script ajeno o un visor de SQLite con una transacción abierta), y el que esperó se rindió.

**Qué hacer.**

1. Esperar y volver a correr. Con Airflow, antes de usar `airflow dags test`, detener el planificador del compose.
2. Si el mensaje dice que el bloqueo quedó de un proceso que ya no está en marcha: comprobar que nada más escribe la carpeta (tampoco un contenedor que la monte: `docker compose ps`), borrar el archivo `pipeline.lock` cuya ruta dice el mensaje y, si esa corrida quedó a medias, retomarla con `python -m promolift run --run-key <corrida> --from <tarea>`.
3. Si el bloqueo es de otro equipo o contenedor, comprobarlo allí con los registros de la tarea antes de borrarlo.
4. Para `database is locked`, cerrar el visor o el script que tiene la base abierta y volver a correr; la base no se repara a mano.

## R9 Empezar un análisis nuevo: otras bandas, otro control, otro mínimo de series o un sello nuevo

**Síntoma.** Se quiere medir otra cosa que lo sellado: bandas con otros bordes, un control con cualquier día sin marca, otro mínimo de series por celda, otro umbral de «sin rebaja» o un efecto con otra ventana de ajuste.

**Qué significa.** Lo sellado no se cambia (D17). Un análisis con otra configuración tiene otro `config_sha256`: todo lo que se calcule queda `post_seal`, se guarda aparte del sellado y nunca lo reemplaza. El control con cualquier día sin marca ya está entre las variantes de C10 (D04). Un cambio de las bandas, del control o del mínimo de series es del dueño (plan, sección 29, ítems 3 y 4) y antes de la corrida real era un cambio de código; después, es un análisis posterior al sello con su impacto medido.

**Qué hacer.**

1. Copiar `config\pipeline.toml` a otro archivo (no se edita el original), cambiar la clave y correr con `--config <otro>.toml`. Una ruta relativa de `--config` se toma de la carpeta del proyecto, no del directorio de trabajo.
2. Registrar la decisión en `docs/decisions.md` con sus siete campos, y decir en el resultado que es posterior al sello y con qué ventana se ajustó.
3. Empezar con otro análisis completo y otro sello, de cero, es una decisión del dueño: se hace en otra carpeta del proyecto (o con otra carpeta de datos, `PROMOLIFT_HOME`), nunca borrando `reports\model_seal.json`.

## R10 Airflow no arranca, o el trabajador se queda sin memoria

**Síntoma.** `docker compose up` termina con un error de variable no definida (`${PROMOLIFT_DB_PASSWORD:?}` y los otros tres secretos), `airflow-init` sale con un código distinto de 0 y los demás servicios no arrancan, la interfaz no responde en `http://localhost:8080`, o la tarea `fit_model` o `load` muere por falta de memoria («Killed» en el registro del contenedor).

**Qué significa.** Cuatro secretos sin valor por defecto vienen del entorno (la contraseña de PostgreSQL, que también está en la cadena de conexión, la clave Fernet, el secreto de JWT y la contraseña del administrador): el compose se niega a arrancar hasta que `airflow\.env` los defina (`airflow\.env.example` dice cómo generarlos). `init.sh` tiene `set -euo pipefail`: se detiene en su primer error. La interfaz se publica solo en `127.0.0.1`. Memoria: RNF03 admite al conjunto de trabajo un pico de 12 GB, así que Docker necesita al menos 12 GB para sus contenedores; el pico medido de la repetición real es de 4.077,9 MB de `PeakWorkingSetSize` (y 5.808,7 MB de `PeakPagefileUsage`, informativo), el motor de este equipo informa 31 GiB de memoria total (`docker info`, que no es un pico de proceso) y el compose no fija `mem_limit` (D24). Sin ese margen, el trabajador muere con «Killed».

**Qué hacer.**

1. Copiar `airflow\.env.example` a `airflow\.env`, llenar los cuatro secretos como dice el archivo y, en Linux, poner `AIRFLOW_UID` (`id -u`) para que las carpetas que crean los montajes sean del usuario.
2. `docker compose build`, `docker compose up airflow-init` (si sale distinto de 0, leer su última línea: el script se detuvo ahí) y `docker compose up -d`.
3. Para el modo rápido dentro del contenedor, `PROMOLIFT_CONFIG=/opt/promolift/config/pipeline.quick.toml` y el accesorio en `data/quick/`; una ruta relativa de una configuración se toma de `/opt/promolift` (`PROMOLIFT_HOME`).
4. Si el trabajador muere por memoria, subir el límite de Docker Desktop (Settings, Resources) a por lo menos 12 GB, el tope que RNF03 admite al `PeakWorkingSetSize`, y reintentar; un rechazo de la validación (`ValidationError`, `SourceError`, `LeakageError`, `RunRefusedError`) falla sin reintentos a propósito.
5. Con `airflow dags test`, detener antes el planificador (R8): las dos formas escriben la misma carpeta de datos.

## R11 Reconstruir desde cero con el sello, o una carpeta del sitio que no verifica

**Síntoma.** Un mensaje dice que una tabla del almacén no tiene las columnas que declara su SQL: «El almacén lo creó una versión anterior: se reconstruye desde cero (docs/runbook.md, R11)»; o `figures` y la exportación se niegan («las figuras se dibujan solo desde los archivos del sitio de una misma exportación») porque `outputs\site\manifest.json` no verifica: un archivo falta, pesa otra cosa o es de otra corrida.

**Qué significa.** Los datos de trabajo (`data\interim\`, `data\warehouse\`, `data\models\`, `data\raw\deliveries\`) se reconstruyen desde los dos Parquet; lo que no se reconstruye es el sello, que se versiona, y lo que fija. Una reconstrucción con el sello compara lo que el sello fija (configuración, archivos, instantes y los diez criterios), no las claves de corrida (`tests/e2e/test_real.py::test_a_rebuild_from_the_seal_compares_what_the_seal_fixes`, AC35). La carpeta del sitio lleva su manifiesto escrito al final con el tamaño y el SHA-256 de cada archivo: un conjunto mezclado, por una falla a mitad de las escrituras, se rechaza.

**Qué hacer.**

1. Poner los Parquet en `data\raw\` (R1), mover (no borrar) `data\interim\`, `data\warehouse\` y `data\models\` a otro lugar y correr `python -m promolift replay`: reconstruye el lanzamiento, las siete entregas y el cierre. Con el mismo código y la misma configuración, el sello tiene que reproducirse (R7). No se toca `reports\model_seal.json`.
2. Para la carpeta del sitio, la tarea `export` reescribe los cinco archivos con su manifiesto al final: `python -m promolift run --run-key <clave> --from export` sobre una corrida que no esté cerrada (una corrida cerrada no se vuelve a abrir: código 2), o una reconstrucción completa; después, `python -m promolift figures`.
3. La repetición real completa tardó 876 s en este equipo (D29): conviene probar primero con el modo rápido (`--config config\pipeline.quick.toml`), que no toca nada fuera de `data\quick\`.

## R12 El cubo no coincide con su manifiesto

**Síntoma.** Un `InterimError` termina con «(runbook R12)»: «falta manifest.json en <carpeta>: el cubo de las entregas cargadas no tiene su manifiesto», «falta <archivo>, que el manifiesto nombra», «<archivo> no coincide con la huella que dice el manifiesto: es de otra escritura», «no tiene la forma ni el tipo que dice el manifiesto del cubo», «la entrega X ya está en el cubo con otro contenido: sus días ya se leyeron», «el día D ya está en la entrega Y del cubo», o «las series del almacén no son las N del cubo», o, de `load`, un `CubeStoreError`: «la entrega quedó cargada sin su cubo».

**Qué significa.** Hay dos cubos (D22): el canónico, `data\interim\canonical\<día>.{sales,stock}.npy` con su `interim_manifest.json`, y el de las entregas cargadas, `data\interim\cube\<entrega>.{sales,stock}.npy` con su `manifest.json`, que la carga llena después de confirmar la transacción de SQLite. Las tareas posteriores a `load` leen solo el segundo y comprueban la huella de cada archivo antes de usarlo; lo recuperado de una entrega está en `<entrega>.recovered.npy` con su propio manifiesto, `recovered.json`. Si la copia falla después de confirmar la carga, la entrega queda cargada en SQLite sin su cubo y ninguno de sus días se ve por el cubo hasta guardarla de nuevo (RNF06 b: un día que todavía no se entregó no se ve).

**Qué hacer.**

1. No editar un manifiesto ni copiar un `.npy` a mano.
2. Con `CubeStoreError`: el error nombra la entrega, y guardar de nuevo sus horas (`cube.store_delivery_cube`) termina el trabajo, pero ningún comando de la CLI lo hace sobre una entrega ya cargada. La evaluación independiente probará este camino; mientras tanto, reconstruir con R11.
3. Si un archivo del cubo no coincide con su manifiesto, mover la carpeta `data\interim\cube\` y volver a cargar las entregas con la reconstrucción de R11; el cubo canónico se comprueba contra `interim_manifest.json` en `fetch_source`.
