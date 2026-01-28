import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os
import re 
import time
import socket
import traceback
from typing import List, Dict, Any, Union

# Prevent hanging forever
socket.setdefaulttimeout(60)

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

    # --- HELPER METHOD ---
    def _prepare_data_for_gspread(self, 
                                    df: pd.DataFrame, 
                                    include_header: bool = True) -> List[List[Any]]:
        """
        Converts a Pandas DataFrame into the list-of-lists format required by gspread.
        """
        
        df = df.fillna('')
        data_rows = df.values.tolist()
        
        if include_header:
            # Get the header row and prepend it
            header = [str(col) for col in df.columns.tolist()]
            prepared_data = [header] + data_rows
        else:
            prepared_data = data_rows
            
        print(f"-> Data prepared. Total rows: {len(prepared_data)}")    
        return prepared_data

    # --- HELPER: FORMATTING ---
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
        
        sorted_layout = sorted(layout_map.items(), key=lambda item: item[0])
        formatted_data = {}
        
        for gsheet_col, df_col_name in sorted_layout:
            if df_col_name is None:
                formatted_data[gsheet_col] = [''] * len(df)
            elif df_col_name in df.columns:
                formatted_data[gsheet_col] = df[df_col_name].tolist() 
            else:
                print(f"-> Warning: DF column '{df_col_name}' not found. Creating empty column for GSheet '{gsheet_col}'.")
                formatted_data[gsheet_col] = [''] * len(df)
                
        formatted_df = pd.DataFrame(formatted_data)
        print(f"-> Layout formatted from {len(df.columns)} columns to {len(formatted_df.columns)} GSheet columns.")
        return formatted_df

    # --- PRIMARY UPLOAD METHOD (UPDATED WITH AUTO-RESIZE) ---
    def upload_dataframe_to_sheet(self, 
                                  dataframe: pd.DataFrame, 
                                  spreadsheet_id: str,
                                  worksheet_name: str = "Sheet1",
                                  clear_before_upload: bool = True,
                                  upload_start_cell: str = "A1", 
                                  include_header: bool = True,
                                  gsheet_layout_map: Dict[str, Union[str, None]] = None):
        """
        The main method to upload a cleaned Pandas DataFrame.
        Includes automatic resizing of the sheet if data exceeds current grid limits.

        Args:
            dataframe: The Pandas DataFrame containing the data to upload.
            spreadsheet_name: The name of the Google Sheet.
            worksheet_name: The specific tab name. Defaults to 'Sheet1'.
            clear_before_upload: If True, clears the sheet contents before uploading.
            upload_start_cell: The starting cell (e.g., "A1") or "APPEND" to add after existing data.
            include_header: If True, includes the DataFrame's header row in the upload.
            gsheet_layout_map: If there is a specific layout mapping for GSheet columns then follow it, else upload as-is.
        """

        # 0. Check if a layout map was provided and apply it
        if gsheet_layout_map:
            dataframe = self._format_dataframe_to_gsheet_layout(dataframe, gsheet_layout_map)
        
        try:
            # 1. Connect to Spreadsheet
            spreadsheet = self.client.open_by_key(spreadsheet_id)
            worksheet = spreadsheet.worksheet(worksheet_name)

            # 2. DYNAMIC LOGIC: Determine Start Cell and Row Index
            start_cell = upload_start_cell 
            start_row_int = 1 
            
            if upload_start_cell.upper() == "APPEND":
                # Get all existing values to find the end of the data
                existing_data = worksheet.get_all_values()
                next_row = len(existing_data) + 1
                start_cell = f"A{next_row}"
                start_row_int = next_row # Capture this for the math below
                print(f"-> Append mode active. Target cell: {start_cell}")
                
                # Force include_header to False if we are appending to existing data
                if next_row > 1:
                    include_header = False
                    print("-> Data already exists. Skipping header for append.")
            else:
                # Parse the row number from standard cell strings like "A1", "C50"
                match = re.search(r"(\d+)", start_cell)
                if match:
                    start_row_int = int(match.group(1))

            # 3. Prepare Data
            data_to_upload = self._prepare_data_for_gspread(
                dataframe, 
                include_header=include_header 
            )

            # --- CRITICAL FIX: RESIZE COLUMNS FIRST ---
            # If we are adding 100k rows, we MUST shrink columns first to avoid hitting the 10M cell limit.
            required_cols = len(dataframe.columns)
            current_sheet_cols = worksheet.col_count
            
            # Optimization: If the sheet is wider than we need, shrink it NOW to free up space.
            # If it's too narrow, expand it NOW so the data fits.
            if required_cols != current_sheet_cols:
                 print(f"↔️ Optimizing columns: {current_sheet_cols} -> {required_cols}")
                 worksheet.resize(cols=required_cols)
                 time.sleep(2) # Short pause for API stability

            # --- AUTO-RESIZE ROWS ---
            num_rows_to_upload = len(data_to_upload)
            required_total_rows = start_row_int + num_rows_to_upload
            current_sheet_rows = worksheet.row_count
            
            if required_total_rows > current_sheet_rows:
                rows_to_add = required_total_rows - current_sheet_rows + 500 # Buffer
                
                # Check Limit Prediction
                predicted_cells = (current_sheet_rows + rows_to_add) * required_cols
                if predicted_cells > 9500000:
                    print(f"⚠️ WARNING: This upload will push the sheet to {predicted_cells} cells (Limit: 10M).")
                
                print(f"📉 Resizing sheet: Adding {rows_to_add} rows...")
                try:
                    worksheet.add_rows(rows_to_add)
                except Exception as resize_err:
                    if "10000000 cells" in str(resize_err):
                        raise Exception("❌ SHEET FULL: Cannot add rows. The Google Sheet has hit the 10 Million cell limit. Please archive old data or use a new sheet.")
                    raise resize_err

            # 4. Clear (only if NOT appending and requested)
            if clear_before_upload and upload_start_cell.upper() != "APPEND":
                print(f"Clearing worksheet: '{worksheet_name}'...")
                worksheet.clear()

            # 5. Upload
            print(f"Uploading {len(data_to_upload)} rows to {worksheet_name} at {start_cell}...")
            
            # Chunked upload for massive files (prevents timeout)
            chunk_size = 5000
            if len(data_to_upload) > chunk_size:
                print(f"   ℹ️ Large file detected. Uploading in chunks of {chunk_size}...")
                for i in range(0, len(data_to_upload), chunk_size):
                    chunk = data_to_upload[i : i + chunk_size]
                    # Calculate chunk start row
                    chunk_start_row = start_row_int + i
                    chunk_range = f"A{chunk_start_row}"
                    worksheet.update(chunk_range, chunk, value_input_option='USER_ENTERED')
                    print(f"      ✅ Uploaded rows {i} to {i+len(chunk)}")
                    time.sleep(1)
            else:
                worksheet.update(start_cell, data_to_upload, value_input_option='USER_ENTERED')
            
            print("✨ Upload complete!")

        except Exception as e:
            print(f"An unexpected error occurred during the upload process: {e}")
            traceback.print_exc()

    def update_selective_columns(self, dataframe, spreadsheet_id, worksheet_name, 
                                 gsheet_layout_map, start_row=3, append=False):
        """
        Overridden method: Uses batch_update and no internal try/catch
        so errors properly trigger the main retry loop.
        """
        if not gsheet_layout_map:
            print("⚠️ No layout map provided. Skipping.")
            return

        spreadsheet = self.client.open_by_key(spreadsheet_id)
        worksheet = spreadsheet.worksheet(worksheet_name)
        
        # --- 1. DETERMINE START ROW ---
        final_start_row = start_row
        if append:
            anchor_col = list(gsheet_layout_map.keys())[0]
            col_values = worksheet.col_values(self._col_letter_to_index(anchor_col))
            final_start_row = max(len(col_values) + 1, start_row)
        
        # --- 2. GRID LIMIT SAFETY ---
        needed_rows = final_start_row + len(dataframe) - 1
        if needed_rows > worksheet.row_count:
            rows_to_add = needed_rows - worksheet.row_count + 10
            print(f"📏 Expanding sheet: Adding {rows_to_add} rows...")
            worksheet.add_rows(rows_to_add)

        # --- 3. COMPILE BATCH DATA ---
        batch_data = []
        end_row = final_start_row + len(dataframe) - 1

        for sheet_col, df_col in gsheet_layout_map.items():
            if df_col not in dataframe.columns:
                continue
            
            # Convert to list of lists, replace NaNs
            values = dataframe[[df_col]].fillna('').astype(str).values.tolist()
            
            # Construct Range
            target_range = f"{sheet_col}{final_start_row}:{sheet_col}{end_row}"
            
            batch_data.append({
                'range': target_range,
                'values': values
            })

        # --- 4. EXECUTE SINGLE BATCH CALL ---
        if batch_data:
            worksheet.batch_update(batch_data, value_input_option='USER_ENTERED')
            print(f"✅ Batch updated {len(dataframe)} rows in '{worksheet_name}'")
        else:
            print("ℹ️ No valid columns found to update.")

    def _col_letter_to_index(self, letter):
        index = 0
        for char in letter:
            index = index * 26 + (ord(char.upper()) - ord('A') + 1)
        return index