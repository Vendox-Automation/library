# GoogleSheetsListener Documentation

## Table of Contents
- [How to Use in Your Project](#how-to-use-in-your-project)
  - [Quick Start Guide](#quick-start-guide)
- [Overview](#overview)
- [Class: GoogleSheetsListener](#class-googlesheetslistener)
  - [Initialization](#initialization)
  - [Methods](#methods)
    - [start_listening](#start_listening)
    - [write_to_cell](#write_to_cell)
    - [stop_listening](#stop_listening)
  - [Private Helper Methods](#private-helper-methods)
- [Trigger Logic](#trigger-logic)
- [Usage Example](#usage-example)

## How to Use in Your Project

`GoogleSheetsListener` monitors a Google Sheet on a loop and fires a callback function whenever a row is "triggered". Your callback handles all the business logic — the listener just delivers the row data and gets out of the way.

### Quick Start Guide

1. **Import the Class**:
    ```python
    from functions.listener import GoogleSheetsListener
    ```

2. **Set Up Your `header_map`**:
    Map internal keys to the actual column headers in your sheet. At minimum, you must map `'trigger'` and `'status'`.
    ```python
    header_map = {
        'trigger':  'Run Automation',   # A checkbox column
        'status':   'Status',           # Written to after processing
        'order_id': 'Order ID',         # Any other columns you need
        'email':    'Customer Email'
    }
    ```

3. **Initialize**:
    ```python
    listener = GoogleSheetsListener(
        credentials_file="path/to/service_account.json",
        spreadsheet_id="your_google_sheet_id",
        worksheet_name="Sheet1",
        header_map=header_map,
        check_interval=10   # Seconds between polls
    )
    ```

4. **Define Your Callback**:
    The listener passes a `data_package` dict to your function. Your function **must update the `'status'` column** to prevent the row from re-triggering on the next poll.
    ```python
    def my_callback(data):
        row = data['row_index']
        order = data['order_id']
        
        # ... your automation logic here ...
        
        # Always write back to prevent re-triggering
        listener.write_to_cell(row, 'Status', 'Done')
    ```

5. **Start Listening**:
    ```python
    listener.start_listening(my_callback)
    ```

---

## Overview

`GoogleSheetsListener` is a polling-based automation trigger built on top of `gspread`. It scans a Google Sheet at a configurable interval, and for each row where a trigger checkbox is `TRUE` and the status column is empty, it packages up the row data and passes it to your callback function. The listener itself has no opinion about what happens next — all logic lives in the callback.

Authentication is handled internally using a Google service account credentials file.

---

## Class: `GoogleSheetsListener`

### Initialization
```python
def __init__(self, credentials_file: str, spreadsheet_id: str, worksheet_name: str,
             header_map: Dict[str, str], check_interval: int = 10)
```

- **Parameters:**
  - `credentials_file` (str): Path to a Google service account JSON credentials file. Must have access to the target spreadsheet.
  - `spreadsheet_id` (str): The ID of the Google Spreadsheet (found in the sheet's URL).
  - `worksheet_name` (str): The name of the specific tab/worksheet to monitor.
  - `header_map` (Dict[str, str]): A dictionary mapping internal keys to column header names in the sheet. **Must include `'trigger'` and `'status'` keys.**
  - `check_interval` (int, optional): Polling interval in seconds. Defaults to `10`.

---

### Methods

#### `start_listening`
```python
def start_listening(self, callback_func: Callable[[Dict[str, Any]], None])
```
Starts the main monitoring loop. Blocks the current thread indefinitely until `stop_listening()` is called. On each poll, it scans all rows for triggers and calls `callback_func` for each matching row.

- **Parameters:**
  - `callback_func` (Callable): A function that accepts a single `data_package` dictionary. The dict contains all keys defined in `header_map`, plus `'row_index'` (1-based sheet row number).
- **Notes:**
  - The loop handles connection errors gracefully with a 15-second retry delay.
  - Header mismatches (a column name not found in the sheet) are logged and retried after 30 seconds.
  - **The callback is responsible for updating the `'status'` cell** to prevent infinite re-triggering of the same row.

---

#### `write_to_cell`
```python
def write_to_cell(self, row_index: int, column_name: str, value: Any)
```
Writes a value to a specific cell, identified by row number and column header name. Intended to be called from within your callback to write results or status updates back to the sheet.

- **Parameters:**
  - `row_index` (int): The 1-based row number in the sheet (provided via `data_package['row_index']`).
  - `column_name` (str): The exact column header name as it appears in row 1 of the sheet.
  - `value` (Any): The value to write into the cell.
- **Notes:**
  - Prints a warning if the column name is not found in the sheet headers.

---

#### `stop_listening`
```python
def stop_listening(self)
```
Signals the listening loop to stop after the current poll cycle completes. Useful for graceful shutdown when running the listener in a thread.

---

### Private Helper Methods

- **`_get_worksheet(self)`**: Opens and returns the `gspread` worksheet object. Called internally before each poll and each `write_to_cell` call.

---

## Trigger Logic

A row is processed by the callback **only if both conditions are met**:

| Condition | Column | Expected Value |
|-----------|--------|----------------|
| Trigger is active | Mapped to `'trigger'` key | Cell value is `"TRUE"` (case-insensitive) |
| Not yet processed | Mapped to `'status'` key | Cell value is empty/blank |

This means that once your callback writes anything to the status column, that row will be skipped on all future polls.

---

## Usage Example

```python
from functions.listener import GoogleSheetsListener

CREDS = "config/service_account.json"
SHEET_ID = "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms"
TAB_NAME = "Automation Queue"

header_map = {
    'trigger':  'Run',
    'status':   'Status',
    'name':     'Customer Name',
    'email':    'Email Address',
    'amount':   'Order Amount'
}

listener = GoogleSheetsListener(
    credentials_file=CREDS,
    spreadsheet_id=SHEET_ID,
    worksheet_name=TAB_NAME,
    header_map=header_map,
    check_interval=15
)

def handle_row(data):
    row = data['row_index']
    name = data['name']
    email = data['email']

    try:
        # Your automation logic here
        print(f"Processing order for {name} ({email})")
        
        # Mark as done so it won't re-trigger
        listener.write_to_cell(row, 'Status', 'Processed')
    except Exception as e:
        listener.write_to_cell(row, 'Status', f'Error: {e}')

listener.start_listening(handle_row)
```