# monitor.py
"""
Monitoring and browser orchestration.

This module is responsible for:
- Creating a Chrome driver (undetected or standard) with stealth-friendly options
- Detecting and responding to anti-bot challenges conservatively
- Respecting robots.txt if enabled
- Cycling through one or more URLs and delegating page actions to the detector
- Keeping the browser available for inspection unless configured to close
"""

import time
import logging
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from urllib.parse import urlparse
import urllib.robotparser as robotparser
import random
import undetected_chromedriver as uc

from src.ai_detector import find_product_and_buy

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')

def _build_chrome_options(settings, use_undetected):
    """
    Build a ChromeOptions object compatible with Selenium and undetected-chromedriver.

    Notes
    - Adds user-agent and language overrides to reduce basic bot signals.
    - Supports persistent profiles (user_data_dir/profile_directory) to retain cookies.
    - Allows an optional proxy and minimal window randomization to avoid a fixed fingerprint.
    """
    options = uc.ChromeOptions() if use_undetected else webdriver.ChromeOptions()

    if settings.get("headless", False):
        options.add_argument("--headless=new")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-infobars")
    # window size (optionally small randomization)
    base_w = int(settings.get("window_width", 1400))
    base_h = int(settings.get("window_height", 900))
    if settings.get("randomize_window", True):
        base_w += random.randint(-40, 40)
        base_h += random.randint(-30, 30)
    options.add_argument(f"--window-size={base_w},{base_h}")
    if settings.get("enable_remote_debugging", False):
        options.add_argument("--remote-debugging-port=9222")
    options.add_argument("--disable-features=SameSiteByDefaultCookies,CookiesWithoutSameSiteMustBeSecure")
    # user agent spoofing helps dodge Cloudflare bot heuristics
    user_agent = settings.get("user_agent")
    if user_agent:
        options.add_argument(f"--user-agent={user_agent}")
    # language
    lang = settings.get("accept_language")
    if lang:
        options.add_argument(f"--lang={lang}")
    # persistent user data dir
    user_data_dir = settings.get("user_data_dir")
    if user_data_dir:
        options.add_argument(f"--user-data-dir={user_data_dir}")
        profile_dir = settings.get("profile_directory")
        if profile_dir:
            options.add_argument(f"--profile-directory={profile_dir}")
    # proxy
    proxy = settings.get("proxy")
    if proxy:
        options.add_argument(f"--proxy-server={proxy}")

    if not use_undetected:
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)

    return options


def create_driver(settings):
    """
    Create and return a Chrome WebDriver.

    Behavior
    - Tries undetected-chromedriver first (when enabled), then falls back to standard Selenium
      Chrome if launch fails.
    - Retries limited times with logs preserved for debugging.
    """
    attempts = 0
    last_error = None
    use_undetected = settings.get("use_undetected", True)
    fell_back_to_standard = False
    while attempts < 3:
        try:
            options = _build_chrome_options(settings, use_undetected)

            if use_undetected:
                log.info("[INFO] Launching undetected Chrome to bypass Cloudflare checks...")
                driver = uc.Chrome(options=options, headless=settings.get("headless", False))
            else:
                driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
                driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
                    "source": """
                        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    """
                })

            log.info("[INFO] Chrome launched successfully.")
            return driver
        except Exception as e:
            attempts += 1
            last_error = e
            log.warning(f"[WARN] Launch attempt {attempts} failed: {e}")
            if use_undetected and not fell_back_to_standard and attempts < 3:
                log.info("[INFO] Falling back to standard Selenium Chrome driver for next attempt.")
                use_undetected = False
                fell_back_to_standard = True
            time.sleep(2)
    raise RuntimeError(f"Failed to create Chrome driver after retries: {last_error}")


def _robots_allows(url: str, user_agent: str = "*"):
    """Return True if robots.txt allows fetching the given URL for `user_agent`.

    Fail-open: when robots.txt cannot be retrieved, return True to avoid hard blocking
    (controlled by higher-level settings to stop when disallowed).
    """
    try:
        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        rp = robotparser.RobotFileParser()
        rp.set_url(robots_url)
        rp.read()
        return rp.can_fetch(user_agent, url)
    except Exception:
        return True


def _detect_challenge(driver) -> str:
    """Return a string describing detected anti-bot challenge, or '' if none."""
    try:
        title = (driver.title or "").lower()
        outer = (driver.page_source or "").lower()
    except Exception:
        return ""
    signals = [
        ("cloudflare", any(s in title or s in outer for s in [
            "checking your browser before accessing",
            "just a moment",
            "cf-browser-verification",
            "attention required",
            "please stand by",
        ])),
        ("captcha", any(s in outer for s in [
            "captcha",
            "g-recaptcha",
            "hcaptcha",
            "cf-chl-widget",
        ])),
    ]
    for name, present in signals:
        if present:
            return name
    return ""


def _handle_detected_challenge(driver, kind: str, settings: dict):
    """
    Conservative handler: pause and/or wait; never attempts to solve challenges.

    Strategies
    - pause: keep session alive and allow manual resolution
    - wait: poll briefly in case the provider clears after a delay
    - backoff: sleep with jitter before the next attempt
    """
    log.warning(f"[WARN] Detected potential anti-bot challenge: {kind}.")
    action = (settings or {}).get("challenge_strategy", "pause")
    if action == "pause":
        log.info("[INFO] Pausing for manual resolution. Leave this tab focused and solve if permitted.")
        time.sleep(int((settings or {}).get("challenge_pause_seconds", 60)))
        return
    if action == "wait":
        total = int((settings or {}).get("challenge_wait_total", 45))
        poll = float((settings or {}).get("challenge_wait_poll", 3))
        waited = 0
        while waited < total:
            time.sleep(poll)
            waited += poll
            if not _detect_challenge(driver):
                log.info("[INFO] Challenge cleared during wait.")
                break
        return
    if action == "backoff":
        delay = int((settings or {}).get("retry_delay", 8))
        jitter = int((settings or {}).get("retry_jitter", 4))
        sleep_s = max(1, delay + random.randint(-jitter, jitter))
        log.info(f"[INFO] Backing off for {sleep_s}s before next attempt.")
        time.sleep(sleep_s)
        return


def _expand_monitor_urls(url):
    """
    Return a small list of equivalent URLs to scan for the same product.

    Example: Nike launch pages sometimes flip between `/launch/upcoming` and
    `/launch/in-stock`. Watching both variants helps react as soon as it becomes
    buyable.
    """
    urls = [url]

    upcoming_variant = None
    instock_variant = None
    if "/launch/upcoming" in url:
        instock_variant = url.replace("/launch/upcoming", "/launch/in-stock")
    if "/launch/in-stock" in url:
        upcoming_variant = url.replace("/launch/in-stock", "/launch/upcoming")

    for candidate in (upcoming_variant, instock_variant):
        if candidate and candidate not in urls:
            urls.append(candidate)

    return urls


def check_product_and_buy(url, product_name, settings, cc_info, preferred_size=None):
    """
    High-level monitoring loop for a single product.

    Steps
    1) Optionally validate robots.txt
    2) Launch a Chrome session with stealth options
    3) Cycle through primary/alternate URLs and delegate page actions to the
       detector (`ai_detector.find_product_and_buy`)
    4) Stop immediately on first successful buy initiation when `stop_on_success` is true
    """
    urls_to_monitor = _expand_monitor_urls(url)
    log.info(f"[INFO] Monitoring {product_name} at: {', '.join(urls_to_monitor)}")
    # optional robots.txt compliance
    if settings.get("respect_robots", False):
        ua = settings.get("user_agent", "*")
        for candidate in urls_to_monitor:
            if not _robots_allows(candidate, ua):
                log.warning(f"[WARN] Blocked by robots.txt for URL: {candidate}")
                if settings.get("block_on_robots", True):
                    return False
    driver = create_driver(settings)
    purchase_initiated = False
    try:
        try:
            driver.get(urls_to_monitor[0])
        except Exception as e:
            log.error(f"[ERROR] Failed to load {urls_to_monitor[0]}: {e}")
            return False

        log.info(f"[INFO] Navigated to {urls_to_monitor[0]}")
        time.sleep(settings.get("wait_for_page", 3))
        ch = _detect_challenge(driver)
        if ch:
            _handle_detected_challenge(driver, ch, settings)

        # continuous monitoring loop; only stops when user interrupts or driver irrecoverably fails
        cycle = 0
        while True:
            try:
                cycle += 1
                log.info(f"[INFO] Scan cycle {cycle} starting.")
                for idx, target_url in enumerate(urls_to_monitor):
                    is_primary = idx == 0
                    label = "primary" if is_primary else "alternate"
                    if driver.current_url != target_url:
                        log.info(f"[INFO] Switching to {label} page: {target_url}")
                        try:
                            driver.get(target_url)
                        except Exception as nav_err:
                            log.error(f"[ERROR] Failed to navigate to {target_url}: {nav_err}")
                            continue
                        time.sleep(settings.get("wait_for_page", 3))
                        ch = _detect_challenge(driver)
                        if ch:
                            _handle_detected_challenge(driver, ch, settings)
                    log.info(f"[INFO] Scanning {label} page: {target_url}")

                    if purchase_initiated:
                        log.info("[INFO] Purchase already initiated; keeping browser open and continuing passive monitoring.")
                        continue

                    log.info("[INFO] Checking for product availability...")
                    initiated = find_product_and_buy(
                        driver,
                        product_name,
                        preferred_size,
                        settings=settings,
                        cc_info=cc_info,
                    )
                    if initiated:
                        purchase_initiated = True
                        if settings.get("stop_on_success", True):
                            log.info(f"[INFO] Product '{product_name}' buy flow initiated. stop_on_success enabled; ending monitoring loop.")
                            return True
                        log.info(f"✅ Product '{product_name}' buy flow initiated.")
                        log.info("[INFO] Continuing to keep the session active until you stop monitoring.")

                if not purchase_initiated:
                    log.info(f"⏳ Product '{product_name}' not yet buyable after cycle {cycle}. Refreshing and retrying...")
                    base = int(settings.get("retry_delay", 8))
                    jitter = int(settings.get("retry_jitter", 4))
                    sleep_s = max(1, base + random.randint(-jitter, jitter))
                    time.sleep(sleep_s)
                    driver.refresh()
                    time.sleep(settings.get("wait_for_page", 2))
                    ch = _detect_challenge(driver)
                    if ch:
                        _handle_detected_challenge(driver, ch, settings)
                else:
                    time.sleep(settings.get("post_purchase_idle", 15))
            except KeyboardInterrupt:
                log.info("[INFO] Monitoring stopped by user.")
                return purchase_initiated
            except Exception as e:
                log.error(f"[ERROR] Exception during monitoring: {e}")
                # attempt to recover by refreshing / short sleep; preserve driver so user can see logs
                try:
                    driver.refresh()
                except Exception:
                    # if driver lost, break and allow outer code to recreate it
                    log.error("[ERROR] Driver lost, exiting monitor loop.")
                    break
                time.sleep(3)
    finally:
        # do NOT auto-close so user can see what happened, unless settings force closure
        if settings.get("close_on_finish", False):
            try:
                log.info("[INFO] Closing Chrome.")
                driver.quit()
            except Exception:
                pass
