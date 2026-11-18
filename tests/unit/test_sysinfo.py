"""The peak memory of the process with the name of its counter (U16; RNF03, AC27; D39; plan, section 22; adapted from project 05's test): every task of a run records the peak
with its counter, a system that reports none is an error, and a task whose peak cannot be measured keeps its result."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from promolift import pipeline, sysinfo
from promolift.sysinfo import MemoryPeaks, peak_memory
from tests.fixtures.pipeline_state import copy_state


def test_every_task_records_its_peak_with_its_counter(pipeline_launched):
    """RNF03, D39: the peak is ``PeakWorkingSetSize`` on Windows and ``ru_maxrss`` elsewhere (``PeakPagefileUsage`` informative, only on Windows), and each task of the launch run
    recorded it in its result and in the state file of its run with the name of the counter and its seconds."""
    peaks = peak_memory()
    assert isinstance(peaks, MemoryPeaks) and peaks.working_set_mb > 0
    assert peaks.counter == ("PeakWorkingSetSize" if sys.platform == "win32" else "ru_maxrss")
    assert (peaks.commit_mb is not None and peaks.commit_mb > 0) == (sys.platform == "win32")
    saved = json.loads((Path(pipeline_launched.cfg.paths.interim_dir) / "runs" / "launch.json").read_text(encoding="utf-8"))["tasks"]
    assert list(saved) == list(pipeline.TASK_IDS)
    for done in pipeline_launched.results:
        result = done["result"]
        assert result["peak_working_set_mb"] > 0 and result["memory_counter"] == peaks.counter and result["seconds"] >= 0
        assert saved[done["task"]]["memory_counter"] == peaks.counter and saved[done["task"]]["peak_working_set_mb"] == result["peak_working_set_mb"]


def test_every_task_of_every_run_of_the_flow_names_its_counter(pipeline_replayed):
    """AC27, RNF03: in the state of every run of a whole replay, each task that ran says its peak with the counter's name, and the closed runs say it in SQLite too."""
    cfg, counter = pipeline_replayed.cfg, peak_memory().counter
    states = sorted((Path(cfg.paths.interim_dir) / "runs").glob("*.json"))
    assert len(states) == 10
    tasks = [(path.stem, task_id, task) for path in states for task_id, task in json.loads(path.read_text(encoding="utf-8"))["tasks"].items()]
    assert len(tasks) == 11 * 9 + 2 and all(task["memory_counter"] == counter and task["peak_working_set_mb"] > 0 and task["seconds"] >= 0 for _, _, task in tasks)


def test_a_system_that_reports_no_peak_is_an_error(monkeypatch):
    """The counter is read, not assumed: a zero from the system is an ``OSError`` with its reason, and never a peak of 0 MB."""
    monkeypatch.setattr(sysinfo, "_windows_peaks", lambda: (0, 0), raising=False)
    monkeypatch.setattr(sysinfo, "_posix_peak", lambda: 0, raising=False)
    with pytest.raises(OSError, match="no informó el pico de memoria"):
        peak_memory()


def test_a_task_whose_peak_cannot_be_measured_keeps_its_result(pipeline_launched, tmp_path, quick_cfg, monkeypatch):
    """Telemetry never discards what a task did: when the peak cannot be read, the task's result is saved with no peak and no counter."""
    def refuses() -> MemoryPeaks:
        raise OSError("the system will not say")

    monkeypatch.setattr(pipeline, "peak_memory", refuses)
    state = copy_state(pipeline_launched, tmp_path / "state", quick_cfg)
    result = pipeline.run_task("fetch_source", "S2", state.cfg)
    assert result["peak_working_set_mb"] is None and result["peak_commit_mb"] is None and result["memory_counter"] is None and result["train_sha256"]
    assert json.loads((Path(state.cfg.paths.interim_dir) / "runs" / "S2.json").read_text(encoding="utf-8"))["tasks"]["fetch_source"]["memory_counter"] is None
