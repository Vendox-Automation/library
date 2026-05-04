import logging
import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select

logger = logging.getLogger(__name__)

class Scraper:
    def __init__(self, headless=True, allow_media_perms=False, disable_noti=False, window_size: tuple = (1920, 1080)):
        """
        Initializes the Scraper with a pre-configured Chrome driver.

        Args:
            headless (bool): If True, runs the browser without a GUI. Defaults to True.
            allow_media_perms (bool): If True, enables media permissions in the browser for webcam purposes.
            disable_noti (bool): If True, will disable all notifications.
            window_size (tuple): Takes a tuple of (width, height) to set the browser window size. Defaults to (1920, 1080).
        """
        self.driver = self.setup_driver(headless=headless, allow_media_perms=allow_media_perms, disable_noti=disable_noti, window_size=window_size)

    def setup_driver(self, headless=True, allow_media_perms=False, disable_noti=False, window_size: tuple = (1920, 1080)):
        """
        Configures Chrome options for anti-detection and stability.

        Args:
            headless (bool): Whether to run in headless mode.
            disable_noti (bool): Whether to enable notifications.
            allow_media_perms (bool): Whether to allow media permissions for the browser.
            window_size (tuple): Sets window size according to given parameters.
        Returns:
            webdriver.Chrome: The initialized driver instance.
        """
        opts = Options()
        if headless:
            opts.add_argument("--headless=new")

        if disable_noti:
            opts.add_argument("--disable-infobars")
            opts.add_argument("--disable-notifications")
            opts.add_argument("--ignore-certificate-errors")

        opts.add_argument("--guest")
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_experimental_option("excludeSwitches", ["enable-automation"])
        opts.add_experimental_option("useAutomationExtension", False)

        opts.add_argument("--disable-gpu")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")

        # Camera/Mic Permissions via Preferences
        if allow_media_perms:
            prefs = {
                "profile.default_content_setting_values.media_stream_camera": 1,
                "profile.default_content_setting_values.media_stream_mic": 1,
            }
            opts.add_experimental_option("prefs", prefs)
            opts.add_argument("--use-fake-device-for-media-stream")
            opts.add_argument("--use-fake-ui-for-media-stream") # Auto-click "Allow" on the permission prompt

        driver = webdriver.Chrome(options=opts)
        driver.set_window_size(*window_size)
        driver.implicitly_wait(2)
        return driver

    # Helper methods (JS)
    def _fill_js(self, element, value):
        """Injects value via JS and dispatches input/change events."""
        self.driver.execute_script("arguments[0].value = arguments[1];", element, value)
        self.driver.execute_script("arguments[0].dispatchEvent(new Event('input', { bubbles: true }));", element)
        self.driver.execute_script("arguments[0].dispatchEvent(new Event('change', { bubbles: true }));", element)

    def _click_js(self, element):
        """Clicks an element directly via JavaScript."""
        self.driver.execute_script("arguments[0].click();", element)

    def _click_actions(self, element):
        """Scrolls element into view then clicks via ActionChains (bypasses overlays)."""
        from selenium.webdriver.common.action_chains import ActionChains
        ActionChains(self.driver).move_to_element(element).click().perform()

    def find_input(self, xpath: str, timeout=10):
        """
        Waits for an input field to appear and returns it.

        Args:
            xpath (str): The XPath of the element.
            timeout (int): Seconds to wait. Defaults to 10.
        Returns:
            WebElement or None: The found element or None if not found.
        """
        try:
            return WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((By.XPATH, xpath))
            )
        except Exception as e:
            logger.error(f"Input not found at {xpath}: {e}")
            return None

    def fill_input(self, element, value, use_js=False):
        """
        Clears and fills an input field with Selenium or JS injection.

        Args:
            element (WebElement): The Selenium element to fill.
            value (str): The text to enter.
            use_js (bool): If True, bypasses Selenium and uses JS immediately.
        """
        if not element:
            logger.info("No element provided to fill.")
            return

        if use_js:
            self._fill_js(element, value)
        else:
            try:
                element.clear()
                element.send_keys(value)
            except Exception as e:
                logger.warning(f"Standard fill failed, falling back to JS: {e}")
                self._fill_js(element, value)

    def get_text(self, xpath: str, timeout=10):
        """
        Waits for an element and returns its text.

        Args:
            xpath (str): The XPath of the element.
            timeout (int): Seconds to wait. Defaults to 10.
        Returns:
            str or None: The text content or None if not found.
        """
        try:
            element = WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((By.XPATH, xpath))
            )
            return element.text.strip()
        except Exception as e:
            logger.error(f"Could not get text from {xpath}: {e}")
            return None

    def select_option(self, xpath: str, option_text):
        """
        Selects an option from a dropdown by visible text.

        Args:
            xpath (str): The XPath of the select element.
            option_text (str): The visible text of the option to select.
        Returns:
            None
        """
        try:
            element = self.find_btn(xpath) # Wait for it to be clickable
            select = Select(element)
            select.select_by_visible_text(option_text)
            logger.info(f"Selected '{option_text}' from dropdown.")
        except Exception as e:
            logger.error(f"Failed to select option '{option_text}': {e}")

    def find_btn(self, xpath: str, timeout=10):
        """
        Waits for a button to be clickable and returns it.

        Args:
            xpath (str): The XPath of the button.
            timeout (int): Seconds to wait. Defaults to 10.
        Returns:
            WebElement or None: The found button or None if not found.
        """
        try:
            return WebDriverWait(self.driver, timeout).until(
                EC.element_to_be_clickable((By.XPATH, xpath))
            )
        except Exception as e:
            logger.error(f"Button not clickable at {xpath}: {e}")
            return None

    def click_btn(self, element, use_js=False):
        """
        Clicks an element using Selenium, ActionChains, or JavaScript — in that order.
        If use_js=True, skips straight to JS. Otherwise cascades through all three
        methods until one succeeds.

        Args:
            element (WebElement): The Selenium element to click.
            use_js (bool): If True, bypasses Selenium and ActionChains, uses JS immediately.
        """
        if not element:
            logger.info("No element provided to click.")
            return

        if use_js:
            self._click_js(element)
            return

        try:
            element.click()
            return
        except Exception as e:
            logger.warning(f"Standard click failed, trying ActionChains: {e}")

        try:
            self._click_actions(element)
            return
        except Exception as e:
            logger.warning(f"ActionChains click failed, falling back to JS: {e}")

        self._click_js(element)

    def find_and_click_btn(self, xpath: str, timeout=10, use_js=False):
        """
        Helper to find and click in one step.

        Args:
            xpath (str): The XPath to find.
            timeout (int): Seconds to wait.
            use_js (bool): Whether to use JS for the click.
        """
        btn = self.find_btn(xpath, timeout)
        if btn:
            self.click_btn(btn, use_js=use_js)

    def scan_and_close_popups(self, keywords: list) -> int:
        """
        Closes visible popups by scanning all interactive elements and clicking
        any whose attributes match the given keywords. Runs entirely in JS to
        bypass modal/overlay interception.

        Args:
            keywords (list[str]): Words matched against id/class/aria-label/title/alt/innerText.
        Returns:
            int: Number of elements clicked.
        """
        try:
            self.driver.execute_script("""
                const chatWidget = document.querySelector("#chat-widget-container");
                if (chatWidget) {
                    chatWidget.style.display = "none";
                    chatWidget.style.visibility = "hidden";
                    chatWidget.remove();
                }
            """)
        except Exception as e:
            logger.warning(f"Failed to suppress live chat widget: {e}")

        script = """
            const keywords = arguments[0];
            const regex = new RegExp("\\\\b(" + keywords.join("|") + ")\\\\b", "i");
            let count = 0;

            document.querySelectorAll("button,a,span,i,img,[role='button']").forEach(el => {
                try {
                    const combined = [
                        el.id || "",
                        el.className || "",
                        el.getAttribute("aria-label") || "",
                        el.getAttribute("title") || "",
                        el.getAttribute("alt") || "",
                        el.innerText || ""
                    ].join(" ");
                    if (regex.test(combined) && el.offsetParent !== null) {
                        el.click();
                        count++;
                    }
                } catch(e) {}
            });

            return count;
        """
        try:
            result = self.driver.execute_script(script, keywords)
            return result if isinstance(result, int) else 0
        except Exception as e:
            logger.error(f"scan_and_close_popups JS execution failed: {e}")
            return 0

    def wait_for_url(self, url_fragment: str, timeout: int = 10) -> bool:
        """
        Waits for the URL to change to one containing the given fragment.
        If no fragment is provided, waits for the URL to change to any other URL.

        Args:
            url_fragment (str) optional: The URL fragment to wait for.
            timeout (int): Seconds to wait. Defaults to 10.
        Returns:
            bool: True if the URL changed, False otherwise.
        """
        try:
            if not url_fragment:
                WebDriverWait(self.driver, timeout).until(EC.url_changes(self.driver.current_url))
                return True
            WebDriverWait(self.driver, timeout).until(EC.url_contains(url_fragment))
            return True
        except Exception:
            if url_fragment:
                logger.error(f"URL did not contain '{url_fragment}' within {timeout}s")
            else:
                logger.error(f"URL did not change within {timeout}s")
            return False

    def wait_for_element(self, xpath: str, timeout: int = 10):
        """
        Waits for an element to be present in the DOM.

        Args:
            xpath (str): The XPath of the element to wait for.
            timeout (int): Seconds to wait. Defaults to 10.
        Returns:
            bool: True if the element is present, False otherwise.
        """
        try:
            WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((By.XPATH, xpath))
            )
            return True
        except Exception:
            logger.error(f"Element not found: {xpath} within {timeout}s")
            return None

    def wait_for_element_hidden(self, xpath: str, timeout: int = 10) -> bool:
        """
        Waits for an element to be hidden from the DOM.

        Args:
            xpath (str): The XPath of the element to wait for.
            timeout (int): Seconds to wait. Defaults to 10.
        Returns:
            bool: True if the element is hidden, False otherwise.
        """
        try:
            WebDriverWait(self.driver, timeout).until(
                EC.invisibility_of_element_located((By.XPATH, xpath))
            )
            return True
        except Exception:
            logger.error(f"Element did not hide: {xpath} within {timeout}s")
            return False

    def quit(self):
        """Closes the driver session."""
        self.driver.quit()
