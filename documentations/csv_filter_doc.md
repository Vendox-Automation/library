# CSVFilter Documentation

## Table of Contents
- [How to Use in Your Project](#how-to-use-in-your-project)
  - [Quick Start Guide](#quick-start-guide)
- [Overview](#overview)
- [Class: CSVFilter](#class-csvfilter)
  - [Initialization](#initialization)
  - [Methods](#methods)
    - [apply_filters](#apply_filters)
  - [Private Helper Methods](#private-helper-methods)
- [Usage Example](#usage-example)

## How to Use in Your Project

The `CSVFilter` is your go-to tool for cleaning and transforming CSV data before it gets used or uploaded. It works by applying a sequence of rules that you define.

### Quick Start Guide

1.  **Import the Class**:
    ```python
    from functions.csv_filter import CSVFilter
    ```

2.  **Initialize**:
    Load your data from a file path or an existing Pandas DataFrame.
    ```python
    # From a file
    my_filter = CSVFilter("path/to/my_data.csv")
    
    # OR from a DataFrame
    my_filter = CSVFilter(existing_dataframe)
    ```

3.  **Define Your Rules**:
    Create a dictionary specifying what you want to do.
    ```python
    my_rules = {
        'columns_to_remove': ['unused_col_1', 'sensitive_data'],
        'filter_criteria': {
            'status': ['EXACT: Active'],      # Keep only 'Active' status
            'email': ['CONTAINS: @company.com'] # Keep only company emails
        },
        'fill_na_value': 'Unknown'            # Replace missing values
    }
    ```

4.  **Set the Order**:
    Tell the filter in what order to apply these rules.
    ```python
    my_order = ['drop_cols', 'filter_rows', 'handle_na']
    ```

5.  **Run It**:
    ```python
    cleaned_df = my_filter.apply_filters(my_rules, my_order)
    ```

---

## Overview
The `CSVFilter` class is a reusable, sequence-configurable module designed for cleaning and transforming CSV data using the Pandas library. It allows users to define a series of operations such as renaming columns, dropping columns or rows, filtering based on criteria, performing conditional math, and handling missing values.

## Class: `CSVFilter`

### Initialization
```python
def __init__(self, input_source: Union[str, pd.DataFrame])
```
Initializes the filter by loading the data into a Pandas DataFrame.
- **Parameters:**
  - `input_source`: Can be a string (file path to CSV) or a `pd.DataFrame`.
- **Raises:**
  - `FileNotFoundError`: If the input is a string and the file does not exist.
  - `TypeError`: If the input is neither a string nor a DataFrame.

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
    - `'filter_rows'`: Applies complex filtering criteria (e.g., CONTAINS, EXACT, >, <).
    - `'handle_na'`: Fills NaN/Null values.
    - `'conditional_math'`: Applies arithmetic operations based on conditions.
    - `'split'`: Splits a column into multiple columns.
    - `'drop_indices'`: Drops rows by index.
- **Returns:**
  - `pd.DataFrame`: The cleaned and filtered DataFrame.

### Private Helper Methods
These methods are used internally by `apply_filters` but define the logic for each operation type.

- **`_apply_renames(self, rename_map: Dict[str, str])`**: Renames columns based on a mapping dictionary.
- **`_drop_columns(self, columns_to_remove: List[str])`**: Drops specified columns from the DataFrame.
- **`_drop_rows_by_value(self, rows_to_remove_by_value: Dict[str, Any])`**: Removes rows where a column matches a specific value or list of values. Supports `None` to match blanks/NaNs.
- **`_apply_filtering_criteria(self, filter_criteria: Dict[str, Any])`**: Applies complex filtering logic. Supports:
  - `CONTAINS:` for partial string matching.
  - `EXACT:` for exact string matching.
  - Comparison operators (`>`, `<`, `>=`, `<=`) for numeric comparisons.
  - List/Tuple for `IN` clauses.
  - Exact value matches (default if no operator specified).
- **`_handle_missing_values(self, fill_na_value: Any)`**: Fills missing values (NaN/Null) with a specified value.
- **`_apply_multiplier_math(self, math_rules: List[Dict[str, Any]])`**: Applies conditional arithmetic.
  - Example Rule: `{'target': 'charge', 'source': 'amount', 'multiplier': 0.1, 'trigger_values': [0, None]}`
  - This would set `charge = amount * 0.1` wherever `charge` is 0 or Empty.
- **`_split_column(self, split_rules: Dict[str, Any])`**: Splits 1 column into 2 columns.
  - Example Rule: `{'target': 'To Address Label', 'delimiter': '/', 'new_headers': ['Label', 'Order ID']}`
- **`_drop_row_indices(self, indices: List[int])`**: Drops rows by their 0-based index.

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
    "filter_criteria": {
        "Age": ">18", 
        "Email": "CONTAINS:@gmail.com",
        "Category": "EXACT:VIP"
    },
    "fill_na_value": "N/A",
    "math_rules": [
        {
            "target": "Tax",
            "source": "Price",
            "multiplier": 0.05,
            "trigger_values": [0, None] # Calculate tax if it's missing or 0
        }
    ],
    'split_rules': {'target': '商户单号', 
                    'delimiter': '_', 
                    'new_headers': ['Prefix', 'Order ID']},
    'indices_to_drop': [0], 
}

# Define Order
order = ["rename", "drop_cols", "drop_rows", "filter_rows", "conditional_math", "handle_na", "split", "drop_indices"]

# Execute
cleaned_df = filter_tool.apply_filters(rules, order)
```