import time
import socket
import logging
import traceback
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from typing import Callable, Dict, Any, List

logger = logging.getLogger(__name__)

class GoogleSheetsListener:
    """
    A reusable listener that monitors a Google Sheet for triggers.
    It handles its own authentication and executes a custom callback when triggered.
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
        """
        Args:
            credentials_file: Path to the Service Account JSON.
            spreadsheet_id: ID of the Google Sheet to monitor.
            worksheet_name: Tab name to scan.
            header_map: Map of keys to column headers (e.g., {"trigger": "Run?", "status": "Status"}).
            check_interval: Seconds to wait between scans.
        """
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
        """Standardizes worksheet access with a fresh open call."""
        return self.client.open_by_key(self.spreadsheet_id).worksheet(self.worksheet_name)

    def start_listening(self, callback_func: Callable[[Dict[str, Any]], None]):
        """
        Starts the monitoring loop.
        
        Args:
            callback_func: A function that accepts a dict of the row's data.
        """
        self._is_listening = True
        print(f"👀 Smart Listener Online (Monitoring: {self.worksheet_name})...")

        while self._is_listening:
            try:
                ws = self._get_worksheet()
                all_values = ws.get_all_values()

                if not all_values or len(all_values) < 2:
                    time.sleep(self.check_interval)
                    continue

                # 1. Map Headers to Column Indices
                headers = all_values[0]
                try:
                    indices = {key: headers.index(name) for key, name in self.header_map.items()}
                except ValueError as e:
                    logger.error(f"Header mismatch: {e}")
                    time.sleep(30)
                    continue

                # 2. Scan Rows
                for i, row in enumerate(all_values[1:], start=2):
                    # Pad row if columns are missing at the end
                    max_idx = max(indices.values())
                    if len(row) <= max_idx:
                        row.extend([""] * (max_idx - len(row) + 1))

                    trigger_val = str(row[indices['trigger']]).upper()
                    status_val = str(row[indices['status']]).strip()

                    # Trigger logic: Checkbox is TRUE and Status is empty
                    if trigger_val == "TRUE" and not status_val:
                        print(f"🚀 Trigger found on Row {i}. Executing...")
                        
                        # Immediate status update to prevent double-execution
                        ws.update_cell(i, indices['status'] + 1, "Processing...")

                        try:
                            # Package row data for the callback
                            data_package = {key: row[idx] for key, idx in indices.items()}
                            data_package['row_index'] = i
                            
                            # Run the external logic
                            callback_func(data_package)

                            ws.update_cell(i, indices['status'] + 1, "Success")
                        except Exception as err:
                            print(f"❌ Automation Error: {err}")
                            ws.update_cell(i, indices['status'] + 1, f"Error: {str(err)[:50]}")

                time.sleep(self.check_interval)

            except Exception as loop_err:
                print(f"⚠️ Connection Error: {loop_err}")
                time.sleep(15)

    def stop_listening(self):
        """Stops the loop on the next iteration."""
        self._is_listening = False
        print("🛑 Listener shutdown.")