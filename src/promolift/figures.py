"""The figures of the documentation, drawn only from the verified files of the site (RF24; plan, sections 21 and 25).

``write_figures`` reads the five JSON files through ``site_export.read_site``, which refuses a folder that is not one export (``SiteSetError``): nothing is drawn from a warehouse, a Parquet
file or a number typed here, so a figure in the README can only say what the site says. ``figure_data`` returns, for each figure, the numbers it plots; the drawing functions take
nothing else. Every figure says what it shows in Spanish, names the blocks a validation figure was fitted with and, while the test week is not sealed, is drawn from the validation and
says so. Each PNG is written atomically.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from promolift.files import write_atomic  # noqa: E402
from promolift.site_export import SiteFiles, read_site  # noqa: E402

logger = logging.getLogger(__name__)

FIGURES = ("hour_profile", "first_stockout", "example_day", "recovery_check", "naive_vs_adjusted", "band_lift", "cell_ranking", "replication", "forecast_wape")
DPI = 110
COLORS = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948")


def _none(values: list) -> list[float]:
    return [float("nan") if v is None else float(v) for v in values]


def figure_data(site: SiteFiles) -> dict[str, dict[str, Any]]:
    """The numbers each figure plots, taken from the verified files and from nothing else."""
    data, algorithms, operation = site.data, site.algorithms, site.operation
    recovery = [r for r in algorithms["recovery"] if r["scope"] in ("valid_v2", "test")]
    test_recovery = [r for r in recovery if r["scope"] == "test"]
    shown_recovery = test_recovery or [r for r in recovery if r["scope"] == "valid_v2"]
    ranked = sorted((c for c in algorithms["cells"] if c["ranked"]), key=lambda c: c["rank"])
    sealed_forecast = any(m["wape"] is not None for m in operation["forecast"])
    return {
        "hour_profile": {"hour": data["hour_profile"]["hour"], "mean_sales": _none(data["hour_profile"]["mean_sales"]), "stockout_rate": _none(data["hour_profile"]["stockout_rate"])},
        "first_stockout": {"hour": data["first_stockout"]["hour"], "share": _none(data["first_stockout"]["share"])},
        "example_day": {key: algorithms["example_day"][key] for key in ("hour", "observed", "recovered", "in_stock")},
        "recovery_check": {"scope": "test" if test_recovery else "valid_v2", "methods": [r["label_es"] for r in shown_recovery], "wape_series": _none([r["wape_series"] for r in shown_recovery]),
                           "fit_blocks": sorted({r["fit_blocks"] for r in shown_recovery}), "chosen": [r["chosen"] for r in shown_recovery]},
        "naive_vs_adjusted": {name: algorithms["naive_vs_adjusted"][name] for name in ("naive_pooled", "raw", "recovered", "any_flag0_control")},
        "band_lift": {"label": [b["label_es"] for b in algorithms["bands"]], "raw": _none([b["raw"] for b in algorithms["bands"]]), "recovered": _none([b["recovered"] for b in algorithms["bands"]]),
                      "unflagged": _none([b["unflagged"] for b in algorithms["bands"]])},
        "cell_ranking": {"cell": [c["cell"] for c in ranked], "recovered": [c["recovered"] for c in ranked], "ci_low": [c["ci_low"] for c in ranked], "ci_high": [c["ci_high"] for c in ranked],
                         "tier": [c["tier"] for c in ranked]},
        "replication": {"cell": [r["cell"] for r in operation["replication"]], "launch": _none([r["launch"] for r in operation["replication"]]), "test": _none([r["test"] for r in operation["replication"]]),
                        "consistent": [r["consistent"] for r in operation["replication"]]},
        "forecast_wape": {"scope": "test" if sealed_forecast else "valid", "method": [m["label_es"] for m in operation["forecast"]],
                          "wape": _none([m["wape"] if sealed_forecast else m["valid_wape"] for m in operation["forecast"]]),
                          "fit_blocks": sorted({m["valid_fit_blocks"] for m in operation["forecast"] if m["valid_fit_blocks"]})}}


def _png(fig: plt.Figure) -> bytes:
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=DPI, bbox_inches="tight", metadata={"Software": None})
    plt.close(fig)
    return buffer.getvalue()


def _empty(ax: plt.Axes, text: str) -> None:
    ax.text(0.5, 0.5, text, ha="center", va="center", transform=ax.transAxes)
    ax.set_xticks([])
    ax.set_yticks([])


def _hour_profile(d: dict) -> bytes:
    fig, (top, bottom) = plt.subplots(2, 1, figsize=(7, 5), sharex=True)
    top.bar(d["hour"], d["mean_sales"], color=COLORS[0])
    top.set_ylabel("Venta media por serie-día\n(venta normalizada)")
    bottom.plot(d["hour"], [v * 100 for v in d["stockout_rate"]], color=COLORS[1], marker="o", ms=3)
    bottom.set_ylabel("Series-días sin stock (%)")
    bottom.set_xlabel("Hora del día (06 a 21 es lo que analiza el proyecto)")
    bottom.axvspan(5.5, 21.5, color=COLORS[0], alpha=0.08)
    top.set_title("La venta y los quiebres, hora por hora, en el período del lanzamiento")
    return _png(fig)


def _first_stockout(d: dict) -> bytes:
    fig, ax = plt.subplots(figsize=(7, 3.6))
    ax.bar(d["hour"], [v * 100 for v in d["share"]], color=COLORS[1])
    ax.set_xlabel("Primera hora sin stock del día")
    ax.set_ylabel("Series-días con quiebre (%)")
    ax.set_title("Los quiebres llegan a la tarde y duran hasta el cierre")
    return _png(fig)


def _example_day(d: dict) -> bytes:
    fig, ax = plt.subplots(figsize=(7, 3.8))
    ax.plot(d["hour"], d["observed"], color=COLORS[0], marker="o", ms=3, label="Venta observada")
    ax.plot(d["hour"], d["recovered"], color=COLORS[1], ls="--", label="Demanda recuperada")
    for hour, stock in zip(d["hour"], d["in_stock"], strict=True):
        if not stock:
            ax.axvspan(hour - 0.5, hour + 0.5, color="grey", alpha=0.15)
    ax.set_xlabel("Hora (en gris, sin stock)")
    ax.set_ylabel("Venta normalizada")
    ax.set_title("Una serie-día que se quedó sin stock: lo observado cae a cero, lo recuperado no")
    ax.legend()
    return _png(fig)


def _recovery_check(d: dict) -> bytes:
    fig, ax = plt.subplots(figsize=(7, 3.8))
    if not d["methods"]:
        _empty(ax, "Sin comprobación de la recuperación")
    else:
        ax.barh(d["methods"], [v * 100 for v in d["wape_series"]], color=[COLORS[1] if c else COLORS[0] for c in d["chosen"]])
        ax.set_xlabel("WAPE de la masa oculta por serie (%)")
        where = "la prueba" if d["scope"] == "test" else "la validación V2, no la prueba"
        ax.set_title(f"La recuperación sobre horas ocultas a propósito: {where}\nMétodos ajustados con {', '.join(d['fit_blocks'])}", fontsize=10)
    return _png(fig)


def _naive_vs_adjusted(d: dict) -> bytes:
    fig, ax = plt.subplots(figsize=(7, 3.8))
    names = {"naive_pooled": "Cuenta ingenua", "raw": "Contrafactual, venta cruda", "recovered": "Contrafactual, demanda recuperada", "any_flag0_control": "Control con cualquier día sin marca"}
    rows = [(names[k], v) for k, v in d.items() if v["value"] is not None]
    if not rows:
        _empty(ax, "Sin aumentos")
    else:
        for i, (label, v) in enumerate(rows):
            ax.barh(label, v["value"] * 100, color=COLORS[i % len(COLORS)])
            if v["ci_low"] is not None:
                ax.plot([v["ci_low"] * 100, v["ci_high"] * 100], [i, i], color="black", lw=1.5)
        ax.set_xlabel("Aumento (%)")
        ax.set_title("La cuenta ingenua mezcla productos; el contrafactual compara la misma serie y la misma hora")
    return _png(fig)


def _band_lift(d: dict) -> bytes:
    fig, ax = plt.subplots(figsize=(7.5, 4))
    x = range(len(d["label"]))
    ax.bar([i - 0.27 for i in x], [v * 100 for v in d["raw"]], width=0.27, color=COLORS[0], label="Venta cruda")
    ax.bar(list(x), [v * 100 for v in d["recovered"]], width=0.27, color=COLORS[1], label="Demanda recuperada")
    ax.bar([i + 0.27 for i in x], [v * 100 for v in d["unflagged"]], width=0.27, color=COLORS[2], label="Rebaja sin marca")
    ax.set_xticks(list(x), d["label"], rotation=20)
    ax.set_ylabel("Aumento (%)")
    ax.set_xlabel("Profundidad de la rebaja")
    ax.set_title("Más descuento, más aumento")
    ax.legend()
    return _png(fig)


def _cell_ranking(d: dict) -> bytes:
    fig, ax = plt.subplots(figsize=(7, max(3.0, 0.2 * len(d["cell"]) + 1.2)))
    if not d["cell"]:
        _empty(ax, "Sin celdas ordenadas")
    else:
        for i, (cell, lift, low, high, tier) in enumerate(zip(d["cell"], d["recovered"], d["ci_low"], d["ci_high"], d["tier"], strict=True)):
            color = COLORS[(tier - 1) % len(COLORS)]
            ax.plot([low * 100, high * 100], [i, i], color=color, lw=2)
            ax.plot([lift * 100], [i], "o", color=color)
        ax.set_yticks(range(len(d["cell"])), d["cell"], fontsize=7)
        ax.invert_yaxis()
        ax.set_xlabel("Aumento con la demanda recuperada (%)")
        ax.set_title("Las celdas del mismo color no se distinguen entre sí (sus intervalos se pisan)", fontsize=10)
    return _png(fig)


def _replication(d: dict) -> bytes:
    fig, ax = plt.subplots(figsize=(5.5, 5))
    pairs = [(a, b) for a, b in zip(d["launch"], d["test"], strict=True) if a == a and b == b]
    if not pairs:
        _empty(ax, "La semana de prueba se evalúa con el cierre")
    else:
        ax.scatter([a * 100 for a, _ in pairs], [b * 100 for _, b in pairs], color=COLORS[0], alpha=0.8)
        top = max(max(a, b) for a, b in pairs) * 100 * 1.05
        ax.plot([0, top], [0, top], ls="--", color="grey")
        ax.set_xlabel("Aumento sellado, lanzamiento (%)")
        ax.set_ylabel("Aumento de la semana de prueba (%)")
        ax.set_title("El orden de las celdas se repite; el nivel, menos", fontsize=10)
    return _png(fig)


def _forecast_wape(d: dict) -> bytes:
    fig, ax = plt.subplots(figsize=(7, 3.6))
    if all(v != v for v in d["wape"]):
        _empty(ax, "Sin pronósticos")
    else:
        ax.barh(d["method"], [v * 100 for v in d["wape"]], color=COLORS[0])
        ax.invert_yaxis()
        ax.set_xlabel("WAPE de la masa con stock (%)")
        where = "la semana de prueba" if d["scope"] == "test" else f"la validación, no la prueba (ajustado con {', '.join(d['fit_blocks'])})"
        ax.set_title(f"El aumento de la celda frente a la regla ingenua: {where}", fontsize=10)
    return _png(fig)


_DRAW = {"hour_profile": _hour_profile, "first_stockout": _first_stockout, "example_day": _example_day, "recovery_check": _recovery_check, "naive_vs_adjusted": _naive_vs_adjusted,
         "band_lift": _band_lift, "cell_ranking": _cell_ranking, "replication": _replication, "forecast_wape": _forecast_wape}


def write_figures(site_dir: Path, out_dir: Path) -> list[Path]:
    """Draw the nine figures from the verified files of `site_dir` into `out_dir` (``<name>.png``, each atomic) and return their paths. A folder that is not one export is a
    ``SiteSetError`` and nothing is drawn or written."""
    data = figure_data(read_site(site_dir))
    pictures = {name: _DRAW[name](data[name]) for name in FIGURES}
    paths = [write_atomic(Path(out_dir) / f"{name}.png", pictures[name]) for name in FIGURES]
    logger.info("figures: %d drawn from %s into %s", len(paths), Path(site_dir).name, Path(out_dir).name)
    return paths
