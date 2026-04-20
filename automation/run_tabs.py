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
USER_DATA_DIR = ROOT / ".auth" / "user_data_dir"


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


async def _try_click_image_mode(page, cfg: dict) -> bool:
    """Best-effort: click the 'Create images' / 이미지 만들기 toggle if it exists."""
    for sel in cfg.get("image_mode_toggle", []):
        try:
            loc = page.locator(sel).first
            await loc.wait_for(state="visible", timeout=3000)
            await loc.click()
            return True
        except Exception:  # noqa: BLE001
            continue
    return False


async def _try_click_first_style(page, cfg: dict) -> bool:
    """If Gemini shows a style-picker gallery, click the first visible option."""
    for sel in cfg.get("style_card_first", []):
        try:
            loc = page.locator(sel).first
            await loc.wait_for(state="visible", timeout=3000)
            await loc.click()
            return True
        except Exception:  # noqa: BLE001
            continue
    return False


async def _collect_generated_images(page, cfg: dict, out_dir: Path, timeout_s: int = 240) -> list[dict]:
    """Poll until generated images appear and are stable; save each via both
    screenshot AND direct HTTP fetch of the img.src.

    Deduplicates by src URL. Filters by min_image_width (avatars, icons are skipped).
    """
    selectors = cfg.get("generated_image", [])
    min_w = int(cfg.get("min_image_width", 300))
    allow = [s.lower() for s in cfg.get("image_src_allow_substrings", [])]
    deny = [s.lower() for s in cfg.get("image_src_deny_substrings", [])]

    def _src_ok(src: str) -> bool:
        s = (src or "").lower()
        if any(d in s for d in deny):
            return False
        if allow and not any(a in s for a in allow):
            return False
        return True

    out_dir.mkdir(parents=True, exist_ok=True)

    elapsed = 0.0
    interval = 4.0
    stable_count = 0
    prev = -1
    best_handles: dict[str, object] = {}  # src -> locator (dedup)

    while elapsed < timeout_s:
        current: dict[str, object] = {}
        for sel in selectors:
            try:
                locators = await page.locator(sel).all()
                for loc in locators:
                    try:
                        meta = await loc.evaluate(
                            "el => ({src: el.currentSrc || el.src || '', w: el.naturalWidth || 0, h: el.naturalHeight || 0})"
                        )
                        src = meta.get("src", "")
                        if meta.get("w", 0) >= min_w and src and _src_ok(src):
                            current[src] = loc
                    except Exception:  # noqa: BLE001
                        continue
            except Exception:  # noqa: BLE001
                continue

        count = len(current)
        if count > 0 and count == prev:
            stable_count += 1
            if stable_count >= 2:
                best_handles = current
                break
        else:
            stable_count = 0
        if count > len(best_handles):
            best_handles = current
        prev = count
        await asyncio.sleep(interval)
        elapsed += interval

    if not best_handles:
        # Last-resort: dump the full page screenshot for debugging
        debug_shot = out_dir / "NO_IMAGES_page.png"
        try:
            await page.screenshot(path=str(debug_shot), full_page=True)
        except Exception:  # noqa: BLE001
            pass
        return []

    # Collect download buttons (usually 1:1 with images, paired in DOM order)
    dl_btns = []
    for sel in cfg.get("download_button", []):
        try:
            dl_btns.extend(await page.locator(sel).all())
        except Exception:  # noqa: BLE001
            continue
    # Dedup by element handle identity via unique JS handles
    seen_handles = set()
    unique_dl = []
    for b in dl_btns:
        try:
            h = await b.element_handle()
            if h is None:
                continue
            key = str(h)
            if key not in seen_handles:
                seen_handles.add(key)
                unique_dl.append(b)
        except Exception:  # noqa: BLE001
            continue
    print(f"  found {len(unique_dl)} download buttons")

    metas: list[dict] = []
    ordered = sorted(best_handles.items())
    for i, (src, loc) in enumerate(ordered, start=1):
        try:
            info = await loc.evaluate(
                "el => ({w: el.naturalWidth || 0, h: el.naturalHeight || 0})"
            )
            w, h = info["w"], info["h"]
        except Exception:  # noqa: BLE001
            w = h = 0

        # Thumbnail via element screenshot (always try — cheap backup)
        shot_path = out_dir / f"image_{i:02d}_thumb.png"
        thumb_ok = False
        try:
            await loc.screenshot(path=str(shot_path))
            thumb_ok = True
        except Exception as e:  # noqa: BLE001
            print(f"  thumb screenshot failed for #{i}: {e}", file=sys.stderr)

        # Original: click matched download button and catch the download
        original_path: str | None = None
        if i - 1 < len(unique_dl):
            dl_btn = unique_dl[i - 1]
            try:
                async with page.expect_download(timeout=25000) as dl_info:
                    try:
                        await dl_btn.scroll_into_view_if_needed(timeout=3000)
                    except Exception:  # noqa: BLE001
                        pass
                    await dl_btn.click()
                dl = await dl_info.value
                suggested = dl.suggested_filename or f"image_{i:02d}.png"
                suffix = Path(suggested).suffix or ".png"
                target = out_dir / f"image_{i:02d}_original{suffix}"
                await dl.save_as(str(target))
                original_path = str(target)
                print(f"  downloaded #{i} original -> {target.name}")
            except Exception as e:  # noqa: BLE001
                print(f"  download #{i} failed: {e}", file=sys.stderr)

        metas.append({
            "index": i,
            "thumbnail": str(shot_path) if thumb_ok else None,
            "original": original_path,
            "src_url": src,
            "width": w,
            "height": h,
        })
    return metas


def _slug_from_filename(name: str) -> str:
    """Derive folder slug from a variant MD filename like
    '20260420T111718Z_visualizer_variant-01-blueprint-glow.md' -> 'variant-01-blueprint-glow'.
    """
    stem = Path(name).stem
    if "_variant-" in stem:
        return "variant-" + stem.split("_variant-", 1)[1]
    return stem


async def _drive_tab(
    context,
    index: int,
    total: int,
    md_path: Path,
    prompt: str,
    cfg: dict,
    submit: bool,
    screenshot_dir: Path,
    image_mode: bool,
    collect_root: Path | None,
    collect_timeout_s: int,
) -> dict:
    """Open one tab, paste + optionally submit + optionally collect generated images."""
    page = await context.new_page()
    label = f"[{index}/{total}] {md_path.name}"
    url = cfg["target_url"]
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(cfg.get("wait_after_goto_ms", 3000))

        if image_mode:
            clicked = await _try_click_image_mode(page, cfg)
            print(f"{label} image-mode toggle: {'clicked' if clicked else 'NOT FOUND'}")
            await page.wait_for_timeout(600)

        input_loc = await _first_matching(page, cfg["prompt_input"])
        try:
            await input_loc.scroll_into_view_if_needed(timeout=5000)
        except Exception:  # noqa: BLE001
            pass
        try:
            await input_loc.click(timeout=8000)
        except Exception:
            # Fallback: focus via JS then click (handles off-viewport edge cases)
            try:
                await input_loc.evaluate("el => { el.focus(); el.scrollIntoView({block:'center'}); }")
                await input_loc.click(timeout=8000, force=True)
            except Exception as e:  # noqa: BLE001
                print(f"{label} input click fallback failed: {e}", file=sys.stderr)
        await page.wait_for_timeout(400)
        # Atomic insertion via document.execCommand('insertText') — one input
        # event, no key interpretation, so Gemini's Enter-to-send never fires
        # mid-prompt and no splitting occurs.
        try:
            await input_loc.evaluate(
                """(el, text) => {
                    el.focus();
                    if (document.execCommand) {
                        document.execCommand('insertText', false, text);
                    } else {
                        // Fallback: set textContent + dispatch input event
                        el.textContent = text;
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                    }
                }""",
                prompt,
            )
        except Exception as e:  # noqa: BLE001
            print(f"{label} insertText failed, falling back to keyboard.insert_text: {e}", file=sys.stderr)
            # Last-resort: still protect against Enter-as-Send by splitting.
            for seg_i, segment in enumerate(prompt.split("\n")):
                if segment:
                    await page.keyboard.insert_text(segment)
                if seg_i < len(prompt.split("\n")) - 1:
                    await page.keyboard.press("Shift+Enter")
        await page.wait_for_timeout(800)

        if submit:
            # NOTE: we no longer click a style card — in Gemini's "이미지 만들기"
            # mode, selecting a style card itself triggers generation, which
            # conflicts with a subsequent explicit Send click. Only click Send.
            try:
                btn = await _first_matching(page, cfg["submit_button"], timeout_ms=5000)
                await btn.click()
                print(f"{label} Send clicked")
            except Exception as e:  # noqa: BLE001
                print(f"{label} Send skipped ({e})")
            # Wait until the URL contains a chat ID (Gemini persists conversation)
            try:
                await page.wait_for_url(
                    lambda url: "/app/" in url and url.rstrip("/").split("/")[-1] != "app",
                    timeout=15000,
                )
                print(f"{label} chat persisted: {page.url}")
            except Exception:  # noqa: BLE001
                print(f"{label} warning: chat ID not in URL after send (may not save)")

        screenshot_dir.mkdir(parents=True, exist_ok=True)
        pre_shot = screenshot_dir / f"{md_path.stem}.posted.png"
        await page.screenshot(path=str(pre_shot), full_page=True)

        result: dict = {"md": str(md_path), "url": page.url, "ok": True, "posted_shot": str(pre_shot)}

        if collect_root is not None and submit:
            slug = _slug_from_filename(md_path.name)
            tab_dir = collect_root / slug
            print(f"{label} waiting up to {collect_timeout_s}s for generated images...")
            images = await _collect_generated_images(page, cfg, tab_dir, timeout_s=collect_timeout_s)
            result["slug"] = slug
            result["rendered_dir"] = str(tab_dir)
            result["images"] = images

            # per-variant meta.json
            meta = {
                "md": str(md_path),
                "prompt_excerpt": prompt[:400],
                "url": page.url,
                "rendered_at": datetime.now(timezone.utc).isoformat(),
                "images": images,
            }
            (tab_dir).mkdir(parents=True, exist_ok=True)
            (tab_dir / "meta.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"{label} collected {len(images)} image(s) -> {tab_dir}")

        return result
    except Exception as e:  # noqa: BLE001
        print(f"{label} ERROR: {e}", file=sys.stderr)
        try:
            screenshot_dir.mkdir(parents=True, exist_ok=True)
            fail_shot = screenshot_dir / f"{md_path.stem}.FAIL.png"
            await page.screenshot(path=str(fail_shot), full_page=True)
        except Exception:  # noqa: BLE001
            fail_shot = None
        return {"md": str(md_path), "url": page.url, "ok": False, "error": str(e), "screenshot": str(fail_shot) if fail_shot else None}


async def _wait_for_close_signal(marker_path: Path, timeout_s: int) -> None:
    """Block until marker_path exists or timeout elapses. Background-safe (no stdin)."""
    elapsed = 0.0
    interval = 1.0
    print(f"\nAll tabs ready. To close the browser, run:  touch {marker_path}")
    print(f"Auto-close in {timeout_s}s if no marker appears.\n")
    while elapsed < timeout_s:
        if marker_path.exists():
            try:
                marker_path.unlink()
            except OSError:
                pass
            return
        await asyncio.sleep(interval)
        elapsed += interval


def _write_rendered_index(collect_root: Path, results: list[dict]) -> Path:
    """Write a rendered/index.md summarizing each variant's generated images."""
    lines = [f"# Rendered results — {collect_root.parent.name}", ""]
    for r in results:
        if not r.get("ok") or "slug" not in r:
            continue
        slug = r["slug"]
        imgs = r.get("images", [])
        lines.append(f"## {slug}")
        lines.append("")
        lines.append(f"- Source MD: `{Path(r['md']).name}`")
        lines.append(f"- URL: {r['url']}")
        lines.append(f"- Images: {len(imgs)}")
        lines.append("")
        for im in imgs:
            if "path" not in im:
                continue
            rel = Path(im["path"]).relative_to(collect_root)
            w = im.get("width", "?")
            h = im.get("height", "?")
            lines.append(f"![{slug} #{im['index']}]({rel}) `{w}x{h}`")
            lines.append("")
    index_path = collect_root / "index.md"
    index_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return index_path


async def run(
    variants_dir: Path,
    *,
    submit: bool,
    headless: bool,
    max_tabs: int | None,
    image_mode: bool,
    keep_open_s: int,
    collect: bool,
    collect_timeout_s: int,
    serial: bool = False,
) -> int:
    # Prefer persistent-context profile (maximum stealth); fall back to
    # storage_state.json if present.
    use_persistent = USER_DATA_DIR.exists() and any(USER_DATA_DIR.iterdir())
    if not use_persistent and not STATE_PATH.exists():
        sys.exit(
            "No saved session. Run: python -m automation.session_setup "
            "(this creates .auth/user_data_dir/)"
        )

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        sys.exit("playwright not installed. Run: pip install playwright && playwright install chromium")

    cfg = json.loads(SELECTORS_PATH.read_text(encoding="utf-8"))
    variants = collect_variants(variants_dir)
    if max_tabs:
        variants = variants[:max_tabs]
    total = len(variants)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    screenshot_dir = Path("screenshots") / f"run_{timestamp}"
    close_marker = ROOT / ".auth" / f".close_{timestamp}"

    collect_root: Path | None = None
    if collect:
        if not submit:
            print("note: --collect requires --submit; enabling --submit automatically")
            submit = True
        collect_root = Path(variants_dir) / "rendered"
        collect_root.mkdir(parents=True, exist_ok=True)

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
    UA = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    )

    async with async_playwright() as pw:
        browser = None
        if use_persistent:
            # Persistent profile — real long-lived install, hardest to fingerprint as automation.
            context = await pw.chromium.launch_persistent_context(
                str(USER_DATA_DIR),
                headless=headless,
                args=LAUNCH_ARGS,
                user_agent=UA,
                viewport={"width": 1440, "height": 900},
                locale="ko-KR",
                timezone_id="Asia/Seoul",
                accept_downloads=True,
            )
            print(f"using persistent profile: {USER_DATA_DIR}")
        else:
            browser = await pw.chromium.launch(headless=headless, args=LAUNCH_ARGS)
            context = await browser.new_context(
                storage_state=str(STATE_PATH),
                user_agent=UA,
                viewport={"width": 1440, "height": 900},
                locale="ko-KR",
                timezone_id="Asia/Seoul",
                accept_downloads=True,
            )
            print(f"using storage_state: {STATE_PATH}")
        await context.add_init_script(STEALTH_INIT)

        import random
        results: list[dict] = []
        if serial:
            gmin = int(cfg.get("serial_gap_s_min", 8))
            gmax = int(cfg.get("serial_gap_s_max", 22))
            for i, (md, prompt) in enumerate(variants):
                r = await _drive_tab(
                    context, i + 1, total, md, prompt, cfg, submit,
                    screenshot_dir, image_mode, collect_root, collect_timeout_s,
                )
                results.append(r)
                if i < total - 1:
                    gap = random.uniform(gmin, gmax)
                    print(f"[serial] waiting {gap:.1f}s before next tab (anti-abuse)")
                    await asyncio.sleep(gap)
        else:
            tasks = [
                _drive_tab(
                    context, i + 1, total, md, prompt, cfg, submit,
                    screenshot_dir, image_mode, collect_root, collect_timeout_s,
                )
                for i, (md, prompt) in enumerate(variants)
            ]
            results = await asyncio.gather(*tasks)

        if collect_root is not None:
            idx = _write_rendered_index(collect_root, results)
            print(f"rendered index: {idx}")

        if not headless and keep_open_s > 0:
            await _wait_for_close_signal(close_marker, timeout_s=keep_open_s)
        if browser is not None:
            await browser.close()
        else:
            await context.close()

    failures = [r for r in results if not r.get("ok")]
    print(f"\n=== SUMMARY === {total - len(failures)}/{total} tabs OK. Screenshots: {screenshot_dir}")
    if collect_root is not None:
        print(f"rendered folder: {collect_root}")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Paste variant prompts into N nano-banana tabs.")
    parser.add_argument("variants_dir", help="Path to a variants_<ts>/ folder.")
    parser.add_argument("--submit", action="store_true", help="Click Send after pasting.")
    parser.add_argument("--headless", action="store_true", help="Run without visible browser.")
    parser.add_argument("--max-tabs", type=int, default=None, help="Cap concurrent tabs.")
    parser.add_argument("--image-mode", action="store_true", help="Try to click '이미지 만들기/Create images' toggle first.")
    parser.add_argument("--keep-open", type=int, default=600, help="Keep browser open this many seconds after pasting (default 600).")
    parser.add_argument("--collect", action="store_true", help="Wait for generated images and save into <variants_dir>/rendered/ (implies --submit).")
    parser.add_argument("--collect-timeout", type=int, default=240, help="Per-tab seconds to wait for image generation (default 240).")
    parser.add_argument("--serial", action="store_true", help="Process variants one at a time with a randomized gap (anti-abuse). RECOMMENDED.")
    args = parser.parse_args()

    return asyncio.run(
        run(
            Path(args.variants_dir),
            submit=args.submit,
            headless=args.headless,
            max_tabs=args.max_tabs,
            image_mode=args.image_mode,
            keep_open_s=args.keep_open,
            collect=args.collect,
            collect_timeout_s=args.collect_timeout,
            serial=args.serial,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
