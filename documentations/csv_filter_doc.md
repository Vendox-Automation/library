# CSVFilter Documentation

## Overview
The `CSVFilter` class is a reusable, sequence-configurable module designed for cleaning and transforming CSV data using the Pandas library. It allows users to define a series of operations such as renaming columns, dropping columns or rows, filtering based on criteria, and handling missing values.

## Class: `CSVFilter`

### Initialization
```python
def __init__(self, csv_file_path: str)
```
Initializes the filter by loading the CSV data into a Pandas DataFrame.
- **Parameters:**
  - `csv_file_path` (str): The file path to the input CSV file.
- **Raises:**
  - `FileNotFoundError`: If the CSV file does not exist.

### Methods

#### `apply_filters`
```python
def apply_filters(self, filter_rules: Dict[str, Any], execution_order: List[str]) -> pd.DataFrame
```
The primary execution method that applies a sequence of cleaning and filtering operations based on a specified order.

- **Parameters:**
  - `filter_rules` (Dict[str, Any]): A dictionary containing transformation rules. Keys map to specific operation parameters.
  - `execution_order` (List[str]): A list of strings defining the order of operations. Valid keys are:
    - `'rename'`: Renames columns.
    - `'drop_cols'`: Removes specified columns.
    - `'drop_rows'`: Removes rows based on specific values.
    - `'filter_rows'`: Applies complex filtering criteria (e.g., CONTAINS, >, <).
    - `'handle_na'`: Fills NaN/Null values.
- **Returns:**
  - `pd.DataFrame`: The cleaned and filtered DataFrame.

### Private Helper Methods
These methods are used internally by `apply_filters` but define the logic for each operation type.

- **`_apply_renames(self, rename_map: Dict[str, str])`**: Renames columns based on a mapping dictionary.
- **`_drop_columns(self, columns_to_remove: List[str])`**: Drops specified columns from the DataFrame.
- **`_drop_rows_by_value(self, rows_to_remove_by_value: Dict[str, Any])`**: Removes rows where a column matches a specific value or list of values. Supports `None` to match blanks/NaNs.
- **`_apply_filtering_criteria(self, filter_criteria: Dict[str, Any])`**: Applies complex filtering logic. Supports:
  - `CONTAINS:` for string matching.
  - Comparison operators (`>`, `<`, `>=`, `<=`).
  - List/Tuple for `IN` clauses.
  - Exact value matches.
- **`_handle_missing_values(self, fill_na_value: Any)`**: Fills missing values (NaN/Null) with a specified value.

## Usage Example
```python
from functions.csv_filter import CSVFilter

# Initialize
filter_tool = CSVFilter("data/input.csv")

# Define Rules
rules = {
    "rename_columns": {"OldName": "NewName"},
    "columns_to_remove": ["UnnecessaryCol"],
    "rows_to_remove_by_value": {"Status": ["Inactive", "Void"]},
    "filter_criteria": {"Age": ">18", "Email": "CONTAINS:@gmail.com"},
    "fill_na_value": "N/A"
}

# Define Order
order = ["rename", "drop_cols", "drop_rows", "filter_rows", "handle_na"]

# Execute
cleaned_df = filter_tool.apply_filters(rules, order)
```
