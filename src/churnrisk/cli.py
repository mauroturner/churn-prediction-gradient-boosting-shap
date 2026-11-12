"""Command line of the pipeline: ``python -m churnrisk <command>`` (RF28, AC33, AC34; plan, section 22; D82). Adapted from project 03's
``cli.py``.

``run``, ``task`` and ``replay`` call the tasks of ``pipeline.TASKS`` (``run_all``, ``run_task``, ``replay``): the same list, order and
functions as the Airflow DAG, so the whole flow runs on Windows without Airflow. No step is written here.

Exit codes: 0 ok (also a run with no delivery left and a replay with nothing pending), 1 a task failed, 2 wrong usage or configuration (also
a task refused by the state of its run or because another writer holds the data folder), 3 the delivery or the source was rejected by the
validation. A combination that cannot do what it says is refused with 2 before anything is written; no option is ignored in silence (AC33).
Every relative path of ``--config`` and of ``make-fixture`` is taken from ``$CHURNRISK_HOME`` or the project folder, never from the working
directory (D32). ``main(argv)`` is the entry the tests use, in the same process.

The top-level help imports only the configuration: the pipeline (scikit-learn, SHAP) is imported by the commands that run tasks.
"""

from __future__ import annotations

import argparse
import logging
import sys
import traceback
from pathlib import Path

from churnrisk.config import DEFAULT_PROJECT_ROOT, ENV_CONFIG, ENV_HOME, load_config

EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_REJECTED = 0, 1, 2, 3
SIGNALS = ("none", "irregular_gaps", "rfm_only")
TASK_COMMANDS = ("run", "task")          # the commands whose options name tasks: only they need the list of the pipeline to build the parser
SUMMARY_MD = "evaluation_summary.md"


class _UsageError(ValueError):
    """A combination of options that cannot do what it says (before anything is written)."""


def _home() -> Path:
    import os

    home = os.environ.get(ENV_HOME)
    return Path(home).resolve() if home else DEFAULT_PROJECT_ROOT


def _common() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", type=Path, metavar="RUTA",
                        help=f"archivo de configuración (por defecto ${ENV_CONFIG} o config/pipeline.toml); una ruta relativa se toma desde ${ENV_HOME} o la carpeta del proyecto")
    common.add_argument("-v", "--verbose", action="store_true", help="muestra el detalle de cada paso y la traza de la tarea que falla")
    return common


def build_parser(task_ids: tuple[str, ...] | None = None) -> argparse.ArgumentParser:
    """The parser. `task_ids` are the choices of ``--only``, ``--from`` and ``task`` (``pipeline.TASK_IDS``); without them those options take
    any name and the pipeline refuses an unknown one (the help of the top level does not import the pipeline)."""
    parser = argparse.ArgumentParser(prog="python -m churnrisk", description="Clientes que están por irse, antes de que se vayan.")
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMANDO")
    common = _common()
    tasks = f" ({', '.join(task_ids)})" if task_ids else ""

    run = commands.add_parser("run", parents=[common], help="una corrida: la siguiente entrega, con las doce tareas en orden",
                              description=f"Una corrida con las tareas de pipeline.TASKS{tasks}.")
    run.add_argument("--only", nargs="+", choices=task_ids, metavar="TAREA", help="corre solo estas tareas de la corrida, en su orden")
    run.add_argument("--from", dest="start", choices=task_ids, metavar="TAREA", help="sigue la corrida desde esta tarea")
    run.add_argument("--run-key", metavar="CLAVE", help="la corrida que se continúa (con --only o --from)")

    replay = commands.add_parser("replay", parents=[common], help="corridas seguidas, una por entrega pendiente, hasta agotarlas o hasta una entrega")
    replay.add_argument("--until", metavar="ENTREGA", help="la última entrega que se corre, por su identificador (por ejemplo M2011-08; por defecto, todas las pendientes)")

    task = commands.add_parser("task", parents=[common], help="una tarea de una corrida", description=f"Una tarea de una corrida{tasks}.")
    task.add_argument("task", choices=task_ids, metavar="TAREA")
    task.add_argument("--run-key", metavar="CLAVE", help="la corrida a la que pertenece (una nueva si se omite)")

    fixture = commands.add_parser("make-fixture", help="escribe un libro sintético para las pruebas y el modo rápido")
    fixture.add_argument("output", type=Path, metavar="SALIDA.zip", help="dónde se escribe; una ruta relativa se toma desde la carpeta del proyecto")
    fixture.add_argument("--customers", type=int, default=1500, help="clientes simulados (por defecto 1500)")
    fixture.add_argument("--seed", type=int, default=0, help="semilla de la simulación (por defecto 0)")
    fixture.add_argument("--signal", choices=SIGNALS, default="none",
                         help="irregular_gaps: la baja depende de lo irregular de las compras (control positivo); rfm_only: solo de RFM (control negativo)")

    commands.add_parser("figures", parents=[common], help="dibuja las siete figuras de la documentación desde los archivos del sitio verificados de la última corrida")
    commands.add_parser("docs-sync", parents=[common], help="copia el resumen de resultados (reports/evaluation_summary.md) en el bloque de resultados del README")
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
    """Log to the standard error from the package's own logger, one line per record, replacing the handler of an earlier call in this
    process (the tests make several): information with ``-v``, warnings and errors without it."""
    package = logging.getLogger("churnrisk")
    for handler in [h for h in package.handlers if getattr(h, "_churnrisk_cli", False)]:
        package.removeHandler(handler)
    handler = logging.StreamHandler(sys.stderr)
    handler._churnrisk_cli = True   # type: ignore[attr-defined]
    handler.setFormatter(_LineFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    package.addHandler(handler)
    package.setLevel(logging.INFO if verbose else logging.WARNING)


def _check_run(args: argparse.Namespace, task_ids: tuple[str, ...]) -> None:
    """The combinations of ``run`` that cannot do what they say, refused before a state file is created (plan, section 22)."""
    if args.only and args.start is not None:
        raise _UsageError("--only y --from no se combinan: elija las tareas o desde cuál seguir. No se escribió nada.")
    if args.run_key and not args.only and args.start is None:
        raise _UsageError("--run-key necesita --only o --from: una corrida completa nueva elige su propia clave. No se escribió nada.")
    first = next(t for t in task_ids if t in args.only) if args.only else (args.start or task_ids[0])
    if args.run_key is None and first != task_ids[0]:
        raise _UsageError(f"una corrida nueva empieza por {task_ids[0]}, no por {first}: indique con --run-key la corrida que continúa (sin ella no hay "
                          "resultado de las tareas anteriores). No se escribió nada.")


def _brief(result: dict) -> str:
    keys = ("delivered", "delivery_id", "lines", "built", "rows", "customers_scored", "contacts", "seal_state", "test", "evaluation_status", "run_status")
    return ", ".join(f"{k}={result[k]}" for k in keys if k in result and not isinstance(result[k], (dict, list)))


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
        raise _UsageError(f"make-fixture usa el generador de tests/fixtures/make_fixture.py, y {root} no tiene la carpeta tests (por ejemplo, la imagen de "
                          "Airflow solo trae las dependencias): córralo desde un clon completo del proyecto. No se escribió nada.") from error

    output = args.output if args.output.is_absolute() else _home() / args.output   # like the paths of the configuration: never the working directory
    truth = make_fixture(output, n_customers=args.customers, seed=args.seed, signal=args.signal)
    _say(f"escribí {truth.path}: {truth.canonical_lines} líneas de {truth.n_customers} clientes simulados (semilla {args.seed}, señal {args.signal})")
    return EXIT_OK


def _docs_sync(cfg) -> int:
    from churnrisk.reporting import RESULTS_END, RESULTS_START, sync_block

    summary = Path(cfg.paths.reports_dir) / SUMMARY_MD
    readme = Path(cfg.paths.readme)
    if not readme.is_file():   # the quick mode has no README of its own (project 03, D90)
        raise _UsageError(f"docs-sync copia el resumen de resultados en el README de la configuración, {readme}, y ese archivo no existe: el modo rápido no "
                          f"tiene README, y su resumen queda en {summary}. No se escribió nada.")
    if not summary.is_file():
        raise _UsageError(f"no existe {summary}: corra la tarea report antes de docs-sync. No se escribió nada.")
    changed = sync_block(readme, RESULTS_START, RESULTS_END, summary.read_text(encoding="utf-8"))
    _say(f"{readme.name} actualizado" if changed else f"{readme.name} ya estaba al día")
    return EXIT_OK


def _figures(cfg) -> int:
    from churnrisk.figures import make_figures   # matplotlib: only the command that draws pays for it

    try:
        paths = make_figures(cfg.paths.site_dir, cfg.paths.figures_dir)
    except FileNotFoundError as error:   # no site files, or a folder that is not one export (SiteSetError): nothing was written
        raise _UsageError(f"{error}. No se escribió ninguna figura.") from error
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
        _say(("1 corrida" if len(runs) == 1 else f"{len(runs)} corridas") if runs else "No hay entregas pendientes: nada que correr.")
        return EXIT_OK
    _show_run(pipeline.run_all(cfg, only=args.only, start=args.start, run_key=args.run_key))
    return EXIT_OK


def _command_of(argv: list[str]) -> str | None:
    return next((a for a in argv if not a.startswith("-")), None)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    task_ids = None
    if _command_of(argv) in TASK_COMMANDS:
        from churnrisk.pipeline import TASK_IDS

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
    from churnrisk import pipeline
    from churnrisk.validate import ValidationError

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
