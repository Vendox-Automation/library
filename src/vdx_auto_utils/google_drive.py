import io
import pandas as pd
from google.oauth2 import service_account
from googleapiclient.discovery import build
from typing import List, Dict, Optional

class DriveManager:
    """
    A reusable module for interacting with the Google Drive API.
    Handles authentication, navigation, file discovery, and reading.
    """
    
    def __init__(self, service_account_file: str, scopes: List[str] = None):
        """
        Initializes the DriveManager with service account credentials.

        Args:
            service_account_file: Path to the service account JSON file.
            scopes: List of OAuth2 scopes for the Drive API.
        """
        if scopes is None:
            scopes = ['https://www.googleapis.com/auth/drive']
            
        self.creds = service_account.Credentials.from_service_account_file(
            service_account_file, scopes=scopes)
        self.service = build('drive', 'v3', credentials=self.creds)

    def get_folder_id_by_name(self, parent_id: str, target_name: str) -> Optional[str]:
        """
        Finds a folder's ID by its name within a specific parent folder.

        Args:
            parent_id: The ID of the parent folder.
            target_name: The name of the target folder to find.

        Returns:
            The ID of the target folder if found, else None.
        """
        query = (f"name = '{target_name}' and '{parent_id}' in parents and "
                 f"mimeType = 'application/vnd.google-apps.folder' and trashed = false")
        response = self.service.files().list(q=query, spaces='drive', supportsAllDrives=True, 
                                       includeItemsFromAllDrives=True, fields='files(id, name)').execute()
        files = response.get('files', [])
        return files[0]['id'] if files else None

    def navigate_path(self, root_id: str, path_list: List[str]) -> Optional[str]:
        """
        Navigates through a list of folder names starting from a root ID.
        Returns the ID of the final folder in the path.

        Args:
            root_id: The starting folder ID.
            path_list: A list of folder names representing the path.

        Returns:
            The ID of the final folder if the path is valid, else None.
        """
        current_parent = root_id
        for folder_name in path_list:
            current_parent = self.get_folder_id_by_name(current_parent, folder_name)
            if not current_parent:
                print(f"❌ Error: Folder '{folder_name}' not found.")
                return None
        return current_parent

    def copy_file(self, file_id: str, new_name: str, parent_id: str) -> Dict:
        """
        Copies a file to a specific parent folder with a new name.

        Args:
            file_id: The ID of the file to copy.
            new_name: The name for the copied file.
            parent_id: The ID of the destination folder.
        
        Returns:
            The metadata of the copied file.
        """
        copy_body = {'name': new_name, 'parents': [parent_id]}
        return self.service.files().copy(
            fileId=file_id, body=copy_body, supportsAllDrives=True).execute()

    def find_files_by_keywords(self, folder_id: str, keyword_map: Dict[str, str]) -> Dict[str, Optional[str]]:
        """
        Maps files in a folder to keys based on keyword matching in filenames.
        
        Args:
            folder_id: The ID of the folder to search within.
            keyword_map: A dictionary mapping keys to filename keywords.
        
        Returns:
            A dictionary mapping each key to the corresponding file ID or None if not found.
        """
        query = f"'{folder_id}' in parents and trashed = false"
        items = self.service.files().list(q=query, spaces='drive', supportsAllDrives=True, 
                                    includeItemsFromAllDrives=True, fields='files(id, name)').execute().get('files', [])
        
        results = {key: None for key in keyword_map.keys()}
        sorted_keywords = sorted(keyword_map.items(), key=lambda x: len(x[1]), reverse=True)
        assigned_file_ids = set()

        for key, pattern in sorted_keywords:
            for item in items:
                if item['id'] not in assigned_file_ids and pattern in item['name']:
                    results[key] = item['id']
                    assigned_file_ids.add(item['id'])
                    break 
        return results

    def read_csv_from_drive(self, file_id: str) -> Optional[pd.DataFrame]:
        """
        Reads a CSV file directly from Google Drive into a Pandas DataFrame.

        Args:
            file_id: The file Id to read from
        
        Returns:
            A Pandas DataFrame containing the CSV data, or None if file_id is invalid.
        """
        if not file_id: return None
        request = self.service.files().get_media(fileId=file_id)
        return pd.read_csv(io.BytesIO(request.execute()), low_memory=False)

    def read_sheet_from_drive(self, file_id: str, sheet_name: str = None) -> Optional[pd.DataFrame]:
        """
        Exports a native Google Sheet to a CSV format and reads it into a Pandas DataFrame.

        Args:
            file_id: The file ID of the Google Sheet.
        
        Returns:
            A Pandas DataFrame containing the Sheet data, or None if file_id is invalid.
        """
        if not file_id: return None
        try:
            # Export as an Excel file to preserve all sheets/tabs
            request = self.service.files().export_media(
                fileId=file_id, 
                mimeType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )
            excel_data = request.execute()
            
            # Read into pandas using read_excel. 
            # If sheet_name is None, it defaults to the first sheet automatically.
            return pd.read_excel(io.BytesIO(excel_data), sheet_name=sheet_name)
            
        except Exception as e:
            print(f"❌ Failed to export Google Sheet: {e}")
            return None