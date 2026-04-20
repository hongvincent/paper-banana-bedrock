#!/usr/bin/env python
"""One-shot "nano-banana" prompt generator.

Reads a short description of a figure you want, asks Bedrock Claude Sonnet 4.6
to expand it into a detailed image-generation prompt (with explicit color
palette, layout, typography, and service-icon treatment), then writes the
result as a reviewable Markdown file via utils.prompt_md_writer.

Usage:
    python scripts/banana_prompt.py description.txt
    echo "a 3-column AWS pipeline diagram" | python scripts/banana_prompt.py -
    python scripts/banana_prompt.py description.txt --palette aws-brand \\
        --aspect 16:9 --agent visualizer
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from utils.generation_utils import call_model_with_retry_async  # noqa: E402
from utils.prompt_md_writer import write_prompt_md  # noqa: E402

PALETTES = {
    "aws-brand": (
        "AWS brand palette: deep navy (#232F3E) as the primary surface, "
        "signature orange (#FF9900) for active service icons and connectors, "
        "smoke white (#FFFFFF) background, squid ink (#161E2D) for type, "
        "and muted slate (#545B64) for secondary lines."
    ),
    "neutral-editorial": (
        "Editorial neutral palette: bone white background, graphite line work, "
        "a single accent hue (indigo #4F46E5) for the critical path."
    ),
    "paper-print": (
        "Print-safe monochrome with a single warm accent (amber #B45309) used "
        "sparingly for emphasis and icons; clean serif labels."
    ),
}

SYSTEM_PROMPT = """You are the Visualizer+Stylist agent of PaperBanana-Bedrock.

Your job: given a short description of an architecture/flow figure, produce a
precise, single-block image-generation prompt that a downstream image model
(nano-banana-class, DALL-E, Flux, Imagen) can render directly.

Requirements:
- Open with a one-line subject statement (what the figure is).
- Specify composition (columns, rows, grouping boxes) with concrete positions.
- Name every visible component and what service icon treatment it gets.
- State the color palette explicitly with hex values; prefer the palette the
  user supplies. If AWS services appear, use official AWS service iconography
  conventions (dark navy squares with colored badges per category) unless the
  palette overrides.
- Set typography (family, weight, size hierarchy) and arrow style (solid =
  primary flow, dashed = feedback/async, labeled where meaningful).
- End with a short list of what to AVOID (e.g., skeuomorphic bevels, stock
  clipart, excessive shadows, clip-art people).
- Use English for the prompt body (image models render English best), but you
  MAY preserve original Korean labels verbatim inside quotes when the caption
  provides them.
- Output ONLY the prompt body. No preface, no markdown headings, no commentary.
- Keep it under 350 words but dense - every sentence should contribute to the
  render.
"""


async def generate(description: str, palette: str, aspect: str, agent: str) -> tuple[Path, str]:
    palette_text = PALETTES.get(palette, palette)
    user_message = (
        f"Figure description (may be multi-line Korean/English):\n"
        f"---\n{description.strip()}\n---\n\n"
        f"Target aspect ratio: {aspect}\n"
        f"Palette: {palette_text}\n"
    )

    response = await call_model_with_retry_async(
        model_name=os.environ.get("BEDROCK_MODEL_ID", "global.anthropic.claude-sonnet-4-6"),
        contents=[{"type": "text", "text": user_message}],
        config={
            "max_tokens": 1500,
            "temperature": 0.4,
            "system_prompt": SYSTEM_PROMPT,
        },
    )
    enhanced_prompt = response[0].strip()

    md_path, _ = write_prompt_md(
        prompt=enhanced_prompt,
        metadata={
            "agent": agent,
            "desc_key": "banana-oneshot",
            "aspect_ratio": aspect,
            "palette": palette,
            "model": os.environ.get("BEDROCK_MODEL_ID", "global.anthropic.claude-sonnet-4-6"),
        },
        output_dir=os.environ.get("OUTPUT_DIR", "./outputs"),
    )
    return md_path, enhanced_prompt


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a nano-banana-style image-gen prompt MD.")
    parser.add_argument("source", help="Path to a text file with the figure description, or '-' for stdin.")
    parser.add_argument("--palette", default="aws-brand", help="Palette key or freeform description.")
    parser.add_argument("--aspect", default="16:9", help="Target aspect ratio.")
    parser.add_argument("--agent", default="visualizer", help="Agent label stored in frontmatter.")
    args = parser.parse_args()

    if args.source == "-":
        description = sys.stdin.read()
    else:
        description = Path(args.source).read_text(encoding="utf-8")

    md_path, enhanced = asyncio.run(generate(description, args.palette, args.aspect, args.agent))
    print(f"\n[banana_prompt] wrote: {md_path}\n")
    print("---- enhanced prompt preview ----")
    print(enhanced[:600] + ("..." if len(enhanced) > 600 else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
