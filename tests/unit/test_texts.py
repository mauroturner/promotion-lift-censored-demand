"""The words of the results (U11; RF19, D21): numbers as the Spanish text shows them, and the fixed text of every criterion (requirements, section 8.1)."""

from __future__ import annotations

import pytest

from promolift import texts


@pytest.mark.parametrize(("value", "decimals", "percent", "expected"), [
    (0.5, 3, False, "0,500"), (1234567.891, 1, False, "1.234.567,9"), (-0.25, 2, False, "−0,25"), (0.4338, 1, True, "43,4 %"),
    (-0.0004, 2, False, "0,00"), (-0.0004, 1, True, "0,0 %"), (None, 2, False, "sin dato"), (float("nan"), 2, True, "sin dato"), (0.0, 0, False, "0")])
def test_es_writes_the_comma_the_thousands_point_and_the_typographic_minus_and_never_minus_zero(value, decimals, percent, expected):
    assert texts.es(value, decimals, percent=percent) == expected


def test_every_criterion_has_its_fixed_text_with_what_the_research_and_the_planner_saw():
    assert list(texts.CRITERIA) == [f"C{k:02d}" for k in range(1, 11)]
    seen = {cid: (c.seen_by_research, c.seen_by_planner) for cid, c in texts.CRITERIA.items()}
    assert seen["C04"] == ("sí", "sí") and seen["C01"] == ("no", "sí") and seen["C03"] == ("no", "en parte") and seen["C07"] == ("sí", "sí")
    assert all(c.name_es and c.threshold_es for c in texts.CRITERIA.values())
    assert texts.threshold_of("C02", max_abs_bias=0.1) == "|sesgo de la recuperación| ≤ 0,10 en la máscara de cola de la prueba"
