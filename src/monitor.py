# monitor.py
"""Main monitor flow. Keeps browser open for visual inspection and logs each step."""

import time
import logging
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
import undetected_chromedriver as uc

from src.ai_detector import find_product_and_buy

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')

def create_driver(settings):
    attempts = 0
    last_error = None
    while attempts < 3:
        try:
            options = webdriver.ChromeOptions()
            if settings.get("headless", False):
                options.add_argument("--headless=new")
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-gpu")
            options.add_argument("--disable-infobars")
            options.add_argument("--window-size=1400,900")
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_experimental_option('useAutomationExtension', False)
            options.add_argument("--remote-debugging-port=9222")
            options.add_argument("--disable-features=SameSiteByDefaultCookies,CookiesWithoutSameSiteMustBeSecure")


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
            time.sleep(2)
    raise RuntimeError(f"Failed to create Chrome driver after retries: {last_error}")


def _expand_monitor_urls(url):
    """Return list of URLs to monitor for a product.

    Nike launches often flip between `/launch/upcoming` and `/launch/in-stock`.
    When the product is supplied with the former we proactively watch both
    endpoints so we can react immediately once it becomes buyable.
    """
    urls = [url]
    if "/launch/upcoming" in url:
        alt = url.replace("/launch/upcoming", "/launch/in-stock")
        if alt not in urls:
            urls.append(alt)
    return urls


def check_product_and_buy(url, product_name, settings, cc_info, preferred_size=None):
    urls_to_monitor = _expand_monitor_urls(url)
    log.info(f"[INFO] Monitoring {product_name} at: {', '.join(urls_to_monitor)}")
    driver = create_driver(settings)
    try:
        try:
            driver.get(urls_to_monitor[0])
        except Exception as e:
            log.error(f"[ERROR] Failed to load {urls_to_monitor[0]}: {e}")
            return False

        log.info(f"[INFO] Navigated to {urls_to_monitor[0]}")
        time.sleep(settings.get("wait_for_page", 3))

        # continuous monitoring loop; stops when product buy flow triggered
        while True:
            try:
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
                    else:
                        log.info(f"[INFO] Checking {label} page: {target_url}")

                    log.info("[INFO] Checking for product availability...")
                    initiated = find_product_and_buy(
                        driver,
                        product_name,
                        preferred_size,
                        settings=settings,
                        cc_info=cc_info,
                    )
                    if initiated:
                        log.info(f"✅ Product '{product_name}' buy flow initiated.")
                        log.info("[INFO] Leaving browser open for manual/visual confirmation.")
                        return True

                log.info(f"⏳ Product '{product_name}' not yet buyable. Refreshing and retrying...")
                time.sleep(settings.get("retry_delay", 8))
                driver.refresh()
                time.sleep(settings.get("wait_for_page", 2))
            except KeyboardInterrupt:
                log.info("[INFO] Monitoring stopped by user.")
                return False
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
