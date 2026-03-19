# ServiceAccountManager Documentation

## Overview

`ServiceAccountManager` helps you use multiple Google service accounts with simple quota failover.

It is designed to:
- Load credentials from a list of service-account JSON files.
- Create a `gspread` client for the current account.
- Detect quota/rate-limit errors.
- Mark exhausted accounts with cooldown.
- Switch to the next available account automatically.

This module currently focuses only on account failover. Network retry logic can be added separately.

## Import

```python
from vdx_auto_utils import ServiceAccountManager
```

## Initialization

```python
manager = ServiceAccountManager(
    service_account_files=GOOGLE_SERVICE_ACCOUNTS,
    account_indices=[0, 1, 2],   # Optional subset
    cooldown_seconds=3600         # Optional, default 1 hour
)
```

### Parameters

- `service_account_files` (`List[str]`, required): list of JSON credential file paths.
- `scopes` (`List[str]`, optional): Google OAuth scopes.
- `account_indices` (`List[int]`, optional): restrict manager to specific account indexes.
- `cooldown_seconds` (`int`, optional): cooldown after quota exhaustion.
- `logger` (`logging.Logger`, optional): custom logger.

## Core Methods

- `get_current_credentials()`: returns credentials for current account.
- `get_current_client()`: returns authenticated `gspread.Client`.
- `switch_to_next_account()`: rotate to next non-exhausted account.
- `mark_current_account_exhausted(error=None, cooldown_seconds=None)`: mark current account in cooldown.
- `is_quota_error(error)`: detect quota/rate-limit style errors.
- `handle_quota_error(error)`: mark + switch when error is quota-related.
- `execute_with_failover(operation, *args, **kwargs)`: run operation with automatic account switching on quota errors.
- `reset_exhausted_accounts(account_index=None)`: clear cooldown state.
- `get_status()`: inspect runtime state.

## Usage Example

```python
from vdx_auto_utils import ServiceAccountManager

GOOGLE_SERVICE_ACCOUNTS = [
    r"C:\creds\acc_1.json",
    r"C:\creds\acc_2.json",
    r"C:\creds\acc_3.json",
]

manager = ServiceAccountManager(service_account_files=GOOGLE_SERVICE_ACCOUNTS)

def read_sheet(client, spreadsheet_id, worksheet_name):
    sheet = client.open_by_key(spreadsheet_id).worksheet(worksheet_name)
    return sheet.get_all_values()

rows = manager.execute_with_failover(
    read_sheet,
    "your_spreadsheet_id",
    "Sheet1",
)

print(f"Rows fetched: {len(rows)}")
print(manager.get_status())
```

## Notes

- Keep your real credential paths in project config files, not in this library.
- This module only switches on quota-like errors (429/rate-limit/quota exceeded).
- Non-quota errors are raised directly to the caller.
