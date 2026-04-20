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
Tests for utils/prompt_md_writer.py
"""

import base64
from pathlib import Path

import pytest

from utils.prompt_md_writer import PLACEHOLDER_JPG_B64, write_prompt_md


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MINIMAL_METADATA = {
    "agent": "test_agent",
    "desc_key": "target_diagram_desc0",
    "aspect_ratio": "16:9",
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_writes_md_file(tmp_path):
    """write_prompt_md must create the .md file and return its absolute path."""
    md_path, _ = write_prompt_md(
        prompt="Draw a neural network diagram.",
        metadata=MINIMAL_METADATA,
        output_dir=tmp_path,
    )
    assert isinstance(md_path, Path), "md_path must be a Path object"
    assert md_path.exists(), f"Expected file to exist at {md_path}"
    assert md_path.suffix == ".md", "Output file must have .md extension"
    assert md_path.is_absolute(), "Returned path must be absolute"


def test_returns_placeholder_b64(tmp_path):
    """The second return value must be the PLACEHOLDER_JPG_B64 constant and
    decode as valid base64."""
    _, placeholder = write_prompt_md(
        prompt="Some prompt.",
        metadata=MINIMAL_METADATA,
        output_dir=tmp_path,
    )
    assert placeholder == PLACEHOLDER_JPG_B64, (
        "Returned base64 must be the module-level PLACEHOLDER_JPG_B64 constant"
    )
    # Must decode without error
    decoded = base64.b64decode(placeholder)
    assert len(decoded) > 0, "Decoded placeholder must not be empty"


def test_filename_includes_agent_and_slug(tmp_path):
    """Filename must contain the agent name and a slug derived from desc_key."""
    metadata = {
        "agent": "visualizer",
        "desc_key": "target_diagram_desc0",
        "aspect_ratio": "1:1",
    }
    md_path, _ = write_prompt_md(
        prompt="Render a pipeline diagram.",
        metadata=metadata,
        output_dir=tmp_path,
    )
    filename = md_path.name
    assert "visualizer" in filename, f"Agent name not found in filename: {filename}"
    # slug is first 40 chars of sanitized desc_key
    assert "target_diagram_desc0" in filename, (
        f"Slug derived from desc_key not found in filename: {filename}"
    )


def test_frontmatter_contains_metadata(tmp_path):
    """The written file must include a YAML frontmatter block with key fields."""
    metadata = {
        "agent": "planner",
        "desc_key": "my_key",
        "aspect_ratio": "4:3",
        "model": "some-bedrock-model",
    }
    md_path, _ = write_prompt_md(
        prompt="Plan a diagram.",
        metadata=metadata,
        output_dir=tmp_path,
    )
    content = md_path.read_text(encoding="utf-8")
    assert content.startswith("---"), "File must start with YAML frontmatter delimiter"
    assert "agent: planner" in content
    assert "aspect_ratio: 4:3" in content
    assert "model: some-bedrock-model" in content
    # Frontmatter must be closed
    lines = content.splitlines()
    assert lines.count("---") >= 2, "Frontmatter must have opening and closing ---"


def test_handles_empty_desc_key(tmp_path):
    """When desc_key is empty, the slug should fall back to the prompt text."""
    metadata = {
        "agent": "vanilla",
        "desc_key": "",
        "aspect_ratio": "1:1",
    }
    md_path, _ = write_prompt_md(
        prompt="Generate a bar chart.",
        metadata=metadata,
        output_dir=tmp_path,
    )
    assert md_path.exists(), "File must be created even when desc_key is empty"
    filename = md_path.name
    # The slug must come from the prompt, not be empty
    assert "vanilla" in filename
    # Slug should contain something from the prompt
    assert len(filename) > len("vanilla") + 20, (
        f"Filename looks too short, likely slug is missing: {filename}"
    )


def test_handles_unicode_prompt(tmp_path):
    """Prompts with Korean characters and emoji must be written without error."""
    unicode_prompt = (
        "한국어 프롬프트 테스트: 이 다이어그램은 신경망을 보여줍니다. "
        "Additional symbols: -- pipeline --> output"
    )
    metadata = {
        "agent": "visualizer",
        "desc_key": "korean_test",
        "aspect_ratio": "16:9",
    }
    md_path, placeholder = write_prompt_md(
        prompt=unicode_prompt,
        metadata=metadata,
        output_dir=tmp_path,
    )
    assert md_path.exists(), "File must be created for unicode prompt"
    content = md_path.read_text(encoding="utf-8")
    assert unicode_prompt in content, "Unicode prompt text must appear in the file"
    assert placeholder == PLACEHOLDER_JPG_B64
