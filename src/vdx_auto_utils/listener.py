import time
import socket
import logging
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from typing import Callable, Dict, Any

logger = logging.getLogger(__name__)

class GeneralListener:
    """
    A reusable listener that monitors a Google Sheet for triggers.
    It passes the row data to a callback and lets the user handle feedback.
    """

    SCOPES = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive'
    ]

    def __init__(self, 
                 credentials_file: str, 
                 spreadsheet_id: str, 
                 worksheet_name: str, 
                 header_map: Dict[str, str],
                 check_interval: int = 10):
        self.spreadsheet_id = spreadsheet_id
        self.worksheet_name = worksheet_name
        self.header_map = header_map
        self.check_interval = check_interval
        self._is_listening = False
        
        # Internal Authentication
        self.creds = ServiceAccountCredentials.from_json_keyfile_name(credentials_file, self.SCOPES)
        self.client = gspread.authorize(self.creds)
        
        socket.setdefaulttimeout(120)

    def _get_worksheet(self):
        """Fetches the worksheet instance."""
        return self.client.open_by_key(self.spreadsheet_id).worksheet(self.worksheet_name)

    def write_to_cell(self, row_index: int, column_name: str, value: Any):
        """
        Helper to write data back to the sheet based on a header name.
        """
        ws = self._get_worksheet()
        headers = ws.row_values(1)
        if column_name in headers:
            col_idx = headers.index(column_name) + 1
            ws.update_cell(row_index, col_idx, value)
            print(f"📝 Updated Row {row_index}, Col '{column_name}' with: {value}")
        else:
            print(f"⚠️ Column '{column_name}' not found.")

    def start_listening(self, callback_func: Callable[[Dict[str, Any]], None]):
        """
        Starts the monitoring loop.
        """
        self._is_listening = True
        print(f"👀 Smart Listener Online (Monitoring: {self.worksheet_name})...")

        while self._is_listening:
            try:
                ws = self._get_worksheet()
                all_values = ws.get_all_values() #

                if not all_values or len(all_values) < 2:
                    time.sleep(self.check_interval)
                    continue

                headers = all_values[0]
                try:
                    indices = {key: headers.index(name) for key, name in self.header_map.items()}
                except ValueError as e:
                    logger.error(f"Header mismatch: {e}")
                    time.sleep(30)
                    continue

                for i, row in enumerate(all_values[1:], start=2):
                    # Ensure row has enough columns
                    max_idx = max(indices.values())
                    if len(row) <= max_idx:
                        row.extend([""] * (max_idx - len(row) + 1))

                    trigger_val = str(row[indices['trigger']]).upper()
                    status_val = str(row[indices['status']]).strip()

                    # Trigger only if Checkbox is TRUE and Status/Remarks is empty
                    if trigger_val == "TRUE" and not status_val:
                        # Package data
                        data_package = {key: row[idx] for key, idx in indices.items()}
                        data_package['row_index'] = i
                        
                        # Execute your custom logic
                        # You are now responsible for updating the 'status' column 
                        # inside this function to prevent the loop from re-triggering.
                        callback_func(data_package)

                time.sleep(self.check_interval)

            except Exception as loop_err:
                print(f"⚠️ Connection Error: {loop_err}")
                time.sleep(15)

    def stop_listening(self):
        self._is_listening = False