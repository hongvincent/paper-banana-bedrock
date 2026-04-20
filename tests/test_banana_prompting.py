"""Tests for utils.banana_prompting helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from utils import banana_prompting as bp


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    monkeypatch.setenv("BEDROCK_MODEL_ID", "global.anthropic.claude-sonnet-4-6")


@pytest.mark.asyncio
async def test_expand_to_prompt_calls_generation_with_visualizer_system():
    with patch("utils.banana_prompting.call_model_with_retry_async", new_callable=AsyncMock) as mock:
        mock.return_value = ["  expanded prompt body  "]
        out = await bp.expand_to_prompt("a diagram", palette="aws-brand", aspect="16:9")
        assert out == "expanded prompt body"
        call_kwargs = mock.await_args.kwargs
        assert call_kwargs["model_name"].startswith("global.anthropic.")
        assert call_kwargs["config"]["system_prompt"] == bp.VISUALIZER_SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_expand_to_prompt_includes_mode_when_given():
    with patch("utils.banana_prompting.call_model_with_retry_async", new_callable=AsyncMock) as mock:
        mock.return_value = ["x"]
        await bp.expand_to_prompt("a diagram", mode="isometric-depth")
        user_text = mock.await_args.kwargs["contents"][0]["text"]
        assert "Creative direction: isometric-depth" in user_text


@pytest.mark.asyncio
async def test_expand_to_prompt_resolves_palette_key():
    with patch("utils.banana_prompting.call_model_with_retry_async", new_callable=AsyncMock) as mock:
        mock.return_value = ["x"]
        await bp.expand_to_prompt("a diagram", palette="aws-brand")
        user_text = mock.await_args.kwargs["contents"][0]["text"]
        assert "#232F3E" in user_text  # palette resolved to its full definition


@pytest.mark.asyncio
async def test_expand_to_prompt_passes_freeform_palette():
    with patch("utils.banana_prompting.call_model_with_retry_async", new_callable=AsyncMock) as mock:
        mock.return_value = ["x"]
        await bp.expand_to_prompt("a diagram", palette="navy + mint accent")
        user_text = mock.await_args.kwargs["contents"][0]["text"]
        assert "navy + mint accent" in user_text


@pytest.mark.asyncio
async def test_propose_directions_parses_slugged_lines():
    with patch("utils.banana_prompting.call_model_with_retry_async", new_callable=AsyncMock) as mock:
        mock.return_value = [
            "flat-vector: render as flat AWS-brand vectors with no depth\n"
            "isometric-depth: lift each service onto a 30-degree isometric plane\n"
            "hand-drawn: loose blueprint-style sketch on graph paper"
        ]
        out = await bp.propose_directions("desc", count=3)
    assert len(out) == 3
    assert out[0] == ("flat-vector", "render as flat AWS-brand vectors with no depth")
    assert out[1][0] == "isometric-depth"
    assert out[2][0] == "hand-drawn"


@pytest.mark.asyncio
async def test_propose_directions_pads_when_model_returns_fewer():
    with patch("utils.banana_prompting.call_model_with_retry_async", new_callable=AsyncMock) as mock:
        mock.return_value = ["flat: only one line here"]
        out = await bp.propose_directions("desc", count=3)
    assert len(out) == 3
    assert out[0] == ("flat", "only one line here")
    assert out[1][0].startswith("direction-")


@pytest.mark.asyncio
async def test_propose_directions_rejects_zero_count():
    with pytest.raises(ValueError):
        await bp.propose_directions("desc", count=0)


@pytest.mark.asyncio
async def test_propose_directions_tolerates_leading_bullets():
    with patch("utils.banana_prompting.call_model_with_retry_async", new_callable=AsyncMock) as mock:
        mock.return_value = [
            "1. flat: a\n"
            "- isometric: b\n"
            "* sketch: c\n"
        ]
        out = await bp.propose_directions("desc", count=3)
    assert [slug for slug, _ in out] == ["flat", "isometric", "sketch"]
