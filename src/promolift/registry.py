"""The artifact of the frozen model, read only when its bytes are the registered ones (M03, RF16, D20), and the seal of the launch (RF16, D17; M05; plan,
section 15). Adapted from project 05's ``registry.py`` (its D39, D18 and A8).

**The artifact** is ``launch.npz``: plain numeric arrays (the base of R1, the distribution of the first hour without stock, the counterfactual ``a`` and ``b`` of the
two versions, the sealed lifts and the keys of the series and groups) and a JSON text as bytes, in an uncompressed zip with fixed entry times, so the same model
always gives the same bytes. It is read with ``np.load(..., allow_pickle=False)`` and only after its size and SHA-256 were compared with the registry's; an array of
Python objects is refused whatever its hash is. R3 does not fit in an array: ``r3.pkl`` holds the fitted ``HistGradientBoostingRegressor`` and is read the way project
05 reads its pickle: the bytes once, ``hmac.compare_digest`` with the registered hash and only then ``pickle.loads`` of *those* bytes. The hash protects against a file that
was replaced or damaged, not against someone who rewrites the file and the registry together (D20).

**The seal** (``reports/model_seal.json``) has a launch part (and, from U11, a test part), each written once. ``config_sha256`` is the SHA-256 of the canonical JSON of the
whole ``SealedConfig``: every key that can change a sealed value is in it, and the hash of the TOML file is another thing (``config_file_sha256``, project 05's A8) that
never appears here. A repetition with the sealed configuration must reproduce the sealed values rounded to 6 decimals (``SealMismatchError`` naming each); another
configuration is ``post_seal`` (M05) and the seal stays as it is.
"""

from __future__ import annotations

import dataclasses
import errno
import hashlib
import hmac
import io
import json
import logging
import math
import os
import pickle
import re
import tempfile
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor

from promolift.config import SealedConfig
from promolift.effect import Counterfactual, Lifts
from promolift.files import write_atomic
from promolift.recovery import Recovery

logger = logging.getLogger(__name__)

MODEL_VERSION = "v1"
ARTIFACT_NAME = "launch.npz"
R3_NAME = "r3.pkl"
PICKLE_PROTOCOL = 5
MAX_ARTIFACT_BYTES = 1 << 30           # the arrays of 50,000 series are tens of MB; a file over this is not this project's model
FORMAT = 1
VERSIONS = ("raw", "recovered")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_ENTRY_TIME = (1980, 1, 1, 0, 0, 0)
REGISTRY_COLUMNS = ("model_version", "trained_as_of", "artifact_name", "artifact_sha256", "r3_name", "r3_sha256", "config_sha256", "recovery_json", "validation_digest")


class ArtifactError(RuntimeError):
    """The artifact cannot be used as the registered model (M03)."""


class ArtifactMismatchError(ArtifactError):
    """The file does not have the registered size or SHA-256: nothing was read from it (runbook R6)."""


class ArtifactMissingError(ArtifactError):
    """There is no artifact, or no registered version, to load (runbook R6)."""


class SealError(RuntimeError):
    """The seal file cannot be read as a seal, or what is asked of it is not allowed."""


class SealMismatchError(SealError):
    """A repetition with the sealed configuration did not reproduce the sealed values (runbook R7)."""


@dataclass(frozen=True)
class RunMeta:
    """What a task needs of its run: its key and the instant it has reached."""

    run_key: str
    as_of: datetime


@dataclass(frozen=True)
class LaunchBundle:
    """What the launch freezes: the recovery chosen, the distribution of the first hour without stock, the counterfactual of the two versions over the 90 days of
    the launch and the lifts it sealed, by version (the cells are ``group position * n_bands + band``)."""

    version: str
    recovery: Recovery
    pmf: np.ndarray
    cf: dict[str, Counterfactual]
    lifts: dict[str, Lifts]
    group_ids: np.ndarray
    n_bands: int
    hours: tuple[int, int]
    r3: Any | None = None       # R3 fitted with the 90 days, kept even when it was not chosen: the test week measures it as a comparison (C10, D20)


# --- the artifact -------------------------------------------------------------------------------------------------------------------------


def _arrays(bundle: LaunchBundle) -> dict[str, np.ndarray]:
    meta = {"format": FORMAT, "version": bundle.version, "method": bundle.recovery.method, "kappa": bundle.recovery.kappa, "n_bands": bundle.n_bands,
            "hours": list(bundle.hours)}
    arrays: dict[str, np.ndarray] = {
        "base": np.asarray(bundle.recovery.base, dtype=np.float64), "pmf": np.asarray(bundle.pmf, dtype=np.float64),
        "group_ids": np.asarray(bundle.group_ids, dtype=np.int64), "days": np.asarray(bundle.cf["recovered"].days, dtype=np.int32),
        "meta": np.frombuffer(json.dumps(meta, sort_keys=True).encode("utf-8"), dtype=np.uint8),
    }
    for version in VERSIONS:
        arrays[f"a_{version}"] = np.asarray(bundle.cf[version].a, dtype=np.float64)
        arrays[f"b_{version}"] = np.asarray(bundle.cf[version].b, dtype=np.float64)
        arrays[f"overall_{version}"] = np.array([bundle.lifts[version].overall], dtype=np.float64)
        arrays[f"cell_{version}"] = np.asarray(bundle.lifts[version].cell, dtype=np.float64)
    return arrays


def artifact_bytes(bundle: LaunchBundle) -> bytes:
    """The bytes of ``launch.npz``: one ``.npy`` per array, in name order, stored (not compressed) with a fixed entry time."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
        for name, array in sorted(_arrays(bundle).items()):
            payload = io.BytesIO()
            np.lib.format.write_array(payload, np.ascontiguousarray(array), allow_pickle=False)
            info = zipfile.ZipInfo(f"{name}.npy", date_time=_ENTRY_TIME)
            info.compress_type = zipfile.ZIP_STORED
            archive.writestr(info, payload.getvalue())
    return buffer.getvalue()


def _r3_bytes(bundle: LaunchBundle) -> bytes | None:
    model = bundle.r3 if bundle.r3 is not None else bundle.recovery.r3
    return None if model is None else pickle.dumps(model, protocol=PICKLE_PROTOCOL)


def artifact_digests(bundle: LaunchBundle) -> tuple[str, str | None]:
    """The SHA-256 of the files ``save_artifact`` would write for `bundle` (``launch.npz`` and, for R3, ``r3.pkl``), without writing them."""
    r3 = _r3_bytes(bundle)
    return hashlib.sha256(artifact_bytes(bundle)).hexdigest(), None if r3 is None else hashlib.sha256(r3).hexdigest()


def save_artifact(bundle: LaunchBundle, models_dir: Path) -> tuple[str, str | None]:
    """Write ``launch.npz`` (and ``r3.pkl`` if the recovery is R3) into `models_dir`, each atomically, and return their SHA-256."""
    folder = Path(models_dir)
    data = artifact_bytes(bundle)
    r3_bytes = _r3_bytes(bundle)
    write_atomic(folder / ARTIFACT_NAME, data)
    if r3_bytes is not None:
        write_atomic(folder / R3_NAME, r3_bytes)
    digest = hashlib.sha256(data).hexdigest()
    logger.info("artifact %s written: sha256 %s, %d bytes", ARTIFACT_NAME, digest, len(data))
    return digest, None if r3_bytes is None else hashlib.sha256(r3_bytes).hexdigest()


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _read_registered(path: Path, expected: str, what: str) -> bytes:
    """The bytes of the file at `path`, read once, only if their SHA-256 is `expected` (M03): ``ArtifactMissingError`` if it is not there, and
    ``ArtifactMismatchError`` before anything is parsed if it is too big or its hash is another one."""
    if not _is_sha256(expected):
        raise ValueError(f"la huella registrada de {what} debe ser un SHA-256 de 64 dígitos hexadecimales en minúscula")
    try:
        size = path.stat().st_size
    except OSError as error:
        raise ArtifactMissingError(f"M03: no hay un artefacto legible en {path.name} ({error.__class__.__name__}); no se leyó nada (docs/runbook.md, R6)") from error
    if size > MAX_ARTIFACT_BYTES:
        raise ArtifactMismatchError(f"M03: {path.name} pesa {size} bytes, más que el tope de {MAX_ARTIFACT_BYTES}: no se leyó (docs/runbook.md, R6)")
    data = path.read_bytes()
    actual = hashlib.sha256(data).hexdigest()
    if not hmac.compare_digest(actual, expected):
        logger.error("M03: %s has sha256 %s and %s was registered; not loaded", path.name, actual, expected)
        raise ArtifactMismatchError(
            f"M03: {path.name} tiene la huella {actual} y la registrada es {expected}: no se leyó. Se restaura el archivo registrado o se vuelve a entrenar "
            "desde el lanzamiento (docs/runbook.md, R6)")
    return data


def _read_arrays(data: bytes, name: str) -> dict[str, np.ndarray]:
    try:
        with np.load(io.BytesIO(data), allow_pickle=False) as archive:
            return {key: archive[key] for key in archive.files}
    except ValueError as error:
        raise ArtifactError(f"M03: {name} guarda objetos de Python o no es un .npz de arreglos numéricos ({error}); no se tomó nada de él (docs/runbook.md, R6)") from error
    except (OSError, zipfile.BadZipFile) as error:
        raise ArtifactError(f"M03: {name} no se puede leer como .npz ({error.__class__.__name__}) (docs/runbook.md, R6)") from error


def load_artifact(models_dir: Path, row: Mapping[str, Any]) -> LaunchBundle:
    """The frozen model of the registry `row`, loaded only if ``launch.npz`` has the registered SHA-256 (and, for R3, ``r3.pkl`` its own). The hash is compared
    before the file is parsed; the arrays are read with ``allow_pickle=False`` and an array of objects, a missing array or an extra one is an ``ArtifactError``."""
    folder = Path(models_dir)
    name = row["artifact_name"]
    arrays = _read_arrays(_read_registered(folder / name, row["artifact_sha256"], "el artefacto"), name)
    expected = {"base", "pmf", "group_ids", "days", "meta", *[f"{kind}_{v}" for v in VERSIONS for kind in ("a", "b", "overall", "cell")]}
    if set(arrays) != expected:
        missing, extra = sorted(expected - set(arrays)), sorted(set(arrays) - expected)
        raise ArtifactError(f"M03: {name} no tiene los arreglos del modelo: faltan {missing or 'ninguno'} y sobran {extra or 'ninguno'} (docs/runbook.md, R6)")
    if any(array.dtype == object for array in arrays.values()):
        raise ArtifactError(f"M03: {name} guarda objetos de Python (docs/runbook.md, R6)")
    meta = json.loads(arrays["meta"].tobytes().decode("utf-8"))
    r3 = None
    if meta["method"] == "r3" and not (row.get("r3_name") and row.get("r3_sha256")):
        raise ArtifactError("M03: el método elegido es r3 y el registro no tiene la huella de su r3.pkl (docs/runbook.md, R6)")
    if row.get("r3_name") and row.get("r3_sha256"):
        data = _read_registered(folder / row["r3_name"], row["r3_sha256"], "r3.pkl")
        r3 = pickle.loads(data)  # noqa: S301 - only bytes whose SHA-256 is the registered one (D20)
        if not isinstance(r3, HistGradientBoostingRegressor):
            raise ArtifactError(f"M03: {row['r3_name']} tiene la huella registrada pero no es un HistGradientBoostingRegressor, es {type(r3).__name__}")
    group_ids = arrays["group_ids"]
    days = arrays["days"]
    cf = {v: Counterfactual(arrays[f"a_{v}"], arrays[f"b_{v}"], days, v, group_ids) for v in VERSIONS}
    lifts = {v: Lifts(float(arrays[f"overall_{v}"][0]), arrays[f"cell_{v}"]) for v in VERSIONS}
    recovery = Recovery(meta["method"], meta["kappa"], arrays["base"], r3 if meta["method"] == "r3" else None, group_ids)
    return LaunchBundle(meta["version"], recovery, arrays["pmf"], cf, lifts, group_ids, int(meta["n_bands"]), (int(meta["hours"][0]), int(meta["hours"][1])), r3)


# --- the registry of the model (insert-only, 002_effects.sql) -----------------------------------------------------------------------------


def register_model(conn: Any, row: Mapping[str, Any]) -> None:
    """Add the model to ``model_registry`` (in the caller's transaction, or its own if there is none). A version is registered once: the table refuses an
    update, a delete and a second insert of the same version, an upsert included. ``artifact_name`` is a file name inside ``[paths] models_dir``, never a path."""
    if set(row) != set(REGISTRY_COLUMNS):
        raise ValueError(f"la fila del registro debe tener exactamente {list(REGISTRY_COLUMNS)}")
    for key in ("artifact_sha256", "config_sha256", "validation_digest"):
        if not _is_sha256(row[key]):
            raise ValueError(f"{key}: se esperaban 64 dígitos hexadecimales en minúscula")
    if row["r3_sha256"] is not None and not _is_sha256(row["r3_sha256"]):
        raise ValueError("r3_sha256: se esperaban 64 dígitos hexadecimales en minúscula")
    for key in ("artifact_name", "r3_name"):
        if row[key] is not None and Path(row[key]).name != row[key]:
            raise ValueError(f"{key}: un nombre de archivo, no una ruta")
    conn.execute(f"INSERT INTO model_registry ({', '.join(REGISTRY_COLUMNS)}) VALUES ({', '.join(':' + c for c in REGISTRY_COLUMNS)})", dict(row))


def read_registry(conn: Any, version: str) -> dict[str, Any] | None:
    """The row of ``model_registry`` of a version as a dict, or None (also when the table does not exist yet: looking creates nothing)."""
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'model_registry'").fetchone() is None:
        return None
    cursor = conn.execute("SELECT * FROM model_registry WHERE model_version = ?", (version,))
    row = cursor.fetchone()
    return None if row is None else dict(zip([c[0] for c in cursor.description], row, strict=True))


def load_registered_bundle(conn: Any, models_dir: Path, version: str = MODEL_VERSION) -> LaunchBundle:
    """The model of a registered version, loaded through ``load_artifact`` with the registry's hashes (M03): the one way a run gets the model."""
    row = read_registry(conn, version)
    if row is None:
        raise ArtifactMissingError(f"M03: la versión {version} del modelo no está registrada; el lanzamiento no la ajustó (docs/runbook.md, R6)")
    return load_artifact(models_dir, row)


# --- the sealed view and its fingerprint (D17, M05) -------------------------------------------------------------------------------------


def sealed_view(cfg: Any, train_sha256: str, eval_sha256: str) -> SealedConfig:
    """The sealed view of the configuration `cfg` for two files that hashed to `train_sha256` and `eval_sha256`: what the sealed calculations receive."""
    return SealedConfig.of(cfg, train_sha256, eval_sha256)


def _json_ready(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, date):
        return value.isoformat()
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    raise SealError(f"un valor de la configuración sellada no es JSON: {type(value).__name__}")


def sealed_document(view: SealedConfig) -> dict[str, Any]:
    """The whole sealed view as JSON: one object per section with its keys (dates as ISO text, lists for tuples) and the two observed hashes."""
    return _json_ready(dataclasses.asdict(view))


def canonical_sha256(document: Any) -> str:
    """SHA-256 of the canonical JSON of `document` (sorted keys, fixed separators, ASCII)."""
    text = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(text.encode("ascii")).hexdigest()


def config_fingerprint(view: SealedConfig) -> str:
    """``config_sha256``: the SHA-256 of the canonical JSON of the whole sealed view, so every key that can change a sealed value changes it."""
    return canonical_sha256(sealed_document(view))


SEAL_VERSION = 1
SEAL_DECIMALS = 6                     # a repetition must reproduce the sealed values rounded to this many decimals
SEAL_MODE = 0o600                     # owner only, where the mode is the access control
LAUNCH_KEYS = ("run_key", "as_of", "train_sha256", "eval_sha256", "config_sha256", "sealed_config", "model_version", "artifact_sha256", "r3_sha256", "recovery", "effects",
               "validation", "validation_digest")
# what a repetition may change: the run that computed the values, its instant and the bytes of the files (the values do not depend on them; M03 checks the files
# against the registry)
_NOT_COMPARED = ("run_key", "as_of", "artifact_sha256", "r3_sha256")
_IDENTIFIERS = ("key", "id", "name", "method", "scope", "version", "unit_key", "check")     # what names an entry of a list of objects
_NO_HARD_LINKS = frozenset({errno.EPERM, errno.ENOTSUP, errno.EOPNOTSUPP, errno.EXDEV, errno.ENOSYS})
_WINDOWS_NO_HARD_LINKS = frozenset({1, 50})      # ERROR_INVALID_FUNCTION and ERROR_NOT_SUPPORTED
_ABSENT = object()


def _flat(document: Any, prefix: str = "") -> dict[str, Any]:
    """``{dotted path: value}`` of the leaves of nested objects. A list of objects is entered entry by entry, each named by its identifiers or by its position;
    any other list is one leaf."""
    if isinstance(document, Mapping):
        out: dict[str, Any] = {}
        for key, value in document.items():
            out.update(_flat(value, f"{prefix}.{key}" if prefix else str(key)))
        return out if out else {prefix: {}}
    if isinstance(document, (list, tuple)) and document and all(isinstance(item, Mapping) for item in document):
        out = {}
        for position, item in enumerate(document):
            name = "|".join(str(item[k]) for k in _IDENTIFIERS if k in item) or str(position)
            out.update({f"{prefix}.{name}.{key}": value for key, value in _flat(item).items()})
        return out
    return {prefix: document}


def differing_keys(sealed: Mapping[str, Any], current: Mapping[str, Any]) -> list[str]:
    """The keys (``section.key``) whose values differ between two documents, sorted."""
    a, b = _flat(sealed), _flat(current)
    return sorted(key for key in set(a) | set(b) if a.get(key, _ABSENT) != b.get(key, _ABSENT))


def _rounded(value: Any) -> Any:
    if isinstance(value, bool) or value is None or isinstance(value, (str, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise SealError("un valor del sello no es un número finito")
        return round(value, SEAL_DECIMALS)
    if isinstance(value, Mapping):
        return {str(key): _rounded(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_rounded(item) for item in value]
    raise SealError(f"un valor del sello no es JSON: {type(value).__name__}")


def read_seal(seal_path: Path) -> dict | None:
    """The seal at `seal_path`, or None if there is no file. A file that is not a seal is a ``SealError``: it is never taken for an absent one."""
    path = Path(seal_path)
    if not path.exists():
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise SealError(f"el sello {path.name} no se puede leer: {error}") from error
    if not isinstance(document, dict) or document.get("version") != SEAL_VERSION or not set(document) <= {"version", "launch", "test"}:
        raise SealError(f"el sello {path.name} no tiene la forma de la versión {SEAL_VERSION}")
    launch = document.get("launch")
    if not isinstance(launch, dict) or set(launch) != set(LAUNCH_KEYS) or not _is_sha256(launch.get("config_sha256")):
        raise SealError(f"la parte del lanzamiento del sello {path.name} no tiene sus claves o su huella")
    return document


def seal_state(seal_path: Path, config_sha256: str) -> Literal["none", "match", "post_seal"]:
    """``none`` if there is no seal, ``match`` if its configuration is `config_sha256` and ``post_seal`` if it is another one (M05)."""
    document = read_seal(seal_path)
    if document is None:
        return "none"
    return "match" if document["launch"]["config_sha256"] == config_sha256 else "post_seal"


def _dump(document: Mapping[str, Any]) -> bytes:
    return (json.dumps(document, sort_keys=True, indent=1, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def _lacks_hard_links(error: OSError) -> bool:
    return error.errno in _NO_HARD_LINKS or getattr(error, "winerror", None) in _WINDOWS_NO_HARD_LINKS


def _create_without_link(path: Path, data: bytes) -> bool:
    """The creation for a file system without hard links: the exclusive create is the check; a half file is removed if the write fails."""
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0), SEAL_MODE)
    except FileExistsError:
        return False
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(descriptor, view):]
        os.fsync(descriptor)
    except BaseException:
        os.close(descriptor)
        path.unlink(missing_ok=True)
        raise
    os.close(descriptor)
    return True


def _create_exclusive(path: Path, data: bytes) -> bool:
    """Create `path` with `data` only if it does not exist, all or nothing: True if created, False if a file was already there. The data goes to a temporary
    file, flushed to disk, that is hard-linked to `path`, which fails if `path` exists and never shows half a file; without hard links an exclusive create is the check."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        try:
            os.link(name, path)
            return True
        except FileExistsError:
            return False
        except OSError as error:
            if not _lacks_hard_links(error):
                raise
            return _create_without_link(path, data)
    finally:
        Path(name).unlink(missing_ok=True)


def _check_part(part: Mapping[str, Any]) -> None:
    missing, extra = [k for k in LAUNCH_KEYS if k not in part], sorted(set(part) - set(LAUNCH_KEYS))
    if missing or extra:
        raise SealError(f"la parte del lanzamiento debe tener exactamente las claves {list(LAUNCH_KEYS)}; faltan {missing}, sobran {extra}")
    if not _is_sha256(part["config_sha256"]):
        raise SealError("config_sha256 de la parte del lanzamiento debe ser un SHA-256 de 64 dígitos hexadecimales")
    if canonical_sha256(part["sealed_config"]) != part["config_sha256"]:
        raise SealError("config_sha256 no es la huella de la configuración sellada de la parte del lanzamiento")
    _rounded(dict(part))                 # refuses a value that is not JSON, or not finite, before anything is compared or written


def _differences(sealed: Mapping[str, Any], current: Mapping[str, Any]) -> list[str]:
    a = _flat(_rounded({k: v for k, v in sealed.items() if k not in _NOT_COMPARED}))
    b = _flat(_rounded({k: v for k, v in current.items() if k not in _NOT_COMPARED}))
    return sorted(key for key in set(a) | set(b) if a.get(key, _ABSENT) != b.get(key, _ABSENT))


def launch_seal_outcome(seal_path: Path, launch: Mapping[str, Any]) -> Literal["written", "unchanged", "post_seal"]:
    """What writing the launch part would do, decided **before** anything is written: ``written`` (there is no seal), ``unchanged`` (the seal has this
    configuration and every sealed value, rounded to 6 decimals, is this one) or ``post_seal`` (the seal has another configuration; M05). The same configuration with
    another sealed value is a ``SealMismatchError`` that names each value (runbook R7)."""
    _check_part(launch)
    document = read_seal(seal_path)
    if document is None:
        return "written"
    sealed = document["launch"]
    if sealed["config_sha256"] != launch["config_sha256"]:
        return "post_seal"
    differ = _differences(sealed, launch)
    if differ:
        then, now = _flat(_rounded(sealed)), _flat(_rounded(dict(launch)))
        named = "; ".join(f"{key}: {then.get(key)!r} sellado, {now.get(key)!r} en esta corrida" for key in differ[:6])
        raise SealMismatchError(f"M05: la configuración es la sellada pero el lanzamiento no la reproduce: {named}{' y otros' if len(differ) > 6 else ''} (docs/runbook.md, R7)")
    return "unchanged"


def write_launch_seal(seal_path: Path, launch: Mapping[str, Any]) -> Literal["written", "unchanged", "post_seal"]:
    """Write the launch part of the seal once (an exclusive creation) and say what happened (``launch_seal_outcome``). An existing seal is never rewritten."""
    path = Path(seal_path)
    outcome = launch_seal_outcome(path, launch)
    if outcome == "written":
        if _create_exclusive(path, _dump({"version": SEAL_VERSION, "launch": dict(launch)})):
            logger.info("seal: launch part written to %s (config %s)", path.name, launch["config_sha256"][:12])
            return "written"
        return launch_seal_outcome(path, launch)         # someone created it between the decision and the write: judge against what is there
    if outcome == "post_seal":
        logger.warning("seal: this configuration (%s) is not the sealed one: post_seal; the keys that differ: %s", launch["config_sha256"][:12],
                       ", ".join(differing_keys(read_seal(path)["launch"]["sealed_config"], launch["sealed_config"])))
    return outcome
