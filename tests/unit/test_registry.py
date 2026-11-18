"""The artifact of the frozen model and its registry (U09; RF16, D20; M03; AC20): read only when its bytes are the registered ones, never with Python objects,
and a registered version is registered once, in the database itself."""

from __future__ import annotations

import io
import pickle
import sqlite3
import zipfile
from pathlib import Path

import numpy as np
import pytest
from sklearn.ensemble import HistGradientBoostingRegressor

from promolift import registry
from promolift.files import sha256_file
from promolift.registry import (
    ARTIFACT_NAME,
    MODEL_VERSION,
    R3_NAME,
    ArtifactError,
    ArtifactMismatchError,
    ArtifactMissingError,
    artifact_bytes,
    load_artifact,
    load_registered_bundle,
    read_registry,
    register_model,
    save_artifact,
)
from promolift.warehouse import apply_schema, connect
from tests.fixtures.bundles import tiny_bundle

SHA = "a" * 64


def row_for(models_dir: Path, bundle, *, r3_sha256=None) -> dict:
    return {"model_version": MODEL_VERSION, "trained_as_of": "2024-06-26 00:00:00", "artifact_name": ARTIFACT_NAME, "artifact_sha256": sha256_file(models_dir / ARTIFACT_NAME),
            "r3_name": None if r3_sha256 is None else R3_NAME, "r3_sha256": r3_sha256, "config_sha256": SHA, "recovery_json": "{}", "validation_digest": SHA}


def fitted_r3():
    rng = np.random.default_rng(0)
    return HistGradientBoostingRegressor(loss="poisson", max_iter=5, early_stopping=False, random_state=0).fit(rng.random((50, 3)), rng.poisson(1.0, 50))


@pytest.fixture
def store(tmp_path):
    bundle = tiny_bundle()
    digest, r3 = save_artifact(bundle, tmp_path)
    return tmp_path, bundle, digest


def test_the_artifact_round_trips_every_array_and_the_same_bundle_always_gives_the_same_bytes(tmp_path):
    bundle = tiny_bundle()
    digest, r3 = save_artifact(bundle, tmp_path / "one")
    again, _ = save_artifact(bundle, tmp_path / "two")
    assert digest == again == sha256_file(tmp_path / "one" / ARTIFACT_NAME) and r3 is None and not (tmp_path / "one" / R3_NAME).exists()
    assert (tmp_path / "one" / ARTIFACT_NAME).read_bytes() == artifact_bytes(bundle)
    loaded = load_artifact(tmp_path / "one", row_for(tmp_path / "one", bundle))
    assert (loaded.version, loaded.n_bands, loaded.hours) == (bundle.version, bundle.n_bands, bundle.hours)
    assert (loaded.recovery.method, loaded.recovery.kappa, loaded.recovery.r3) == ("r2", 0.25, None)
    assert np.array_equal(loaded.recovery.base, bundle.recovery.base) and np.array_equal(loaded.pmf, bundle.pmf) and np.array_equal(loaded.group_ids, bundle.group_ids)
    for version in ("raw", "recovered"):
        assert np.array_equal(loaded.cf[version].a, bundle.cf[version].a) and np.array_equal(loaded.cf[version].b, bundle.cf[version].b)
        assert np.array_equal(loaded.cf[version].days, bundle.cf[version].days) and loaded.cf[version].version == version
        assert loaded.lifts[version].overall == bundle.lifts[version].overall and np.array_equal(loaded.lifts[version].cell, bundle.lifts[version].cell)


def test_the_artifact_is_a_zip_of_plain_arrays_and_nothing_in_it_is_an_object(store):
    folder, bundle, _digest = store
    with zipfile.ZipFile(folder / ARTIFACT_NAME) as archive:
        names = archive.namelist()
        assert names == sorted(names) and all(n.endswith(".npy") for n in names)
        for name in names:
            array = np.load(io.BytesIO(archive.read(name)), allow_pickle=False)
            assert array.dtype != object


def test_artifact_with_other_hash_is_refused_before_loading(store, monkeypatch):
    folder, bundle, _digest = store
    row = row_for(folder, bundle)
    victim = folder / ARTIFACT_NAME
    victim.write_bytes(victim.read_bytes() + b"\0")                          # another file under the name that was registered
    monkeypatch.setattr(registry.np, "load", lambda *a, **k: pytest.fail("np.load was called on a file whose hash is not the registered one"))
    with pytest.raises(ArtifactMismatchError, match=row["artifact_sha256"]):
        load_artifact(folder, row)
    with pytest.raises(ValueError, match="64"):
        load_artifact(folder, {**row, "artifact_sha256": "not-a-hash"})
    victim.unlink()
    with pytest.raises(ArtifactMissingError, match=ARTIFACT_NAME):
        load_artifact(folder, row)


def test_an_npz_with_an_object_array_is_refused(store):
    folder, bundle, _digest = store
    arrays = {name: np.zeros(1) for name in ("base", "pmf", "group_ids")}
    arrays["base"] = np.array([{"x": 1}], dtype=object)               # a Python object inside: np.savez pickles it
    buffer = io.BytesIO()
    np.savez(buffer, **arrays)
    (folder / ARTIFACT_NAME).write_bytes(buffer.getvalue())             # with a hash that does match the registry: the hash is not the only guard
    row = row_for(folder, bundle)
    with pytest.raises(ArtifactError, match="objetos"):
        load_artifact(folder, row)


def test_an_artifact_that_lacks_an_array_or_has_one_more_is_refused_by_name(store):
    folder, bundle, _digest = store
    with zipfile.ZipFile(folder / ARTIFACT_NAME) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    for change, match in (({"base.npy": None}, "base"), ({"extra.npy": members["base.npy"]}, "extra")):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
            for name, data in {**members, **change}.items():
                if data is not None:
                    archive.writestr(name, data)
        (folder / ARTIFACT_NAME).write_bytes(buffer.getvalue())
        with pytest.raises(ArtifactError, match=match):
            load_artifact(folder, row_for(folder, bundle))


def test_r3_is_a_pickle_read_only_with_its_registered_hash_and_never_before_it(tmp_path, monkeypatch):
    model = fitted_r3()
    bundle = tiny_bundle("r3", r3=model)
    digest, r3_digest = save_artifact(bundle, tmp_path)
    assert r3_digest == sha256_file(tmp_path / R3_NAME) and (tmp_path / R3_NAME).stat().st_size > 0
    row = row_for(tmp_path, bundle, r3_sha256=r3_digest)
    loaded = load_artifact(tmp_path, row)
    assert loaded.recovery.method == "r3" and np.array_equal(loaded.recovery.r3.predict(np.ones((2, 3))), model.predict(np.ones((2, 3))))
    (tmp_path / R3_NAME).write_bytes(pickle.dumps({"not": "the model"}))
    monkeypatch.setattr(registry.pickle, "loads", lambda *a, **k: pytest.fail("pickle.loads was called on bytes whose hash is not the registered one"))
    with pytest.raises(ArtifactMismatchError, match=r3_digest):
        load_artifact(tmp_path, row)
    with pytest.raises(ArtifactError, match="r3"):
        load_artifact(tmp_path, {**row, "r3_sha256": None, "r3_name": None})      # an r3 model whose pickle the registry does not know


INSERTS = {
    "model_registry": ("INSERT INTO model_registry VALUES ('v1', '2024-06-26 00:00:00', 'launch.npz', ?, NULL, NULL, ?, '{}', ?)", (SHA, SHA, SHA)),
    "recovery_checks": ("INSERT INTO recovery_checks VALUES ('valid_v1', 'tail', 'r1', 'train', 10, 20, 100, 5.0, 0.3, 0.01, NULL, NULL, NULL, NULL, NULL)", ()),
    "effect_estimates": ("INSERT INTO effect_estimates VALUES ('launch', 'raw', 'overall', 'all', 'regular', 'train', 1.0, 0.5, 1.0, 0.9, 1.1, 'two_way', 5, 10, 0, NULL)", ()),
    "daily_cell": ("INSERT INTO daily_cell VALUES (20240626, 'raw', 'all', 1.0, 0.5, 1.0, 10, 3, 'run-1')", ()),
    "forecasts": ("INSERT INTO forecasts VALUES (1, 20240626, 'f0_no_lift', 2.0, 3.0, 'test', 'run-1')", ()),
    "mask_checks": ("INSERT INTO mask_checks VALUES (1, 20240626, 'r1', 15, 2.0, 1.5, 'promo', 'run-1')", ()),
}
KEYS = {
    "model_registry": "model_version = 'v1'", "recovery_checks": "scope = 'valid_v1' AND mask = 'tail' AND method = 'r1'",
    "effect_estimates": "scope = 'launch' AND version = 'raw' AND unit = 'overall'", "daily_cell": "date_key = 20240626 AND version = 'raw'",
    "forecasts": "series_key = 1 AND date_key = 20240626", "mask_checks": "series_key = 1 AND date_key = 20240626",
}
CHANGES = {
    "model_registry": "validation_digest = 'b'", "recovery_checks": "wape_series = 9.9", "effect_estimates": "lift = 9.9", "daily_cell": "lift = 9.9",
    "forecasts": "forecast = 9.9", "mask_checks": "estimate = 9.9",
}


@pytest.mark.parametrize("table", sorted(INSERTS))
def test_a_table_of_what_the_model_said_refuses_an_update_a_delete_and_a_second_insert_in_every_form(tmp_path, table):
    conn = connect(tmp_path / "w.sqlite")
    try:
        apply_schema(conn)
        conn.execute("INSERT INTO series VALUES (1, 3, 1, 500, 0, 40, 20, 100)")
        sql, params = INSERTS[table]
        conn.execute(sql, params)
        before = conn.execute(f"SELECT * FROM {table}").fetchall()
        assert len(before) == 1
        attempts = [(f"UPDATE {table} SET {CHANGES[table]}", ()), (f"DELETE FROM {table}", ()), (sql.replace("INSERT INTO", "INSERT OR REPLACE INTO", 1), params),
                    (sql.replace("INSERT INTO", "INSERT OR IGNORE INTO", 1), params), (sql, params)]
        for attempt, bound in attempts:
            with pytest.raises(sqlite3.DatabaseError, match="solo inserción"):
                conn.execute(attempt, bound)
        with pytest.raises(sqlite3.DatabaseError, match="solo inserción"):
            conn.execute(f"{sql} ON CONFLICT DO UPDATE SET {CHANGES[table].split(' = ')[0]} = {CHANGES[table].split(' = ')[1]}", params)
        assert conn.execute(f"SELECT * FROM {table}").fetchall() == before
    finally:
        conn.close()


def test_a_version_is_registered_once_and_read_back_whole(tmp_path):
    bundle = tiny_bundle()
    save_artifact(bundle, tmp_path / "models")
    conn = connect(tmp_path / "w.sqlite")
    try:
        assert read_registry(conn, MODEL_VERSION) is None            # no table yet: nothing is created by looking
        assert conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0] == 0
        apply_schema(conn)
        row = row_for(tmp_path / "models", bundle)
        register_model(conn, row)
        assert read_registry(conn, MODEL_VERSION) == row
        with pytest.raises(sqlite3.DatabaseError, match="ya está registrada"):
            register_model(conn, row)
        loaded = load_registered_bundle(conn, tmp_path / "models")
        assert loaded.recovery.kappa == 0.25
    finally:
        conn.close()
    other = connect(tmp_path / "other.sqlite")
    try:
        apply_schema(other)
        with pytest.raises(ArtifactMissingError, match="v1"):
            load_registered_bundle(other, tmp_path / "models")        # a version nobody registered cannot be loaded, whatever file is in the folder
    finally:
        other.close()


def test_r3_is_kept_with_the_artifact_even_when_another_method_was_chosen(tmp_path):
    import dataclasses

    model = fitted_r3()
    bundle = dataclasses.replace(tiny_bundle("r2"), r3=model)
    digest, r3_digest = save_artifact(bundle, tmp_path)
    assert r3_digest == sha256_file(tmp_path / R3_NAME)
    loaded = load_artifact(tmp_path, row_for(tmp_path, bundle, r3_sha256=r3_digest))
    assert loaded.recovery.method == "r2" and loaded.recovery.r3 is None
    assert np.array_equal(loaded.r3.predict(np.ones((2, 3))), model.predict(np.ones((2, 3))))
    plain = tiny_bundle("r2")
    assert load_artifact(tmp_path, row_for(tmp_path, plain)).r3 is None            # a registry row without an r3 loads none
