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
    - [edit_message](#edit_message)
    - [edit_message_keyboard](#edit_message_keyboard)
    - [pin_message](#pin_message)
    - [set_commands](#set_commands)
    - [send_calendar](#send_calendar)
    - [make_calendar](#make_calendar)
    - [parse_calendar_callback](#parse_calendar_callback)
- [Usage Example](#usage-example)
- [Calendar Date Picker Example](#calendar-date-picker-example)

## How to Use in Your Project

`TelegramBot` is a lightweight wrapper around the Telegram Bot API. Use it to send messages, files, and interactive buttons to Telegram groups or topics — or to poll for incoming updates (button clicks, messages).

### Quick Start Guide

1. **Import the Class**:
    ```python
    from vdx_auto_utils import TelegramBot
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

`TelegramBot` wraps the Telegram Bot HTTP API using the `requests` library. It supports sending text messages (with HTML formatting, inline buttons, and reply threading), sending files (with automatic type detection for photos, videos, and documents), polling for new updates, answering callback queries, editing existing messages in-place, pinning messages, registering slash commands, and fetching group admin lists.

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

#### `edit_message`
```python
def edit_message(self, group_id: str, message_id: int, text: str,
                 buttons: list = None) -> dict | None
```
Edits the text (and optionally the inline keyboard) of an existing message in-place. Use this to create an "updating panel" effect — the same message is reused rather than sending a new one.

- **Parameters:**
  - `group_id` (str): The Chat ID of the group or channel.
  - `message_id` (int): ID of the message to edit.
  - `text` (str): New message text. Supports HTML formatting.
  - `buttons` (list, optional):
    - `None` — leave the existing keyboard unchanged.
    - `[]` — remove the keyboard entirely.
    - `[...]` — replace the keyboard with this new layout.
- **Returns:** The Telegram API JSON response as a dict, or `None` on failure.

**Example:**
```python
# Replace text and remove the keyboard
bot.edit_message(GROUP_ID, msg_id, "✅ <b>Done!</b>", buttons=[])

# Replace text and attach a new keyboard
bot.edit_message(GROUP_ID, msg_id, "Pick a date:", buttons=bot.make_calendar(2026, 4))
```

---

#### `edit_message_keyboard`
```python
def edit_message_keyboard(self, group_id: str, message_id: int,
                          buttons: list) -> dict | None
```
Replaces the inline keyboard of an existing message **without changing its text**. More efficient than `edit_message` for calendar navigation (◀/▶) where only the month grid needs to change.

- **Parameters:**
  - `group_id` (str): The Chat ID of the group or channel.
  - `message_id` (int): ID of the message whose keyboard you want to update.
  - `buttons` (list): New keyboard layout. Pass `[]` to remove the keyboard entirely.
- **Returns:** The Telegram API JSON response as a dict, or `None` on failure.

**Example:**
```python
# Swap to a different month's grid without rewriting the caption
bot.edit_message_keyboard(GROUP_ID, msg_id,
    bot.make_calendar(result["year"], result["month"],
                      step=result["step"],
                      picked_start=result["picked_start"]))
```

---

#### `pin_message`
```python
def pin_message(self, group_id: str, message_id: int,
                silent: bool = True) -> dict | None
```
Pins a message in a group or channel.

- **Parameters:**
  - `group_id` (str): The Chat ID of the group or channel.
  - `message_id` (int): ID of the message to pin.
  - `silent` (bool, optional): If `True` (default), pins without notifying members.
- **Returns:** The Telegram API JSON response as a dict, or `None` on failure.

**Example:**
```python
resp = bot.send_message(GROUP_ID, "📌 This report will stay pinned.")
bot.pin_message(GROUP_ID, resp["result"]["message_id"])
```

---

#### `set_commands`
```python
def set_commands(self, commands: list) -> dict | None
```
Registers bot commands so they appear in Telegram's `/` autocomplete menu. Call this once at startup.

- **Parameters:**
  - `commands` (list): A list of dicts, each with `"command"` (without the leading `/`) and `"description"` keys.
- **Returns:** The Telegram API JSON response as a dict, or `None` on failure.

**Example:**
```python
bot.set_commands([
    {"command": "start",     "description": "Start the bot"},
    {"command": "runreport", "description": "▶️ Run the bank sync report"},
    {"command": "setdate",   "description": "📅 Set the date range"},
    {"command": "status",    "description": "📊 Show current settings"},
])
```

---

#### `send_calendar`
```python
def send_calendar(self, group_id: str, year: int, month: int,
                  title: str = "📅 Select a date:", topic_id: int = None,
                  step: str = "s", picked_start: str = "") -> dict | None
```
Sends a calendar date-picker message with an inline keyboard. The user taps a day and your bot receives a callback query that you decode with `parse_calendar_callback()`.

This is a convenience wrapper — it calls `make_calendar()` internally and passes the result to `send_message()`. All state (`step`, `picked_start`) is baked into each button's `callback_data` so the bot is fully stateless — it survives restarts and concurrent users.

- **Parameters:**
  - `group_id` (str): The Chat ID of the target group or channel.
  - `year` (int): The year of the month to display.
  - `month` (int): The month to display (1 = January … 12 = December).
  - `title` (str, optional): Caption shown above the keyboard. Defaults to `"📅 Select a date:"`.
  - `topic_id` (int, optional): Forum topic ID, if needed.
  - `step` (str, optional): `"s"` = picking the start date (default); `"e"` = picking the end date. Dates before `picked_start` are greyed out when `step="e"`.
  - `picked_start` (str, optional): Already-chosen start date in `"YYYY-MM-DD"` format. Only relevant when `step="e"`.
- **Returns:** The Telegram API JSON response as a dict, or `None` on failure.

**Example:**
```python
from datetime import date

today = date.today()

# Step 1 — ask for start date
resp = bot.send_calendar(GROUP_ID, today.year, today.month,
                         title="📅 <b>Step 1</b>: Select the start date:",
                         topic_id=TOPIC_ID, step="s")
msg_id = resp["result"]["message_id"]
```

---

#### `make_calendar`
```python
@staticmethod
def make_calendar(year: int, month: int,
                  step: str = "s", picked_start: str = "") -> list
```
Generates the raw inline keyboard layout for a calendar month. Returns a `list[list[dict]]` ready to pass directly to `send_message(buttons=...)`, `edit_message(buttons=...)`, or `edit_message_keyboard(buttons=...)`.

Use this when you need to swap the calendar grid on an existing message (e.g. after the user taps ◀ or ▶), rather than sending a new one.

**Keyboard layout:**

| Row | Content |
|-----|---------|
| 0 | `[◀]` `[Month YYYY]` `[▶]` — navigation bar |
| 1 | `[Mo]` `[Tu]` `[We]` `[Th]` `[Fr]` `[Sa]` `[Su]` — day headers (non-clickable) |
| 2–7 | Numbered day buttons; today shown as `[D]`; days before `picked_start` shown as `·` (non-clickable) when `step="e"` |

**Callback data format produced:**

| Tap | `callback_data` value |
|-----|-----------------------|
| A numbered day | `"cal:day:YYYY-MM-DD:STEP"` or `"cal:day:YYYY-MM-DD:STEP:START"` |
| ◀ or ▶ | `"cal:nav:YYYY-MM:STEP"` or `"cal:nav:YYYY-MM:STEP:START"` |
| Header / blank / month label | `"cal:ignore"` |

- **Parameters:**
  - `year` (int): Year to display.
  - `month` (int): Month to display (1–12).
  - `step` (str, optional): `"s"` = picking start date (default); `"e"` = picking end date.
  - `picked_start` (str, optional): Already-chosen start date (`"YYYY-MM-DD"`). Days before this are greyed out when `step="e"`.
- **Returns:** Nested list of button dicts for an inline keyboard.

**Example:**
```python
# Single date picker
buttons = bot.make_calendar(2026, 4)
bot.send_message(GROUP_ID, "Pick a date:", buttons=buttons)

# Date range — step 2 (grey out days before chosen start)
buttons = bot.make_calendar(2026, 4, step="e", picked_start="2026-04-10")
bot.send_message(GROUP_ID, "Now pick the end date:", buttons=buttons)
```

---

#### `parse_calendar_callback`
```python
@staticmethod
def parse_calendar_callback(data: str) -> dict
```
Decodes a `callback_data` string produced by `make_calendar()`. Call this inside your callback query handler to determine what the user tapped.

Because `make_calendar` bakes `step` and `picked_start` into every button, the dict returned here contains everything you need to respond — no external state variables required.

- **Parameters:**
  - `data` (str): The `callback_data` field from a Telegram callback query.
- **Returns:** A dict with an `"action"` key. Possible shapes:

| `action` | Extra keys | Meaning |
|----------|------------|---------|
| `"day"` | `"date"` (str, `"YYYY-MM-DD"`), `"step"` (str), `"picked_start"` (str) | User picked a date |
| `"nav"` | `"year"` (int), `"month"` (int), `"step"` (str), `"picked_start"` (str) | User navigated to a new month |
| `"ignore"` | — | User tapped a header, blank cell, or the month label |

**Example:**
```python
result = bot.parse_calendar_callback(query["data"])
bot.answer_callback_query(query["id"])

if result["action"] == "day" and result["step"] == "s":
    # Start date chosen — switch to end-date step
    bot.edit_message(chat_id, msg_id,
        f"Start: <b>{result['date']}</b> — now pick end date:",
        buttons=bot.make_calendar(int(result["date"][:4]), int(result["date"][5:7]),
                                  step="e", picked_start=result["date"]))

elif result["action"] == "day" and result["step"] == "e":
    # Both dates confirmed
    start, end = result["picked_start"], result["date"]
    bot.edit_message(chat_id, msg_id,
        f"✅ <b>{start}</b> → <b>{end}</b>", buttons=[])

elif result["action"] == "nav":
    bot.edit_message_keyboard(chat_id, msg_id,
        bot.make_calendar(result["year"], result["month"],
                          step=result["step"],
                          picked_start=result["picked_start"]))

else:
    pass  # "ignore" — callback already acknowledged, nothing to do
```

---

## Usage Example

```python
from vdx_auto_utils import TelegramBot

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

---

## Calendar Date Picker Example

This example shows the full flow for a date range picker (start → end) that edits a single message in-place rather than sending new ones. The calendar is stateless — all context is baked into the button `callback_data`, so the bot survives restarts and concurrent users without any variables to track.

```python
from vdx_auto_utils import TelegramBot
from datetime import date
import time

BOT_TOKEN = "YOUR_BOT_TOKEN"
GROUP_ID  = "-1001234567890"
TOPIC_ID  = 42  # omit if not using Forum Topics

bot   = TelegramBot(api_token=BOT_TOKEN)
today = date.today()

# ── Step 1: Send the initial calendar ────────────────────────────────────────
resp   = bot.send_calendar(GROUP_ID, today.year, today.month,
                           title="📅 <b>Set Date Range — Step 1 of 2</b>\nSelect the <b>start date</b>:",
                           topic_id=TOPIC_ID, step="s")
msg_id = resp["result"]["message_id"]

# ── Polling loop ──────────────────────────────────────────────────────────────
offset = None
while True:
    try:
        updates = bot.get_updates(offset=offset, timeout=30)
    except Exception as e:
        print(f"⚠️  Polling error: {e}")
        time.sleep(5)
        continue

    for update in updates:
        offset = update["update_id"] + 1
        try:
            query = update.get("callback_query")
            if not query:
                continue

            result     = bot.parse_calendar_callback(query["data"])
            chat_id    = str(query["message"]["chat"]["id"])
            message_id = query["message"]["message_id"]

            if result["action"] == "ignore":
                bot.answer_callback_query(query["id"])

            elif result["action"] == "nav":
                # User tapped ◀ or ▶ — swap only the keyboard grid
                bot.answer_callback_query(query["id"])
                bot.edit_message_keyboard(
                    chat_id, message_id,
                    bot.make_calendar(result["year"], result["month"],
                                      step=result["step"],
                                      picked_start=result["picked_start"]),
                )

            elif result["action"] == "day":
                bot.answer_callback_query(query["id"])

                if result["step"] == "s":
                    # Start date chosen — edit message to step 2
                    start = result["date"]
                    bot.edit_message(
                        chat_id, message_id,
                        f"📅 <b>Set Date Range — Step 2 of 2</b>\n"
                        f"Start: <b>{start}</b>\nSelect the <b>end date</b>:",
                        buttons=bot.make_calendar(int(start[:4]), int(start[5:7]),
                                                  step="e", picked_start=start),
                    )

                elif result["step"] == "e":
                    # Both dates confirmed — replace calendar with summary
                    start = result["picked_start"]
                    end   = result["date"]
                    bot.edit_message(
                        chat_id, message_id,
                        f"✅ <b>Date range selected:</b>\n\n"
                        f"Start: <b>{start}</b>\nEnd:   <b>{end}</b>",
                        buttons=[],
                    )
                    print(f"Range confirmed: {start} → {end}")
                    # ── Your logic here ──────────────────────────────────────

        except Exception as e:
            print(f"⚠️  Error on update {update.get('update_id')}: {e}")
```

### How the pieces fit together

```
bot.send_calendar(step="s")
    └─ calls make_calendar(year, month, step="s")   ← builds keyboard; state baked into each button
    └─ calls send_message(buttons=...)              ← sends to Telegram

User taps a button
    └─ Telegram sends a callback_query to your bot

bot.answer_callback_query()                         ← always call this first (10 s deadline)
bot.parse_calendar_callback(query["data"])
    ├─ action == "ignore" → do nothing
    ├─ action == "nav"    → edit_message_keyboard() with make_calendar() for new month
    └─ action == "day"
           ├─ step == "s" → edit_message() with make_calendar(step="e", picked_start=date)
           └─ step == "e" → edit_message(text=summary, buttons=[])  ← done!
```
