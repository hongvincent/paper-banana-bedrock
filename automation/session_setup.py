#!/usr/bin/env python
"""One-time manual login using a PERSISTENT Chromium profile.

The profile directory (.auth/user_data_dir/) stores cookies, service workers,
localStorage, IndexedDB — everything Google's bot detection looks at to
decide whether a session is a "real" browser. Reusing the same directory
across runs makes the profile look like a normal long-lived install.

Usage:
    python -m automation.session_setup

Opens a visible Chromium window pointed at the target URL, waits for Google
auth cookies to appear (auto-detect), then exits. The browser state persists
inside the dir for run_tabs to reuse.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SELECTORS_PATH = ROOT / "automation" / "selectors.json"
AUTH_DIR = ROOT / ".auth"
USER_DATA_DIR = AUTH_DIR / "user_data_dir"

LOGIN_TIMEOUT_S = 15 * 60

GOOGLE_AUTH_COOKIES = {
    "SID", "HSID", "SSID", "APISID", "SAPISID",
    "__Secure-1PSID", "__Secure-3PSID",
    "__Secure-1PSIDTS", "__Secure-3PSIDTS",
    "LSID",
}

STEALTH_INIT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'languages', { get: () => ['ko-KR','ko','en-US','en'] });
Object.defineProperty(navigator, 'plugins', {
    get: () => [{name:'Chrome PDF Plugin'},{name:'Chrome PDF Viewer'},{name:'Native Client'}]
});
window.chrome = { runtime: {}, loadTimes: () => ({}), csi: () => ({}), app: {} };
const origQuery = window.navigator.permissions && window.navigator.permissions.query;
if (origQuery) {
    window.navigator.permissions.query = (p) =>
        p.name === 'notifications'
            ? Promise.resolve({ state: Notification.permission })
            : origQuery(p);
}
"""

LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-default-browser-check",
    "--disable-infobars",
    "--disable-notifications",
    "--disable-extensions",
    "--lang=ko-KR",
]


async def _wait_for_input_ready(page, selectors: list[str], timeout_ms: int) -> str:
    for sel in selectors:
        try:
            await page.locator(sel).first.wait_for(state="visible", timeout=timeout_ms)
            return sel
        except Exception:  # noqa: BLE001
            continue
    raise TimeoutError("prompt input not visible — check selectors.json")


async def _wait_for_google_login(context, total_timeout_s: int, poll_interval_s: float = 2.0) -> list[str]:
    elapsed = 0.0
    last_hint = 0.0
    while elapsed < total_timeout_s:
        cookies = await context.cookies()
        names = {c["name"] for c in cookies}
        found = sorted(GOOGLE_AUTH_COOKIES & names)
        if found:
            return found
        if elapsed - last_hint >= 20:
            print(f"  ... waiting for login (elapsed {int(elapsed)}s, cookies: {len(names)})")
            last_hint = elapsed
        await asyncio.sleep(poll_interval_s)
        elapsed += poll_interval_s
    raise TimeoutError("timed out waiting for Google login")


async def capture_session(url: str, prompt_selectors: list[str]) -> None:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        sys.exit("playwright not installed. Run: pip install playwright && playwright install chromium")

    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as pw:
        context = await pw.chromium.launch_persistent_context(
            str(USER_DATA_DIR),
            headless=False,
            args=LAUNCH_ARGS,
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1440, "height": 900},
            locale="ko-KR",
            timezone_id="Asia/Seoul",
        )
        await context.add_init_script(STEALTH_INIT)

        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(url, wait_until="domcontentloaded")

        print("\n" + "=" * 64)
        print(f"Browser opened at: {url}")
        print(f"Profile dir: {USER_DATA_DIR}")
        print("Sign in with your Google account in the window.")
        print("Auto-detects via Google auth cookies. Anonymous won't be saved.")
        print(f"(Waiting up to {LOGIN_TIMEOUT_S // 60} minutes.)")
        print("=" * 64 + "\n")

        matched = await _wait_for_input_ready(page, prompt_selectors, timeout_ms=60_000)
        print(f"App reachable (selector: {matched})")

        print("Waiting for Google login...")
        found = await _wait_for_google_login(context, total_timeout_s=LOGIN_TIMEOUT_S)
        print(f"Login confirmed via auth cookies: {found[:3]}{'...' if len(found) > 3 else ''}")

        await page.wait_for_timeout(2000)
        await context.close()

    try:
        for root, dirs, files in os.walk(USER_DATA_DIR):
            for f in files:
                try:
                    os.chmod(os.path.join(root, f), 0o600)
                except OSError:
                    pass
    except OSError:
        pass
    print(f"\nSession persisted in {USER_DATA_DIR}")
    print("This directory is gitignored. Do NOT share it.")


def main() -> int:
    cfg = json.loads(SELECTORS_PATH.read_text(encoding="utf-8"))
    url = os.environ.get("NANO_BANANA_URL") or cfg.get("target_url", "https://gemini.google.com/app")
    prompt_selectors = cfg.get("prompt_input", ["textarea"])
    asyncio.run(capture_session(url, prompt_selectors))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
