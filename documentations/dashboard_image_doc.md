# Dashboard Image Documentation

## Table of Contents
- [How to Use in Your Project](#how-to-use-in-your-project)
  - [Quick Start Guide](#quick-start-guide)
- [Overview](#overview)
- [Installation](#installation)
- [The Metric Dictionary](#the-metric-dictionary)
- [Functions](#functions)
  - [generate_dashboard_image](#generate_dashboard_image)
  - [trim_sparkline_series](#trim_sparkline_series)
- [Colour & Status Rules](#colour--status-rules)
- [Icons](#icons)
- [Usage Example](#usage-example)
- [Sending the Image to Telegram](#sending-the-image-to-telegram)
- [Notes & Gotchas](#notes--gotchas)

## How to Use in Your Project

The `dashboard_image` module turns a few numbers into a clean, mobile-friendly
**PNG report image**. You give it a title and a list of "metrics" (for example:
how many loans were approved today vs. the usual average), and it draws a header
plus one coloured card per metric. Each card shows the metric name, how far it is
above or below the average (a big coloured percentage with an arrow), the current
vs. average values, and a small line chart (sparkline) of the recent trend.

The image comes back in memory as a `BytesIO` PNG, so you can send it straight to
Telegram, attach it to an email, or save it to disk — without writing any drawing
code yourself.

### Quick Start Guide

1. **Install the optional dependencies** (Pillow + matplotlib):
    ```bash
    pip install "vdx_auto_utils[dashboard]"
    ```

2. **Import the function**:
    ```python
    from vdx_auto_utils.dashboard_image import generate_dashboard_image
    ```

3. **Build your metrics and generate the image**:
    ```python
    from datetime import datetime

    metrics = [
        {"name": "Approved", "current": 233, "average": 177.29, "difference_pct": 31.4},
    ]

    png = generate_dashboard_image(
        topic_name="Loan Listing",
        report_datetime=datetime.now(),
        metrics=metrics,
        platform_name="FastRinggit",
    )
    ```

4. **Use the PNG** (save or send):
    ```python
    with open("loan_listing.png", "wb") as f:
        f.write(png.getvalue())
    ```

---

## Overview

The module exposes two functions:

| Function | Purpose |
|----------|---------|
| `generate_dashboard_image` | Title + metrics → in-memory PNG image (`BytesIO`). |
| `trim_sparkline_series` | Shorten long trend data so the chart stays readable. |

Internally it uses **Pillow (PIL)** to draw the layout, text, and icons, and
**matplotlib** to render the sparkline charts. The output is a single fixed-width
(1080px) PNG that looks good on mobile.

---

## Installation

This module needs `pillow` and `matplotlib`, which are **optional extras** so
projects that don't draw images stay lightweight:

```bash
pip install "vdx_auto_utils[dashboard]"
```

---

## The Metric Dictionary

Each metric is a plain Python dictionary. One card is drawn per metric, in order.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Card label, e.g. `"Approved"`. |
| `current` | `float` | The current/latest value. |
| `average` | `float` | The average/benchmark value. |
| `difference_pct` | `float` | Percent difference vs. average. Its sign decides the colour (positive → green, negative → red, `0` → amber). |

**Optional fields:**

| Field | Type | Description |
|-------|------|-------------|
| `actual_trend` | `list[float]` | Recent values for the mini line-chart. |
| `average_trend` | `list[float]` | Benchmark values for the chart. |
| `trend_labels` | `list[str]` | X-axis labels, e.g. `["05:00", "06:00"]`. |
| `unit` | `str` | Pass `"RM"` to format values as currency (e.g. `RM 1,234.56`). |
| `status` | `str` | Force the colour theme instead of using the sign of `difference_pct`. One of `"above_average"`, `"below_average"`, `"neutral"`. Useful when "down is good" (e.g. tracking failures/rejections). |
| `icon` | `str` | Force a specific icon instead of the auto-picked one (see [Icons](#icons)). |

If you omit the trend fields, the card still renders with the numbers and a
simple chart derived from `current`.

---

## Functions

### `generate_dashboard_image`
```python
def generate_dashboard_image(
    topic_name: str,
    report_datetime: Any,
    metrics: list[dict],
    platform_name: str = "PayLaju",
) -> BytesIO
```
Turn a title and a list of metrics into a ready-to-share PNG dashboard image.

- **Parameters:**
  - `topic_name` (str): Report/topic name shown in the header. The header reads `"{platform_name} Alert - {topic_name}"`.
  - `report_datetime` (datetime | str): A `datetime` (preferred) or pre-formatted string shown under the title. Also used to auto-generate chart hour labels.
  - `metrics` (list[dict]): Non-empty list of metric dictionaries (see [The Metric Dictionary](#the-metric-dictionary)). One card is drawn per metric.
  - `platform_name` (str): Brand/platform name shown in the header. Defaults to `"PayLaju"`.
- **Returns:**
  - `BytesIO`: An in-memory PNG image, rewound to the start (`seek(0)`) and ready to read or send.
- **Raises:**
  - `ValueError`: If `metrics` is empty.
  - `OSError`: If no usable TrueType font can be found for rendering.

### `trim_sparkline_series`
```python
def trim_sparkline_series(
    actual_trend: list[float],
    average_trend: list[float],
    trend_labels: list[str] | None = None,
    window: int = 6,
) -> tuple[list[float], list[float], list[str]]
```
Keep only the most recent points of a trend so the chart stays readable.

When you track a value hour by hour, the list can get long (24+ points). Drawing
all of them makes the mini chart cramped. This helper trims the three parallel
lists down to the last `window` points and keeps them aligned (padding labels
with empty strings or truncating extras as needed).

- **Parameters:**
  - `actual_trend` (list[float]): Measured values, oldest first.
  - `average_trend` (list[float]): Benchmark/average values for the same points (may be empty).
  - `trend_labels` (list[str], optional): Per-point labels, e.g. `["02:00", "03:00"]`.
  - `window` (int): How many of the most recent points to keep. Defaults to `6`.
- **Returns:**
  - `tuple[list[float], list[float], list[str]]`: The three lists trimmed to at most `window` points each.

**Example:**
```python
from vdx_auto_utils.dashboard_image import trim_sparkline_series

actual = [10, 20, 30, 40, 50, 60, 70, 80]
avg    = [15, 25, 35, 45, 55, 65, 75, 85]
labels = [f"{h:02d}:00" for h in range(8)]

a, b, lab = trim_sparkline_series(actual, avg, labels, window=3)
# a   -> [60, 70, 80]
# lab -> ['05:00', '06:00', '07:00']
```

---

## Colour & Status Rules

The card colour comes from `difference_pct` automatically:

| Condition | Status | Colour |
|-----------|--------|--------|
| `difference_pct > 0` | `above_average` | Green |
| `difference_pct < 0` | `below_average` | Red |
| `difference_pct == 0` | `neutral` | Amber |

To override this (for example, when a **drop is good** — like fewer failed
transactions), set the metric's `status` field explicitly:

```python
{
    "name": "Rejected",
    "current": 5,
    "average": 20,
    "difference_pct": -75.0,
    "status": "above_average",  # fewer rejections is good -> show green
}
```

---

## Icons

If you don't set the `icon` field, an icon is auto-picked from the metric name
first, then the topic name. Available icon keys:

`approved`, `disbursed`, `closed`, `in_progress`, `pending`, `count`, `amount`,
`register`, `loan_listing`, `kyc`, `fpx`, `repayment`, and a generic fallback.

Override it per metric with `"icon": "amount"`, etc.

---

## Usage Example

```python
from datetime import datetime
from vdx_auto_utils.dashboard_image import generate_dashboard_image

metrics = [
    {
        "name": "Approved",
        "current": 233,
        "average": 177.29,
        "difference_pct": 31.4,
        "actual_trend": [40, 90, 150, 200, 233],
        "trend_labels": ["02:00", "03:00", "04:00", "05:00", "06:00"],
    },
    {
        "name": "Disbursed",
        "current": 103,
        "average": 81.14,
        "difference_pct": 26.9,
    },
    {
        "name": "Closed",
        "current": 22,
        "average": 52.71,
        "difference_pct": -58.3,  # negative -> red card
    },
]

png = generate_dashboard_image(
    topic_name="Loan Listing",
    report_datetime=datetime(2026, 6, 14, 6, 0),
    metrics=metrics,
    platform_name="FastRinggit",
)

with open("loan_listing.png", "wb") as f:
    f.write(png.getvalue())
```

---

## Sending the Image to Telegram

`generate_dashboard_image` returns a PNG buffer. To send it with the library's
[`TelegramBot`](./telegram_doc.md), write it to a temporary file first
(`send_document` routes `.png` files to Telegram's `sendPhoto`):

```python
from vdx_auto_utils import TelegramBot
from vdx_auto_utils.dashboard_image import generate_dashboard_image

png = generate_dashboard_image("Loan Listing", report_dt, metrics, "FastRinggit")

with open("alert.png", "wb") as f:
    f.write(png.getvalue())

bot = TelegramBot("YOUR_BOT_TOKEN")
bot.send_document(
    group_id="-1003684073969",
    file_path="alert.png",
    caption="Loan Listing Alert",
    topic_id=8,
)
```

---

## Notes & Gotchas

- **Width is fixed at 1080px.** Height grows with the number of metrics. Keep
  metric lists short (1–4 cards) for the best look.
- **The chart benchmark is simplified for display.** The sparkline draws the real
  `actual_trend` but a flat benchmark line at the top of the chart area for a
  clean look; the precise `average_trend` numbers are not plotted point-for-point.
  The accurate values are always shown in the card's "Current / Avg" text.
- **Fonts.** Rendering uses matplotlib's bundled DejaVu Sans (Docker/Linux safe),
  falling back to system fonts. If none are found, an `OSError` is raised.
- **Status vs. colour.** When "down is good", set `status` explicitly per metric;
  otherwise the colour follows the sign of `difference_pct`.
