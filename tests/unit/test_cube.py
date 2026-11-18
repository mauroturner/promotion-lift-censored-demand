"""The cube of the loaded deliveries (U06; RF08, D22, RNF06 b): the hours of each delivery are copied to ``data/interim/cube/`` when it is loaded, with a
manifest written last, and a day is visible through the cube only once its delivery is in it. The canonical cube (U04) holds all 97 days from the first
read; this one holds what had arrived, so a calculation for an instant cannot see a day that was not delivered yet."""

from __future__ import annotations

import hashlib
import json
import os

import numpy as np
import pytest

from promolift import cube as cube_module
from promolift.cube import CUBE_MANIFEST, InterimError, open_loaded_cube, store_delivery_cube


def sha(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree(root) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): sha(p) for p in sorted(root.rglob("*")) if p.is_file()} if root.exists() else {}


def store(folder, published, delivery_id):
    _entry, _days, (date_keys, sales, stock) = published.items[delivery_id]
    store_delivery_cube(folder, delivery_id, date_keys, sales, stock)


def test_a_stored_delivery_is_listed_in_a_manifest_that_names_each_file_and_its_hash(tmp_path, published):
    store(tmp_path, published, "D2024-06-26")
    folder = tmp_path / "cube"
    assert sorted(p.name for p in folder.iterdir()) == sorted([CUBE_MANIFEST, "D2024-06-26.sales.npy", "D2024-06-26.stock.npy"])
    document = json.loads((folder / CUBE_MANIFEST).read_text(encoding="utf-8"))
    assert document["version"] == 1 and [e["delivery_id"] for e in document["deliveries"]] == ["D2024-06-26"]
    entry = document["deliveries"][0]
    assert entry["date_keys"] == [20240626] and set(entry["files"]) == {"sales", "stock"}
    assert entry["files"]["sales"] == {"name": "D2024-06-26.sales.npy", "sha256": sha(folder / "D2024-06-26.sales.npy")}
    assert entry["files"]["stock"]["sha256"] == sha(folder / "D2024-06-26.stock.npy")


def test_a_day_is_visible_only_once_its_delivery_is_in_the_cube(tmp_path, published, canonical):
    folder = tmp_path / "interim"
    assert not (folder / "cube").exists()
    with pytest.raises(InterimError, match="manifiesto"):
        open_loaded_cube(folder)
    store(folder, published, "L2024-06-25")
    loaded = open_loaded_cube(folder)
    assert loaded.n_series == 300 and loaded.date_keys.tolist() == canonical.date_keys[:90].tolist() and 20240625 in loaded and 20240626 not in loaded
    with pytest.raises(KeyError, match="20240626"):
        loaded.sales(20240626)
    store(folder, published, "D2024-06-26")
    store(folder, published, "C2024-07-03")                 # the close holds no day and is listed all the same
    loaded = open_loaded_cube(folder)
    assert loaded.date_keys.tolist() == canonical.date_keys[:91].tolist() and 20240626 in loaded and 20240627 not in loaded
    day = canonical.date_keys.tolist().index(20240626)
    sales, stock = loaded.sales(20240626), loaded.stock(20240626)
    assert sales.shape == stock.shape == (300, 24) and sales.dtype == np.float32 and stock.dtype == np.int8 and not sales.flags.writeable
    assert np.array_equal(sales, canonical.sales[:, day, :]) and np.array_equal(stock, canonical.stock[:, day, :])
    old = loaded.sales(20240401)
    assert np.array_equal(old, canonical.sales[:, canonical.date_keys.tolist().index(20240401), :]), "a day of the launch comes out of the launch's file"
    assert [e["delivery_id"] for e in json.loads((folder / "cube" / CUBE_MANIFEST).read_text(encoding="utf-8"))["deliveries"]] == [
        "L2024-06-25", "D2024-06-26", "C2024-07-03"]


def test_storing_the_same_delivery_again_changes_nothing_and_another_content_is_refused(tmp_path, published):
    store(tmp_path, published, "D2024-06-26")
    before = tree(tmp_path / "cube")
    mtimes = {p: p.stat().st_mtime_ns for p in (tmp_path / "cube").iterdir()}
    store(tmp_path, published, "D2024-06-26")
    assert tree(tmp_path / "cube") == before and {p: p.stat().st_mtime_ns for p in (tmp_path / "cube").iterdir()} == mtimes
    keys, sales, stock = published.items["D2024-06-26"][2]
    with pytest.raises(InterimError, match=r"D2024-06-26 ya está en el cubo con otro contenido.*R12"):
        store_delivery_cube(tmp_path, "D2024-06-26", keys, sales + np.float32(1.0), stock)
    assert tree(tmp_path / "cube") == before


def test_the_manifest_is_written_last_and_a_failure_before_it_lists_nothing(tmp_path, published, monkeypatch):
    store(tmp_path, published, "L2024-06-25")
    before = tree(tmp_path / "cube")
    real_save, calls = np.save, []

    def failing(handle, array, *args, **kwargs):
        calls.append(1)
        if len(calls) == 2:                                  # the stock file: the sales file was written and the manifest was not yet
            raise OSError("disk full")
        return real_save(handle, array, *args, **kwargs)

    monkeypatch.setattr(np, "save", failing)
    with pytest.raises(OSError, match="disk full"):
        store(tmp_path, published, "D2024-06-26")
    monkeypatch.undo()
    assert open_loaded_cube(tmp_path).date_keys.tolist()[-1] == 20240625, "the delivery that failed is not listed, so none of its days is visible"
    assert {k: v for k, v in tree(tmp_path / "cube").items() if k.startswith(("L2024", CUBE_MANIFEST))} == {k: v for k, v in before.items()}
    store(tmp_path, published, "D2024-06-26")                # storing again finishes the job
    assert open_loaded_cube(tmp_path).date_keys.tolist()[-1] == 20240626


def test_a_changed_or_missing_file_or_a_wrong_manifest_is_refused_by_name(tmp_path, published):
    store(tmp_path, published, "D2024-06-26")
    folder = tmp_path / "cube"
    target = folder / "D2024-06-26.sales.npy"
    good = target.read_bytes()
    target.write_bytes(good[:-1] + bytes([good[-1] ^ 0x01]))
    with pytest.raises(InterimError, match=r"D2024-06-26\.sales\.npy no coincide con la huella.*R12"):
        open_loaded_cube(tmp_path)
    target.write_bytes(good)
    assert open_loaded_cube(tmp_path).date_keys.tolist() == [20240626]
    target.unlink()
    with pytest.raises(InterimError, match=r"falta D2024-06-26\.sales\.npy"):
        open_loaded_cube(tmp_path)
    target.write_bytes(good)
    for text in ("not json", "[]", '{"version": 2, "deliveries": []}', '{"version": 1, "deliveries": [{"delivery_id": "x"}]}'):
        (folder / CUBE_MANIFEST).write_text(text, encoding="utf-8")
        with pytest.raises(InterimError, match="manifiesto válido"):
            open_loaded_cube(tmp_path)


def test_a_file_with_python_objects_is_refused_even_when_its_manifest_names_its_hash(tmp_path, published):
    store(tmp_path, published, "D2024-06-26")
    folder = tmp_path / "cube"
    target = folder / "D2024-06-26.stock.npy"
    np.save(target, np.array([{"a": 1}], dtype=object), allow_pickle=True)
    manifest = json.loads((folder / CUBE_MANIFEST).read_text(encoding="utf-8"))
    manifest["deliveries"][0]["files"]["stock"]["sha256"] = sha(target)
    (folder / CUBE_MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises((ValueError, InterimError)):
        open_loaded_cube(tmp_path).stock(20240626)


def test_two_deliveries_with_the_same_day_are_refused_and_no_module_other_than_the_cube_names_the_folder():
    assert cube_module.LOADED_CUBE_DIR == "cube" and cube_module.CANONICAL_DIR == "canonical"
    assert os.path.basename(cube_module.LOADED_CUBE_DIR) != cube_module.CANONICAL_DIR


def test_the_same_day_in_two_deliveries_is_refused(tmp_path, published):
    store(tmp_path, published, "D2024-06-26")
    keys, sales, stock = published.items["D2024-06-26"][2]
    with pytest.raises(InterimError, match=r"el día 20240626 ya está en la entrega D2024-06-26"):
        store_delivery_cube(tmp_path, "D2024-06-26-again", keys, sales, stock)


# --- the recovered hours of a delivery ---------------------------------------------------------------------------------------------------


def test_the_recovered_hours_of_a_delivery_are_stored_once_listed_in_their_own_manifest_and_read_back_only_if_they_are_the_listed_ones(tmp_path):
    from promolift.cube import RECOVERED_MANIFEST, open_recovered, store_recovered

    recovered = np.arange(2 * 3 * 24, dtype=np.float32).reshape(2, 3, 24) / 4
    digest = store_recovered(tmp_path, "L1", np.array([20240601, 20240602, 20240603]), recovered)
    folder = tmp_path / "cube"
    assert sorted(p.name for p in folder.iterdir()) == sorted([RECOVERED_MANIFEST, "L1.recovered.npy"]) and digest == sha(folder / "L1.recovered.npy")
    document = json.loads((folder / RECOVERED_MANIFEST).read_text(encoding="utf-8"))
    assert document == {"version": 1, "deliveries": [{"delivery_id": "L1", "date_keys": [20240601, 20240602, 20240603], "name": "L1.recovered.npy", "sha256": digest}]}
    again = store_recovered(tmp_path, "L1", np.array([20240601, 20240602, 20240603]), recovered)          # the same hours: nothing changes
    assert again == digest and json.loads((folder / RECOVERED_MANIFEST).read_text(encoding="utf-8")) == document
    read = open_recovered(tmp_path, "L1")
    assert read.dtype == np.float32 and read.shape == (2, 3, 24) and not read.flags.writeable and np.array_equal(read, recovered)
    with pytest.raises(InterimError, match="otro contenido"):
        store_recovered(tmp_path, "L1", np.array([20240601, 20240602, 20240603]), recovered + 1)
    with pytest.raises(InterimError, match="no hay horas recuperadas"):
        open_recovered(tmp_path, "L2")
    del read
    (folder / "L1.recovered.npy").write_bytes((folder / "L1.recovered.npy").read_bytes()[:-4] + b"\0\0\0\1")
    with pytest.raises(InterimError, match="no es el archivo"):
        open_recovered(tmp_path, "L1")
    store_recovered(tmp_path, "L1", np.array([20240601, 20240602, 20240603]), recovered)                   # a damaged file is written again
    assert np.array_equal(open_recovered(tmp_path, "L1"), recovered)
