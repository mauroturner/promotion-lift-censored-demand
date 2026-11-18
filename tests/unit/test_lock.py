"""One writer at a time on the data folder (U15, AC29; plan, section 22; D26; ported from project 05's tests): a second writer is refused with exit 2 and writes
nothing, giving the lock back never raises (also while another process has the file open, as Windows refuses the removal then), a nested take
whose rewrite fails never leaves the lock behind, a reused process number is not taken for the owner, another thread is refused and a lock
released between a failed create and the read is taken on a second try.

The other processes are real: each is started here with ``subprocess.Popen`` and ended by its process id."""

from __future__ import annotations

import json
import logging
import os
import signal
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from promolift import files, lock

PROJECT = Path(__file__).resolve().parents[2]
ENV = {**os.environ, "PYTHONPATH": str(PROJECT / "src")}
SECOND_WRITER = """
import sys
from pathlib import Path
from promolift.lock import RunRefusedError, sole_writer
folder, marker = Path(sys.argv[1]), Path(sys.argv[2])
try:
    with sole_writer(folder, "run", "second"):
        marker.write_text("written by the second writer", encoding="utf-8")
except RunRefusedError as error:
    print(f"{type(error).__name__} {error.state}: {error}", file=sys.stderr)
    sys.exit(error.exit_code)
"""
HOLD_OPEN = """
import sys
handle = open(sys.argv[1], "rb")
print("open", flush=True)
sys.stdin.read()
"""


@pytest.fixture
def fast_release(monkeypatch):
    """The retries of a removal shortened to 0.2 s: what they test does not depend on their length (2 s by default, plan section 22)."""
    monkeypatch.setattr(lock, "RELEASE_ATTEMPTS", 4)
    monkeypatch.setattr(lock, "RELEASE_PAUSE_S", 0.05)


def end(process: subprocess.Popen) -> None:
    """End a process this test started, by its process id."""
    if process.poll() is None:
        os.kill(process.pid, signal.SIGTERM)
    process.wait(timeout=10)


# --- the RED of U15 -----------------------------------------------------------------------------------------------------------


def test_a_release_while_another_process_holds_the_file_open_never_raises_and_keeps_the_task_result(tmp_path, fast_release, caplog, monkeypatch):
    """Project 03, B2 (D87): on Windows a file another process has open cannot be removed; giving the lock back retries, then logs a warning
    with the last error and names runbook R8, and the block's result stands. The lock is left for a person (only its owner removes it)."""
    if sys.platform != "win32":       # elsewhere an open file can be removed: the refusal Windows gives is what the test reproduces
        real_unlink = Path.unlink
        monkeypatch.setattr(Path, "unlink", lambda self, missing_ok=False: (_ for _ in ()).throw(PermissionError(32, "in use")) if self.name == lock.LOCK_NAME else real_unlink(self, missing_ok))
    holder = None
    try:
        with caplog.at_level(logging.WARNING, logger="promolift.lock"):
            with lock.sole_writer(tmp_path, "run", "r1"):
                holder = subprocess.Popen([sys.executable, "-c", HOLD_OPEN, str(tmp_path / lock.LOCK_NAME)], stdin=subprocess.PIPE,
                                          stdout=subprocess.PIPE, env=ENV)
                assert holder.stdout.readline().strip() == b"open"
                result = "the task's result"
        assert result == "the task's result"
        warnings = [r for r in caplog.records if r.name == "promolift.lock" and r.levelno == logging.WARNING]
        assert warnings and "could not remove the lock" in warnings[-1].getMessage() and "R8" in warnings[-1].getMessage()
        assert warnings[-1].exc_info is not None and isinstance(warnings[-1].exc_info[1], PermissionError), "the last error is in the warning"
        assert (tmp_path / lock.LOCK_NAME).exists()
    finally:
        if holder is not None:
            end(holder)
    assert lock.read_holder(tmp_path)["run_key"] == "r1", "left as it was, for a person to check and remove (R8)"


def test_a_nested_take_whose_rewrite_fails_never_leaves_the_lock_behind(tmp_path, monkeypatch):
    """Project 03, review of B2: an inner take (``replay`` calls ``run_all``) interrupted while it rewrites the file takes nothing, and the
    outer release removes the lock; a rewrite that fails with an OSError never raises and the inner take goes on with the outer record."""
    real_rewrite = lock._rewrite
    with lock.sole_writer(tmp_path, "replay", None):
        monkeypatch.setattr(lock, "_rewrite", lambda path, record: (_ for _ in ()).throw(KeyboardInterrupt()))
        with pytest.raises(KeyboardInterrupt):
            with lock.sole_writer(tmp_path, "run", "r2"):
                pass
        monkeypatch.setattr(lock, "_rewrite", real_rewrite)
        assert lock.read_holder(tmp_path)["command"] == "replay"
    assert not (tmp_path / lock.LOCK_NAME).exists() and lock._HELD == {}


def test_a_nested_release_whose_rewrite_fails_never_raises(tmp_path, monkeypatch, caplog):
    with lock.sole_writer(tmp_path, "replay", None):
        with caplog.at_level(logging.WARNING, logger="promolift.lock"):
            with lock.sole_writer(tmp_path, "run", "r3"):
                assert lock.read_holder(tmp_path)["run_key"] == "r3"
                monkeypatch.setattr(files.tempfile, "mkstemp", lambda **kw: (_ for _ in ()).throw(OSError(28, "No space left on device")))
        assert any("could not rewrite the lock" in r.getMessage() and r.exc_info for r in caplog.records)
        assert lock.read_holder(tmp_path)["run_key"] == "r3", "the file keeps the inner record when its rewrite fails"
    assert not (tmp_path / lock.LOCK_NAME).exists()


def test_a_second_writer_is_refused_with_exit_2_and_writes_nothing(tmp_path):
    """AC29: while this process holds the lock, a second process that tries to write the folder exits with 2, says who holds it and writes
    nothing; once the lock is given back the same command writes."""
    marker = tmp_path / "written.txt"
    with lock.sole_writer(tmp_path, "run", "r1"):
        second = subprocess.Popen([sys.executable, "-c", SECOND_WRITER, str(tmp_path), str(marker)], stderr=subprocess.PIPE, env=ENV)
        try:
            _out, err = second.communicate(timeout=60)
        finally:
            end(second)
        assert second.returncode == 2 and not marker.exists()
        assert "RunLockedError alive" in err.decode("utf-8", "replace") and f"proceso {os.getpid()}" in err.decode("utf-8", "replace")
    again = subprocess.run([sys.executable, "-c", SECOND_WRITER, str(tmp_path), str(marker)], env=ENV, timeout=60, capture_output=True)
    assert again.returncode == 0 and marker.read_text(encoding="utf-8") == "written by the second writer"
    assert not (tmp_path / lock.LOCK_NAME).exists()


# --- who holds it ---------------------------------------------------------------------------------------------------------------


def write_lock(folder: Path, **record) -> None:
    base = {"pid": os.getpid(), "started": lock._process_start(os.getpid()), "host": socket.gethostname(), "command": "run", "run_key": "r9",
            "since": "2026-11-12T10:00:00+00:00", "token": "f" * 32}
    (folder / lock.LOCK_NAME).write_text(json.dumps({**base, **record}), encoding="utf-8")


def test_a_reused_pid_with_another_start_time_is_not_the_owner(tmp_path):
    started = lock._process_start(os.getpid())
    assert isinstance(started, int)
    write_lock(tmp_path, started=started + 1)
    with pytest.raises(lock.RunLockedError) as error:
        lock.acquire(tmp_path, command="run")
    assert error.value.state == "stale" and "lo tiene ahora otro proceso" in str(error.value) and error.value.exit_code == 2
    write_lock(tmp_path)
    with pytest.raises(lock.RunLockedError) as error:
        lock.acquire(tmp_path, command="run")
    assert error.value.state == "alive"


def test_a_finished_holder_another_host_and_an_unreadable_lock_are_each_named_and_never_removed(tmp_path):
    finished = subprocess.run([sys.executable, "-c", "import os; print(os.getpid())"], capture_output=True, text=True, timeout=60)
    for record, state in (({"pid": int(finished.stdout), "started": None}, "stale"), ({"host": "another-host"}, "elsewhere")):
        write_lock(tmp_path, **record)
        with pytest.raises(lock.RunLockedError) as error:
            lock.acquire(tmp_path, command="run")
        assert error.value.state == state and "No se escribió nada" in str(error.value)
        assert (tmp_path / lock.LOCK_NAME).exists()
    (tmp_path / lock.LOCK_NAME).write_text("not json", encoding="utf-8")
    with pytest.raises(lock.RunLockedError) as error:
        lock.acquire(tmp_path, command="run")
    assert error.value.state == "unreadable" and (tmp_path / lock.LOCK_NAME).read_text(encoding="utf-8") == "not json"


def test_another_thread_of_the_same_process_is_refused(tmp_path):
    seen = []
    with lock.sole_writer(tmp_path, "run", "r1"):
        def other():
            try:
                lock.acquire(tmp_path, command="run")
            except lock.RunLockedError as error:
                seen.append(error.state)

        thread = threading.Thread(target=other)
        thread.start()
        thread.join(timeout=30)
    assert seen == ["thread"] and not (tmp_path / lock.LOCK_NAME).exists()


def test_a_lock_released_between_the_failed_create_and_the_read_is_taken_on_a_second_try(tmp_path, monkeypatch):
    real_create = lock._create
    calls = []

    def create(path, record):
        calls.append(path)
        return False if len(calls) == 1 else real_create(path, record)      # someone held it at the create and released it before the read

    monkeypatch.setattr(lock, "_create", create)
    with lock.sole_writer(tmp_path, "run", "r1"):
        assert lock.read_holder(tmp_path)["pid"] == os.getpid()
    assert len(calls) == 2 and not (tmp_path / lock.LOCK_NAME).exists()


def test_the_block_s_error_is_what_the_caller_sees_and_only_the_owner_removes_the_lock(tmp_path, caplog):
    with pytest.raises(ValueError, match="the task failed"):
        with lock.sole_writer(tmp_path, "run", "r1"):
            raise ValueError("the task failed")
    assert not (tmp_path / lock.LOCK_NAME).exists()
    held = lock.acquire(tmp_path, command="run", run_key="r1")
    write_lock(tmp_path, token="0" * 32)                 # another process took the folder meanwhile (a person removed the file and ran again)
    with caplog.at_level(logging.WARNING, logger="promolift.lock"):
        lock.release(held)
    assert (tmp_path / lock.LOCK_NAME).exists() and any("is not this process's any more" in r.getMessage() for r in caplog.records)
    (tmp_path / lock.LOCK_NAME).unlink()


def test_the_record_says_the_process_its_start_the_host_the_command_the_run_and_a_token(tmp_path):
    with lock.sole_writer(tmp_path, "replay", None):
        outer = lock.read_holder(tmp_path)
        with lock.sole_writer(tmp_path, "run", "r4"):
            inner = lock.read_holder(tmp_path)
        assert lock.read_holder(tmp_path) == outer
    assert (outer["pid"], outer["host"], outer["command"], outer["run_key"]) == (os.getpid(), socket.gethostname(), "replay", None)
    assert outer["started"] == lock._process_start(os.getpid()) and len(outer["token"]) == 32
    assert (inner["command"], inner["run_key"], inner["token"]) == ("run", "r4", outer["token"])


def test_the_lock_imports_only_the_standard_library_and_the_atomic_write_that_does_too():
    """A process takes the lock without loading the pipeline: the lock imports the standard library and ``promolift.files`` (its atomic write, RNF05),
    which imports the standard library only."""
    import ast

    def imported(module: str) -> set[str]:
        tree = ast.parse((PROJECT / "src" / "promolift" / f"{module}.py").read_text(encoding="utf-8"))
        names = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        names |= {f"{node.module}.{alias.name}" if node.module == "promolift" else node.module
                  for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module for alias in node.names}
        return names

    stdlib = set(sys.stdlib_module_names) | {"__future__"}
    own = {name for name in imported("lock") if name.split(".")[0] not in stdlib}
    assert own == {"promolift.files"}, own
    assert {name.split(".")[0] for name in imported("files")} <= stdlib


def test_a_release_retries_while_the_file_is_held_and_removes_it_once_it_is_closed(tmp_path, fast_release, monkeypatch, caplog):
    """A reader that closes the file a moment later (a refused writer reading who holds it) does not leave the lock: the removal is tried
    again and succeeds, with no warning."""
    real_unlink = Path.unlink
    refusals = []

    def unlink(self, missing_ok=False):
        if self.name == lock.LOCK_NAME and len(refusals) < 2:
            refusals.append(self)
            raise PermissionError(32, "being used by another process")
        return real_unlink(self, missing_ok)

    monkeypatch.setattr(Path, "unlink", unlink)
    with caplog.at_level(logging.WARNING, logger="promolift.lock"):
        with lock.sole_writer(tmp_path, "run", "r1"):
            pass
    assert len(refusals) == 2 and not (tmp_path / lock.LOCK_NAME).exists()
    assert not [r for r in caplog.records if r.name == "promolift.lock"]


# --- what this lock keeps from project 05's: its rewrite is the atomic write of ``files`` and its words are this project's ------------------


def test_a_nested_take_says_its_record_through_the_atomic_write_of_files_and_leaves_no_temporary_file(tmp_path, monkeypatch):
    """RNF05: the rewrite of the file on a nested take (and on its release) is ``files.write_atomic``, not a second copy of the temporary file and the
    rename; the folder holds only the lock before, during and after."""
    real = files.write_atomic
    written = []

    def spy(path, data):
        written.append((Path(path).name, json.loads(data)["run_key"]))
        return real(path, data)

    monkeypatch.setattr(files, "write_atomic", spy)
    with lock.sole_writer(tmp_path, "replay", None):
        with lock.sole_writer(tmp_path, "run", "r5"):
            assert lock.read_holder(tmp_path)["run_key"] == "r5" and sorted(p.name for p in tmp_path.iterdir()) == [lock.LOCK_NAME]
        assert lock.read_holder(tmp_path)["run_key"] is None
    assert written == [(lock.LOCK_NAME, "r5"), (lock.LOCK_NAME, None)]
    assert list(tmp_path.iterdir()) == []


def test_every_refusal_names_this_project_and_its_runbook_entry(tmp_path):
    """The refusals say what to do in this project's words: ``promolift`` for the command that resumes a run and the runbook entry R8 (D26), never another project's."""
    finished = subprocess.run([sys.executable, "-c", "import os; print(os.getpid())"], capture_output=True, text=True, timeout=60)
    cases = {
        "alive": {}, "elsewhere": {"host": "another-host"}, "stale": {"pid": int(finished.stdout), "started": None},
    }
    messages = {}
    for state, record in cases.items():
        write_lock(tmp_path, **record)
        with pytest.raises(lock.RunLockedError) as error:
            lock.acquire(tmp_path, command="run")
        assert error.value.state == state
        messages[state] = str(error.value)
    (tmp_path / lock.LOCK_NAME).write_text("not json", encoding="utf-8")
    with pytest.raises(lock.RunLockedError) as error:
        lock.acquire(tmp_path, command="run")
    messages["unreadable"] = str(error.value)
    with lock.sole_writer(tmp_path / "other", "run", "r1"):
        def other():
            try:
                lock.acquire(tmp_path / "other", command="run")
            except lock.RunLockedError as refused:
                messages["thread"] = str(refused)

        thread = threading.Thread(target=other)
        thread.start()
        thread.join(timeout=30)
    assert set(messages) == {"alive", "elsewhere", "stale", "unreadable", "thread"}
    for state, message in messages.items():
        assert "R8" in message and "R9" not in message and "flotsilica" not in message.lower() and "No se escribió nada" in message, state
    assert "python -m promolift run --run-key <corrida> --from <tarea>" in messages["stale"]


# --- the review advisories of project 05's lock (R4-001, R4-002, R3-001) --------------------------------------------------------------------------


def test_a_nested_rewrite_that_retries_does_not_hold_up_another_folder(tmp_path, monkeypatch):
    """R4-001: while the inner take of one folder retries its rewrite (another process has the file open), a thread taking the lock of another
    folder is not kept waiting: the retries run outside the registry of the locks this process holds."""
    first, second = tmp_path / "a", tmp_path / "b"
    real_replace = os.replace
    seen = {}

    def replace(src, dst):
        if Path(dst) == first / lock.LOCK_NAME and "other" not in seen:
            def other():
                lock.release(lock.acquire(second, command="run", run_key="b1"))
                seen["done"] = True

            seen["other"] = thread = threading.Thread(target=other)
            thread.start()
            thread.join(timeout=1.0)
            seen["in_time"] = not thread.is_alive()
            raise PermissionError(32, "being used by another process")
        return real_replace(src, dst)

    monkeypatch.setattr(lock.os, "replace", replace)
    with lock.sole_writer(first, "replay", None):
        with lock.sole_writer(first, "run", "a1"):
            assert lock.read_holder(first)["run_key"] == "a1", "the rewrite was retried and done"
    seen["other"].join(timeout=30)
    assert seen.get("done") and seen["in_time"], "the other folder's lock waited for this folder's retries"
    assert not (first / lock.LOCK_NAME).exists() and not (second / lock.LOCK_NAME).exists() and lock._HELD == {}


def test_a_thread_that_takes_the_lock_while_another_gives_it_back_waits_and_takes_it(tmp_path, monkeypatch):
    """R3-001: a thread that asks for the lock while the thread that held it is removing the file is not refused as if a live holder were
    there: it waits for the removal and takes the lock."""
    real_read = lock.read_holder
    outcome = {}

    def read_holder(folder):
        if "thread" not in outcome:                 # the release reads who holds the file, then removes it
            def other():
                try:
                    held = lock.acquire(tmp_path, command="run", run_key="r2")
                except lock.RunLockedError as error:
                    outcome["state"] = error.state
                    return
                outcome["state"] = "taken"
                outcome["record"] = real_read(tmp_path)
                lock.release(held)

            outcome["thread"] = thread = threading.Thread(target=other)
            thread.start()
            thread.join(timeout=0.5)
        return real_read(folder)

    held = lock.acquire(tmp_path, command="run", run_key="r1")
    monkeypatch.setattr(lock, "read_holder", read_holder)
    lock.release(held)
    outcome["thread"].join(timeout=30)
    assert outcome["state"] == "taken" and outcome["record"]["run_key"] == "r2"
    assert not (tmp_path / lock.LOCK_NAME).exists() and lock._HELD == {}


def test_a_lock_from_an_earlier_boot_is_not_the_owner_even_with_the_same_start_time(tmp_path, monkeypatch):
    """R4-002: on Linux the start time counts clock ticks since the boot, so after a reboot a reused process number can show the same start
    time; the lock also says which boot took it, and a lock of another boot is stale. A lock with no boot (Windows, where the start time is a
    date, or an earlier version) keeps the comparison of the start time alone."""
    monkeypatch.setattr(lock, "_boot_id", lambda: "this-boot", raising=False)
    write_lock(tmp_path, boot="an-earlier-boot")
    with pytest.raises(lock.RunLockedError) as error:
        lock.acquire(tmp_path, command="run")
    assert error.value.state == "stale" and (tmp_path / lock.LOCK_NAME).exists()
    for same in ({"boot": "this-boot"}, {}):
        write_lock(tmp_path, **same)
        with pytest.raises(lock.RunLockedError) as error:
            lock.acquire(tmp_path, command="run")
        assert error.value.state == "alive", same
    (tmp_path / lock.LOCK_NAME).unlink()
    with lock.sole_writer(tmp_path, "run", "r1"):
        assert lock.read_holder(tmp_path)["boot"] == "this-boot", "the record says the boot that took it"


@pytest.mark.skipif(sys.platform != "win32", reason="the Windows calls (OpenProcess, GetExitCodeProcess, GetProcessTimes) are what this test exercises")
def test_on_windows_the_system_says_whether_a_process_runs_and_when_it_started(tmp_path):
    """R3-002 (project 05, U16): the ctypes calls on this machine. This process and a child it starts are alive with a start time (100-ns steps since
    1601) that does not change; the child started after this process; once the child ends it is not alive, and an id no process can have is
    neither alive nor dated (OpenProcess fails with ERROR_INVALID_PARAMETER)."""
    import time

    me = os.getpid()
    mine = lock._windows_start(me)
    now = int((time.time() + 11_644_473_600) * 10_000_000)
    assert lock._windows_alive(me) is True and isinstance(mine, int) and mine == lock._windows_start(me) == lock._process_start(me)
    assert 0 < now - mine < 7 * 24 * 3600 * 10_000_000, "a date in 100-ns steps since 1601, before now"
    child = subprocess.Popen([sys.executable, "-c", "import sys; print('up', flush=True); sys.stdin.read()"], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    try:
        assert child.stdout.readline().strip() == b"up"
        assert lock._windows_alive(child.pid) is True
        assert lock._windows_start(child.pid) > mine
    finally:
        end(child)
    assert lock._windows_alive(child.pid) is False, "ended: its exit code is no longer STILL_ACTIVE"
    impossible = 0xFFFFFFFC
    assert lock._windows_alive(impossible) is False and lock._windows_start(impossible) is None


def test_a_boot_id_that_cannot_be_decoded_is_no_boot_id_and_never_stops_the_lock(tmp_path, monkeypatch):
    """R4-boot-id-narrow-exception (F1): a boot id file whose bytes are not ASCII (an unusual mount) is read as a system that cannot tell: ``None``,
    so the lock is taken and the comparison keeps the start time alone, instead of a ``UnicodeDecodeError`` out of ``acquire``."""
    real = Path.read_text

    def read_text(self, *args, **kwargs):
        if self.name == "boot_id":
            return b"\xff\xfe".decode("ascii")      # UnicodeDecodeError, a ValueError
        return real(self, *args, **kwargs)

    monkeypatch.setattr(lock.sys, "platform", "linux")
    monkeypatch.setattr(Path, "read_text", read_text)
    assert lock._boot_id() is None
    with lock.sole_writer(tmp_path, "run", "r1"):
        assert lock.read_holder(tmp_path)["boot"] is None


# --- the review advisories of project 05's F1 (R3-release-earlyreturn-wakeup-untested, R3-boot-id-real-read-untested) ----------------------------


def test_a_release_that_finds_the_file_taken_by_another_process_still_wakes_the_thread_waiting_for_it(tmp_path, monkeypatch):
    """R3-release-earlyreturn-wakeup-untested: when the outer release finds that the file is no longer this process's (a person removed it and another process
    took the folder), it leaves the file alone and returns early; the thread parked in ``acquire`` for the end of that release is still woken, asks again and is
    refused for the other process's lock, instead of waiting for ever. The entry of the folder is gone."""
    real_read = lock.read_holder
    outcome = {}

    def read_holder(folder):
        if "thread" not in outcome:                 # the release is reading who holds the file: another thread asks for the lock now
            def other():
                try:
                    lock.acquire(tmp_path, command="run", run_key="r2")
                    outcome["state"] = "taken"
                except lock.RunLockedError as error:
                    outcome["state"] = error.state

            outcome["thread"] = thread = threading.Thread(target=other, daemon=True)     # a daemon: if the wake-up is lost it must not hold up the test run
            thread.start()
            thread.join(timeout=0.5)
            outcome["waiting"] = thread.is_alive()   # parked on the end of the release, not refused as a thread of this process
            write_lock(tmp_path, token="0" * 32)       # the file now belongs to another process
        return real_read(folder)

    held = lock.acquire(tmp_path, command="run", run_key="r1")
    monkeypatch.setattr(lock, "read_holder", read_holder)
    lock.release(held)
    outcome["thread"].join(timeout=10)
    assert outcome["waiting"] is True and not outcome["thread"].is_alive(), "woken by the early return"
    assert outcome["state"] == "alive", "then refused for the other process's lock"
    assert (tmp_path / lock.LOCK_NAME).exists() and lock.read_holder(tmp_path)["token"] == "0" * 32 and lock._HELD == {}


def test_the_boot_id_is_read_from_proc_on_linux_and_is_none_elsewhere_or_when_it_says_nothing(tmp_path, monkeypatch):
    """R3-boot-id-real-read-untested: ``_boot_id`` itself, which the other tests replace. Off Linux it is ``None`` without reading anything; on Linux it is the text of
    ``/proc/sys/kernel/random/boot_id`` stripped, and ``None`` when that file is empty or cannot be read."""
    reads = []
    real = Path.read_text

    def read_text(self, *args, **kwargs):
        if self.name == "boot_id":
            reads.append(self.as_posix())
            return answer[0]() if callable(answer[0]) else answer[0]
        return real(self, *args, **kwargs)

    def unreadable():
        raise PermissionError(13, "denied")

    answer = [" 2f0e6c1a-9d3b-4a55-8b0e-0c1d2e3f4a5b\n"]
    monkeypatch.setattr(Path, "read_text", read_text)
    monkeypatch.setattr(lock.sys, "platform", "win32")
    assert lock._boot_id() is None and reads == []
    monkeypatch.setattr(lock.sys, "platform", "linux")
    assert lock._boot_id() == "2f0e6c1a-9d3b-4a55-8b0e-0c1d2e3f4a5b" and reads == ["/proc/sys/kernel/random/boot_id"]
    for nothing in ("", "\n", unreadable):
        answer[0] = nothing
        assert lock._boot_id() is None, nothing


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the real boot id is a Linux file")
def test_on_linux_the_boot_id_is_the_one_the_system_reports():
    assert lock._boot_id() == Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip() != ""


def test_a_record_that_cannot_be_written_never_leaves_a_lock_file_behind(tmp_path, monkeypatch):
    """The lock is created and written as one step: a full disk while its record is written removes the file, so no process finds a lock nobody can read."""
    monkeypatch.setattr(lock.os, "write", lambda handle, data: (_ for _ in ()).throw(OSError(28, "No space left on device")))
    with pytest.raises(OSError, match="No space left"):
        lock.acquire(tmp_path, command="run", run_key="r1")
    monkeypatch.undo()
    assert not (tmp_path / lock.LOCK_NAME).exists() and lock._HELD == {}
    with lock.sole_writer(tmp_path, "run", "r2"):
        assert lock.read_holder(tmp_path)["run_key"] == "r2"


def test_the_folders_the_lock_created_are_removed_with_it_when_nothing_was_written_in_them(tmp_path):
    """A6 (L85): a refusal in a new copy left ``data/quick/interim/`` behind, empty, because the lock creates its folder. The outer release now removes the folders its take
    created, deepest first, while they are empty; a folder that was there, or that holds anything, stays."""
    folder = tmp_path / "data" / "quick" / "interim"
    with lock.sole_writer(folder, "run", None):
        assert (folder / lock.LOCK_NAME).is_file()
    assert not (tmp_path / "data").exists()
    with lock.sole_writer(folder, "run", None):
        (folder / "state.json").write_text("{}", encoding="utf-8")
    assert (folder / "state.json").is_file() and not (folder / lock.LOCK_NAME).exists()
    with lock.sole_writer(tmp_path / "data" / "quick" / "other", "run", None):
        pass
    assert not (tmp_path / "data" / "quick" / "other").exists() and folder.is_dir()


def test_a_take_whose_folder_another_release_just_removed_creates_it_again(tmp_path, monkeypatch):
    """The other side of the removal: between this take's ``mkdir`` and its exclusive create another process's release may remove the empty folder; the take makes it again
    and takes the lock instead of failing."""
    folder = tmp_path / "interim"
    real_create, calls = lock._create, []

    def create_after_the_folder_is_gone(path, record):
        calls.append(path)
        if len(calls) == 1:
            os.rmdir(path.parent)
        return real_create(path, record)

    monkeypatch.setattr(lock, "_create", create_after_the_folder_is_gone)
    with lock.sole_writer(folder, "run", None):
        assert (folder / lock.LOCK_NAME).is_file() and len(calls) == 2
