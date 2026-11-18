"""The hours of the pipeline, in two cubes and the delivery files (RF03, RF08, D22; plan, sections 3 and 5).

**The canonical cube** (``data/interim/canonical/``, written by ``fetch_source``) has one pair of tensors per day for all 97 days of the two files and a
manifest that names every canonical file. **The cube of the loaded deliveries** (``data/interim/cube/``, written when a delivery is loaded) holds the hours
of each delivery once its series-days are in the warehouse, with a manifest of its own written last: a day is visible through it only after its delivery
arrived, so a calculation for an instant cannot read a day that was not delivered yet (RNF06 b).

``data/interim/canonical/<date_key>.sales.npy`` holds the sale of the 24 hours of one day for every series (float32, series x 24, in the order of
``series_key``) and ``<date_key>.stock.npy`` the hourly status (int8, 1 = out of stock). They are read with ``np.load(..., mmap_mode="r",
allow_pickle=False)``: a file that holds Python objects is refused, and the SHA-256 of every file is in ``interim_manifest.json``, which is written
last: a set of files without its manifest, or a file that is not the one the manifest names, is refused by every reader (``InterimError``).
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from promolift.files import atomic_path, sha256_file, write_atomic

INTERIM_MANIFEST = "interim_manifest.json"
INTERIM_MANIFEST_VERSION = 1
CANONICAL_DIR = "canonical"
LOADED_CUBE_DIR = "cube"
CUBE_MANIFEST = "manifest.json"
CUBE_MANIFEST_VERSION = 1
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


# --- the cube of one delivery ---------------------------------------------------------------------------------------------------


def delivery_cube_bytes(date_keys: np.ndarray, sales: np.ndarray, stock: np.ndarray) -> bytes:
    """The bytes of a delivery's cube: ``date_keys`` (int32, days), ``sales`` (float32, series x days x 24) and ``stock`` (int8, same shape) as an
    uncompressed zip of three ``.npy`` with a fixed entry time, so the same hours always give the same bytes (publishing again changes nothing, D18)."""
    arrays = {"date_keys": np.ascontiguousarray(date_keys, dtype=np.int32), "sales": np.ascontiguousarray(sales, dtype=DTYPES["sales"]),
              "stock": np.ascontiguousarray(stock, dtype=DTYPES["stock"])}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
        for name, array in arrays.items():
            payload = io.BytesIO()
            np.lib.format.write_array(payload, array, allow_pickle=False)
            info = zipfile.ZipInfo(f"{name}.npy", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            archive.writestr(info, payload.getvalue())
    return buffer.getvalue()


def write_delivery_cube(path: Path, date_keys: np.ndarray, sales: np.ndarray, stock: np.ndarray) -> str:
    """Write the cube of one delivery (``delivery_cube_bytes``) as ``<delivery_id>.cube.npz`` atomically and return its SHA-256; it is read back with
    ``read_delivery_cube`` (``np.load(allow_pickle=False)``)."""
    write_atomic(Path(path), delivery_cube_bytes(date_keys, sales, stock))
    return sha256_file(Path(path))


def read_delivery_cube(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """``(date_keys, sales, stock)`` of a delivery's cube; ``InterimError`` if it is not three arrays of the right type and shape, and a file with
    Python objects is refused (``allow_pickle=False``)."""
    with np.load(Path(path), allow_pickle=False) as archive:
        if set(archive.files) != {"date_keys", "sales", "stock"}:
            raise InterimError(f"{Path(path).name} no tiene los tres arreglos de una entrega (date_keys, sales, stock): tiene {sorted(archive.files)}")
        date_keys, sales, stock = archive["date_keys"], archive["sales"], archive["stock"]
    if date_keys.dtype != np.int32 or date_keys.ndim != 1:
        raise InterimError(f"{Path(path).name}: date_keys debe ser un arreglo int32 de una dimensión")
    for name, array in (("sales", sales), ("stock", stock)):
        if array.dtype != DTYPES[name] or array.ndim != 3 or array.shape[1] != len(date_keys) or array.shape[2] != 24:
            raise InterimError(f"{Path(path).name}: {name} debe ser {DTYPES[name]} de forma (series, {len(date_keys)}, 24), tiene {array.dtype} {array.shape}")
    if sales.shape != stock.shape:
        raise InterimError(f"{Path(path).name}: sales y stock no tienen la misma forma")
    return date_keys, sales, stock


# --- the cube of the loaded deliveries ---------------------------------------------------------------------------------------------


def _npy_bytes(array: np.ndarray, dtype: np.dtype) -> bytes:
    buffer = io.BytesIO()
    np.save(buffer, np.ascontiguousarray(array, dtype=dtype), allow_pickle=False)
    return buffer.getvalue()


def _read_cube_manifest(folder: Path) -> list[dict[str, Any]]:
    """The entries of the manifest of the cube of the loaded deliveries (none if there is no manifest); ``InterimError`` if it is not a valid one."""
    path = Path(folder) / CUBE_MANIFEST
    if not path.is_file():
        return []
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        entries = document["deliveries"]
        valid = (isinstance(document, dict) and set(document) == {"version", "deliveries"} and document["version"] == CUBE_MANIFEST_VERSION
                 and isinstance(entries, list)
                 and all(isinstance(e, dict) and set(e) == {"delivery_id", "n_series", "date_keys", "files"} and isinstance(e["delivery_id"], str)
                         and isinstance(e["n_series"], int) and isinstance(e["date_keys"], list) and all(isinstance(k, int) for k in e["date_keys"])
                         and isinstance(e["files"], dict) and set(e["files"]) == set(FIELDS)
                         and all(isinstance(f, dict) and set(f) == {"name", "sha256"} and isinstance(f["name"], str) and _HEX64.fullmatch(str(f["sha256"]))
                                 for f in e["files"].values()) for e in entries))
    except (OSError, ValueError, KeyError, TypeError):
        valid = False
    if not valid:
        raise InterimError(f"{CUBE_MANIFEST} no es un manifiesto válido del cubo de las entregas cargadas (runbook R12)")
    return entries


def store_delivery_cube(interim_dir: Path, delivery_id: str, date_keys: np.ndarray, sales: np.ndarray, stock: np.ndarray) -> None:
    """Copy the hours of a loaded delivery into ``<interim_dir>/cube/`` (``<delivery_id>.sales.npy`` and ``.stock.npy``) and list it in the manifest,
    written last and atomically: a failure before it leaves the delivery unlisted, so none of its days is visible, and storing again finishes the job.

    Storing the same hours again changes nothing (a file that was lost or damaged is written again); other hours for a delivery that is already in the
    cube are refused, and so is a day that another delivery already holds (runbook R12). The close has no day and is listed all the same."""
    folder = Path(interim_dir) / LOADED_CUBE_DIR
    entries = _read_cube_manifest(folder)
    keys = [int(k) for k in np.asarray(date_keys).tolist()]
    payloads = {"sales": _npy_bytes(sales, DTYPES["sales"]), "stock": _npy_bytes(stock, DTYPES["stock"])}
    digests = {field: hashlib.sha256(payloads[field]).hexdigest() for field in FIELDS}
    existing = next((e for e in entries if e["delivery_id"] == delivery_id), None)
    if existing is not None and (existing["date_keys"] != keys or {f: v["sha256"] for f, v in existing["files"].items()} != digests):
        raise InterimError(f"la entrega {delivery_id} ya está en el cubo con otro contenido (runbook R12): sus días ya se leyeron")
    for other in entries:
        clash = sorted(set(keys) & set(other["date_keys"]))
        if clash and other["delivery_id"] != delivery_id:
            raise InterimError(f"el día {clash[0]} ya está en la entrega {other['delivery_id']} del cubo (runbook R12)")
    for field in FIELDS:
        path = folder / f"{delivery_id}.{field}.npy"
        if not path.is_file() or sha256_file(path) != digests[field]:
            write_atomic(path, payloads[field])
    if existing is None:
        entry = {"delivery_id": delivery_id, "n_series": int(np.asarray(sales).shape[0]), "date_keys": keys,
                 "files": {field: {"name": f"{delivery_id}.{field}.npy", "sha256": digests[field]} for field in FIELDS}}
        write_atomic(folder / CUBE_MANIFEST, json.dumps({"version": CUBE_MANIFEST_VERSION, "deliveries": [*entries, entry]}, indent=2) + "\n")


class LoadedCube:
    """The hours of the days whose delivery was loaded: ``sales(date_key)`` and ``stock(date_key)``, each series x 24, read lazily as memory maps."""

    def __init__(self, folder: Path, entries: list[dict[str, Any]]) -> None:
        self.folder = Path(folder)
        self._where: dict[int, tuple[dict[str, Any], int]] = {key: (entry, i) for entry in entries for i, key in enumerate(entry["date_keys"])}
        self.date_keys = np.array(sorted(self._where), dtype=np.int32)
        self.n_series = int(entries[0]["n_series"]) if entries else 0
        self.deliveries = [e["delivery_id"] for e in entries]

    def __contains__(self, date_key: object) -> bool:
        return date_key in self._where

    def _load(self, date_key: int, field: str) -> np.ndarray:
        if date_key not in self._where:
            raise KeyError(f"el cubo de las entregas cargadas no tiene el día {date_key}")
        entry, index = self._where[date_key]
        array = np.load(self.folder / entry["files"][field]["name"], mmap_mode="r", allow_pickle=False)
        if array.dtype != DTYPES[field] or array.ndim != 3 or array.shape[0] != self.n_series or array.shape[2] != 24 or array.shape[1] != len(entry["date_keys"]):
            raise InterimError(f"{entry['files'][field]['name']} no tiene la forma ni el tipo que dice el manifiesto del cubo (runbook R12)")
        return array[:, index, :]

    def sales(self, date_key: int) -> np.ndarray:
        """float32 (series, 24): the sale of every hour of a delivered day, read-only."""
        return self._load(date_key, "sales")

    def stock(self, date_key: int) -> np.ndarray:
        """int8 (series, 24): 1 where the hour had no stock, read-only."""
        return self._load(date_key, "stock")


def open_loaded_cube(interim_dir: Path) -> LoadedCube:
    """The cube of the loaded deliveries of `interim_dir`; ``InterimError`` if it has no manifest or a file is missing or is not the one the manifest names."""
    folder = Path(interim_dir) / LOADED_CUBE_DIR
    if not (folder / CUBE_MANIFEST).is_file():
        raise InterimError(f"falta {CUBE_MANIFEST} en {folder}: el cubo de las entregas cargadas no tiene su manifiesto (runbook R12)")
    entries = _read_cube_manifest(folder)
    for entry in entries:
        for field in FIELDS:
            name, expected = entry["files"][field]["name"], entry["files"][field]["sha256"]
            if not (folder / name).is_file():
                raise InterimError(f"falta {name}, que el manifiesto nombra (runbook R12)")
            if sha256_file(folder / name) != expected:
                raise InterimError(f"{name} no coincide con la huella que dice el manifiesto: es de otra escritura (runbook R12)")
    return LoadedCube(folder, entries)
