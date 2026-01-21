import requests
import logging

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