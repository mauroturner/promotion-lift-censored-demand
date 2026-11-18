"""The peak memory of the process, from the standard library only, with the name of the counter that gave it (RNF03; D39; plan, section 22; adapted from project 05).

Every figure says which counter it is, because two counters of the same process differ a lot: in project 02 the reported 1,471 MB were the peak working set, while the
peak committed memory of the same run reached 3,514 MB. On Windows the working set is ``PeakWorkingSetSize`` and the committed memory ``PeakPagefileUsage`` of
``GetProcessMemoryInfo`` (through ``ctypes``, with ``argtypes`` and ``restype`` declared: without them the call fails with ``OverflowError`` on 64 bits); elsewhere it is
``ru_maxrss`` of ``resource.getrusage``, in kilobytes (bytes on macOS), and there is no committed figure. A peak never falls, so the value after a task is the peak of the
process so far.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

MEGABYTE = 1024 * 1024
WINDOWS_COUNTER = "PeakWorkingSetSize"
POSIX_COUNTER = "ru_maxrss"


@dataclass(frozen=True)
class MemoryPeaks:
    """The peaks of the process so far, in megabytes (1 MB = 1,048,576 bytes). ``counter`` names the counter of ``working_set_mb``; ``commit_mb`` is None where the
    system has no counter for it (everywhere but Windows) and it is informative: no limit rests on it."""

    working_set_mb: float
    commit_mb: float | None
    counter: str


def _windows_peaks() -> tuple[int, int]:
    import ctypes
    from ctypes import wintypes

    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    kernel32, psapi = ctypes.WinDLL("kernel32", use_last_error=True), ctypes.WinDLL("psapi", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessMemoryCounters), wintypes.DWORD]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    counters = ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    if not psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    return int(counters.PeakWorkingSetSize), int(counters.PeakPagefileUsage)


def _posix_peak() -> int:
    import resource

    peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return peak if sys.platform == "darwin" else peak * 1024


def peak_memory() -> MemoryPeaks:
    """The peak memory of this process so far; ``OSError`` if the system will not say."""
    if sys.platform == "win32":
        working_set, commit = _windows_peaks()
        counter = WINDOWS_COUNTER
    else:
        working_set, commit, counter = _posix_peak(), 0, POSIX_COUNTER
    if working_set <= 0:
        raise OSError("El sistema no informó el pico de memoria del proceso")
    return MemoryPeaks(working_set / MEGABYTE, commit / MEGABYTE if commit > 0 else None, counter)
