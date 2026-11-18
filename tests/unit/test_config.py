"""Configuration (U02): paths against the project folder, the seal's two lists of keys, the source's guarantees and every key refused
by name (RNF04, AC09, AC18 in part, AC30, AC31; D14, D17, D27)."""

from __future__ import annotations

import dataclasses
import re
from datetime import date
from pathlib import Path

import pytest

from promolift.config import (
    DEFAULT_CONFIG,
    ENV_CONFIG,
    ENV_HOME,
    FINGERPRINT_KEYS,
    UNSEALED_KEYS,
    PipelineConfig,
    SealedConfig,
    config_leaves,
    load_config,
)

PROJECT = Path(__file__).resolve().parents[2]
TRAIN_HASH = "6706832db892bbae4969c19d87e07975d2543d2ba7d7d4756360654785de5a3d"
EVAL_HASH = "1b118840664280c6b88bffc84c80ee1f54c05d911e354b7599e5da10995e960e"


def variant(tmp_path: Path, snippet: str = "", replace: tuple[str, str] | None = None, name: str = "pipeline.toml") -> Path:
    """A configuration inside `tmp_path/config/`: the real file with one textual replacement, or an ``extends`` of it plus `snippet`."""
    folder = tmp_path / "config"
    folder.mkdir(exist_ok=True)
    target = folder / name
    if replace is not None:
        text = DEFAULT_CONFIG.read_text(encoding="utf-8")
        assert replace[0] in text, f"{replace[0]!r} is not in the default configuration"
        target.write_text(text.replace(*replace, 1), encoding="utf-8")
    else:
        target.write_text(f'extends = "{DEFAULT_CONFIG.as_posix()}"\n{snippet}', encoding="utf-8")
    return target


def refused(tmp_path: Path, match: str, snippet: str = "", replace: tuple[str, str] | None = None) -> None:
    with pytest.raises(ValueError, match=match):
        load_config(variant(tmp_path, snippet, replace))


# --- the default configuration -------------------------------------------------------------------------------------


def test_default_configuration_has_the_values_of_the_plan(cfg):
    assert isinstance(cfg, PipelineConfig) and cfg.project_root == PROJECT
    s = cfg.source
    assert s.train_path == PROJECT / "data" / "raw" / "train.parquet" and s.eval_path == PROJECT / "data" / "raw" / "eval.parquet"
    assert (s.train_bytes, s.train_sha256) == (106436287, TRAIN_HASH) and (s.eval_bytes, s.eval_sha256) == (8440124, EVAL_HASH)
    assert (s.max_bytes, s.max_rows, s.max_hourly_sale) == (256 * 1024 * 1024, 6_000_000, 1000.0)
    assert s.dataset_commit == "c374e85975c82816c495acfa904cc55ab14a47d3"
    c = cfg.calendar
    assert (c.first_day, c.launch_last_day, c.last_day, c.day_hours) == (date(2024, 3, 28), date(2024, 6, 25), date(2024, 7, 2), (6, 21))
    d = cfg.days
    assert (d.regular_min_discount, d.anomalous_max_discount, d.anomalous_min_discount) == (0.999, 0.0, 1.0)
    assert d.bands == (0.0, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 1.0)
    p = cfg.split
    assert p.train == (date(2024, 3, 28), date(2024, 5, 31)) and p.purge == (date(2024, 6, 1), date(2024, 6, 7))
    assert p.valid_v1 == (date(2024, 6, 8), date(2024, 6, 16)) and p.valid_v2 == (date(2024, 6, 17), date(2024, 6, 25))
    assert p.test == (date(2024, 6, 26), date(2024, 7, 2)) and p.min_masked_days == 10000
    r = cfg.recovery
    assert r.methods == ("r1", "r2", "r3") and r.kappas == (0.25, 0.5, 1.0, 2.0)
    assert (r.mask_seed_v1, r.mask_seed_v2, r.mask_seed_test, r.mcar_hours) == (0, 1, 2, 3)
    assert (r.r3_train_days, r.r3_max_iter, r.r3_learning_rate, r.r3_max_leaf_nodes, r.r3_min_samples_leaf) == (150000, 200, 0.1, 31, 50)
    assert (r.random_state, r.leak_tripwire_ratio) == (0, 0.5)
    assert (cfg.effect.ipf_iterations, cfg.effect.versions) == (30, ("raw", "recovered"))
    assert (cfg.bootstrap.resamples, cfg.bootstrap.seed, cfg.bootstrap.recovery_resamples) == (500, 0, 500)
    assert cfg.ranking.min_series == 30 and cfg.forecast.naive_days == 7
    assert dataclasses.astuple(cfg.variants) == (True, True, True, True)
    k = cfg.criteria
    assert (k.c02_max_abs_bias, k.c03_max_abs_lift_bias, k.c05_min_spearman, k.c06_min_consistent_share, k.c07_min_spearman) == (
        0.10, 0.05, 0.80, 0.80, 0.90)
    assert cfg.site.max_total_bytes == 204800


def test_the_configuration_is_immutable(cfg):
    with pytest.raises(dataclasses.FrozenInstanceError):
        cfg.ranking.min_series = 3  # type: ignore[misc]


# --- paths (D27, RNF04, AC31) --------------------------------------------------------------------------------------


def test_relative_paths_resolve_against_project_root_from_another_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(ENV_HOME, raising=False)
    monkeypatch.delenv(ENV_CONFIG, raising=False)
    for load in (lambda: load_config(PROJECT / "config" / "pipeline.toml"), lambda: load_config(Path("config") / "pipeline.toml"), load_config):
        cfg = load()
        assert cfg.project_root == PROJECT
        for field in dataclasses.fields(cfg.paths):
            path = getattr(cfg.paths, field.name)
            assert path.is_absolute() and PROJECT in path.parents, field.name
        for path in (cfg.source.train_path, cfg.source.eval_path):
            assert path.is_absolute() and PROJECT in path.parents
        assert cfg.paths.warehouse == PROJECT / "data" / "warehouse" / "promolift.sqlite"
        assert cfg.paths.seal == PROJECT / "reports" / "model_seal.json"
    # the working directory holds another copy's configuration: it is never read in silence
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "pipeline.toml").write_text("this is not the project's configuration", encoding="utf-8")
    assert load_config(Path("config") / "pipeline.toml").project_root == PROJECT


def test_a_relative_promolift_config_is_taken_from_the_project_folder(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(ENV_HOME, raising=False)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "pipeline.quick.toml").write_text("[ranking]\nmin_series = 999\n", encoding="utf-8")
    monkeypatch.setenv(ENV_CONFIG, "config/pipeline.quick.toml")
    cfg = load_config()
    assert cfg.ranking.min_series == 5 and cfg.paths.warehouse == PROJECT / "data" / "quick" / "promolift.sqlite"


def test_promolift_home_moves_the_project_folder_and_must_exist(tmp_path, monkeypatch):
    home = tmp_path / "elsewhere"
    (home / "config").mkdir(parents=True)
    (home / "config" / "pipeline.toml").write_text(DEFAULT_CONFIG.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setenv(ENV_HOME, str(home))
    assert load_config(DEFAULT_CONFIG).paths.warehouse == home.resolve() / "data" / "warehouse" / "promolift.sqlite"
    monkeypatch.setenv(ENV_CONFIG, "config/pipeline.toml")
    assert load_config().project_root == home.resolve()
    monkeypatch.setenv(ENV_HOME, str(tmp_path / "does-not-exist"))
    with pytest.raises(ValueError, match=ENV_HOME):
        load_config(DEFAULT_CONFIG)


def test_quick_configuration_keeps_every_output_under_data_quick(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(ENV_HOME, raising=False)
    monkeypatch.delenv(ENV_CONFIG, raising=False)
    cfg = load_config(PROJECT / "config" / "pipeline.quick.toml")
    quick = PROJECT / "data" / "quick"
    assert cfg.source.train_path == quick / "train.parquet" and cfg.source.eval_path == quick / "eval.parquet"
    assert (cfg.source.train_bytes, cfg.source.train_sha256, cfg.source.eval_bytes, cfg.source.eval_sha256) == (0, "", 0, "")
    for field in dataclasses.fields(cfg.paths):
        assert quick in getattr(cfg.paths, field.name).parents, field.name
    assert (cfg.recovery.r3_train_days, cfg.recovery.r3_max_iter, cfg.bootstrap.resamples, cfg.bootstrap.recovery_resamples) == (2000, 20, 100, 100)
    assert (cfg.ranking.min_series, cfg.split.min_masked_days) == (5, 50)
    default = load_config(DEFAULT_CONFIG)
    assert (cfg.calendar, cfg.days, cfg.effect, cfg.criteria, cfg.forecast) == (default.calendar, default.days, default.effect, default.criteria,
                                                                              default.forecast)
    assert dataclasses.replace(cfg.split, min_masked_days=default.split.min_masked_days) == default.split, "the quick run replays the same calendar"


def test_a_relative_path_cannot_leave_the_project_folder(tmp_path):
    refused(tmp_path, r"\[paths\] raw_dir.*sale de la carpeta del proyecto", replace=('raw_dir = "data/raw"', 'raw_dir = "../elsewhere"'))
    refused(tmp_path, r"\[paths\] seal.*sale de la carpeta", replace=('seal = "reports/model_seal.json"', 'seal = "data/../../x.json"'))
    refused(tmp_path, r"\[source\] train_path.*sale de la carpeta", snippet='[source]\ntrain_path = "../x.parquet"\n')


def test_a_dotdot_that_stays_inside_the_project_is_normalised_and_an_absolute_path_is_kept(tmp_path):
    path = variant(tmp_path, replace=('raw_dir = "data/raw"', 'raw_dir = "data/quick/../raw"'))
    assert load_config(path).paths.raw_dir == tmp_path / "data" / "raw"
    outside = (tmp_path / "outside").as_posix()
    path = variant(tmp_path, replace=('raw_dir = "data/raw"', f'raw_dir = "{outside}"'))
    assert load_config(path).paths.raw_dir == Path(outside)


def test_an_empty_path_is_refused(tmp_path):
    refused(tmp_path, r"\[paths\] figures_dir.*texto vacío", replace=('figures_dir = "docs/figures"', 'figures_dir = ""'))


# --- the seal's keys (D17, AC18) -----------------------------------------------------------------------------------


def test_every_config_key_is_fingerprinted_or_declared_unsealed():
    leaves = [leaf for leaf in config_leaves(PipelineConfig) if leaf != "project_root"]
    assert len(leaves) == len(set(leaves)) and len(leaves) > 60
    fingerprinted, unsealed = set(FINGERPRINT_KEYS), set(UNSEALED_KEYS)
    assert len(FINGERPRINT_KEYS) == len(fingerprinted) and len(UNSEALED_KEYS) == len(unsealed), "a key is listed twice"
    assert fingerprinted & unsealed == set(), "a key is both fingerprinted and declared unsealed"
    assert sorted(set(leaves) - fingerprinted - unsealed) == [], "a key is neither fingerprinted nor declared unsealed"
    assert sorted((fingerprinted | unsealed) - set(leaves)) == [], "a listed key is not in the configuration"
    # the plan, section 4: [source] enters only with its dataset commit; every key of these sections enters; [site] and [paths] stay out
    for section in ("calendar", "days", "split", "recovery", "effect", "bootstrap", "ranking", "forecast", "variants", "criteria"):
        assert {leaf for leaf in leaves if leaf.startswith(f"{section}.")} <= fingerprinted, section
    assert {leaf for leaf in fingerprinted if leaf.startswith("source.")} == {"source.dataset_commit"}
    assert {leaf for leaf in leaves if leaf.startswith(("site.", "paths."))} <= unsealed
    assert {"source.train_path", "source.train_bytes", "source.train_sha256", "source.eval_path", "source.eval_bytes", "source.eval_sha256",
            "source.max_bytes", "source.max_rows", "source.max_hourly_sale"} <= unsealed


def test_the_sealed_view_holds_exactly_the_fingerprinted_keys_and_the_two_observed_hashes(cfg):
    assert set(config_leaves(SealedConfig)) == set(FINGERPRINT_KEYS) | {"train_sha256_seen", "eval_sha256_seen"}
    view = SealedConfig.of(cfg, TRAIN_HASH, EVAL_HASH)
    for key in FINGERPRINT_KEYS:
        section, name = key.split(".")
        assert getattr(getattr(view, section), name) == getattr(getattr(cfg, section), name), key
    assert (view.train_sha256_seen, view.eval_sha256_seen) == (TRAIN_HASH, EVAL_HASH)
    assert not any(hasattr(view, name) for name in ("paths", "site")) and not hasattr(view.source, "train_path")
    for bad in (TRAIN_HASH.upper(), TRAIN_HASH[:-1], ""):
        with pytest.raises(ValueError, match="train_sha256_seen"):
            SealedConfig.of(cfg, bad, EVAL_HASH)
        with pytest.raises(ValueError, match="eval_sha256_seen"):
            SealedConfig.of(cfg, TRAIN_HASH, bad)


# --- the source (RF01, V01-V03) ------------------------------------------------------------------------------------


def test_an_empty_accepted_hash_is_allowed_only_for_a_source_under_data_quick(tmp_path):
    for which in ("train", "eval"):
        empty = f'[source]\n{which}_sha256 = ""\n{which}_bytes = 0\n'
        refused(tmp_path, rf"\[source\] {which}_sha256.*data/quick", snippet=empty)
        quick = tmp_path / "data" / "quick" / "x.parquet"
        assert getattr(load_config(variant(tmp_path, snippet=empty + f'{which}_path = "{quick.as_posix()}"\n')).source, f"{which}_sha256") == ""
        assert getattr(load_config(variant(tmp_path, snippet=empty + f'{which}_path = "data/quick/x.parquet"\n')).source, f"{which}_path") == quick
        refused(tmp_path, rf"\[source\] {which}_sha256.*data/quick", snippet=empty + f'{which}_path = "data/quick_not/x.parquet"\n')


@pytest.mark.parametrize("bad", [TRAIN_HASH.upper(), TRAIN_HASH[:-1], TRAIN_HASH + "0", "z" * 64, " " + TRAIN_HASH])
def test_an_accepted_hash_is_64_lower_case_hex_characters(tmp_path, bad):
    refused(tmp_path, r"\[source\] train_sha256.*64 caracteres", snippet=f'[source]\ntrain_sha256 = "{bad}"\n')
    refused(tmp_path, r"\[source\] eval_sha256.*64 caracteres", snippet=f'[source]\neval_sha256 = "{bad}"\n')


def test_the_accepted_size_and_hash_go_together(tmp_path):
    refused(tmp_path, r"\[source\] train_bytes.*0", snippet='[source]\ntrain_sha256 = ""\ntrain_bytes = 5\ntrain_path = "data/quick/x.parquet"\n')
    refused(tmp_path, r"\[source\] eval_bytes.*mayor que 0", snippet="[source]\neval_bytes = 0\n")
    refused(tmp_path, r"\[source\] train_bytes.*max_bytes", snippet="[source]\ntrain_bytes = 268435457\n")
    refused(tmp_path, r"\[source\] eval_bytes.*max_bytes", snippet="[source]\neval_bytes = 268435457\n")


@pytest.mark.parametrize("snippet", ['[source]\ndataset_commit = ""\n', '[source]\ndataset_commit = "c374e859"\n', '[source]\ndataset_commit = "' + "G" * 40 + '"\n'])
def test_the_dataset_commit_is_40_lower_case_hex_characters(tmp_path, snippet):
    refused(tmp_path, r"\[source\] dataset_commit.*40 caracteres", snippet=snippet)


def test_the_two_source_files_are_two_files(tmp_path):
    refused(tmp_path, r"\[source\] eval_path.*train_path", snippet='[source]\neval_path = "data/raw/train.parquet"\n')


# --- mistakes in the file are named (AC30) ---------------------------------------------------------------------------


def test_unknown_key_is_rejected_with_its_name(tmp_path):
    refused(tmp_path, r"\[ranking\].*'min_serie'", snippet="[ranking]\nmin_serie = 30\n")
    refused(tmp_path, r"\[bootstrap\].*'resample'", snippet="[bootstrap]\nresample = 500\n")
    refused(tmp_path, r"\[site\].*'cors'", snippet='[site]\ncors = "*"\n')


def test_unknown_section_missing_section_and_missing_key_are_named(tmp_path):
    refused(tmp_path, r"sección desconocida \[extras\]", snippet="[extras]\nx = 1\n")
    text = DEFAULT_CONFIG.read_text(encoding="utf-8")
    without_site = re.sub(r"\[site\].*?(?=\[paths\])", "", text, flags=re.S)
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "config" / "a.toml").write_text(without_site, encoding="utf-8")
    with pytest.raises(ValueError, match=r"falta la sección \[site\]"):
        load_config(tmp_path / "config" / "a.toml")
    refused(tmp_path, r"\[ranking\]: falta la clave 'min_series'", replace=("min_series = 30", ""))


@pytest.mark.parametrize(("snippet", "match"), [
    ('[ranking]\nmin_series = "30"\n', r"\[ranking\] min_series.*un entero"),
    ("[ranking]\nmin_series = true\n", r"\[ranking\] min_series.*un entero"),
    ("[effect]\nipf_iterations = 30.5\n", r"\[effect\] ipf_iterations.*un entero"),
    ("[recovery]\nr3_learning_rate = 'fast'\n", r"\[recovery\] r3_learning_rate.*un número"),
    ("[recovery]\nkappas = 0.25\n", r"\[recovery\] kappas.*una lista"),
    ('[recovery]\nkappas = ["a"]\n', r"\[recovery\] kappas.*un número"),
    ('[calendar]\nfirst_day = "2024-03-28"\n', r"\[calendar\] first_day.*una fecha"),
    ("[calendar]\nlast_day = 2024-07-02T00:00:00\n", r"\[calendar\] last_day.*una fecha"),
    ("[calendar]\nlast_day = 2024-07-02T00:00:00Z\n", r"\[calendar\] last_day.*una fecha"),
    ('[split]\ntrain = ["2024-03-28", "2024-05-31"]\n', r"\[split\] train.*una fecha"),
    ("[split]\ntrain = 2024-03-28\n", r"\[split\] train.*una lista"),
    ("[paths]\nraw_dir = 3\n", r"\[paths\] raw_dir.*ruta"),
    ('[variants]\nmcar_mask = "yes"\n', r"\[variants\] mcar_mask.*verdadero o falso"),
    ('[days]\nbands = "0.5"\n', r"\[days\] bands.*una lista"),
    ("[source]\nmax_hourly_sale = 'a lot'\n", r"\[source\] max_hourly_sale.*un número"),
])
def test_a_value_of_the_wrong_type_is_named(tmp_path, snippet, match):
    refused(tmp_path, match, snippet=snippet)


def test_extends_cycle_and_missing_base_are_refused(tmp_path):
    folder = tmp_path / "config"
    folder.mkdir()
    (folder / "a.toml").write_text('extends = "b.toml"\n', encoding="utf-8")
    (folder / "b.toml").write_text('extends = "a.toml"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="ciclo"):
        load_config(folder / "a.toml")
    (folder / "c.toml").write_text('extends = "nothing.toml"\n', encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        load_config(folder / "c.toml")
    with pytest.raises(FileNotFoundError):
        load_config(folder / "absent.toml")


# --- numeric bounds, names and lists: every limit has a test with its invalid values -----------------------------------


@pytest.mark.parametrize(("section", "key", "bad"), [
    ("source", "max_bytes", 0), ("source", "max_rows", 0), ("source", "max_hourly_sale", 0.0), ("source", "max_hourly_sale", -1.0),
    ("split", "min_masked_days", 0),
    ("days", "regular_min_discount", 0.0), ("days", "regular_min_discount", 1.5),
    ("recovery", "mask_seed_v1", -1), ("recovery", "mask_seed_v2", 2**32), ("recovery", "mask_seed_test", -1), ("recovery", "mcar_hours", 0),
    ("recovery", "mcar_hours", 17), ("recovery", "r3_train_days", 0), ("recovery", "r3_max_iter", 0), ("recovery", "r3_learning_rate", 0.0),
    ("recovery", "r3_learning_rate", -0.1), ("recovery", "r3_max_leaf_nodes", 1), ("recovery", "r3_min_samples_leaf", 0),
    ("recovery", "random_state", -1), ("recovery", "random_state", 2**32), ("recovery", "leak_tripwire_ratio", 0.0),
    ("recovery", "leak_tripwire_ratio", 1.5),
    ("effect", "ipf_iterations", 0),
    ("bootstrap", "resamples", 0), ("bootstrap", "seed", -1), ("bootstrap", "recovery_resamples", 0),
    ("ranking", "min_series", 0), ("forecast", "naive_days", 0),
    ("criteria", "c02_max_abs_bias", 0.0), ("criteria", "c03_max_abs_lift_bias", 0.0), ("criteria", "c05_min_spearman", 0.0),
    ("criteria", "c05_min_spearman", 1.5), ("criteria", "c06_min_consistent_share", 0.0), ("criteria", "c06_min_consistent_share", 1.5),
    ("criteria", "c07_min_spearman", 0.0), ("criteria", "c07_min_spearman", 1.5),
    ("site", "max_total_bytes", 0),
])
def test_numeric_bounds_reject_their_invalid_values_naming_the_key(tmp_path, section, key, bad):
    refused(tmp_path, rf"\[{section}\] {key}", snippet=f"[{section}]\n{key} = {bad}\n")


def test_the_edges_of_the_valid_ranges_are_accepted(tmp_path):
    ok = ("[recovery]\nmcar_hours = 16\nleak_tripwire_ratio = 1.0\nr3_max_leaf_nodes = 2\n[criteria]\nc05_min_spearman = 1.0\n"
          "c07_min_spearman = 1.0\nc06_min_consistent_share = 1.0\n[days]\nregular_min_discount = 1.0\n[bootstrap]\nseed = 4294967295\n")
    cfg = load_config(variant(tmp_path, snippet=ok))
    assert cfg.recovery.mcar_hours == 16 and cfg.days.regular_min_discount == 1.0 and cfg.bootstrap.seed == 2**32 - 1


@pytest.mark.parametrize(("snippet", "match"), [
    ('[recovery]\nmethods = []\n', r"\[recovery\] methods"),
    ('[recovery]\nmethods = ["r1", "r4"]\n', r"\[recovery\] methods.*r4"),
    ('[recovery]\nmethods = ["r1", "r1"]\n', r"\[recovery\] methods"),
    ("[recovery]\nkappas = []\n", r"\[recovery\] kappas"),
    ("[recovery]\nkappas = [0.25, 0.0]\n", r"\[recovery\] kappas"),
    ("[recovery]\nkappas = [0.25, -1.0]\n", r"\[recovery\] kappas"),
    ("[recovery]\nkappas = [0.25, 0.25]\n", r"\[recovery\] kappas.*repetidos"),
    ('[effect]\nversions = []\n', r"\[effect\] versions"),
    ('[effect]\nversions = ["raw", "weird"]\n', r"\[effect\] versions.*weird"),
    ('[effect]\nversions = ["raw", "raw"]\n', r"\[effect\] versions"),
    ('[effect]\nversions = ["raw"]\n', r"\[effect\] versions.*\['raw', 'recovered'\]"),             # B2 (L85, D47): a value the flow would not honor
    ('[effect]\nversions = ["recovered"]\n', r"\[effect\] versions.*\['raw', 'recovered'\]"),
    ('[effect]\nversions = ["recovered", "raw"]\n', r"\[effect\] versions.*\['raw', 'recovered'\]"),
    ("[days]\nbands = []\n", r"\[days\] bands"),
    ("[days]\nbands = [0.0, 0.5, 0.5, 1.0]\n", r"\[days\] bands.*crecientes"),
    ("[days]\nbands = [0.0, 0.7, 0.6, 1.0]\n", r"\[days\] bands.*crecientes"),
    ("[days]\nbands = [0.1, 0.5, 1.0]\n", r"\[days\] bands.*empezar en 0"),
    ("[days]\nbands = [0.0, 0.5, 0.9]\n", r"\[days\] bands.*terminar en 1"),
    ("[days]\nbands = [0.0]\n", r"\[days\] bands"),
    ("[days]\nanomalous_max_discount = 0.5\nregular_min_discount = 0.4\n", r"\[days\] anomalous_max_discount"),
    ("[days]\nanomalous_min_discount = 0.9\n", r"\[days\] anomalous_min_discount"),
    ("[calendar]\nday_hours = [6]\n", r"\[calendar\] day_hours.*dos"),
    ("[calendar]\nday_hours = [6, 21, 22]\n", r"\[calendar\] day_hours.*dos"),
    ("[calendar]\nday_hours = [21, 6]\n", r"\[calendar\] day_hours.*desordenadas"),
    ("[calendar]\nday_hours = [-1, 21]\n", r"\[calendar\] day_hours.*0 a 23"),
    ("[calendar]\nday_hours = [6, 24]\n", r"\[calendar\] day_hours.*0 a 23"),
])
def test_grids_names_and_lists_are_checked(tmp_path, snippet, match):
    refused(tmp_path, match, snippet=snippet)


# --- the calendar and the blocks of D14 (RF05, AC09) -----------------------------------------------------------------------


@pytest.mark.parametrize(("snippet", "match"), [
    ("[split]\ntrain = [2024-05-31, 2024-03-28]\n", r"\[split\] train.*desordenado"),
    ("[split]\ntrain = [2024-03-28]\n", r"\[split\] train.*dos fechas"),
    ("[split]\ntrain = [2024-03-28, 2024-06-03]\n", r"borde train → purge"),
    ("[split]\npurge = [2024-05-31, 2024-06-07]\n", r"borde train → purge"),
    ("[split]\nvalid_v1 = [2024-06-07, 2024-06-16]\n", r"borde purge → valid_v1"),
    ("[split]\nvalid_v1 = [2024-06-08, 2024-06-17]\n", r"borde valid_v1 → valid_v2"),
    ("[split]\nvalid_v2 = [2024-06-16, 2024-06-25]\n", r"borde valid_v1 → valid_v2"),
    ("[split]\nvalid_v2 = [2024-06-17, 2024-06-26]\n", r"borde valid_v2 → test"),
    ("[split]\ntest = [2024-06-25, 2024-07-02]\n", r"borde valid_v2 → test"),
    ("[split]\ntrain = [2024-03-27, 2024-05-31]\n", r"\[split\] train.*first_day"),
    ("[split]\ntest = [2024-06-26, 2024-07-03]\n", r"\[split\] test.*last_day"),
    ("[split]\ntest = [2024-06-27, 2024-07-02]\n", r"\[split\] test.*launch_last_day"),
    ("[split]\ntest = [2024-06-26, 2024-07-01]\n", r"\[split\] test.*last_day"),
    ("[calendar]\nfirst_day = 2024-07-03\n", r"\[calendar\] first_day"),
    ("[calendar]\nlaunch_last_day = 2024-07-02\n", r"\[calendar\] launch_last_day"),
    ("[calendar]\nlaunch_last_day = 2024-06-24\n", r"\[split\] valid_v2.*launch_last_day"),
])
def test_the_calendar_is_checked_with_the_name_of_the_boundary(tmp_path, snippet, match):
    refused(tmp_path, match, snippet=snippet)


def test_every_split_date_is_used_by_the_check(tmp_path):
    """Moving any one date of [split] outside its place is refused: none is accepted and then ignored."""
    moved = {
        "train": "[2024-03-27, 2024-05-31]", "purge": "[2024-05-31, 2024-06-07]", "valid_v1": "[2024-06-07, 2024-06-16]",
        "valid_v2": "[2024-06-16, 2024-06-25]", "test": "[2024-06-25, 2024-07-02]",
    }
    for key, value in moved.items():
        with pytest.raises(ValueError, match=r"\[split\]|borde"):
            load_config(variant(tmp_path, snippet=f"[split]\n{key} = {value}\n"))
    assert load_config(variant(tmp_path, snippet="[split]\nvalid_v1 = [2024-06-08, 2024-06-15]\n")).split.valid_v1[1] == date(2024, 6, 15)
