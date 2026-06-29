"""
Tests for dashboard_image and an optional manual Telegram send.

Unit tests run in CI when pillow + matplotlib are installed (they skip otherwise).

To try sending a real dashboard image to Telegram:
  1. Fill in TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID below.
  2. Optionally set TELEGRAM_TOPIC_ID for a forum topic.
  3. Run: pytest tests/test_dashboard_image.py::test_send_dashboard_to_telegram -v -s
"""

from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from vdx_auto_utils.dashboard_image import (
    generate_dashboard_image,
    trim_sparkline_series,
)

# ---------------------------------------------------------------------------
# Telegram placeholders — replace with your own values for a live send test
# ---------------------------------------------------------------------------
TELEGRAM_BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"
TELEGRAM_CHAT_ID = "YOUR_CHAT_ID_HERE"
TELEGRAM_TOPIC_ID = None  # e.g. 8 for a forum topic; leave None for the main chat


def _telegram_configured() -> bool:
    return (
        TELEGRAM_BOT_TOKEN != "YOUR_BOT_TOKEN_HERE"
        and TELEGRAM_CHAT_ID != "YOUR_CHAT_ID_HERE"
        and bool(TELEGRAM_BOT_TOKEN.strip())
        and bool(TELEGRAM_CHAT_ID.strip())
    )


def _sample_metrics() -> list[dict]:
    """Example metrics similar to a Loan Listing hourly alert."""
    return [
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
            "actual_trend": [20, 45, 70, 90, 103],
        },
        {
            "name": "Closed",
            "current": 22,
            "average": 52.71,
            "difference_pct": -58.3,
            "actual_trend": [10, 14, 18, 20, 22],
        },
    ]


pytest.importorskip("PIL")
pytest.importorskip("matplotlib")


class TestTrimSparklineSeries:

    def test_keeps_all_points_when_under_window(self):
        actual = [1.0, 2.0, 3.0]
        average = [1.5, 2.5, 3.5]
        labels = ["01:00", "02:00", "03:00"]

        a, b, lab = trim_sparkline_series(actual, average, labels, window=6)

        assert a == actual
        assert b == average
        assert lab == labels

    def test_trims_to_last_window_points(self):
        actual = [10, 20, 30, 40, 50, 60, 70, 80]
        average = [15, 25, 35, 45, 55, 65, 75, 85]
        labels = [f"{h:02d}:00" for h in range(8)]

        a, b, lab = trim_sparkline_series(actual, average, labels, window=3)

        assert a == [60, 70, 80]
        assert b == [65, 75, 85]
        assert lab == ["05:00", "06:00", "07:00"]

    def test_pads_short_label_list(self):
        actual = [1.0, 2.0, 3.0]
        a, _, lab = trim_sparkline_series(actual, [], ["01:00"], window=6)

        assert len(lab) == len(a)
        assert lab == ["01:00", "", ""]


class TestGenerateDashboardImage:

    def test_returns_png_bytesio(self):
        png = generate_dashboard_image(
            topic_name="Loan Listing",
            report_datetime=datetime(2026, 6, 14, 6, 0),
            metrics=_sample_metrics(),
            platform_name="FastRinggit",
        )

        data = png.getvalue()
        assert data.startswith(b"\x89PNG\r\n\x1a\n")
        assert len(data) > 1000

    def test_raises_when_metrics_empty(self):
        with pytest.raises(ValueError, match="At least one metric"):
            generate_dashboard_image(
                topic_name="Loan Listing",
                report_datetime=datetime.now(),
                metrics=[],
            )

    def test_single_metric_renders(self):
        png = generate_dashboard_image(
            topic_name="Register",
            report_datetime=datetime.now(),
            metrics=[
                {
                    "name": "Count",
                    "current": 50,
                    "average": 40,
                    "difference_pct": 25.0,
                }
            ],
            platform_name="PayLaju",
        )

        assert png.getvalue().startswith(b"\x89PNG")


@pytest.mark.skipif(
    not _telegram_configured(),
    reason="Fill in TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID at the top of this file",
)
def test_send_dashboard_to_telegram():
    """
    Manual integration test: generates a dashboard PNG and sends it via TelegramBot.

    Requires network access and valid bot token + chat ID.
    """
    from vdx_auto_utils.telegram import TelegramBot

    png = generate_dashboard_image(
        topic_name="Loan Listing",
        report_datetime=datetime.now(),
        metrics=_sample_metrics(),
        platform_name="FastRinggit",
    )

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp.write(png.getvalue())
        image_path = tmp.name

    try:
        bot = TelegramBot(api_token=TELEGRAM_BOT_TOKEN)
        result = bot.send_document(
            group_id=TELEGRAM_CHAT_ID,
            file_path=image_path,
            caption="Test dashboard from vdx_auto_utils (pytest)",
            topic_id=TELEGRAM_TOPIC_ID,
        )
        assert result is not None
        assert result.get("ok") is True
    finally:
        Path(image_path).unlink(missing_ok=True)
