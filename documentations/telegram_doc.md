# TelegramBot Documentation

## Table of Contents
- [How to Use in Your Project](#how-to-use-in-your-project)
  - [Quick Start Guide](#quick-start-guide)
- [Overview](#overview)
- [Class: TelegramBot](#class-telegrambot)
  - [Initialization](#initialization)
  - [Methods](#methods)
    - [send_message](#send_message)
    - [send_document](#send_document)
    - [get_updates](#get_updates)
    - [answer_callback_query](#answer_callback_query)
    - [get_chat_admins](#get_chat_admins)
- [Usage Example](#usage-example)

## How to Use in Your Project

`TelegramBot` is a lightweight wrapper around the Telegram Bot API. Use it to send messages, files, and interactive buttons to Telegram groups or topics — or to poll for incoming updates (button clicks, messages).

### Quick Start Guide

1. **Import the Class**:
    ```python
    from functions.telegram import TelegramBot
    ```

2. **Initialize**:
    ```python
    bot = TelegramBot(api_token="your_bot_token_from_BotFather")
    ```

3. **Send a Message**:
    ```python
    bot.send_message(group_id="-1001234567890", message="Hello, World!")
    ```

4. **Send to a Specific Topic** (in a Forum group):
    ```python
    bot.send_message(group_id="-1001234567890", message="Update ready.", topic_id=5)
    ```

5. **Send a File**:
    ```python
    bot.send_document(group_id="-1001234567890", file_path="reports/output.csv", caption="Latest report")
    ```

---

## Overview

`TelegramBot` wraps the Telegram Bot HTTP API using the `requests` library. It supports sending text messages (with HTML formatting, inline buttons, and reply threading), sending files (with automatic type detection for photos, videos, and documents), polling for new updates, answering callback queries, and fetching group admin lists.

Messages support `HTML` parse mode by default. All methods return `None` on failure and log errors via Python's `logging` module rather than raising exceptions — making it safe to use in automated workflows without crashing on transient Telegram API errors.

---

## Class: `TelegramBot`

### Initialization
```python
def __init__(self, api_token: str)
```
Sets up the bot with your API token. No network calls are made at initialization.

- **Parameters:**
  - `api_token` (str): Your Telegram Bot API token, obtained from [@BotFather](https://t.me/BotFather).

---

### Methods

#### `send_message`
```python
def send_message(self, group_id: str, message: str, topic_id: int = None,
                 buttons: list = None, reply_to_message_id: int = None,
                 disable_web_page_preview: bool = False) -> dict | None
```
Sends a text message to a group or topic. Supports HTML formatting, inline keyboard buttons, and reply threading.

- **Parameters:**
  - `group_id` (str): The Chat ID of the target group or channel (e.g. `"-1001234567890"`).
  - `message` (str): The message text. Supports HTML tags such as `<b>`, `<i>`, `<code>`, `<a href="...">`.
  - `topic_id` (int, optional): The `message_thread_id` for groups with Forum Topics enabled.
  - `buttons` (list, optional): A list of lists defining an inline keyboard. Each inner list is a row of buttons. Each button is a dict with `text` and `callback_data` keys.
  - `reply_to_message_id` (int, optional): Message ID to reply to.
  - `disable_web_page_preview` (bool, optional): If `True`, suppresses link previews. Defaults to `False`.
- **Returns:** The Telegram API JSON response as a dict, or `None` on failure.

**Button format example:**
```python
buttons = [
    [{"text": "Approve ✅", "callback_data": "approve_123"}],
    [{"text": "Reject ❌",  "callback_data": "reject_123"}]
]
```

---

#### `send_document`
```python
def send_document(self, group_id: str, file_path: str, caption: str = None,
                  topic_id: int = None) -> dict | None
```
Sends a local file to a group. Automatically selects the appropriate Telegram API method based on the file extension:

| Extension | Method Used |
|-----------|-------------|
| `.jpg`, `.jpeg`, `.png` | `sendPhoto` |
| `.mp4`, `.mov` | `sendVideo` |
| All others | `sendDocument` |

- **Parameters:**
  - `group_id` (str): The Chat ID of the target group.
  - `file_path` (str): Absolute or relative path to the local file.
  - `caption` (str, optional): Caption text to display with the file.
  - `topic_id` (int, optional): Forum topic ID to send into.
- **Returns:** The Telegram API JSON response as a dict, or `None` on failure.
- **Notes:**
  - Files larger than 50MB will be rejected before upload (standard Bot API limit).
  - Returns `None` if the file does not exist at the given path.

---

#### `get_updates`
```python
def get_updates(self, offset: int = None, timeout: int = 30) -> list
```
Polls the Telegram API for new incoming updates (messages, callback queries, etc.). Used to build simple polling loops for interactive bots.

- **Parameters:**
  - `offset` (int, optional): The ID of the first update to return. Pass the last received `update_id + 1` to acknowledge previous updates and avoid receiving them again.
  - `timeout` (int): Long-polling timeout in seconds. Defaults to `30`.
- **Returns:** A list of update objects (dicts), or an empty list on failure.

---

#### `answer_callback_query`
```python
def answer_callback_query(self, callback_query_id: str, text: str = None,
                          show_alert: bool = False)
```
Acknowledges a callback query triggered by a user clicking an inline button. Must be called within 10 seconds of receiving the query, or Telegram will show a "loading" indicator to the user.

- **Parameters:**
  - `callback_query_id` (str): The unique ID from the incoming callback query object.
  - `text` (str, optional): Notification text shown to the user. If omitted, nothing is displayed.
  - `show_alert` (bool, optional): If `True`, shows a popup alert instead of a brief toast notification. Defaults to `False`.

---

#### `get_chat_admins`
```python
def get_chat_admins(self, group_id: str) -> list
```
Returns a list of user IDs for all current administrators of a group. Useful for permission checks inside callback handlers.

- **Parameters:**
  - `group_id` (str): The Chat ID of the group.
- **Returns:** A list of integer user IDs, or an empty list on failure.

---

## Usage Example

```python
from functions.telegram import TelegramBot

bot = TelegramBot(api_token="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11")
GROUP_ID = "-1001234567890"
TOPIC_ID = 42  # Optional: for groups with Forum Topics

# Send a plain message
bot.send_message(GROUP_ID, "Automation started.")

# Send a formatted message with buttons
bot.send_message(
    group_id=GROUP_ID,
    message="<b>New Order</b>\nOrder #1042 is ready for review.",
    topic_id=TOPIC_ID,
    buttons=[
        [{"text": "Approve ✅", "callback_data": "approve_1042"}],
        [{"text": "Reject ❌",  "callback_data": "reject_1042"}]
    ]
)

# Send a file
bot.send_document(GROUP_ID, "exports/daily_report.xlsx", caption="Daily Report")

# Poll for button clicks and handle them
offset = None
while True:
    updates = bot.get_updates(offset=offset)
    for update in updates:
        offset = update["update_id"] + 1
        if "callback_query" in update:
            query = update["callback_query"]
            data = query["data"]
            user_id = query["from"]["id"]
            admins = bot.get_chat_admins(GROUP_ID)

            if user_id in admins:
                bot.answer_callback_query(query["id"], text=f"Action: {data}", show_alert=True)
                bot.send_message(GROUP_ID, f"Admin approved action: <code>{data}</code>")
            else:
                bot.answer_callback_query(query["id"], text="Access denied.", show_alert=True)
```