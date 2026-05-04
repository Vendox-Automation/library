# retry_utils Documentation

## Table of Contents
- [How to Use in Your Project](#how-to-use-in-your-project)
  - [Quick Start Guide](#quick-start-guide)
- [Overview](#overview)
- [Decorator: with_retry](#decorator-with_retry)
- [Usage Example](#usage-example)

## How to Use in Your Project

`with_retry` is a function decorator that automatically retries a function when it raises an exception or returns `None`. Apply it directly above any function definition.

### Quick Start Guide

1. **Import the decorator**:
    ```python
    from vdx_auto_utils import with_retry
    ```

2. **Apply it to a function**:
    ```python
    @with_retry(max_attempts=5, delay_seconds=3)
    def fetch_data():
        ...
    ```

3. **Call the function normally** — retries are handled automatically:
    ```python
    result = fetch_data()
    ```

---

## Overview

`with_retry` wraps a function to re-execute it on failure. A retry is triggered when the function either raises any exception or returns `None`. The wait between each attempt increases by 2 seconds progressively (e.g. 3s → 5s → 7s…).

On final failure the decorator returns an empty list (`[]`) if the last result was a list, or `None` for all other return types.

---

## Decorator: `with_retry`

```python
def with_retry(max_attempts: int = 5, delay_seconds: int = 3)
```

- **Parameters:**
  - `max_attempts` (int): Maximum number of attempts including the first call. Defaults to `5`.
  - `delay_seconds` (int): Initial delay in seconds between the first and second attempt. Each subsequent delay increases by `2` seconds. Defaults to `3`.

- **Returns:** The decorated function. On final failure returns `[]` if the last result was a `list`, otherwise `None`.

- **Retry conditions:**
  - The wrapped function raises any `Exception`.
  - The wrapped function returns `None`.

- **Delay schedule** (default `delay_seconds=3`):

  | Attempt | Delay before next attempt |
  |---------|--------------------------|
  | 1       | 3 s                      |
  | 2       | 5 s                      |
  | 3       | 7 s                      |
  | 4       | 9 s                      |
  | 5       | Final — no more retries  |

---

## Usage Example

```python
from vdx_auto_utils import with_retry

# Basic usage — retry up to 5 times with a 3s initial delay
@with_retry(max_attempts=5, delay_seconds=3)
def fetch_report(date: str):
    response = requests.get(f"https://api.example.com/report?date={date}")
    response.raise_for_status()
    return response.json()

data = fetch_report("2024-01-01")
if data is None:
    print("All attempts failed.")

# Returning a list — gets [] on final failure instead of None
@with_retry(max_attempts=3, delay_seconds=5)
def get_rows_from_sheet():
    rows = sheet.get_all_values()
    return rows if rows else None  # None triggers a retry

rows = get_rows_from_sheet()
if not rows:
    print("No data retrieved after all attempts.")
```
