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

## `get_status()` Return Value

`get_status()` returns a dictionary with the following keys:

| Key                     | Type        | Description                                         |
|-------------------------|-------------|-----------------------------------------------------|
| `current_account_index` | `int`       | Index of the account currently in use               |
| `current_account_file`  | `str`       | File path of the currently active account           |
| `total_accounts`        | `int`       | Total number of accounts managed                    |
| `exhausted_accounts`    | `List[int]` | Indexes of accounts currently in cooldown           |
| `available_accounts`    | `int`       | Number of accounts not in cooldown                  |
| `cooldown_seconds`      | `int`       | Configured cooldown duration                        |
| `last_errors`           | `Dict`      | Maps exhausted account indexes to their last error  |

**Example output:**
```python
{
    "current_account_index": 1,
    "current_account_file": "C:\\creds\\acc_2.json",
    "total_accounts": 3,
    "exhausted_accounts": [0],
    "available_accounts": 2,
    "cooldown_seconds": 3600,
    "last_errors": {0: "429 RESOURCE_EXHAUSTED: Quota exceeded..."}
}
```

## Using `account_indices`

Use `account_indices` to restrict the manager to a specific subset of the accounts list. This is useful when different scripts should share only certain accounts or when debugging with a single account.

```python
GOOGLE_SERVICE_ACCOUNTS = [
    r"C:\creds\acc_1.json",  # index 0
    r"C:\creds\acc_2.json",  # index 1
    r"C:\creds\acc_3.json",  # index 2
]

# Only use acc_2.json and acc_3.json
manager = ServiceAccountManager(
    service_account_files=GOOGLE_SERVICE_ACCOUNTS,
    account_indices=[1, 2],
)
```

Indexes refer to positions in `service_account_files`. If an index is out of range it is silently skipped.

## Notes

- Keep your real credential paths in project config files, not in this library.
- This module only switches on quota-like errors (429/rate-limit/quota exceeded).
- Non-quota errors are raised directly to the caller.
- `reset_exhausted_accounts()` with no argument clears all cooldowns. Pass a specific index to reset just one account.
