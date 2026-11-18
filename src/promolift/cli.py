"""Command line of the pipeline: ``python -m promolift <command>`` (RF23, AC28, AC30, AC31; plan, section 22; D25, D27). Adapted from project 05's ``cli.py``.

``run``, ``task`` and ``replay`` call ``pipeline.run_all``, ``pipeline.run_task`` and ``pipeline.replay``: the same task list, order and functions as the Airflow DAG, so the whole
flow runs on Windows without Airflow. ``figures`` calls ``figures.write_figures`` and ``docs-sync`` calls ``reporting.replace_block`` and ``docs_sync.render_dictionary_tables``: no step is written here.

Exit codes: 0 ok (also a run with no delivery left and a replay with nothing pending), 1 a task failed, 2 wrong usage or configuration (also a task refused by the state of its run
or because another writer holds the data folder), 3 the delivery or the source was rejected by the validation. A combination that cannot do what it says is refused with 2 before
anything is written: no option is ignored in silence (AC30). Every relative path of ``--config`` and of ``make-fixture`` is taken from ``$PROMOLIFT_HOME`` or the project folder,
never from the working directory (AC31). ``main(argv)`` is the entry the tests use, in the same process.

The top-level help imports only the configuration: the pipeline (scikit-learn) is imported by the commands that run tasks. A new command is a ``commands.add_parser`` in
``build_parser`` and a branch of ``_execute``.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import traceback
from pathlib import Path

from promolift.config import DEFAULT_PROJECT_ROOT, ENV_CONFIG, ENV_HOME, load_config

EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_REJECTED = 0, 1, 2, 3
SIGNALS = ("lift", "null")
TASK_COMMANDS = ("run", "task")          # the commands whose options name tasks: only they need the pipeline's list to build the parser
SUMMARY_MD = "evaluation_summary.md"
NOTHING_WRITTEN = "No se escribió nada."
QUIET_KEYS = ("seconds", "sha256", "peak_working_set_mb", "peak_commit_mb", "memory_counter", "message")     # what a line of a task leaves out: it is in the state of the run


class _UsageError(ValueError):
    """A combination of options that cannot do what it says (before anything is written)."""


def _home() -> Path:
    home = os.environ.get(ENV_HOME)
    return Path(home).resolve() if home else DEFAULT_PROJECT_ROOT


def _common() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", type=Path, metavar="RUTA",
                        help=f"archivo de configuración (por defecto ${ENV_CONFIG} o config/pipeline.toml); una ruta relativa se toma desde ${ENV_HOME} o la carpeta del proyecto")
    common.add_argument("-v", "--verbose", action="store_true", help="muestra el detalle de cada paso y la traza de la tarea que falla")
    return common


def build_parser(task_ids: tuple[str, ...] | None = None) -> argparse.ArgumentParser:
    """The parser. `task_ids` are the choices of ``--only``, ``--from`` and ``task`` (``pipeline.TASK_IDS``); without them those options take any name and the pipeline refuses
    an unknown one (the top-level help does not import the pipeline)."""
    parser = argparse.ArgumentParser(prog="python -m promolift", description="Qué promociones venden de verdad, con la demanda que esconden los quiebres.")
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMANDO")
    common = _common()
    tasks = f" ({', '.join(task_ids)})" if task_ids else ""

    run = commands.add_parser("run", parents=[common], help="una corrida: la siguiente entrega, con las once tareas en orden", description=f"Una corrida con las tareas de pipeline.TASKS{tasks}.")
    run.add_argument("--only", nargs="+", choices=task_ids, metavar="TAREA", help="corre solo estas tareas de la corrida, en su orden")
    run.add_argument("--from", dest="start", choices=task_ids, metavar="TAREA", help="sigue la corrida desde esta tarea")
    run.add_argument("--run-key", metavar="CLAVE", help="la corrida que se continúa (con --only o --from)")

    replay = commands.add_parser("replay", parents=[common], help="corridas seguidas, una por entrega pendiente, hasta agotarlas o hasta una entrega")
    replay.add_argument("--until", metavar="ENTREGA", help="la última entrega que se corre, por su identificador (por ejemplo D2024-06-30; por defecto, todas las pendientes; una anterior a "
                                                           "la siguiente pendiente, o cualquiera si no queda ninguna, sale con 2)")

    task = commands.add_parser("task", parents=[common], help="una tarea de una corrida", description=f"Una tarea de una corrida{tasks}.")
    task.add_argument("task", choices=task_ids, metavar="TAREA")
    task.add_argument("--run-key", metavar="CLAVE", help="la corrida a la que pertenece (una nueva si se omite; una tarea desde load necesita la de una corrida que tiene su entrega: sin ella sale con 2)")

    fixture = commands.add_parser("make-fixture", help="escribe los dos Parquet sintéticos (train y eval) para las pruebas y el modo rápido")
    fixture.add_argument("output", type=Path, metavar="SALIDA_DIR", help="la carpeta donde se escriben; una ruta relativa se toma desde la carpeta del proyecto")
    fixture.add_argument("--series", type=int, default=300, help="series (por defecto 300; la configuración rápida espera 300)")
    fixture.add_argument("--seed", type=int, default=0, help="semilla de la simulación (por defecto 0)")
    fixture.add_argument("--signal", choices=SIGNALS, default="lift", help="lift: el aumento plantado por banda y grupo (control positivo); null: ninguno (control negativo)")
    fixture.add_argument("--days", type=int, default=97, help="días del calendario, los 7 últimos de la prueba (por defecto 97, el del conjunto real)")

    commands.add_parser("figures", parents=[common], help="dibuja las nueve figuras de la documentación desde los archivos del sitio verificados de la última corrida")
    docs_sync = ("copia el resumen de resultados (reports/" + SUMMARY_MD + ") en el bloque de resultados del README y escribe, desde el modelo semántico, las tablas de cada "
                 "Parquet en el diccionario de datos (docs/data-dictionary.md) si existe junto a la carpeta de figuras")
    commands.add_parser("docs-sync", parents=[common], help=docs_sync,
                        description=docs_sync[0].upper() + docs_sync[1:] + ". Un segundo uso no cambia nada; si un archivo no tiene sus dos marcadores no se escribe ninguno.")
    return parser


def _say(text: str) -> None:
    sys.stdout.write(text + "\n")


def _fail(text: str) -> None:
    sys.stderr.write(text + "\n")


class _LineFormatter(logging.Formatter):
    """One line per record: the traceback of a failed task is printed once, by ``main`` with ``-v``."""

    def formatException(self, ei) -> str:
        return ""


def _configure_logging(verbose: bool) -> None:
    """Log to the standard error from the package's own logger, one line per record, replacing the handler of an earlier call in this process (the tests make several):
    information with ``-v``, warnings and errors without it."""
    package = logging.getLogger("promolift")
    for handler in [h for h in package.handlers if getattr(h, "_promolift_cli", False)]:
        package.removeHandler(handler)
    handler = logging.StreamHandler(sys.stderr)
    handler._promolift_cli = True   # type: ignore[attr-defined]
    handler.setFormatter(_LineFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    package.addHandler(handler)
    package.setLevel(logging.INFO if verbose else logging.WARNING)


def _check_run(args: argparse.Namespace, task_ids: tuple[str, ...]) -> None:
    """The combinations of ``run`` that cannot do what they say, refused before a state file is created (plan, section 22)."""
    if args.only and args.start is not None:
        raise _UsageError("--only y --from no se combinan: una elige las tareas y la otra desde cuál se sigue. " + NOTHING_WRITTEN)
    if args.run_key and not args.only and args.start is None:
        raise _UsageError("--run-key continúa una corrida y necesita --only o --from para decir qué tareas corren; una corrida nueva no lleva clave. " + NOTHING_WRITTEN)
    first = next(t for t in task_ids if t in args.only) if args.only else (args.start or task_ids[0])
    if args.run_key is None and first != task_ids[0]:
        raise _UsageError(f"una corrida nueva empieza por {task_ids[0]} y esta empezaría por {first}: para seguir una corrida que ya empezó, dé su clave con --run-key. " + NOTHING_WRITTEN)


def _brief(result: dict) -> str:
    return ", ".join(f"{k}={v}" for k, v in result.items() if k not in QUIET_KEYS and v is not None and not isinstance(v, (dict, list)))


def _show_run(outcome: list[dict]) -> None:
    for step in outcome:
        result = step["result"]
        if step["task"] == "deliver" and result.get("delivered"):
            _say(f"entrega {result['delivery_id']} (cálculo al {result['as_of']})")
        _say(f"{step['task']:<18} {result.get('seconds', 0):>8.1f} s  {_brief(result)}")
    if outcome and not outcome[-1]["result"].get("delivered", True):
        _say(outcome[-1]["result"]["message"])


def _make_fixture(args: argparse.Namespace) -> int:
    root = DEFAULT_PROJECT_ROOT
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))   # the generator lives with the tests, next to src/
    try:
        from tests.fixtures.make_fixture import make_fixture
    except ModuleNotFoundError as error:
        if error.name not in ("tests", "tests.fixtures", "tests.fixtures.make_fixture"):
            raise   # a module the generator itself needs is missing: a real error, not an absent tests tree
        raise _UsageError(f"el generador de datos sintéticos vive en tests/fixtures/ de la carpeta del proyecto ({root}) y no está: make-fixture solo corre desde una copia completa. "
                          + NOTHING_WRITTEN) from error

    home = _home()
    output = args.output if args.output.is_absolute() else Path(os.path.normpath(home / args.output))   # like the paths of the configuration: never the working directory
    if not args.output.is_absolute() and home not in output.parents:
        raise _UsageError(f"{args.output} sale de la carpeta del proyecto ({home}): dé una ruta absoluta si el destino está fuera a propósito. " + NOTHING_WRITTEN)
    missing = [folder for folder in reversed(output.parents) if not folder.exists()]    # a clean clone has no data/quick/ yet: the folders this call makes, which it takes back
    output.mkdir(parents=True, exist_ok=True)                                            # if the generator refuses its arguments (nothing is left behind)
    try:
        truth = make_fixture(output, series=args.series, seed=args.seed, signal=args.signal, days=args.days)
    except BaseException:
        for folder in (output, *reversed(missing)):
            try:
                folder.rmdir()
            except OSError:
                break
        raise
    _say(f"escribí {truth.train_path} y {truth.eval_path}: {args.series} series, {args.days} días, semilla {args.seed}, señal {args.signal}")
    return EXIT_OK


def _docs_sync(cfg) -> int:
    """The results block of the README from the summary and, when ``docs/data-dictionary.md`` is next to the figures folder, its generated tables from the semantic model.

    Check everything, then write: each file is read once, its markers are checked and its new text is computed (the dictionary's tables rendered) before any file is written, so a
    file without its markers or a column type the dictionary cannot name leaves every file as it was (exit 2)."""
    from promolift.dashboard.semantic_model import MODEL
    from promolift.docs_sync import COLUMNS_END, COLUMNS_START, dictionary_path, render_dictionary_tables
    from promolift.files import write_atomic
    from promolift.reporting import RESULTS_END, RESULTS_START, replace_block

    summary, readme = Path(cfg.paths.reports_dir) / SUMMARY_MD, Path(cfg.paths.readme)
    if not readme.is_file():   # the quick mode has no README of its own
        raise _UsageError(f"la configuración no tiene un README que sincronizar: {readme} no existe (el modo rápido no lo tiene). {NOTHING_WRITTEN}")
    if not summary.is_file():
        raise _UsageError(f"falta el resumen de resultados {summary}: lo escribe la tarea report. {NOTHING_WRITTEN}")
    dictionary = dictionary_path(Path(cfg.paths.figures_dir))
    blocks = [(readme, RESULTS_START, RESULTS_END, lambda: summary.read_text(encoding="utf-8"))]
    if dictionary.is_file():
        blocks.append((dictionary, COLUMNS_START, COLUMNS_END, lambda: render_dictionary_tables(MODEL)))
    planned: list[tuple[Path, str, str]] = []   # (file, its text as read, its new text)
    try:
        for path, start, end, content in blocks:
            text = path.read_text(encoding="utf-8")
            planned.append((path, text, replace_block(text, path.name, start, end, content())))
    except ValueError as error:   # a file without its two markers, once each and in order, or a type the dictionary cannot name: nothing was written
        raise _UsageError(f"{error}. {NOTHING_WRITTEN}") from error
    for path, text, new in planned:
        if new != text:
            write_atomic(path, new)
    for path, text, new in planned:
        _say(f"{path.name} actualizado" if new != text else f"{path.name} ya estaba al día")
    return EXIT_OK


def _figures(cfg) -> int:
    from promolift.figures import write_figures   # matplotlib: only the command that draws pays for it

    try:
        paths = write_figures(cfg.paths.site_dir, cfg.paths.figures_dir)
    except FileNotFoundError as error:   # no site files, or a folder that is not one export (SiteSetError): nothing was written
        raise _UsageError(f"las figuras se dibujan solo desde los archivos del sitio de una misma exportación: {error}. {NOTHING_WRITTEN}") from error
    for path in paths:
        _say(f"escribí {path}")
    return EXIT_OK


def _execute(args: argparse.Namespace, cfg, pipeline) -> int:
    if args.command == "docs-sync":
        return _docs_sync(cfg)
    if args.command == "figures":
        return _figures(cfg)
    if args.command == "task":
        result = pipeline.run_task(args.task, args.run_key, cfg)
        _say(f"{args.task}: {_brief(result)}")
        return EXIT_OK
    if args.command == "replay":
        runs = pipeline.replay(cfg, args.until)
        for outcome in runs:
            _show_run(outcome)
        _say(f"{len(runs)} corrida" + ("" if len(runs) == 1 else "s") if runs else "no hay entregas pendientes: las del plan ya están cargadas")
        return EXIT_OK
    _show_run(pipeline.run_all(cfg, only=args.only, start=args.start, run_key=args.run_key))
    return EXIT_OK


def _command_of(argv: list[str]) -> str | None:
    return next((a for a in argv if not a.startswith("-")), None)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    task_ids = None
    if _command_of(argv) in TASK_COMMANDS:
        from promolift.pipeline import TASK_IDS

        task_ids = TASK_IDS
    try:
        args = build_parser(task_ids).parse_args(argv)
    except SystemExit as stop:   # argparse exits on a wrong option (2) and on --help (0)
        return int(stop.code or 0)
    _configure_logging(getattr(args, "verbose", False))
    if args.command == "make-fixture":
        try:
            return _make_fixture(args)
        except (ValueError, OSError) as error:   # a count or a seed the generator refuses, or a path that cannot be written
            _fail(f"error: {error}")
            return EXIT_USAGE
    try:
        if args.command == "run":
            _check_run(args, task_ids)
        cfg = load_config(args.config)
    except (ValueError, FileNotFoundError) as error:   # a wrong option or configuration: nothing has been written
        _fail(f"error: {error}")
        return EXIT_USAGE
    from promolift import pipeline
    from promolift.validate import ValidationError

    try:
        return _execute(args, cfg, pipeline)
    except ValidationError as error:
        _fail(f"rechazada: {error}")
        return EXIT_REJECTED
    except (_UsageError, pipeline.UsageError, pipeline.RunRefusedError) as error:   # refused before anything ran or was written
        _fail(f"error: {error}")
        return getattr(error, "exit_code", EXIT_USAGE)
    except Exception as error:   # a task failed: its record is in the state of the run
        _fail(f"falló: {type(error).__name__}: {error}")
        if getattr(args, "verbose", False):
            _fail("".join(traceback.format_exception(error)).rstrip())
        return EXIT_FAILED


__all__ = ["EXIT_FAILED", "EXIT_OK", "EXIT_REJECTED", "EXIT_USAGE", "build_parser", "main"]
