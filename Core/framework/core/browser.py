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
            driver = webdriver.Chrome(options=options)
        elif normalized == "firefox":
            options = FirefoxOptions()
            if self.environment.headless:
                options.add_argument("-headless")
            driver = webdriver.Firefox(options=options)
        else:
            raise ValueError(f"Unsupported browser: {browser_name}")
        driver.set_page_load_timeout(self.environment.default_timeout_seconds)
        driver.implicitly_wait(0)
        return driver
