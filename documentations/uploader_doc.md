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
    - [upload_csv_to_sheet (Deprecated)](#upload_csv_to_sheet-deprecated)
  - [Internal Helper Methods](#internal-helper-methods)
- [Usage Example](#usage-example)

## How to Use in Your Project

The `GoogleSheetUploader` makes it easy to send your Pandas DataFrames to Google Sheets. It handles authentication, clears old data (if you want), and even resizes the sheet for you.

### Quick Start Guide

1.  **Import the Class**:
    ```python
    from functions.uploader import GoogleSheetUploader
    ```

2.  **Initialize**:
    Point it to your Google Service Account JSON key.
    ```python
    uploader = GoogleSheetUploader("path/to/credentials.json")
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
def __init__(self, credentials_file_path: str)
```
Initializes the uploader by authenticating with Google using a Service Account JSON key file.
- **Parameters:**
  - `credentials_file_path` (str): Path to the Service Account JSON key file.
- **Raises:**
  - `FileNotFoundError`: If the credentials file is not found.

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
                             worksheet_name: str = "Sheet1", 
                             gsheet_layout_map: Dict[str, str] = None,
                             start_row: int = 1)
```
Updates specific columns in a worksheet without overwriting other columns. This is useful for updating status columns or specific fields while preserving other data.

- **Parameters:**
  - `dataframe` (pd.DataFrame): The source DataFrame containing the data to update.
  - `spreadsheet_id` (str): The ID of the target Google Sheet.
  - `worksheet_name` (str): The target tab name.
  - `gsheet_layout_map` (Dict[str, str]): A dictionary mapping Google Sheet column letters to DataFrame column names (e.g., `{'E': 'Status'}`). **Required**.
  - `start_row` (int): The row number to start the update from. Defaults to 1.

#### `upload_csv_to_sheet` (Deprecated)
Legacy method. It is recommended to use `CSVFilter` to load/clean data and then use `upload_dataframe_to_sheet`.

### Internal Helper Methods

- **`_prepare_data_for_gspread(self, df: pd.DataFrame, include_header: bool) -> List[List[Any]]`**: Converts a Pandas DataFrame into a list of lists format required by `gspread`. Handles `NaN` values.
- **`_format_dataframe_to_gsheet_layout(self, df: pd.DataFrame, layout_map: Dict)`**: Reorders and spaces DataFrame columns to match a specific Google Sheet layout (e.g., putting 'Name' in Col A and 'Email' in Col C).

## Usage Example
```python
from functions.uploader import GoogleSheetUploader
import pandas as pd

# Initialize
uploader = GoogleSheetUploader("credentials.json")

# Prepare Data
df = pd.DataFrame({
    "Name": ["Alice", "Bob"],
    "Role": ["Admin", "User"]
})

# 1. Standard Upload (Overwrite)
uploader.upload_dataframe_to_sheet(
    dataframe=df,
    spreadsheet_id="1abc...",
    worksheet_name="TeamRoster",
    clear_before_upload=True
)

# 2. Append Data
uploader.upload_dataframe_to_sheet(
    dataframe=df,
    spreadsheet_id="1abc...",
    worksheet_name="HistoryLog",
    upload_start_cell="APPEND"
)

# 3. Custom Layout Upload
layout = {
    'A': 'Name',
    'C': 'Role' # Column B will be left empty
}
uploader.upload_dataframe_to_sheet(
    dataframe=df,
    spreadsheet_id="1abc...",
    worksheet_name="FormattedView",
    gsheet_layout_map=layout
)

# 4. Selective Column Update
# Update only Column E with 'Status' data, starting from row 2
status_map = {'E': 'Status'}
uploader.update_selective_columns(
    dataframe=df,
    spreadsheet_id="1abc...",
    worksheet_name="Orders",
    gsheet_layout_map=status_map,
    start_row=2
)
```
