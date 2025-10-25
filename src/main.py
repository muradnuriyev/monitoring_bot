# main.py - console interface (run with `python -m src.main`)
import os
import json
import time
import logging

from src.monitor import check_product_and_buy

logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
log = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(BASE_DIR, "config")
PRODUCTS_FILE = os.path.join(CONFIG_DIR, "products.txt")
SETTINGS_FILE = os.path.join(CONFIG_DIR, "settings.json")
CC_FILE = os.path.join(CONFIG_DIR, "credit_card_info.txt")


def load_settings():
    if not os.path.exists(SETTINGS_FILE):
        return {
            "headless": False,
            "scroll_delay": 2,
            "max_scrolls": 3,
            "wait_for_page": 5,
            "retry_delay": 8,
            "retry_jitter": 4,
            "post_purchase_idle": 15,
            "use_undetected": True,
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            "min_match_score": 0.7,
            # compliance & stealth
            "respect_robots": False,
            "block_on_robots": True,
            "accept_language": "en-US,en;q=0.9",
            "randomize_window": True,
            "window_width": 1400,
            "window_height": 900,
            "user_data_dir": None,
            "profile_directory": None,
            "proxy": None,
            "challenge_strategy": "pause",  # pause | wait | backoff
            "challenge_pause_seconds": 60,
            "stop_on_success": True,
            "dismiss_banners": True,
            "allow_global_cta_when_name_found": True,
            "allow_global_cta_always": False,
            "select_size_before_global": True,
        }
    with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def load_credit_card():
    cc_info = {}
    if not os.path.exists(CC_FILE):
        return cc_info
    with open(CC_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if ":" in line:
                k, v = line.strip().split(":", 1)
                cc_info[k.strip()] = v.strip()
    return cc_info


def load_products():
    prods = []
    if not os.path.exists(PRODUCTS_FILE):
        return prods
    with open(PRODUCTS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            # accept format URL|Name|Size (size optional)
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 2:
                url = parts[0]
                name = parts[1]
                size = parts[2] if len(parts) >= 3 else None
                prods.append((url, name, size))
            else:
                log.warning(f"[WARN] Skipping malformed products.txt line: {line}")
    return prods


def view_products():
    prods = load_products()
    if not prods:
        print("[INFO] No products configured.")
        return
    for i, (u, n, s) in enumerate(prods, start=1):
        size_txt = f" (size: {s})" if s else ""
        print(f"{i}. {n} -> {u}{size_txt}")


def add_product():
    url = input("Enter product URL: ").strip()
    name = input("Enter product name: ").strip()
    size = input("Preferred size (optional): ").strip()
    entry = f"{url}|{name}|{size}" if size else f"{url}|{name}"
    with open(PRODUCTS_FILE, "a", encoding="utf-8") as f:
        f.write(entry + "\n")
    print("[INFO] Product added.")


def start_monitoring():
    prods = load_products()
    if not prods:
        print("[WARN] No products found. Add one first.")
        return
    print("\nSelect a product to monitor:\n")
    for i, (u, n, s) in enumerate(prods, start=1):
        size_txt = s if s else "-"
        print(f"{i}. {n} (size: {size_txt})")
    try:
        choice = int(input("\nYour choice: ")) - 1
    except Exception:
        print("[ERROR] Invalid input.")
        return
    if not (0 <= choice < len(prods)):
        print("[ERROR] Invalid selection.")
        return
    url, name, size = prods[choice]
    settings = load_settings()
    cc_info = load_credit_card()
    log.info(f"[INFO] Monitoring '{name}' at {url} (preferred size: {size})...")
    try:
        check_product_and_buy(url, name, settings, cc_info, preferred_size=size)
    except KeyboardInterrupt:
        log.info("[INFO] Monitoring stopped by user.")
    time.sleep(1)


def main_menu():
    while True:
        print("""
===============================
   UNIVERSAL PRODUCT MONITOR
===============================
1. View products
2. Add new product
3. Start monitoring
4. Exit
===============================
""")
        choice = input("Select an option: ").strip()
        if choice == "1":
            view_products()
        elif choice == "2":
            add_product()
        elif choice == "3":
            start_monitoring()
        elif choice == "4":
            print("Goodbye")
            break
        else:
            print("[ERROR] Invalid option.")
        time.sleep(0.3)


if __name__ == "__main__":
    main_menu()
