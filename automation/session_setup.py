#!/usr/bin/env python
"""One-time manual login: capture an authenticated browser session.

Usage:
    python -m automation.session_setup

Opens a real Chromium window pointed at the target URL, waits for you to log
in by hand (username, password, 2FA, whatever Google requires this time),
then saves the session to .auth/nano_banana_state.json for later reuse.

Credentials are NEVER read by this script. You type them into the real browser
UI yourself. The saved JSON contains cookies + localStorage only.
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
STATE_PATH = AUTH_DIR / "nano_banana_state.json"


async def capture_session(url: str) -> None:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        sys.exit("playwright not installed. Run: pip install playwright && playwright install chromium")

    AUTH_DIR.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto(url)

        print("\n" + "=" * 60)
        print("Log in by hand in the browser window that just opened.")
        print("When the app is fully loaded and you are signed in,")
        print("come back here and press ENTER to save the session.")
        print("=" * 60 + "\n")

        # Run blocking input() on the event-loop executor so the Playwright
        # loop keeps running.
        await asyncio.get_event_loop().run_in_executor(None, input)

        await context.storage_state(path=str(STATE_PATH))
        await browser.close()

    try:
        os.chmod(STATE_PATH, 0o600)
    except OSError:
        pass
    print(f"\nSaved session to {STATE_PATH} (mode 600)")
    print("This file is gitignored. Do NOT share it.")


def main() -> int:
    url = os.environ.get("NANO_BANANA_URL")
    if not url:
        cfg = json.loads(SELECTORS_PATH.read_text(encoding="utf-8"))
        url = cfg.get("target_url", "https://aistudio.google.com/app/prompts/new")
    asyncio.run(capture_session(url))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
