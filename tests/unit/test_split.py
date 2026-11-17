"""The split in time (U02; RF05, D14; AC09): the blocks by day, the purge that belongs to no block, a configuration that breaks an edge
refused by the edge's name, and the test week that is exactly what comes after the launch. The same rule as the SQL staging is compared
in U06 (``tests/integration/test_load.py``)."""

from __future__ import annotations

import dataclasses
from datetime import date

import pandas as pd
import pytest

from promolift.config import SealedConfig
from promolift.split import BLOCKS, MODEL_BLOCKS, SplitError, block_of, check_split

SEEN = "a" * 64


def resplit(cfg, **changes):
    return dataclasses.replace(cfg, split=dataclasses.replace(cfg.split, **changes))


def recalendar(cfg, **changes):
    return dataclasses.replace(cfg, calendar=dataclasses.replace(cfg.calendar, **changes))


def test_blocks_are_ordered_disjoint_and_purge_days_belong_to_no_block(cfg):
    s = cfg.split
    days = pd.date_range("2024-03-20", "2024-07-10", freq="D")
    blocks = block_of(days, cfg)
    assert list(blocks.index) == list(days) and set(blocks) == set(BLOCKS)
    windows = {"train": s.train, "purge": s.purge, "valid_v1": s.valid_v1, "valid_v2": s.valid_v2, "test": s.test}
    for name, (first, last) in windows.items():
        inside = blocks[(days >= pd.Timestamp(first)) & (days <= pd.Timestamp(last))]
        assert set(inside) == {name} and len(inside) == (last - first).days + 1, name
        assert set(blocks[blocks == name].index) == set(inside.index), f"{name} holds no day outside its window"
    assert [len(blocks[blocks == name]) for name in ("train", "purge", "valid_v1", "valid_v2", "test")] == [65, 7, 9, 9, 7]
    assert not set(blocks[blocks == "purge"]) & set(MODEL_BLOCKS), "a purge day belongs to no block of the model"
    assert set(blocks[blocks == "purge"].index).isdisjoint(blocks[blocks.isin(MODEL_BLOCKS)].index)
    # the edges: the day on each side of every boundary belongs to its own block, and the days outside the windows are outside
    assert blocks["2024-05-31"] == "train" and blocks["2024-06-01"] == "purge" and blocks["2024-06-07"] == "purge"
    assert blocks["2024-06-08"] == "valid_v1" and blocks["2024-06-16"] == "valid_v1" and blocks["2024-06-17"] == "valid_v2"
    assert blocks["2024-06-25"] == "valid_v2" and blocks["2024-06-26"] == "test" and blocks["2024-07-02"] == "test"
    assert set(blocks[days < pd.Timestamp(s.train[0])]) == {"outside"} and set(blocks[days > pd.Timestamp(s.test[1])]) == {"outside"}
    check_split(cfg)
    check_split(SealedConfig.of(cfg, SEEN, SEEN))


def test_block_of_follows_the_order_and_the_index_it_is_given_and_ignores_the_time_of_day(cfg):
    days = pd.DatetimeIndex(["2024-06-26", "2024-03-28", "2024-06-09 15:30", "2024-06-03", "2024-03-28", "2024-03-27 23:59", "2024-07-03"])
    blocks = block_of(days, cfg)
    assert blocks.tolist() == ["test", "train", "valid_v1", "purge", "train", "outside", "outside"] and list(blocks.index) == list(days)
    assert block_of(pd.DatetimeIndex([]), cfg).empty and len(days) == 7


def test_a_day_between_two_windows_is_outside(cfg):
    """The windows need not touch: a gap between two of them holds days that belong to no block, and the check accepts it."""
    gapped = resplit(cfg, valid_v1=(date(2024, 6, 10), date(2024, 6, 16)))
    check_split(gapped)
    blocks = block_of(pd.DatetimeIndex(["2024-06-07", "2024-06-08", "2024-06-09", "2024-06-10"]), gapped)
    assert blocks.tolist() == ["purge", "outside", "outside", "valid_v1"]


def test_an_edge_that_overlaps_or_is_out_of_order_is_refused_with_the_name_of_the_edge(cfg):
    cases = [
        (dict(train=(date(2024, 3, 28), date(2024, 6, 3))), r"borde train → purge"),
        (dict(train=(date(2024, 3, 28), date(2024, 6, 1))), r"borde train → purge"),
        (dict(purge=(date(2024, 5, 31), date(2024, 6, 7))), r"borde train → purge"),
        (dict(purge=(date(2024, 6, 1), date(2024, 6, 8))), r"borde purge → valid_v1"),
        (dict(valid_v1=(date(2024, 6, 7), date(2024, 6, 16))), r"borde purge → valid_v1"),
        (dict(valid_v1=(date(2024, 6, 8), date(2024, 6, 17))), r"borde valid_v1 → valid_v2"),
        (dict(valid_v2=(date(2024, 6, 16), date(2024, 6, 25))), r"borde valid_v1 → valid_v2"),
        (dict(valid_v2=(date(2024, 6, 17), date(2024, 6, 26))), r"borde valid_v2 → test"),
        (dict(test=(date(2024, 6, 25), date(2024, 7, 2))), r"borde valid_v2 → test"),
    ]
    for changes, match in cases:
        for view in (resplit(cfg, **changes), SealedConfig.of(resplit(cfg, **changes), SEEN, SEEN)):
            with pytest.raises(SplitError, match=match):
                check_split(view)
    assert issubclass(SplitError, ValueError)
    one_day = resplit(cfg, valid_v1=(date(2024, 6, 15), date(2024, 6, 15)))
    check_split(one_day)                       # a block of one day is a block
    assert block_of(pd.DatetimeIndex(["2024-06-15"]), one_day).tolist() == ["valid_v1"]
    check_split(resplit(cfg, purge=(date(2024, 6, 1), date(2024, 6, 1))))


def test_a_pair_that_is_not_two_dates_in_order_or_leaves_the_calendar_is_refused(cfg):
    cases = [
        (dict(train=(date(2024, 5, 31), date(2024, 3, 28))), r"\[split\] train.*desordenado"),
        (dict(valid_v1=(date(2024, 6, 8),)), r"\[split\] valid_v1.*dos fechas"),
        (dict(test=()), r"\[split\] test.*dos fechas"),
        (dict(train=(date(2024, 3, 27), date(2024, 5, 31))), r"\[split\] train.*first_day"),
        (dict(test=(date(2024, 6, 26), date(2024, 7, 3))), r"\[split\] test.*last_day"),
        (dict(valid_v2=(date(2024, 6, 17), date(2024, 7, 3))), r"\[split\] valid_v2.*last_day"),
    ]
    for changes, match in cases:
        with pytest.raises(SplitError, match=match):
            check_split(resplit(cfg, **changes))


def test_v2_ends_with_the_launch_and_the_test_is_exactly_the_days_after_it(cfg):
    with pytest.raises(SplitError, match=r"\[split\] valid_v2.*launch_last_day"):
        check_split(recalendar(cfg, launch_last_day=date(2024, 6, 24)))
    with pytest.raises(SplitError, match=r"\[split\] test.*empezar el día siguiente a launch_last_day"):
        check_split(resplit(cfg, test=(date(2024, 6, 27), date(2024, 7, 2))))
    with pytest.raises(SplitError, match=r"\[split\] test.*terminar en last_day"):
        check_split(resplit(cfg, test=(date(2024, 6, 26), date(2024, 7, 1))))
    # the launch may end after V2 as long as the test follows it
    later = recalendar(resplit(cfg, test=(date(2024, 6, 27), date(2024, 7, 2))), launch_last_day=date(2024, 6, 26))
    check_split(later)
