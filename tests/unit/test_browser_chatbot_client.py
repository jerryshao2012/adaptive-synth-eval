import asyncio
import threading

from adaptive_synth_eval.clients.browser_chatbot import BrowserChatbotClient
from adaptive_synth_eval.config.schemas import BrowserChatbot


class FakeLocator:
    def __init__(self, texts=None):
        self.texts = texts or []
        self.filled = []
        self.clicks = 0

    def count(self):
        return len(self.texts)

    def nth(self, index):
        return FakeLocator([self.texts[index]])

    def inner_text(self):
        return self.texts[-1]

    def fill(self, value):
        self.filled.append(value)

    def click(self):
        self.clicks += 1


class FakePage:
    def __init__(self):
        self.goto_calls = []
        self.thread_ids = []
        self.wait_calls = []
        self.input_locator = FakeLocator()
        self.submit_locator = FakeLocator()
        self.response_locator = FakeLocator(["old response", "new response"])

    def _record_thread(self):
        self.thread_ids.append(threading.get_ident())

    def goto(self, url, wait_until):
        self._record_thread()
        self.goto_calls.append((url, wait_until))

    def wait_for_selector(self, selector, timeout):
        self._record_thread()
        self.wait_calls.append((selector, timeout))

    def locator(self, selector):
        self._record_thread()
        if selector == "textarea":
            return self.input_locator
        if selector == "button[type='submit']":
            return self.submit_locator
        if selector == ".bot-message":
            return self.response_locator
        raise AssertionError(f"Unexpected selector: {selector}")

    def wait_for_function(self, script, arg, timeout):
        self._record_thread()
        self.wait_calls.append(("function", arg, timeout))
        self.response_locator.texts.append("fresh response")


class FakeBrowser:
    def __init__(self):
        self.page = FakePage()
        self.closed = False

    def new_page(self):
        return self.page

    def close(self):
        self.closed = True


class FakeChromium:
    def __init__(self, browser):
        self.browser = browser
        self.launch_kwargs = None

    def launch(self, **kwargs):
        self.launch_kwargs = kwargs
        return self.browser


class FakePlaywright:
    def __init__(self):
        self.browser = FakeBrowser()
        self.chromium = FakeChromium(self.browser)
        self.stopped = False

    def stop(self):
        self.stopped = True


class FakeSyncPlaywrightContext:
    def __init__(self, playwright):
        self.playwright = playwright

    def start(self):
        return self.playwright


def test_browser_chatbot_client_sends_message_with_edge_channel():
    fake_playwright = FakePlaywright()
    config = BrowserChatbot(
        url="https://chat.example.com",
        input_selector="textarea",
        submit_selector="button[type='submit']",
        response_selector=".bot-message",
        ready_selector="textarea",
        browser_type="edge",
        headless=True,
    )
    client = BrowserChatbotClient(
        browser_config=config,
        enabled=True,
        sync_playwright_factory=lambda: FakeSyncPlaywrightContext(fake_playwright),
    )

    response = client.send(
        conversation_id="c1",
        session_id="s1",
        turn_id=1,
        user_message="Hello",
    )
    client.close()

    assert fake_playwright.chromium.launch_kwargs == {"headless": True, "channel": "msedge"}
    assert fake_playwright.browser.page.goto_calls == [("https://chat.example.com", "domcontentloaded")]
    assert fake_playwright.browser.page.input_locator.filled == ["Hello"]
    assert fake_playwright.browser.page.submit_locator.clicks == 1
    assert response.bot_response == "fresh response"
    assert response.status_code == 200
    assert response.raw["browser"] is True
    assert fake_playwright.browser.closed is True
    assert fake_playwright.stopped is True


def test_browser_chatbot_client_async_calls_use_one_worker_thread():
    fake_playwright = FakePlaywright()
    config = BrowserChatbot(
        url="https://chat.example.com",
        input_selector="textarea",
        submit_selector="button[type='submit']",
        response_selector=".bot-message",
        browser_type="edge",
        headless=True,
    )
    client = BrowserChatbotClient(
        browser_config=config,
        enabled=True,
        sync_playwright_factory=lambda: FakeSyncPlaywrightContext(fake_playwright),
    )

    async def run_calls():
        await client.send_async(
            conversation_id="c1",
            session_id="s1",
            turn_id=1,
            user_message="Hello",
        )
        await client.send_async(
            conversation_id="c1",
            session_id="s1",
            turn_id=2,
            user_message="Again",
        )
        await client.close_async()

    asyncio.run(run_calls())

    assert len(set(fake_playwright.browser.page.thread_ids)) == 1
