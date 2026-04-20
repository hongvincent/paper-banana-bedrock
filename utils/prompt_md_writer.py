# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Utility for writing preliminary PaperBanana prompt Markdown files instead of
actually generating images.  Used by Visualizer, Vanilla, and Polish agents in
the Bedrock fork.
"""

import re
from datetime import datetime, timezone
from pathlib import Path

# Standard 1x1 JPEG encoded as base64.  Deterministic across all calls.
PLACEHOLDER_JPG_B64 = (
    "/9j/4AAQSkZJRgABAQEAAAAAAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0a"
    "HBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIy"
    "MjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAABAAEDASIA"
    "AhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAn/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFAEBAAAA"
    "AAAAAAAAAAAAAAAAAP/EABQRAQAAAAAAAAAAAAAAAAAAAAD/2gAMAwEAAhEDEQA/AJ//2Q=="
)


def _slugify(text: str, max_len: int = 40) -> str:
    """Return a filesystem-safe slug from text, at most max_len characters."""
    text = text.strip()
    # Replace non-alphanumeric characters (keep hyphens and underscores) with _
    text = re.sub(r"[^\w\-]", "_", text, flags=re.UNICODE)
    # Collapse consecutive underscores
    text = re.sub(r"_+", "_", text)
    text = text.strip("_")
    return text[:max_len] if text else "prompt"


def write_prompt_md(
    prompt: str,
    metadata: dict,
    output_dir: str | Path = "./outputs",
) -> tuple:
    """
    Write a Markdown file containing the preliminary PaperBanana image-generation
    prompt for review instead of actually rendering an image.

    Parameters
    ----------
    prompt : str
        The text prompt that would have been sent to an image-generation model.
    metadata : dict
        Must contain at minimum:
          - "agent"        (str) name of the calling agent
          - "desc_key"     (str) key identifying which description this is for
          - "aspect_ratio" (str) e.g. "16:9"
        Optional keys are written verbatim into the frontmatter and metadata table.
    output_dir : str or Path
        Directory where the .md file will be written (created if absent).

    Returns
    -------
    (md_file_path, placeholder_jpg_base64) : tuple[Path, str]
      - md_file_path        : absolute Path to the written .md file
      - placeholder_jpg_base64 : the PLACEHOLDER_JPG_B64 constant
    """
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    agent = metadata.get("agent", "unknown")
    desc_key = metadata.get("desc_key", "")
    slug = _slugify(desc_key) if desc_key else _slugify(prompt)

    filename = f"{timestamp}_{agent}_{slug}.md"
    md_path = output_dir / filename

    aspect_ratio = metadata.get("aspect_ratio", "1:1")
    model = metadata.get("model", "")

    # Build YAML frontmatter
    frontmatter_lines = ["---"]
    frontmatter_lines.append(f"agent: {agent}")
    frontmatter_lines.append(f"timestamp: {timestamp}")
    frontmatter_lines.append(f"aspect_ratio: {aspect_ratio}")
    if model:
        frontmatter_lines.append(f"model: {model}")
    # Write any extra metadata keys
    for key, value in metadata.items():
        if key in ("agent", "desc_key", "aspect_ratio", "model"):
            continue
        frontmatter_lines.append(f"{key}: {value!r}")
    frontmatter_lines.append("---")
    frontmatter = "\n".join(frontmatter_lines)

    # Build metadata table rows
    table_rows = [
        f"| agent | {agent} |",
        f"| timestamp | {timestamp} |",
        f"| aspect_ratio | {aspect_ratio} |",
    ]
    if model:
        table_rows.append(f"| model | {model} |")
    if desc_key:
        table_rows.append(f"| desc_key | {desc_key} |")
    for key, value in metadata.items():
        if key in ("agent", "desc_key", "aspect_ratio", "model"):
            continue
        table_rows.append(f"| {key} | {value} |")

    metadata_table = "| Key | Value |\n|-----|-------|\n" + "\n".join(table_rows)

    content = (
        f"{frontmatter}\n\n"
        "# Preliminary PaperBanana Prompt\n\n"
        "## Metadata\n\n"
        f"{metadata_table}\n\n"
        "## Prompt\n\n"
        "```\n"
        f"{prompt}\n"
        "```\n\n"
        "## Next Steps\n\n"
        "A human reviewer or downstream image-generation model should consume this\n"
        "document to produce the final figure.  Replace the stub output in the\n"
        "pipeline with the resulting image encoded as base64 JPEG.\n"
    )

    md_path.write_text(content, encoding="utf-8")
    return md_path, PLACEHOLDER_JPG_B64
