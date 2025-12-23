# DataUtils Documentation

## Table of Contents
- [How to Use in Your Project](#how-to-use-in-your-project)
  - [Quick Start Guide](#quick-start-guide)
- [Overview](#overview)
- [Functions](#functions)
  - [split_dataframe](#split_dataframe)
- [Usage Example](#usage-example)

## How to Use in Your Project

The `data_utils` module provides helper functions for common DataFrame operations, such as splitting data based on conditions.

### Quick Start Guide

1.  **Import the Function**:
    ```python
    from functions.data_utils import split_dataframe
    ```

2.  **Create a Mask**:
    Define a boolean condition for your DataFrame.
    ```python
    mask = df['status'] == 'Active'
    ```

3.  **Split the Data**:
    Get two DataFrames: one matching the condition, and one with the rest.
    ```python
    active_df, inactive_df = split_dataframe(df, mask)
    ```

---

## Overview
The `data_utils` module contains utility functions for data manipulation using Pandas. It is designed to simplify common tasks like splitting datasets.

## Functions

### `split_dataframe`
```python
def split_dataframe(df: pd.DataFrame, mask: pd.Series) -> Tuple[pd.DataFrame, pd.DataFrame]
```
Splits a DataFrame into two based on a boolean mask.

- **Parameters:**
  - `df` (pd.DataFrame): The source DataFrame.
  - `mask` (pd.Series): A boolean Series aligned with the DataFrame's index.
- **Returns:**
  - `Tuple[pd.DataFrame, pd.DataFrame]`: A tuple containing `(extracted_df, remaining_df)`.
    - `extracted_df`: Rows where the mask is `True`.
    - `remaining_df`: Rows where the mask is `False`.

## Usage Example
```python
from functions.data_utils import split_dataframe
import pandas as pd

# Sample Data
df = pd.DataFrame({
    'Name': ['Alice', 'Bob', 'Charlie'],
    'Age': [25, 30, 35]
})

# Create a mask for age > 28
mask = df['Age'] > 28

# Split the DataFrame
older_group, younger_group = split_dataframe(df, mask)

# older_group will contain Bob and Charlie
# younger_group will contain Alice
```
