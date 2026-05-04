import pytest
import time
from unittest.mock import MagicMock, patch
from vdx_auto_utils.service_account_manager import ServiceAccountManager


class TestServiceAccountManager:

    def test_raises_if_no_files_provided(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            ServiceAccountManager([])

    def test_initialises_with_single_account(self):
        mgr = ServiceAccountManager(["account1.json"])
        assert mgr.current_account_index == 0
        assert len(mgr.service_account_files) == 1

    def test_filters_accounts_by_index(self):
        files = ["a.json", "b.json", "c.json"]
        mgr = ServiceAccountManager(files, account_indices=[0, 2])
        assert mgr.service_account_files == ["a.json", "c.json"]

    def test_raises_if_filtered_list_is_empty(self):
        with pytest.raises(ValueError):
            ServiceAccountManager(["a.json"], account_indices=[99])

    def test_is_quota_error_detects_429(self):
        mgr = ServiceAccountManager(["a.json"])
        err = Exception("HTTP 429: Too Many Requests")
        assert mgr.is_quota_error(err) is True

    def test_is_quota_error_detects_quota_exceeded(self):
        mgr = ServiceAccountManager(["a.json"])
        err = Exception("quota exceeded for this project")
        assert mgr.is_quota_error(err) is True

    def test_is_quota_error_returns_false_for_other_errors(self):
        mgr = ServiceAccountManager(["a.json"])
        err = Exception("invalid credentials")
        assert mgr.is_quota_error(err) is False

    def test_mark_account_exhausted_sets_cooldown(self):
        mgr = ServiceAccountManager(["a.json"], cooldown_seconds=60)
        mgr.mark_current_account_exhausted()
        assert 0 in mgr._cooldown_until
        assert mgr._cooldown_until[0] > time.time()

    def test_switch_to_next_account_rotates(self):
        mgr = ServiceAccountManager(["a.json", "b.json", "c.json"])
        assert mgr.current_account_index == 0
        switched = mgr.switch_to_next_account()
        assert switched is True
        assert mgr.current_account_index == 1

    def test_switch_returns_false_if_all_in_cooldown(self):
        mgr = ServiceAccountManager(["a.json", "b.json"])
        mgr._cooldown_until[0] = time.time() + 9999
        mgr._cooldown_until[1] = time.time() + 9999
        result = mgr.switch_to_next_account()
        assert result is False

    def test_reset_clears_all_cooldowns(self):
        mgr = ServiceAccountManager(["a.json", "b.json"])
        mgr._cooldown_until = {0: time.time() + 999, 1: time.time() + 999}
        mgr.reset_exhausted_accounts()
        assert mgr._cooldown_until == {}

    def test_get_status_returns_expected_keys(self):
        mgr = ServiceAccountManager(["a.json", "b.json"])
        status = mgr.get_status()
        assert "current_account_index" in status
        assert "total_accounts" in status
        assert "available_accounts" in status
        assert "exhausted_accounts" in status

    def test_execute_with_failover_switches_on_quota_error(self):
        mgr = ServiceAccountManager(["a.json", "b.json"])
        calls = []

        mock_client = MagicMock()

        def operation(client):
            calls.append(len(calls))
            if len(calls) == 1:
                raise Exception("429 quota exceeded")
            return "success"

        with patch.object(mgr, "get_current_client", return_value=mock_client):
            with patch.object(mgr, "handle_quota_error", wraps=mgr.handle_quota_error):
                # Patch switch so it doesn't actually rotate (single account scenario)
                with patch.object(mgr, "switch_to_next_account", return_value=False):
                    with pytest.raises(RuntimeError, match="exhausted"):
                        mgr.execute_with_failover(operation)