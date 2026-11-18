"""The words of the results (RF19, D16, D21; plan, section 16): the one place that has the text of a criterion, of a method and of a verdict, so that the summary, the
README, the model card, the dashboard and the site say the same thing in the same way.

A verdict is a sentence made from the numbers of its criterion: it names the comparison it makes, says whether the model beats the other side, loses to it or ties
with it (a tie never passes), and where. ``es`` writes a number as the Spanish text shows it: a comma for the decimals, a point for the thousands and the minus sign of
typography; nothing in the documents is written by hand (project 05's B3).
"""

from __future__ import annotations

import math
from typing import NamedTuple


class CriterionText(NamedTuple):
    name_es: str
    threshold_es: str
    seen_by_research: str
    seen_by_planner: str


# id: name, threshold, what the research saw, what the planner saw (requirements.md, 8.1; D16)
CRITERIA: dict[str, CriterionText] = {
    "C01": CriterionText("La recuperación supera a la media simple",
                         "límite superior del intervalo del 95 % de WAPE por serie (recuperación) − WAPE por serie (R1) < 0, en la máscara de cola de la prueba", "no", "sí"),
    "C02": CriterionText("La masa recuperada no tiene sesgo grande", "|sesgo de la recuperación| ≤ {max_abs_bias} en la máscara de cola de la prueba", "no", "sí"),
    "C03": CriterionText("La recuperación no cambia el aumento",
                         "|(1 + sesgo en días con promoción) / (1 + sesgo en días regulares) − 1| ≤ {max_abs_lift_bias} en la máscara de cola de la prueba", "no", "en parte"),
    "C04": CriterionText("Los quiebres esconden parte del efecto",
                         "límite inferior del intervalo del 95 % del aumento total recuperado − el crudo, en la prueba, > 0", "sí", "sí"),
    "C05": CriterionText("El orden de las celdas se repite",
                         "correlación de Spearman entre los aumentos sellados y los de la prueba, en las celdas con series suficientes en las dos, ≥ {min_spearman}", "no", "sí"),
    "C06": CriterionText("El nivel de cada celda se repite",
                         "proporción de esas celdas cuyo intervalo de la diferencia prueba − sellado contiene 0 ≥ {min_share}", "no", "sí"),
    "C07": CriterionText("Más descuento, más aumento",
                         "correlación de Spearman entre la profundidad de la banda y su aumento en la prueba ≥ {min_spearman}", "sí", "sí"),
    "C08": CriterionText("El aumento de la celda mejora el pronóstico",
                         "límite superior del intervalo del 95 % de WAPE(F2) − WAPE(F2a) < 0, en las series-días con promoción de la prueba", "no", "sí"),
    "C09": CriterionText("El pronóstico con el aumento supera a la regla ingenua",
                         "límite superior del intervalo del 95 % de WAPE(F2) − WAPE(F1) < 0, en las mismas series-días", "no", "sí"),
    "C10": CriterionText("Variantes y seguimiento (informativo)", "sin umbral: que esté escrito y sea consistente", "en parte", "sí, en el entrenamiento y la validación"),
}

# which key of the configuration's ``[criteria]`` fills which placeholder of a threshold
_THRESHOLD_KEYS = {"C02": {"max_abs_bias": "c02_max_abs_bias"}, "C03": {"max_abs_lift_bias": "c03_max_abs_lift_bias"}, "C05": {"min_spearman": "c05_min_spearman"},
                   "C06": {"min_share": "c06_min_consistent_share"}, "C07": {"min_spearman": "c07_min_spearman"}}
FORECAST_LABELS_ES = {"f0_no_lift": "F0, el contrafactual sin aumento", "f1_naive": "F1, la media de los 7 días anteriores de la serie",
                      "f2a_overall_lift": "F2a, un solo aumento total", "f2_cell_lift": "F2, el aumento de la celda"}


def es(value: float | None, decimals: int = 3, *, percent: bool = False) -> str:
    """A number as the Spanish text shows it: a comma for the decimals, a point for the thousands and «−» for the minus sign; «sin dato» if there is none. With
    `percent` the number is a fraction written as « x %». A number that rounds to zero never carries a minus sign."""
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return "sin dato"
    text = f"{(value * 100 if percent else value):,.{decimals}f}"
    if text.startswith("-") and not any(ch in "123456789" for ch in text):
        text = text[1:]
    text = text.replace(",", "§").replace(".", ",").replace("§", ".").replace("-", "−")
    return f"{text} %" if percent else text


def threshold_of(criterion_id: str, **numbers: float) -> str:
    """The threshold of a criterion as the summary shows it, with the limits of the configuration written in it (two decimals)."""
    return CRITERIA[criterion_id].threshold_es.format(**{k: es(v, 2) for k, v in numbers.items()})


def thresholds_from(criteria_document: dict[str, float]) -> dict[str, str]:
    """The threshold text of each criterion from the sealed ``[criteria]`` of the configuration."""
    return {cid: threshold_of(cid, **{placeholder: criteria_document[key] for placeholder, key in _THRESHOLD_KEYS.get(cid, {}).items()}) for cid in CRITERIA}


def method_label(name: str) -> str:
    """``r2@0.25`` as «R2 con κ = 0,25», ``r1`` as «R1 (la media simple)»."""
    if name.startswith("r2@"):
        return f"R2 con κ = {es(float(name[3:]), 2)}"
    return {"r0": "R0 (cero)", "r1": "R1 (la media simple)", "r3": "R3 (gradient boosting)"}.get(name, name)


def points(value: float | None) -> str:
    """A difference of fractions in points, as «1,5 puntos»."""
    return f"{es(None if value is None else value * 100, 2)} puntos"


def interval_es(low: float | None, high: float | None) -> str:
    return f"la diferencia va de {es(None if low is None else low * 100, 2)} a {points(high)}"


def pending_reason(ready_instant: str, as_of: str) -> str:
    """Why the criteria are pending before the close (the date of the close, from its instant)."""
    del as_of
    return f"La prueba se evalúa con el cierre del {ready_instant[:10]}: hasta entonces los criterios quedan pendientes."


def verdict(criterion_id: str, passed: bool, **f: object) -> str:
    """The sentence of a criterion made from its figures (see ``evaluation.criteria_of``); it names its own comparison and never another's."""
    if criterion_id == "C01":
        return (f"La recuperación ({method_label(str(f['method']))}) {'supera' if passed else 'no supera'} a la media simple (R1) en la máscara de cola de la prueba: "
                f"WAPE por serie {es(f['a'], 1, percent=True)} frente a {es(f['b'], 1, percent=True)}; {interval_es(f['low'], f['high'])}.")
    if criterion_id == "C02":
        direction = "de más" if (f["bias"] or 0) > 0 else "de menos"
        return (f"El sesgo de la masa recuperada {'cumple' if passed else 'no cumple'}: la recuperación estima {es(abs(f['bias']), 1, percent=True)} {direction} "
                f"y se pedía a lo sumo {es(f['limit'], 1, percent=True)}.")
    if criterion_id == "C03":
        return (f"La recuperación {'no cambia' if passed else 'cambia'} el aumento: el sesgo en días con promoción frente al de los días regulares lo mueve "
                f"{es(abs(f['lift_bias']), 1, percent=True)}, y se pedía a lo sumo {es(f['limit'], 1, percent=True)}.")
    if criterion_id == "C04":
        return (f"Los quiebres {'esconden' if passed else 'no esconden'} parte del efecto: el aumento total con la demanda recuperada es {es(f['a'], 1, percent=True)} frente a "
                f"{es(f['b'], 1, percent=True)} con la venta cruda; {interval_es(f['low'], f['high'])}.")
    if criterion_id == "C05":
        return (f"El orden de las celdas {'se repite' if passed else 'no se repite'} en la semana de prueba: correlación de Spearman {es(f['value'], 3)} entre el aumento sellado "
                f"y el de la prueba, sobre {f['cells']} celdas, y se pedía al menos {es(f['limit'], 2)}.")
    if criterion_id == "C06":
        return (f"El nivel de cada celda {'se repite' if passed else 'no se repite'}: el intervalo de la diferencia prueba − sellado contiene 0 en el "
                f"{es(f['value'], 1, percent=True)} de {f['cells']} celdas, y se pedía al menos {es(f['limit'], 1, percent=True)}.")
    if criterion_id == "C07":
        return (f"Más descuento, {'más' if passed else 'no más'} aumento: correlación de Spearman {es(f['value'], 3)} entre la profundidad de la banda y su aumento en la prueba, "
                f"y se pedía al menos {es(f['limit'], 2)}.")
    if criterion_id == "C08":
        return (f"El aumento de la celda {'mejora' if passed else 'no mejora'} el pronóstico frente a un aumento único (F2a): WAPE de F2 {es(f['a'], 1, percent=True)} frente a "
                f"{es(f['b'], 1, percent=True)} de F2a; {interval_es(f['low'], f['high'])}.")
    if criterion_id == "C09":
        return (f"El pronóstico con el aumento de la celda {'supera' if passed else 'no supera'} a la regla ingenua (F1), la media de los días anteriores de la propia serie: "
                f"WAPE de F2 {es(f['a'], 1, percent=True)} frente a {es(f['b'], 1, percent=True)} de F1; {interval_es(f['low'], f['high'])}.")
    raise ValueError(f"criterio sin veredicto: {criterion_id!r}")


def informative_verdict(variants: int, days: int) -> str:
    return f"Informativo, sin umbral: se escribieron {variants} cifras de variantes y el seguimiento de {days} días de la prueba."


def cannot(why: str) -> str:
    """The verdict of a criterion that cannot be computed: it is never passed (requirements, section 8.1)."""
    return f"No se puede calcular: {why}."
