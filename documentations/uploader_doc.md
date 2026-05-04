# GoogleSheetUploader Documentation

## Table of Contents
- [How to Use in Your Project](#how-to-use-in-your-project)
  - [Quick Start Guide](#quick-start-guide)
  - [Advanced Features](#advanced-features)
- [Overview](#overview)
- [Class: GoogleSheetUploader](#class-googlesheetuploader)
  - [Initialization](#initialization)
  - [Methods](#methods)
    - [upload_dataframe_to_sheet](#upload_dataframe_to_sheet)
    - [update_selective_columns](#update_selective_columns)
    - [upload_csv_to_sheet (Deprecated)](#upload_csv_to_sheet-deprecated)
  - [Internal Helper Methods](#internal-helper-methods)
- [Usage Example](#usage-example)

## How to Use in Your Project

The `GoogleSheetUploader` makes it easy to send your Pandas DataFrames to Google Sheets. It handles authentication, clears old data (if you want), and even resizes the sheet for you.

It supports two authentication modes:
- **`ServiceAccountManager` (recommended)** — automatic quota failover across multiple service accounts.
- **Single credentials file (legacy)** — original behaviour, no failover.

### Quick Start Guide

1.  **Import the Class**:
    ```python
    from vdx_auto_utils import GoogleSheetUploader, ServiceAccountManager
    ```

2.  **Initialize** (recommended — with quota failover):
    ```python
    manager = ServiceAccountManager(["sa1.json", "sa2.json"])
    uploader = GoogleSheetUploader(service_account_manager=manager)
    ```

    Or with a single credentials file (legacy):
    ```python
    uploader = GoogleSheetUploader(credentials_file="path/to/credentials.json")
    ```

3.  **Upload Data**:
    Send your DataFrame to a specific sheet and tab.
    ```python
    uploader.upload_dataframe_to_sheet(
        dataframe=my_df,
        spreadsheet_id="17s2ADB7cYMBYAc8qvztivMlEqCrYWecQ0fDigThg5r0", # From URL
        worksheet_name="Sheet1"
    )
    ```

### Advanced Features

-   **Append Mode**: Add data to the bottom instead of overwriting.
    ```python
    upload_start_cell="APPEND"
    ```

-   **Custom Layout**: Map your DataFrame columns to specific Google Sheet columns (A, B, C...).
    ```python
    my_layout = {'A': 'Name', 'C': 'Email'} # B will be empty
    uploader.upload_dataframe_to_sheet(..., gsheet_layout_map=my_layout)
    ```

---

## Overview
The `GoogleSheetUploader` class is a reusable module designed to upload Pandas DataFrames to Google Sheets using a Service Account. It handles authentication, uploading to specific worksheets, automatic resizing, and custom column mapping.

## Class: `GoogleSheetUploader`

### Initialization
```python
def __init__(
    self,
    credentials_file: Optional[str] = None,
    service_account_manager: Optional[ServiceAccountManager] = None,
)
```
Initialises the uploader. Exactly one of `credentials_file` or `service_account_manager` must be provided.

- **Parameters:**
  - `credentials_file` (str, optional): Path to a single Service Account JSON key file. Kept for backwards compatibility; prefer `service_account_manager` for production use.
  - `service_account_manager` (ServiceAccountManager, optional): A pre-configured `ServiceAccountManager` instance. All gspread calls go through its `execute_with_failover()` so quota errors automatically rotate to the next account.
- **Raises:**
  - `ValueError`: If both or neither arguments are provided.
  - `FileNotFoundError`: If `credentials_file` path does not exist.

### Methods

#### `upload_dataframe_to_sheet`
```python
def upload_dataframe_to_sheet(self, 
                              dataframe: pd.DataFrame, 
                              spreadsheet_id: str,
                              worksheet_name: str = "Sheet1",
                              clear_before_upload: bool = True,
                              upload_start_cell: str = "A1", 
                              include_header: bool = True,
                              gsheet_layout_map: Dict[str, Union[str, None]] = None)
```
The main method to upload a Pandas DataFrame to a Google Sheet. Includes automatic resizing if the data exceeds current grid limits.

- **Parameters:**
  - `dataframe` (pd.DataFrame): The data to upload.
  - `spreadsheet_id` (str): The ID of the Google Sheet (found in the URL).
  - `worksheet_name` (str): The specific tab name to upload to. Defaults to "Sheet1".
  - `clear_before_upload` (bool): If `True`, clears the worksheet content before uploading. Defaults to `True`. Ignored if `upload_start_cell` is "APPEND".
  - `upload_start_cell` (str): The starting cell (e.g., "A1") or "APPEND" to add after existing data.
  - `include_header` (bool): If `True`, includes the DataFrame's header row in the upload. Defaults to `True`. Automatically set to `False` if appending.
  - `gsheet_layout_map` (Dict): Optional mapping of GSheet columns (A, B..) to DataFrame columns.

#### `update_selective_columns`
```python
def update_selective_columns(self,
                             dataframe: pd.DataFrame,
                             spreadsheet_id: str,
                             worksheet_name: str,
                             gsheet_layout_map: Dict[str, str],
                             start_row: int = 3,
                             append: bool = False)
```
Batch-updates specific columns in a worksheet without touching the rest of the sheet. Useful for writing status values, calculated fields, or any partial update while preserving other column data.

- **Parameters:**
  - `dataframe` (pd.DataFrame): The source DataFrame containing the data to update.
  - `spreadsheet_id` (str): The ID of the target Google Sheet.
  - `worksheet_name` (str): The target tab name.
  - `gsheet_layout_map` (Dict[str, str]): Maps Google Sheet column letters to DataFrame column names (e.g., `{'E': 'Status'}`). **Required**. Columns in the map that don't exist in the DataFrame are silently skipped.
  - `start_row` (int): The 1-based row number to start writing from. Defaults to `3`.
  - `append` (bool): If `True`, writes after the last occupied row in the first mapped column instead of at `start_row`. Defaults to `False`.

#### `upload_csv_to_sheet` (Deprecated)
Legacy method. It is recommended to use `CSVFilter` to load/clean data and then use `upload_dataframe_to_sheet`.

### Internal Helper Methods

- **`_prepare_data_for_gspread(df, include_header)`**: Converts a Pandas DataFrame into the nested list format `gspread` expects. Fills `NaN` values with empty strings.
- **`_format_dataframe_to_gsheet_layout(df, layout_map)`**: Reorders and spaces DataFrame columns to match a specific Google Sheet layout (e.g., putting `'Name'` in column A and `'Email'` in column C, leaving B empty). A `None` value in the map creates an intentionally blank column.
- **`_col_letter_to_index(letter)`**: Converts a column letter (`'A'`, `'B'`, `'AA'`…) to a 1-based integer column index. Used internally by `update_selective_columns` when `append=True` to look up the last occupied row in the anchor column.

## Usage Example
```python
from vdx_auto_utils import GoogleSheetUploader, ServiceAccountManager
import pandas as pd

# Initialize with quota failover (recommended)
manager = ServiceAccountManager([
    r"C:\creds\sa1.json",
    r"C:\creds\sa2.json",
])
uploader = GoogleSheetUploader(service_account_manager=manager)

# Or with a single credentials file (legacy)
# uploader = GoogleSheetUploader(credentials_file="credentials.json")

SHEET_ID = "1abc..."

df = pd.DataFrame({
    "Name": ["Alice", "Bob"],
    "Role": ["Admin", "User"],
    "Status": ["Active", "Active"],
})

# 1. Standard Upload (overwrite)
uploader.upload_dataframe_to_sheet(
    dataframe=df,
    spreadsheet_id=SHEET_ID,
    worksheet_name="TeamRoster",
    clear_before_upload=True,
)

# 2. Append Mode — adds rows after existing data, skips header automatically
uploader.upload_dataframe_to_sheet(
    dataframe=df,
    spreadsheet_id=SHEET_ID,
    worksheet_name="HistoryLog",
    upload_start_cell="APPEND",
)

# 3. Custom Layout — place columns at specific sheet positions, leave gaps
layout = {
    'A': 'Name',
    'B': None,   # intentional blank column
    'C': 'Role',
}
uploader.upload_dataframe_to_sheet(
    dataframe=df,
    spreadsheet_id=SHEET_ID,
    worksheet_name="FormattedView",
    gsheet_layout_map=layout,
)

# 4. Selective Column Update — write only specific columns, leave others untouched
status_map = {'E': 'Status'}
uploader.update_selective_columns(
    dataframe=df,
    spreadsheet_id=SHEET_ID,
    worksheet_name="Orders",
    gsheet_layout_map=status_map,
    start_row=3,
)

# 5. Selective Column Update with Append — write after the last occupied row
uploader.update_selective_columns(
    dataframe=df,
    spreadsheet_id=SHEET_ID,
    worksheet_name="Orders",
    gsheet_layout_map=status_map,
    start_row=3,
    append=True,
)
```
