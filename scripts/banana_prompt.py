#!/usr/bin/env python
"""One-shot "nano-banana" prompt generator.

Reads a short description of a figure you want, asks Bedrock Claude Sonnet 4.6
to expand it into a detailed image-generation prompt, then writes the result
as a reviewable Markdown file via utils.prompt_md_writer.

Usage:
    python scripts/banana_prompt.py description.txt
    echo "a 3-column AWS pipeline diagram" | python scripts/banana_prompt.py -
    python scripts/banana_prompt.py description.txt --palette aws-brand --aspect 16:9

For multiple variants of the same description, see scripts/banana_variants.py.
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from utils.banana_prompting import expand_to_prompt  # noqa: E402
from utils.prompt_md_writer import write_prompt_md  # noqa: E402


async def run(description: str, palette: str, aspect: str, agent: str) -> tuple[Path, str]:
    enhanced = await expand_to_prompt(description, palette=palette, aspect=aspect)
    md_path, _ = write_prompt_md(
        prompt=enhanced,
        metadata={
            "agent": agent,
            "desc_key": "banana-oneshot",
            "aspect_ratio": aspect,
            "palette": palette,
            "model": os.environ.get("BEDROCK_MODEL_ID", "global.anthropic.claude-sonnet-4-6"),
        },
        output_dir=os.environ.get("OUTPUT_DIR", "./outputs"),
    )
    return md_path, enhanced


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a nano-banana-style image-gen prompt MD.")
    parser.add_argument("source", help="Path to a text file with the figure description, or '-' for stdin.")
    parser.add_argument("--palette", default="aws-brand", help="Palette key (aws-brand/neutral-editorial/paper-print) or freeform string.")
    parser.add_argument("--aspect", default="16:9", help="Target aspect ratio.")
    parser.add_argument("--agent", default="visualizer", help="Agent label stored in frontmatter.")
    args = parser.parse_args()

    description = sys.stdin.read() if args.source == "-" else Path(args.source).read_text(encoding="utf-8")
    md_path, enhanced = asyncio.run(run(description, args.palette, args.aspect, args.agent))

    print(f"\n[banana_prompt] wrote: {md_path}\n")
    print("---- enhanced prompt preview ----")
    print(enhanced[:600] + ("..." if len(enhanced) > 600 else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
