"""Shared helpers for nano-banana-style image-gen prompt expansion.

Both `scripts/banana_prompt.py` (single) and `scripts/banana_variants.py`
(multi) call into this module so the Visualizer+Stylist system prompt and
palette library stay in one place.
"""

from __future__ import annotations

import os

from utils.generation_utils import call_model_with_retry_async

PALETTES: dict[str, str] = {
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

VISUALIZER_SYSTEM_PROMPT = """You are the Visualizer+Stylist agent of PaperBanana-Bedrock.

Given a short description of an architecture/flow figure, produce a precise,
single-block image-generation prompt that a downstream image model
(nano-banana-class, DALL-E, Flux, Imagen) can render directly.

Requirements:
- Open with a one-line subject statement (what the figure is).
- Specify composition (columns, rows, grouping boxes) with concrete positions.
- Name every visible component and what icon / badge treatment it gets.
- State the color palette explicitly with hex values; prefer the palette the
  user supplies. If AWS services appear, use official AWS service iconography
  conventions (dark navy squares with colored category badges) unless the
  palette overrides.
- Set typography (family, weight, size hierarchy) and arrow style (solid =
  primary flow, dashed = feedback/async, labeled where meaningful).
- End with a short list of what to AVOID.
- Output ONLY the prompt body - no preface, no markdown headings, no commentary.
- Keep it under 350 words but dense; every sentence should contribute to the
  render.
"""

DIRECTIONS_SYSTEM_PROMPT = """You are the Art Director of PaperBanana-Bedrock.

Given a figure description, propose N DISTINCT creative directions for how to
render it. Each direction must differ meaningfully in one or more of:
composition style, visual metaphor, typography register, icon treatment,
lighting/flatness, or decorative restraint.

Return exactly N lines, each formatted as:
    <short-slug>: <one-sentence directive under 25 words>

No numbering, no extra commentary, no blank lines.
"""


def _resolve_palette(palette: str) -> str:
    return PALETTES.get(palette, palette)


def _build_user_message(description: str, palette: str, aspect: str, mode: str | None) -> str:
    parts = [
        "Figure description (may be multi-line Korean/English):",
        "---",
        description.strip(),
        "---",
        f"Target aspect ratio: {aspect}",
        f"Palette: {_resolve_palette(palette)}",
    ]
    if mode:
        parts.append(f"Creative direction: {mode}")
    return "\n".join(parts) + "\n"


async def expand_to_prompt(
    description: str,
    *,
    palette: str = "aws-brand",
    aspect: str = "16:9",
    mode: str | None = None,
    max_tokens: int = 1500,
    temperature: float = 0.4,
) -> str:
    """Single-shot: expand a short description into a nano-banana prompt body."""
    user_message = _build_user_message(description, palette, aspect, mode)
    response = await call_model_with_retry_async(
        model_name=os.environ.get("BEDROCK_MODEL_ID", "global.anthropic.claude-sonnet-4-6"),
        contents=[{"type": "text", "text": user_message}],
        config={
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system_prompt": VISUALIZER_SYSTEM_PROMPT,
        },
    )
    return response[0].strip()


async def propose_directions(description: str, *, count: int) -> list[tuple[str, str]]:
    """Ask Claude for N distinct creative directions.

    Returns a list of (slug, directive) tuples, length == count.
    """
    if count < 1:
        raise ValueError("count must be >= 1")

    user_message = (
        f"Figure description:\n---\n{description.strip()}\n---\n\n"
        f"Propose exactly N={count} distinct directions."
    )
    response = await call_model_with_retry_async(
        model_name=os.environ.get("BEDROCK_MODEL_ID", "global.anthropic.claude-sonnet-4-6"),
        contents=[{"type": "text", "text": user_message}],
        config={
            "max_tokens": 400,
            "temperature": 0.8,
            "system_prompt": DIRECTIONS_SYSTEM_PROMPT,
        },
    )
    raw = response[0].strip()

    directions: list[tuple[str, str]] = []
    for line in raw.splitlines():
        line = line.strip().lstrip("-*0123456789. )")
        if not line or ":" not in line:
            continue
        slug, directive = line.split(":", 1)
        slug = slug.strip().lower().replace(" ", "-")[:40] or f"direction-{len(directions) + 1}"
        directive = directive.strip()
        if directive:
            directions.append((slug, directive))
        if len(directions) == count:
            break

    # Pad if model returned fewer lines than requested
    while len(directions) < count:
        directions.append((f"direction-{len(directions) + 1}", "alternate rendering"))

    return directions
