"""Generation utilities — AWS Bedrock backend only."""

import asyncio
import logging
import os
from typing import List, Dict, Any

from utils.bedrock_client import BedrockClient, BedrockInvocationError

logger = logging.getLogger(__name__)

_BEDROCK_PREFIXES = (
    "anthropic.",
    "apac.anthropic.",
    "global.anthropic.",
    "us.anthropic.",
)

# Module-level client, lazily created on first call.
_bedrock_client: BedrockClient | None = None


def _get_bedrock_client() -> BedrockClient:
    global _bedrock_client
    if _bedrock_client is None:
        _bedrock_client = BedrockClient()
    return _bedrock_client


def reinitialize_clients() -> list[str]:
    """No-op compatibility shim — upstream callers may invoke this."""
    global _bedrock_client
    _bedrock_client = None
    logger.info("reinitialize_clients: Bedrock client will be recreated on next call.")
    return ["Bedrock"]


def _contents_to_bedrock_messages(contents: List[Dict[str, Any]]) -> list[dict]:
    """Convert generic content list to Bedrock messages array.

    Only text items are supported.  Image items are silently skipped.
    """
    bedrock_content: list[dict] = []
    for item in contents:
        if item.get("type") == "text":
            bedrock_content.append({"type": "text", "text": item["text"]})

    if not bedrock_content:
        bedrock_content = [{"type": "text", "text": ""}]

    return [{"role": "user", "content": bedrock_content}]


def _is_bedrock_model(model_name: str) -> bool:
    return any(model_name.startswith(p) for p in _BEDROCK_PREFIXES)


async def call_model_with_retry_async(
    model_name: str,
    contents: list,
    config: dict | None = None,
    max_retries: int = 3,
    **kwargs,
) -> list[str]:
    """Call AWS Bedrock and return a list of assistant text responses.

    For single-shot calls this returns a 1-element list.

    Args:
        model_name: Must start with one of: anthropic., apac.anthropic.,
                    global.anthropic., us.anthropic.
        contents:   List of dicts with at minimum {"type": "text", "text": "..."}.
        config:     Optional dict with keys: max_tokens, temperature,
                    system_prompt, top_p.
        max_retries: Maximum retry attempts (passed to BedrockClient).

    Returns:
        list[str] of assistant response text(s).

    Raises:
        ValueError: If model_name prefix is not a supported Bedrock prefix.
        BedrockInvocationError: If all retries are exhausted.
    """
    if not _is_bedrock_model(model_name):
        raise ValueError(
            f"Unsupported model '{model_name}'. "
            f"model_name must start with one of: {_BEDROCK_PREFIXES}"
        )

    cfg = config or {}
    max_tokens: int = int(cfg.get("max_tokens", 4096))
    temperature: float = float(cfg.get("temperature", 0.7))
    system_prompt: str | None = cfg.get("system_prompt") or None
    top_p: float = float(cfg.get("top_p", 0.95))

    messages = _contents_to_bedrock_messages(contents)
    client = _get_bedrock_client()

    # Temporarily override model_id if caller specifies one explicitly.
    original_model_id = client.model_id
    client.model_id = model_name
    try:
        response = await client.invoke_text(
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt,
            top_p=top_p,
        )
    finally:
        client.model_id = original_model_id

    content_blocks = response.get("content", [])
    texts = [
        block["text"]
        for block in content_blocks
        if block.get("type") == "text" and block.get("text")
    ]

    return texts if texts else [""]
