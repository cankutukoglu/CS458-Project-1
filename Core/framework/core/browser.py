from __future__ import annotations

from selenium import webdriver
from selenium.webdriver import ChromeOptions, FirefoxOptions

from framework.config.schema import EnvironmentConfig


class BrowserSession:
    """Creates browser instances using Selenium Manager."""

    def __init__(self, environment: EnvironmentConfig) -> None:
        self.environment = environment

    def start(self, browser_name: str):
        normalized = browser_name.lower()
        if normalized == "chrome":
            options = ChromeOptions()
            if self.environment.headless:
                options.add_argument("--headless=new")
            options.add_argument("--window-size=1440,1200")
            # Prevent Google/GitHub from detecting ChromeDriver and closing the session
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_experimental_option("useAutomationExtension", False)
            # Return as soon as DOM is interactive so OAuth redirects don't hit page-load timeout
            options.page_load_strategy = "eager"
            driver = webdriver.Chrome(options=options)
            # Remove navigator.webdriver at the JS level on every new document
            driver.execute_cdp_cmd(
                "Page.addScriptToEvaluateOnNewDocument",
                {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"},
            )
        elif normalized == "firefox":
            options = FirefoxOptions()
            if self.environment.headless:
                options.add_argument("-headless")
            options.page_load_strategy = "eager"
            driver = webdriver.Firefox(options=options)
        else:
            raise ValueError(f"Unsupported browser: {browser_name}")
        driver.set_page_load_timeout(self.environment.default_timeout_seconds)
        driver.implicitly_wait(0)
        return driver
