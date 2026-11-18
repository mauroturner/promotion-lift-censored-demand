"""A frozen model as small as the artifact and the seal tests need it (U09)."""

from __future__ import annotations

import numpy as np

from promolift.effect import Counterfactual, Lifts
from promolift.recovery import Recovery
from promolift.registry import MODEL_VERSION, LaunchBundle

SERIES, HOURS, GROUPS, DAYS, BANDS = 4, 16, 3, 5, 7


def tiny_bundle(method: str = "r2", r3=None, seed: int = 0) -> LaunchBundle:
    rng = np.random.default_rng(seed)
    group_ids = np.array([10, 20, 30])
    days = np.arange(20240601, 20240601 + DAYS, dtype=np.int32)
    recovery = Recovery(method, 0.25 if method == "r2" else None, rng.random((SERIES, 2, HOURS)), r3, group_ids)
    cf = {version: Counterfactual(rng.random((SERIES, HOURS)), rng.random((GROUPS, DAYS)), days, version, group_ids) for version in ("raw", "recovered")}
    lifts = {version: Lifts(0.4 + 0.1 * k, rng.random(GROUPS * BANDS)) for k, version in enumerate(("raw", "recovered"))}
    return LaunchBundle(MODEL_VERSION, recovery, np.full(HOURS, 1 / HOURS), cf, lifts, group_ids, BANDS, (6, 21))
