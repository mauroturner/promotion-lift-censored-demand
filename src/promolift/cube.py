"""The canonical hours, one pair of tensors per day, and the manifest that names every canonical file (RF03, D22; plan, sections 3 and 5).

``data/interim/canonical/<date_key>.sales.npy`` holds the sale of the 24 hours of one day for every series (float32, series x 24, in the order of
``series_key``) and ``<date_key>.stock.npy`` the hourly status (int8, 1 = out of stock). They are read with ``np.load(..., mmap_mode="r",
allow_pickle=False)``: a file that holds Python objects is refused, and the SHA-256 of every file is in ``interim_manifest.json``, which is written
last: a set of files without its manifest, or a file that is not the one the manifest names, is refused by every reader (``InterimError``).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from promolift.files import atomic_path, sha256_file

INTERIM_MANIFEST = "interim_manifest.json"
INTERIM_MANIFEST_VERSION = 1
CANONICAL_DIR = "canonical"
TABLES = ("series.parquet", "series_days.parquet")
FIELDS = ("sales", "stock")
DTYPES = {"sales": np.dtype(np.float32), "stock": np.dtype(np.int8)}
TRAIN_KEY = b"promolift.train_sha256"
EVAL_KEY = b"promolift.eval_sha256"
ATTRIBUTION_KEY = b"promolift.attribution"
ATTRIBUTION = "Dingdong-Inc, FreshRetailNet-50K, Hugging Face, CC BY 4.0, commit c374e859; Wang et al. (2026), arXiv:2505.16319."

_HEX64 = re.compile(r"[0-9a-f]{64}")
_TENSOR = re.compile(rf"{CANONICAL_DIR}/([0-9]{{8}})\.(sales|stock)\.npy")


class InterimError(ValueError):
    """The canonical files are not the ones their manifest names: missing, changed, from another source, or without a manifest."""


def tensor_name(date_key: int, field: str) -> str:
    return f"{CANONICAL_DIR}/{date_key}.{field}.npy"


def write_tensor(folder: Path, date_key: int, field: str, array: np.ndarray) -> str:
    """Write one day's tensor atomically (``allow_pickle=False``) and return its SHA-256."""
    path = Path(folder) / tensor_name(date_key, field)
    with atomic_path(path) as temporary, temporary.open("wb") as handle:
        np.save(handle, np.ascontiguousarray(array, dtype=DTYPES[field]), allow_pickle=False)
    return sha256_file(path)


def write_table(folder: Path, name: str, table: pa.Table, train_sha256: str, eval_sha256: str) -> str:
    """Write a canonical table atomically with the fingerprints of the two source files in its metadata; returns its SHA-256."""
    path = Path(folder) / name
    metadata = {**(table.schema.metadata or {}), TRAIN_KEY: train_sha256.encode("ascii"), EVAL_KEY: eval_sha256.encode("ascii"),
                ATTRIBUTION_KEY: ATTRIBUTION.encode("utf-8")}
    with atomic_path(path) as temporary:
        pq.write_table(table.replace_schema_metadata(metadata), temporary)
    return sha256_file(path)


def manifest_problem(interim_dir: Path) -> tuple[str | None, dict[str, Any]]:
    """What is wrong with the canonical files of `interim_dir` (None if nothing) and the manifest document."""
    folder = Path(interim_dir)
    path = folder / INTERIM_MANIFEST
    if not path.is_file():
        return f"falta {INTERIM_MANIFEST} en {folder}: las tablas canónicas no tienen su manifiesto", {}
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        files = document["files"]
        valid = (isinstance(document, dict) and set(document) == {"version", "train_sha256", "eval_sha256", "counts", "files"}
                 and document["version"] == INTERIM_MANIFEST_VERSION and isinstance(document["counts"], dict) and isinstance(files, dict)
                 and all(isinstance(document[k], str) and _HEX64.fullmatch(document[k]) for k in ("train_sha256", "eval_sha256"))
                 and all(isinstance(v, str) and _HEX64.fullmatch(v) for v in files.values())
                 and all(name in TABLES or _TENSOR.fullmatch(name) for name in files) and set(TABLES) <= set(files))
    except (OSError, ValueError, KeyError, TypeError):
        valid = False
    if not valid:
        return f"{INTERIM_MANIFEST} no es un manifiesto válido de las tablas canónicas", {}
    for name, expected in sorted(files.items()):
        target = folder / name
        if not target.is_file():
            return f"falta {name}, que el manifiesto nombra", {}
        if sha256_file(target) != expected:
            return f"{name} no coincide con la huella que dice el manifiesto: es de otra escritura", {}
    for name in TABLES:
        try:
            metadata = pq.read_schema(folder / name).metadata or {}
        except (OSError, pa.ArrowException):
            return f"{name} no se puede leer", {}
        if metadata.get(TRAIN_KEY) != document["train_sha256"].encode("ascii") or metadata.get(EVAL_KEY) != document["eval_sha256"].encode("ascii"):
            return f"{name} no es de la fuente que dice el manifiesto", {}
    return None, document


class Cube:
    """The canonical hours of every day, read lazily as memory maps (``sales(date_key)`` and ``stock(date_key)``, each series x 24)."""

    def __init__(self, folder: Path, date_keys: np.ndarray, n_series: int) -> None:
        self.folder = Path(folder)
        self.date_keys = date_keys
        self.n_series = n_series
        self._known = set(date_keys.tolist())

    def __contains__(self, date_key: object) -> bool:
        return date_key in self._known

    def _load(self, date_key: int, field: str) -> np.memmap:
        if date_key not in self._known:
            raise KeyError(f"el cubo no tiene el día {date_key}")
        array = np.load(self.folder / tensor_name(date_key, field), mmap_mode="r", allow_pickle=False)
        if array.dtype != DTYPES[field] or array.shape != (self.n_series, 24):
            raise InterimError(f"{tensor_name(date_key, field)} no tiene la forma {(self.n_series, 24)} y el tipo {DTYPES[field]} del cubo")
        return array

    def sales(self, date_key: int) -> np.memmap:
        """float32 (series, 24): the sale of every hour of the day, read-only."""
        return self._load(date_key, "sales")

    def stock(self, date_key: int) -> np.memmap:
        """int8 (series, 24): 1 where the hour had no stock, read-only."""
        return self._load(date_key, "stock")


def open_cube(interim_dir: Path) -> Cube:
    """The cube of `interim_dir`; ``InterimError`` if the files are not the ones their manifest names (runbook R12)."""
    problem, document = manifest_problem(interim_dir)
    if problem is not None:
        raise InterimError(problem)
    keys = sorted({int(match.group(1)) for name in document["files"] if (match := _TENSOR.fullmatch(name))})
    return Cube(Path(interim_dir), np.array(keys, dtype=np.int32), int(document["counts"]["series"]))
