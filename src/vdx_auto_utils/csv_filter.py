import numpy as np
import pandas as pd
import traceback
from typing import List, Dict, Any, Union

class CSVFilter:
    """
    A reusable, sequence-configurable module for cleaning and transforming CSV data.
    """

    def __init__(self, input_source):
        """
        Args:
            input_source: Can be a string (file path) or a pd.DataFrame.
        """
        if isinstance(input_source, pd.DataFrame):
            # Initializing directly from an in-memory DataFrame
            print("🚀 Initializing CSVFilter with provided DataFrame.")
            self.df = input_source
        elif isinstance(input_source, str):
            # Initializing from a local CSV file path
            print(f"📂 Loading data from path: {input_source}")
            excel_extensions = ('.xlsx', '.xls', '.xlt', '.xltx', '.xlsm')
            try:
                if input_source.lower.endswith(excel_extensions):
                    self.df = pd.read_excel(input_source)
                elif input_source.lower.endswith(('.csv')):
                    self.read_csv(input_source, low_memory=False)
            except FileNotFoundError:
                traceback.print_exc()
                raise FileNotFoundError(f"Input CSV file not found at: {input_source}")
            except Exception as e:
                print(f"Error loading CSV: {e}")
                traceback.print_exc()
                raise
        else:
            raise TypeError("Input must be either a file path (string) or a Pandas DataFrame.")

        self.initial_rows = len(self.df)
            
    def _apply_renames(self, rename_map: Dict[str, str]):
        """
        Helper for column renaming.
        Args:
            rename_map: Dictionary mapping old column names to new names.
        """
        print(f"-> Applying Column Renames: {rename_map}")
        self.df.rename(columns=rename_map, inplace=True)
        
    def _drop_columns(self, columns_to_remove: List[str]):
        """
        Helper for column removal.
        Args:
            columns_to_remove: List of column names to drop.
        """
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
        Args:
            rows_to_remove_by_value: Dictionary where keys are column names and values are
                                        either a single value or a list of values to remove.
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
                
                # None for matching all blanks (NaN/empty strings)
                if value is None:
                    # Clean the series: strip whitespace and replace empty strings with NaN
                    series = self.df[column]
                    if series.dtype == object:
                        series = series.str.strip().replace('', np.nan)
                    
                    # Rows where the value is NaN/Null are marked True (for removal)
                    blank_mask = series.isna() 
                    column_mask |= blank_mask
                    
                # Exact value match
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

        Args:
            filter_criteria: Dictionary where keys are column names and values are either
                                a single criterion or a list of criteria.
        """
        print(f"-> Applying Complex Filtering Criteria: {filter_criteria}")
        initial_count = len(self.df)
        
        # Initialize the master mask to True, aligned to the current DataFrame index.
        combined_mask = pd.Series(True, index=self.df.index)
        
        # Iterate through each column criterion (Inter-column AND logic)
        for column, criterion in filter_criteria.items():
            if column not in self.df.columns:
                print(f"-> Warning: Filter column '{column}' not found. Skipping filter.")
                continue
            
            # Prepare for Intra-column OR logic.
            criteria_list = criterion if isinstance(criterion, list) else [criterion]
            
            # Initialize the mask for this specific column to False (no rows match yet)
            column_mask = pd.Series(False, index=self.df.index)

            # Iterate through each rule defined for the current column (Intra-column OR logic)
            for single_criterion in criteria_list:
                temp_mask = None # Mask for the specific rule

                # Handling CONTAINS operator
                if isinstance(single_criterion, str) and single_criterion.upper().startswith('CONTAINS:'):
                    search_string = single_criterion[len('CONTAINS:'):].strip()
                    series = self.df[column].astype(str)
                    # na=False ensures null/NaN values are not included in the match
                    temp_mask = series.str.contains(search_string, case=False, na=False)
                
                # Handling EXACT operator
                elif isinstance(single_criterion, str) and single_criterion.upper().startswith('EXACT:'):
                    exact_value = single_criterion[len('EXACT:'):].strip()
                    # We compare against the string version of the column
                    temp_mask = (self.df[column].astype(str) == exact_value)
                    
                # Handling comparison operators (>, <, etc.)
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

                # Handling standard list/IN clause
                elif isinstance(single_criterion, (list, tuple)):
                    temp_mask = self.df[column].isin(single_criterion)

                # Handling exact string/value match
                else:
                    temp_mask = (self.df[column] == single_criterion)
                    
                # Use OR (|) to combine masks for the same column
                if temp_mask is not None:
                    column_mask |= temp_mask

            # Use AND (&) to combine the column's mask with the overall master mask
            combined_mask &= column_mask 

        # Apply the combined filter: keep only rows where the mask is True
        self.df = self.df[combined_mask].copy()
        
        print(f"-> Rows removed (by criteria): {initial_count - len(self.df)}")
        return self.df
        
    def _handle_missing_values(self, fill_na_value: Any):
        """
        Helper for filling NaN/Null values.
        Args:
            fill_na_value: The value to replace NaN/Null entries with.
        """
        if fill_na_value is not None:
            print(f"-> Replacing NaN/Null values with: '{fill_na_value}'")
            self.df.fillna(fill_na_value, inplace=True)

    def _apply_multiplier_math(self, math_rules: List[Dict[str, Any]]):
        """
        Applies conditional arithmetic. 
        Example Rule: {'target': 'charge', 'source': 'amount', 'multiplier': 0.1, 'trigger_values': [0, None, '']}
        Meaning: If 'charge' is 0 or Empty, set 'charge' = 'amount' * 0.1
        Args:
            math_rules: List of dictionaries defining the math operations.
        """
        print(f"-> Applying Conditional Math Rules: {math_rules}")

        for rule in math_rules:
            target = rule.get('target')
            source = rule.get('source')
            multiplier = rule.get('multiplier', 1.0)
            triggers = rule.get('trigger_values', [0, None, ''])

            if target not in self.df.columns or source not in self.df.columns:
                print(f"Warning: Columns {target} or {source} not found. Skipping math rule.")
                continue

            if target not in self.df.columns:
                print(f"   -> Creating new target column: '{target}'")
                self.df[target] = 0.0
            
            # 1. Clean data to ensure we can do math
            self.df[target] = pd.to_numeric(self.df[target], errors='coerce')
            self.df[source] = pd.to_numeric(self.df[source], errors='coerce')

            # 2. Build the Mask 
            if triggers == '*' or (isinstance(triggers, list) and '*' in triggers):
                print(f"   ⚡ Wildcard detected. Applying to ALL rows.")
                mask = pd.Series(True, index=self.df.index)
            else:
                # Standard conditional logic
                mask = pd.Series(False, index=self.df.index)
                for val in triggers:
                    if val is None or val == '':
                        mask |= self.df[target].isna()
                    else:
                        mask |= (self.df[target] == val)

            # 3. Apply the Math
            rows_affected = mask.sum()
            if rows_affected > 0:
                self.df.loc[mask, target] = self.df.loc[mask, source] * multiplier
                print(f"   -> Updated {rows_affected} rows in '{target}' using '{source}' * {multiplier}") 
    
    def _split_column(self, split_rules: Union[Dict[str, Any], List[Dict[str, Any]]]):
        """
        Helper for splitting a column into two new columns. Now supports multiple splits.
        Expects: {
            'target': 'original_col', 
            'delimiter': '-', 
            'new_headers': ['Col1', 'Col2']
        }
        Args:
            split_rules: Dictionary defining the split operation.
        """
        # 1. Handle List of Rules (Recursive)
        if isinstance(split_rules, list):
            print(f"-> Processing sequence of {len(split_rules)} split rules...")
            for rule in split_rules:
                self._split_column(rule) # Recursive call for each rule in order
            return

        # 2. Standard Logic for Single Rule
        target = split_rules.get('target')
        delimiter = split_rules.get('delimiter')
        # If new_headers is missing, auto-generate specific names
        new_headers = split_rules.get('new_headers', [f"{target}_1", f"{target}_2"])

        if target not in self.df.columns:
            print(f"-> Warning: Column '{target}' not found for splitting.")
            return

        print(f"-> Splitting column '{target}' by '{delimiter}' into {new_headers}")

        try:
            # Expand=True turns the result into a DataFrame with two columns
            split_data = self.df[target].astype(str).str.split(delimiter, n=1, expand=True)

            # Assign to new headers safely
            self.df.loc[:, new_headers[0]] = split_data[0]
            # Handle cases where the delimiter wasn't found (no second part)
            if len(split_data.columns) > 1:
                self.df.loc[:, new_headers[1]] = split_data[1]
            else:
                self.df.loc[:, new_headers[1]] = "" # Fill with empty string if no split occurred
            
            # Remove original column 
            self.df.drop(columns=[target], inplace=True)

        except Exception as e:
            print(f"🛑 Error splitting column '{target}': {e}")

    def _drop_row_indices(self, indices: List[int]):
        """
        Helper to drop rows by their index (0-based).
        Args:
            indices: List of integer row indices to drop.
        """
        print(f"-> Dropping rows at indices: {indices}")
        try:
            self.df.drop(indices, inplace=True)
            self.df.reset_index(drop=True, inplace=True)
        except Exception as e:
            print(f"⚠️ Warning: Could not drop rows {indices}: {e}")

    # PRIMARY EXECUTION METHOD
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
            'conditional_math': (self._apply_multiplier_math, 'math_rules'),
            'split': (self._split_column, 'split_rules'),
            'drop_indices': (self._drop_row_indices, 'indices_to_drop')
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
                    traceback.print_exc()
                    raise
            else:
                print(f"-> Skipping '{step_name}': No rules provided.")

        
        final_rows = len(self.df)
        print(f"\nFiltering sequence complete. Final row count: {final_rows}")
        
        return self.df