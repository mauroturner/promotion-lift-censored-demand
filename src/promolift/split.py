"""The split in time (RF05, D14; plan, section 9): the block of each day and the check of the blocks.

Training, the purge, V1 (where the recovery method and kappa are chosen), V2 (the preview that chooses nothing) and the test week follow
one another in time. The purge days belong to no block of the model, and a day outside every window is ``outside``. Nothing that is fitted
looks across days, so there is no purge between V1 and V2 or before the test (D14). ``sql/staging/stg_series_days.sql`` assigns the same
blocks in SQL; a test compares the two.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import numpy as np
import pandas as pd

BLOCKS = ("train", "purge", "valid_v1", "valid_v2", "test", "outside")
MODEL_BLOCKS = ("train", "valid_v1", "valid_v2", "test")
ORDER = ("train", "purge", "valid_v1", "valid_v2", "test")
DAY = timedelta(days=1)


class SplitError(ValueError):
    """The split of the configuration breaks a rule of D14; the message names the block or the edge."""


def block_of(days: pd.DatetimeIndex, view: Any) -> pd.Series:
    """The block of each day of `days`, as a Series indexed by `days` in the order given: one of ``BLOCKS``.

    Each block holds its window from its first day to its last, both included; a day in no window is ``outside``."""
    index = pd.DatetimeIndex(days)
    day = index.normalize()
    values = np.full(len(index), "outside", dtype=object)
    for name in ORDER:
        first, last = getattr(view.split, name)
        values[(day >= pd.Timestamp(first)) & (day <= pd.Timestamp(last))] = name
    return pd.Series(values, index=index, dtype=object)


def check_split(view: Any) -> None:
    """Raise ``SplitError`` naming the block or the edge if the split of `view` (``[calendar]`` and ``[split]``) breaks D14 (AC09): a pair
    that is not two dates in order, a block outside the calendar, two consecutive blocks that overlap or come in the wrong order, a V2 that
    ends after the launch, or a test that is not exactly the days after the launch."""
    c, s = view.calendar, view.split
    windows = {name: getattr(s, name) for name in ORDER}
    for name, pair in windows.items():
        if len(pair) != 2:
            raise SplitError(f"[split] {name}: se esperaban dos fechas (la primera y la última), se recibió {list(pair)}")
        if pair[0] > pair[1]:
            raise SplitError(f"[split] {name}: par desordenado, la primera fecha ({pair[0]}) es posterior a la última ({pair[1]})")
        if pair[0] < c.first_day:
            raise SplitError(f"[split] {name}: no puede empezar antes de first_day de [calendar] ({c.first_day}), se recibió {pair[0]}")
        if pair[1] > c.last_day:
            raise SplitError(f"[split] {name}: no puede terminar después de last_day de [calendar] ({c.last_day}), se recibió {pair[1]}")
    for before, after in zip(ORDER, ORDER[1:]):
        last, first = windows[before][1], windows[after][0]
        if first <= last:
            raise SplitError(
                f"borde {before} → {after}: {before} termina el {last} y {after} empieza el {first}; deben ir en ese orden y sin solaparse"
            )
    if s.valid_v2[1] > c.launch_last_day:
        raise SplitError(f"[split] valid_v2: el lanzamiento debe incluir todo V2 (launch_last_day = {c.launch_last_day}), V2 termina el {s.valid_v2[1]}")
    if s.test[0] != c.launch_last_day + DAY:
        raise SplitError(
            f"[split] test: debe empezar el día siguiente a launch_last_day ({c.launch_last_day + DAY}): la prueba es lo que llega después "
            f"del lanzamiento, se recibió {s.test[0]}"
        )
    if s.test[1] != c.last_day:
        raise SplitError(f"[split] test: debe terminar en last_day de [calendar] ({c.last_day}), se recibió {s.test[1]}")
