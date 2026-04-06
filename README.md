# Library

This project provides a robust, reusable automation pipeline for extracting data from CSV files, applying configurable filters and transformations, and uploading the cleaned data to Google Sheets.

It is designed to be modular and easily adaptable for various automation tasks involving data processing and reporting.

## Table of Contents
- [Features](#features)
- [Installation](#installation)
- [Prerequisites](#prerequisites)
- [Project Structure](#project-structure)
- [Usage](#usage)
  - [Using the Modules](#using-the-modules)
- [Configuration](#configuration)

## Features

- **Configurable Filtering**: Define rules to drop columns, filter rows by value, apply complex criteria (e.g., "contains", ">", "<"), and handle missing values.
- **Google Sheets Integration**: Seamlessly uploads processed data to a specified Google Sheet and Worksheet.
- **Google Drive Management**: Navigate folders, copy files, and read CSVs directly from Google Drive using `DriveManager`.
- **Data Utilities**: Helper functions for common DataFrame operations (e.g., splitting data) in `data_utils`.
- **Service Account Failover**: Rotate Google service accounts automatically when quota limits are hit using `ServiceAccountManager`.
- **Report Downloader**: Log in to JSON APIs and download reports (GET/POST) to CSV/JSON via `run_login_and_report`.
- **Modular Design**: Separate components for filtering (`CSVFilter`), uploading (`GoogleSheetUploader`), and Drive interactions allow for easy reuse.
- **Execution Control**: Define the exact order of operations for data processing.

## Installation

To install the package, use pip with the git repository URL:

```bash
pip install git+https://github.com/Vendox-Automation/dictionary
```

## Prerequisites

Before running the project, ensure you have the following:

1.  **Python 3.9+** installed.
2.  **Google Cloud Service Account**:
    *   Create a Service Account in the Google Cloud Console.
    *   Download the JSON key file.
    *   Enable the **Google Sheets API** and **Google Drive API**.
    *   **Share your target Google Sheet** with the email address of the Service Account (found in the JSON file).

## Project Structure

```
.
├── src/
│   └── vdx_auto_utils/
│       ├── __init__.py
│       ├── csv_filter.py     # Logic for filtering and cleaning CSV data
│       ├── uploader.py       # Logic for uploading data to Google Sheets
│       ├── google_drive.py   # Logic for Google Drive interactions
│       ├── service_account_manager.py # Service-account failover helper
│       ├── report_downloader.py # HTTP login + report download to CSV/JSON
│       └── data_utils.py     # Helper functions for data manipulation
├── documentation/            # Project documentation
├── pyproject.toml            # Package configuration
└── README.md                 # This file
```

## Usage

### Using the Modules

You can import `CSVFilter`, `GoogleSheetUploader`, `DriveManager`, and `split_dataframe` into your own scripts:

```python
from vdx_auto_utils.csv_filter import CSVFilter
from vdx_auto_utils.uploader import GoogleSheetUploader
from vdx_auto_utils.google_drive import DriveManager
from vdx_auto_utils.data_utils import split_dataframe

# 1. Filter Data
my_filter = CSVFilter("path/to/my_data.csv")
# ... define rules and order ...
cleaned_df = my_filter.apply_filters(my_rules, my_order)

# 2. Upload Data
uploader = GoogleSheetUploader("path/to/credentials.json")
uploader.upload_dataframe_to_sheet(cleaned_df, spreadsheet_id="your_sheet_id")

# 3. Manage Google Drive
drive = DriveManager("path/to/credentials.json")
df = drive.read_csv_from_drive("file_id_here")

# 4. Split Data
active_df, inactive_df = split_dataframe(df, df['status'] == 'Active')
```

## Configuration

The core configuration is typically handled in your main script (e.g., `main.py`) by creating a configuration class or dictionary that defines:

*   **Credentials**: Path to your Service Account JSON key.
*   **Filter Rules**: Dictionary controlling how data is processed.
*   **Execution Order**: Sequence of operations.
