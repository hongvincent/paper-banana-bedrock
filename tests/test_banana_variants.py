"""Tests for scripts.banana_variants orchestration."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest


def _load_module():
    here = Path(__file__).resolve().parent.parent
    path = here / "scripts" / "banana_variants.py"
    spec = importlib.util.spec_from_file_location("banana_variants", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["banana_variants"] = module
    spec.loader.exec_module(module)
    return module


bv = _load_module()


@pytest.fixture
def run_env(tmp_path, monkeypatch):
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("BEDROCK_MODEL_ID", "global.anthropic.claude-sonnet-4-6")
    return tmp_path


@pytest.mark.asyncio
async def test_run_with_explicit_modes_creates_n_files_plus_index(run_env):
    with patch.object(bv, "expand_to_prompt", new_callable=AsyncMock) as expand:
        expand.side_effect = lambda desc, **kw: f"PROMPT[{kw.get('mode')}]"
        index_path, paths = await bv.run(
            "a diagram",
            count=0,  # ignored when modes given
            modes=["flat-vector", "isometric", "hand-drawn"],
            palette="aws-brand",
            aspect="16:9",
        )
    assert len(paths) == 3
    assert all(p.exists() for p in paths)
    assert index_path.exists()
    assert expand.await_count == 3
    # index.md references all three variants
    index_text = index_path.read_text(encoding="utf-8")
    for slug in ("flat-vector", "isometric", "hand-drawn"):
        assert slug in index_text


@pytest.mark.asyncio
async def test_run_auto_direction_generation(run_env):
    fake_directions = [
        ("flat", "flat vector AWS icons"),
        ("iso", "isometric lift on 30-degree plane"),
        ("sketch", "loose blueprint sketch"),
    ]
    with patch.object(bv, "propose_directions", new_callable=AsyncMock) as directions, \
         patch.object(bv, "expand_to_prompt", new_callable=AsyncMock) as expand:
        directions.return_value = fake_directions
        expand.side_effect = lambda desc, **kw: "P"
        index_path, paths = await bv.run(
            "a diagram",
            count=3,
            modes=None,
            palette="aws-brand",
            aspect="16:9",
        )
    directions.assert_awaited_once()
    assert len(paths) == 3
    assert expand.await_count == 3
    # Each expand call received one of the directive strings
    called_modes = {call.kwargs.get("mode") for call in expand.await_args_list}
    assert called_modes == {d[1] for d in fake_directions}


@pytest.mark.asyncio
async def test_run_parallel_dispatch(run_env):
    """All N expand calls should happen before any completes (asyncio.gather)."""
    import asyncio

    started = 0
    completed = 0
    max_in_flight = 0

    async def fake_expand(desc, **kw):
        nonlocal started, completed, max_in_flight
        started += 1
        max_in_flight = max(max_in_flight, started - completed)
        await asyncio.sleep(0.05)
        completed += 1
        return "P"

    with patch.object(bv, "expand_to_prompt", side_effect=fake_expand):
        await bv.run(
            "a diagram",
            count=0,
            modes=["a", "b", "c"],
            palette="aws-brand",
            aspect="16:9",
        )
    assert max_in_flight >= 2, "variants should run concurrently, not serially"


def test_slugify_handles_special_chars():
    assert bv._slugify("Flat Vector!") == "flat-vector"
    assert bv._slugify("   ---   ") == "variant"
    assert bv._slugify("A" * 100).startswith("a" * 10)
    assert len(bv._slugify("A" * 100)) <= 40
