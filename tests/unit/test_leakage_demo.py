"""The leak shown on purpose (U09; D19; AC13): a recovery that reads the daily total finds the hidden mass exactly, and that is what the trap M01 is for.
The demonstration only reads and reports."""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from promolift.cube import DayInputs
from promolift.days import PROMO
from promolift.leakage_demo import leakage_table, leaky_hidden_mass
from promolift.masks import Mask

SRC = Path(__file__).resolve().parents[2] / "src" / "promolift"
H = 16


class FakeCube:
    """The 24 hours of one day of three series, as the cube holds them."""

    def __init__(self):
        self.day = np.arange(72, dtype=np.float32).reshape(3, 24) / 7

    def sales(self, date_key):
        assert date_key == 20240601
        return self.day


def hand_day(cube: FakeCube) -> DayInputs:
    return DayInputs(np.arange(3, dtype=np.int32), 20240601, np.arange(6, 22), cube.day[:, 6:22].copy(), np.zeros((3, H), dtype=np.int8),
                     np.full(3, PROMO, dtype=np.int8), np.full(3, 2, dtype=np.int8), np.zeros(3, dtype=np.int64))


def test_a_method_that_reads_the_daily_total_gets_the_hidden_mass_of_every_series_day_right():
    cube = FakeCube()
    inputs = hand_day(cube)
    hidden = np.zeros((2, H), dtype=bool)
    hidden[0, 10:] = True
    hidden[1, 3:7] = True
    mask = Mask(np.array([0, 2]), hidden, np.array([16, 9]))
    guess = leaky_hidden_mass(cube, inputs, mask)
    expected = [cube.day[0, 6 + 10:22].sum(), cube.day[2, 6 + 3:6 + 7].sum()]
    assert guess.tolist() == pytest.approx([float(x) for x in expected], rel=1e-6)
    # it reads only what a method would see once the hours are hidden plus the total: hiding other values changes nothing
    other = hand_day(cube)
    other.sales[0, 10:] = 1e6
    assert leaky_hidden_mass(cube, other, mask).tolist() == pytest.approx([float(x) for x in expected], rel=1e-6)


def test_the_table_reports_each_method_its_error_and_whether_the_trap_would_stop_it():
    table = leakage_table({"r1": 0.38, "chosen": 0.31, "reads_daily_total": 0.002}, {"r1": 0.1, "chosen": 0.01, "reads_daily_total": 0.0}, {"r1": 40, "chosen": 40, "reads_daily_total": 40},
                          ratio=0.5)
    assert isinstance(table, pd.DataFrame) and list(table.columns) == ["check_id", "description_es", "wape", "bias", "rows", "trips_m01", "note_es"]
    by = table.set_index("check_id")
    assert by["trips_m01"].to_dict() == {"r1": False, "chosen": False, "reads_daily_total": True}
    assert by.loc["reads_daily_total", "wape"] == 0.002 and by["description_es"].str.len().min() > 10 and by["note_es"].str.len().min() > 10


def test_the_demonstration_writes_nothing_and_nothing_that_chooses_imports_it():
    text = (SRC / "leakage_demo.py").read_text(encoding="utf-8")
    assert not re.search(r"\b(INSERT|UPDATE|DELETE|executemany|to_parquet|write_atomic|open\()", text)
    for module in ("recovery.py", "effect.py", "bootstrap.py", "ranking.py", "forecast.py", "masks.py", "cube.py", "registry.py"):
        assert "leakage_demo" not in (SRC / module).read_text(encoding="utf-8"), module
