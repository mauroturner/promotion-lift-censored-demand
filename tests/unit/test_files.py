"""Atomic writes (RNF05): the temporary file is flushed to disk before the rename, and a failure leaves the target as it was."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from promolift import files


@pytest.fixture
def calls(monkeypatch) -> list[tuple]:
    """The order of ``os.fsync`` and ``os.replace`` in `promolift.files`, with the size the synced file had when it was synced."""
    seen: list[tuple] = []
    real_fsync, real_replace = os.fsync, os.replace

    def fsync(fd: int) -> None:
        seen.append(("fsync", os.fstat(fd).st_size))
        real_fsync(fd)

    def replace(source, target) -> None:
        seen.append(("replace", Path(target).name))
        real_replace(source, target)

    monkeypatch.setattr(files.os, "fsync", fsync)
    monkeypatch.setattr(files.os, "replace", replace)
    return seen


def test_write_atomic_flushes_the_whole_payload_to_disk_before_the_rename(tmp_path, calls):
    payload = b"x" * 5000 + "ñ\n".encode()
    target = files.write_atomic(tmp_path / "out" / "data.bin", payload)
    assert target.read_bytes() == payload
    assert calls == [("fsync", len(payload)), ("replace", "data.bin")]
    assert sorted(p.name for p in target.parent.iterdir()) == ["data.bin"]


def test_atomic_path_flushes_what_the_caller_wrote_to_the_temporary_name_before_the_rename(tmp_path, calls):
    """A writer that takes a path (Parquet) is synced after it closes the file, whatever it wrote."""
    target = tmp_path / "table.parquet"
    with files.atomic_path(target) as temporary:
        assert temporary != target and temporary.parent == target.parent and not target.exists()
        temporary.write_bytes(b"0123456789")
    assert target.read_bytes() == b"0123456789"
    assert calls == [("fsync", 10), ("replace", "table.parquet")]


def test_a_failed_sync_keeps_the_previous_target_and_leaves_no_temporary_file(tmp_path, monkeypatch):
    target = tmp_path / "keep.txt"
    target.write_bytes(b"old")
    renamed: list[str] = []

    def broken(fd: int) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(files.os, "fsync", broken)
    real_replace = os.replace
    monkeypatch.setattr(files.os, "replace", lambda a, b: (renamed.append(str(b)), real_replace(a, b)))
    with pytest.raises(OSError, match="disk full"):
        files.write_atomic(target, b"new")
    assert target.read_bytes() == b"old" and renamed == [] and [p.name for p in tmp_path.iterdir()] == ["keep.txt"]


def test_a_failed_rename_keeps_the_previous_target_and_leaves_no_temporary_file_and_no_open_descriptor(tmp_path, monkeypatch):
    """``write_atomic`` writes through the descriptor that created the temporary file: when the rename fails the file is closed (it can be removed) and the target is as it was."""
    target = tmp_path / "keep.txt"
    target.write_bytes(b"old")

    def broken(source, destination) -> None:
        raise OSError("access denied")

    monkeypatch.setattr(files.os, "replace", broken)
    with pytest.raises(OSError, match="access denied"):
        files.write_atomic(target, "new")
    assert target.read_bytes() == b"old" and [p.name for p in tmp_path.iterdir()] == ["keep.txt"]


def test_a_failure_of_the_writer_keeps_the_previous_target_and_leaves_no_temporary_file(tmp_path):
    """The behaviour that did not change: a writer that raises never replaces the target."""
    target = tmp_path / "keep.txt"
    target.write_bytes(b"old")
    with pytest.raises(RuntimeError, match="boom"), files.atomic_path(target) as temporary:
        temporary.write_bytes(b"partial")
        raise RuntimeError("boom")
    assert target.read_bytes() == b"old" and [p.name for p in tmp_path.iterdir()] == ["keep.txt"]


def test_sha256_file_is_the_hash_of_the_bytes(tmp_path):
    path = tmp_path / "a.bin"
    path.write_bytes(b"abc")
    assert files.sha256_file(path) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
