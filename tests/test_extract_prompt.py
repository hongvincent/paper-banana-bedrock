"""Tests for automation.extract_prompt."""

from __future__ import annotations

from pathlib import Path

import pytest

from automation.extract_prompt import (
    PromptExtractionError,
    collect_variants,
    extract_from_file,
    extract_prompt,
)

SAMPLE_MD = """---
agent: visualizer
---

# Preliminary PaperBanana Prompt

## Metadata

| Key | Value |
|-----|-------|
| agent | visualizer |

## Prompt

```
A 16:9 landscape architecture diagram with five group boxes.
COMPOSITION: ...
AVOID: gradients, drop shadows.
```

## Next Steps

Consume this in downstream image model.
"""


def test_extract_prompt_returns_block_body():
    out = extract_prompt(SAMPLE_MD)
    assert out.startswith("A 16:9 landscape")
    assert "AVOID: gradients" in out
    assert "Next Steps" not in out
    assert not out.startswith("```")


def test_extract_prompt_missing_heading_raises():
    with pytest.raises(PromptExtractionError):
        extract_prompt("no heading here\n```\nbody\n```")


def test_extract_prompt_missing_fence_raises():
    with pytest.raises(PromptExtractionError):
        extract_prompt("## Prompt\n\nplain text only, no fence\n")


def test_extract_prompt_tolerates_language_hint_on_fence():
    md = "## Prompt\n\n```text\nhello\n```\n"
    assert extract_prompt(md) == "hello"


def test_extract_from_file(tmp_path):
    p = tmp_path / "v.md"
    p.write_text(SAMPLE_MD, encoding="utf-8")
    assert extract_from_file(p).startswith("A 16:9")


def test_collect_variants_skips_index_and_sorts(tmp_path):
    (tmp_path / "index.md").write_text("# index", encoding="utf-8")
    (tmp_path / "20260420T111718Z_visualizer_variant-02-b.md").write_text(
        SAMPLE_MD.replace("landscape", "LANDSCAPE-B"), encoding="utf-8"
    )
    (tmp_path / "20260420T111718Z_visualizer_variant-01-a.md").write_text(
        SAMPLE_MD.replace("landscape", "LANDSCAPE-A"), encoding="utf-8"
    )
    results = collect_variants(tmp_path)
    assert len(results) == 2
    # sorted lexically -> 01 before 02
    assert "variant-01" in results[0][0].name
    assert "LANDSCAPE-A" in results[0][1]
    assert "LANDSCAPE-B" in results[1][1]


def test_collect_variants_missing_dir_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        collect_variants(tmp_path / "nope")


def test_collect_variants_empty_dir_raises(tmp_path):
    with pytest.raises(PromptExtractionError):
        collect_variants(tmp_path)
