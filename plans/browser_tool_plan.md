# Headless Browser Tool — Implementation Plan

## Goal

Give the LLM a `browser_act` tool to control a headless Chrome browser for web automation, starting with **Shopee.sg** (product search, browsing, add-to-cart, checkout).

## Constraints

1. **Text-only feedback** — no multimodal image input to the LLM (for now)
2. **Persistent cookies/storage** — browser must survive restarts, keep login sessions
3. **Admin-only** — Telegram admin users only, never WhatsApp
4. **Target site** — Shopee.sg (phase 1)

## Environment

- **Python 3.14** with virtualenv at `v/`
- **Playwright 1.59.0** (sync + async APIs available)
- **Google Chrome** at `/usr/bin/google-chrome`
- **Existing pattern**: tools live in `tools/`, registered in `core_brain.py` as OpenAI-style function schemas, dispatched via `execute_tool()`

## Probe Findings (Shopee.sg)

- Login page (`/login`) loads fine in headless — username/password fields + login button accessible
- All browsing/search **requires login** — unauthenticated requests redirect to `verify/traffic/error`
- Login flow: username → password → OTP via SMS → success
- Stealth settings needed: disable `navigator.webdriver`, set real UA, proper viewport

---

## Architecture

```
Telegram User → Bot → LLM → browser_act() → Playwright (persistent Chrome) → Shopee.sg
                                      ↑
                              structured text feedback
                                      ↑
                          page state extraction
```

---

## Component 1: `tools/browser_manager.py` — Persistent Browser Singleton

**Purpose**: Manage a single long-lived Chrome browser with persistent user data dir.

**Key design**:
- Uses Playwright's `user_data_dir` for persistent cookies/localStorage
  - Survives browser restarts and bot restarts
- Stealth mode: disable webdriver flag, set real UA, viewport, locale
- Lazy init: browser starts on first tool call, stays open
- Async API (matches `core_brain.py`'s async `execute_tool`)
- Graceful shutdown on bot exit

**User data dir**: `/home/lenny/myp/telegram_bot/browser_data/`

**Class**: `BrowserManager` (singleton)

```python
class BrowserManager:
    _instance = None
    _playwright = None
    _browser = None
    _context = None
    _page = None
    _data_dir = "/home/lenny/myp/telegram_bot/browser_data"

    @classmethod
    async def get(cls) -> "BrowserManager":
        if cls._instance is None:
            cls._instance = cls()
            await cls._instance._init()
        return cls._instance

    async def _init(self):
        from playwright.async_api import async_playwright
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            channel="chrome",
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
            ],
        )
        self._context = await self._browser.new_context(
            user_data_dir=self._data_dir,
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.3400.0 Safari/537.36",
            locale="en-SG",
            timezone_id="Asia/Singapore",
        )
        # Disable navigator.webdriver detection
        await self._context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )
        self._page = await self._context.new_page()

    @property
    def page(self):
        return self._page

    @property
    def context(self):
        return self._context

    @classmethod
    async def close(cls):
        if cls._instance:
            if cls._context:
                await cls._context.close()
            if cls._browser:
                await cls._browser.close()
            if cls._playwright:
                await cls._playwright.stop()
            cls._instance = None
```

---

## Component 2: `tools/browser_page.py` — Page State Extractor

**Purpose**: Turn the current DOM into structured text the LLM can reason about.

**Function**: `extract_page_state(page) -> str`

**Output format**:

```
--- PAGE STATE ---
URL: https://shopee.sg/search?keyword=coffee+mug
Title: coffee mug - Shopee Singapore

HEADINGS:
  [H1] Coffee Mug
  [H2] Sort by: Most Relevant
  [H3] Filters

SEARCH BAR:
  [input] placeholder="Search for products, brands and shops" value="coffee mug"

PRODUCTS (visible):
  [1] "Stainless Steel Coffee Mug 350ml" - SGD 8.90 (1.2k sold, 4.8★)
      href: /Stainless-Steel-Coffee-Mug-i.12345.67890
  [2] "Ceramic Coffee Mug with Lid" - SGD 12.50 (856 sold, 4.7★)
      href: /Ceramic-Coffee-Mug-i.11111.22222

BUTTONS:
  [1] "Log In"
  [2] "Apply" (filter)
  [3] "Add to Cart"

LINKS:
  [1] "Categories" -> /categories
  [2] "Flash Sale" -> /sale

INPUTS:
  [1] [text] placeholder="Search..."
  [2] [number] placeholder="Quantity" value="1"
------------------
```

**Page-type detection** (auto-detected from URL/path):

| URL Pattern | Extractor | Special Data |
|---|---|---|
| `/search?*` | `extract_search_results()` | Product grid: name, price, sold count, rating, image URL |
| `/Product-Name-i.*` | `extract_product_details()` | Price, variants, description, reviews, shop info |
| `/cart` | `extract_cart()` | Cart items: name, price, qty, subtotal |
| `/checkout` | `extract_checkout()` | Order summary, shipping options, payment methods |
| `/login` | `extract_login_form()` | Login fields, social login options |
| default | `extract_generic()` | Headings + links + buttons + inputs |

---

## Component 3: Tool Schema (in `core_brain.py`)

Added to `ADMIN_TOOLS` only (Telegram admin users).

```python
{
    "type": "function",
    "function": {
        "name": "browser_act",
        "description": (
            "Control a headless browser to navigate websites, fill forms, click elements, "
            "and read page content. Returns the current page state as structured text after "
            "each action. The browser maintains persistent cookies/login state across calls. "
            "Use this for tasks like browsing Shopee, searching products, adding to cart, etc. "
            "IMPORTANT: Always call browser_get_state after navigate/wait to see the page "
            "before deciding what to click or fill."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "navigate",      # Go to a URL
                        "get_state",     # Read current page (headings, links, buttons, inputs, products)
                        "click",         # Click an element by number, text, or selector
                        "fill",          # Type text into an input by number, text, or selector
                        "submit",        # Submit the current form
                        "press_key",     # Press a key (Enter, Tab, Escape, etc.)
                        "go_back",       # Navigate back
                        "refresh",       # Reload the page
                        "scroll",        # Scroll down/up
                        "wait",          # Wait for page to load (seconds)
                        "select_option", # Select from a dropdown
                        "get_cookies",   # Check if logged in (debug)
                    ],
                },
                "url": {
                    "type": "string",
                    "description": "URL for navigate action (e.g., 'https://shopee.sg/login')"
                },
                "target": {
                    "type": "string",
                    "description": (
                        "Target element for click/fill. Can be: "
                        "'[1]' (numbered element from get_state output), "
                        "'Login' (visible text match), "
                        "'#search-input' (CSS selector), "
                        "'//button[contains(text(),\"Buy\")]' (XPath)"
                    )
                },
                "value": {
                    "type": "string",
                    "description": "Text to type into an input (for fill action)"
                },
                "key": {
                    "type": "string",
                    "description": "Key to press (Enter, Tab, Escape, ArrowDown, etc.)"
                },
                "direction": {
                    "type": "string",
                    "enum": ["up", "down"],
                    "description": "Scroll direction"
                },
                "seconds": {
                    "type": "number",
                    "description": "Wait time in seconds (default 2)"
                },
            },
            "required": ["action"],
        }
    }
}
```

---

## Component 4: Dispatch Logic (in `core_brain.py`)

```python
# In execute_tool():
elif tool_name == 'browser_act':
    args = json.loads(tc['function']['arguments'])
    result = await browser_act_handler(args)
    return format_msg(tool_call_id, result)
```

---

## Component 5: `tools/browser_act.py` — Action Handler

```python
async def browser_act(args: dict) -> str:
    """Execute a browser action and return page state as text."""
    action = args['action']
    browser = await BrowserManager.get()
    page = browser.page

    if action == 'navigate':
        await page.goto(args['url'], wait_until='domcontentloaded', timeout=30000)
        await page.wait_for_timeout(2000)

    elif action == 'get_state':
        return extract_page_state(page)

    elif action == 'click':
        target = await resolve_target(page, args['target'])
        await target.click()
        await page.wait_for_timeout(2000)

    elif action == 'fill':
        target = await resolve_target(page, args['target'])
        await target.fill(args['value'])

    elif action == 'submit':
        await page.press('body', 'Enter')
        await page.wait_for_timeout(3000)

    elif action == 'press_key':
        await page.keyboard.press(args['key'])
        await page.wait_for_timeout(1000)

    elif action == 'go_back':
        await page.go_back(timeout=15000)
        await page.wait_for_timeout(2000)

    elif action == 'refresh':
        await page.reload(wait_until='domcontentloaded')
        await page.wait_for_timeout(2000)

    elif action == 'scroll':
        direction = args.get('direction', 'down')
        delta = 500 if direction == 'down' else -500
        await page.evaluate(f'window.scrollBy(0, {delta})')
        await page.wait_for_timeout(1000)

    elif action == 'wait':
        seconds = args.get('seconds', 2)
        await page.wait_for_timeout(seconds * 1000)

    elif action == 'get_cookies':
        cookies = await page.context.cookies()
        return format_cookies(cookies)

    # Always return page state after navigation/mutation actions
    if action in ('navigate', 'click', 'submit', 'press_key', 'go_back', 'refresh', 'scroll'):
        return extract_page_state(page)

    return f"Action '{action}' completed."
```

### Target Resolution Strategy

```python
async def resolve_target(page, target):
    """Resolve a target string to a Playwright ElementHandle.

    Priority:
    1. '[N]' pattern → use pre-indexed elements from last get_state
    2. CSS selector (starts with #, ., or tag name) → page.locator()
    3. XPath (starts with //) → page.locator()
    4. Visible text match → page.get_by_text()
    """
    import re
    num_match = re.match(r'^\[(\d+)\]$', target)
    if num_match:
        idx = int(num_match.group(1)) - 1
        # Look up from cached indexed elements
        ...

    if target.startswith('//'):
        return await page.locator(target).first

    if target.startswith('#') or target.startswith('.') or (target[0].isalpha() and ' ' not in target):
        return await page.locator(target).first

    # Text-based: find element containing this text
    return await page.get_by_text(target).first
```

---

## Login Flow (End-to-End Example)

```
User (Telegram): "Log me into shopee.sg"

LLM → browser_act(navigate, "https://shopee.sg/login")
     ← gets page state showing login form with numbered inputs/buttons

LLM → browser_act(fill, target="[1]", value="+65XXXXXXXX")
LLM → browser_act(fill, target="[2]", value="mypassword")
LLM → browser_act(click, target="[1]")   (clicks "Log In" button)
     ← page state shows OTP input field

LLM → "I've sent the login request. Shopee is asking for an OTP.
       Please check your phone and send me the OTP code."
       (LLM reports back to user, waits for next message)

User (Telegram): "The OTP is 123456"

LLM → browser_act(fill, target="[1]", value="123456")
LLM → browser_act(submit)
     ← page state shows Shopee homepage (logged in!)
     → cookies saved to browser_data/ automatically

Future sessions: browser loads with saved cookies → already logged in ✅
```

---

## File Structure

```
tools/
  browser_act.py        ← action handler + resolve_target
  browser_manager.py    ← persistent browser singleton (async Playwright)
  browser_page.py       ← extract_page_state() + Shopee-specific extractors

core_brain.py           ← add browser_act to ADMIN_TOOLS + dispatch in execute_tool()
```

---

## Security

- **Admin-only** — `browser_act` in `ADMIN_TOOLS` only (Telegram, never WhatsApp)
- **Human-in-the-loop** for sensitive actions (payment confirmation, checkout)
- Consider adding a `require_confirmation` flag for checkout/payment actions

---

## Known Challenges & Mitigations

| Challenge | Mitigation |
|---|---|
| Shopee blocks headless browsers | Stealth flags + real UA + persistent session (login bypasses check) |
| OTP login required | LLM reports OTP request to user, user replies with code via Telegram |
| Session expiry (hours) | Detect redirect to login/verify page → LLM re-prompts user for credentials |
| Dynamic content / lazy loading | `wait` action + explicit scroll before `get_state` |
| Shopee changes DOM selectors | Text-based targeting (not CSS selectors) as primary method |
| Checkout/payment pages | May need special handling; consider human-in-the-loop for payment |
| Bot restart during browser session | `user_data_dir` persists cookies; browser re-launches with saved state |

---

## Implementation Order

1. **`tools/browser_manager.py`** — persistent browser singleton with stealth
2. **`tools/browser_page.py`** — generic page state extractor first, Shopee-specific extractors later
3. **`tools/browser_act.py`** — action handler with target resolution
4. **`core_brain.py`** — wire up tool schema to `ADMIN_TOOLS` + dispatch in `execute_tool()`
5. **Test** — login flow → search → product page → add to cart

---

## Future Enhancements

- **Screenshot support** — add base64 image to tool response for multimodal LLMs
- **Multiple browser profiles** — separate `browser_data/` dirs for different sites/accounts
- **Auto-login detection** — detect captcha/verification pages and alert user
- **Shopee API fallback** — use Shopee's unofficial API where possible (faster, more reliable)
- **Payment confirmation** — send Telegram notification before confirming checkout
- **Order tracking** — poll order status after purchase
