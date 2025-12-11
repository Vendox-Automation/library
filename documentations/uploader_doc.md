# GoogleSheetUploader Documentation

## Overview
The `GoogleSheetUploader` class is a reusable module designed to upload Pandas DataFrames to Google Sheets using a Service Account. It handles authentication and uploading to specific worksheets.

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
def upload_dataframe_to_sheet(self, dataframe: pd.DataFrame, spreadsheet_name: str, worksheet_name: str = "Sheet1", clear_before_upload: bool = True)
```
The main method to upload a Pandas DataFrame to a Google Sheet.

- **Parameters:**
  - `dataframe` (pd.DataFrame): The data to upload.
  - `spreadsheet_name` (str): The name of the Google Sheet file.
  - `worksheet_name` (str): The specific tab name to upload to. Defaults to "Sheet1".
  - `clear_before_upload` (bool): If `True`, clears the worksheet content before uploading. Defaults to `True`.

#### `upload_csv_to_sheet` (Deprecated)
```python
def upload_csv_to_sheet(self, *args, **kwargs)
```
Legacy method that reads a CSV file and uploads it. It is recommended to use `CSVFilter` to load/clean data and then use `upload_dataframe_to_sheet`.

### Internal Helper Methods

- **`_prepare_data_for_gspread(self, df: pd.DataFrame) -> List[List[Any]]`**: Converts a Pandas DataFrame into a list of lists format required by the `gspread` library. It handles `NaN` values by converting them to empty strings.

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

# Upload
uploader.upload_dataframe_to_sheet(
    dataframe=df,
    spreadsheet_name="My Project Data",
    worksheet_name="TeamRoster",
    clear_before_upload=True
)
```
