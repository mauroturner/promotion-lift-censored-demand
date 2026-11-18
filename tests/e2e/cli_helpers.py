"""Helpers of the command-line and quick-mode tests (U17): a command of the CLI run in this process, a configuration file that points a command at a copy of a pipeline state, a
clean quick clone and the fingerprint of a folder.

A clean quick clone is a folder with a copy of ``config/`` (what a clone has that the commands read; the SQL comes with the package). With ``PROMOLIFT_HOME`` on it the command line
writes under its ``data/quick/``."""

from __future__ import annotations

import contextlib
import io
import os
import shutil
from pathlib import Path
from types import SimpleNamespace

from promolift.config import ENV_CONFIG, ENV_HOME

PROJECT_ROOT = Path(__file__).resolve().parents[2]
QUICK_CONFIG = "config/pipeline.quick.toml"
SKIPPED = {".venv", ".git", "__pycache__", ".pytest_cache"}


def cli(*args: str) -> SimpleNamespace:
    """``python -m promolift <args>`` in this process (``cli.main``): its exit code and what it wrote to stdout and stderr."""
    from promolift.cli import main

    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(list(args))
    return SimpleNamespace(code=code, out=out.getvalue(), err=err.getvalue())


def write_config(state, name: str = "cli.toml") -> Path:
    """A configuration file at the root of a pipeline state (``tests/fixtures/pipeline_state``) that extends the quick one and points the sources and every folder at that state,
    with absolute paths: what ``--config`` takes to run a command over a copy of a state."""
    cfg = state.cfg
    quick = (PROJECT_ROOT / QUICK_CONFIG).as_posix()
    lines = [f'extends = "{quick}"', "", "[source]"]
    for key in ("train_path", "eval_path"):
        lines.append(f'{key} = "{Path(getattr(cfg.source, key)).as_posix()}"')
    for split in ("train", "eval"):
        lines += [f"{split}_bytes = {getattr(cfg.source, f'{split}_bytes')}", f'{split}_sha256 = "{getattr(cfg.source, f"{split}_sha256")}"']
    lines += ["", "[paths]"] + [f'{key} = "{Path(value).as_posix()}"' for key, value in vars(cfg.paths).items()]
    path = Path(state.root) / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return path


def quick_project(dest: Path) -> Path:
    """A clean quick clone at `dest`: ``config/`` and nothing else."""
    dest = Path(dest)
    shutil.copytree(PROJECT_ROOT / "config", dest / "config")
    return dest


def fingerprint(root: Path, skipped: set[str] = SKIPPED) -> dict[str, tuple[int, int]]:
    """Size and modification time of every file under `root` (the environment and the caches left out)."""
    found = {}
    for folder, names, files in os.walk(root):
        names[:] = [n for n in names if n not in skipped]
        for name in files:
            path = Path(folder) / name
            stat = path.stat()
            found[path.relative_to(root).as_posix()] = (stat.st_size, stat.st_mtime_ns)
    return found


@contextlib.contextmanager
def at_home(home: Path, cwd: Path):
    """``PROMOLIFT_HOME`` on `home`, no ``PROMOLIFT_CONFIG`` and `cwd` as the working directory, all restored afterwards."""
    saved = {k: os.environ.get(k) for k in (ENV_HOME, ENV_CONFIG)}
    before = Path.cwd()
    os.environ[ENV_HOME] = str(home)
    os.environ.pop(ENV_CONFIG, None)
    os.chdir(cwd)
    try:
        yield
    finally:
        os.chdir(before)
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
