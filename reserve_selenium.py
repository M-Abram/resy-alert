"""
Selenium backend for ARM boards (e.g. Jetson) when installing Playwright is difficult.

Install:
  sudo apt install chromium-browser chromium-chromedriver   # names may vary by distro
  python3 -m venv .venv && .venv/bin/pip install selenium

reserve.env:
  BROWSER_BACKEND=selenium
"""

from __future__ import annotations

import os
import sys
from typing import List, Optional, Tuple

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException

from reserve import (
    BROWSER_RECYCLE_EVERY,
    SLOT_WAIT_TIMEOUT_MS,
    TransientAnimation,
    chromedriver_executable,
    finalize_check_iteration,
    get_resy_url,
    load_reserve_env,
    print_monitoring_banner,
    random_wait_seconds,
    selenium_css_slot_selector,
    stderr_color,
    stderr_reset,
    system_chromium_executable_for_selenium,
    wait_with_countdown,
)


def selenium_chrome_options() -> Options:
    options = Options()
    if os.environ.get("HEADLESS", "true").lower() == "true":
        options.add_argument("--headless=new")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-setuid-sandbox")
    options.add_argument("--window-size=1280,900")

    chromium = system_chromium_executable_for_selenium()
    if chromium:
        options.binary_location = chromium
    return options


def create_selenium_driver() -> webdriver.Chrome:
    options = selenium_chrome_options()
    path = chromedriver_executable()
    service = Service(executable_path=path) if path else Service()
    return webdriver.Chrome(service=service, options=options)


def get_time_slots_selenium(driver: webdriver.Chrome) -> List[str]:
    sel = selenium_css_slot_selector()
    wait_s = max(1.0, SLOT_WAIT_TIMEOUT_MS / 1000.0)
    try:
        WebDriverWait(driver, wait_s).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, sel))
        )
    except TimeoutException:
        pass

    slots: List[str] = []
    seen: set[str] = set()
    for el in driver.find_elements(By.CSS_SELECTOR, sel):
        text = (el.text or "").strip()
        if text and text not in seen:
            seen.add(text)
            slots.append(text)
    return slots


def check_availability_selenium(
    driver: webdriver.Chrome, resy_url: Optional[str] = None
) -> Tuple[bool, List[str]]:
    url = resy_url or get_resy_url()
    ms = max(5000, int(os.environ.get("PAGE_LOAD_TIMEOUT_MS", "30000")))
    driver.set_page_load_timeout(ms / 1000.0)
    driver.get(url)
    slots = get_time_slots_selenium(driver)
    return bool(slots), slots


def run_check_selenium(
    driver: webdriver.Chrome, was_available: Optional[bool]
) -> bool:
    blue = stderr_color("\033[94m")
    reset = stderr_reset()
    with TransientAnimation(
        lambda frame: f"{blue}Checking Website Now {frame}{reset}"
    ):
        available, slots = check_availability_selenium(driver)
    return finalize_check_iteration(available, slots, was_available)


def start_selenium_monitor() -> None:
    """Call after load_reserve_env()."""
    if not chromedriver_executable():
        print(
            "Chromedriver not found. Install: sudo apt install chromium-chromedriver\n"
            "Or set CHROMEDRIVER_PATH in reserve.env to the chromedriver binary.",
            file=sys.stderr,
        )
        sys.exit(1)

    print_monitoring_banner("selenium")
    run_count = 0
    was_available: Optional[bool] = None

    try:
        driver = create_selenium_driver()
        try:
            while True:
                run_count += 1
                was_available = run_check_selenium(driver, was_available)
                wait_with_countdown(random_wait_seconds())
                if run_count % BROWSER_RECYCLE_EVERY == 0:
                    driver.quit()
                    driver = create_selenium_driver()
        finally:
            driver.quit()
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)


def main() -> None:
    load_reserve_env()
    start_selenium_monitor()


if __name__ == "__main__":
    main()
