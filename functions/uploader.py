import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os
from typing import List, Dict, Any, Union

class GoogleSheetUploader:
    """
    A reusable module to upload a Pandas DataFrame's contents to a specified
    Google Sheet and Worksheet using a Service Account.
    """
    
    # Define the required scopes for the Service Account
    SCOPES = [
        'https://www.googleapis.com/auth/spreadsheets', # For Sheets API
        'https://www.googleapis.com/auth/drive'         # For Drive API
    ]

    def __init__(self, credentials_file_path: str):
        """
        Initializes the uploader by authenticating with Google.

        Args:
            credentials_file_path: The path to the Service Account JSON key file.
        """
        if not os.path.exists(credentials_file_path):
            raise FileNotFoundError(f"Credentials file not found at: {credentials_file_path}")
            
        print(f"Authenticating with Google using {credentials_file_path}...")
        
        # Authenticate using the Service Account credentials
        self.creds = ServiceAccountCredentials.from_json_keyfile_name(
            credentials_file_path, self.SCOPES
        )
        self.client = gspread.authorize(self.creds)
        print("Authentication successful.")


    # --- MODIFIED/NEW HELPER METHOD ---
    # Renamed the old method to reflect its new, cleaner role
    def _prepare_data_for_gspread(self, 
                                    df: pd.DataFrame, 
                                    include_header: bool = True) -> List[List[Any]]: # <-- NEW PARAMETER
        """
        Converts a Pandas DataFrame into the list-of-lists format required by gspread.
        """
        
        df = df.fillna('')
        data_rows = df.values.tolist()
        
        if include_header:
            # Get the header row and prepend it
            header = [str(col) for col in df.columns.tolist()]
            prepared_data = [header] + data_rows
            print(f"Data prepared with header. Total rows: {len(prepared_data)}")
        else:
            # Only return the data rows
            prepared_data = data_rows
            print(f"Data prepared without header. Total rows: {len(prepared_data)}")
            
        return prepared_data

    # --- New Helper Function: Maps the DataFrame to the GSheet Layout ---
    def _format_dataframe_to_gsheet_layout(self, 
                                            df: pd.DataFrame, 
                                            layout_map: Dict[str, Union[str, None]]) -> pd.DataFrame:
        """
        Creates a new DataFrame structure where columns are ordered and spaced
        according to the layout_map.
        
        Args:
            df: The cleaned source DataFrame.
            layout_map: A dict mapping GSheet column letters (A, B, C) to 
                        DataFrame column names (or None for a gap).
                        
        Returns:
            A new DataFrame with columns named by their GSheet column letters (A, B, C...).
        """
        print("-> Formatting DataFrame to Google Sheet Layout...")
        
        # 1. Sort the layout map by GSheet column letter (A, B, C, ...)
        sorted_layout = sorted(layout_map.items(), key=lambda item: item[0])
        
        # 2. Create the new, structured DataFrame
        formatted_data = {}
        
        # 3. Populate the new data structure column by column
        for gsheet_col, df_col_name in sorted_layout:
            if df_col_name is None:
                # Create a gap column: Fill all rows with empty strings
                formatted_data[gsheet_col] = [''] * len(df)
            elif df_col_name in df.columns:
                # Map the clean DF column data
                # Ensure data is converted to list/array format for insertion
                formatted_data[gsheet_col] = df[df_col_name].tolist() 
            else:
                print(f"-> Warning: DF column '{df_col_name}' not found. Creating empty column for GSheet '{gsheet_col}'.")
                formatted_data[gsheet_col] = [''] * len(df)
                
        # Create the final DataFrame from the structured data
        formatted_df = pd.DataFrame(formatted_data)
        
        print(f"-> Layout formatted from {len(df.columns)} columns to {len(formatted_df.columns)} GSheet columns.")
        return formatted_df

    # --- NEW PRIMARY UPLOAD METHOD ---
    def upload_dataframe_to_sheet(self, 
                                dataframe: pd.DataFrame, 
                                spreadsheet_name: str, 
                                worksheet_name: str = "Sheet1",
                                clear_before_upload: bool = True,
                                upload_start_cell: str = "A1", # Handles Scenario B
                                include_header: bool = True,
                                gsheet_layout_map: Dict[str, Union[str, None]] = None): # Handles Scenario C
        """
        The main method to upload a cleaned Pandas DataFrame.

        Args:
            dataframe: The Pandas DataFrame containing the data to upload.
            spreadsheet_name: The name of the Google Sheet.
            worksheet_name: The specific tab name. Defaults to 'Sheet1'.
            clear_before_upload: If True, clears the sheet contents before uploading.
        """

        # 0. Check if a layout map was provided and apply it
        if gsheet_layout_map:
            dataframe = self._format_dataframe_to_gsheet_layout(dataframe, gsheet_layout_map)
        
        try:
        # 1. Prepare the data: PASS THE NEW FLAG
            data_to_upload = self._prepare_data_for_gspread(
                dataframe, 
                include_header=include_header 
            )
            
            # 2. Open the specified Google Spreadsheet
            print(f"Connecting to Google Sheet: '{spreadsheet_name}'...")
            spreadsheet = self.client.open(spreadsheet_name)
            
            # 3. Open the specified Worksheet (tab)
            worksheet = spreadsheet.worksheet(worksheet_name)
            
            # 4. Clear existing data (if requested)
            if clear_before_upload:
                print(f"Clearing existing data from worksheet: '{worksheet_name}'...")
                worksheet.clear()
            
            # 5. Upload the new data!
            print(f"Uploading data to Google Sheets starting at cell: {upload_start_cell}")
            worksheet.update(upload_start_cell, data_to_upload)
            
            print("✨ Upload complete!")
            print(f"Data uploaded to: {spreadsheet.url}")

        except gspread.WorksheetNotFound:
            print(f"Error: Worksheet '{worksheet_name}' not found in '{spreadsheet_name}'.")
        except gspread.SpreadsheetNotFound:
            print(f"Error: Spreadsheet '{spreadsheet_name}' not found. Check name and Service Account permissions.")
        except Exception as e:
            print(f"An unexpected error occurred during the upload process: {e}")

    # --- LEGACY/WRAPPER METHOD (OPTIONAL) ---
    # The old method now reads the CSV and calls the new primary method.
    def upload_csv_to_sheet(self, *args, **kwargs):
        """
        [DEPRECATED/LEGACY]: Uploads a CSV by first reading it into a DataFrame.
        It is recommended to use CSVFilter and upload_dataframe_to_sheet instead.
        """
        print("Warning: Using legacy 'upload_csv_to_sheet'. For complex pipelines, use CSVFilter first.")
        
        csv_file_path = kwargs.pop('csv_file_path')
        df = pd.read_csv(csv_file_path).fillna('') # Basic reading
        
        # Re-map the function arguments
        self.upload_dataframe_to_sheet(dataframe=df, **kwargs)