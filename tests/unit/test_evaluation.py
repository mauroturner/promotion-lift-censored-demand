"""The criteria C01 to C10 from the figures of the test (U11; AC22; requirements, section 8.1): every threshold, its edge, a tie that never passes and a figure that is not
there, which is never a pass."""

from __future__ import annotations

import copy

import pytest

from promolift.evaluation import Criterion, criteria_of

DOC = {"c02_max_abs_bias": 0.10, "c03_max_abs_lift_bias": 0.05, "c05_min_spearman": 0.80, "c06_min_consistent_share": 0.80, "c07_min_spearman": 0.90}


def figures(**changes):
    """The figures of a test week that meets every criterion, with the given leaves replaced (``a__b=value`` replaces ``figures['a']['b']``)."""
    base = {
        "recovery": {"method": "r2@0.25", "wape": 0.30, "wape_r1": 0.37, "ci_low": -0.08, "ci_high": -0.05, "bias": 0.03, "bias_promo": 0.02, "bias_regular": 0.04,
                     "lift_bias": -0.0192, "series": 250, "masked_days": 900},
        "effect": {"raw": {"lift": 0.50, "ci_low": 0.46, "ci_high": 0.54}, "recovered": {"lift": 0.55, "ci_low": 0.51, "ci_high": 0.59},
                   "difference": {"value": 0.05, "ci_low": 0.02, "ci_high": 0.08}, "series_days": 4000},
        "replication": {"cells": 40, "spearman": 0.90, "share_consistent": 0.85, "spearman_depth": 0.95},
        "forecast": {"series_days": 3000, "methods": {m: {"wape": w, "bias": 0.0} for m, w in (("f0_no_lift", 0.48), ("f1_naive", 0.36), ("f2a_overall_lift", 0.45), ("f2_cell_lift", 0.43))},
                     "f2_minus_f2a": {"value": -0.02, "ci_low": -0.03, "ci_high": -0.01}, "f2_minus_f1": {"value": -0.03, "ci_low": -0.05, "ci_high": -0.01}},
    }
    out = copy.deepcopy(base)
    for path, value in changes.items():
        node = out
        *head, last = path.split("__")
        for part in head:
            node = node[part]
        node[last] = value
    return out


def by_id(figs):
    return {c.criterion_id: c for c in criteria_of(figs, DOC)}


def test_a_week_that_meets_everything_passes_c01_to_c09_and_c10_is_informative():
    criteria = by_id(figures())
    assert list(criteria) == [f"C{k:02d}" for k in range(1, 11)]
    assert [criteria[f"C{k:02d}"].passed for k in range(1, 10)] == [True] * 9 and criteria["C10"].passed is None
    assert isinstance(criteria["C01"], Criterion) and criteria["C01"].value == 0.30 and criteria["C01"].baseline_value == 0.37 and (criteria["C01"].ci_low, criteria["C01"].ci_high) == (-0.08, -0.05)
    assert criteria["C04"].value == 0.55 and criteria["C04"].baseline_value == 0.50 and criteria["C04"].ci_low == 0.02
    assert criteria["C08"].value == 0.43 and criteria["C08"].baseline_value == 0.45 and criteria["C09"].value == 0.43 and criteria["C09"].baseline_value == 0.36


@pytest.mark.parametrize(("changes", "failing"), [
    ({"recovery__ci_high": 0.0}, "C01"), ({"recovery__ci_high": 0.001}, "C01"),             # a tie, or an interval that touches 0, does not beat R1
    ({"recovery__bias": 0.1000001}, "C02"), ({"recovery__bias": -0.2}, "C02"),
    ({"recovery__lift_bias": 0.0500001}, "C03"), ({"recovery__lift_bias": -0.06}, "C03"),
    ({"effect__difference__ci_low": 0.0}, "C04"), ({"effect__difference__ci_low": -0.01}, "C04"),
    ({"replication__spearman": 0.7999}, "C05"), ({"replication__share_consistent": 0.79}, "C06"), ({"replication__spearman_depth": 0.8999}, "C07"),
    ({"forecast__f2_minus_f2a__ci_high": 0.0}, "C08"), ({"forecast__f2_minus_f1__ci_high": 0.0}, "C09"), ({"forecast__f2_minus_f1__ci_high": 0.02}, "C09")])
def test_each_threshold_and_its_edge(changes, failing):
    criteria = by_id(figures(**changes))
    assert criteria[failing].passed is False
    assert [cid for cid, c in criteria.items() if c.passed is False] == [failing]            # and no other criterion moves


@pytest.mark.parametrize(("changes", "passing"), [
    ({"recovery__bias": 0.10}, "C02"), ({"recovery__bias": -0.10}, "C02"), ({"recovery__lift_bias": 0.05}, "C03"), ({"replication__spearman": 0.80}, "C05"),
    ({"replication__share_consistent": 0.80}, "C06"), ({"replication__spearman_depth": 0.90}, "C07")])
def test_a_value_that_equals_its_limit_passes_where_the_criterion_says_at_most_or_at_least(changes, passing):
    assert by_id(figures(**changes))[passing].passed is True


@pytest.mark.parametrize(("changes", "cannot"), [
    ({"recovery": None}, ("C01", "C02", "C03")), ({"recovery__ci_low": None, "recovery__ci_high": None}, ("C01",)), ({"recovery__lift_bias": None}, ("C03",)),
    ({"effect": None}, ("C04",)), ({"replication__spearman": None}, ("C05",)), ({"replication__share_consistent": None}, ("C06",)), ({"replication__spearman_depth": None}, ("C07",)),
    ({"forecast": None}, ("C08", "C09")), ({"forecast__f2_minus_f2a": None}, ("C08",))])
def test_a_criterion_that_cannot_be_computed_is_not_passed_and_says_why(changes, cannot):
    criteria = by_id(figures(**changes))
    for cid in cannot:
        assert criteria[cid].passed is False and criteria[cid].value is None and criteria[cid].verdict_es.startswith("No se puede calcular")
    assert all(c.passed for cid, c in criteria.items() if cid not in cannot and c.passed is not None)


def test_the_criteria_carry_their_fixed_text_and_the_limits_of_the_configuration_in_their_threshold():
    criteria = by_id(figures())
    assert criteria["C02"].threshold_es.endswith("≤ 0,10 en la máscara de cola de la prueba") and "0,05" in criteria["C03"].threshold_es
    assert "0,80" in criteria["C05"].threshold_es and "0,90" in criteria["C07"].threshold_es
    assert criteria["C04"].seen_by_research == "sí" and criteria["C01"].seen_by_planner == "sí" and criteria["C10"].threshold_es.startswith("sin umbral")
    strict = {c.criterion_id: c for c in criteria_of(figures(), {**DOC, "c02_max_abs_bias": 0.01})}
    assert strict["C02"].passed is False and strict["C02"].threshold_es.endswith("≤ 0,01 en la máscara de cola de la prueba")
