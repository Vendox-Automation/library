import numpy as np
import pandas as pd
from typing import List, Dict, Any, Union

class CSVFilter:
    """
    A reusable, sequence-configurable module for cleaning and transforming CSV data.
    """

    def __init__(self, csv_file_path: str):
        """
        Initializes the filter by loading the CSV data into a Pandas DataFrame.
        """
        print(f"Loading data from: {csv_file_path}")
        try:
            self.df = pd.read_csv(csv_file_path, low_memory=False)
            self.initial_rows = len(self.df)
            print(f"Initial row count: {self.initial_rows}")
        except FileNotFoundError:
            raise FileNotFoundError(f"Input CSV file not found at: {csv_file_path}")
        except Exception as e:
            print(f"Error loading CSV: {e}")
            raise
            
    # --- PRIVATE HELPER METHODS FOR EACH OPERATION ---
    def _apply_renames(self, rename_map: Dict[str, str]):
        """Helper for column renaming."""
        print(f"-> Applying Column Renames: {rename_map}")
        self.df.rename(columns=rename_map, inplace=True)
        
    def _drop_columns(self, columns_to_remove: List[str]):
        """Helper for column removal."""
        valid_cols = [col for col in columns_to_remove if col in self.df.columns]
        invalid_cols = [col for col in columns_to_remove if col not in self.df.columns]
        
        if invalid_cols:
            print(f"-> Warning: Columns not found and skipped during removal: {invalid_cols}")
        
        if valid_cols:
            print(f"-> Removing Columns: {valid_cols}")
            self.df.drop(columns=valid_cols, inplace=True)

    def _drop_rows_by_value(self, rows_to_remove_by_value: Dict[str, Any]):
        """
        Helper for removing rows based on an exact value or list of values.
        Accepts: {'column_name': single_value} or {'column_name': [value_1, value_2, None]}
        The value 'None' is treated specially to match NaN, Null, and empty strings.
        """
        print(f"-> Removing Rows by Value/List: {rows_to_remove_by_value}")
        initial_count = len(self.df)
        
        # Initialize a mask where no rows are marked for removal yet
        mask = pd.Series([False] * len(self.df))
        
        for column, values_to_remove in rows_to_remove_by_value.items():
            if column not in self.df.columns:
                print(f"-> Warning: Removal column '{column}' not found.")
                continue

            # Convert single value into a list for consistent processing
            if not isinstance(values_to_remove, list):
                values_to_remove = [values_to_remove]
            
            # Temporary mask for the current column's criteria
            column_mask = pd.Series([False] * len(self.df), index=self.df.index)
            
            # Iterate through each specific value or the special None case
            for value in values_to_remove:
                
                # --- Special Case: None for matching all blanks (NaN/empty strings) ---
                if value is None:
                    # Clean the series: strip whitespace and replace empty strings with NaN
                    series = self.df[column]
                    if series.dtype == object:
                        series = series.str.strip().replace('', np.nan)
                    
                    # Rows where the value is NaN/Null are marked True (for removal)
                    blank_mask = series.isna() 
                    column_mask |= blank_mask
                    
                # --- Standard Case: Exact value match ---
                else:
                    exact_match_mask = (self.df[column] == value)
                    column_mask |= exact_match_mask

            # Use OR (|) logic to combine the current column's removals with the overall mask
            mask |= column_mask
        
        # Apply the inverse mask: Keep rows where the mask is False (i.e., NOT the ones we want to remove)
        self.df = self.df[~mask]
        
        # Reset the index after dropping rows (critical for preventing Unalignable Series error)
        self.df.reset_index(drop=True, inplace=True)
        
        print(f"-> Rows removed (by value/list): {initial_count - len(self.df)}")

    def _apply_filtering_criteria(self, filter_criteria: Dict[str, Any]):
        """
        Helper for complex row filtering (IN, CONTAINS, >, <, etc.).
        
        If a column has a single criterion, it's applied directly.
        If a column has a list of criteria (e.g., ['CONTAINS: @gmail', '>100']), 
        it applies OR logic within that column's mask.
        All column masks are combined using AND logic.
        """
        print(f"-> Applying Complex Filtering Criteria: {filter_criteria}")
        initial_count = len(self.df)
        
        # 1. Initialize the master mask to True, aligned to the current DataFrame index.
        combined_mask = pd.Series(True, index=self.df.index)
        
        # Iterate through each column criterion (Inter-column AND logic)
        for column, criterion in filter_criteria.items():
            if column not in self.df.columns:
                print(f"-> Warning: Filter column '{column}' not found. Skipping filter.")
                continue
            
            # 2. Prepare for Intra-column OR logic.
            # Ensure criterion is a list, even if it's a single item, for consistent looping.
            criteria_list = criterion if isinstance(criterion, list) else [criterion]
            
            # Initialize the mask for this specific column to False (no rows match yet)
            column_mask = pd.Series(False, index=self.df.index)

            # Iterate through each rule defined for the current column (Intra-column OR logic)
            for single_criterion in criteria_list:
                temp_mask = None # Mask for the specific rule

                # --- A. Handling CONTAINS operator ---
                if isinstance(single_criterion, str) and single_criterion.upper().startswith('CONTAINS:'):
                    search_string = single_criterion[len('CONTAINS:'):].strip()
                    series = self.df[column].astype(str)
                    # na=False ensures null/NaN values are not included in the match
                    temp_mask = series.str.contains(search_string, case=False, na=False)
                    
                # --- B. Handling comparison operators (>, <, etc.) ---
                elif isinstance(single_criterion, str) and any(op in single_criterion for op in ['>', '<', '>=', '<=']):
                    op = single_criterion[0:2] if single_criterion[1] == '=' else single_criterion[0]
                    value = single_criterion[len(op):].strip()
                    
                    # Convert column to numeric, coercing non-numeric values to NaN
                    series = pd.to_numeric(self.df[column], errors='coerce')

                    if op == '>':
                        temp_mask = (series > float(value))
                    elif op == '<':
                        temp_mask = (series < float(value))
                    elif op == '>=':
                        temp_mask = (series >= float(value))
                    elif op == '<=':
                        temp_mask = (series <= float(value))
                    else:
                        print(f"-> Warning: Unsupported operator '{op}' for column '{column}'. Skipping criterion.")
                        continue # Skip to next criterion

                # --- C. Handling standard list/IN clause ---
                elif isinstance(single_criterion, (list, tuple)):
                    temp_mask = self.df[column].isin(single_criterion)

                # --- D. Handling exact string/value match ---
                else:
                    temp_mask = (self.df[column] == single_criterion)
                    
                # Use OR (|) to combine masks for the same column
                if temp_mask is not None:
                    column_mask |= temp_mask

            # 3. Use AND (&) to combine the column's mask with the overall master mask
            combined_mask &= column_mask 

        # Apply the combined filter: keep only rows where the mask is True
        self.df = self.df[combined_mask]
        
        print(f"-> Rows removed (by criteria): {initial_count - len(self.df)}")
        return self.df
        
    def _handle_missing_values(self, fill_na_value: Any):
        """Helper for filling NaN/Null values."""
        if fill_na_value is not None:
            print(f"-> Replacing NaN/Null values with: '{fill_na_value}'")
            self.df.fillna(fill_na_value, inplace=True)

    # --- PRIMARY EXECUTION METHOD ---

    def apply_filters(self, 
                      filter_rules: Dict[str, Any],
                      execution_order: List[str]) -> pd.DataFrame:
        """
        Applies a sequence of cleaning and filtering operations based on a specified order.

        Args:
            filter_rules: A dictionary containing all transformation rules (renames, filters, drops).
            execution_order: A list of strings defining the precise order of operations.
                             Valid keys: 'rename', 'drop_cols', 'drop_rows', 'filter_rows', 'handle_na'.

        Returns:
            The cleaned and filtered Pandas DataFrame.
        """
        
        # Define the map between the user-defined string keys and the internal methods/parameters
        OPERATION_MAP = {
            'rename': (self._apply_renames, 'rename_columns'),
            'drop_cols': (self._drop_columns, 'columns_to_remove'),
            'drop_rows': (self._drop_rows_by_value, 'rows_to_remove_by_value'),
            'filter_rows': (self._apply_filtering_criteria, 'filter_criteria'),
            'handle_na': (self._handle_missing_values, 'fill_na_value'),
        }

        # Iterate through the requested order
        for step_name in execution_order:
            if step_name not in OPERATION_MAP:
                print(f"Warning: Unknown operation '{step_name}' requested in execution_order. Skipping.")
                continue

            method, param_key = OPERATION_MAP[step_name]
            params = filter_rules.get(param_key)

            # Only execute the step if the user provided relevant parameters
            if params is not None and (isinstance(params, (list, dict)) and len(params) > 0) or step_name == 'handle_na':
                try:
                    method(params)
                except Exception as e:
                    # Provide helpful context if an operation fails
                    print(f"🛑 Error during step '{step_name}' using parameter '{param_key}': {e}")
                    raise
            else:
                print(f"-> Skipping '{step_name}': No rules provided.")

        
        final_rows = len(self.df)
        print(f"\nFiltering sequence complete. Final row count: {final_rows}")
        
        return self.df