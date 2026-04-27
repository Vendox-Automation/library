import calendar as _cal
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
                     buttons: list = None, reply_to_message_id: int = None, disable_web_page_preview: bool = False):
        """
        Sends a text message with optional interactive buttons.
        Args:
            group_id (str): The Chat ID of the group or channel.
            message (str): The text content of the message.
            topic_id (int, optional): The 'message_thread_id' for forum topics.
            buttons (list, optional): A list of lists representing rows of buttons for an inline keyboard.
            reply_to_message_id (int, optional): If set, the message will be a reply to this message ID.
            disable_web_page_preview (bool, optional): If set to True, it will disable preview links. Defaults to False
        """
        endpoint = f"{self.base_url}/sendMessage"
        
        payload = {
            "chat_id": group_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": disable_web_page_preview
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
            try:
                error_desc = response.json().get('description', 'No description')
            except Exception:
                error_desc = "No response"
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
    
    def answer_callback_query(self, callback_query_id: str, text: str = None, show_alert: bool = False):
        """
        Acknowledges a callback query and optionally shows a popup alert.

        Args:
            callback_query_id (str): The unique identifier for the query to be answered.
            text (str, optional): Text of the notification. If not specified, nothing will be shown.
            show_alert (bool, optional): If true, an alert will be shown instead of a notification at the top of the chat screen.
        """
        endpoint = f"{self.base_url}/answerCallbackQuery"
        payload = {"callback_query_id": callback_query_id}
        
        if text:
            payload["text"] = text
            payload["show_alert"] = show_alert

        try:
            requests.post(endpoint, data=payload, timeout=10)
        except Exception as e:  
            logger.error(f"Error answering callback query: {e}")

    def send_calendar(self, group_id: str, year: int, month: int,
                      title: str = "📅 Select a date:", topic_id: int = None) -> dict:
        """
        Sends a calendar date-picker message with an inline keyboard.

        Convenience wrapper around ``make_calendar()`` + ``send_message()``.
        The user taps a day and your bot receives a callback query whose
        ``data`` field you decode with ``parse_calendar_callback()``.

        Args:
            group_id (str): Chat ID of the group or channel.
            year     (int): Year of the month to display.
            month    (int): Month to display (1–12).
            title    (str, optional): Caption shown above the keyboard.
                Defaults to ``"📅 Select a date:"``.
            topic_id (int, optional): Forum topic (message_thread_id), if needed.

        Returns:
            dict: The raw Telegram API response, or ``None`` on failure.

        Example::

            from vdx_auto_utils import TelegramBot
            from datetime import date

            bot = TelegramBot("YOUR_TOKEN")

            # 1. Send the calendar for the current month
            today = date.today()
            bot.send_calendar(chat_id, today.year, today.month, title="Pick a report date:")

            # 2. In your callback handler loop:
            for update in bot.get_updates(offset=...):
                query = update.get("callback_query")
                if not query:
                    continue

                result = bot.parse_calendar_callback(query["data"])
                bot.answer_callback_query(query["id"])

                if result["action"] == "day":
                    bot.send_message(query["message"]["chat"]["id"],
                                     f"You picked: {result['date']}")

                elif result["action"] == "nav":
                    # Re-send / edit the message with the new month's keyboard
                    new_buttons = bot.make_calendar(result["year"], result["month"])
        """
        buttons = self.make_calendar(year, month)
        return self.send_message(
            group_id=group_id,
            message=title,
            buttons=buttons,
            topic_id=topic_id,
        )

    def edit_message(self, group_id: str, message_id: int, text: str,
                     buttons: list = None) -> dict:
        """
        Edits the text (and optionally the inline keyboard) of an existing message.

        Args:
            group_id   (str): Chat ID of the group or channel.
            message_id (int): ID of the message to edit.
            text       (str): New message text. Supports HTML formatting.
            buttons    (list, optional):
                - ``None``  → leave the existing keyboard unchanged.
                - ``[]``    → remove the keyboard entirely.
                - ``[...]`` → replace the keyboard with this new layout.

        Returns:
            dict: The Telegram API response, or ``None`` on failure.
        """
        endpoint = f"{self.base_url}/editMessageText"
        payload  = {
            "chat_id":    group_id,
            "message_id": message_id,
            "text":       text,
            "parse_mode": "HTML",
        }
        if buttons is not None:
            payload["reply_markup"] = json.dumps({"inline_keyboard": buttons})
        try:
            response = requests.post(endpoint, data=payload, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to edit message: {e}")
            return None

    def edit_message_keyboard(self, group_id: str, message_id: int,
                              buttons: list) -> dict:
        """
        Replaces the inline keyboard of an existing message without changing its text.

        Use this for calendar navigation (◀/▶) so only the month grid is swapped.

        Args:
            group_id   (str): Chat ID of the group or channel.
            message_id (int): ID of the message whose keyboard you want to update.
            buttons    (list): New keyboard layout (pass ``[]`` to remove entirely).

        Returns:
            dict: The Telegram API response, or ``None`` on failure.
        """
        endpoint = f"{self.base_url}/editMessageReplyMarkup"
        payload  = {
            "chat_id":      group_id,
            "message_id":   message_id,
            "reply_markup": json.dumps({"inline_keyboard": buttons}),
        }
        try:
            response = requests.post(endpoint, data=payload, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to edit message keyboard: {e}")
            return None

    @staticmethod
    def make_calendar(year: int, month: int) -> list:
        """
        Generates an inline keyboard layout for a month calendar date picker.

        Returns a ``list[list[dict]]`` compatible with the ``buttons`` parameter
        of ``send_message`` and ``send_calendar``.

        Keyboard layout
        ---------------
        Row 0 — Navigation bar:
            [◀]  [Month YYYY]  [▶]
        Row 1 — Day-of-week headers (non-clickable):
            [Mo] [Tu] [We] [Th] [Fr] [Sa] [Su]
        Rows 2-7 — Week rows:
            Numbered day buttons; empty cells (padding days) show a blank space
            and use ``"CAL:IGNORE"`` so tapping them does nothing.

        Callback data format
        --------------------
        - Day selected  : ``"CAL:DAY:YYYY-MM-DD"``
        - Navigate month: ``"CAL:NAV:YYYY-MM"``
        - Non-clickable : ``"CAL:IGNORE"``

        Pass the resulting list directly to ``send_message(buttons=...)`` or let
        ``send_calendar`` do it for you. Decode the callback with
        ``parse_calendar_callback()``.

        Args:
            year  (int): Year to display (e.g. 2026).
            month (int): Month to display (1 = January … 12 = December).

        Returns:
            list: Nested list of button dicts for an inline keyboard.

        Example::

            bot = TelegramBot("YOUR_TOKEN")
            buttons = bot.make_calendar(2026, 4)
            bot.send_message(chat_id, "Pick a date:", buttons=buttons)
        """
        _DOW = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]

        prev_year,  prev_month  = (year - 1, 12) if month == 1  else (year, month - 1)
        next_year,  next_month  = (year + 1,  1) if month == 12 else (year, month + 1)

        nav_row = [
            {"text": "◀", "callback_data": f"CAL:NAV:{prev_year}-{prev_month:02d}"},
            {"text": f"{_cal.month_name[month]} {year}", "callback_data": "CAL:IGNORE"},
            {"text": "▶", "callback_data": f"CAL:NAV:{next_year}-{next_month:02d}"},
        ]
        dow_row = [{"text": d, "callback_data": "CAL:IGNORE"} for d in _DOW]

        week_rows = []
        for week in _cal.monthcalendar(year, month):
            row = []
            for day in week:
                if day == 0:
                    row.append({"text": " ", "callback_data": "CAL:IGNORE"})
                else:
                    date_str = f"{year}-{month:02d}-{day:02d}"
                    row.append({"text": str(day), "callback_data": f"CAL:DAY:{date_str}"})
            week_rows.append(row)

        return [nav_row, dow_row] + week_rows

    @staticmethod
    def parse_calendar_callback(data: str) -> dict:
        """
        Decodes a callback_data string produced by ``make_calendar()``.

        Call this inside your callback query handler to find out what the
        user tapped.

        Return value
        ------------
        A dict with an ``"action"`` key:

        ``"day"``
            User tapped a date.
            Extra key: ``"date"`` (str, ``"YYYY-MM-DD"``).

        ``"nav"``
            User tapped ◀ or ▶ to change month.
            Extra keys: ``"year"`` (int), ``"month"`` (int).
            Call ``make_calendar(year, month)`` with these to get the new keyboard.

        ``"ignore"``
            User tapped a header, blank cell, or the month label.
            Acknowledge the callback and do nothing else.

        Args:
            data (str): The ``callback_data`` field from a Telegram callback query.

        Returns:
            dict: Decoded action dict (see above).

        Example::

            result = bot.parse_calendar_callback(query["data"])

            if result["action"] == "day":
                print("User picked:", result["date"])      # "2026-04-15"

            elif result["action"] == "nav":
                new_buttons = bot.make_calendar(result["year"], result["month"])
                # edit the message to show the new month's keyboard …

            else:
                pass  # non-interactive tap — nothing to do
        """
        if not isinstance(data, str) or not data.startswith("CAL:"):
            return {"action": "ignore"}

        parts = data.split(":", 2)

        if parts[1] == "DAY" and len(parts) == 3:
            return {"action": "day", "date": parts[2]}

        if parts[1] == "NAV" and len(parts) == 3:
            try:
                y, m = parts[2].split("-")
                return {"action": "nav", "year": int(y), "month": int(m)}
            except ValueError:
                pass

        return {"action": "ignore"}

    def get_chat_admins(self, group_id: str) -> list:
        """
        Fetches the current list of administrator user IDs for a specific chat.
        Args:
            group_id (str): The Chat ID of the group or channel.
        Returns:
            list: A list of user IDs (integers) who are administrators of the chat.
        """
        endpoint = f"{self.base_url}/getChatAdministrators"
        payload = {"chat_id": group_id}
        try:
            response = requests.post(endpoint, data=payload, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if data.get("ok"):
                # Extract and return just the numeric user IDs of the admins
                admin_ids = [admin["user"]["id"] for admin in data["result"]]
                return admin_ids
            else:
                logger.error(f"Telegram API Error: {data.get('description')}")
                return []
                
        except Exception as e:
            logger.error(f"Error fetching admins: {e}")
            return []