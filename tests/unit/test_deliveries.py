"""Deliveries (U05; RF05, D18; AC05): the plan that comes from the configuration, the two files of a delivery with the sums of its days, the manifest
that lists them, and the next delivery that is always the first that is not loaded."""

from __future__ import annotations

import dataclasses
import hashlib
import io
import json
import zipfile
from datetime import date, datetime

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest

from promolift.config import SealedConfig
from promolift.cube import InterimError, read_delivery_cube, write_delivery_cube
from promolift.deliveries import (
    DAYS_COLUMNS,
    MANIFEST_NAME,
    DeliverySpec,
    ManifestEntry,
    delivery_digest,
    delivery_plan,
    delivery_sums,
    mark_delivery,
    next_pending,
    publish,
    read_delivery,
    read_manifest,
)
from promolift.schema import FORBIDDEN_COLUMNS

SEEN = "a" * 64


def sha(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def new_folder(tmp_path):
    folder = tmp_path / "deliveries"
    folder.mkdir()
    return folder


# --- the plan -----------------------------------------------------------------------------------------------------------------


def test_launch_seven_daily_deliveries_and_the_close_come_from_the_config(cfg):
    for view in (cfg, SealedConfig.of(cfg, SEEN, SEEN)):
        plan = delivery_plan(view)
        assert [s.delivery_id for s in plan] == ["L2024-06-25", *[f"D2024-06-{d:02d}" for d in (26, 27, 28, 29, 30)], "D2024-07-01", "D2024-07-02", "C2024-07-03"]
        assert [s.kind for s in plan] == ["launch"] + ["daily"] * 7 + ["close"]
        assert (plan[0].first_day, plan[0].last_day) == (date(2024, 3, 28), date(2024, 6, 25))
        assert [(s.first_day, s.last_day) for s in plan[1:8]] == [(date(2024, 6, 26) + (date(2024, 6, 27) - date(2024, 6, 26)) * i,) * 2 for i in range(7)]
        assert (plan[-1].first_day, plan[-1].last_day) == (None, None)
        assert [s.as_of for s in plan] == [datetime(2024, 6, 26)] + [datetime(2024, 6, 27 + i) if i < 4 else datetime(2024, 7, i - 3) for i in range(7)] + [datetime(2024, 7, 3)]
        assert all(isinstance(s, DeliverySpec) for s in plan)
        # contiguous: each delivery starts the day after the one before ends
        periods = [s for s in plan if s.first_day is not None]
        assert all((b.first_day - a.last_day).days == 1 for a, b in zip(periods, periods[1:]))


def test_the_plan_follows_the_calendar_of_the_configuration(cfg):
    shorter = dataclasses.replace(cfg, calendar=dataclasses.replace(cfg.calendar, launch_last_day=date(2024, 6, 29), last_day=date(2024, 7, 1)))
    plan = delivery_plan(shorter)
    assert [s.delivery_id for s in plan] == ["L2024-06-29", "D2024-06-30", "D2024-07-01", "C2024-07-02"]
    assert plan[0].as_of == datetime(2024, 6, 30) and plan[-1].as_of == datetime(2024, 7, 2)
    assert [s.delivery_id for s in delivery_plan(dataclasses.replace(shorter, calendar=dataclasses.replace(shorter.calendar, first_day=date(2024, 4, 1))))][0] == "L2024-06-29"
    assert delivery_plan(dataclasses.replace(cfg, source=cfg.source)) == delivery_plan(cfg), "the plan reads the calendar and nothing else"


# --- publishing ------------------------------------------------------------------------------------------------------------------


def test_a_delivery_is_two_files_with_the_series_days_of_its_period_and_their_sums(published, canonical, cfg):
    entry, days, (date_keys, sales, stock) = published.items["D2024-06-27"]
    assert isinstance(entry, ManifestEntry) and entry.status == "published" and entry.run_key is None
    assert (entry.delivery_id, entry.kind, entry.first_day, entry.last_day, entry.as_of, entry.series_days) == (
        "D2024-06-27", "daily", date(2024, 6, 27), date(2024, 6, 27), datetime(2024, 6, 28), 300)
    assert (entry.days_file, entry.cube_file) == ("D2024-06-27.days.parquet", "D2024-06-27.cube.npz")
    assert [p.name for p in sorted(published.out_dir.glob("D2024-06-27*"))] == ["D2024-06-27.cube.npz", "D2024-06-27.days.parquet"]
    assert entry.days_sha256 == sha(published.out_dir / entry.days_file) and entry.cube_sha256 == sha(published.out_dir / entry.cube_file)
    assert entry.sha256 == delivery_digest(entry.days_sha256, entry.cube_sha256) == hashlib.sha256(f"{entry.days_sha256}\n{entry.cube_sha256}".encode()).hexdigest()
    assert list(days.columns) == list(DAYS_COLUMNS) and len(days) == 300 and set(days["date_key"]) == {20240627}
    assert days["series_key"].tolist() == list(range(300)) and not set(days.columns) & set(FORBIDDEN_COLUMNS)
    assert not set(days.columns) & {"hours_sale", "hours_stock_status"}, "a delivery's days carry no hourly list"
    # the tensors are the day's hours of the canonical cube
    day_index = canonical.date_keys.tolist().index(20240627)
    assert date_keys.tolist() == [20240627] and sales.shape == stock.shape == (300, 1, 24)
    assert np.array_equal(sales[:, 0, :], canonical.sales[:, day_index, :]) and np.array_equal(stock[:, 0, :], canonical.stock[:, day_index, :])
    # the sums: from 06 to 21, written independently here
    core = canonical.sales[:, day_index, 6:22].astype(np.float64)
    out = canonical.stock[:, day_index, 6:22]
    assert np.array_equal(days["raw_sum"].to_numpy(), core.sum(axis=1)) and np.array_equal(days["instock_hours"].to_numpy(), 16 - out.sum(axis=1))
    assert np.array_equal(days["stockout_hours"].to_numpy(), out.sum(axis=1)) and np.allclose(days["instock_sum"], (core * (out == 0)).sum(axis=1), atol=1e-12)
    assert (days["instock_hours"] + days["stockout_hours"] == 16).all() and (days["instock_sum"] <= days["raw_sum"] + 1e-12).all()
    # the rest of the columns are the canonical series-days
    canon_day = canonical.series_days[canonical.series_days["date_key"] == 20240627].reset_index(drop=True)
    assert days[list(canon_day.columns)].equals(canon_day)


def test_the_parquet_schema_and_the_metadata_of_a_delivery(published):
    entry, _days, _cube = published.items["L2024-06-25"]
    file = pq.ParquetFile(published.out_dir / entry.days_file)
    assert file.schema_arrow.names == list(DAYS_COLUMNS)
    types = {name: str(file.schema_arrow.field(name).type) for name in DAYS_COLUMNS}
    assert types["series_key"] == "int32" and types["date_key"] == "int32" and types["raw_sum"] == "double" and types["instock_hours"] == "int8"
    metadata = file.schema_arrow.metadata
    assert metadata[b"promolift.delivery_id"] == b"L2024-06-25" and metadata[b"promolift.period"] == b"2024-03-28/2024-06-25"
    assert b"CC BY 4.0" in metadata[b"promolift.attribution"]
    assert entry.series_days == 300 * 90 and file.metadata.num_rows == 27000


def test_the_whole_plan_delivers_every_series_day_exactly_once(published, canonical):
    entries = [published.items[s.delivery_id][0] for s in published.plan]
    assert sum(e.series_days for e in entries) == len(canonical.series_days) == 300 * 97
    keys = pd.concat([published.items[s.delivery_id][1][["series_key", "date_key"]] for s in published.plan])
    assert not keys.duplicated().any() and len(keys) == 300 * 97
    assert [e.series_days for e in entries] == [27000, *[300] * 7, 0]
    close = published.items["C2024-07-03"]
    assert close[0].kind == "close" and close[0].first_day is None and len(close[1]) == 0 and close[2][1].shape == (300, 0, 24)
    assert close[0].days_sha256 and close[0].cube_sha256 and close[0].sha256 == delivery_digest(close[0].days_sha256, close[0].cube_sha256)


def test_publishing_the_same_rows_again_changes_nothing_and_a_damaged_file_is_written_again(published, canonical, cfg, tmp_path):
    folder = new_folder(tmp_path)
    spec = published.plan[2]
    first = publish(spec, canonical, folder, cfg)
    manifest = folder / MANIFEST_NAME
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in folder.iterdir()}
    again = publish(spec, canonical, folder, cfg)
    assert again == first and {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in folder.iterdir()} == before, "nothing is rewritten"
    assert (folder / first.days_file).read_bytes() == (published.out_dir / first.days_file).read_bytes(), "the bytes depend on the rows alone"
    assert (folder / first.cube_file).read_bytes() == (published.out_dir / first.cube_file).read_bytes()
    (folder / first.cube_file).write_bytes(b"broken")
    (folder / first.days_file).unlink()
    assert publish(spec, canonical, folder, cfg) == first and sha(folder / first.cube_file) == first.cube_sha256 and sha(folder / first.days_file) == first.days_sha256
    assert len(read_manifest(manifest)) == 1


def test_changed_rows_replace_a_delivery_that_is_not_loaded_and_never_one_that_is(published, canonical, cfg, tmp_path):
    folder = new_folder(tmp_path)
    spec = published.plan[3]
    first = publish(spec, canonical, folder, cfg)
    changed = dataclasses.replace(canonical, sales=canonical.sales.copy())
    day = canonical.date_keys.tolist().index(spec.first_day.year * 10000 + spec.first_day.month * 100 + spec.first_day.day)
    changed.sales[0, day, 10] += 1.0
    replaced = publish(spec, changed, folder, cfg)
    assert replaced.sha256 != first.sha256 and replaced.status == "published" and len(read_manifest(folder / MANIFEST_NAME)) == 1
    mark_delivery(folder / MANIFEST_NAME, spec.delivery_id, "loaded", "run-a")
    with pytest.raises(ValueError, match=r"ya está cargada en el almacén.*R4"):
        publish(spec, canonical, folder, cfg)
    assert read_manifest(folder / MANIFEST_NAME)[0].sha256 == replaced.sha256 and read_manifest(folder / MANIFEST_NAME)[0].status == "loaded"
    assert publish(spec, changed, folder, cfg).status == "loaded", "the same rows as the loaded ones are not an error"


def test_read_delivery_gives_back_what_was_published(published):
    entry, days, (date_keys, sales, stock) = published.items["L2024-06-25"]
    again_days, (again_keys, again_sales, again_stock) = read_delivery(published.out_dir, entry)
    assert again_days.equals(days) and np.array_equal(again_keys, date_keys) and np.array_equal(again_sales, sales) and np.array_equal(again_stock, stock)
    assert len(date_keys) == 90 and sales.shape == (300, 90, 24) and sales.dtype == np.float32 and stock.dtype == np.int8 and date_keys.dtype == np.int32


def test_delivery_sums_are_the_one_function_that_publishing_and_the_rule_that_checks_them_use(canonical):
    sales, stock = canonical.sales[:, :3, :], canonical.stock[:, :3, :]
    sums = delivery_sums(sales, stock, (6, 21))
    assert set(sums) == {"raw_sum", "instock_hours", "stockout_hours", "instock_sum"} and all(v.shape == (300, 3) for v in sums.values())
    assert sums["raw_sum"].dtype == np.float64 and sums["instock_hours"].dtype == np.int8 and sums["stockout_hours"].dtype == np.int8
    narrower = delivery_sums(sales, stock, (8, 9))
    assert (narrower["instock_hours"] + narrower["stockout_hours"] == 2).all() and (narrower["raw_sum"] <= sums["raw_sum"] + 1e-12).all()


# --- the cube of a delivery ----------------------------------------------------------------------------------------------------------


def test_the_cube_of_a_delivery_has_the_same_bytes_every_time_and_is_read_without_pickle(canonical, tmp_path):
    keys, sales, stock = canonical.date_keys[:2], canonical.sales[:, :2, :], canonical.stock[:, :2, :]
    one, two = write_delivery_cube(tmp_path / "a.npz", keys, sales, stock), write_delivery_cube(tmp_path / "b.npz", keys, sales, stock)
    assert one == two == sha(tmp_path / "a.npz") and (tmp_path / "a.npz").read_bytes() == (tmp_path / "b.npz").read_bytes()
    assert sorted(zipfile.ZipFile(tmp_path / "a.npz").namelist()) == ["date_keys.npy", "sales.npy", "stock.npy"]
    assert all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in zipfile.ZipFile(tmp_path / "a.npz").infolist())
    got_keys, got_sales, got_stock = read_delivery_cube(tmp_path / "a.npz")
    assert np.array_equal(got_keys, keys) and np.array_equal(got_sales, sales) and np.array_equal(got_stock, stock)
    assert [p.name for p in tmp_path.iterdir()] == ["a.npz", "b.npz"]


@pytest.mark.parametrize("damage", ["object", "dtype", "shape", "missing_array"])
def test_a_cube_that_is_not_what_a_delivery_holds_is_refused(canonical, tmp_path, damage):
    keys, sales, stock = canonical.date_keys[:2], canonical.sales[:, :2, :], canonical.stock[:, :2, :]
    arrays = {"date_keys": keys, "sales": sales, "stock": stock}
    if damage == "object":
        arrays["stock"] = np.array([{"a": 1}], dtype=object)
    elif damage == "dtype":
        arrays["sales"] = sales.astype(np.float64)
    elif damage == "shape":
        arrays["stock"] = stock[:, :, :23]
    else:
        del arrays["stock"]
    with zipfile.ZipFile(tmp_path / "bad.npz", "w") as archive:
        for name, array in arrays.items():
            buffer = io.BytesIO()
            np.lib.format.write_array(buffer, array, allow_pickle=True)
            archive.writestr(f"{name}.npy", buffer.getvalue())
    with pytest.raises((InterimError, ValueError)):
        read_delivery_cube(tmp_path / "bad.npz")


# --- the manifest ------------------------------------------------------------------------------------------------------------------------


def manifest_with(published, canonical, cfg, folder, upto):
    for spec in published.plan[:upto]:
        publish(spec, canonical, folder, cfg)
    return folder / MANIFEST_NAME


def test_a_missing_manifest_is_an_empty_one_and_a_wrong_one_is_refused(tmp_path):
    assert read_manifest(tmp_path / "none.json") == []
    for text in ("not json", "[]", '{"version": 2, "entries": []}', '{"version": 1}', '{"version": 1, "entries": [{"delivery_id": "x"}]}'):
        (tmp_path / "m.json").write_text(text, encoding="utf-8")
        with pytest.raises(ValueError, match="no es un manifiesto de entregas válido"):
            read_manifest(tmp_path / "m.json")


def test_a_manifest_with_the_same_delivery_twice_or_a_wrong_value_is_refused(published, canonical, cfg, tmp_path):
    manifest = manifest_with(published, canonical, cfg, new_folder(tmp_path), 2)
    document = json.loads(manifest.read_text(encoding="utf-8"))
    for change in (lambda d: d["entries"].append(dict(d["entries"][0])), lambda d: d["entries"][0].update(status="shipped"),
                   lambda d: d["entries"][0].update(kind="weekly"), lambda d: d["entries"][0].update(series_days=-1),
                   lambda d: d["entries"][0].update(series_days=True), lambda d: d["entries"][0].update(run_key=7)):
        broken = json.loads(json.dumps(document))
        change(broken)
        manifest.write_text(json.dumps(broken), encoding="utf-8")
        with pytest.raises(ValueError, match="no es un manifiesto de entregas válido"):
            read_manifest(manifest)
    manifest.write_text(json.dumps(document), encoding="utf-8")
    assert [e.delivery_id for e in read_manifest(manifest)] == ["L2024-06-25", "D2024-06-26"]


def test_the_next_delivery_is_the_first_of_the_plan_that_is_not_loaded(published, canonical, cfg, tmp_path):
    folder = new_folder(tmp_path)
    plan = published.plan
    assert next_pending(folder / MANIFEST_NAME, plan) == plan[0], "no manifest: the launch"
    manifest = manifest_with(published, canonical, cfg, folder, 3)
    assert next_pending(manifest, plan) == plan[0], "published is not loaded"
    mark_delivery(manifest, "L2024-06-25", "loaded", "run-1")
    assert next_pending(manifest, plan) == plan[1]
    mark_delivery(manifest, "D2024-06-26", "rejected", "run-2")
    assert next_pending(manifest, plan) == plan[1], "a rejected delivery stays the pending one"
    mark_delivery(manifest, "D2024-06-26", "loaded", "run-3")
    mark_delivery(manifest, "D2024-06-27", "loaded", "run-4")
    assert next_pending(manifest, plan) == plan[3]
    for spec in plan[3:]:
        publish(spec, canonical, folder, cfg)
        mark_delivery(manifest, spec.delivery_id, "loaded", f"run-{spec.delivery_id}")
    assert next_pending(manifest, plan) is None


def test_a_manifest_that_skips_the_plan_or_disagrees_with_it_is_refused_with_the_runbook(published, canonical, cfg, tmp_path):
    folder = new_folder(tmp_path)
    manifest = manifest_with(published, canonical, cfg, folder, 3)
    mark_delivery(manifest, "D2024-06-27", "loaded", "run-x")
    with pytest.raises(ValueError, match=r"D2024-06-27 está cargada pero la anterior, L2024-06-25, no lo está.*R4"):
        next_pending(manifest, published.plan)
    other = dataclasses.replace(cfg, calendar=dataclasses.replace(cfg.calendar, launch_last_day=date(2024, 6, 26), last_day=date(2024, 7, 2)))
    with pytest.raises(ValueError, match=r"no está en el plan.*R4|otro período.*R4"):
        next_pending(manifest, delivery_plan(other))
    document = json.loads(manifest.read_text(encoding="utf-8"))
    document["entries"][0]["last_day"] = "2024-06-24"
    manifest.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match=r"otro período.*R4"):
        next_pending(manifest, published.plan)


def test_marking_a_delivery_keeps_the_rest_and_a_loaded_one_is_never_changed_by_another_run(published, canonical, cfg, tmp_path):
    manifest = manifest_with(published, canonical, cfg, new_folder(tmp_path), 2)
    before = read_manifest(manifest)
    mark_delivery(manifest, "L2024-06-25", "rejected", "run-1")
    after = read_manifest(manifest)
    assert after[0] == dataclasses.replace(before[0], status="rejected", run_key="run-1") and after[1] == before[1]
    mark_delivery(manifest, "L2024-06-25", "published")
    assert read_manifest(manifest)[0].status == "published" and read_manifest(manifest)[0].run_key == "run-1", "a missing run key keeps the one it had"
    mark_delivery(manifest, "L2024-06-25", "loaded", "run-2")
    mark_delivery(manifest, "L2024-06-25", "loaded", "run-2")
    for status, run in (("rejected", "run-2"), ("published", None), ("loaded", "run-9")):
        with pytest.raises(ValueError, match=r"ya está cargada por la corrida 'run-2'.*R4"):
            mark_delivery(manifest, "L2024-06-25", status, run)
    assert read_manifest(manifest)[0].status == "loaded"
    with pytest.raises(ValueError, match="no hay una entrega"):
        mark_delivery(manifest, "D9999", "loaded", "run")
    with pytest.raises(ValueError, match="status"):
        mark_delivery(manifest, "L2024-06-25", "shipped")
