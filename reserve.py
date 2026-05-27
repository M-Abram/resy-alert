import os
import random
import shutil
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, List, Optional, Tuple

DEFAULT_RESY_URL = (
    "https://resy.com/cities/new-york-ny/venues/eyval"
    "?date=2026-05-23&seats=2"
)
DEFAULT_RESTAURANT_NAME = "Eyval"
USE_COLOR = sys.stdout.isatty()
GREEN = "\033[92m" if USE_COLOR else ""
RESET = "\033[0m" if USE_COLOR else ""
TIME_BUTTON_SELECTOR = "motion.div.ReservationButton__time, div.ReservationButton__time"
WAIT_MIN_SECONDS = int(os.environ.get("WAIT_MIN_SECONDS", "15"))
WAIT_MAX_SECONDS = int(os.environ.get("WAIT_MAX_SECONDS", "45"))
BROWSER_RECYCLE_EVERY = int(os.environ.get("BROWSER_RECYCLE_EVERY", "15"))
PAGE_LOAD_TIMEOUT_MS = int(os.environ.get("PAGE_LOAD_TIMEOUT_MS", "30000"))
SLOT_WAIT_TIMEOUT_MS = int(os.environ.get("SLOT_WAIT_TIMEOUT_MS", "10000"))
PAGE_WAIT_UNTIL = os.environ.get("PAGE_WAIT_UNTIL", "domcontentloaded")
BLOCK_MEDIA = os.environ.get("BLOCK_MEDIA", "true").lower() == "true"
LINUX_CHROMIUM_FALLBACK_PATHS = (
    "/usr/bin/chromium-browser",
    "/usr/bin/chromium",
    "/usr/bin/google-chrome-stable",
    "/snap/bin/chromium",
)
THINKING_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
THINKING_INTERVAL_SECONDS = 0.15


def load_reserve_env() -> None:
    env_path = Path(__file__).resolve().parent / "reserve.env"
    if not env_path.is_file():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


def get_resy_url() -> str:
    return os.environ.get("RESY_URL", DEFAULT_RESY_URL)


def get_restaurant_name() -> str:
    return os.environ.get("RESTAURANT_NAME", DEFAULT_RESTAURANT_NAME)


def stderr_color(code: str) -> str:
    return code if sys.stderr.isatty() else ""


def stderr_reset() -> str:
    return "\033[0m" if sys.stderr.isatty() else ""


def show_transient_status(message: str) -> None:
    print(f"\r{message}", end="", file=sys.stderr, flush=True)


def clear_transient_status() -> None:
    if sys.stderr.isatty():
        print("\r\033[K", end="", file=sys.stderr, flush=True)
    else:
        print(file=sys.stderr, flush=True)


class TransientAnimation:
    def __init__(self, message_fn: Callable[[str], str]) -> None:
        self.message_fn = message_fn
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        index = 0
        while not self._stop.is_set():
            frame = THINKING_FRAMES[index % len(THINKING_FRAMES)]
            show_transient_status(self.message_fn(frame))
            index += 1
            self._stop.wait(THINKING_INTERVAL_SECONDS)

    def __enter__(self) -> "TransientAnimation":
        self._thread.start()
        return self

    def __exit__(self, *args: object) -> None:
        self._stop.set()
        self._thread.join(timeout=THINKING_INTERVAL_SECONDS + 1)
        clear_transient_status()


def print_availability(slot_count: int) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if slot_count == 0:
        status = "No Availability"
    elif slot_count == 1:
        status = "Reservation Found"
    else:
        status = "Reservations Found"
    print(f"{GREEN}{now}{RESET} {status}", flush=True)


def print_monitoring_banner(backend: str) -> None:
    print(
        f"Monitoring {get_restaurant_name()} every {WAIT_MIN_SECONDS}-{WAIT_MAX_SECONDS}s "
        f"(browser restarts every {BROWSER_RECYCLE_EVERY} checks, backend={backend}). "
        "Press Ctrl+C to stop.",
        file=sys.stderr,
    )


def finalize_check_iteration(
    available: bool,
    slots: List[str],
    was_available: Optional[bool],
) -> bool:
    if not available:
        print_availability(0)
        return False

    print_availability(len(slots))
    for slot in slots:
        print(slot, flush=True)

    if was_available is not True:
        notify_slots_found(slots)

    return True


def configure_page_playwright(page: Any) -> None:
    if not BLOCK_MEDIA:
        return

    def skip_heavy_assets(route: Any, request: Any) -> None:
        if request.resource_type in {"image", "media", "font"}:
            route.abort()
        else:
            route.continue_()

    page.route("**/*", skip_heavy_assets)


def get_time_slots_playwright(page: Any) -> List[str]:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

    try:
        page.wait_for_selector(
            TIME_BUTTON_SELECTOR, timeout=SLOT_WAIT_TIMEOUT_MS
        )
    except PlaywrightTimeoutError:
        pass

    buttons = page.locator(TIME_BUTTON_SELECTOR)
    slots: List[str] = []
    seen: set[str] = set()
    for i in range(buttons.count()):
        text = buttons.nth(i).inner_text().strip()
        if text and text not in seen:
            seen.add(text)
            slots.append(text)
    return slots


def check_availability_playwright(
    page: Any, resy_url: Optional[str] = None
) -> Tuple[bool, List[str]]:
    url = resy_url or get_resy_url()
    page.goto(
        url,
        wait_until=PAGE_WAIT_UNTIL,
        timeout=PAGE_LOAD_TIMEOUT_MS,
    )
    slots = get_time_slots_playwright(page)
    return bool(slots), slots


def send_ntfy_notification(topic: str, title: str, message: str) -> None:
    server = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
    url = f"{server}/{topic}"
    request = urllib.request.Request(
        url,
        data=message.encode("utf-8"),
        method="POST",
        headers={
            "Title": title,
            "Priority": "high",
            "Tags": "restaurant,resy",
        },
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        response.read()


def notify_slots_found(slots: List[str]) -> None:
    topic = os.environ.get("NTFY_TOPIC")
    if not topic:
        print("Slots found. Set NTFY_TOPIC to send an ntfy notification.", file=sys.stderr)
        return

    restaurant = get_restaurant_name()
    resy_url = get_resy_url()
    times = ", ".join(slots)
    message = (
        f"{restaurant} has reservation slots available.\n\n"
        f"URL: {resy_url}\n"
        f"Times: {times}"
    )
    try:
        send_ntfy_notification(
            topic,
            title=f"Resy: {restaurant}",
            message=message,
        )
        print(f"Notification sent to ntfy topic '{topic}'.", file=sys.stderr)
    except urllib.error.URLError as error:
        print(f"Failed to send ntfy notification: {error}", file=sys.stderr)


def create_browser_session(playwright: Any) -> Tuple[Any, Any]:
    browser = playwright.chromium.launch(**chromium_launch_options_playwright())
    page = browser.new_page()
    configure_page_playwright(page)
    return browser, page


def linux_chromium_path() -> Optional[str]:
    if sys.platform != "linux":
        return None
    if os.environ.get("USE_PLAYWRIGHT_BUNDLED_CHROMIUM", "").lower() in (
        "1",
        "true",
        "yes",
    ):
        return None
    explicit = os.environ.get("CHROMIUM_EXECUTABLE", "").strip()
    if explicit:
        path = Path(explicit)
        if path.is_file():
            return str(path.resolve())
        print(
            f"CHROMIUM_EXECUTABLE not found: {explicit!r} — falling back "
            "to Playwright-managed Chromium.",
            file=sys.stderr,
        )
        return None
    for candidate in LINUX_CHROMIUM_FALLBACK_PATHS:
        path = Path(candidate)
        if path.is_file():
            return str(path.resolve())
    return None


def system_chromium_executable_for_selenium() -> Optional[str]:
    """Linux Chromium path for Selenium (ignores bundled-playwright flags)."""
    if sys.platform != "linux":
        return None
    explicit = os.environ.get("CHROMIUM_EXECUTABLE", "").strip()
    if explicit:
        path = Path(explicit)
        return str(path.resolve()) if path.is_file() else None
    for candidate in LINUX_CHROMIUM_FALLBACK_PATHS:
        path = Path(candidate)
        if path.is_file():
            return str(path.resolve())
    return None


def chromedriver_executable() -> Optional[str]:
    explicit = os.environ.get("CHROMEDRIVER_PATH", "").strip()
    if explicit:
        return explicit if Path(explicit).is_file() else None
    found = shutil.which("chromedriver")
    return found


def selenium_css_slot_selector() -> str:
    """Plain CSS for slot buttons (Playwright also matches motion.div → div in DOM)."""
    return "div.ReservationButton__time"


def chromium_launch_options_playwright() -> dict:
    options: dict = {
        "headless": os.environ.get("HEADLESS", "true").lower() == "true",
    }
    if sys.platform == "linux":
        options["args"] = ["--disable-dev-shm-usage", "--disable-gpu"]
        exe = linux_chromium_path()
        if exe:
            options["executable_path"] = exe
    return options


def run_check_playwright(page: Any, was_available: Optional[bool]) -> bool:
    blue = stderr_color("\033[94m")
    reset = stderr_reset()
    with TransientAnimation(
        lambda frame: f"{blue}Checking Website Now {frame}{reset}"
    ):
        available, slots = check_availability_playwright(page)
    return finalize_check_iteration(available, slots, was_available)


def random_wait_seconds() -> int:
    return random.randint(WAIT_MIN_SECONDS, WAIT_MAX_SECONDS)


def wait_with_countdown(seconds: int) -> None:
    blue = stderr_color("\033[94m")
    reset = stderr_reset()
    for remaining in range(seconds, 0, -1):
        show_transient_status(
            f"Waiting {blue}{remaining}{reset}s until next check"
        )
        time.sleep(1)
    clear_transient_status()


def main_playwright() -> None:
    from playwright.sync_api import sync_playwright

    print_monitoring_banner("playwright")
    was_available: Optional[bool] = None
    run_count = 0

    try:
        with sync_playwright() as playwright:
            browser, page = create_browser_session(playwright)
            try:
                while True:
                    run_count += 1
                    was_available = run_check_playwright(page, was_available)
                    wait_with_countdown(random_wait_seconds())
                    if run_count % BROWSER_RECYCLE_EVERY == 0:
                        browser.close()
                        browser, page = create_browser_session(playwright)
            finally:
                browser.close()
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)


def main() -> None:
    load_reserve_env()
    backend = os.environ.get("BROWSER_BACKEND", "playwright").strip().lower()
    if backend == "selenium":
        import importlib

        selenium_mod = importlib.import_module("reserve_selenium")
        selenium_mod.start_selenium_monitor()
        return

    main_playwright()


if __name__ == "__main__":
    main()
