"""Stealth web scraper built on nodriver.

nodriver drives a real Chrome over the DevTools Protocol with none of the
automation fingerprints Selenium leaves behind, so it clears Cloudflare
Turnstile / "Just a moment..." interstitials that block the Selenium-based
``Scraper``. This class wraps nodriver's async API in a synchronous facade so
callers keep the same blocking style as the legacy ``Scraper`` (no ``await``).

The legacy Selenium ``Scraper`` is intentionally left untouched; this is an
additive, opt-in backend. Method names mirror ``Scraper`` where practical so
existing flows are cheap to port.

Selector strings are auto-detected: anything starting with ``/``, ``(`` or
``./`` is treated as XPath, otherwise it is a CSS selector.

Note: nodriver is AGPL-3.0. Fine for internal use; review obligations before
shipping ``vdx_auto_utils`` to a third party or exposing it as a network
service.
"""

import asyncio
import json
import logging
import time
from pathlib import Path

import nodriver as uc
from nodriver import cdp

logger = logging.getLogger(__name__)


def _is_xpath(selector: str) -> bool:
    """True if the selector looks like an XPath expression rather than CSS."""
    return selector.lstrip().startswith(("/", "(", "./"))


class StealthScraper:
    def __init__(
        self,
        headless: bool = True,
        use_profile: bool = False,
        window_size: tuple = (1920, 1080),
        disable_noti: bool = False,
        allow_media_perms: bool = False,
    ):
        """
        Launches a nodriver-controlled Chrome and opens a blank tab.

        Args:
            headless (bool): Run without a visible window. Defaults to True.
            use_profile (bool): Persist the session to disk (chrome_profile/) so
                logins survive between runs. If False, a fresh temp profile is
                used each run. Defaults to False.
            window_size (tuple): (width, height) of the browser window.
            disable_noti (bool): Suppress notifications / infobars.
            allow_media_perms (bool): Auto-grant camera/mic with fake devices.
        """
        self._loop = asyncio.new_event_loop()
        # nodriver internals occasionally reach for the ambient loop; make ours it.
        asyncio.set_event_loop(self._loop)

        width, height = window_size
        args = [f"--window-size={width},{height}"]
        if disable_noti:
            args += ["--disable-notifications", "--disable-infobars"]
        if allow_media_perms:
            args += [
                "--use-fake-ui-for-media-stream",
                "--use-fake-device-for-media-stream",
            ]

        user_data_dir = None
        if use_profile:
            profile_path = Path.cwd() / "chrome_profile"
            profile_path.mkdir(parents=True, exist_ok=True)
            user_data_dir = str(profile_path)
            logger.info(f"Chrome profile loaded from: {profile_path}")

        config = uc.Config(
            headless=headless,
            user_data_dir=user_data_dir,
            browser_args=args,
        )
        # Deliberately no anti-detection flags / navigator.webdriver patch:
        # nodriver handles stealth natively and extra flags can re-trip detection.
        self.browser = self._run(uc.start(config=config))
        self.tab = self._run(self.browser.get("about:blank"))

    # ------------------------------------------------------------------ #
    # Async bridge
    # ------------------------------------------------------------------ #
    def _run(self, coro):
        """Drive one coroutine to completion on the persistent loop."""
        return self._loop.run_until_complete(coro)

    async def _visible(self, el) -> bool:
        """True if the element occupies layout space (is rendered)."""
        try:
            return bool(
                await el.apply(
                    "(e) => !!(e.offsetWidth || e.offsetHeight || "
                    "e.getClientRects().length)"
                )
            )
        except Exception:
            return False

    async def _afind(self, selector: str, timeout: float, visible: bool):
        """Poll for the first (optionally visible) match of an xpath/css selector."""
        is_xp = _is_xpath(selector)
        end = time.monotonic() + timeout
        while True:
            try:
                if is_xp:
                    els = await self.tab.xpath(selector)
                else:
                    els = await self.tab.select_all(selector, timeout=0.5)
            except Exception:
                els = []
            for el in els or []:
                if not visible or await self._visible(el):
                    return el
            if time.monotonic() >= end:
                return None
            await asyncio.sleep(0.3)

    # ------------------------------------------------------------------ #
    # Navigation
    # ------------------------------------------------------------------ #
    def get(self, url: str):
        """Navigate the active tab to a URL. Returns the nodriver tab."""
        self.tab = self._run(self.browser.get(url))
        return self.tab

    @property
    def current_url(self):
        """URL of the active tab, or None before the first navigation."""
        return self.tab.url if self.tab else None

    def refresh(self):
        """Reload the active tab."""
        self._run(self.tab.reload())

    def verify_cf(self, template_image: str = None):
        """
        Attempt to solve a Cloudflare Turnstile / interstitial on the current page
        using nodriver's native handler. Call after navigating to a CF-protected URL.
        """
        try:
            self._run(self.tab.verify_cf(template_image))
            return True
        except Exception as e:
            logger.warning(f"verify_cf failed: {e}")
            return False

    # ------------------------------------------------------------------ #
    # Finders (mirror Scraper names)
    # ------------------------------------------------------------------ #
    def find(self, selector: str, timeout: int = 10, visible: bool = True):
        """Return the first matching element, or None. Selector is xpath or CSS."""
        el = self._run(self._afind(selector, timeout, visible))
        if el is None:
            logger.error(f"Element not found: {selector} within {timeout}s")
        return el

    def find_all(self, selector: str, timeout: int = 10):
        """Return all matching elements (possibly empty)."""

        async def _all():
            if _is_xpath(selector):
                return await self.tab.xpath(selector)
            return await self.tab.select_all(selector, timeout=timeout)

        return self._run(_all()) or []

    # Aliases kept for parity with the Selenium Scraper API.
    def find_input(self, selector: str, timeout: int = 10):
        return self.find(selector, timeout)

    def find_btn(self, selector: str, timeout: int = 10):
        return self.find(selector, timeout)

    def wait_for_element(self, selector: str, timeout: int = 10):
        """True if the element appears within the timeout, else None."""
        return True if self.find(selector, timeout) else None

    def wait_for_element_hidden(self, selector: str, timeout: int = 10) -> bool:
        """True once the element is gone/invisible within the timeout."""

        async def _hidden():
            end = time.monotonic() + timeout
            while True:
                el = await self._afind(selector, 0.5, visible=True)
                if el is None:
                    return True
                if time.monotonic() >= end:
                    return False
                await asyncio.sleep(0.3)

        result = self._run(_hidden())
        if not result:
            logger.error(f"Element did not hide: {selector} within {timeout}s")
        return result

    def wait_for_url(self, url_fragment: str = "", timeout: int = 10) -> bool:
        """
        Wait until the tab URL contains ``url_fragment``. If no fragment is given,
        wait until the URL changes from the current one.
        """

        async def _wait():
            start_url = self.tab.url
            end = time.monotonic() + timeout
            while True:
                cur = self.tab.url
                if url_fragment:
                    if url_fragment in (cur or ""):
                        return True
                elif cur != start_url:
                    return True
                if time.monotonic() >= end:
                    return False
                await asyncio.sleep(0.3)

        result = self._run(_wait())
        if not result:
            if url_fragment:
                logger.error(f"URL did not contain '{url_fragment}' within {timeout}s")
            else:
                logger.error(f"URL did not change within {timeout}s")
        return result

    # ------------------------------------------------------------------ #
    # Actions
    # ------------------------------------------------------------------ #
    async def _js_fill(self, el, value):
        payload = json.dumps(value)
        await el.apply(
            "(e) => { e.value = %s; "
            "e.dispatchEvent(new Event('input', { bubbles: true })); "
            "e.dispatchEvent(new Event('change', { bubbles: true })); }" % payload
        )

    def fill_input(self, element, value, use_js: bool = False):
        """Clear and fill an input element (native, or JS injection on fallback)."""
        if not element:
            logger.info("No element provided to fill.")
            return

        async def _fill():
            if use_js:
                await self._js_fill(element, value)
                return
            try:
                await element.clear_input()
                await element.send_keys(value)
            except Exception as e:
                logger.warning(f"Standard fill failed, falling back to JS: {e}")
                await self._js_fill(element, value)

        self._run(_fill())

    def click_btn(self, element, use_js: bool = False):
        """
        Click an element, cascading native -> mouse -> JS until one works.
        With use_js=True, goes straight to a JS .click().
        """
        if not element:
            logger.info("No element provided to click.")
            return

        async def _click():
            if use_js:
                await element.apply("(e) => e.click()")
                return
            try:
                await element.click()
                return
            except Exception as e:
                logger.warning(f"Standard click failed, trying mouse_click: {e}")
            try:
                await element.mouse_click()
                return
            except Exception as e:
                logger.warning(f"mouse_click failed, falling back to JS: {e}")
            await element.apply("(e) => e.click()")

        self._run(_click())

    def find_and_click_btn(self, selector, timeout: int = 10, use_js: bool = False):
        """Find and click in one step. Accepts a single selector or a list to try in order."""
        if isinstance(selector, (list, tuple)):
            for s in selector:
                el = self.find(s, timeout=2)
                if el:
                    self.click_btn(el, use_js=use_js)
                    return True
            logger.error(f"None of the selectors were found: {selector}")
            return False
        el = self.find(selector, timeout)
        if el:
            self.click_btn(el, use_js=use_js)
            return True
        return False

    def get_text(self, selector: str, timeout: int = 10):
        """Return the stripped text of the first match, or None."""

        async def _text():
            el = await self._afind(selector, timeout, visible=False)
            if not el:
                return None
            try:
                await el.update()  # refresh cached node so .text is current
            except Exception:
                pass
            return (el.text or "").strip()

        result = self._run(_text())
        if result is None:
            logger.error(f"Could not get text from {selector}")
        return result

    def get_attribute(self, element, name: str):
        """Return an element attribute value via JS, or None."""
        return self.apply_to(element, f"(e) => e.getAttribute({json.dumps(name)})")

    def apply_to(self, element, js_function: str):
        """
        Run a JS function against an element and return its result. ``js_function``
        is a string like ``"(e) => e.someProp"`` — the element is passed as the sole
        argument. Sync escape hatch for callers holding a raw nodriver Element who
        can't await its (async) ``.apply()`` themselves.
        """
        if not element:
            return None
        return self._run(element.apply(js_function))

    def scroll_into_view(self, element):
        """Scroll an element into the viewport."""
        if not element:
            return
        self._run(element.scroll_into_view())

    def mouse_click(self, x: float, y: float, move_first: bool = True):
        """
        Dispatch a real synthetic mouse click at absolute page coordinates. Unlike
        a JS ``.click()``, this reaches content inside cross-origin iframes (e.g. a
        Cloudflare Turnstile checkbox), since CDP delivers it as a real input event.

        With ``move_first`` (default), the cursor is moved to the target over a
        short interpolated path before clicking — a teleported click with no
        preceding movement is a bot signal some widgets (e.g. Turnstile) key off.
        """
        if move_first:
            self._run(self.tab.mouse_move(x, y, steps=10))
        self._run(self.tab.mouse_click(x, y))

    async def _apierce_find_all(self, tag_name: str, attr_contains: str = None):
        """
        Walk the live DOM via CDP with shadow roots pierced — this sees through
        CLOSED shadow roots (e.g. declarative ``<template shadowrootmode="closed">``)
        that normal CSS/xpath queries (``find``/``find_all``) cannot. Matches by tag
        name and, if given, a substring anywhere in the node's attribute values
        (e.g. an iframe's ``src``). Returns raw CDP DOM nodes.
        """
        tag_name = tag_name.lower()
        await self.tab.send(cdp.dom.enable())
        doc = await self.tab.send(cdp.dom.get_document(depth=-1, pierce=True))
        found = []

        def walk(node):
            if (node.node_name or "").lower() == tag_name:
                attrs = node.attributes or []
                if not attr_contains or any(attr_contains in v for v in attrs[1::2]):
                    found.append(node)
            for root in node.shadow_roots or []:
                walk(root)
            for child in node.children or []:
                walk(child)
            if node.content_document:
                walk(node.content_document)

        walk(doc)
        return found

    def find_pierced(
        self, tag_name: str, attr_contains: str = None, timeout: float = 10
    ):
        """
        Locate an element even inside a CLOSED shadow root, by tag name and an
        optional attribute-value substring (e.g. ``find_pierced("iframe",
        "challenges.cloudflare.com")``). Returns its on-screen rect as
        ``{"x", "y", "width", "height"}`` (page/viewport CSS-pixel coordinates,
        suitable for ``mouse_click``), or None if not found within timeout.
        """

        async def _search():
            end = time.monotonic() + timeout
            while True:
                nodes = await self._apierce_find_all(tag_name, attr_contains)
                if nodes:
                    bm = await self.tab.send(
                        cdp.dom.get_box_model(backend_node_id=nodes[0].backend_node_id)
                    )
                    xs, ys = bm.content[0::2], bm.content[1::2]
                    return {
                        "x": min(xs),
                        "y": min(ys),
                        "width": max(xs) - min(xs),
                        "height": max(ys) - min(ys),
                    }
                if time.monotonic() >= end:
                    return None
                await asyncio.sleep(0.3)

        rect = self._run(_search())
        if rect is None:
            logger.error(f"Pierced search found no <{tag_name}> within {timeout}s")
        return rect

    def is_visible(self, element) -> bool:
        """True if the element is currently rendered."""
        if not element:
            return False
        return self._run(self._visible(element))

    def select_option(self, selector: str, option_text: str) -> bool:
        """Select an <option> by visible text on a native <select> element."""

        async def _select():
            el = await self._afind(selector, 10, visible=False)
            if not el:
                return False
            t = json.dumps(option_text)
            return bool(
                await el.apply(
                    "(sel) => { const t = %s.trim(); "
                    "for (let i = 0; i < sel.options.length; i++) { "
                    "if (sel.options[i].text.trim() === t) { "
                    "sel.selectedIndex = i; "
                    "sel.dispatchEvent(new Event('change', { bubbles: true })); "
                    "return true; } } return false; }" % t
                )
            )

        ok = self._run(_select())
        if ok:
            logger.info(f"Selected '{option_text}' from dropdown.")
        else:
            logger.error(f"Failed to select option '{option_text}'")
        return ok

    def evaluate(self, expression: str):
        """Run a JS expression in the page context and return the value."""
        return self._run(self.tab.evaluate(expression))

    def save_screenshot(self, path: str):
        """Save a screenshot of the active tab to ``path``."""
        return self._run(self.tab.save_screenshot(path))

    def scan_and_close_popups(self, keywords: list) -> int:
        """
        Close visible popups by scanning interactive elements and clicking any
        whose attributes/text match the given keywords. Runs entirely in JS.

        Args:
            keywords (list[str]): Matched against id/class/aria-label/title/alt/innerText.
        Returns:
            int: Number of elements clicked.
        """
        kw_json = json.dumps([str(k).lower() for k in keywords])
        js = """
        (() => {
            try {
                const c = document.querySelector("#chat-widget-container");
                if (c) c.remove();
            } catch (e) {}
            const keywords = %s;
            if (!keywords.length) return 0;
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
                } catch (e) {}
            });
            return count;
        })()
        """ % kw_json
        try:
            result = self._run(self.tab.evaluate(js))
            return int(result) if isinstance(result, (int, float)) else 0
        except Exception as e:
            logger.error(f"scan_and_close_popups JS execution failed: {e}")
            return 0

    # ------------------------------------------------------------------ #
    # Teardown
    # ------------------------------------------------------------------ #
    def quit(self):
        """Stop the browser and close the event loop."""
        try:
            self.browser.stop()
            # browser.stop() only *schedules* its cleanup coroutine (a fire-and-forget
            # create_task) rather than running it — give the loop one more beat so
            # that task actually executes before we close the loop out from under it.
            # Skipping this leaves the connection's background reader task dangling,
            # which then spins forever retrying recv() on the now-dead websocket.
            self._run(asyncio.sleep(0.3))
        except Exception as e:
            logger.warning(f"Browser stop failed: {e}")
        finally:
            try:
                self._loop.close()
            except Exception:
                pass
