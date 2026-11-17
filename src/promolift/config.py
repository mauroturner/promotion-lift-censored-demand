"""Pipeline configuration: one TOML file, typed, immutable and checked key by key (plan, section 4).

``config/pipeline.toml`` holds every default. A file may start from another one with a top-level ``extends = "<path>"``
(``config/pipeline.quick.toml`` does). Every relative path is resolved against the project folder, never against the working
directory (decision D27): the paths inside the configuration (``[source]`` and ``[paths]``) against ``$PROMOLIFT_HOME`` when it
is set, otherwise the parent of the folder that holds the main configuration file; a relative configuration file
(``$PROMOLIFT_CONFIG`` or the ``path`` argument, which ``--config`` passes) against ``$PROMOLIFT_HOME`` or, without it, the folder of
this package's project.

Anything unknown, missing, mistyped or inconsistent is a ``ValueError`` that names the key: an option that is accepted and silently
not used is the defect projects 01 and 02 both had.

Every leaf of the configuration is either in ``FINGERPRINT_KEYS`` (it can change a sealed value, so it enters the seal's
``config_sha256``) or in ``UNSEALED_KEYS`` (it cannot), never both and never neither (decision D17). The sealed calculations
receive ``SealedConfig``, which holds only the fingerprinted keys and the observed hashes of the two source files. The hash of the
TOML file itself is a different thing (``config_file_sha256``, project 05's A8) and never appears here.
"""

from __future__ import annotations

import dataclasses
import math
import os
import re
import tomllib
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, get_args, get_origin, get_type_hints

DEFAULT_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = DEFAULT_PROJECT_ROOT / "config" / "pipeline.toml"

ENV_CONFIG = "PROMOLIFT_CONFIG"
ENV_HOME = "PROMOLIFT_HOME"
RECOVERY_METHOD_NAMES = ("r1", "r2", "r3")
EFFECT_VERSION_NAMES = ("raw", "recovered")
SPLIT_BLOCK_NAMES = ("train", "purge", "valid_v1", "valid_v2", "test")

_SHA256 = re.compile(r"[0-9a-f]{64}")
_COMMIT = re.compile(r"[0-9a-f]{40}")
MAX_SEED = 2**32 - 1   # the largest seed that numpy's legacy generators and scikit-learn accept
_TYPE_NAMES = {
    bool: "verdadero o falso", int: "un entero", float: "un número", str: "un texto", date: "una fecha (AAAA-MM-DD, sin hora)",
    Path: "una ruta",
}


@dataclass(frozen=True)
class SourceConfig:
    train_path: Path
    train_bytes: int
    train_sha256: str
    eval_path: Path
    eval_bytes: int
    eval_sha256: str
    max_bytes: int
    max_rows: int
    max_hourly_sale: float
    dataset_commit: str


@dataclass(frozen=True)
class CalendarConfig:
    first_day: date
    launch_last_day: date
    last_day: date
    day_hours: tuple[int, ...]


@dataclass(frozen=True)
class DaysConfig:
    regular_min_discount: float
    anomalous_max_discount: float
    anomalous_min_discount: float
    bands: tuple[float, ...]


@dataclass(frozen=True)
class SplitConfig:
    train: tuple[date, ...]
    purge: tuple[date, ...]
    valid_v1: tuple[date, ...]
    valid_v2: tuple[date, ...]
    test: tuple[date, ...]
    min_masked_days: int


@dataclass(frozen=True)
class RecoveryConfig:
    methods: tuple[str, ...]
    kappas: tuple[float, ...]
    mask_seed_v1: int
    mask_seed_v2: int
    mask_seed_test: int
    mcar_hours: int
    r3_train_days: int
    r3_max_iter: int
    r3_learning_rate: float
    r3_max_leaf_nodes: int
    r3_min_samples_leaf: int
    random_state: int
    leak_tripwire_ratio: float


@dataclass(frozen=True)
class EffectConfig:
    ipf_iterations: int
    versions: tuple[str, ...]


@dataclass(frozen=True)
class BootstrapConfig:
    resamples: int
    seed: int
    recovery_resamples: int


@dataclass(frozen=True)
class RankingConfig:
    min_series: int


@dataclass(frozen=True)
class ForecastConfig:
    naive_days: int


@dataclass(frozen=True)
class VariantsConfig:
    control_any_flag0: bool
    series_only_intervals: bool
    mcar_mask: bool
    first_category_cells: bool


@dataclass(frozen=True)
class CriteriaConfig:
    c02_max_abs_bias: float
    c03_max_abs_lift_bias: float
    c05_min_spearman: float
    c06_min_consistent_share: float
    c07_min_spearman: float


@dataclass(frozen=True)
class SiteConfig:
    max_total_bytes: int


@dataclass(frozen=True)
class PathsConfig:
    raw_dir: Path
    interim_dir: Path
    warehouse: Path
    models_dir: Path
    outputs_dir: Path
    site_dir: Path
    reports_dir: Path
    seal: Path
    dashboard_html: Path
    readme: Path
    figures_dir: Path


@dataclass(frozen=True)
class PipelineConfig:
    source: SourceConfig
    calendar: CalendarConfig
    days: DaysConfig
    split: SplitConfig
    recovery: RecoveryConfig
    effect: EffectConfig
    bootstrap: BootstrapConfig
    ranking: RankingConfig
    forecast: ForecastConfig
    variants: VariantsConfig
    criteria: CriteriaConfig
    site: SiteConfig
    paths: PathsConfig
    project_root: Path


# --- the seal's view of the configuration (D17) ------------------------------------------------------------------------


@dataclass(frozen=True)
class SealedSourceConfig:
    """The one key of ``[source]`` that can change a sealed value: the commit of the dataset. The paths, the accepted sizes and hashes and the
    limits cannot; the hashes of the files that were actually read enter as ``SealedConfig.train_sha256_seen`` and ``eval_sha256_seen``."""

    dataset_commit: str


@dataclass(frozen=True)
class SealedConfig:
    """What the sealed calculations receive (days, split, masks, recovery, effect, intervals, ranking, forecast, evaluation and variants):
    only the keys of ``FINGERPRINT_KEYS`` and the observed hashes of the two files. A key outside it cannot reach a sealed value."""

    source: SealedSourceConfig
    calendar: CalendarConfig
    days: DaysConfig
    split: SplitConfig
    recovery: RecoveryConfig
    effect: EffectConfig
    bootstrap: BootstrapConfig
    ranking: RankingConfig
    forecast: ForecastConfig
    variants: VariantsConfig
    criteria: CriteriaConfig
    train_sha256_seen: str
    eval_sha256_seen: str

    @classmethod
    def of(cls, cfg: PipelineConfig, train_sha256: str, eval_sha256: str) -> SealedConfig:
        """The sealed view of `cfg` for two files that hashed to `train_sha256` and `eval_sha256`."""
        for name, value in (("train_sha256_seen", train_sha256), ("eval_sha256_seen", eval_sha256)):
            if not _SHA256.fullmatch(value):
                raise ValueError(f"{name}: se esperaban 64 caracteres hexadecimales en minúscula, se recibió {value!r}")
        skipped = ("source", "train_sha256_seen", "eval_sha256_seen")
        sections = {f.name: getattr(cfg, f.name) for f in dataclasses.fields(cls) if f.name not in skipped}
        source = SealedSourceConfig(dataset_commit=cfg.source.dataset_commit)
        return cls(source=source, **sections, train_sha256_seen=train_sha256, eval_sha256_seen=eval_sha256)


def config_leaves(cls: type, prefix: str = "") -> Iterator[str]:
    """The full name of every leaf of a configuration dataclass, ``section.key``, in declaration order."""
    hints = get_type_hints(cls)
    for f in dataclasses.fields(cls):
        name = f"{prefix}{f.name}"
        if dataclasses.is_dataclass(hints[f.name]):
            yield from config_leaves(hints[f.name], f"{name}.")
        else:
            yield name


# Every key that can change a sealed value, named one by one so that a new key fails tests/unit/test_config.py until it is classified.
# Including one too many only turns a cosmetic change into a post_seal run; one too few is project 03's defect B4 (D17). The observed
# hashes of the two files (train_sha256_seen, eval_sha256_seen) are not configured: SealedConfig adds them.
FINGERPRINT_KEYS: tuple[str, ...] = (
    "source.dataset_commit",
    "calendar.first_day", "calendar.launch_last_day", "calendar.last_day", "calendar.day_hours",
    "days.regular_min_discount", "days.anomalous_max_discount", "days.anomalous_min_discount", "days.bands",
    "split.train", "split.purge", "split.valid_v1", "split.valid_v2", "split.test", "split.min_masked_days",
    "recovery.methods", "recovery.kappas", "recovery.mask_seed_v1", "recovery.mask_seed_v2", "recovery.mask_seed_test",
    "recovery.mcar_hours", "recovery.r3_train_days", "recovery.r3_max_iter", "recovery.r3_learning_rate", "recovery.r3_max_leaf_nodes",
    "recovery.r3_min_samples_leaf", "recovery.random_state", "recovery.leak_tripwire_ratio",
    "effect.ipf_iterations", "effect.versions",
    "bootstrap.resamples", "bootstrap.seed", "bootstrap.recovery_resamples",
    "ranking.min_series",
    "forecast.naive_days",
    "variants.control_any_flag0", "variants.series_only_intervals", "variants.mcar_mask", "variants.first_category_cells",
    "criteria.c02_max_abs_bias", "criteria.c03_max_abs_lift_bias", "criteria.c05_min_spearman", "criteria.c06_min_consistent_share",
    "criteria.c07_min_spearman",
)
# Every key that cannot: where the two files are and their accepted sizes, hashes and limits (the hashes of the files that were read enter
# instead), the site's limit and where the outputs go.
UNSEALED_KEYS: tuple[str, ...] = (
    "source.train_path", "source.train_bytes", "source.train_sha256", "source.eval_path", "source.eval_bytes", "source.eval_sha256",
    "source.max_bytes", "source.max_rows", "source.max_hourly_sale",
    "site.max_total_bytes",
    "paths.raw_dir", "paths.interim_dir", "paths.warehouse", "paths.models_dir", "paths.outputs_dir", "paths.site_dir", "paths.reports_dir",
    "paths.seal", "paths.dashboard_html", "paths.readme", "paths.figures_dir",
)


# --- loading --------------------------------------------------------------------------------------------------------


def _resolve(value: str, root: Path, where: str) -> Path:
    if not value.strip():
        raise ValueError(f"{where}: se esperaba una ruta, se recibió un texto vacío")
    path = Path(value)
    if path.is_absolute():
        return path  # an absolute path is explicit: it may point anywhere on purpose
    joined = Path(os.path.normpath(root / path))
    base = Path(os.path.normpath(root))
    if joined != base and base not in joined.parents:
        raise ValueError(
            f"{where}: la ruta relativa {value!r} sale de la carpeta del proyecto ({base}); "
            "use una ruta absoluta si el destino está fuera a propósito"
        )
    return joined


def _coerce(value: Any, annotation: Any, where: str, root: Path) -> Any:
    """Convert a TOML value to the annotated type or raise ValueError naming `where`."""
    origin = get_origin(annotation)
    if origin is tuple:
        (element, _ellipsis) = get_args(annotation)
        if not isinstance(value, list):
            raise ValueError(f"{where}: se esperaba una lista, se recibió {type(value).__name__}")
        return tuple(_coerce(v, element, where, root) for v in value)
    if annotation is bool:
        ok = isinstance(value, bool)
    elif annotation is int:
        ok = isinstance(value, int) and not isinstance(value, bool)
    elif annotation is float:
        ok = isinstance(value, (int, float)) and not isinstance(value, bool)
        value = float(value) if ok else value
    elif annotation is str:
        ok = isinstance(value, str)
    elif annotation is date:
        ok = type(value) is date   # a local date: no date-time (a subclass of date), no text
    elif annotation is Path:
        if isinstance(value, str):
            return _resolve(value, root, where)
        ok = False
    else:  # pragma: no cover - only reachable by adding an unsupported annotation
        raise TypeError(f"{where}: unsupported annotation {annotation!r}")
    if not ok:
        raise ValueError(f"{where}: se esperaba {_TYPE_NAMES.get(annotation, annotation)}, se recibió {value!r}")
    return value


def _build_section(cls: type, data: Any, name: str, root: Path) -> Any:
    if not isinstance(data, dict):
        raise ValueError(f"[{name}]: se esperaba una tabla, se recibió {type(data).__name__}")
    hints = get_type_hints(cls)
    fields = [f.name for f in dataclasses.fields(cls)]
    unknown = sorted(set(data) - set(fields))
    if unknown:
        raise ValueError(f"[{name}]: clave desconocida {unknown[0]!r}")
    missing = [f for f in fields if f not in data]
    if missing:
        raise ValueError(f"[{name}]: falta la clave {missing[0]!r}")
    return cls(**{f: _coerce(data[f], hints[f], f"[{name}] {f}", root) for f in fields})


# --- consistency checks ---------------------------------------------------------------------------------------------


def _positive(value: float, where: str) -> None:
    if not (math.isfinite(value) and value > 0):
        raise ValueError(f"{where}: se esperaba un valor finito mayor que 0, se recibió {value!r}")


def _at_least(value: int, minimum: int, where: str) -> None:
    if value < minimum:
        raise ValueError(f"{where}: se esperaba {minimum} o más, se recibió {value!r}")


def _seed(value: int, where: str) -> None:
    if not 0 <= value <= MAX_SEED:
        raise ValueError(f"{where}: se esperaba un entero de 0 a {MAX_SEED}, se recibió {value!r}")


def _fraction(value: float, where: str, *, closed_high: bool = False) -> None:
    if not (math.isfinite(value) and (0 < value <= 1 if closed_high else 0 < value < 1)):
        interval = "(0, 1]" if closed_high else "(0, 1)"
        raise ValueError(f"{where}: se esperaba un valor en {interval}, se recibió {value!r}")


def _names(values: tuple[str, ...], allowed: tuple[str, ...], where: str) -> None:
    if not values or len(set(values)) != len(values):
        raise ValueError(f"{where}: se esperaba una lista no vacía y sin repetidos, se recibió {list(values)}")
    for value in values:
        if value not in allowed:
            raise ValueError(f"{where}: {value!r} no es un valor conocido ({', '.join(allowed)})")


def _check_hash(value: str, where: str) -> None:
    if not _SHA256.fullmatch(value):
        raise ValueError(f"{where}: se esperaban 64 caracteres hexadecimales en minúscula, se recibió {value!r}")


def _check_source(cfg: PipelineConfig) -> None:
    s = cfg.source
    for key in ("max_bytes", "max_rows", "max_hourly_sale"):
        _positive(getattr(s, key), f"[source] {key}")
    if not _COMMIT.fullmatch(s.dataset_commit):
        raise ValueError(f"[source] dataset_commit: se esperaban 40 caracteres hexadecimales en minúscula, se recibió {s.dataset_commit!r}")
    if Path(os.path.normpath(s.train_path)) == Path(os.path.normpath(s.eval_path)):
        raise ValueError(f"[source] eval_path: se esperaban dos archivos distintos, y es el mismo que train_path ({s.train_path})")
    quick = Path(os.path.normpath(cfg.project_root / "data" / "quick"))
    for which in ("train", "eval"):
        path, size, digest = getattr(s, f"{which}_path"), getattr(s, f"{which}_bytes"), getattr(s, f"{which}_sha256")
        _at_least(size, 0, f"[source] {which}_bytes")
        if digest:
            _check_hash(digest, f"[source] {which}_sha256")
            if size == 0:
                raise ValueError(f"[source] {which}_bytes: con una huella aceptada se esperaba un tamaño mayor que 0")
            if size > s.max_bytes:
                raise ValueError(f"[source] {which}_bytes: el tamaño aceptado ({size}) supera max_bytes ({s.max_bytes})")
        else:
            if quick not in Path(os.path.normpath(path)).parents:
                raise ValueError(
                    f"[source] {which}_sha256: vacía solo se admite en el modo rápido, con la fuente bajo data/quick/ ({quick}); "
                    f"la fuente real exige los 64 caracteres de su huella (se recibió la ruta {path})"
                )
            if size != 0:
                raise ValueError(f"[source] {which}_bytes: con {which}_sha256 vacía (modo rápido) se esperaba 0, se recibió {size}")


def _check_calendar(cfg: PipelineConfig) -> None:
    """The days, the launch and the blocks of D14."""
    c = cfg.calendar
    hours = c.day_hours
    if len(hours) != 2:
        raise ValueError(f"[calendar] day_hours: se esperaban dos horas (la primera y la última), se recibió {list(hours)}")
    if not all(0 <= hour <= 23 for hour in hours):
        raise ValueError(f"[calendar] day_hours: se esperaban horas de 0 a 23, se recibió {list(hours)}")
    if hours[0] > hours[1]:
        raise ValueError(f"[calendar] day_hours: se esperaban horas ordenadas (primera ≤ última), se recibieron desordenadas: {list(hours)}")
    if not c.first_day < c.launch_last_day:
        raise ValueError(f"[calendar] first_day: se esperaba first_day < launch_last_day, se recibió {c.first_day} y {c.launch_last_day}")
    if not c.launch_last_day < c.last_day:
        raise ValueError(f"[calendar] launch_last_day: se esperaba launch_last_day < last_day, se recibió {c.launch_last_day} y {c.last_day}")
    from promolift.split import check_split

    check_split(cfg)      # the blocks, their edges and the test week after the launch (AC09): split.py is their one home


def _check_days(cfg: PipelineConfig) -> None:
    d = cfg.days
    _fraction(d.regular_min_discount, "[days] regular_min_discount", closed_high=True)
    if not (math.isfinite(d.anomalous_max_discount) and 0 <= d.anomalous_max_discount < d.regular_min_discount):
        raise ValueError(
            f"[days] anomalous_max_discount: se esperaba un valor desde 0 y menor que regular_min_discount ({d.regular_min_discount}), "
            f"se recibió {d.anomalous_max_discount!r}"
        )
    if not (math.isfinite(d.anomalous_min_discount) and d.anomalous_min_discount >= 1):
        raise ValueError(f"[days] anomalous_min_discount: se esperaba 1 o más (el descuento 1 es «sin rebaja»), se recibió {d.anomalous_min_discount!r}")
    edges = d.bands
    if len(edges) < 2 or not all(math.isfinite(edge) for edge in edges):
        raise ValueError(f"[days] bands: se esperaba una lista de al menos 2 bordes finitos, se recibió {list(edges)}")
    if any(later <= earlier for earlier, later in zip(edges, edges[1:])):
        raise ValueError(f"[days] bands: se esperaban bordes estrictamente crecientes, se recibió {list(edges)}")
    if edges[0] != 0:
        raise ValueError(f"[days] bands: la lista debe empezar en 0, se recibió {edges[0]!r}")
    if edges[-1] != 1:
        raise ValueError(f"[days] bands: la lista debe terminar en 1, se recibió {edges[-1]!r}")


def _check_recovery(cfg: PipelineConfig) -> None:
    r = cfg.recovery
    _names(r.methods, RECOVERY_METHOD_NAMES, "[recovery] methods")
    if not r.kappas or len(set(r.kappas)) != len(r.kappas):
        raise ValueError(f"[recovery] kappas: se esperaba una lista no vacía y sin repetidos, se recibió {list(r.kappas)}")
    for kappa in r.kappas:
        _positive(kappa, "[recovery] kappas")
    _seed(r.mask_seed_v1, "[recovery] mask_seed_v1")
    _seed(r.mask_seed_v2, "[recovery] mask_seed_v2")
    _seed(r.mask_seed_test, "[recovery] mask_seed_test")
    first, last = cfg.calendar.day_hours
    if not 1 <= r.mcar_hours <= last - first + 1:
        raise ValueError(f"[recovery] mcar_hours: se esperaba un valor de 1 a {last - first + 1} (las horas del análisis), se recibió {r.mcar_hours!r}")
    _at_least(r.r3_train_days, 1, "[recovery] r3_train_days")
    _at_least(r.r3_max_iter, 1, "[recovery] r3_max_iter")
    _positive(r.r3_learning_rate, "[recovery] r3_learning_rate")
    _at_least(r.r3_max_leaf_nodes, 2, "[recovery] r3_max_leaf_nodes")
    _at_least(r.r3_min_samples_leaf, 1, "[recovery] r3_min_samples_leaf")
    _seed(r.random_state, "[recovery] random_state")
    _fraction(r.leak_tripwire_ratio, "[recovery] leak_tripwire_ratio", closed_high=True)


def _check(cfg: PipelineConfig) -> None:
    _check_source(cfg)
    _check_calendar(cfg)
    _check_days(cfg)
    _at_least(cfg.split.min_masked_days, 1, "[split] min_masked_days")
    _check_recovery(cfg)

    _at_least(cfg.effect.ipf_iterations, 1, "[effect] ipf_iterations")
    _names(cfg.effect.versions, EFFECT_VERSION_NAMES, "[effect] versions")

    b = cfg.bootstrap
    _at_least(b.resamples, 1, "[bootstrap] resamples")
    _seed(b.seed, "[bootstrap] seed")
    _at_least(b.recovery_resamples, 1, "[bootstrap] recovery_resamples")

    _at_least(cfg.ranking.min_series, 1, "[ranking] min_series")
    _at_least(cfg.forecast.naive_days, 1, "[forecast] naive_days")

    k = cfg.criteria
    _positive(k.c02_max_abs_bias, "[criteria] c02_max_abs_bias")
    _positive(k.c03_max_abs_lift_bias, "[criteria] c03_max_abs_lift_bias")
    _fraction(k.c05_min_spearman, "[criteria] c05_min_spearman", closed_high=True)
    _fraction(k.c06_min_consistent_share, "[criteria] c06_min_consistent_share", closed_high=True)
    _fraction(k.c07_min_spearman, "[criteria] c07_min_spearman", closed_high=True)

    _positive(cfg.site.max_total_bytes, "[site] max_total_bytes")


# --- reading --------------------------------------------------------------------------------------------------------


def _deep_merge(base: dict[str, Any], top: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in top.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _read_toml(path: Path, _seen: tuple[Path, ...] = ()) -> dict[str, Any]:
    """Read a TOML file, following ``extends`` (relative to the file) and merging over its base."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"no se encontró el archivo de configuración: {path}")
    resolved = path.resolve()
    if resolved in _seen:
        raise ValueError(f"los archivos de configuración se extienden entre sí en un ciclo en {path}")
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    parent = data.pop("extends", None)
    if parent is None:
        return data
    if not isinstance(parent, str):
        raise ValueError(f"{path}: extends debe ser una ruta escrita como texto")
    parent_path = Path(parent)
    if not parent_path.is_absolute():
        parent_path = path.parent / parent_path
    return _deep_merge(_read_toml(parent_path, (*_seen, resolved)), data)


def _home() -> Path | None:
    home = os.environ.get(ENV_HOME)
    if not home:
        return None
    root = Path(home).resolve()
    if not root.is_dir():
        raise ValueError(f"{ENV_HOME}: {home!r} no es una carpeta existente")
    return root


def load_config(path: Path | None = None) -> PipelineConfig:
    """Load the configuration.

    `path` is the main file; without it, ``$PROMOLIFT_CONFIG`` and then ``config/pipeline.toml`` of the project. A relative `path` or
    ``$PROMOLIFT_CONFIG`` is taken from ``$PROMOLIFT_HOME`` or, without it, from this package's project: the working directory may be
    another copy's folder, and its configuration is never read in silence. The paths inside are resolved against ``$PROMOLIFT_HOME`` or
    the parent of the folder that holds the main file. Anything unknown, missing, mistyped or inconsistent is a ``ValueError`` naming the key.
    """
    home = _home()
    if path is None:
        env = os.environ.get(ENV_CONFIG)
        path = Path(env) if env else DEFAULT_CONFIG
    path = Path(path)
    if not path.is_absolute():
        path = (home or DEFAULT_PROJECT_ROOT) / path
    data = _read_toml(path)
    root = home or path.resolve().parent.parent

    sections = [f.name for f in dataclasses.fields(PipelineConfig) if f.name != "project_root"]
    unknown = sorted(set(data) - set(sections))
    if unknown:
        raise ValueError(f"sección desconocida [{unknown[0]}]")
    missing = [s for s in sections if s not in data]
    if missing:
        raise ValueError(f"falta la sección [{missing[0]}]")
    hints = get_type_hints(PipelineConfig)
    built = {name: _build_section(hints[name], data[name], name, root) for name in sections}
    cfg = PipelineConfig(**built, project_root=root)
    _check(cfg)
    return cfg


__all__ = [
    "DEFAULT_CONFIG", "DEFAULT_PROJECT_ROOT", "ENV_CONFIG", "ENV_HOME", "FINGERPRINT_KEYS", "UNSEALED_KEYS", "PipelineConfig", "SealedConfig",
    "config_leaves", "load_config",
]
