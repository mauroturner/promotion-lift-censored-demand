"""A copy of the issued week of the test for the tests that evaluate it (U11)."""

from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace

from promolift.cube import open_loaded_cube
from promolift.registry import sealed_view
from promolift.warehouse import connect


def clone(source_folder: Path, destination: Path, launch_config, train: str, eval_: str, **sections) -> SimpleNamespace:
    """Copy a folder of the issued week to `destination` and open it: ``cfg`` (pointed at the copy), ``view``, ``conn``, ``db``, ``seal`` and ``cube``."""
    shutil.copytree(source_folder, destination)
    cfg = launch_config(destination, **sections)
    return SimpleNamespace(cfg=cfg, view=sealed_view(cfg, train, eval_), conn=connect(destination / "w.sqlite"), db=destination / "w.sqlite", seal=cfg.paths.seal,
                           cube=open_loaded_cube(destination / "interim"))
