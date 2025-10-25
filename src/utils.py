# utils.py
"""
Small Selenium helper utilities used across the project.

Includes:
- safe_click: click with logging and basic error handling
- wait_for_element: presence wait wrapper
- highlight_element: temporary outline to visualize targets during debug
- safe_get_text: robust text extractor
"""

import time
import logging
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import WebDriverException, TimeoutException, StaleElementReferenceException

logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
log = logging.getLogger(__name__)

def safe_click(driver, element, desc=None, timeout=0.5):
    """Attempt to click an element; log every attempt and any exception path."""
    try:
        desc_text = f" ({desc})" if desc else ""
        log.info(f"[ACTION] Clicking element{desc_text}: text='{element.text[:60]}'")
        element.click()
        time.sleep(timeout)
        log.info("[ACTION] Click successful.")
        return True
    except StaleElementReferenceException as e:
        log.warning(f"[WARN] Click failed (stale element): {e}")
        return False
    except WebDriverException as e:
        log.warning(f"[WARN] Click failed (webdriver): {e}")
        return False
    except Exception as e:
        log.error(f"[ERROR] Unexpected click error: {e}")
        return False

def wait_for_element(driver, by, selector, timeout=10):
    """Wait for an element to be present; return the element or None on timeout."""
    try:
        return WebDriverWait(driver, timeout).until(EC.presence_of_element_located((by, selector)))
    except TimeoutException:
        log.debug(f"[DEBUG] wait_for_element timeout for {selector}")
        return None

def highlight_element(driver, element, color="red", duration=1.0):
    """Visually outline element (for debugging), non-fatal if it fails."""
    try:
        driver.execute_script("""
            const el = arguments[0];
            const orig = el.style.boxShadow;
            el.style.boxShadow = '0 0 0 3px %s';
            setTimeout(()=> el.style.boxShadow = orig, %d);
        """ % (color, int(duration * 1000)), element)
    except Exception:
        pass

def safe_get_text(el):
    """Return stripped element text, or empty string on any exception."""
    try:
        return el.text.strip()
    except Exception:
        return ""
