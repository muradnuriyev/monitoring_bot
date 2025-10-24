# ai_detector.py
"""
Adaptive site-agnostic product detector + buyer helper.
This file's API:
  find_product_and_buy(driver, product_name, preferred_size=None, settings=None, cc_info=None)
Returns True if buy flow initiated (Add to Bag / Buy clicked and (optionally) checkout attempted).
"""

import re
import time
import logging
from difflib import SequenceMatcher
from selenium.webdriver.common.by import By
from selenium.common.exceptions import WebDriverException

from src.utils import safe_click, highlight_element, wait_for_element, safe_get_text

log = logging.getLogger(__name__)

def similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()

def extract_candidate_cards(driver, limit=400):
    """Return list of clickable product-like blocks (element, text)."""
    candidates = []
    try:
        els = driver.find_elements(By.XPATH, "//body//*[self::div or self::article or self::section or self::li][string-length(normalize-space())>0]")
        for el in els:
            try:
                text = safe_get_text(el)
                if not text:
                    continue
                imgs = el.find_elements(By.TAG_NAME, "img")
                # Heuristic: element looks like product card if contains image or several lines
                if imgs or "\n" in text:
                    candidates.append((el, text))
            except Exception:
                continue
    except WebDriverException as e:
        log.warning(f"[ai_detector] extract_candidate_cards webdriver error: {e}")
    return candidates

def scroll_into_view_and_wait(driver, el, pause=0.8):
    try:
        driver.execute_script("arguments[0].scrollIntoView({behavior:'smooth', block:'center'});", el)
        time.sleep(pause)
    except Exception:
        try:
            driver.execute_script("window.scrollBy(0, 300);")
            time.sleep(pause)
        except Exception:
            pass

def find_buy_button_in(element):
    try:
        # prefer buttons then links
        buttons = element.find_elements(By.XPATH, ".//button | .//a")
        for b in buttons:
            txt = safe_get_text(b).lower()
            if re.search(r"(add to bag|add to cart|add to basket|buy now|buy|shop now|checkout|purchase)", txt):
                return b
        # fallback: return first visible button-like
        for b in buttons:
            if b.is_displayed():
                return b
    except Exception:
        pass
    return None

def open_pdp_from_card(driver, card_el):
    """Try to open product page (PDP) by clicking image or link inside the card."""
    try:
        # click anchor if present
        anchors = card_el.find_elements(By.XPATH, ".//a")
        for a in anchors:
            href = a.get_attribute("href") or ""
            if href and href.strip().startswith("http"):
                log.info(f"[ai_detector] Opening PDP via anchor href: {href}")
                safe_click(driver, a, desc="open_pdp_anchor")
                time.sleep(1.2)
                return True
        # click image
        imgs = card_el.find_elements(By.TAG_NAME, "img")
        if imgs:
            log.info("[ai_detector] Clicking image to open PDP.")
            safe_click(driver, imgs[0], desc="open_pdp_image")
            time.sleep(1.2)
            return True
    except Exception as e:
        log.debug(f"[ai_detector] open_pdp_from_card failed: {e}")
    return False

def select_size_on_pdp(driver, preferred_size):
    """Try to select size on product detail page. Returns True if selected."""
    if not preferred_size:
        return False
    log.info(f"[ai_detector] Attempting to select preferred size: {preferred_size}")
    # normalize size token
    token = preferred_size.strip().lower()
    try:
        # common patterns for size buttons/inputs
        candidates = driver.find_elements(By.XPATH, "//button | //label | //a | //div")
        for c in candidates:
            try:
                if not c.is_displayed():
                    continue
                txt = safe_get_text(c).lower()
                # match exact text or contain numeric tokens
                if token in txt or re.search(r"\b" + re.escape(token) + r"\b", txt):
                    if safe_click(driver, c, desc=f"select_size:{txt[:20]}"):
                        time.sleep(0.8)
                        log.info("[ai_detector] Size element clicked.")
                        return True
            except Exception:
                continue

        # attribute-based search (data-size, aria-label)
        els = driver.find_elements(By.XPATH, "//*[contains(@aria-label, '')]")
        for e in els:
            try:
                aria = (e.get_attribute("aria-label") or "").lower()
                if token in aria:
                    if safe_click(driver, e, desc=f"size_by_aria:{aria[:30]}"):
                        time.sleep(0.7)
                        return True
            except Exception:
                continue
    except Exception as e:
        log.warning(f"[ai_detector] select_size_on_pdp error: {e}")
    log.info("[ai_detector] Preferred size not found/selectable automatically.")
    return False

def find_global_add_to_cart(driver):
    """Try to find standard add-to-cart / buy button on PDP."""
    # prefer big CTAs
    patterns = [
        r"add to bag", r"add to cart", r"add to basket",
        r"buy now", r"buy \u2014", r"buy", r"checkout", r"purchase", r"add"
    ]
    try:
        ctas = driver.find_elements(By.XPATH, "//button | //a")
        for c in ctas:
            try:
                if not c.is_displayed():
                    continue
                txt = safe_get_text(c).lower()
                outer = (c.get_attribute("outerHTML") or "").lower()
                for p in patterns:
                    if re.search(p, txt) or re.search(p, outer):
                        return c
            except Exception:
                continue
    except Exception:
        pass
    return None

def find_product_and_buy(driver, product_name: str, preferred_size: str = None, settings: dict = None, cc_info: dict = None) -> bool:
    """
    Full universal flow:
      1) scan page cards, fuzzy match best card
      2) if card has buy button -> click
      3) else open PDP, select size (if provided), click add to bag
      4) if buy flow reached and cc_info provided -> attempt autofill and submit
    Returns True if a buy/add CTA was clicked (and optionally checkout attempted).
    """
    log.info("[ai_detector] Starting search & buy flow...")
    target = product_name.strip().lower()
    max_scrolls = settings.get("max_scrolls", 10) if settings else 10
    scroll_delay = settings.get("scroll_delay", 1.0) if settings else 1.0
    min_score = settings.get("min_match_score", 0.9) if settings else 0.9

    best_match = None
    best_score = 0.0

    for pass_i in range(max_scrolls):
        log.info(f"[ai_detector] Scan pass {pass_i+1}/{max_scrolls}")
        cards = extract_candidate_cards(driver)
        # compute best fuzzy match
        for el, text in cards:
            score = similar(target, text)
            if score > best_score:
                best_score = score
                best_match = (el, text, score)
        log.info(f"[ai_detector] Best score so far: {best_score:.2f}")

        if best_match and best_score >= min_score:
            el, text, score = best_match
            log.info(f"[ai_detector] Possible match (score={score:.2f}): {text[:120]}...")
            highlight_element(driver, el, color="cyan", duration=1.0)
            scroll_into_view_and_wait(driver, el, pause=0.8)

            # look for buy inline
            buy_btn = find_buy_button_in(el)
            if buy_btn:
                highlight_element(driver, buy_btn, color="lime", duration=0.8)
                if safe_click(driver, buy_btn, desc="inline_buy"):
                    log.info("[ai_detector] Inline buy/add button clicked.")
                    return True

            # open PDP and attempt buy there
            if open_pdp_from_card(driver, el):
                # wait for PDP to settle
                time.sleep(settings.get("wait_for_page", 3) if settings else 3)
                # try select size
                selected = select_size_on_pdp(driver, preferred_size)
                if selected:
                    log.info("[ai_detector] Preferred size selected.")
                else:
                    log.info("[ai_detector] Preferred size not auto-selected (or not specified).")

                # find PDP add to cart
                add_btn = find_global_add_to_cart(driver)
                if add_btn:
                    highlight_element(driver, add_btn, color="lime", duration=0.8)
                    if safe_click(driver, add_btn, desc="pdp_add_to_cart"):
                        log.info("[ai_detector] PDP Add/Buy clicked.")
                        # optionally attempt autofill checkout if cc_info provided
                        if cc_info:
                            # delegate to form filler (import at runtime to avoid cycles)
                            try:
                                from src.form_filler import fill_and_submit_form
                                # small wait to let cart/modal appear
                                time.sleep(1.2)
                                fill_and_submit_form(driver, cc_info, settings=settings)
                            except Exception as e:
                                log.warning(f"[ai_detector] Autofill/checkout failed: {e}")
                        return True
                else:
                    log.info("[ai_detector] No add-to-cart CTA found on PDP after opening.")
            # if not clickable / PDP not opened, keep scanning / scroll
            log.info("[ai_detector] Will continue scanning / scrolling.")
        elif best_match:
            log.info(
                f"[ai_detector] Best fuzzy score {best_score:.2f} below threshold {min_score:.2f}; continuing scan."
            )
        # scroll to load more content
        try:
            driver.execute_script("window.scrollBy(0, Math.round(window.innerHeight * 0.9));")
        except Exception:
            pass
        time.sleep(scroll_delay)

    log.info("[ai_detector] Finished scans. No actionable buy CTA triggered.")
    return False
