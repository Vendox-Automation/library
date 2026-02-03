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

    def send_message(self, group_id: str, message: str, topic_id: int = None, reply_to_message_id: int = None):
        """
        Sends a text message to a specific group, topic, or as a reply.

        Args:
            group_id (str): The Chat ID (e.g., "-100123456789").
            message (str): The actual text content to send.
            topic_id (int, optional): The 'message_thread_id' for forum topics. Defaults to None.
            reply_to_message_id (int, optional): The ID of a message to reply to. Defaults to None.

        Returns:
            dict: The JSON response from the Telegram API if successful, else None.
        """
        endpoint = f"{self.base_url}/sendMessage"
        
        payload = {
            "chat_id": group_id,
            "text": message,
            "parse_mode": "HTML"  # Optional: allows bold/italic/links in message
        }

        # Handle Topics (Forum Threads)
        if topic_id:
            payload["message_thread_id"] = topic_id

        # Handle Replies
        if reply_to_message_id:
            payload["reply_to_message_id"] = reply_to_message_id

        try:
            response = requests.post(endpoint, data=payload, timeout=10)
            response.raise_for_status() # Raises error for 4xx/5xx status codes
            
            logger.info(f"Message sent to {group_id} (Topic: {topic_id})")
            return response.json()

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to send Telegram message: {e}")
            if response is not None:
                logger.error(f"Response: {response.text}")
            return None

    def send_document(self, group_id: str, file_path: str, caption: str = None, topic_id: int = None):
        """
        Sends a file (Document, Photo, or Video) to a specific group or topic.
        Automatically handles different media types and enforces the 50MB limit.
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
    
    def send_interactive_message(self, group_id: str, message: str, buttons: list, topic_id: int = None):
        """
        Sends a message with Inline Keyboard buttons.
        
        Args:
            group_id (str): The Chat ID.
            message (str): The text content above the buttons.
            buttons (list): A list of lists representing rows of buttons.
                            Example: [[{"text": "Option 1", "callback_data": "1"}, {"text": "Option 2", "callback_data": "2"}]]
            topic_id (int, optional): The 'message_thread_id' for forum topics.
        """
        endpoint = f"{self.base_url}/sendMessage"
        
        # Construct the inline keyboard structure
        reply_markup = {"inline_keyboard": buttons}
        
        payload = {
            "chat_id": group_id,
            "text": message,
            "parse_mode": "HTML",
            "reply_markup": json.dumps(reply_markup) # Must be a JSON-serialized string
        }

        if topic_id:
            payload["message_thread_id"] = topic_id

        try:
            response = requests.post(endpoint, data=payload, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to send interactive message: {e}")
            return None