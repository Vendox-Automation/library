import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os
from typing import List, Dict, Any

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
    def _prepare_data_for_gspread(self, df: pd.DataFrame) -> List[List[Any]]:
        """Converts a Pandas DataFrame into the list-of-lists format required by gspread."""
        
        # 1. Convert any NaN values to empty strings for GSheets compatibility
        # (This is a safety measure, though the filter should ideally handle it)
        df = df.fillna('')
        
        # 2. Get the header row (list of column names)
        header = [str(col) for col in df.columns.tolist()]
        
        # 3. Get the data rows (list of lists)
        data_rows = df.values.tolist()
        
        # Combine header and data
        prepared_data = [header] + data_rows
        
        print(f"Data prepared for upload. Total rows (incl. header): {len(prepared_data)}")
        return prepared_data

    # --- NEW PRIMARY UPLOAD METHOD ---
    def upload_dataframe_to_sheet(self, 
                                  dataframe: pd.DataFrame, 
                                  spreadsheet_name: str, 
                                  worksheet_name: str = "Sheet1",
                                  clear_before_upload: bool = True):
        """
        The main method to upload a cleaned Pandas DataFrame.

        Args:
            dataframe: The Pandas DataFrame containing the data to upload.
            spreadsheet_name: The name of the Google Sheet.
            worksheet_name: The specific tab name. Defaults to 'Sheet1'.
            clear_before_upload: If True, clears the sheet contents before uploading.
        """
        try:
            # 1. Prepare the data from the DataFrame
            data_to_upload = self._prepare_data_for_gspread(dataframe)
            
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
            print("Uploading data to Google Sheets...")
            # gspread's update method is efficient for large bulk uploads
            worksheet.update('A1', data_to_upload)
            
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