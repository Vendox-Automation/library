"""
Dashboard image generator: turn a list of metrics into a shareable PNG report.

Public API:
    - generate_dashboard_image: title + metrics -> in-memory PNG (BytesIO).
    - trim_sparkline_series: shorten long trend data so the chart stays readable.

Requires the optional ``pillow`` and ``matplotlib`` dependencies:
    pip install "vdx_auto_utils[dashboard]"

See documentations/dashboard_image_doc.md for the full guide and examples.
"""

from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")  # headless backend — safe in Docker/servers (no display)

import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator
from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------------------
# Layout & style constants (tuned for a 1080px-wide, mobile-friendly image)
# ---------------------------------------------------------------------------
WIDTH = 1080
BACKGROUND = "#F7F8FC"
TEXT = "#202638"
MUTED = "#6F7482"
CARD_RADIUS = 28
CARD_HEIGHT = 248
CARD_GAP = 28
HEADER_HEIGHT = 170
BOTTOM_PADDING = 32
SPARKLINE_WINDOW_HOURS = 6
CARD_SIDE_PADDING = 46
CARD_INNER_WIDTH = WIDTH - (CARD_SIDE_PADDING * 2)
LEFT_PANEL_WIDTH = int(CARD_INNER_WIDTH * 0.48)
CHART_WIDTH = CARD_INNER_WIDTH - LEFT_PANEL_WIDTH - 24
CHART_X = CARD_SIDE_PADDING + LEFT_PANEL_WIDTH + 24
TEXT_OFFSET_FROM_CARD = 112

# Card typography (readable in Docker without crowding the card)
FONT_METRIC_NAME = 36
FONT_PERCENT = 58
FONT_SUBTITLE = 24
FONT_VALUES = 27
FONT_CHART_TITLE = 19

# Colour themes per status. "above_average" = green, "below_average" = red,
# "neutral" = amber. Each theme styles the card background, border, accent
# text and the chart fill area.
THEMES = {
    "above_average": {
        "accent": "#139A55",
        "soft": "#EAF7EF",
        "border": "#9ED8B5",
        "fill": "#CFEFDB",
        "arrow": "↑",
    },
    "below_average": {
        "accent": "#CF1833",
        "soft": "#FDEDEE",
        "border": "#F3B5BE",
        "fill": "#F6D4D8",
        "arrow": "↓",
    },
    "neutral": {
        "accent": "#C07A13",
        "soft": "#FFF7E8",
        "border": "#EBC77D",
        "fill": "#F8E7B9",
        "arrow": "→",
    },
}


_FONT_CACHE: dict[tuple[int, bool], ImageFont.FreeTypeFont] = {}


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Load a scalable TrueType font (Docker/Linux safe via matplotlib's DejaVu bundle)."""
    cache_key = (size, bold)
    if cache_key in _FONT_CACHE:
        return _FONT_CACHE[cache_key]

    candidates: list[Path | str] = []

    try:
        font_prop = fm.FontProperties(
            family="DejaVu Sans",
            weight="bold" if bold else "normal",
        )
        candidates.append(fm.findfont(font_prop, fallback_to_default=False))
    except (ValueError, OSError):
        pass

    module_dir = Path(__file__).resolve().parent
    candidates.extend(
        [
            module_dir
            / "fonts"
            / ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"),
            (
                Path(r"C:\Windows\Fonts\arialbd.ttf")
                if bold
                else Path(r"C:\Windows\Fonts\arial.ttf")
            ),
            (
                Path(r"C:\Windows\Fonts\Arial Bold.ttf")
                if bold
                else Path(r"C:\Windows\Fonts\Arial.ttf")
            ),
            (
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
                if bold
                else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
            ),
            "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
            "arialbd.ttf" if bold else "arial.ttf",
        ]
    )

    for candidate in candidates:
        try:
            font = ImageFont.truetype(str(candidate), size)
            _FONT_CACHE[cache_key] = font
            return font
        except OSError:
            continue

    raise OSError(
        "No TrueType font found for dashboard rendering. "
        "Install fonts-dejavu-core or matplotlib."
    )


def _status_for(diff_pct: float) -> str:
    """Map a percentage difference to a theme key (positive=green, negative=red)."""
    if diff_pct > 0:
        return "above_average"
    if diff_pct < 0:
        return "below_average"
    return "neutral"


def _format_number(value: Any, unit: str = "") -> str:
    """Format a number for display (e.g. ``1,234`` or ``RM 1,234.56``)."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)

    if unit.upper() == "RM":
        return f"RM {number:,.2f}".rstrip("0").rstrip(".")

    if number.is_integer():
        return f"{int(number):,}"
    return f"{number:,.2f}".rstrip("0").rstrip(".")


def _resolve_trend_labels(
    metric: dict[str, Any], point_count: int, report_datetime: Any = None
) -> list[str]:
    """Build x-axis labels (``HH:00``) for the sparkline when none are supplied."""
    labels = metric.get("trend_labels")
    if labels and len(labels) >= point_count:
        return [str(label) for label in labels[:point_count]]

    end_hour = None
    if isinstance(report_datetime, datetime):
        end_hour = report_datetime.hour
    elif metric.get("report_datetime") and isinstance(
        metric["report_datetime"], datetime
    ):
        end_hour = metric["report_datetime"].hour

    if end_hour is not None and point_count > 0:
        start_hour = max(0, end_hour - point_count + 1)
        return [
            f"{hour:02d}:00" for hour in range(start_hour, start_hour + point_count)
        ]

    return [f"{idx + 1:02d}:00" for idx in range(point_count)]


def _format_y_tick(value: float) -> str:
    """Compact y-axis tick formatting (e.g. ``1.2k`` for 1200)."""
    if abs(value) >= 1000:
        return f"{value / 1000:.1f}k"
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.1f}"


def trim_sparkline_series(
    actual_trend: list[float],
    average_trend: list[float],
    trend_labels: list[str] | None = None,
    window: int = SPARKLINE_WINDOW_HOURS,
) -> tuple[list[float], list[float], list[str]]:
    """
    Keep only the most recent points of a trend so the chart stays readable.

    Trims the three parallel lists (actual values, average/benchmark values, and
    labels) to the last ``window`` points and keeps the label list aligned to
    ``actual_trend`` (padding with empty strings or truncating as needed).

    Args:
        actual_trend: Measured values, oldest first.
        average_trend: Benchmark/average values for the same points (may be empty).
        trend_labels: Optional per-point labels (e.g. ``["02:00", "03:00"]``).
        window: How many of the most recent points to keep. Defaults to 6.

    Returns:
        Tuple ``(actual_trend, average_trend, trend_labels)`` trimmed to at most
        ``window`` points each.
    """
    labels = list(trend_labels or [])
    if len(labels) < len(actual_trend):
        labels = labels + [""] * (len(actual_trend) - len(labels))
    elif len(labels) > len(actual_trend):
        labels = labels[: len(actual_trend)]

    if len(actual_trend) <= window:
        return actual_trend, average_trend, labels

    return actual_trend[-window:], average_trend[-window:], labels[-window:]


def _draw_direction_arrow(
    draw: ImageDraw.ImageDraw, x: int, y: int, status: str, color: str
) -> None:
    """Draw an up/down/flat arrow as vectors (avoids missing Unicode glyphs in Docker)."""
    cy = y + 24
    half = 11

    if status == "above_average":
        draw.polygon(
            [(x, cy - half), (x - half, cy + 6), (x + half, cy + 6)], fill=color
        )
        return

    if status == "below_average":
        draw.polygon(
            [(x, cy + half), (x - half, cy - 6), (x + half, cy - 6)], fill=color
        )
        return

    draw.line([(x - half, cy), (x + half, cy)], fill=color, width=4)
    draw.polygon(
        [(x + half, cy), (x + half - 8, cy - 5), (x + half - 8, cy + 5)], fill=color
    )


def _format_report_time(report_datetime: Any) -> str:
    """Format the header timestamp as ``YYYY-MM-DD HH:00``."""
    if isinstance(report_datetime, datetime):
        return report_datetime.strftime("%Y-%m-%d %H:00")
    if report_datetime:
        return str(report_datetime)
    return datetime.now().strftime("%Y-%m-%d %H:00")


def _resolve_icon_key(metric_name: str, topic_name: str) -> str:
    """Map a metric/topic label to a drawable icon style."""
    name = str(metric_name).strip().lower()
    topic = str(topic_name).strip().lower()

    metric_icons = {
        "approved": "approved",
        "disbursed": "disbursed",
        "closed": "closed",
        "in-progress": "in_progress",
        "pending": "pending",
        "count": "count",
        "amount": "amount",
        "row count": "count",
        "fpx amount": "amount",
        "repayment amount": "amount",
    }
    if name in metric_icons:
        return metric_icons[name]

    topic_icons = {
        "register": "register",
        "loan listing": "loan_listing",
        "kyc": "kyc",
        "fpx": "fpx",
        "repayment": "repayment",
    }
    return topic_icons.get(topic, "metric")


def _draw_metric_icon(
    draw: ImageDraw.ImageDraw, cx: int, cy: int, icon_key: str, color: str
) -> None:
    """Draw a simple vector icon centered at (cx, cy)."""
    draw.ellipse(
        (cx - 40, cy - 40, cx + 40, cy + 40), fill="#FFFFFF", outline=color, width=2
    )

    if icon_key == "loan_listing":
        # Clipboard
        draw.rounded_rectangle(
            (cx - 18, cy - 24, cx + 18, cy + 26), radius=6, outline=color, width=3
        )
        draw.rounded_rectangle((cx - 8, cy - 30, cx + 8, cy - 20), radius=4, fill=color)
        for offset in (-10, 0, 10):
            draw.line(
                [(cx - 10, cy + offset), (cx + 10, cy + offset)], fill=color, width=3
            )
        return

    if icon_key == "kyc":
        # Shield with user
        draw.polygon(
            [
                (cx, cy - 24),
                (cx + 22, cy - 10),
                (cx + 18, cy + 22),
                (cx, cy + 30),
                (cx - 18, cy + 22),
                (cx - 22, cy - 10),
            ],
            outline=color,
            width=3,
        )
        draw.ellipse((cx - 8, cy - 14, cx + 8, cy + 2), outline=color, width=3)
        draw.arc(
            (cx - 14, cy + 2, cx + 14, cy + 20), start=200, end=340, fill=color, width=3
        )
        return

    if icon_key == "fpx":
        # Lightning bolt
        draw.polygon(
            [
                (cx + 4, cy - 24),
                (cx - 10, cy + 2),
                (cx + 2, cy + 2),
                (cx - 6, cy + 24),
                (cx + 12, cy - 4),
                (cx, cy - 4),
            ],
            fill=color,
        )
        return

    if icon_key == "repayment":
        _draw_wallet_icon(draw, cx, cy, color)
        return

    if icon_key == "register":
        # User with plus
        draw.ellipse((cx - 10, cy - 22, cx + 10, cy - 2), outline=color, width=3)
        draw.arc(
            (cx - 18, cy - 2, cx + 18, cy + 24), start=200, end=340, fill=color, width=3
        )
        draw.line([(cx + 20, cy - 8), (cx + 20, cy + 8)], fill=color, width=3)
        draw.line([(cx + 14, cy - 1), (cx + 26, cy - 1)], fill=color, width=3)
        return

    if icon_key == "approved":
        # Document with check
        draw.rounded_rectangle(
            (cx - 16, cy - 22, cx + 16, cy + 24), radius=5, outline=color, width=3
        )
        draw.line([(cx - 8, cy - 10), (cx + 8, cy - 10)], fill=color, width=2)
        draw.line([(cx - 8, cy), (cx + 4, cy)], fill=color, width=2)
        draw.line(
            [(cx - 4, cy + 14), (cx + 2, cy + 20), (cx + 14, cy + 4)],
            fill=color,
            width=4,
            joint="curve",
        )
        return

    if icon_key == "disbursed":
        # Wallet with outgoing arrow
        _draw_wallet_icon(draw, cx, cy, color)
        draw.polygon(
            [(cx + 18, cy - 4), (cx + 30, cy - 4), (cx + 24, cy + 2)], fill=color
        )
        draw.polygon(
            [(cx + 18, cy + 4), (cx + 30, cy + 4), (cx + 24, cy - 2)], fill=color
        )
        return

    if icon_key == "closed":
        # Padlock
        draw.arc(
            (cx - 14, cy - 18, cx + 14, cy + 2), start=0, end=180, fill=color, width=3
        )
        draw.rounded_rectangle(
            (cx - 18, cy - 2, cx + 18, cy + 22), radius=6, outline=color, width=3
        )
        draw.ellipse((cx - 4, cy + 8, cx + 4, cy + 16), fill=color)
        return

    if icon_key == "in_progress":
        # Clock
        draw.ellipse((cx - 20, cy - 20, cx + 20, cy + 20), outline=color, width=3)
        draw.line([(cx, cy), (cx, cy - 12)], fill=color, width=3)
        draw.line([(cx, cy), (cx + 10, cy + 4)], fill=color, width=3)
        return

    if icon_key == "pending":
        # Hourglass
        draw.polygon(
            [(cx, cy - 22), (cx + 16, cy - 8), (cx - 16, cy - 8)],
            outline=color,
            width=3,
        )
        draw.polygon(
            [(cx, cy + 22), (cx + 16, cy + 8), (cx - 16, cy + 8)],
            outline=color,
            width=3,
        )
        draw.line([(cx - 10, cy - 8), (cx + 10, cy + 8)], fill=color, width=3)
        draw.line([(cx + 10, cy - 8), (cx - 10, cy + 8)], fill=color, width=3)
        return

    if icon_key == "count":
        for idx, height in enumerate([14, 24, 18]):
            x0 = cx - 14 + idx * 14
            draw.rounded_rectangle(
                (x0, cy + 12 - height, x0 + 8, cy + 12), radius=3, fill=color
            )
        return

    if icon_key == "amount":
        draw.ellipse((cx - 18, cy - 18, cx + 18, cy + 18), outline=color, width=3)
        draw.text((cx - 10, cy - 14), "RM", font=_font(18, bold=True), fill=color)
        return

    # Generic metric fallback
    draw.ellipse((cx - 6, cy - 6, cx + 6, cy + 6), fill=color)


def _draw_wallet_icon(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: str) -> None:
    """Draw a wallet shape (shared by the repayment/disbursed icons)."""
    draw.rounded_rectangle(
        (cx - 20, cy - 10, cx + 20, cy + 20), radius=8, outline=color, width=3
    )
    draw.pieslice((cx - 20, cy - 24, cx + 8, cy + 4), start=180, end=360, fill=color)
    draw.ellipse((cx + 8, cy + 2, cx + 16, cy + 10), fill=color)


def _draw_header(
    draw: ImageDraw.ImageDraw,
    platform_name: str,
    topic_name: str,
    report_datetime: Any,
) -> None:
    """Draw the top banner: brand mark, title, timestamp and subtitle."""
    title_font = _font(46, bold=True)
    time_font = _font(26)
    subtitle_font = _font(24)

    icon_x, icon_y = 46, 38
    draw.rounded_rectangle(
        (icon_x, icon_y, icon_x + 92, icon_y + 92), radius=24, fill="#EDF3FF"
    )
    bar_colors = ["#18A54A", "#D21838", "#2674D9"]
    bar_heights = [44, 66, 84]
    for idx, (color, height) in enumerate(zip(bar_colors, bar_heights)):
        x0 = icon_x + 26 + idx * 24
        y0 = icon_y + 76 - height
        draw.rounded_rectangle((x0, y0, x0 + 14, icon_y + 76), radius=5, fill=color)

    draw.text(
        (168, 36), f"{platform_name} Alert - {topic_name}", font=title_font, fill=TEXT
    )
    draw.text(
        (170, 92), _format_report_time(report_datetime), font=time_font, fill=MUTED
    )
    draw.text(
        (170, 126), "Hourly Performance vs Average", font=subtitle_font, fill=MUTED
    )


def _prepare_sparkline_display(
    actual: list[float],
    metric: dict[str, Any],
) -> tuple[list[float], list[float], float, float]:
    """
    Build chart series tuned for a clean visual look.

    Live cumulative benchmark curves often slope far above actual, which leaves a
    large empty band between the lines. For display we keep the real actual
    trend but draw a flat benchmark at the top of the chart area and zoom the
    y-axis to the actual series so the fill looks solid.
    """
    if not actual:
        actual = [float(metric.get("current", 0))]

    min_actual = min(actual)
    max_actual = max(actual)
    span = max_actual - min_actual
    if span <= 0:
        span = max(abs(max_actual), 1) * 0.2

    chart_floor = min_actual - span * 0.15
    chart_ceil = max_actual + span * 0.15
    # Flat target line at the top of the chart area (matches sample layout).
    benchmark = [chart_ceil] * len(actual)
    return actual, benchmark, chart_floor, chart_ceil


def _make_sparkline(
    metric: dict[str, Any], theme: dict[str, str], report_datetime: Any = None
) -> Image.Image:
    """Render the recent-trend mini line-chart with matplotlib and return it as a PIL image."""
    actual = list(metric.get("actual_trend") or [metric.get("current", 0)])
    average = list(
        metric.get("average_trend") or [metric.get("average", 0)] * len(actual)
    )
    labels = list(metric.get("trend_labels") or [])
    actual, _average, labels = trim_sparkline_series(actual, average, labels)

    plot_actual, plot_benchmark, chart_floor, chart_ceil = _prepare_sparkline_display(
        actual, metric
    )

    x_values = list(range(len(plot_actual)))
    if labels and len(labels) == len(plot_actual) and all(labels):
        x_labels = labels
    else:
        x_labels = _resolve_trend_labels(metric, len(plot_actual), report_datetime)

    fig, ax = plt.subplots(figsize=(4.6, 1.85), dpi=160)
    fig.patch.set_alpha(0)
    ax.set_facecolor("none")

    ax.plot(
        x_values, plot_benchmark, color="#9AA1AE", linewidth=2.0, linestyle=(0, (4, 5))
    )
    ax.plot(x_values, plot_actual, color=theme["accent"], linewidth=3.0)
    ax.fill_between(
        x_values,
        plot_actual,
        chart_floor,
        color=theme["fill"],
        alpha=0.92,
    )
    ax.scatter([x_values[-1]], [plot_actual[-1]], color=theme["accent"], s=28, zorder=5)

    ax.set_ylim(chart_floor, chart_ceil)
    ax.set_xlim(x_values[0], x_values[-1] if len(x_values) > 1 else 1)

    tick_values = plot_actual + plot_benchmark
    use_integer_ticks = all(float(value).is_integer() for value in tick_values)
    ax.yaxis.set_major_locator(MaxNLocator(nbins=4, integer=use_integer_ticks))
    ax.set_xticks(x_values)
    ax.set_xticklabels(x_labels, fontsize=8, color=MUTED)
    ax.tick_params(axis="y", labelsize=8, colors=MUTED, length=0, pad=2)
    ax.tick_params(axis="x", length=0, pad=2)
    ax.yaxis.set_major_formatter(
        plt.FuncFormatter(lambda value, _pos: _format_y_tick(value))
    )

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#D5DAE3")
    ax.spines["bottom"].set_color("#D5DAE3")
    ax.grid(axis="y", color="#E6E9EF", linewidth=0.8, alpha=0.7)

    output = BytesIO()
    fig.savefig(
        output, format="png", transparent=True, bbox_inches="tight", pad_inches=0.05
    )
    plt.close(fig)
    output.seek(0)
    return Image.open(output).convert("RGBA")


def _draw_values_block(
    draw: ImageDraw.ImageDraw,
    text_x: int,
    y: int,
    current_text: str,
    average_text: str,
    max_width: int,
) -> None:
    """Draw current/avg values; wrap to two lines when the single line is too wide."""
    values_font = _font(FONT_VALUES, bold=True)
    single_line = f"Current: {current_text}   |   Avg: {average_text}"
    line_bbox = draw.textbbox((0, 0), single_line, font=values_font)
    if line_bbox[2] - line_bbox[0] <= max_width:
        draw.text((text_x, y), single_line, font=values_font, fill=TEXT)
        return

    draw.text((text_x, y), f"Current: {current_text}", font=values_font, fill=TEXT)
    draw.text((text_x, y + 30), f"Avg: {average_text}", font=values_font, fill=TEXT)


def _draw_card(
    draw: ImageDraw.ImageDraw,
    image: Image.Image,
    metric: dict[str, Any],
    y: int,
    report_datetime: Any = None,
    topic_name: str = "",
) -> None:
    """Draw one metric card: background, icon, percentage, values and sparkline."""
    diff_pct = float(metric.get("difference_pct", 0))
    status = metric.get("status") or _status_for(diff_pct)
    theme = THEMES.get(status, THEMES["neutral"])

    left, right = CARD_SIDE_PADDING, WIDTH - CARD_SIDE_PADDING
    draw.rounded_rectangle(
        (left, y, right, y + CARD_HEIGHT),
        radius=CARD_RADIUS,
        fill=theme["soft"],
        outline=theme["border"],
        width=3,
    )

    icon_x = left + 58
    icon_y = y + (CARD_HEIGHT // 2)
    icon_key = metric.get("icon") or _resolve_icon_key(
        str(metric.get("name", "")), topic_name
    )
    _draw_metric_icon(draw, icon_x, icon_y, icon_key, theme["accent"])

    text_x = left + TEXT_OFFSET_FROM_CARD
    name_font = _font(FONT_METRIC_NAME, bold=True)
    percent_font = _font(FONT_PERCENT, bold=True)
    subtitle_font = _font(FONT_SUBTITLE)

    draw.text(
        (text_x, y + 32), str(metric.get("name", "Metric")), font=name_font, fill=TEXT
    )

    sign = "+" if diff_pct > 0 else ""
    percent_text = f"{sign}{diff_pct:.1f}%"
    percent_y = y + 78
    draw.text(
        (text_x, percent_y), percent_text, font=percent_font, fill=theme["accent"]
    )
    percent_bbox = draw.textbbox((text_x, percent_y), percent_text, font=percent_font)
    _draw_direction_arrow(
        draw, percent_bbox[2] + 12, percent_y, status, theme["accent"]
    )
    draw.text((text_x, y + 146), "vs hourly average", font=subtitle_font, fill=MUTED)

    current_text = _format_number(metric.get("current", 0), metric.get("unit", ""))
    average_text = _format_number(metric.get("average", 0), metric.get("unit", ""))
    _draw_values_block(
        draw,
        text_x,
        y + 182,
        current_text,
        average_text,
        max_width=CHART_X - text_x - 20,
    )

    chart_title_x = CHART_X + 8
    draw.text(
        (chart_title_x, y + 32),
        "Actual trend vs benchmark average",
        font=_font(FONT_CHART_TITLE),
        fill=MUTED,
    )
    chart = _make_sparkline(metric, theme, report_datetime)
    chart = chart.resize((CHART_WIDTH, 152), Image.Resampling.LANCZOS)
    image.alpha_composite(chart, (CHART_X, y + 60))


def generate_dashboard_image(
    topic_name: str,
    report_datetime: Any,
    metrics: list[dict],
    platform_name: str = "PayLaju",
) -> BytesIO:
    """
    Turn a title and a list of metrics into a ready-to-share PNG dashboard image.

    Draws a header followed by one coloured card per metric (name, percentage vs.
    average, current/avg values, and a recent-trend sparkline) and returns the
    finished image as an in-memory PNG.

    Each metric dict supports: required ``name``, ``current``, ``average``,
    ``difference_pct``; optional ``actual_trend``, ``average_trend``,
    ``trend_labels``, ``unit`` (e.g. ``"RM"``), ``status`` (force the colour
    theme), and ``icon`` (force the icon). See the documentation for full details.

    Args:
        topic_name: Report/topic name shown in the header. The header reads
            ``"{platform_name} Alert - {topic_name}"``.
        report_datetime: A ``datetime`` (preferred) or pre-formatted string shown
            under the title; also used to auto-generate chart hour labels.
        metrics: Non-empty list of metric dicts; one card is drawn per metric.
        platform_name: Brand/platform name shown in the header. Defaults to "PayLaju".

    Returns:
        BytesIO: An in-memory PNG image, rewound to the start and ready to send.

    Raises:
        ValueError: If ``metrics`` is empty.
        OSError: If no usable TrueType font can be found for rendering.
    """
    if not metrics:
        raise ValueError(
            "At least one metric is required to generate a dashboard image"
        )

    height = (
        HEADER_HEIGHT
        + (CARD_HEIGHT * len(metrics))
        + (CARD_GAP * (len(metrics) - 1))
        + BOTTOM_PADDING
    )
    image = Image.new("RGBA", (WIDTH, height), BACKGROUND)
    draw = ImageDraw.Draw(image)

    _draw_header(draw, platform_name, topic_name, report_datetime)

    y = HEADER_HEIGHT
    for metric in metrics:
        _draw_card(draw, image, metric, y, report_datetime, topic_name)
        y += CARD_HEIGHT + CARD_GAP

    output = BytesIO()
    image.convert("RGB").save(output, format="PNG", optimize=True)
    output.seek(0)
    return output
