"""The inputs of the methods (U07; RNF06 a, D05, D19; AC10): a daily field that holds the target cannot reach a method, in the data or in the code."""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from promolift.cube import INPUT_COLUMNS, BlockInputs, DayInputs, LeakageError, build_inputs, group_index
from promolift.schema import FORBIDDEN_COLUMNS, TARGET_COLUMNS

SRC = Path(__file__).resolve().parents[2] / "src" / "promolift"
# the modules whose code decides what a method sees or issues (the leak demonstration is the one that names the field, on purpose)
MODEL_MODULES = ("cube.py", "masks.py", "recovery.py", "effect.py", "forecast.py", "bootstrap.py", "ranking.py", "registry.py", "launch.py")


def frame(**extra) -> pd.DataFrame:
    return pd.DataFrame({**{name: [1.0, 2.0] for name in INPUT_COLUMNS}, **extra})


def test_the_inputs_of_a_method_are_the_ones_on_the_list_in_their_order():
    out = build_inputs(frame().loc[:, ::-1])
    assert list(out.columns) == list(INPUT_COLUMNS) and out.shape == (2, len(INPUT_COLUMNS))
    assert set(INPUT_COLUMNS).isdisjoint(FORBIDDEN_COLUMNS) and set(INPUT_COLUMNS).isdisjoint(TARGET_COLUMNS)


@pytest.mark.parametrize("name", [*FORBIDDEN_COLUMNS, *TARGET_COLUMNS])
def test_forbidden_columns_cannot_reach_any_input(name):
    with pytest.raises(LeakageError, match=rf"prohibida '{name}'"):
        build_inputs(frame(**{name: [0.0, 0.0]}))


def test_a_column_that_is_not_on_the_list_is_refused_by_name_without_calling_it_forbidden():
    with pytest.raises(LeakageError, match="'something_else'.*permitidas") as caught:
        build_inputs(frame(something_else=[0.0, 0.0]))
    assert "prohibida" not in str(caught.value)


def test_a_frame_that_misses_an_input_is_refused_by_name():
    with pytest.raises(LeakageError, match="cut"):
        build_inputs(frame().drop(columns=["cut"]))


@pytest.mark.parametrize("module", MODEL_MODULES)
def test_model_code_never_names_a_forbidden_column(module):
    text = (SRC / module).read_text(encoding="utf-8")
    named = [name for name in FORBIDDEN_COLUMNS if re.search(rf"\b{name}\b", text)]
    assert named == [], f"{module} names {named}"


def test_the_cube_hands_a_method_only_the_hours_the_state_the_band_and_the_group():
    assert [f.name for f in dataclasses.fields(DayInputs)] == ["series_key", "date_key", "hours", "sales", "stock", "state", "band", "group"]
    assert [f.name for f in dataclasses.fields(BlockInputs)] == ["series_key", "date_keys", "hours", "sales", "stock", "state", "band", "group"]


def test_a_group_id_is_its_position_among_the_sorted_ids_and_an_unknown_one_is_refused():
    ids = np.array([3, 7, 12])
    assert group_index(np.array([12, 3, 3, 7]), ids).tolist() == [2, 0, 0, 1]
    with pytest.raises(ValueError, match="99"):
        group_index(np.array([3, 99]), ids)
