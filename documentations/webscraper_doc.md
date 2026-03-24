# Scraper Documentation

## Table of Contents
- [How to Use in Your Project](#how-to-use-in-your-project)
  - [Quick Start Guide](#quick-start-guide)
- [Overview](#overview)
- [Class: Scraper](#class-scraper)
  - [Initialization](#initialization)
  - [Methods](#methods)
    - [find_input](#find_input)
    - [fill_input](#fill_input)
    - [find_btn](#find_btn)
    - [click_btn](#click_btn)
    - [find_and_click_btn](#find_and_click_btn)
    - [get_text](#get_text)
    - [select_option](#select_option)
    - [scan_and_close_popups](#scan_and_close_popups)
    - [quit](#quit)
  - [Private Helper Methods](#private-helper-methods)
- [Class: SpoofScraper](#class-soofscraper)
- [Usage Example](#usage-example)

## How to Use in Your Project

`Scraper` gives you a pre-configured Chrome driver with sensible defaults for automation. All interaction methods handle their own waits, fallbacks, and error logging — so your scripts stay clean and readable.

### Quick Start Guide

1. **Import the Class**:
    ```python
    from functions.webscraper import Scraper
    ```

2. **Initialize**:
    ```python
    scraper = Scraper(headless=True)
    ```

3. **Navigate**:
    ```python
    scraper.driver.get("https://example.com")
    ```

4. **Interact**:
    ```python
    field = scraper.find_input("//input[@name='email']")
    scraper.fill_input(field, "hello@example.com")

    btn = scraper.find_btn("//button[@type='submit']")
    scraper.click_btn(btn)
    ```

5. **Read Results**:
    ```python
    result = scraper.get_text("//div[@class='confirmation']")
    print(result)
    ```

6. **Quit**:
    ```python
    scraper.quit()
    ```

---

## Overview

`Scraper` wraps Selenium's Chrome WebDriver with anti-detection settings, configurable options (headless mode, window size, media permissions, notifications), and a set of robust interaction helpers. Every method cascades through multiple fallback strategies (standard Selenium → ActionChains → JavaScript) before giving up, and logs errors rather than raising exceptions — making it resilient to flaky pages and dynamic UIs.

For sites that check browser fingerprints or user-agent strings, use `SpoofScraper` instead — it sets a realistic user-agent header on top of all the same features.

---

## Class: `Scraper`

### Initialization
```python
def __init__(self, headless: bool = True, allow_media_perms: bool = False,
             disable_noti: bool = False, window_size: tuple = (1920, 1080))
```
Creates and stores a configured Chrome WebDriver instance at `self.driver`.

- **Parameters:**
  - `headless` (bool): Run Chrome without a visible window. Set to `False` for debugging. Defaults to `True`.
  - `allow_media_perms` (bool): Auto-grants camera and microphone permissions. Useful for automating webcam-based flows. Defaults to `False`.
  - `disable_noti` (bool): Disables browser notifications and certificate error prompts. Defaults to `False`.
  - `window_size` (tuple): Browser window size as `(width, height)`. Defaults to `(1920, 1080)`.

---

### Methods

#### `find_input`
```python
def find_input(self, xpath: str, timeout: int = 10) -> WebElement | None
```
Waits for an input field to appear in the DOM and returns it.

- **Parameters:**
  - `xpath` (str): XPath of the target input element.
  - `timeout` (int): Max seconds to wait. Defaults to `10`.
- **Returns:** The `WebElement` if found, or `None` if it times out.

---

#### `fill_input`
```python
def fill_input(self, element: WebElement, value: str, use_js: bool = False)
```
Clears and fills an input element. Falls back to JavaScript injection automatically if standard Selenium input fails.

- **Parameters:**
  - `element` (WebElement): The element to fill (from `find_input`).
  - `value` (str): The text to type.
  - `use_js` (bool): If `True`, skips Selenium and uses JavaScript directly. Useful for React/Angular inputs that don't respond to `send_keys`. Defaults to `False`.

---

#### `find_btn`
```python
def find_btn(self, xpath: str, timeout: int = 10) -> WebElement | None
```
Waits for an element to be **clickable** (visible and enabled) and returns it.

- **Parameters:**
  - `xpath` (str): XPath of the target button or clickable element.
  - `timeout` (int): Max seconds to wait. Defaults to `10`.
- **Returns:** The `WebElement` if clickable, or `None` if it times out.

---

#### `click_btn`
```python
def click_btn(self, element: WebElement, use_js: bool = False)
```
Clicks an element using a cascade of strategies until one succeeds: standard Selenium click → ActionChains → JavaScript click.

- **Parameters:**
  - `element` (WebElement): The element to click.
  - `use_js` (bool): If `True`, jumps straight to JavaScript click, skipping the other methods. Useful for elements hidden behind overlays. Defaults to `False`.

---

#### `find_and_click_btn`
```python
def find_and_click_btn(self, xpath: str, timeout: int = 10, use_js: bool = False)
```
Convenience wrapper that combines `find_btn` and `click_btn` in a single call.

- **Parameters:**
  - `xpath` (str): XPath of the target element.
  - `timeout` (int): Max seconds to wait. Defaults to `10`.
  - `use_js` (bool): Whether to use JavaScript for the click. Defaults to `False`.

---

#### `get_text`
```python
def get_text(self, xpath: str, timeout: int = 10) -> str | None
```
Waits for an element to appear and returns its visible text content (stripped of leading/trailing whitespace).

- **Parameters:**
  - `xpath` (str): XPath of the target element.
  - `timeout` (int): Max seconds to wait. Defaults to `10`.
- **Returns:** The element's text as a string, or `None` if not found.

---

#### `select_option`
```python
def select_option(self, xpath: str, option_text: str)
```
Selects an option from a standard HTML `<select>` dropdown by its visible label text.

- **Parameters:**
  - `xpath` (str): XPath of the `<select>` element.
  - `option_text` (str): The exact visible text of the option to select (e.g. `"Malaysia"`).

---

#### `scan_and_close_popups`
```python
def scan_and_close_popups(self, keywords: list) -> int
```
Scans the page for visible interactive elements (buttons, links, spans, etc.) whose attributes or text match any of the provided keywords, then clicks them via JavaScript. Also silently removes any live chat widgets (`#chat-widget-container`). Entirely JavaScript-based to bypass modal overlays.

- **Parameters:**
  - `keywords` (list[str]): Words to match against element `id`, `class`, `aria-label`, `title`, `alt`, and `innerText`. Matching is case-insensitive and uses whole-word boundaries.
- **Returns:** The number of elements clicked.

**Example:**
```python
scraper.scan_and_close_popups(["close", "dismiss", "accept", "cookie"])
```

---

#### `quit`
```python
def quit(self)
```
Closes the browser and ends the WebDriver session. Always call this when done to free up resources.

---

### Private Helper Methods

These are used internally by the public methods and generally don't need to be called directly.

- **`_fill_js(element, value)`**: Injects a value into an input via JavaScript and dispatches `input` and `change` events to trigger framework reactivity (useful for React/Vue/Angular inputs).
- **`_click_js(element)`**: Clicks an element directly via JavaScript.
- **`_click_actions(element)`**: Scrolls the element into view and clicks it using Selenium ActionChains (bypasses overlay interception).
- **`setup_driver(...)`**: Configures and returns the Chrome WebDriver. Called automatically during `__init__`.

---

## Class: `SpoofScraper`

`SpoofScraper` is identical to `Scraper` in every way, with one addition: it sets a realistic Windows/Chrome user-agent string to reduce the chance of bot detection on sites that check the `User-Agent` header.

```python
from functions.webscraper import SpoofScraper

scraper = SpoofScraper(headless=True)
scraper.driver.get("https://target-site.com")
```

Use `SpoofScraper` as a drop-in replacement for `Scraper` when automation is being blocked or flagged.

---

## Usage Example

```python
from functions.webscraper import Scraper

scraper = Scraper(headless=True, disable_noti=True)

try:
    scraper.driver.get("https://example-portal.com/login")

    # Dismiss any popups
    scraper.scan_and_close_popups(["accept", "close", "cookie"])

    # Log in
    email_field = scraper.find_input("//input[@id='email']")
    scraper.fill_input(email_field, "user@company.com")

    pass_field = scraper.find_input("//input[@id='password']")
    scraper.fill_input(pass_field, "securepassword")

    scraper.find_and_click_btn("//button[@type='submit']")

    # Select a dropdown option
    scraper.select_option("//select[@id='region']", "Southeast Asia")

    # Read a result
    message = scraper.get_text("//div[@class='welcome-message']")
    print(f"Logged in: {message}")

finally:
    scraper.quit()
```