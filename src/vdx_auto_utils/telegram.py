import requests
import logging
import os
import json

# Configure basic logging to catch errors
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TelegramBot:
    """
    A wrapper for the Telegram Bot API to send messages to Groups and Topics.
    """

    def __init__(self, api_token: str):
        """
        Initialize the bot with your API Token.

        Args:
            api_token (str): The Telegram Bot API Token from @BotFather.
        """
        self.api_token = api_token
        self.base_url = f"https://api.telegram.org/bot{self.api_token}"

    def send_message(self, group_id: str, message: str, topic_id: int = None, 
                     buttons: list = None, reply_to_message_id: int = None):
        """
        Sends a text message with optional interactive buttons.
        Args:
            group_id (str): The Chat ID of the group or channel.
            message (str): The text content of the message.
            topic_id (int, optional): The 'message_thread_id' for forum topics.
            buttons (list, optional): A list of lists representing rows of buttons for an inline keyboard.
            reply_to_message_id (int, optional): If set, the message will be a reply to this message ID.
        """
        endpoint = f"{self.base_url}/sendMessage"
        
        payload = {
            "chat_id": group_id,
            "text": message,
            "parse_mode": "HTML"
        }

        if topic_id:
            payload["message_thread_id"] = topic_id

        if reply_to_message_id:
            payload["reply_to_message_id"] = reply_to_message_id

        # Added: Handle buttons if provided
        if buttons:
            payload["reply_markup"] = json.dumps({"inline_keyboard": buttons})

        try:
            response = requests.post(endpoint, data=payload, timeout=10)
            response.raise_for_status()
            logger.info(f"Message sent to {group_id}")
            return response.json()
        except requests.exceptions.RequestException as e:
            # Enhanced error logging to see the exact description from Telegram
            error_desc = response.json().get('description') if response else "No response"
            logger.error(f"Failed to send Telegram message: {e} | Detail: {error_desc}")
            return None

    def send_document(self, group_id: str, file_path: str, caption: str = None, topic_id: int = None):
        """
        Sends a file (Document, Photo, or Video) to a specific group or topic.
        Automatically handles different media types and enforces the 50MB limit.
        Args:
            group_id (str): The Chat ID of the group or channel.
            file_path (str): The local path to the file to be sent.
            caption (str, optional): An optional caption for the file.
            topic_id (int, optional): The 'message_thread_id' for forum topics.
        """
        if not os.path.exists(file_path):
            logger.error(f"File not found: {file_path}")
            return None

        # Check 50MB limit (standard Bot API constraint)
        file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
        if file_size_mb > 50:
            logger.error(f"File too large ({file_size_mb:.2f}MB). Standard API limit is 50MB.")
            return None

        # Determine method and payload key based on file extension
        ext = os.path.splitext(file_path)[1].lower()
        if ext in ['.jpg', '.jpeg', '.png']:
            method = "sendPhoto"
            file_key = "photo"
        elif ext in ['.mp4', '.mov']:
            method = "sendVideo"
            file_key = "video"
        else:
            method = "sendDocument"
            file_key = "document"

        endpoint = f"{self.base_url}/{method}"
        
        payload = {"chat_id": group_id}
        if caption:
            payload["caption"] = caption
        if topic_id:
            payload["message_thread_id"] = topic_id

        try:
            with open(file_path, 'rb') as f:
                files = {file_key: f}
                response = requests.post(endpoint, data=payload, files=files, timeout=60)
                response.raise_for_status()
                
            logger.info(f"File '{os.path.basename(file_path)}' sent via {method}")
            return response.json()

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to send file: {e}")
            return None
    
    def get_updates(self, offset=None, timeout=30):
        """
        Polls the Telegram API for new updates (messages, button clicks).

        Args:
            offset (int, optional): Identifier of the first update to be returned.
            timeout (int): Timeout in seconds
        """
        endpoint = f"{self.base_url}/getUpdates"
        params = {"timeout": timeout, "offset": offset}
        try:
            response = requests.get(endpoint, params=params, timeout=timeout + 5)
            return response.json().get("result", [])
        except Exception as e:
            logger.error(f"Error fetching updates: {e}")
            return []
    
    def answer_callback_query(self, callback_query_id: str):
        """
        Acknowledges a callback query to remove the loading state from the button.

        Args:
            callback_query_id (str): The unique identifier for the query to be answered.
        """
        endpoint = f"{self.base_url}/answerCallbackQuery"
        payload = {"callback_query_id": callback_query_id}
        try:
            requests.post(endpoint, data=payload, timeout=10)
        except Exception as e:
            logger.error(f"Error answering callback query: {e}")