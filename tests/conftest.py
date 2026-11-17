"""Shared fixtures, the automatic skipping of the real_data and docker marks and the fast suite's time limit (plan, section 24.1).

The fixtures of the units that come later (the synthetic Parquet files, the loaded warehouses, the launch, the sealed history, the site
files, the rendered design and the figures) are added by the unit that writes the code they need.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REAL_TRAIN = PROJECT_ROOT / "data" / "raw" / "train.parquet"
REAL_EVAL = PROJECT_ROOT / "data" / "raw" / "eval.parquet"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip, instead of failing, the tests whose external requirement is missing (they are not selected by default either)."""
    skips = {
        "real_data": (not (REAL_TRAIN.exists() and REAL_EVAL.exists()), "the real Parquet files are not in data/raw/"),
        "docker": (shutil.which("docker") is None, "docker is not installed"),
    }
    for item in items:
        for mark, (missing, reason) in skips.items():
            if mark in item.keywords and missing:
                item.add_marker(pytest.mark.skip(reason=reason))


@pytest.fixture(scope="session")
def project_root() -> Path:
    return PROJECT_ROOT


@pytest.fixture(scope="session")
def cfg():
    """The default configuration, loaded once (it is immutable)."""
    from promolift.config import load_config

    return load_config(PROJECT_ROOT / "config" / "pipeline.toml")


@pytest.fixture(scope="session")
def quick_cfg():
    """The quick-mode configuration, loaded once."""
    from promolift.config import load_config

    return load_config(PROJECT_ROOT / "config" / "pipeline.quick.toml")
