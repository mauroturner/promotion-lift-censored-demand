"""Small SVG charts for the dashboard design: previews with real numbers, no scripts and no external files (adapted from project 05's ``dashboard/svg.py``; ``interval_chart``
and ``scatter_chart`` are this project's: the cells with their intervals and tiers, and the sealed lift against the one of the test week).

Every function returns one inline ``<svg>`` string with no namespace declaration, which an HTML page does not need and which would be the only address in the document (``standalone`` adds it
for a file of its own). Colors are CSS custom properties (``--series-1`` ... and the text and grid tokens) declared by the page, so light and dark mode swap in one
place. A chart has a ``role="img"`` and an ``aria-label``; hovering a point or a bar shows its value (native ``<title>``). Lines are 2 px, bars are thin with a rounded end, the grid is
recessive and a legend is drawn from two entries on; a series that is missing a value breaks its line instead of drawing a false one. A line chart can carry a shaded band (the range of
the estimate) and markers (the analyses, the ones that bring nothing new drawn in grey and named). Every text goes through ``html.escape``.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from html import escape

SERIES_COLORS = tuple(f"var(--series-{i})" for i in range(1, 9))
MUTED = "var(--muted)"
MARGIN_LEFT, MARGIN_RIGHT, MARGIN_TOP, MARGIN_BOTTOM = 52, 12, 10, 26
LEGEND_HEIGHT = 18
HIT_LIMIT = 80          # a line with more points than this has no hover targets
_ROOT = '<svg viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img" aria-label="{title}">'


def standalone(chart: str) -> str:
    """The chart as a file of its own (an ``.svg``): the same string with the SVG namespace on its root."""
    return chart.replace("<svg ", '<svg xmlns="http://www.w3.org/2000/svg" ', 1)


def format_number(value: float | None, digits: int = 1) -> str:
    """A number in Spanish: ``1,2 M``, ``25 mil``, ``12,5``; a number with more than two digits or a whole one has no decimals; a missing one is a dash."""
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return "—"
    magnitude = abs(value)
    for limit, divisor, suffix in ((1e9, 1e9, " mil M"), (1e6, 1e6, " M"), (1e4, 1e3, " mil")):
        if magnitude >= limit:
            text = f"{value / divisor:.{digits}f}".rstrip("0").rstrip(".")
            return text.replace(".", ",") + suffix
    if magnitude >= 100 or float(value).is_integer():
        return f"{value:,.0f}".replace(",", ".")
    return f"{value:.{digits}f}".rstrip("0").rstrip(".").replace(".", ",")


def nice_ticks(low: float, high: float, count: int = 4) -> list[float]:
    """About `count` round tick values covering ``[low, high]`` (at least two)."""
    if not math.isfinite(low) or not math.isfinite(high):
        return [0.0, 1.0]
    if high <= low:
        high = low + (abs(low) or 1.0)
    raw = (high - low) / max(count, 1)
    power = 10 ** math.floor(math.log10(raw))
    step = next(m * power for m in (1, 2, 2.5, 5, 10) if m * power >= raw)
    ticks, value = [], math.floor(low / step) * step
    while value <= high + step * 0.999:
        ticks.append(round(value, 10))
        value += step
        if len(ticks) > 12:
            break
    return ticks


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _empty(width: int, height: int, title: str) -> str:
    return (_ROOT.format(w=width, h=height, title=f"{escape(title)}: sin datos") + f'<text x="{width / 2:.0f}" y="{height / 2:.0f}" text-anchor="middle" class="svg-note">Sin datos</text></svg>')


def _legend(entries: Sequence[tuple[str, str, str]], width: int, dashed: Sequence[str] = ()) -> str:
    """A row of swatches and names, (name, color, kind) with kind ``line``, ``band`` or ``dot``; identity never rests on color alone, and the row stops where the frame ends."""
    parts, x = [], MARGIN_LEFT
    for name, color, kind in entries:
        if kind == "dot":
            parts.append(f'<circle cx="{x + 8}" cy="9" r="3.5" fill="{color}"/>')
        elif kind == "band":
            parts.append(f'<rect x="{x}" y="4" width="16" height="10" fill="{color}" fill-opacity="0.2"/>')
        else:
            dash = ' stroke-dasharray="4 3"' if name in dashed else ""
            parts.append(f'<line x1="{x}" y1="9" x2="{x + 16}" y2="9" stroke="{color}" stroke-width="2"{dash}/>')
        parts.append(f'<text x="{x + 20}" y="13" class="svg-legend">{escape(name)}</text>')
        x += 28 + 6.2 * len(name)
        if x > width - 40:
            break
    return "".join(parts)


def _axes(x0: float, x1: float, y1: float, ticks: list[float], scale) -> str:
    out = []
    for tick in ticks:
        y = scale(tick)
        out.append(f'<line x1="{x0}" y1="{y:.1f}" x2="{x1}" y2="{y:.1f}" class="svg-grid"/>')
        out.append(f'<text x="{x0 - 6}" y="{y + 4:.1f}" text-anchor="end" class="svg-tick">{escape(format_number(tick))}</text>')
    out.append(f'<line x1="{x0}" y1="{y1}" x2="{x1}" y2="{y1}" class="svg-axis"/>')
    return "".join(out)


def line_chart(
    series: dict[str, list[tuple[float, float]]],
    width: int,
    height: int,
    title: str,
    *,
    dashed: Sequence[str] = (),
    x_ticks: Sequence[tuple[float, str]] = (),
    unit: str = "",
    band: tuple[str, list[tuple[float, float, float]]] | None = None,
    markers: dict[str, list[tuple[float, float]]] | None = None,
    muted: Sequence[str] = (),
) -> str:
    """Lines of ``(x, y)`` points; `band` is a shaded area ``(name, [(x, low, high)])``, `markers` are named dots (those named in `muted` in grey) and `x_ticks` the labels of the x axis."""
    markers = markers or {}
    band_points = [(x, lo, hi) for x, lo, hi in (band[1] if band else []) if _finite(x) and _finite(lo) and _finite(hi)]
    dots = {name: [(x, y) for x, y in points if _finite(x) and _finite(y)] for name, points in markers.items()}
    points = ([(x, y) for pts in series.values() for x, y in pts if _finite(x) and _finite(y)] + [(x, v) for x, lo, hi in band_points for v in (lo, hi)]
              + [p for pts in dots.values() for p in pts])
    if not points:
        return _empty(width, height, title)
    names = list(series)
    colors = [SERIES_COLORS[i % len(SERIES_COLORS)] for i in range(len(names))]
    entries = [(n, c, "line") for n, c in zip(names, colors, strict=True)]
    if band_points and band:
        entries.append((band[0], SERIES_COLORS[0], "band"))
    for i, name in enumerate(n for n, pts in dots.items() if pts):
        entries.append((name, MUTED if name in muted else SERIES_COLORS[(len(names) + i) % len(SERIES_COLORS)], "dot"))
    top = MARGIN_TOP + (LEGEND_HEIGHT if len(entries) >= 2 else 0)
    x0, x1, y0, y1 = MARGIN_LEFT, width - MARGIN_RIGHT, top, height - MARGIN_BOTTOM
    x_lo, x_hi = min(p[0] for p in points), max(p[0] for p in points)
    ys = [p[1] for p in points]
    ticks = nice_ticks(0.0 if min(ys) >= 0 else min(ys), max(ys))
    y_lo, y_hi = ticks[0], ticks[-1]

    def sx(x: float) -> float:
        return x0 + (x - x_lo) / ((x_hi - x_lo) or 1.0) * (x1 - x0)

    def sy(y: float) -> float:
        return y1 - (y - y_lo) / ((y_hi - y_lo) or 1.0) * (y1 - y0)

    out = [_ROOT.format(w=width, h=height, title=escape(title)), f"<title>{escape(title)}</title>"]
    if len(entries) >= 2:
        out.append(_legend(entries, width, dashed))
    out.append(_axes(x0, x1, y1, ticks, sy))
    for x, label in x_ticks:
        anchor = "end" if sx(x) > x1 - 28 else "middle"          # the last label must not run out of the frame
        out.append(f'<text x="{sx(x):.1f}" y="{height - 8}" text-anchor="{anchor}" class="svg-tick">{escape(label)}</text>')
    if band_points and band:
        upper = [f"{sx(x):.1f},{sy(hi):.1f}" for x, _lo, hi in band_points]
        lower = [f"{sx(x):.1f},{sy(lo):.1f}" for x, lo, _hi in reversed(band_points)]
        out.append(f'<polygon points="{" ".join(upper + lower)}" fill="{SERIES_COLORS[0]}" fill-opacity="0.18"><title>{escape(band[0])}</title></polygon>')
    for name, color in zip(names, colors, strict=True):
        dash = ' stroke-dasharray="5 4"' if name in dashed else ""
        segments: list[list[tuple[float, float]]] = []
        segment: list[tuple[float, float]] = []
        for x, y in series[name]:
            if _finite(x) and _finite(y):
                segment.append((x, y))
            elif segment:
                segments.append(segment)
                segment = []
        if segment:
            segments.append(segment)
        for seg in segments:
            if len(seg) == 1:
                out.append(f'<circle cx="{sx(seg[0][0]):.1f}" cy="{sy(seg[0][1]):.1f}" r="3" fill="{color}"/>')
            else:
                path = " ".join(f"{sx(x):.1f},{sy(y):.1f}" for x, y in seg)
                out.append(f'<polyline points="{path}" fill="none" stroke="{color}" stroke-width="2" stroke-linejoin="round"{dash}/>')
        if len(series[name]) <= HIT_LIMIT:          # a wide hit target with the value, for the hover
            for x, y in series[name]:
                if _finite(x) and _finite(y):
                    out.append(f'<circle cx="{sx(x):.1f}" cy="{sy(y):.1f}" r="5" class="svg-hit"><title>{escape(name)}: {escape(format_number(y))} {escape(unit)}</title></circle>')
    for name, color in ((n, c) for n, c, kind in entries if kind == "dot"):
        for x, y in dots[name]:
            out.append(f'<circle cx="{sx(x):.1f}" cy="{sy(y):.1f}" r="3.5" fill="{color}"><title>{escape(name)}: {escape(format_number(y, 2))} {escape(unit)}</title></circle>')
    out.append("</svg>")
    return "".join(out)


def sparkline(points: Sequence[tuple[float, float]], width: int, height: int, title: str) -> str:
    """A line with no axes for a small multiple: the polyline, its last point and the title as a tooltip (a missing value breaks the line)."""
    finite = [(x, y) for x, y in points if _finite(x) and _finite(y)]
    if not finite:
        return _empty(width, height, title)
    x_lo, x_hi = min(p[0] for p in finite), max(p[0] for p in finite)
    y_lo, y_hi = min(p[1] for p in finite), max(p[1] for p in finite)

    def sx(x: float) -> float:
        return 3 + (x - x_lo) / ((x_hi - x_lo) or 1.0) * (width - 6)

    def sy(y: float) -> float:
        return (height - 4) - (y - y_lo) / ((y_hi - y_lo) or 1.0) * (height - 8)

    segments, segment = [], []
    for x, y in points:
        if _finite(x) and _finite(y):
            segment.append((x, y))
        elif segment:
            segments.append(segment)
            segment = []
    if segment:
        segments.append(segment)
    out = [_ROOT.format(w=width, h=height, title=escape(title)), f"<title>{escape(title)}</title>"]
    for seg in segments:
        if len(seg) > 1:
            out.append(f'<polyline points="{" ".join(f"{sx(x):.1f},{sy(y):.1f}" for x, y in seg)}" fill="none" stroke="var(--series-1)" stroke-width="1.5" stroke-linejoin="round"/>')
    x, y = finite[-1]
    out.append(f'<circle cx="{sx(x):.1f}" cy="{sy(y):.1f}" r="2.5" fill="var(--series-2)"/></svg>')
    return "".join(out)


def bar_chart(values: list[tuple[str, float]], width: int, height: int, title: str, *, unit: str = "") -> str:
    """Horizontal bars, one per ``(label, value)``, with the label at the left and the value at the end of the bar."""
    values = [(label, value) for label, value in values if _finite(value)]
    if not values:
        return _empty(width, height, title)
    label_width = min(max(len(label) for label, _ in values) * 6.2 + 8, width * 0.45)
    x0, x1 = label_width, width - 56
    top, bottom = 4, height - 4
    slot = (bottom - top) / len(values)
    bar = min(14.0, slot * 0.6)
    peak = max(max(v for _, v in values), 0.0) or 1.0
    out = [_ROOT.format(w=width, h=height, title=escape(title)), f"<title>{escape(title)}</title>", f'<line x1="{x0}" y1="{top}" x2="{x0}" y2="{bottom}" class="svg-axis"/>']
    for i, (label, value) in enumerate(values):
        y = top + i * slot + (slot - bar) / 2
        length = max(value, 0.0) / peak * (x1 - x0)
        shown = escape(label if len(label) * 6.2 <= label_width - 8 else label[: int((label_width - 8) / 6.2) - 1] + "…")
        out.append(f'<text x="{x0 - 6}" y="{y + bar / 2 + 4:.1f}" text-anchor="end" class="svg-tick">{shown}</text>')
        out.append(f'<path d="M{x0},{y:.1f} h{max(length - 4, 0):.1f} a4,4 0 0 1 4,4 v{max(bar - 8, 0):.1f} a4,4 0 0 1 -4,4 h-{max(length - 4, 0):.1f} z" '
                   f'fill="var(--series-1)"><title>{escape(label)}: {escape(format_number(value))} {escape(unit)}</title></path>')
        out.append(f'<text x="{x0 + length + 5:.1f}" y="{y + bar / 2 + 4:.1f}" class="svg-value">{escape(format_number(value))}</text>')
    out.append("</svg>")
    return "".join(out)


def grouped_bar_chart(groups: list[tuple[str, dict[str, float]]], width: int, height: int, title: str) -> str:
    """Vertical bars: one cluster per group label, one bar per series name (legend always present)."""
    names = list(dict.fromkeys(name for _, values in groups for name in values))
    if not groups or not names or not any(_finite(v) for _, vals in groups for v in vals.values()):
        return _empty(width, height, title)
    colors = [SERIES_COLORS[i % len(SERIES_COLORS)] for i in range(len(names))]
    x0, x1, y0, y1 = MARGIN_LEFT, width - MARGIN_RIGHT, MARGIN_TOP + LEGEND_HEIGHT, height - MARGIN_BOTTOM
    peak = max(v for _, vals in groups for v in vals.values() if _finite(v))
    ticks = nice_ticks(0.0, peak if peak > 0 else 1.0)
    y_hi = ticks[-1]

    def sy(y: float) -> float:
        return y1 - y / (y_hi or 1.0) * (y1 - y0)

    out = [_ROOT.format(w=width, h=height, title=escape(title)), f"<title>{escape(title)}</title>", _legend([(n, c, "line") for n, c in zip(names, colors, strict=True)], width),
           _axes(x0, x1, y1, ticks, sy)]
    slot = (x1 - x0) / len(groups)
    bar = min(18.0, slot * 0.8 / len(names))
    for i, (label, values) in enumerate(groups):
        left = x0 + i * slot + (slot - bar * len(names)) / 2
        out.append(f'<text x="{x0 + i * slot + slot / 2:.1f}" y="{height - 8}" text-anchor="middle" class="svg-tick">{escape(label)}</text>')
        for j, name in enumerate(names):
            value = values.get(name)
            if not _finite(value):
                continue
            h = max(value, 0.0) / (y_hi or 1.0) * (y1 - y0)
            out.append(f'<rect x="{left + j * bar + 1:.1f}" y="{y1 - h:.1f}" width="{max(bar - 2, 1):.1f}" height="{h:.1f}" rx="2" fill="{colors[j]}">'
                       f"<title>{escape(name)}, {escape(label)}: {escape(format_number(value, 2))}</title></rect>")
    out.append("</svg>")
    return "".join(out)


def interval_chart(items: list[tuple[str, float, float, float, int | None]], width: int, height: int, title: str) -> str:
    """Horizontal intervals, one per ``(label, low, value, high, tier)``: a whisker from the low to the high limit and a dot at the value, in the color of the tier (cells of the
    same color do not differ from each other, because their intervals overlap); a cell with no tier is drawn in grey."""
    items = [(label, lo, v, hi, tier) for label, lo, v, hi, tier in items if _finite(lo) and _finite(v) and _finite(hi)]
    if not items:
        return _empty(width, height, title)
    label_width = min(max(len(label) for label, *_ in items) * 5.6 + 8, width * 0.4)
    x0, x1, top, bottom = label_width, width - 14, 4, height - 22
    low, high = min(0.0, min(lo for _, lo, *_ in items)), max(hi for _, _, _, hi, _ in items)
    ticks = nice_ticks(low, high if high > low else low + 1.0)
    span = (ticks[-1] - ticks[0]) or 1.0

    def sx(x: float) -> float:
        return x0 + (x - ticks[0]) / span * (x1 - x0)

    slot = (bottom - top) / len(items)
    out = [_ROOT.format(w=width, h=height, title=escape(title)), f"<title>{escape(title)}</title>"]
    for t in ticks:
        out.append(f'<line x1="{sx(t):.1f}" y1="{top}" x2="{sx(t):.1f}" y2="{bottom}" class="svg-grid"/><text x="{sx(t):.1f}" y="{height - 8}" text-anchor="middle" class="svg-tick">{escape(format_number(t * 100, 0))} %</text>')
    for i, (label, lo, v, hi, tier) in enumerate(items):
        y = top + i * slot + slot / 2
        color = MUTED if tier is None else SERIES_COLORS[(int(tier) - 1) % len(SERIES_COLORS)]
        shown = escape(label if len(label) * 5.6 <= label_width - 8 else label[: int((label_width - 8) / 5.6) - 1] + "…")
        out.append(f'<text x="{x0 - 6}" y="{y + 3:.1f}" text-anchor="end" class="svg-tick">{shown}</text>')
        out.append(f'<line x1="{sx(lo):.1f}" y1="{y:.1f}" x2="{sx(hi):.1f}" y2="{y:.1f}" stroke="{color}" stroke-width="2"/>')
        out.append(f'<circle cx="{sx(v):.1f}" cy="{y:.1f}" r="3" fill="{color}"><title>{escape(label)}: {escape(format_number(v * 100, 1))} % ({escape(format_number(lo * 100, 1))} a {escape(format_number(hi * 100, 1))} %)'
                   f'{"" if tier is None else f", grupo {int(tier)}"}</title></circle>')
    out.append("</svg>")
    return "".join(out)


def scatter_chart(points: list[tuple[str, float, float]], width: int, height: int, title: str, *, x_label: str = "", y_label: str = "") -> str:
    """Dots ``(label, x, y)`` with the diagonal ``y = x`` drawn dashed: a dot on the diagonal is a value that repeated."""
    points = [(label, x, y) for label, x, y in points if _finite(x) and _finite(y)]
    if not points:
        return _empty(width, height, title)
    x0, x1, y0, y1 = MARGIN_LEFT, width - MARGIN_RIGHT, MARGIN_TOP, height - MARGIN_BOTTOM
    low = min(0.0, min(min(x, y) for _, x, y in points))
    high = max(max(x, y) for _, x, y in points)
    ticks = nice_ticks(low, high if high > low else low + 1.0)
    lo, hi = ticks[0], ticks[-1]

    def sx(x: float) -> float:
        return x0 + (x - lo) / ((hi - lo) or 1.0) * (x1 - x0)

    def sy(y: float) -> float:
        return y1 - (y - lo) / ((hi - lo) or 1.0) * (y1 - y0)

    out = [_ROOT.format(w=width, h=height, title=escape(title)), f"<title>{escape(title)}</title>", _axes(x0, x1, y1, ticks, sy)]
    out.append(f'<line x1="{sx(lo):.1f}" y1="{sy(lo):.1f}" x2="{sx(hi):.1f}" y2="{sy(hi):.1f}" stroke="var(--muted)" stroke-dasharray="4 3"/>')
    for label, x, y in points:
        out.append(f'<circle cx="{sx(x):.1f}" cy="{sy(y):.1f}" r="3" fill="var(--series-1)" fill-opacity=".8"><title>{escape(label)}: {escape(x_label)} {escape(format_number(x * 100, 1))} %, '
                   f'{escape(y_label)} {escape(format_number(y * 100, 1))} %</title></circle>')
    if x_label:
        out.append(f'<text x="{(x0 + x1) / 2:.1f}" y="{height - 6}" text-anchor="middle" class="svg-note">{escape(x_label)}</text>')
    out.append("</svg>")
    return "".join(out)
