"""Extract the prompt body from a PaperBanana variant Markdown file.

Each variant MD contains a section:

    ## Prompt

    ```
    <prompt body here>
    ```

    ## Next Steps
    ...

This module pulls the content of that first fenced code block under '## Prompt'.
"""

from __future__ import annotations

import re
from pathlib import Path

_PROMPT_HEADING = re.compile(r"^##\s+Prompt\s*$", re.MULTILINE)
_FENCE = re.compile(r"^```(?:\w+)?\s*\n(.*?)\n```", re.DOTALL | re.MULTILINE)


class PromptExtractionError(ValueError):
    """Raised when a markdown file does not contain a parseable prompt block."""


def extract_prompt(md_text: str) -> str:
    """Return the content of the fenced code block under '## Prompt'.

    Raises PromptExtractionError if the heading or fence is missing.
    """
    heading_match = _PROMPT_HEADING.search(md_text)
    if not heading_match:
        raise PromptExtractionError("'## Prompt' heading not found")
    after = md_text[heading_match.end():]
    fence_match = _FENCE.search(after)
    if not fence_match:
        raise PromptExtractionError("Fenced code block after '## Prompt' not found")
    return fence_match.group(1).strip()


def extract_from_file(path: Path | str) -> str:
    text = Path(path).read_text(encoding="utf-8")
    return extract_prompt(text)


def collect_variants(variants_dir: Path | str) -> list[tuple[Path, str]]:
    """Walk a variants_<ts>/ directory and return [(md_path, prompt), ...].

    Skips index.md. Sorted by filename (which encodes variant order).
    """
    base = Path(variants_dir)
    if not base.is_dir():
        raise FileNotFoundError(f"not a directory: {base}")
    md_files = sorted(
        p for p in base.iterdir()
        if p.suffix == ".md" and p.name != "index.md"
    )
    out: list[tuple[Path, str]] = []
    for f in md_files:
        try:
            out.append((f, extract_from_file(f)))
        except PromptExtractionError:
            continue
    if not out:
        raise PromptExtractionError(f"no parseable variant MDs in {base}")
    return out
