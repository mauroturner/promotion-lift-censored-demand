"""The strict reader and the canonical tables (U04; RF01-RF03, V01-V07, V26, V27; AC01-AC03): the pinned files, what is read and what is not,
the canonical series, series-days and day tensors, and their manifest written last."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from promolift import ingest
from promolift.cube import open_cube
from promolift.ingest import (
    INTERIM_MANIFEST,
    LOCK_NAME,
    InterimError,
    SourceFrames,
    canonical_state,
    check_source,
    read_canonical,
    read_source,
    read_source_lock,
    write_canonical,
    write_source_lock,
)
from promolift.schema import FORBIDDEN_COLUMNS, SourceError
from tests.fixtures.make_fixture import STATE_NAMES, UNFLAGGED, damaged_pair, make_fixture, replace_column


def sha(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- V01, V03: the pinned files ------------------------------------------------------------------------------------------------


def test_check_source_returns_the_two_hashes_of_the_accepted_files(cfg_for, small_truth):
    config = cfg_for(small_truth.dir)
    assert check_source(config) == (small_truth.train_sha256, small_truth.eval_sha256)


def test_a_missing_file_is_refused_with_the_runbook_and_writes_nothing(cfg_for, small_truth, tmp_path):
    config = cfg_for(small_truth.dir, train_path=tmp_path / "nowhere" / "train.parquet")
    with pytest.raises(SourceError, match=r"V01.*no existe.*R1") as raised:
        check_source(config)
    assert raised.value.rule_id == "V01" and raised.value.problems[0]["reason"] == "missing" and not (tmp_path / "nowhere").exists()
    config = cfg_for(small_truth.dir, eval_path=tmp_path / "eval-nowhere.parquet")
    with pytest.raises(SourceError, match=r"V01.*eval-nowhere.*R1"):
        check_source(config)


def test_a_file_of_another_size_is_refused_before_it_is_hashed(cfg_for, small_truth, monkeypatch):
    config = cfg_for(small_truth.dir, eval_bytes=small_truth.eval_bytes + 1)
    monkeypatch.setattr(ingest, "sha256_file", lambda *a, **k: pytest.fail("a file of another size must never be hashed"))
    with pytest.raises(SourceError, match=r"V01.*pesa .* y se aceptan .*R1") as raised:
        check_source(config)
    assert raised.value.problems[0]["reason"] == "size" and raised.value.problems[0]["expected"] == small_truth.eval_bytes + 1


def test_a_file_with_the_same_size_and_another_hash_is_refused(cfg_for, small_truth, tmp_path):
    folder = tmp_path / "flipped"
    folder.mkdir()
    data = bytearray(small_truth.train_path.read_bytes())
    data[len(data) // 2] ^= 0x01
    (folder / "train.parquet").write_bytes(bytes(data))
    (folder / "eval.parquet").write_bytes(small_truth.eval_path.read_bytes())
    config = cfg_for(small_truth.dir, train_path=folder / "train.parquet", eval_path=folder / "eval.parquet")
    with pytest.raises(SourceError, match=r"V01.*huella SHA-256.*no se cambió nada") as raised:
        check_source(config)
    assert raised.value.problems[0]["reason"] == "sha256" and (folder / "train.parquet").read_bytes() == bytes(data)


def test_a_file_over_the_cap_is_refused_by_its_size_and_the_rows_cap_before_any_data_is_read(cfg_for, small_truth, monkeypatch):
    config = cfg_for(small_truth.dir, max_bytes=small_truth.eval_bytes + 10)
    with pytest.raises(SourceError, match=r"V03.*por encima del límite de \d+") as raised:
        check_source(config)                        # the train file is bigger than the eval one
    assert raised.value.rule_id == "V03" and raised.value.problems[0]["size"] == small_truth.train_bytes
    config = cfg_for(small_truth.dir, max_rows=small_truth.n_series * 90 - 1)
    monkeypatch.setattr(pq.ParquetFile, "iter_batches", lambda *a, **k: pytest.fail("no data may be read when the footer says too many rows"))
    with pytest.raises(SourceError, match=r"V03.*filas"):
        read_source(small_truth.train_path, "train", config)


def test_the_quick_mode_registers_the_first_hashes_and_refuses_other_ones_later(cfg_for, small_truth, tmp_path, copy_of):
    own = copy_of(small_truth.dir)                  # the registry is written next to the files: never into the session's folder
    quick = cfg_for(own, train_bytes=0, train_sha256="", eval_bytes=0, eval_sha256="")
    lock = quick.source.train_path.parent / LOCK_NAME
    assert read_source_lock(lock) is None and check_source(quick) == (small_truth.train_sha256, small_truth.eval_sha256)
    assert not lock.exists(), "checking registers nothing: fetch_source does, after the files were read without a failing rule"
    write_source_lock(lock, {"train": (small_truth.train_sha256, small_truth.train_bytes), "eval": (small_truth.eval_sha256, small_truth.eval_bytes)})
    document = json.loads(lock.read_text(encoding="utf-8"))
    assert document == {"version": 1, "files": {"train": {"sha256": small_truth.train_sha256, "size": small_truth.train_bytes},
                                                "eval": {"sha256": small_truth.eval_sha256, "size": small_truth.eval_bytes}}}
    assert read_source_lock(lock) == document and check_source(quick) == (small_truth.train_sha256, small_truth.eval_sha256)
    other = make_fixture(tmp_path / "other", series=60, seed=5)
    changed = dataclasses.replace(quick, source=dataclasses.replace(quick.source, train_path=other.train_path, eval_path=other.eval_path))
    (other.dir / LOCK_NAME).write_bytes(lock.read_bytes())
    with pytest.raises(SourceError, match=r"V01.*registrada.*no se cambió nada"):
        check_source(changed)
    for bad in ('{"version": 2}', "not json", '{"version": 1, "files": {"train": {"sha256": "x", "size": 1}}}', "[]"):
        (other.dir / LOCK_NAME).write_text(bad, encoding="utf-8")
        with pytest.raises(SourceError, match=r"V01.*registro válido"):
            check_source(changed)


# --- V02-V07, V26, V27: the strict reader ------------------------------------------------------------------------------------------------


def test_read_source_returns_the_frames_and_what_it_saw(cfg_for, small_truth):
    config = cfg_for(small_truth.dir)
    frames, report = read_source(small_truth.train_path, "train", config)
    assert isinstance(frames, SourceFrames) and frames.split == "train" and len(frames.sales) == 60 * 90
    assert (report.split, report.rows, report.series, report.days) == ("train", 60 * 90, 60, 90)
    assert report.first_day.isoformat() == "2024-03-28" and report.last_day.isoformat() == "2024-06-25"
    assert report.size_bytes == small_truth.train_bytes and report.row_groups == -(-60 * 90 // 1000)
    assert (report.sale_amount_mismatch, report.stock_count_mismatch) == (0, 0)
    assert frames.sales.dtype == np.float32 and frames.stock.dtype == np.int8 and frames.sales.shape == frames.stock.shape == (5400, 24)
    assert frames.discount.dtype == np.float64 and frames.flag.dtype == np.int8 and frames.holiday.dtype == np.int8
    assert frames.date_key.dtype == np.int32 and list(frames.ids.columns) == ["city_id", "store_id", "management_group_id", "first_category_id",
                                                                             "second_category_id", "third_category_id", "product_id"]
    eval_frames, eval_report = read_source(small_truth.eval_path, "eval", config)
    assert (eval_report.rows, eval_report.days, eval_report.first_day.isoformat(), eval_report.last_day.isoformat()) == (60 * 7, 7, "2024-06-26", "2024-07-02")
    assert not (set(FORBIDDEN_COLUMNS) & {f.name for f in dataclasses.fields(frames)}) and eval_frames.split == "eval"


def test_the_two_identities_that_differ_are_counted_and_not_refused(cfg_for, small_truth, tmp_path):
    def tamper(table):
        amounts = table.column("sale_amount").to_numpy().copy()
        amounts[[0, 7, 100]] += 1.0
        counts = table.column("stock_hour6_22_cnt").to_numpy().copy()
        counts[[3, 4]] = (counts[[3, 4]] + 1) % 17
        return replace_column(replace_column(table, "sale_amount", pa.array(amounts)), "stock_hour6_22_cnt", pa.array(counts, type=pa.int32()))

    folder = damaged_pair(small_truth, tmp_path / "ident", tamper)
    _frames, report = read_source(folder / "train.parquet", "train", cfg_for(folder))
    assert (report.sale_amount_mismatch, report.stock_count_mismatch) == (3, 2)


def test_only_the_columns_the_pipeline_uses_are_read_and_the_weather_never(cfg_for, small_truth, monkeypatch):
    asked: list[list[str]] = []
    real = pq.ParquetFile.iter_batches

    def spy(self, *args, **kwargs):
        asked.append(list(kwargs.get("columns") or []))
        return real(self, *args, **kwargs)

    monkeypatch.setattr(pq.ParquetFile, "iter_batches", spy)
    read_source(small_truth.train_path, "train", cfg_for(small_truth.dir))
    assert asked, "the reader goes through iter_batches"
    read = set().union(*map(set, asked))
    assert not read & {"precpt", "avg_temperature", "avg_humidity", "avg_wind_level"}, "the weather never leaves the file"
    assert read & set(FORBIDDEN_COLUMNS) == {"sale_amount", "stock_hour6_22_cnt"}, "only the two sums, to count V26 and V27, and never kept"
    assert {"hours_sale", "hours_stock_status", "discount", "activity_flag", "holiday_flag", "dt", "store_id", "product_id"} <= read


def test_the_order_of_the_rows_does_not_matter(cfg_for, small_truth, tmp_path, canonical):
    def shuffle(table):
        return table.take(pa.array(np.random.default_rng(1).permutation(len(table))))

    folder = damaged_pair(small_truth, tmp_path / "shuffled", shuffle)
    config = cfg_for(folder)
    train, _ = read_source(folder / "train.parquet", "train", config)
    eval_, _ = read_source(folder / "eval.parquet", "eval", config)
    shuffled = ingest.canonical((train, eval_), config)
    base_config = cfg_for(small_truth.dir)
    base_train, _ = read_source(small_truth.train_path, "train", base_config)
    base_eval, _ = read_source(small_truth.eval_path, "eval", base_config)
    ordered = ingest.canonical((base_train, base_eval), base_config)
    assert np.array_equal(shuffled.sales, ordered.sales) and np.array_equal(shuffled.stock, ordered.stock)
    assert shuffled.series.equals(ordered.series) and shuffled.series_days.equals(ordered.series_days)
    assert canonical is not None


@pytest.mark.parametrize(("column", "make", "match"), [
    ("discount", lambda t: pa.array(np.where(np.arange(len(t)) == 2, np.nan, t.column("discount").to_numpy())), r"V04.*discount"),
    ("discount", lambda t: pa.array([None if i == 2 else v for i, v in enumerate(t.column("discount").to_pylist())]), r"V04.*discount"),
    ("discount", lambda t: pa.array(np.where(np.arange(len(t)) == 2, np.inf, t.column("discount").to_numpy())), r"V04.*discount"),
    ("activity_flag", lambda t: pa.array(np.where(np.arange(len(t)) == 2, 2, t.column("activity_flag").to_numpy()), type=pa.int32()),
     r"V04.*activity_flag"),
    ("holiday_flag", lambda t: pa.array(np.where(np.arange(len(t)) == 2, -1, t.column("holiday_flag").to_numpy()), type=pa.int32()),
     r"V04.*holiday_flag"),
    ("store_id", lambda t: pa.array([None if i == 2 else v for i, v in enumerate(t.column("store_id").to_pylist())], type=pa.int64()),
     r"V04.*store_id"),
    ("product_id", lambda t: pa.array(np.where(np.arange(len(t)) == 2, -5, t.column("product_id").to_numpy()), type=pa.int64()), r"V04.*product_id"),
    ("dt", lambda t: pa.array([None if i == 2 else v for i, v in enumerate(t.column("dt").to_pylist())]), r"V04.*dt|V05.*dt"),
])
def test_the_daily_fields_the_pipeline_keeps_are_checked_too(cfg_for, small_truth, tmp_path, column, make, match):
    folder = damaged_pair(small_truth, tmp_path / f"daily_{column}", lambda table: replace_column(table, column, make(table)))
    with pytest.raises(SourceError, match=match):
        read_source(folder / "train.parquet", "train", cfg_for(folder))


@pytest.mark.parametrize("bad", ["2024-3-28", "20240328", "2024-02-30", "2024-03-28 ", "", "abc"])
def test_a_date_that_is_not_yyyy_mm_dd_is_refused_by_rule_v05(cfg_for, small_truth, tmp_path, bad):
    folder = damaged_pair(small_truth, tmp_path / "date", lambda t: replace_column(
        t, "dt", pa.array([bad if i == 0 else v for i, v in enumerate(t.column("dt").to_pylist())])))
    with pytest.raises(SourceError, match=r"V05.*dt") as raised:
        read_source(folder / "train.parquet", "train", cfg_for(folder))
    assert raised.value.rule_id == "V05"


def test_each_file_must_hold_the_days_of_its_own_window(cfg_for, small_truth):
    config = cfg_for(small_truth.dir)
    with pytest.raises(SourceError, match=r"V05.*ventana de eval \(2024-06-26 a 2024-07-02\)"):
        read_source(small_truth.train_path, "eval", config)
    with pytest.raises(SourceError, match=r"V05.*ventana"):
        read_source(small_truth.eval_path, "train", config)
    with pytest.raises(ValueError, match="split"):
        read_source(small_truth.train_path, "validation", config)


def test_a_file_that_is_not_a_parquet_is_refused_without_reading_data(cfg_for, small_truth, tmp_path):
    folder = tmp_path / "junk"
    folder.mkdir()
    (folder / "train.parquet").write_bytes(b"not a parquet file at all" * 100)
    (folder / "eval.parquet").write_bytes(small_truth.eval_path.read_bytes())
    with pytest.raises(SourceError, match=r"V02.*Parquet"):
        read_source(folder / "train.parquet", "train", cfg_for(folder))
    data = small_truth.train_path.read_bytes()
    (folder / "train.parquet").write_bytes(data[: len(data) // 2])
    with pytest.raises(SourceError, match=r"V02.*Parquet"):
        read_source(folder / "train.parquet", "train", cfg_for(folder))


# --- the canonical tables ----------------------------------------------------------------------------------------------------------


def test_the_canonical_tensors_are_the_hours_the_files_say_in_the_order_of_the_series(canonical, fixture_truth):
    t, c = fixture_truth, canonical
    assert c.sales.shape == c.stock.shape == (300, 97, 24) and c.sales.dtype == np.float32 and c.stock.dtype == np.int8
    assert np.array_equal(c.sales, t.sales.astype(np.float32)) and np.array_equal(c.stock, t.stock)
    assert c.date_keys.dtype == np.int32 and c.date_keys[0] == 20240328 and c.date_keys[-1] == 20240702 and len(c.date_keys) == 97
    assert c.series.columns.tolist() == ["series_key", *t.series.columns.tolist()] and c.series["series_key"].dtype == np.int32
    assert c.series["series_key"].tolist() == list(range(300)) and c.series.drop(columns="series_key").equals(t.series)


def test_the_series_days_carry_the_state_the_band_and_no_forbidden_column(canonical, fixture_truth):
    t, sd = fixture_truth, canonical.series_days
    assert sd.columns.tolist() == ["series_key", "date_key", "activity_flag", "discount", "holiday_flag", "day_state", "band"]
    assert len(sd) == 300 * 97 and not set(sd.columns) & set(FORBIDDEN_COLUMNS)
    assert sd["day_state"].dtype == np.int8 and sd["band"].dtype == np.int8 and sd["series_key"].dtype == np.int32 and sd["date_key"].dtype == np.int32
    assert sd[["date_key", "series_key"]].equals(sd[["date_key", "series_key"]].sort_values(["date_key", "series_key"]).reset_index(drop=True))
    by_day = sd.sort_values(["series_key", "date_key"])
    assert np.array_equal(by_day["day_state"].to_numpy().reshape(300, 97), t.state) and np.array_equal(by_day["band"].to_numpy().reshape(300, 97), t.band)
    assert np.array_equal(by_day["discount"].to_numpy().reshape(300, 97), t.discount) and np.array_equal(by_day["activity_flag"].to_numpy().reshape(300, 97), t.flag)
    assert np.array_equal(by_day["holiday_flag"].to_numpy().reshape(300, 97)[0], t.holiday)


def test_the_counts_are_the_ones_of_the_truth(canonical, fixture_truth):
    counts, expected = canonical.counts, fixture_truth.rule_counts()
    assert counts["series"] == 300 and counts["days"] == 97 and counts["series_days"] == expected["series_days"] == 300 * 97
    assert counts["rows"] == {"train": 300 * 90, "eval": 300 * 7}
    assert counts["day_state"] == expected["day_state"] and counts["day_state"]["unflagged_cut"] == expected["unflagged_cut"]
    for key in ("discount_zero", "discount_above_one", "discount_below_half", "flag_with_no_discount"):
        assert counts[key] == expected[key], key
    assert STATE_NAMES[UNFLAGGED] == "unflagged_cut"


def test_two_files_whose_series_differ_are_refused_by_rule_v07(cfg_for, small_truth, tmp_path):
    other = make_fixture(tmp_path / "forty_five", series=45, seed=0)
    config = cfg_for(small_truth.dir)
    train, _ = read_source(small_truth.train_path, "train", config)
    eval_, _ = read_source(other.eval_path, "eval", cfg_for(other.dir))
    with pytest.raises(SourceError, match=r"V07.*series"):
        ingest.canonical((train, eval_), config)


def test_the_frames_must_be_train_then_eval_and_cover_the_calendar_without_overlap(cfg_for, small_truth):
    config = cfg_for(small_truth.dir)
    train, _ = read_source(small_truth.train_path, "train", config)
    eval_, _ = read_source(small_truth.eval_path, "eval", config)
    with pytest.raises(ValueError, match="train.*eval"):
        ingest.canonical((eval_, train), config)
    with pytest.raises(ValueError, match="train.*eval"):
        ingest.canonical((train,), config)
    gap = dataclasses.replace(eval_, split="eval", date_key=np.where(eval_.date_key == 20240626, 20240627, eval_.date_key).astype(np.int32))
    with pytest.raises(SourceError, match=r"V05"):
        ingest.canonical((train, gap), config)


# --- the manifest, written last --------------------------------------------------------------------------------------------------------


@pytest.fixture
def written(small_truth, cfg_for, tmp_path):
    config = cfg_for(small_truth.dir)
    train, _ = read_source(small_truth.train_path, "train", config)
    eval_, _ = read_source(small_truth.eval_path, "eval", config)
    canon = ingest.canonical((train, eval_), config)
    folder = tmp_path / "interim"
    write_canonical(canon, folder, small_truth.train_sha256, small_truth.eval_sha256)
    return folder, canon, config


def test_the_canonical_files_are_written_and_their_manifest_names_each_one(written, small_truth):
    folder, canon, _config = written
    manifest = json.loads((folder / INTERIM_MANIFEST).read_text(encoding="utf-8"))
    assert set(manifest) == {"version", "train_sha256", "eval_sha256", "counts", "files"} and manifest["version"] == 1
    assert (manifest["train_sha256"], manifest["eval_sha256"]) == (small_truth.train_sha256, small_truth.eval_sha256)
    names = {"series.parquet", "series_days.parquet"} | {f"canonical/{key}.{field}.npy" for key in canon.date_keys.tolist() for field in ("sales", "stock")}
    assert set(manifest["files"]) == names and len(names) == 2 + 2 * 97
    assert all(sha(folder / name) == digest for name, digest in manifest["files"].items())
    assert sorted(p.name for p in folder.iterdir()) == ["canonical", INTERIM_MANIFEST, "series.parquet", "series_days.parquet"]
    assert canonical_state(folder) == (small_truth.train_sha256, small_truth.eval_sha256)
    series, series_days = read_canonical(folder)
    assert series.equals(canon.series) and series_days.equals(canon.series_days)
    metadata = pq.read_schema(folder / "series_days.parquet").metadata
    assert metadata[b"promolift.train_sha256"].decode() == small_truth.train_sha256 and b"promolift.attribution" in metadata


def test_the_manifest_is_the_last_thing_written_and_the_old_one_goes_first(written, small_truth, monkeypatch):
    folder, canon, _config = written
    events: list[str] = []
    real_save = np.save

    def save(file, arr, *args, **kwargs):
        events.append(f"save:{os.path.basename(str(file))}")
        events.append("manifest-present" if (folder / INTERIM_MANIFEST).exists() else "manifest-absent")
        return real_save(file, arr, *args, **kwargs)

    monkeypatch.setattr(np, "save", save)
    write_canonical(canon, folder, small_truth.train_sha256, small_truth.eval_sha256)
    assert events and set(e for e in events if e.startswith("manifest")) == {"manifest-absent"}, "the old manifest is removed before the first new file"
    assert (folder / INTERIM_MANIFEST).exists() and canonical_state(folder) is not None


def test_a_failure_in_the_middle_of_the_writes_leaves_no_manifest_and_a_state_that_is_refused(written, small_truth, monkeypatch):
    folder, canon, _config = written
    real_save, calls = np.save, []

    def failing(file, arr, *args, **kwargs):
        calls.append(file)
        if len(calls) == 5:
            raise OSError("disk full")
        return real_save(file, arr, *args, **kwargs)

    monkeypatch.setattr(np, "save", failing)
    with pytest.raises(OSError, match="disk full"):
        write_canonical(canon, folder, small_truth.train_sha256, small_truth.eval_sha256)
    assert not (folder / INTERIM_MANIFEST).exists() and canonical_state(folder) is None
    with pytest.raises(InterimError, match="manifiesto"):
        read_canonical(folder)
    with pytest.raises(InterimError, match="manifiesto"):
        open_cube(folder)


def test_a_changed_or_missing_file_is_refused_by_name(written, small_truth):
    folder, _canon, _config = written
    target = folder / "canonical" / "20240401.sales.npy"
    original = target.read_bytes()
    data = bytearray(original)
    data[-1] ^= 0x01
    target.write_bytes(bytes(data))
    assert canonical_state(folder) is None
    for reader in (read_canonical, open_cube):
        with pytest.raises(InterimError, match=r"20240401\.sales\.npy.*huella"):
            reader(folder)
    target.write_bytes(original)
    assert canonical_state(folder) == (small_truth.train_sha256, small_truth.eval_sha256)
    target.unlink()
    with pytest.raises(InterimError, match=r"falta canonical/20240401\.sales\.npy"):
        read_canonical(folder)
    (folder / INTERIM_MANIFEST).write_text("[]", encoding="utf-8")
    assert canonical_state(folder) is None
    with pytest.raises(InterimError, match="manifiesto válido"):
        read_canonical(folder)


def test_open_cube_gives_each_day_as_a_read_only_memory_map_and_never_unpickles(written, small_truth, fixture_truth):
    folder, canon, _config = written
    cube = open_cube(folder)
    assert cube.n_series == 60 and cube.date_keys.tolist() == canon.date_keys.tolist() and 20240401 in cube and 20250101 not in cube
    day = cube.sales(20240401)
    assert isinstance(day, np.memmap) and day.shape == (60, 24) and day.dtype == np.float32 and not day.flags.writeable
    assert np.array_equal(day, canon.sales[:, 4, :]) and np.array_equal(cube.stock(20240401), canon.stock[:, 4, :])
    assert cube.stock(20240401).dtype == np.int8
    with pytest.raises(KeyError, match="20250101"):
        cube.sales(20250101)
    # a file that is an object array is refused even when its manifest names its real hash
    target = folder / "canonical" / "20240402.stock.npy"
    np.save(target, np.array([{"a": 1}], dtype=object), allow_pickle=True)
    manifest = json.loads((folder / INTERIM_MANIFEST).read_text(encoding="utf-8"))
    manifest["files"]["canonical/20240402.stock.npy"] = sha(target)
    (folder / INTERIM_MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="pickle|object"):
        open_cube(folder).stock(20240402)


def test_a_store_in_two_cities_and_a_series_whose_hierarchy_changes_between_the_files_are_refused_by_rule_v06(cfg_for, small_truth, tmp_path):
    def two_cities(table):
        cities = table.column("city_id").to_pylist()
        cities[0] = cities[0] % 3 + 1
        return replace_column(table, "city_id", pa.array(cities, type=pa.int64()))

    folder = damaged_pair(small_truth, tmp_path / "cities", two_cities)
    with pytest.raises(SourceError, match=r"V06.*tienda \d+ tiene más de una ciudad"):
        read_source(folder / "train.parquet", "train", cfg_for(folder))

    def regroup(table):
        """Every row of one product moves to another group: the eval file is consistent by itself and differs from the train file."""
        products = table.column("product_id").to_numpy()
        groups = table.column("management_group_id").to_numpy()
        return replace_column(table, "management_group_id", pa.array(np.where(products == 500, (groups + 1) % 7, groups), type=pa.int64()))

    folder = damaged_pair(small_truth, tmp_path / "regroup", regroup, which="eval")
    config = cfg_for(folder)
    train, _ = read_source(folder / "train.parquet", "train", config)
    eval_, _ = read_source(folder / "eval.parquet", "eval", config)
    with pytest.raises(SourceError, match=r"V06.*cambia de jerarquía entre el archivo de train y el de eval"):
        ingest.canonical((train, eval_), config)
