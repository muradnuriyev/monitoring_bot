# Universal Product Monitor & Auto‑Buy

Automatically monitors product pages and purchases when available. The bot detects buy CTAs on listings, PDPs, or globally on the page, proceeds to checkout, autofills contact/shipping/payment, accepts terms, and submits the order.

- CLI entry: `src/main.py`
- Monitor + driver: `src/monitor.py`
- Detector + flow: `src/ai_detector.py`
- Autofill + submit: `src/form_filler.py`

## Features

- Buy anywhere: clicks inline card CTAs, nearby CTAs, PDP “Add to Cart”, and global “Buy/Checkout/View Bag/Cart” CTAs (while avoiding footer/help links and “Notify Me”).
- Full checkout: follows View Bag/Checkout, handles common overlays, proceeds through intermediate steps.
- Autofill: contact + shipping (with dropdowns), payment fields (in‑page + Stripe/Adyen/Braintree iframes), terms/consent checkboxes, final submit.
- Stealth & stability: undetected Chrome, realistic UA/language, window size randomization, persistent profile, optional proxy, jittered pacing, overlay dismissal, anti‑bot challenge detection.
- Stop on success: ends monitoring as soon as the buy flow starts (configurable).

## Requirements

- Python 3.9+
- Google Chrome installed

Install packages:

```bash
pip install selenium webdriver-manager undetected-chromedriver
```

## Configuration

### Products

`config/products.txt` — one product per line, format: `URL|Name|Size`

Example:

```
https://www.nike.com/launch/t/air-jordan-3|Air Jordan 3 Medium Olive|M 11 / W 12.5
```

### Payment

`config/credit_card_info.txt` — key: value pairs (one per line)

Required keys:
- `number`, `expiry` (MM/YY or MMYY), `cvv`

Helpful keys:
- `name` (or `first_name` + `last_name`), `email`, `phone`, `address`, `address2`, `city`, `state`, `zip` or `postal`, `country`

Example:

```
number: 4242424242424242
expiry: 12/26
cvv: 123
name: Jane Doe
email: jane@example.com
phone: +15555551234
address: 123 Main St
city: San Francisco
state: CA
zip: 94105
country: US
```

### Settings

`config/settings.json`

Common options:
- `headless`: run headless (set `false` to watch the browser)
- `use_undetected`: start undetected Chrome
- `user_agent`, `accept_language`: fingerprint hints
- `randomize_window`, `window_width`, `window_height`
- `max_scrolls`, `scroll_delay`, `wait_for_page`
- `min_match_score`: fuzzy name threshold (0.0–1.0)
- `retry_delay`, `retry_jitter`: pacing between cycles
- `stop_on_success`: stop scanning after buy starts (default true)
- `dismiss_banners`: auto‑close cookie/consent banners
- `allow_global_cta_when_name_found`: attempt global buy when target name is visible on the page
- `allow_global_cta_always`: attempt global buy even without a match (use with caution)
- `select_size_before_global`: try selecting preferred size before global buy
- `order_success_timeout`: seconds to wait for confirmation text after submit
- `respect_robots`, `block_on_robots`: optional robots.txt checks
- `user_data_dir`, `profile_directory`: persist sessions/cookies (recommended)
- `proxy`: `http(s)://user:pass@host:port` (static)

## Usage

Run the CLI:

```bash
python -m src.main
```

Choose “Start monitoring” and select your product. The bot opens Chrome, clicks a valid buy CTA (listing/PDP/global), follows View Bag/Checkout, fills forms, accepts terms, and submits.

## How It Works

- `src/monitor.py`
  - Launches a stealthy/stable Chrome instance (optional undetected), applies UA/language/window tuning, optional profile/proxy.
  - Optionally checks robots.txt. Detects Cloudflare/CAPTCHA interstitials and pauses/waits/backoffs per strategy.
  - Alternates across provided URL variants (e.g., upcoming/in‑stock), paces with jitter, and stops at first success when `stop_on_success` is true.

- `src/ai_detector.py`
  - Extracts candidate product blocks and fuzzy‑matches to your target name.
  - Clicks inline or near CTAs; opens PDP and selects preferred size; falls back to global CTAs (excluding footer/help/“Payment Options”/“Notify Me”).
  - Follows View Bag/Checkout CTAs (overlay‑aware; JS fallback if needed).

- `src/form_filler.py`
  - Fills contact/shipping (with dropdowns), selects shipping method, chooses the credit‑card tab, fills card fields in‑page and inside common third‑party iframes, accepts terms, and clicks the final submit. Waits briefly for an order confirmation message.

## Anti‑Bot & Compliance

- Uses undetected‑chromedriver, realistic UA/language, and persistent profiles to reduce friction.
- Detects Cloudflare/CAPTCHA interstitials; configurable handling: pause/wait/backoff. It does not solve challenges.
- Optional robots.txt checks to respect disallowed paths.

## Troubleshooting

- Set `headless: false` to watch the flow and tune selectors.
- If clicks are intercepted, the bot auto‑dismisses overlays and retries (including JS click). If a specific overlay persists, add it to the dismiss list.
- If login/3‑D Secure is required, set a persistent profile (`user_data_dir`) and complete it once manually; subsequent runs reuse the session.
- Ensure Chrome is installed; `webdriver-manager` downloads a compatible driver automatically.
- Adjust `min_match_score`, `max_scrolls`, `retry_delay`, and `retry_jitter` for speed vs. strictness.

## Notes & Safety

Use responsibly and only where permitted. Automation may be restricted by site Terms or local laws. Some checkout flows require manual completion (e.g., 3‑D Secure/OTP).

## Contributing

Site‑specific selectors greatly improve reliability. For a known store, add tailored selectors/steps in `src/ai_detector.py` and `src/form_filler.py` (or share details and we can add them).

