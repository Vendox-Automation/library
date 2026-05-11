import logging
import os
import re
import time
import traceback
import socket
from typing import Dict, List, Any, Optional, Union
import gspread
import pandas as pd
from oauth2client.service_account import ServiceAccountCredentials
from .service_account_manager import ServiceAccountManager

socket.setdefaulttimeout(60)
logger = logging.getLogger(__name__)


class GoogleSheetUploader:
    """
    A reusable module to upload a Pandas DataFrame to a Google Sheet.

    Supports two auth modes:
      1. ServiceAccountManager (recommended) — automatic quota failover
         across multiple service accounts.
      2. Single credentials file (legacy) — original behaviour, no failover.

    Usage (recommended):
        manager = ServiceAccountManager(["sa1.json", "sa2.json"])
        uploader = GoogleSheetUploader(service_account_manager=manager)

    Usage (legacy, single account):
        uploader = GoogleSheetUploader(credentials_file="sa.json")
    """

    SCOPES = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    def __init__(
        self,
        credentials_file: Optional[str] = None,
        service_account_manager: Optional[ServiceAccountManager] = None,
    ):
        """
        Initialise the uploader.

        Exactly one of credentials_file or service_account_manager must be
        provided. Passing both raises ValueError. Passing neither raises
        ValueError.

        Args:
            credentials_file: Path to a single service account JSON key file.
                               Kept for backwards compatibility; prefer
                               service_account_manager for production use.
            service_account_manager: A pre-configured ServiceAccountManager
                                     instance. All gspread calls will go
                                     through its execute_with_failover() so
                                     quota errors automatically rotate to the
                                     next account.
        """
        if credentials_file and service_account_manager:
            raise ValueError(
                "Provide either credentials_file or service_account_manager, not both."
            )
        if not credentials_file and not service_account_manager:
            raise ValueError(
                "Provide either credentials_file or service_account_manager."
            )

        self._manager: Optional[ServiceAccountManager] = service_account_manager

        if credentials_file:
            if not os.path.exists(credentials_file):
                raise FileNotFoundError(
                    f"Credentials file not found at: {credentials_file}"
                )
            logger.info(
                "Authenticating with single credentials file: %s", credentials_file
            )
            creds = ServiceAccountCredentials.from_json_keyfile_name(
                credentials_file, self.SCOPES
            )
            # Wrap in a trivial manager so the rest of the class is uniform.
            # We build a one-shot manager that always returns this client.
            self._static_client = gspread.authorize(creds)
            logger.info("Authentication successful (single account, no failover).")
        else:
            self._static_client = None
            logger.info(
                "Using ServiceAccountManager with %d account(s).",
                len(service_account_manager.service_account_files),
            )

    def _run(self, operation, *args, **kwargs):
        """
        Execute a gspread operation with quota failover if a manager is
        present, or directly against the static client otherwise.

        Args:
            operation: Callable(client, *args, **kwargs) -> Any
        """
        if self._manager is not None:
            return self._manager.execute_with_failover(operation, *args, **kwargs)
        return operation(self._static_client, *args, **kwargs)

    def _prepare_data_for_gspread(
        self, df: pd.DataFrame, include_header: bool = True
    ) -> List[List[Any]]:
        """
        Convert a DataFrame into the list-of-lists format gspread expects.
        """
        df = df.fillna("")
        data_rows = df.values.tolist()

        if include_header:
            header = [str(col) for col in df.columns.tolist()]
            prepared = [header] + data_rows
        else:
            prepared = data_rows

        logger.info("Data prepared — total rows (incl. header): %d", len(prepared))
        return prepared

    def _format_dataframe_to_gsheet_layout(
        self,
        df: pd.DataFrame,
        layout_map: Dict[str, Union[str, None]],
    ) -> pd.DataFrame:
        """
        Reorder and space columns according to a sheet-column-letter map.

        Args:
            df: Source DataFrame.
            layout_map: Maps GSheet column letters (A, B, C…) to DataFrame
                        column names, or None for an intentional blank column.
        """
        logger.info("Formatting DataFrame to Google Sheet layout…")
        sorted_layout = sorted(layout_map.items(), key=lambda item: item[0])
        formatted_data = {}

        for gsheet_col, df_col_name in sorted_layout:
            if df_col_name is None:
                formatted_data[gsheet_col] = [""] * len(df)
            elif df_col_name in df.columns:
                formatted_data[gsheet_col] = df[df_col_name].tolist()
            else:
                logger.warning(
                    "DataFrame column '%s' not found — creating empty column '%s'.",
                    df_col_name,
                    gsheet_col,
                )
                formatted_data[gsheet_col] = [""] * len(df)

        formatted_df = pd.DataFrame(formatted_data)
        logger.info(
            "Layout formatted: %d source columns → %d sheet columns.",
            len(df.columns),
            len(formatted_df.columns),
        )
        return formatted_df

    def upload_dataframe_to_sheet(
        self,
        dataframe: pd.DataFrame,
        spreadsheet_id: str,
        worksheet_name: str = "Sheet1",
        clear_before_upload: bool = True,
        upload_start_cell: str = "A1",
        include_header: bool = True,
        gsheet_layout_map: Optional[Dict[str, Union[str, None]]] = None,
    ):
        """
        Upload a DataFrame to a Google Sheet worksheet.

        Includes automatic grid resizing, chunked upload for large files,
        and quota failover when a ServiceAccountManager is provided.

        Args:
            dataframe: DataFrame to upload.
            spreadsheet_id: Google Sheet ID (from the URL).
            worksheet_name: Tab name. Defaults to 'Sheet1'.
            clear_before_upload: Clear sheet contents before uploading.
                                 Ignored in APPEND mode.
            upload_start_cell: Starting cell (e.g. 'A1'), or 'APPEND' to
                               write after the last occupied row.
            include_header: Include the DataFrame column headers as the
                            first row. Auto-disabled in APPEND mode when
                            data already exists.
            gsheet_layout_map: Optional column-letter → DataFrame-column
                               mapping to reorder/space columns before upload.
        """
        if gsheet_layout_map:
            dataframe = self._format_dataframe_to_gsheet_layout(
                dataframe, gsheet_layout_map
            )

        try:
            # 1. Open spreadsheet and worksheet
            def _open_worksheet(client):
                return client.open_by_key(spreadsheet_id).worksheet(worksheet_name)

            worksheet = self._run(_open_worksheet)

            # 2. Resolve start cell and row index
            start_cell = upload_start_cell
            start_row_int = 1

            if upload_start_cell.upper() == "APPEND":

                def _get_all(client):
                    ws = client.open_by_key(spreadsheet_id).worksheet(worksheet_name)
                    return ws.get_all_values()

                existing_data = self._run(_get_all)
                next_row = len(existing_data) + 1
                start_cell = f"A{next_row}"
                start_row_int = next_row
                logger.info("Append mode — target cell: %s", start_cell)

                if next_row > 1:
                    include_header = False
                    logger.info("Existing data found — skipping header for append.")
            else:
                match = re.search(r"(\d+)", start_cell)
                if match:
                    start_row_int = int(match.group(1))

            # 3. Prepare data
            data_to_upload = self._prepare_data_for_gspread(
                dataframe, include_header=include_header
            )

            # 4. Resize columns if needed
            required_cols = len(dataframe.columns)
            current_cols = worksheet.col_count

            if required_cols > current_cols:
                logger.info("Expanding columns: %d → %d", current_cols, required_cols)

                def _resize_cols(client):
                    ws = client.open_by_key(spreadsheet_id).worksheet(worksheet_name)
                    ws.resize(cols=required_cols)

                self._run(_resize_cols)
                time.sleep(2)

            # 5. Resize rows if needed
            num_rows_to_upload = len(data_to_upload)
            required_total_rows = start_row_int + num_rows_to_upload
            current_rows = worksheet.row_count

            if required_total_rows > current_rows:
                rows_to_add = required_total_rows - current_rows + 500  # buffer

                predicted_cells = (current_rows + rows_to_add) * required_cols
                if predicted_cells > 9_500_000:
                    logger.warning(
                        "Upload will push sheet to ~%d cells (limit: 10M).",
                        predicted_cells,
                    )

                logger.info("Adding %d rows to sheet…", rows_to_add)

                def _add_rows(client):
                    ws = client.open_by_key(spreadsheet_id).worksheet(worksheet_name)
                    ws.add_rows(rows_to_add)

                try:
                    self._run(_add_rows)
                except Exception as resize_err:
                    if "10000000 cells" in str(resize_err):
                        raise Exception(
                            "Sheet full — the Google Sheet has hit the 10M cell limit. "
                            "Archive old data or use a new sheet."
                        ) from resize_err
                    raise

            # 6. Clear (only when not appending)
            if clear_before_upload and upload_start_cell.upper() != "APPEND":
                logger.info("Clearing worksheet: '%s'…", worksheet_name)

                def _clear(client):
                    client.open_by_key(spreadsheet_id).worksheet(worksheet_name).clear()

                self._run(_clear)

            # 7. Upload (chunked for large files)
            logger.info(
                "Uploading %d rows to '%s' at %s…",
                len(data_to_upload),
                worksheet_name,
                start_cell,
            )

            chunk_size = 5000
            if len(data_to_upload) > chunk_size:
                logger.info("Large file — uploading in chunks of %d…", chunk_size)
                for i in range(0, len(data_to_upload), chunk_size):
                    chunk = data_to_upload[i : i + chunk_size]
                    chunk_start_row = start_row_int + i
                    chunk_range = f"A{chunk_start_row}"

                    def _upload_chunk(client, _range=chunk_range, _chunk=chunk):
                        ws = client.open_by_key(spreadsheet_id).worksheet(
                            worksheet_name
                        )
                        ws.update(_range, _chunk, value_input_option="USER_ENTERED")

                    self._run(_upload_chunk)
                    logger.info("Uploaded rows %d – %d.", i, i + len(chunk))
                    time.sleep(1)
            else:

                def _upload(client):
                    ws = client.open_by_key(spreadsheet_id).worksheet(worksheet_name)
                    ws.update(
                        start_cell, data_to_upload, value_input_option="USER_ENTERED"
                    )

                self._run(_upload)

            logger.info("Upload complete.")

        except Exception:
            logger.error("Upload failed.", exc_info=True)
            traceback.print_exc()
            raise

    def update_selective_columns(
        self,
        dataframe: pd.DataFrame,
        spreadsheet_id: str,
        worksheet_name: str,
        gsheet_layout_map: Dict[str, str],
        start_row: int = 3,
        append: bool = False,
    ):
        """
        Batch-update specific columns without touching the rest of the sheet.

        Args:
            dataframe: Source DataFrame.
            spreadsheet_id: Google Sheet ID.
            worksheet_name: Tab name.
            gsheet_layout_map: Maps GSheet column letters to DataFrame columns.
            start_row: First row to write to (1-based). Defaults to 3.
            append: If True, writes after the last occupied row in the anchor
                    column instead of at start_row.
        """
        if not gsheet_layout_map:
            logger.warning("No layout map provided — skipping update.")
            return

        # Determine the actual start row
        final_start_row = start_row
        if append:
            anchor_col = list(gsheet_layout_map.keys())[0]
            anchor_idx = self._col_letter_to_index(anchor_col)

            def _get_col(client):
                ws = client.open_by_key(spreadsheet_id).worksheet(worksheet_name)
                return ws.col_values(anchor_idx)

            col_values = self._run(_get_col)
            final_start_row = max(len(col_values) + 1, start_row)

        # Expand grid if needed
        needed_rows = final_start_row + len(dataframe) - 1

        def _get_row_count(client):
            ws = client.open_by_key(spreadsheet_id).worksheet(worksheet_name)
            return ws.row_count

        current_rows = self._run(_get_row_count)

        if needed_rows > current_rows:
            rows_to_add = needed_rows - current_rows + 10
            logger.info("Expanding sheet by %d rows…", rows_to_add)

            def _add_rows(client):
                ws = client.open_by_key(spreadsheet_id).worksheet(worksheet_name)
                ws.add_rows(rows_to_add)

            try:
                self._run(_add_rows)
            except Exception as resize_err:
                if "10000000 cells" in str(resize_err):
                    raise Exception(
                        "Sheet full — the Google Sheet has hit the 10M cell limit. "
                        "Archive old data or use a new sheet."
                    ) from resize_err
                raise

        # Build batch payload
        end_row = final_start_row + len(dataframe) - 1
        batch_data = []

        for sheet_col, df_col in gsheet_layout_map.items():
            if df_col not in dataframe.columns:
                continue
            values = dataframe[[df_col]].fillna("").astype(str).values.tolist()
            target_range = f"{sheet_col}{final_start_row}:{sheet_col}{end_row}"
            batch_data.append({"range": target_range, "values": values})

        if not batch_data:
            logger.info("No valid columns found to update.")
            return

        def _batch_update(client):
            ws = client.open_by_key(spreadsheet_id).worksheet(worksheet_name)
            ws.batch_update(batch_data, value_input_option="USER_ENTERED")

        self._run(_batch_update)
        logger.info("Batch updated %d rows in '%s'.", len(dataframe), worksheet_name)

    @staticmethod
    def _col_letter_to_index(letter: str) -> int:
        """Convert a column letter (A, B, AA…) to a 1-based column index."""
        index = 0
        for char in letter:
            index = index * 26 + (ord(char.upper()) - ord("A") + 1)
        return index
