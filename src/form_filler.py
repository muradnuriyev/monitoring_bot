# form_filler.py
"""
Form filler that attempts to fill checkout / payment forms.
This is a best-effort helper: websites vary widely; code logs each step.
"""

import logging
import time
from selenium.webdriver.common.by import By
from selenium.common.exceptions import WebDriverException
from src.utils import safe_click, wait_for_element, safe_get_text

log = logging.getLogger(__name__)

def try_fill_simple_inputs(driver, cc_info):
    """
    Attempt to fill common input names (name, number, expiry, cvv, address, city, zip).
    Returns count of fields filled.
    """
    filled = 0
    field_map = {
        "name": ["name", "cardholder", "card-name", "cardholder-name", "fullName"],
        "number": ["cardnumber", "number", "card-number", "cc-number"],
        "expiry": ["expiry", "exp", "cardExpiry", "exp-date", "expiry-date"],
        "cvv": ["cvv", "cvc", "security-code"]
    }
    try:
        inputs = driver.find_elements(By.XPATH, "//input | //textarea | //select")
        for inp in inputs:
            try:
                if not inp.is_displayed():
                    continue
                n = (inp.get_attribute("name") or "").lower()
                pid = (inp.get_attribute("id") or "").lower()
                placeholder = (inp.get_attribute("placeholder") or "").lower()
                label = ""
                # attempt to find an associated <label>
                try:
                    lbl = driver.find_element(By.XPATH, f"//label[@for='{inp.get_attribute('id')}']")
                    label = (lbl.text or "").lower()
                except Exception:
                    pass

                field_ident = " ".join([n, pid, placeholder, label])
                # match each cc_info key
                for k, v in cc_info.items():
                    # allow typical keys like number, expiry, cvv, name, address, city, zip
                    if k.lower() in ["number", "cardnumber", "card_number", "card-number"] and "card" in field_ident or "number" in field_ident:
                        try:
                            inp.clear()
                            inp.send_keys(v)
                            filled += 1
                            log.info(f"[form_filler] Filled credit-card number field (matched '{field_ident[:40]}').")
                            break
                        except Exception:
                            continue
                    if k.lower() in ["name", "cardholder", "fullname"] and ("name" in field_ident or "cardholder" in field_ident):
                        try:
                            inp.clear()
                            inp.send_keys(v)
                            filled += 1
                            log.info(f"[form_filler] Filled name field.")
                            break
                        except Exception:
                            continue
                    if k.lower() in ["expiry", "exp", "expiry_date", "expiry-date"] and ("exp" in field_ident or "expiry" in field_ident):
                        try:
                            inp.clear()
                            inp.send_keys(v)
                            filled += 1
                            log.info("[form_filler] Filled expiry.")
                            break
                        except Exception:
                            continue
                    if k.lower() in ["cvv", "cvc", "security-code"] and ("cvv" in field_ident or "cvc" in field_ident):
                        try:
                            inp.clear()
                            inp.send_keys(v)
                            filled += 1
                            log.info("[form_filler] Filled CVV.")
                            break
                        except Exception:
                            continue
                # address / city / zip
                address_val = cc_info.get("address")
                city_val = cc_info.get("city")
                zip_val = cc_info.get("zip") or cc_info.get("postal")

                if address_val and "address" in field_ident:
                    try:
                        inp.clear()
                        inp.send_keys(address_val)
                        filled += 1
                        log.info("[form_filler] Filled address.")
                        continue
                    except Exception:
                        pass
                if city_val and "city" in field_ident:
                    try:
                        inp.clear()
                        inp.send_keys(city_val)
                        filled += 1
                        log.info("[form_filler] Filled city.")
                        continue
                    except Exception:
                        pass
                if zip_val and ("zip" in field_ident or "postal" in field_ident):
                    try:
                        inp.clear()
                        inp.send_keys(zip_val)
                        filled += 1
                        log.info("[form_filler] Filled zip/postal.")
                        continue
                    except Exception:
                        pass
            except Exception:
                continue
    except WebDriverException as e:
        log.warning(f"[form_filler] inputs scan error: {e}")
    return filled

def click_submit_button(driver):
    # Look for final submit / pay button and click it
    try:
        ctas = driver.find_elements(By.XPATH, "//button | //a")
        for c in ctas:
            if not c.is_displayed():
                continue
            txt = (c.text or "").lower()
            outer = (c.get_attribute("outerHTML") or "").lower()
            if any(tok in txt for tok in ["pay", "place order", "place order", "complete order", "submit payment", "confirm order", "pay $"]) \
               or any(tok in outer for tok in ["pay", "place-order", "submit-order", "checkout"]):
                if safe_click(driver, c, desc="final_submit"):
                    log.info("[form_filler] Clicked final submit button.")
                    return True
    except Exception as e:
        log.warning(f"[form_filler] click_submit_button error: {e}")
    log.info("[form_filler] No final-submit button found automatically.")
    return False

def fill_and_submit_form(driver, cc_info, settings=None):
    """
    High-level attempt: fill inputs, attempt to click final submit.
    This is best-effort and logs every step.
    """
    log.info("[form_filler] Attempting to autofill payment/checkout form...")
    try:
        filled_count = try_fill_simple_inputs(driver, cc_info)
        log.info(f"[form_filler] Filled ~{filled_count} fields (best-effort).")
        time.sleep(1.0)
        clicked = click_submit_button(driver)
        if clicked:
            log.info("[form_filler] Submitted payment (attempt).")
        else:
            log.info("[form_filler] Did not detect submit; stopping to allow manual completion.")
    except Exception as e:
        log.error(f"[form_filler] Exception during autofill: {e}")

