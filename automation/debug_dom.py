#!/usr/bin/env python
"""Debug helper: visit a Gemini chat URL, scan all image-like DOM elements,
then click the main generated image and re-scan for download controls.

Usage:
    python -m automation.debug_dom <chat-url>
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
USER_DATA_DIR = ROOT / ".auth" / "user_data_dir"

SCAN_JS = """() => {
    const pickAttrs = (el) => ({
        tag: el.tagName,
        id: el.id || '',
        className: (el.getAttribute('class') || '').slice(0, 200),
        ariaLabel: el.getAttribute('aria-label') || '',
        title: el.getAttribute('title') || '',
        text: (el.textContent || '').trim().slice(0, 100),
        href: el.getAttribute('href') || '',
        download: el.getAttribute('download') || '',
    });
    const imgs = Array.from(document.querySelectorAll('img')).map(el => ({
        ...pickAttrs(el),
        src: (el.currentSrc || el.src || '').slice(0, 300),
        naturalWidth: el.naturalWidth || 0,
        naturalHeight: el.naturalHeight || 0,
    }));
    const downloadable = Array.from(
        document.querySelectorAll(
            'a[download], a[href*="download" i], button[aria-label*="다운" i], '
            + 'button[aria-label*="download" i], [data-test-id*="download" i], '
            + 'button[aria-label*="원본" i], button[aria-label*="전체" i], '
            + 'button[aria-label*="저장" i]'
        )
    ).map(pickAttrs);
    const menuButtons = Array.from(
        document.querySelectorAll('button[aria-label*="더보기" i], button[aria-haspopup], button[mat-icon-button]')
    ).slice(0, 20).map(pickAttrs);
    const menuItems = Array.from(
        document.querySelectorAll('[role="menuitem"], mat-menu-item, button[role="menuitem"]')
    ).slice(0, 20).map(pickAttrs);
    return { url: location.href, imgs: imgs.slice(0, 12), downloadable, menuButtons, menuItems };
}"""


async def dump(url: str) -> None:
    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        ctx = await pw.chromium.launch_persistent_context(
            str(USER_DATA_DIR),
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
            locale="ko-KR",
            timezone_id="Asia/Seoul",
            accept_downloads=True,
        )
        await ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto(url, wait_until="domcontentloaded")
        await page.wait_for_timeout(6000)

        print("=== BEFORE CLICK ===")
        r1 = await page.evaluate(SCAN_JS)
        print(f"imgs:{len(r1['imgs'])} dl:{len(r1['downloadable'])} menu:{len(r1['menuButtons'])} items:{len(r1['menuItems'])}")
        for d in r1["downloadable"]:
            print(f"  DL: {d['tag']} aria={d['ariaLabel'][:60]!r} dl-attr={d['download']!r} href={d['href'][:60]!r}")

        # Click the main generated image
        try:
            img_btn = page.locator("button.image-button").first
            await img_btn.wait_for(state="visible", timeout=8000)
            await img_btn.click()
            print("\n[clicked image-button]")
            await page.wait_for_timeout(3000)
        except Exception as e:  # noqa: BLE001
            print(f"image-button click failed: {e}")

        print("\n=== AFTER CLICK ===")
        r2 = await page.evaluate(SCAN_JS)
        print(f"imgs:{len(r2['imgs'])} dl:{len(r2['downloadable'])} menu:{len(r2['menuButtons'])} items:{len(r2['menuItems'])}")
        for d in r2["downloadable"]:
            print(f"  DL: {d['tag']} aria={d['ariaLabel'][:60]!r} dl-attr={d['download']!r} href={d['href'][:80]!r}")
        for m in r2["menuButtons"][:10]:
            print(f"  MENU: {m['tag']} aria={m['ariaLabel'][:60]!r}")
        for mi in r2["menuItems"][:10]:
            print(f"  ITEM: {mi['tag']} aria={mi['ariaLabel'][:60]!r} text={mi['text'][:40]!r}")
        print("\nImgs in current DOM (>=300px):")
        for i in r2["imgs"]:
            if i["naturalWidth"] >= 300:
                print(f"  {i['naturalWidth']}x{i['naturalHeight']} src={i['src'][:90]}")

        (ROOT / "outputs" / "dom_debug.json").write_text(
            json.dumps({"before": r1, "after": r2}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"\nfull dump: outputs/dom_debug.json")

        await page.wait_for_timeout(5000)
        await ctx.close()


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python -m automation.debug_dom <chat-url>", file=sys.stderr)
        return 2
    asyncio.run(dump(sys.argv[1]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
