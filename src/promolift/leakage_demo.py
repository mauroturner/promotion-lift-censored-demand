"""The leak, shown on purpose (D19; plan, section 16): what a recovery that reads the daily total of sales would give, and that the trap M01 would stop it.

The total of a series-day is the sum of its 24 hourly sales, so it contains what the hours hidden by a synthetic mask sold: a method that subtracts from it what it can
see recovers the hidden mass exactly in a simulation, and in a real stock-out, where those hours sold nothing, it would give back only noise. ``leaky_hidden_mass``
is that method (it is also the control that the tests hand to the launch to see M01 stop it) and ``leakage_table`` reports its error next to the honest ones.

This module reads and reports: it never writes to the registry, the estimates or the forecasts, and nothing that chooses imports it (static tests read this file for it).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd

from promolift.cube import DayInputs
from promolift.masks import Mask, apply

CHECKS_ES = {
    "r1": "La media simple de la serie, la hora y el estado del día",
    "chosen": "El método de recuperación que eligió el lanzamiento, ajustado en el entrenamiento",
    "reads_daily_total": "Una recuperación que lee el total diario de la venta, que contiene las horas ocultas",
}
NOTES_ES = {
    "r1": "La referencia: lo que se obtiene sin mirar nada del día.",
    "chosen": "La cifra honesta: el método no ve nada de las horas que se ocultan.",
    "reads_daily_total": "Parece casi perfecta porque el total ya incluye la venta oculta; en un quiebre real esas horas no vendieron nada y no serviría. La trampa M01 detiene un lanzamiento así.",
}


def leaky_hidden_mass(cube: Any, inputs: DayInputs, mask: Mask) -> np.ndarray:
    """The hidden mass of each masked series-day as a method that reads the daily total finds it: that total (the 24 hours of the cube, ``sale_amount``) minus
    the sale of every hour the method can see (the analysis hours that were not hidden and the night)."""
    total = np.asarray(cube.sales(inputs.date_key), dtype=np.float64)[inputs.series_key[mask.rows].astype(np.intp)]
    night = [hour for hour in range(total.shape[1]) if hour not in set(inputs.hours.tolist())]
    visible = np.nansum(apply(inputs, mask).sales[mask.rows], axis=1, dtype=np.float64) + total[:, night].sum(axis=1)
    return total.sum(axis=1) - visible


def leakage_table(wape: Mapping[str, float], bias: Mapping[str, float], rows: Mapping[str, int], *, ratio: float) -> pd.DataFrame:
    """``check_id``, ``description_es``, ``wape``, ``bias``, ``rows``, ``trips_m01`` and ``note_es`` of each method measured on the V2 mask: whether the trap M01
    (an error under `ratio` times that of R1) would stop it; R1 itself never does."""
    return pd.DataFrame([
        {"check_id": name, "description_es": CHECKS_ES[name], "wape": float(wape[name]), "bias": float(bias[name]), "rows": int(rows[name]),
         "trips_m01": bool(name != "r1" and wape[name] < ratio * wape["r1"]), "note_es": NOTES_ES[name]}
        for name in wape])
