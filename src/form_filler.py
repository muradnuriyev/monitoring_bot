# form_filler.py
"""
Form filler that attempts to fill checkout / payment forms.
This is a best-effort helper: websites vary widely; code logs each step.
Enhancements:
- Fill common contact + shipping fields (email, phone, address, city, state, zip, country).
- Handle common card iframes (Stripe/Adyen/Braintree) by switching into frames to input card data.
- Attempt intermediate CTAs (Continue/Next/Review) before final Pay.
"""

import logging
import time
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    WebDriverException,
    NoSuchFrameException,
    ElementClickInterceptedException,
)
from src.utils import safe_click, wait_for_element, safe_get_text

log = logging.getLogger(__name__)

def _normalize_expiry(val: str) -> str:
    v = (val or "").strip().replace(" ", "").replace("-", "/").replace(".", "/")
    # accept 1226 or 12/26
    if len(v) == 4 and v.isdigit():
        return v[:2] + "/" + v[2:]
    if len(v) in (5, 7):
        return v
    return v


def _try_fill_contact_and_address(driver, cc_info) -> int:
    filled = 0
    try:
        inputs = driver.find_elements(By.XPATH, "//input | //textarea | //select")
    except Exception:
        inputs = []

    def matches(field_ident: str, keys):
        fi = field_ident.lower()
        return any(k in fi for k in keys)

    for inp in inputs:
        try:
            if not inp.is_displayed():
                continue
            n = (inp.get_attribute("name") or "").lower()
            pid = (inp.get_attribute("id") or "").lower()
            placeholder = (inp.get_attribute("placeholder") or "").lower()
            ftype = (inp.get_attribute("type") or "").lower()
            field_ident = " ".join([n, pid, placeholder, ftype])

            def fill(val):
                nonlocal filled
                try:
                    inp.clear()
                except Exception:
                    pass
                try:
                    inp.send_keys(val)
                    filled += 1
                    return True
                except Exception:
                    return False

            # handle <select> dropdowns for country/state
            try:
                tag = inp.tag_name.lower()
            except Exception:
                tag = ""
            if tag == "select":
                try:
                    sel = Select(inp)
                    # country
                    if cc_info.get("country") and ("country" in field_ident):
                        target = cc_info["country"].strip()
                        try:
                            sel.select_by_visible_text(target)
                        except Exception:
                            try:
                                sel.select_by_value(target)
                            except Exception:
                                pass
                        filled += 1
                        continue
                    # state/region/province
                    if cc_info.get("state") and any(k in field_ident for k in ["state", "region", "province"]):
                        target = cc_info["state"].strip()
                        try:
                            sel.select_by_visible_text(target)
                        except Exception:
                            try:
                                sel.select_by_value(target)
                            except Exception:
                                pass
                        filled += 1
                        continue
                except Exception:
                    pass

            # email
            if cc_info.get("email") and (matches(field_ident, ["email"]) or ftype == "email"):
                if fill(cc_info["email"]):
                    continue
            # phone
            if cc_info.get("phone") and (matches(field_ident, ["phone", "tel"]) or ftype in ("tel",)):
                if fill(cc_info["phone"]):
                    continue
            # first/last name
            if cc_info.get("first_name") and matches(field_ident, ["first", "given"]):
                if fill(cc_info["first_name"]):
                    continue
            if cc_info.get("last_name") and matches(field_ident, ["last", "family", "surname"]):
                if fill(cc_info["last_name"]):
                    continue
            if cc_info.get("name") and matches(field_ident, ["name", "fullname", "full-name", "cardholder"]):
                if fill(cc_info["name"]):
                    continue
            # address lines
            if cc_info.get("address") and matches(field_ident, ["address", "address1", "address-line1", "line1"]):
                if fill(cc_info["address"]):
                    continue
            if cc_info.get("address2") and matches(field_ident, ["address2", "address-line2", "line2"]):
                if fill(cc_info["address2"]):
                    continue
            # city/state/zip/country
            if cc_info.get("city") and matches(field_ident, ["city", "town"]):
                if fill(cc_info["city"]):
                    continue
            if cc_info.get("state") and matches(field_ident, ["state", "region", "province"]):
                if fill(cc_info["state"]):
                    continue
            postal = cc_info.get("zip") or cc_info.get("postal") or cc_info.get("postal_code")
            if postal and matches(field_ident, ["zip", "postal", "postcode"]):
                if fill(postal):
                    continue
            if cc_info.get("country") and matches(field_ident, ["country"]):
                if fill(cc_info["country"]):
                    continue
        except Exception:
            continue
    return filled


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
                    if k.lower() in ["number", "cardnumber", "card_number", "card-number"] and ("card" in field_ident or "number" in field_ident or "pan" in field_ident):
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
                    if k.lower() in ["expiry", "exp", "expiry_date", "expiry-date"] and ("exp" in field_ident or "expiry" in field_ident or "mm/yy" in field_ident):
                        try:
                            inp.clear()
                            inp.send_keys(_normalize_expiry(v))
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


def _try_fill_card_iframes(driver, cc_info) -> int:
    """Try to locate and fill common 3rd-party payment iframes (Stripe/Adyen/Braintree)."""
    filled = 0
    frames = []
    try:
        frames = driver.find_elements(By.TAG_NAME, "iframe")
    except Exception:
        pass
    if not frames:
        return 0

    for i, frame in enumerate(frames):
        try:
            src = (frame.get_attribute("src") or "").lower()
            name = (frame.get_attribute("name") or "").lower()
            title = (frame.get_attribute("title") or "").lower()
            outer = (frame.get_attribute("outerHTML") or "").lower()
            hints = ["stripe", "braintree", "adyen", "card", "payment"]
            if any(h in src or h in name or h in title or h in outer for h in hints):
                try:
                    driver.switch_to.frame(frame)
                except NoSuchFrameException:
                    continue
                try:
                    # inside frame, try to fill number/expiry/cvc
                    try:
                        number = driver.find_element(By.XPATH, "//input[contains(translate(@name,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'number') or contains(translate(@id,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'number') or contains(translate(@placeholder,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'number') or contains(., 'card number')]")
                        number.clear(); number.send_keys(cc_info.get("number", "")); filled += 1
                    except Exception:
                        pass
                    try:
                        exp = driver.find_element(By.XPATH, "//input[contains(translate(@name,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'exp') or contains(translate(@id,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'exp') or contains(translate(@placeholder,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'mm')]")
                        exp.clear(); exp.send_keys(_normalize_expiry(cc_info.get("expiry", ""))); filled += 1
                    except Exception:
                        # Some providers use separate MM / YY fields
                        try:
                            mm = driver.find_element(By.XPATH, "//input[contains(translate(@name,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'mm') or contains(translate(@placeholder,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'mm') or contains(translate(@aria-label,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'mm')]")
                            yy = driver.find_element(By.XPATH, "//input[contains(translate(@name,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'yy') or contains(translate(@placeholder,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'yy') or contains(translate(@aria-label,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'yy') or contains(translate(@name,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'year')]")
                            expv = _normalize_expiry(cc_info.get("expiry", ""))
                            parts = expv.split("/") if "/" in expv else [expv[:2], expv[-2:]]
                            if len(parts) == 2:
                                try:
                                    mm.clear(); mm.send_keys(parts[0]); filled += 1
                                except Exception:
                                    pass
                                try:
                                    yy.clear(); yy.send_keys(parts[1]); filled += 1
                                except Exception:
                                    pass
                        except Exception:
                            pass
                    try:
                        cvc = driver.find_element(By.XPATH, "//input[contains(translate(@name,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'cvc') or contains(translate(@id,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'cvc') or contains(translate(@placeholder,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'cvc') or contains(translate(@name,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'cvv')]")
                        cvc.clear(); cvc.send_keys(cc_info.get("cvv", "")); filled += 1
                    except Exception:
                        pass
                finally:
                    driver.switch_to.default_content()
        except Exception:
            try:
                driver.switch_to.default_content()
            except Exception:
                pass
            continue
    return filled


def _scroll_into_view(driver, el):
    try:
        driver.execute_script("arguments[0].scrollIntoView({behavior:'smooth', block:'center'});", el)
    except Exception:
        try:
            driver.execute_script("window.scrollBy(0, Math.round(window.innerHeight * 0.3));")
        except Exception:
            pass


def _dismiss_overlays(driver) -> int:
    """Dismiss overlays/modals that can block clicks (close buttons, dialogs, overlays)."""
    dismissed = 0
    selectors = [
        "//*[@aria-label='Close' or @aria-label='Dismiss']",
        "//*[contains(@class,'close') or contains(@class,'modal-close') or contains(@class,'overlay-close')]",
        "//*[@role='dialog']//*[self::button or self::a]",
        "//*[contains(@class,'modal') or contains(@class,'overlay') or contains(@data-qa,'child-modal')]//button",
    ]
    for sx in selectors:
        try:
            els = driver.find_elements(By.XPATH, sx)
        except Exception:
            els = []
        for el in els:
            try:
                if not el.is_displayed():
                    continue
                _scroll_into_view(driver, el)
                if safe_click(driver, el, desc="dismiss_overlay"):
                    dismissed += 1
            except Exception:
                continue
    return dismissed


def _choose_credit_card_tab(driver) -> bool:
    """If payment methods are tabbed, pick the credit card tab."""
    try:
        ctas = driver.find_elements(By.XPATH, "//button | //a | //div")
        for el in ctas:
            try:
                if not el.is_displayed():
                    continue
                txt = (el.text or "").lower()
                outer = (el.get_attribute("outerHTML") or "").lower()
                if any(k in txt for k in ["credit card", "card", "visa", "mastercard"]) or \
                   any(k in outer for k in ["credit-card", "payment-card"]):
                    if safe_click(driver, el, desc="select_cc_tab"):
                        time.sleep(0.8)
                        return True
            except Exception:
                continue
    except Exception:
        pass
    return False


def _select_shipping_method(driver, prefer_keywords=("standard", "free", "ground")) -> bool:
    """Select a shipping method radio/button; prefer standard/free if present."""
    try:
        candidates = driver.find_elements(By.XPATH, "//input[@type='radio'] | //button | //label")
    except Exception:
        candidates = []

    best = None
    for el in candidates:
        try:
            if not el.is_displayed():
                continue
            txt = (el.text or "").lower()
            outer = (el.get_attribute("outerHTML") or "").lower()
            joined = txt + " " + outer
            if any(k in joined for k in ["shipping", "delivery", "pickup", "method", "standard", "express", "overnight", "free"]):
                score = 0
                for kw in prefer_keywords:
                    if kw in joined:
                        score += 1
                best = (score, el) if (best is None or score >= best[0]) else best
        except Exception:
            continue
    if best:
        el = best[1]
        # click label, or ensure radio gets selected
        if safe_click(driver, el, desc="select_shipping"):
            time.sleep(0.6)
            return True
    return False


def _accept_terms(driver) -> int:
    """Tick common terms & conditions consent boxes if present."""
    accepted = 0
    try:
        inputs = driver.find_elements(By.XPATH, "//input[@type='checkbox'] | //label")
    except Exception:
        inputs = []

    keywords = ["terms", "conditions", "policy", "privacy", "agree", "gdpr"]
    for el in inputs:
        try:
            if not el.is_displayed():
                continue
            txt = (el.text or "").lower()
            outer = (el.get_attribute("outerHTML") or "").lower()
            if any(k in txt for k in keywords) or any(k in outer for k in keywords):
                if safe_click(driver, el, desc="accept_terms"):
                    accepted += 1
        except Exception:
            continue
    return accepted

def click_submit_button(driver):
    # Look for final submit / pay button and click it, avoiding footer/help links.
    import re as _re

    def is_footer(el):
        try:
            anc = el.find_elements(By.XPATH, "./ancestor::*[self::footer or contains(translate(@class,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'footer')]")
            return len(anc) > 0
        except Exception:
            return False

    phrases = [
        r"\bplace( your)? order\b",
        r"\bcomplete order\b",
        r"\bsubmit order\b",
        r"\bconfirm (and )?order\b",
        r"\bcomplete purchase\b",
        r"\bbuy now\b",
        r"\bpay now\b",
    ]
    deny = ["payment options", "payment methods", "/help/", "help", "faq", "policy", "privacy", "terms"]

    try:
        candidates = driver.find_elements(By.XPATH, "//button | //input[@type='submit' or @type='button'] | //a[@role='button'] | //*[@role='button']")
    except Exception:
        candidates = []

    scored = []
    for el in candidates:
        try:
            if not el.is_displayed():
                continue
            txt = (el.text or "").lower()
            outer = (el.get_attribute("outerHTML") or "").lower()
            href = (el.get_attribute("href") or "").lower()
            type_attr = (el.get_attribute("type") or "").lower()
            if is_footer(el):
                continue
            if any(d in txt or d in outer or d in href for d in deny):
                continue
            matched = any(_re.search(p, txt) or _re.search(p, outer) for p in phrases)
            boost = (type_attr == 'submit') or ('place-order' in outer) or ('submit-order' in outer)
            if matched or boost:
                score = (2 if boost else 1) + (1 if 'button' in outer else 0)
                scored.append((score, el))
        except Exception:
            continue

    scored.sort(key=lambda x: x[0], reverse=True)

    for _, btn in scored:
        try:
            _scroll_into_view(driver, btn)
            try:
                WebDriverWait(driver, 5).until(EC.element_to_be_clickable(btn))
            except Exception:
                pass
            if safe_click(driver, btn, desc="final_submit"):
                log.info("[form_filler] Clicked final submit button.")
                return True
        except ElementClickInterceptedException:
            _dismiss_overlays(driver)
            try:
                driver.execute_script("arguments[0].click();", btn)
                log.info("[form_filler] JS-clicked final submit button after overlay dismissal.")
                return True
            except Exception:
                continue
        except Exception as e:
            log.debug(f"[form_filler] submit click attempt error: {e}")

    # Fallback: generic submit inputs
    try:
        inputs = driver.find_elements(By.XPATH, "//input[@type='submit']")
        for i in inputs:
            if not i.is_displayed():
                continue
            _scroll_into_view(driver, i)
            try:
                i.click()
                log.info("[form_filler] Clicked generic submit input.")
                return True
            except Exception:
                continue
    except Exception:
        pass

    log.info("[form_filler] No final-submit button found automatically.")
    return False

def _click_intermediate_ctas(driver):
    """Try to click intermediate CTAs like Continue/Next/Review."""
    try:
        ctas = driver.find_elements(By.XPATH, "//button | //a")
        for c in ctas:
            if not c.is_displayed():
                continue
            txt = (c.text or "").lower()
            outer = (c.get_attribute("outerHTML") or "").lower()
            if any(k in txt for k in ["continue", "next", "review", "proceed", "shipping", "payment", "pay now"]) or \
               any(k in outer for k in ["continue", "next", "review", "proceed"]):
                if safe_click(driver, c, desc="intermediate_cta"):
                    time.sleep(1.0)
                    return True
    except Exception:
        pass
    return False


def _wait_for_order_confirmation(driver, settings=None) -> bool:
    """Wait briefly for confirmation page; return True if detected."""
    timeout = int((settings or {}).get("order_success_timeout", 30))
    poll = 1
    deadline = time.time() + timeout
    success_tokens = [
        "thank you", "order number", "order confirmed", "order placed",
        "confirmation", "we've received your order", "payment successful",
    ]
    while time.time() < deadline:
        try:
            src = (driver.page_source or "").lower()
            if any(tok in src for tok in success_tokens):
                return True
        except Exception:
            pass
        time.sleep(poll)
    return False


def fill_and_submit_form(driver, cc_info, settings=None):
    """
    High-level attempt: fill inputs, attempt to click final submit.
    This is best-effort and logs every step.
    """
    log.info("[form_filler] Attempting to autofill payment/checkout form...")
    try:
        # Step 1: contact + address
        contact_filled = _try_fill_contact_and_address(driver, cc_info)
        time.sleep(0.5)
        _click_intermediate_ctas(driver)
        time.sleep(0.8)

        # Step 2: shipping method (if any)
        if _select_shipping_method(driver):
            time.sleep(0.6)
            _click_intermediate_ctas(driver)
            time.sleep(0.8)

        # Step 3: payment method selection
        _choose_credit_card_tab(driver)
        time.sleep(0.6)

        # Step 4: card fields (in-page + iframes)
        base_filled = try_fill_simple_inputs(driver, cc_info)
        iframe_filled = _try_fill_card_iframes(driver, cc_info)
        filled_count = contact_filled + base_filled + iframe_filled
        log.info(f"[form_filler] Filled ~{filled_count} fields (best-effort).")
        time.sleep(0.8)

        # Terms checkboxes if required
        accepted = _accept_terms(driver)
        if accepted:
            log.info(f"[form_filler] Accepted {accepted} consent/terms checkbox(es).")

        # Step 5: submit order
        _click_intermediate_ctas(driver)
        time.sleep(0.6)
        _dismiss_overlays(driver)
        time.sleep(0.3)
        clicked = click_submit_button(driver)
        if clicked:
            log.info("[form_filler] Submitted payment (attempt).")
            # Optional: wait for confirmation
            if _wait_for_order_confirmation(driver, settings=settings):
                log.info("[form_filler] Order confirmation detected.")
        else:
            log.info("[form_filler] Did not detect submit; stopping to allow manual completion.")
    except Exception as e:
        log.error(f"[form_filler] Exception during autofill: {e}")

