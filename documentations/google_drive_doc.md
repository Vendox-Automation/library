# GoogleDrive Documentation

## Table of Contents
- [How to Use in Your Project](#how-to-use-in-your-project)
  - [Quick Start Guide](#quick-start-guide)
- [Overview](#overview)
- [Class: DriveManager](#class-drivemanager)
  - [Initialization](#initialization)
  - [Methods](#methods)
    - [get_folder_id_by_name](#get_folder_id_by_name)
    - [navigate_path](#navigate_path)
    - [copy_file](#copy_file)
    - [find_files_by_keywords](#find_files_by_keywords)
    - [read_csv_from_drive](#read_csv_from_drive)
- [Usage Example](#usage-example)

## How to Use in Your Project

The `DriveManager` simplifies interactions with Google Drive, allowing you to navigate folders, copy files, and read CSVs directly into Pandas.

### Quick Start Guide

1.  **Import the Class**:
    ```python
    from functions.google_drive import DriveManager
    ```

2.  **Initialize**:
    Connect using your service account.
    ```python
    drive = DriveManager("path/to/credentials.json")
    ```

3.  **Navigate Folders**:
    Find a specific folder path.
    ```python
    folder_id = drive.navigate_path(root_id="root_folder_id", path_list=["2024", "December"])
    ```

4.  **Read Data**:
    Read a CSV file directly into a DataFrame.
    ```python
    df = drive.read_csv_from_drive("file_id_here")
    ```

---

## Overview
The `DriveManager` class is a reusable module for interacting with the Google Drive API. It handles authentication, navigation, file discovery, and reading data.

## Class: `DriveManager`

### Initialization
```python
def __init__(self, service_account_file: str, scopes: List[str] = None)
```
Initializes the DriveManager with service account credentials.
- **Parameters:**
  - `service_account_file` (str): Path to the service account JSON file.
  - `scopes` (List[str], optional): List of OAuth2 scopes. Defaults to `['https://www.googleapis.com/auth/drive']`.

### Methods

#### `get_folder_id_by_name`
```python
def get_folder_id_by_name(self, parent_id: str, target_name: str) -> Optional[str]
```
Finds a folder's ID by its name within a specific parent folder.
- **Returns:** The ID of the target folder if found, else `None`.

#### `navigate_path`
```python
def navigate_path(self, root_id: str, path_list: List[str]) -> Optional[str]
```
Navigates through a list of folder names starting from a root ID.
- **Parameters:**
  - `root_id`: The starting folder ID.
  - `path_list`: A list of folder names representing the path (e.g., `['Year', 'Month']`).
- **Returns:** The ID of the final folder if the path is valid, else `None`.

#### `copy_file`
```python
def copy_file(self, file_id: str, new_name: str, parent_id: str) -> Dict
```
Copies a file to a specific parent folder with a new name.
- **Returns:** The metadata of the copied file.

#### `find_files_by_keywords`
```python
def find_files_by_keywords(self, folder_id: str, keyword_map: Dict[str, str]) -> Dict[str, Optional[str]]
```
Maps files in a folder to keys based on keyword matching in filenames.
- **Parameters:**
  - `folder_id`: The ID of the folder to search within.
  - `keyword_map`: A dictionary mapping keys to filename keywords (e.g., `{'Report': 'Sales Report'}`).
- **Returns:** A dictionary mapping each key to the corresponding file ID.

#### `read_csv_from_drive`
```python
def read_csv_from_drive(self, file_id: str) -> Optional[pd.DataFrame]
```
Reads a CSV file directly from Google Drive into a Pandas DataFrame.
- **Returns:** A Pandas DataFrame containing the CSV data, or `None` if `file_id` is invalid.

## Usage Example
```python
from functions.google_drive import DriveManager

# Initialize
drive = DriveManager("credentials.json")

# 1. Navigate to a specific day folder
root_id = "0AFHOYy..."
path = ["2024", "12/2024", "23.12.2024"]
day_folder_id = drive.navigate_path(root_id, path)

if day_folder_id:
    # 2. Copy a template file to this folder
    drive.copy_file(
        file_id="template_id_123", 
        new_name="Daily Summary", 
        parent_id=day_folder_id
    )

    # 3. Find specific files
    files = drive.find_files_by_keywords(day_folder_id, {
        'Sales': 'Sales Data',
        'Inventory': 'Stock List'
    })

    # 4. Read the found files
    sales_df = drive.read_csv_from_drive(files['Sales'])
```
