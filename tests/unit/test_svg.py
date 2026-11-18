"""The two charts this project adds to the dashboard's SVG helpers (U13): the cells with their intervals and tiers, and the sealed lift against the one of the test week."""

from __future__ import annotations

from promolift.dashboard import svg


def test_the_interval_chart_draws_one_whisker_and_one_dot_per_cell_in_the_color_of_its_tier_and_escapes_the_labels():
    chart = svg.interval_chart([("g1-b0", 0.5, 0.9, 1.4, 1), ("g2-<b>", 0.6, 0.8, 1.0, 1), ("g3-b3", 0.1, 0.2, 0.3, 2), ("sin grupo", 0.0, 0.1, 0.2, None)], 400, 120, "Celdas <ordenadas>")
    assert chart.count("<circle") == 4 and chart.count("stroke-width=\"2\"") == 4 and "var(--series-1)" in chart and "var(--series-2)" in chart and "var(--muted)" in chart
    assert "&lt;b&gt;" in chart and "<b>" not in chart and "Celdas &lt;ordenadas&gt;" in chart and "grupo 1" in chart and "grupo 2" in chart
    assert chart.startswith("<svg") and "<script" not in chart


def test_an_empty_chart_says_there_is_no_data_and_a_value_that_is_not_a_number_is_not_drawn():
    for chart in (svg.interval_chart([], 300, 100, "T"), svg.scatter_chart([], 300, 100, "T"), svg.interval_chart([("a", float("nan"), 0.1, 0.2, 1)], 300, 100, "T")):
        assert "Sin datos" in chart and "<circle" not in chart
    assert svg.scatter_chart([("a", 0.1, 0.2), ("b", float("nan"), 0.3)], 300, 100, "T").count("<circle") == 1


def test_the_scatter_draws_the_diagonal_and_each_point_with_its_values():
    chart = svg.scatter_chart([("g1-b1", 0.2, 0.25), ("g2-b2", 0.5, 0.4)], 400, 200, "Réplica", x_label="sellado", y_label="prueba")
    assert chart.count("<circle") == 2 and "stroke-dasharray" in chart and "g1-b1: sellado 20 %, prueba 25 %" in chart and "sellado" in chart
