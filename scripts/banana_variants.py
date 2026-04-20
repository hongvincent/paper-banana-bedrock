#!/usr/bin/env python
"""Generate N distinct variant prompts for a single figure description.

Two ways to define the N directions:
  A) Let Claude propose them automatically:
     python scripts/banana_variants.py description.txt --count 3

  B) Specify the directions yourself (one per mode, comma-separated):
     python scripts/banana_variants.py description.txt \\
         --modes "flat-vector,isometric-depth,hand-drawn-blueprint"

Output: a timestamped folder under OUTPUT_DIR/variants_<ts>/ with one
variant_<NN>.md per direction plus an index.md that links them all.
Variants are generated in parallel via asyncio.gather.
"""

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from utils.banana_prompting import expand_to_prompt, propose_directions  # noqa: E402
from utils.prompt_md_writer import write_prompt_md  # noqa: E402


def _slugify(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in value.lower())
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned.strip("-")[:40] or "variant"


async def _generate_one(
    index: int,
    total: int,
    slug: str,
    directive: str,
    description: str,
    palette: str,
    aspect: str,
    run_dir: Path,
) -> tuple[Path, str, str]:
    enhanced = await expand_to_prompt(
        description,
        palette=palette,
        aspect=aspect,
        mode=directive,
    )
    padded = f"{index:02d}"
    md_path, _ = write_prompt_md(
        prompt=enhanced,
        metadata={
            "agent": "visualizer",
            "desc_key": f"variant-{padded}-{slug}",
            "aspect_ratio": aspect,
            "palette": palette,
            "variant_index": f"{index}/{total}",
            "direction": directive,
            "model": os.environ.get("BEDROCK_MODEL_ID", "global.anthropic.claude-sonnet-4-6"),
        },
        output_dir=run_dir,
    )
    return md_path, slug, enhanced


def _write_index(run_dir: Path, description: str, directions: list[tuple[str, str]], paths: list[Path]) -> Path:
    lines: list[str] = [
        f"# Variant experiment - {run_dir.name}",
        "",
        "## Input description",
        "",
        "```",
        description.strip(),
        "```",
        "",
        "## Variants",
        "",
    ]
    for i, ((slug, directive), path) in enumerate(zip(directions, paths), start=1):
        rel = path.name
        lines.append(f"### {i:02d}. {slug}")
        lines.append("")
        lines.append(f"- **Direction**: {directive}")
        lines.append(f"- **File**: [{rel}](./{rel})")
        lines.append("")
    index_path = run_dir / "index.md"
    index_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return index_path


async def run(
    description: str,
    *,
    count: int,
    modes: list[str] | None,
    palette: str,
    aspect: str,
) -> tuple[Path, list[Path]]:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = Path(os.environ.get("OUTPUT_DIR", "./outputs"))
    run_dir = base / f"variants_{timestamp}"
    run_dir.mkdir(parents=True, exist_ok=True)

    if modes:
        directions = [(_slugify(m), m) for m in modes]
        count = len(directions)
    else:
        directions = await propose_directions(description, count=count)

    tasks = [
        _generate_one(
            index=i + 1,
            total=count,
            slug=slug,
            directive=directive,
            description=description,
            palette=palette,
            aspect=aspect,
            run_dir=run_dir,
        )
        for i, (slug, directive) in enumerate(directions)
    ]
    results = await asyncio.gather(*tasks)
    paths = [r[0] for r in results]

    index_path = _write_index(run_dir, description, directions, paths)
    return index_path, paths


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate N variant prompts in parallel.")
    parser.add_argument("source", help="Path to description text file, or '-' for stdin.")
    parser.add_argument("--count", type=int, default=3, help="Number of auto-generated variants (ignored if --modes set).")
    parser.add_argument("--modes", default=None, help="Comma-separated explicit directions, e.g. 'flat,isometric,blueprint'.")
    parser.add_argument("--palette", default="aws-brand", help="Palette key or freeform string.")
    parser.add_argument("--aspect", default="16:9", help="Target aspect ratio.")
    args = parser.parse_args()

    if args.count < 1:
        parser.error("--count must be >= 1")

    description = sys.stdin.read() if args.source == "-" else Path(args.source).read_text(encoding="utf-8")
    modes = [m.strip() for m in args.modes.split(",") if m.strip()] if args.modes else None

    index_path, paths = asyncio.run(
        run(description, count=args.count, modes=modes, palette=args.palette, aspect=args.aspect)
    )
    print(f"\n[banana_variants] wrote {len(paths)} variants + index")
    print(f"  index: {index_path}")
    for p in paths:
        print(f"  - {p.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
