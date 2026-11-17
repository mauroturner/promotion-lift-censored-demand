"""Atomic file writes (RNF05): write to a temporary file of its own, flush it to disk, then rename.

The temporary file is unique and lives in the folder of the target, so two overlapping writers never share it and
the rename stays on one filesystem. A failure removes the temporary file and leaves the target as it was.

What is guaranteed: the target is, at every instant, either its previous content or the complete new content, never a mix (the
rename is ``os.replace``), and the complete new content was flushed with ``os.fsync`` to the storage device before the rename, so
after a crash or a power cut a target that was renamed does not come back empty or cut short. What is not: the folder entry is not
synced (``fsync`` of a directory is not available on Windows), so after a power cut the rename itself may not have survived and the
target may be its previous content; nothing is torn either way. A reader that needs to know which one it got checks the manifest
hashes the writers keep (RNF05).
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


def _sync(path: Path) -> None:
    """Flush the content of a closed file to the storage device (Windows needs a writable descriptor for ``fsync``)."""
    with path.open("rb+") as handle:
        handle.flush()
        os.fsync(handle.fileno())


@contextmanager
def atomic_path(path: Path) -> Iterator[Path]:
    """Yield a temporary path next to `path`; on a clean exit its content is flushed to disk (``os.fsync``) and it replaces `path`
    (``os.replace``). The caller writes the file by name and closes it before leaving the block."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    os.close(handle)
    temporary = Path(name)
    try:
        yield temporary
        _sync(temporary)
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def write_atomic(path: Path, data: str | bytes) -> Path:
    """Write `data` (text as UTF-8, newlines untouched) to `path` atomically; returns `path`. The temporary file is written, flushed to disk and closed through the
    descriptor that created it (the same steps as ``atomic_path`` without opening a file that was just closed, which costs a lot on Windows), and then renamed."""
    payload = data.encode("utf-8") if isinstance(data, str) else data
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    temporary = Path(name)
    try:
        try:
            stream = os.fdopen(handle, "wb")
        except BaseException:
            os.close(handle)
            raise
        with stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return path


def sha256_file(path: Path, block: int = 1 << 20) -> str:
    """SHA-256 of a file, read in blocks."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(block):
            digest.update(chunk)
    return digest.hexdigest()
