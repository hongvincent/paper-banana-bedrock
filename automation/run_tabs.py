#!/usr/bin/env python
"""Open N browser tabs, paste one variant prompt into each in parallel.

Usage:
    python -m automation.run_tabs outputs/variants_20260420T111655Z/
    python -m automation.run_tabs outputs/variants_... --submit --headless
    python -m automation.run_tabs outputs/variants_... --max-tabs 3

Flags:
    --submit        Click the Run/Generate button after pasting (default: dry-run,
                    paste only — you click Run yourself).
    --headless      Run without a visible browser (fragile for anti-bot; prefer default).
    --screenshot    Save a PNG of each tab after submit.
    --max-tabs N    Cap concurrent tabs (default: all variants in the folder).

Reads session from .auth/nano_banana_state.json (created by session_setup.py).
Never touches credentials.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from automation.extract_prompt import collect_variants  # noqa: E402

SELECTORS_PATH = ROOT / "automation" / "selectors.json"
STATE_PATH = ROOT / ".auth" / "nano_banana_state.json"


async def _first_matching(page, selectors: list[str], *, timeout_ms: int = 15000):
    """Try each selector; return the first one that resolves."""
    last_error: Exception | None = None
    for sel in selectors:
        try:
            locator = page.locator(sel).first
            await locator.wait_for(state="visible", timeout=timeout_ms)
            return locator
        except Exception as e:
            last_error = e
            continue
    raise RuntimeError(f"none of {selectors} matched a visible element") from last_error


async def _drive_tab(
    context,
    index: int,
    total: int,
    md_path: Path,
    prompt: str,
    cfg: dict,
    submit: bool,
    screenshot_dir: Path | None,
) -> dict:
    """Open one tab, paste the prompt, optionally submit + screenshot."""
    page = await context.new_page()
    label = f"[{index}/{total}] {md_path.name}"
    url = cfg["target_url"]
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(cfg.get("wait_after_goto_ms", 3000))

        input_loc = await _first_matching(page, cfg["prompt_input"])
        await input_loc.click()
        # Fill works for textarea; for contenteditable we fall back to keyboard.
        try:
            await input_loc.fill(prompt)
        except Exception:
            await page.keyboard.insert_text(prompt)

        if submit:
            btn = await _first_matching(page, cfg["submit_button"])
            await btn.click()
            await page.wait_for_timeout(cfg.get("screenshot_after_ms", 15000))

        if screenshot_dir is not None:
            screenshot_dir.mkdir(parents=True, exist_ok=True)
            shot_path = screenshot_dir / f"{md_path.stem}.png"
            await page.screenshot(path=str(shot_path), full_page=True)
            print(f"{label} screenshot -> {shot_path}")
        else:
            print(f"{label} pasted {'+submitted' if submit else '(dry-run)'} at {page.url}")

        return {"md": str(md_path), "url": page.url, "ok": True}
    except Exception as e:  # noqa: BLE001
        print(f"{label} ERROR: {e}", file=sys.stderr)
        return {"md": str(md_path), "url": page.url, "ok": False, "error": str(e)}


async def run(
    variants_dir: Path,
    *,
    submit: bool,
    headless: bool,
    screenshot: bool,
    max_tabs: int | None,
) -> int:
    if not STATE_PATH.exists():
        sys.exit(f"missing {STATE_PATH}. Run: python -m automation.session_setup")

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        sys.exit("playwright not installed. Run: pip install playwright && playwright install chromium")

    cfg = json.loads(SELECTORS_PATH.read_text(encoding="utf-8"))
    variants = collect_variants(variants_dir)
    if max_tabs:
        variants = variants[:max_tabs]
    total = len(variants)

    screenshot_dir = None
    if screenshot:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        screenshot_dir = Path("screenshots") / f"run_{timestamp}"

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless)
        context = await browser.new_context(storage_state=str(STATE_PATH))
        tasks = [
            _drive_tab(context, i + 1, total, md, prompt, cfg, submit, screenshot_dir)
            for i, (md, prompt) in enumerate(variants)
        ]
        results = await asyncio.gather(*tasks)

        if not submit and headless is False:
            print("\nAll tabs ready. Press ENTER to close the browser.")
            await asyncio.get_event_loop().run_in_executor(None, input)
        await browser.close()

    failures = [r for r in results if not r["ok"]]
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Paste variant prompts into N nano-banana tabs.")
    parser.add_argument("variants_dir", help="Path to a variants_<ts>/ folder.")
    parser.add_argument("--submit", action="store_true", help="Click Run after pasting.")
    parser.add_argument("--headless", action="store_true", help="Run without visible browser.")
    parser.add_argument("--screenshot", action="store_true", help="Save PNG of each tab post-submit.")
    parser.add_argument("--max-tabs", type=int, default=None, help="Cap concurrent tabs.")
    args = parser.parse_args()

    return asyncio.run(
        run(
            Path(args.variants_dir),
            submit=args.submit,
            headless=args.headless,
            screenshot=args.screenshot,
            max_tabs=args.max_tabs,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
