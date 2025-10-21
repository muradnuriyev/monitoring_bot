...existing code...
# Universal Product Monitor

Lightweight, site‑agnostic monitoring + autofill helper that scans product listing pages, opens product detail pages (PDPs), attempts to select a preferred size and click Add/Buy, and — optionally — attempts a best‑effort checkout autofill.

- Primary entry: [`main.main_menu`](src/main.py) — see [src/main.py](src/main.py)  
- Core detector: [`ai_detector.find_product_and_buy`](src/ai_detector.py) — see [src/ai_detector.py](src/ai_detector.py)  
- Monitoring loop + driver setup: [`monitor.check_product_and_buy`](src/monitor.py) and [`monitor.create_driver`](src/monitor.py) — see [src/monitor.py](src/monitor.py)  
- Autofill helper: [`form_filler.fill_and_submit_form`](src/form_filler.py) and [`form_filler.try_fill_simple_inputs`](src/form_filler.py) — see [src/form_filler.py](src/form_filler.py)  
- Utilities: [`utils.safe_click`](src/utils.py), [`utils.wait_for_element`](src/utils.py), [`utils.safe_get_text`](src/utils.py) — see [src/utils.py](src/utils.py)

Contents
- [README.md](README.md) — this file  
- [config/settings.json](config/settings.json) — runtime settings (headless, delays, sizes)  
- [config/products.txt](config/products.txt) — products to monitor (format: URL|Name|Size)  
- [config/credit_card_info.txt](config/credit_card_info.txt) — optional key:value lines used by autofill  
- [src/main.py](src/main.py) — CLI to view/add products and start monitoring  
- [src/monitor.py](src/monitor.py) — creates Chrome driver and runs monitoring loop  
- [src/ai_detector.py](src/ai_detector.py) — fuzzy product detection and buy flow initiation  
- [src/form_filler.py](src/form_filler.py) — best-effort form autofill & submit helper  
- [src/utils.py](src/utils.py) — small helpers (click, wait, highlight)  
- logs/ — run-time logs (if used by your environment)

Quick start

1. Install dependencies:
```sh
pip install selenium webdriver-manager undetected-chromedriver
```
2. Configure:
Edit config/settings.json to tune behavior (headless, delays, scrolls).
Add product lines to config/products.txt using URL|Name|Size (size optional).
Optionally populate config/credit_card_info.txt with payment fields in key: value form for autofill.


3. Run the CLI:

```python
python -m src.main
```

Choose "Start monitoring", select a product and the monitor will open Chrome and start scanning. The monitor uses ai_detector.find_product_and_buy to detect product cards, attempts to open PDPs, select sizes and click Add/Buy. If credit_card_info.txt is present the monitor will attempt autofill via form_filler.fill_and_submit_form.

Notes & safety

This project is for educational/testing on sites you control. Using automation on third‑party websites may violate terms of service and local laws.
The autofill/submit logic is heuristic and will not work for all checkout flows (frames, iframes, and strict anti-bot/ captcha protections).
To debug visually set "headless": false in config/settings.json.
If ChromeDriver fails, ensure Chrome is installed and compatible with the driver installed by webdriver-manager.
Troubleshooting

Increase timeouts in config/settings.json if pages load slowly.
Inspect logs and page state in the browser window (monitor keeps the browser open by default).
Key helpers: utils.safe_click logs every click attempt.
Development pointers

Add site-specific selectors or improve matching in ai_detector.find_product_and_buy.
Improve form mapping in form_filler.try_fill_simple_inputs for site-specific input names.
Use src/monitor.py to modify how the Chrome instance is created (create_driver).
License

Use as educational/demo code. Adapt responsibly.
...existing code...
