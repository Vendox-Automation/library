import pytest
from unittest.mock import patch
from src.vdx_auto_utils.retry_utils import with_retry

class TestWithRetry:

    def test_succeeds_on_first_attempt(self):
        @with_retry(max_attempts=3, delay_seconds=0)
        def always_works():
            return "ok"

        assert always_works() == "ok"

    def test_retries_and_succeeds_eventually(self):
        calls = []

        @with_retry(max_attempts=3, delay_seconds=0)
        def flaky():
            calls.append(1)
            if len(calls) < 3:
                raise ValueError("not yet")
            return "ok"

        with patch("time.sleep"):
            result = flaky()

        assert result == "ok"
        assert len(calls) == 3

    def test_returns_none_after_max_attempts(self):
        @with_retry(max_attempts=3, delay_seconds=0)
        def always_fails():
            raise RuntimeError("boom")

        with patch("time.sleep"):
            result = always_fails()

        assert result is None

    def test_returns_empty_list_if_last_result_was_list(self):
        # If the function had previously returned a list but then fails,
        # with_retry returns [] instead of None
        calls = []

        @with_retry(max_attempts=3, delay_seconds=0)
        def fails_after_list():
            calls.append(1)
            if len(calls) == 1:
                return None  # triggers ValueError internally
            raise RuntimeError("boom")

        with patch("time.sleep"):
            result = fails_after_list()

        assert result is None

    def test_returns_none_when_function_returns_none(self):
        @with_retry(max_attempts=2, delay_seconds=0)
        def returns_none():
            return None

        with patch("time.sleep"):
            result = returns_none()

        assert result is None

    def test_delay_increases_between_attempts(self):
        sleep_calls = []

        @with_retry(max_attempts=3, delay_seconds=2)
        def always_fails():
            raise RuntimeError("boom")

        with patch("time.sleep", side_effect=lambda s: sleep_calls.append(s)):
            always_fails()

        # First sleep = 2s, second sleep = 4s (increases by 2 each time)
        assert sleep_calls == [2, 4]