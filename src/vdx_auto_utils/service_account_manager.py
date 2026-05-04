import logging
import os
import time
from typing import Any, Callable, Dict, List, Optional

import gspread
from google.oauth2.service_account import Credentials


class ServiceAccountManager:
    """
    Manage multiple Google service accounts with automatic quota failover.

    This class intentionally focuses on account lifecycle only:
    - credential/client creation
    - quota-error detection
    - account cooldown and rotation
    """

    DEFAULT_SCOPES = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    def __init__(
        self,
        service_account_files: List[str],
        scopes: Optional[List[str]] = None,
        account_indices: Optional[List[int]] = None,
        cooldown_seconds: int = 3600,
        logger: Optional[logging.Logger] = None,
    ):
        """
        Initialize the service-account manager.

        Args:
            service_account_files: List of JSON credential file paths.
            scopes: OAuth scopes used to build Google credentials.
            account_indices: Optional subset of account indexes to use.
            cooldown_seconds: Cooldown period for exhausted accounts.
            logger: Optional custom logger. Defaults to module logger.

        Raises:
            ValueError: If no accounts are provided or no valid subset remains.
        """
        if not service_account_files:
            raise ValueError("service_account_files cannot be empty.")

        filtered_files = self._filter_account_files(
            service_account_files, account_indices
        )
        if not filtered_files:
            raise ValueError(
                "No valid service account files available after filtering."
            )

        self.service_account_files = filtered_files
        self.scopes = scopes or self.DEFAULT_SCOPES
        self.cooldown_seconds = max(0, int(cooldown_seconds))
        self.logger = logger or logging.getLogger(__name__)

        self.current_account_index = 0
        self._cooldown_until: Dict[int, float] = {}
        self._last_errors: Dict[int, str] = {}

    def _filter_account_files(
        self, service_account_files: List[str], account_indices: Optional[List[int]]
    ) -> List[str]:
        """
        Return the selected account files based on optional index filtering.

        Args:
            service_account_files: Full list of account file paths.
            account_indices: Optional list of indexes to keep.

        Returns:
            List of account files to use.
        """
        if not account_indices:
            return service_account_files

        filtered: List[str] = []
        for idx in account_indices:
            if 0 <= idx < len(service_account_files):
                filtered.append(service_account_files[idx])
        return filtered

    def _is_in_cooldown(self, account_index: int) -> bool:
        """
        Check whether an account is still in cooldown.

        Expired cooldown entries are cleared automatically.

        Args:
            account_index: Index of account in current manager list.

        Returns:
            True if account is still cooling down, else False.
        """
        until_ts = self._cooldown_until.get(account_index)
        if not until_ts:
            return False
        if time.time() >= until_ts:
            self._cooldown_until.pop(account_index, None)
            self._last_errors.pop(account_index, None)
            return False
        return True

    def get_current_account_file(self) -> str:
        """
        Get the credential file path for the active account.

        Returns:
            Path to the current service-account JSON file.
        """
        return self.service_account_files[self.current_account_index]

    def get_current_credentials(self) -> Credentials:
        """
        Build Google credentials for the active account.

        Returns:
            google.oauth2.service_account.Credentials for current account.

        Raises:
            FileNotFoundError: If the active account file path does not exist.
        """
        credentials_file = self.get_current_account_file()
        if not os.path.exists(credentials_file):
            raise FileNotFoundError(
                f"Service account file not found: {credentials_file}"
            )

        return Credentials.from_service_account_file(
            credentials_file, scopes=self.scopes
        )

    def get_current_client(self) -> gspread.Client:
        """
        Create an authenticated gspread client for the active account.

        Returns:
            Authenticated gspread client.
        """
        credentials = self.get_current_credentials()
        return gspread.authorize(credentials)

    def mark_current_account_exhausted(
        self, error: Optional[Exception] = None, cooldown_seconds: Optional[int] = None
    ) -> None:
        """
        Mark the current account as exhausted and apply cooldown.

        Args:
            error: Optional error object for status/debugging visibility.
            cooldown_seconds: Optional override for cooldown duration.
        """
        cooldown = (
            self.cooldown_seconds
            if cooldown_seconds is None
            else max(0, int(cooldown_seconds))
        )
        account_index = self.current_account_index
        self._cooldown_until[account_index] = time.time() + cooldown

        if error is not None:
            self._last_errors[account_index] = str(error)

        self.logger.warning(
            "Service account marked exhausted: %s (cooldown=%ss)",
            self.service_account_files[account_index],
            cooldown,
        )

    def switch_to_next_account(self) -> bool:
        """
        Rotate to the next available account that is not in cooldown.

        Returns:
            True if an account switch succeeded, else False.
        """
        total = len(self.service_account_files)
        if total == 1:
            return not self._is_in_cooldown(0)

        start = self.current_account_index
        for offset in range(1, total + 1):
            next_index = (start + offset) % total
            if not self._is_in_cooldown(next_index):
                self.current_account_index = next_index
                self.logger.info(
                    "Switched to service account: %s",
                    self.service_account_files[next_index],
                )
                return True
        return False

    def reset_exhausted_accounts(self, account_index: Optional[int] = None) -> None:
        """
        Clear cooldown/exhausted state for one account or all accounts.

        Args:
            account_index: Specific account index to reset. If None, reset all.
        """
        if account_index is None:
            self._cooldown_until.clear()
            self._last_errors.clear()
            return

        self._cooldown_until.pop(account_index, None)
        self._last_errors.pop(account_index, None)

    def is_quota_error(self, error: Exception) -> bool:
        """
        Detect quota/rate-limit style errors from exception text.

        Args:
            error: Exception raised by Google API client call.

        Returns:
            True if error appears quota/rate-limit related, else False.
        """
        message = str(error).lower()
        quota_indicators = [
            "429",
            "quota exceeded",
            "rate limit",
            "too many requests",
            "resource exhausted",
        ]
        return any(indicator in message for indicator in quota_indicators)

    def handle_quota_error(self, error: Exception) -> bool:
        """
        Handle a quota error by exhausting current account and rotating.

        Args:
            error: Exception from operation execution.

        Returns:
            True if error was quota-related and a switch attempt was made.
            False if error is not quota-related.
        """
        if not self.is_quota_error(error):
            return False

        self.mark_current_account_exhausted(error=error)
        return self.switch_to_next_account()

    def execute_with_failover(
        self, operation: Callable[..., Any], *args, **kwargs
    ) -> Any:
        """
        Execute an operation that receives a gspread client as first argument.

        Retries by switching to another service account only on quota-related errors.

        Args:
            operation: Callable that accepts `client` as first parameter.
            *args: Positional arguments passed to operation after client.
            **kwargs: Keyword arguments passed to operation.

        Returns:
            The return value of `operation(...)`.

        Raises:
            RuntimeError: If all accounts are exhausted or in cooldown.
            Exception: Re-raises non-quota operation errors.
        """
        max_attempts = len(self.service_account_files)
        attempts = 0
        last_error: Optional[Exception] = None

        while attempts < max_attempts:
            try:
                client = self.get_current_client()
                return operation(client, *args, **kwargs)
            except Exception as error:  # noqa: BLE001
                last_error = error
                if not self.handle_quota_error(error):
                    raise
                attempts += 1

        raise RuntimeError(
            "All service accounts are exhausted or in cooldown."
        ) from last_error

    def get_status(self) -> Dict[str, Any]:
        """
        Get runtime status for monitoring and debugging.

        Returns:
            Dictionary with current account, exhausted accounts, and counts.
        """
        exhausted_accounts = sorted(self._cooldown_until.keys())
        return {
            "current_account_index": self.current_account_index,
            "current_account_file": self.get_current_account_file(),
            "total_accounts": len(self.service_account_files),
            "exhausted_accounts": exhausted_accounts,
            "available_accounts": len(self.service_account_files)
            - len(exhausted_accounts),
            "cooldown_seconds": self.cooldown_seconds,
            "last_errors": dict(self._last_errors),
        }
