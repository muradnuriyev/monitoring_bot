# ai_detector.py
"""
Adaptive site-agnostic product detector and buyer helper.

Responsibilities
- Locate the target product on listing/PDP pages via fuzzy text matching
- Trigger purchase by clicking inline/near/global CTAs (avoid footer/help/notify links)
- Push the flow toward checkout and hand off to the form filler
- Provide conservative banner/overlay dismissal for better click success

Public API
- find_product_and_buy(driver, product_name, preferred_size=None, settings=None, cc_info=None)
  Returns True if a buy/add CTA was clicked (and optionally checkout attempted).
"""

import re
import time
import logging
from difflib import SequenceMatcher
from selenium.webdriver.common.by import By
from selenium.common.exceptions import WebDriverException, ElementClickInterceptedException

from src.utils import safe_click, highlight_element, wait_for_element, safe_get_text

log = logging.getLogger(__name__)

def similar(a: str, b: str) -> float:
    """Case-insensitive similarity score between two strings (0.0–1.0)."""
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
    """Scroll the element into view and pause briefly to allow layout settle."""
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
    """Find a likely buy/add button within the provided element subtree."""
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


def find_buy_button_near(driver, element, max_ancestors=3):
    """Search for a buy/add CTA near the given element by walking up ancestors."""
    try:
        ancestors = element.find_elements(By.XPATH, "./ancestor::*")
        ancestors = ancestors[:max_ancestors]
        for anc in ancestors:
            try:
                btn = find_buy_button_in(anc)
                if btn and btn.is_displayed():
                    return btn
            except Exception:
                continue
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


def find_global_buy_ctas(driver):
    """Return visible buy/add/checkout CTAs across the whole document."""
    patterns = [
        r"\badd to bag\b", r"\badd to cart\b", r"\badd to basket\b",
        r"\bbuy now\b", r"\bbuy\b", r"\bcheckout\b", r"\bpurchase\b",
        r"\bview bag\b", r"\bview cart\b", r"\bgo to cart\b",
    ]
    ctalist = []
    deny = [
        "notify me", "coming soon", "sold out", "out of stock",
        "payment options", "payment methods", "/help/", "help", "faq",
        "privacy", "terms", "learn more", "sign up", "join", "notify",
    ]
    try:
        ctas = driver.find_elements(By.XPATH, "//button | //a")
        for c in ctas:
            try:
                if not c.is_displayed():
                    continue
                txt = (c.text or "").lower()
                outer = (c.get_attribute("outerHTML") or "").lower()
                href = (c.get_attribute("href") or "").lower()
                if any(d in txt or d in outer or d in href for d in deny):
                    continue
                if any(re.search(p, txt) or re.search(p, outer) for p in patterns):
                    ctalist.append(c)
            except Exception:
                continue
    except Exception:
        pass
    return ctalist


def dismiss_banners(driver, settings=None):
    """Dismiss common cookie/consent banners or overlays to unblock CTAs."""
    if settings and settings.get("dismiss_banners") is False:
        return 0
    dismissed = 0
    tokens_btn = ["accept", "agree", "allow all", "got it", "ok", "i understand", "continue"]
    tokens_ctx = ["cookie", "consent", "gdpr", "privacy", "policy"]
    try:
        ctas = driver.find_elements(By.XPATH, "//button | //a | //div")
    except Exception:
        ctas = []
    for el in ctas:
        try:
            if not el.is_displayed():
                continue
            txt = (el.text or "").lower()
            outer = (el.get_attribute("outerHTML") or "").lower()
            if any(t in txt for t in tokens_btn) and any(c in outer or c in txt for c in tokens_ctx):
                if safe_click(driver, el, desc="dismiss_banner"):
                    dismissed += 1
        except Exception:
            continue
    # generic close
    try:
        closes = driver.find_elements(By.XPATH, "//*[@aria-label='Close' or @aria-label='Dismiss' or contains(@class,'close')]")
        for c in closes:
            try:
                if c.is_displayed() and safe_click(driver, c, desc="dismiss_close"):
                    dismissed += 1
            except Exception:
                continue
    except Exception:
        pass
    return dismissed


def page_contains_target(driver, product_name: str) -> bool:
    try:
        body = (driver.page_source or "").lower()
    except Exception:
        return False
    tokens = [t for t in product_name.lower().split() if t]
    return all(tok in body for tok in tokens) if tokens else False


def attempt_global_buy_flow(driver, product_name: str, preferred_size: str, settings: dict, cc_info: dict) -> bool:
    """Attempt a global buy without relying on a matched card: select size if possible, click CTA, checkout and submit."""
    try:
        if settings.get("select_size_before_global", True):
            try:
                select_size_on_pdp(driver, preferred_size)
            except Exception:
                pass
        buttons = find_global_buy_ctas(driver)
        if not buttons:
            return False
        btn = buttons[0]
        highlight_element(driver, btn, color="lime", duration=0.8)
        if safe_click(driver, btn, desc="global_buy_any"):
            progressed = proceed_to_checkout(driver, settings=settings)
            if cc_info:
                try:
                    from src.form_filler import fill_and_submit_form
                    time.sleep(1.0 if progressed else 0.7)
                    fill_and_submit_form(driver, cc_info, settings=settings)
                except Exception as e:
                    log.warning(f"[ai_detector] Autofill/checkout failed after global buy: {e}")
            return True
    except Exception:
        return False
    return False


def _is_footer(el) -> bool:
    try:
        anc = el.find_elements(By.XPATH, "./ancestor::*[self::footer or contains(translate(@class,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'footer')]")
        return len(anc) > 0
    except Exception:
        return False


def _dismiss_overlays(driver) -> int:
    dismissed = 0
    selectors = [
        "//*[@aria-label='Close' or @aria-label='Dismiss']",
        "//*[contains(@class,'close') or contains(@class,'modal-close') or contains(@class,'overlay-close')]",
        "//*[@role='dialog']//*[self::button or self::a]",
        "//*[contains(@class,'modal') or contains(@class,'overlay') or contains(@data-qa,'child-modal')]//button",
    ]
    for sx in selectors:
        try:
            for el in driver.find_elements(By.XPATH, sx):
                try:
                    if el.is_displayed():
                        el.click()
                        dismissed += 1
                except Exception:
                    continue
        except Exception:
            continue
    return dismissed


def proceed_to_checkout(driver, settings=None):
    """Attempt to follow any checkout/view-cart CTA after adding to bag."""
    wait_time = (settings or {}).get("checkout_cta_timeout", 10)
    poll_interval = 0.6
    end_time = time.time() + wait_time
    checkout_patterns = [
        r"\bcheckout\b", r"\bview bag\b", r"\bview cart\b", r"\bgo to cart\b",
        r"\bproceed\b", r"continue to checkout",
    ]
    deny = [
        "payment options", "payment methods", "/help/", "help", "faq", "privacy", "terms", "learn more"
    ]

    while time.time() < end_time:
        try:
            ctas = driver.find_elements(By.XPATH, "//button | //a")
        except Exception:
            ctas = []

        for cta in ctas:
            try:
                if not cta.is_displayed() or _is_footer(cta):
                    continue
                txt = safe_get_text(cta).lower()
                outer = (cta.get_attribute("outerHTML") or "").lower()
                href = (cta.get_attribute("href") or "").lower()
                if any(d in txt or d in outer or d in href for d in deny):
                    continue
                if any(re.search(pattern, txt) or re.search(pattern, outer) for pattern in checkout_patterns):
                    highlight_element(driver, cta, color="orange", duration=0.6)
                    try:
                        if safe_click(driver, cta, desc="checkout_transition"):
                            log.info("[ai_detector] Checkout/View Cart CTA clicked; waiting for checkout page...")
                            time.sleep((settings or {}).get("post_checkout_click_wait", 2))
                            return True
                    except ElementClickInterceptedException:
                        _dismiss_overlays(driver)
                        try:
                            driver.execute_script("arguments[0].click();", cta)
                            log.info("[ai_detector] JS-clicked checkout CTA after overlay dismissal.")
                            time.sleep((settings or {}).get("post_checkout_click_wait", 2))
                            return True
                        except Exception:
                            continue
            except Exception:
                continue

        time.sleep(poll_interval)

    log.info("[ai_detector] No checkout/view-cart CTA detected after adding to cart.")
    return False

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
    try:
        dismissed = dismiss_banners(driver, settings)
        if dismissed:
            log.info(f"[ai_detector] Dismissed {dismissed} banner(s).")
    except Exception:
        pass
    target = product_name.strip().lower()
    max_scrolls = settings.get("max_scrolls", 3) if settings else 3
    scroll_delay = settings.get("scroll_delay", 1.0) if settings else 1.0
    min_score = settings.get("min_match_score", 0.7) if settings else 0.7

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

        # opportunistic: try global CTA if allowed and target is visible somewhere, or forced
        allow_global_name = (settings or {}).get("allow_global_cta_when_name_found", True)
        allow_global_any = (settings or {}).get("allow_global_cta_always", False)
        if allow_global_any or (allow_global_name and page_contains_target(driver, product_name)):
            if attempt_global_buy_flow(driver, product_name, preferred_size, settings or {}, cc_info or {}):
                return True

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
                    progressed = proceed_to_checkout(driver, settings=settings)
                    if cc_info:
                        try:
                            from src.form_filler import fill_and_submit_form
                            time.sleep(1.2 if progressed else 0.8)
                            fill_and_submit_form(driver, cc_info, settings=settings)
                        except Exception as e:
                            log.warning(f"[ai_detector] Autofill/checkout failed after inline buy: {e}")
                    return True

            # try a nearby CTA if inline not found
            near_btn = find_buy_button_near(driver, el)
            if near_btn:
                highlight_element(driver, near_btn, color="lime", duration=0.8)
                if safe_click(driver, near_btn, desc="near_buy"):
                    log.info("[ai_detector] Nearby buy/add button clicked.")
                    progressed = proceed_to_checkout(driver, settings=settings)
                    if cc_info:
                        try:
                            from src.form_filler import fill_and_submit_form
                            time.sleep(1.2 if progressed else 0.8)
                            fill_and_submit_form(driver, cc_info, settings=settings)
                        except Exception as e:
                            log.warning(f"[ai_detector] Autofill/checkout failed after near buy: {e}")
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
                        progressed = proceed_to_checkout(driver, settings=settings)
                        if cc_info:
                            # delegate to form filler (import at runtime to avoid cycles)
                            try:
                                from src.form_filler import fill_and_submit_form
                                # small wait to let checkout elements stabilise
                                time.sleep(1.2 if progressed else 0.8)
                                fill_and_submit_form(driver, cc_info, settings=settings)
                            except Exception as e:
                                log.warning(f"[ai_detector] Autofill/checkout failed: {e}")
                        return True
                else:
                    log.info("[ai_detector] No add-to-cart CTA found on PDP after opening.")
                    # global fallback on PDP: try any visible CTA
                    globals_cta = find_global_buy_ctas(driver)
                    if globals_cta:
                        btn = globals_cta[0]
                        highlight_element(driver, btn, color="lime", duration=0.8)
                        if safe_click(driver, btn, desc="global_buy"):
                            progressed = proceed_to_checkout(driver, settings=settings)
                            if cc_info:
                                try:
                                    from src.form_filler import fill_and_submit_form
                                    time.sleep(1.2 if progressed else 0.8)
                                    fill_and_submit_form(driver, cc_info, settings=settings)
                                except Exception as e:
                                    log.warning(f"[ai_detector] Autofill/checkout failed after global buy: {e}")
                            return True
            # if not clickable / PDP not opened, try a global CTA as last resort
            globals_cta = find_global_buy_ctas(driver)
            if globals_cta:
                btn = globals_cta[0]
                highlight_element(driver, btn, color="lime", duration=0.8)
                if safe_click(driver, btn, desc="global_buy_list"):
                    progressed = proceed_to_checkout(driver, settings=settings)
                    if cc_info:
                        try:
                            from src.form_filler import fill_and_submit_form
                            time.sleep(1.2 if progressed else 0.8)
                            fill_and_submit_form(driver, cc_info, settings=settings)
                        except Exception as e:
                            log.warning(f"[ai_detector] Autofill/checkout failed after global buy on listing: {e}")
                    return True

            # if not clickable / no global CTA, keep scanning / scroll
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
